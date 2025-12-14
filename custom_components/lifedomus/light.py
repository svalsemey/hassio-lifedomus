"""Light platform for Lifedomus.

This platform queries the Lifedomus gateway for all lights in the "light" category
(CLSID-DEVC-A-EC) and exposes them as Home Assistant light entities. It supports
two device kinds based on their available actions:
 - Dimmable lights (presence of prop_clsid: CLSID-DEVC-PROP-DIMMER-VA-POS)
 - On/off (TOR) lights (no dimmer value action present)

Behavior when state is missing:
 - If no <value> exists in <states>, the entity remains available but its state is unknown
   (is_on=None, assumed_state=True; brightness=None for dimmers).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any, Final
from xml.etree.ElementTree import Element

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .api import LifedomusApi, LifedomusApiError, build_action_descriptor
from .const import (
    CONF_SITE_KEY,
    CONF_USER_KEY,
    DOMAIN,
    LD_ACTION_OFF,
    LD_ACTION_ON,
    LD_ACTION_VALUE,
    LD_CLSID_DEVICE_TYPE_ACTUATOR_LIGHT,
    LD_PROP_DIMMER_SW,
    LD_PROP_DIMMER_VA_POS,
    LD_PROP_TOR_SW,
    LD_STATE_LIGHT,
    LD_STATE_POSITION_PERCENTAGE,
    LD_STATE_SOCKET,
)
from .coordinator import LdCoordinator, LdCoordinatorConfig
from .helpers import EntityDependencies, build_device_info, get_update_interval

_LOGGER = logging.getLogger(__name__)

# CLSIDs with a binary state (true/false)
LIGHTS_ONOFF: Final[set[str]] = {
    LD_STATE_LIGHT,
    LD_STATE_SOCKET,
}


@dataclass(slots=True)
class _LdLightDevice:
    """Container for a parsed Lifedomus light device."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str
    is_dimmer: bool
    is_on: bool | None
    brightness_pct: int | None  # 0..100; None means unknown
    available: bool


def _parse_light_actions_capabilities(api: LifedomusApi, dev_el: Element) -> bool:
    """Return True when the device supports dimmer VALUE action."""
    for action_el in dev_el.findall("./actions/action"):
        prop_clsid = api.txt("prop_clsid", action_el)
        if prop_clsid == LD_PROP_DIMMER_VA_POS:
            return True
    return False


def _parse_light_states(
    api: LifedomusApi, dev_el: Element, is_dimmer: bool
) -> tuple[bool | None, int | None]:
    """Extract on/off and brightness percentage from <states>, handling both kinds."""
    states_el = dev_el.find("./states")
    if states_el is None or states_el.find(".//value") is None:
        return None, None

    bool_state: bool | None = None
    pct: int | None = None

    for st_el in states_el.findall("./state"):
        state_clsid = api.txt("state_clsid", st_el)
        val_txt_raw = api.txt_path(st_el, "./values/value/value")
        val_txt = val_txt_raw.lower() if val_txt_raw else None
        if not val_txt:
            continue

        if (
            bool_state is None
            and state_clsid in {LD_STATE_LIGHT, LD_STATE_SOCKET}
            and val_txt in ("true", "false")
        ):
            bool_state = val_txt == "true"

        if is_dimmer and pct is None and state_clsid == LD_STATE_POSITION_PERCENTAGE:
            try:
                pct_val = int(val_txt)
                pct = max(0, min(100, pct_val))
            except ValueError:
                pass

        if (bool_state is not None) and (not is_dimmer or pct is not None):
            break

    if is_dimmer:
        brightness_pct: int | None = pct
        is_on: bool | None
        if pct is not None:
            is_on = (pct > 0) if bool_state is None else bool_state
        else:
            is_on = bool_state
        return is_on, brightness_pct

    if bool_state is None:
        return None, None
    return bool_state, (100 if bool_state else 0)


def _parse_light_device_element(
    api: LifedomusApi, dev_el: Element
) -> _LdLightDevice | None:
    """Parse a <device> element returned by GetDevicesFromCatg into a device snapshot."""
    device_key = api.txt("device_key", dev_el)
    if not device_key:
        return None

    device_clsid = api.txt("device_clsid", dev_el)
    label = api.txt("label", dev_el) or device_key
    room_label = api.txt("room_label", dev_el)

    is_dimmer = _parse_light_actions_capabilities(api, dev_el)
    is_on, brightness_pct = _parse_light_states(api, dev_el, is_dimmer)

    return _LdLightDevice(
        device_key=device_key,
        device_clsid=device_clsid,
        label=label,
        room_label=room_label,
        is_dimmer=is_dimmer,
        is_on=is_on,
        brightness_pct=brightness_pct,
        available=True,
    )


class _LdBaseLight(LightEntity):
    """Base HA light for Lifedomus."""

    _attr_should_poll = False

    def __init__(
        self,
        coordinator: LdCoordinator[_LdLightDevice],
        device: _LdLightDevice,
        dependencies: EntityDependencies,
    ) -> None:
        """Initialize the entity and attach the coordinator by composition."""
        super().__init__()
        self.coordinator = coordinator
        self._api = dependencies.api
        self._site_key = str(dependencies.entry.data.get(CONF_SITE_KEY))
        self._user_key = str(dependencies.entry.data.get(CONF_USER_KEY))

        self._attr_unique_id = device.device_key
        self._attr_name = device.label

        self._attr_device_info = build_device_info(
            device_key=device.device_key,
            device_clsid=device.device_clsid,
            label=self._attr_name,
            room_label=device.room_label,
            uuid=dependencies.uuid,
        )

        self._apply_device_snapshot(device)

    async def async_added_to_hass(self) -> None:
        """Register coordinator update listener and publish initial state."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )

        device = (
            self.coordinator.data.get(self._attr_unique_id)
            if self._attr_unique_id
            else None
        )
        if device is not None:
            self._apply_device_snapshot(device)
            self._attr_available = device.available
        self.async_write_ha_state()

    def _apply_device_snapshot(self, device: _LdLightDevice) -> None:
        """Apply the coordinator snapshot to HA attributes."""
        self._attr_name = device.label
        # is_on must always be bool for HA. When unknown, default to False and mark as assumed
        if device.is_on is None:
            self._attr_is_on = False
            self._attr_assumed_state = True
            self._attr_icon = "mdi:lightbulb-question"
        else:
            self._attr_is_on = device.is_on
            self._attr_assumed_state = False
            self._attr_icon = None

    @property
    def _dev(self) -> _LdLightDevice | None:
        """Return the current device snapshot from the coordinator."""
        if self._attr_unique_id is None:
            return None
        return self.coordinator.data.get(self._attr_unique_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle state update from the coordinator."""
        if self._dev is not None:
            self._apply_device_snapshot(self._dev)
            self._attr_available = self._dev.available
        self.async_write_ha_state()


class LifedomusTorLight(_LdBaseLight):
    """On/off (TOR) Lifedomus light."""

    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Turn on the TOR light."""
        if not self._dev:
            return

        self._attr_is_on = True
        self._attr_assumed_state = False
        # When state becomes known, clear custom icon to let HA use the default
        self._attr_icon = None
        self.async_write_ha_state()

        try:
            await self.coordinator.api.async_execute_one_action(
                target_key=str(self._attr_unique_id),
                prop_clsid=LD_PROP_TOR_SW,
                prop_numr=0,
                action_clsid=LD_ACTION_ON,
            )
        except LifedomusApiError as err:
            _LOGGER.warning(
                "Failed to execute ON action for %s: %s", self._attr_unique_id, err
            )

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off the TOR light."""
        if not self._dev or not self._attr_unique_id:
            return

        self._attr_is_on = False
        self._attr_assumed_state = False
        # When state becomes known, clear custom icon to let HA use the default
        self._attr_icon = None
        self.async_write_ha_state()

        try:
            await self.coordinator.api.async_execute_one_action(
                target_key=self._attr_unique_id,
                prop_clsid=LD_PROP_TOR_SW,
                action_clsid=LD_ACTION_OFF,
            )
        except LifedomusApiError as err:
            _LOGGER.warning(
                "Failed to execute OFF action for %s: %s", self._attr_unique_id, err
            )


class LifedomusDimmerLight(_LdBaseLight):
    """Dimmable Lifedomus light."""

    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS

    def _apply_device_snapshot(self, device: _LdLightDevice) -> None:
        """Apply snapshot, including brightness mapping for dimmers."""
        super()._apply_device_snapshot(device)
        self._attr_brightness = (
            None
            if device.brightness_pct is None
            else round(device.brightness_pct * 255 / 100)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the dimmer, optionally setting brightness."""
        if not self._dev or not self._attr_unique_id:
            return

        self._attr_is_on = True
        # When state becomes known, clear custom icon to let HA use the default
        self._attr_icon = None
        self.async_write_ha_state()

        if ATTR_BRIGHTNESS in kwargs:
            try:
                bri = int(kwargs[ATTR_BRIGHTNESS])
            except (TypeError, ValueError):
                bri = 255
            bri = max(0, min(255, bri))
            percentage = max(0, min(100, round(bri * 100 / 255)))

            self._attr_is_on = percentage > 0
            self._attr_brightness = round(percentage * 255 / 100)
            self.async_write_ha_state()

            try:
                await self.coordinator.api.async_execute_one_action(
                    target_key=self._attr_unique_id,
                    prop_clsid=LD_PROP_DIMMER_VA_POS,
                    action_clsid=LD_ACTION_VALUE,
                    descriptor=build_action_descriptor({"percentage": percentage}),
                )
            except LifedomusApiError as err:
                _LOGGER.warning(
                    "Failed to execute VALUE action for %s: %s",
                    self._attr_unique_id,
                    err,
                )
        else:
            self._attr_is_on = True
            self._attr_assumed_state = False
            # Icon remains cleared (known state)
            self._attr_icon = None
            self.async_write_ha_state()
            try:
                await self.coordinator.api.async_execute_one_action(
                    target_key=self._attr_unique_id,
                    prop_clsid=LD_PROP_DIMMER_SW,
                    action_clsid=LD_ACTION_ON,
                )
            except LifedomusApiError as err:
                _LOGGER.warning(
                    "Failed to execute ON action for %s: %s",
                    self._attr_unique_id,
                    err,
                )

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off the dimmer."""
        if not self._dev or not self._attr_unique_id:
            return

        self._attr_is_on = False
        self._attr_assumed_state = False
        self._attr_brightness = 0
        # Known state -> clear custom icon to let HA use the default
        self._attr_icon = None
        self.async_write_ha_state()

        try:
            await self.coordinator.api.async_execute_one_action(
                target_key=self._attr_unique_id,
                prop_clsid=LD_PROP_DIMMER_SW,
                action_clsid=LD_ACTION_OFF,
            )
        except LifedomusApiError as err:
            _LOGGER.warning(
                "Failed to execute OFF action for %s: %s", self._attr_unique_id, err
            )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Callable[[list[LightEntity]], None],
) -> None:
    """Set up the Lifedomus light platform from a config entry."""
    api: LifedomusApi = entry.runtime_data

    cfg = LdCoordinatorConfig[_LdLightDevice](
        name="Lifedomus light coordinator",
        update_interval=get_update_interval(entry),
        category_clsid=LD_CLSID_DEVICE_TYPE_ACTUATOR_LIGHT,
        parse_device=_parse_light_device_element,
    )
    coordinator = LdCoordinator(hass, api, cfg)
    await coordinator.async_config_entry_first_refresh()

    # Share the coordinator so the button platform can reuse it.
    hass.data.setdefault(DOMAIN, {})["light_coordinator"] = coordinator

    dependencies = EntityDependencies(
        api=api, entry=entry, uuid=str(hass.data.setdefault(DOMAIN, {}).get("uuid", ""))
    )

    entities: list[LightEntity] = [
        (LifedomusDimmerLight if device.is_dimmer else LifedomusTorLight)(
            coordinator, device, dependencies
        )
        for device in coordinator.data.values()
    ]

    async_add_entities(entities)
