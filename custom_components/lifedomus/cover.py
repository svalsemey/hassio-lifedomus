"""Cover platform for Lifedomus.

This platform queries the Lifedomus gateway for all shutter/motor devices in the
"motor" category (CLSID-DEVC-A-MO) and exposes them as Home Assistant cover entities.
Supported operations:
 - Open/Close.
 - Stop.
 - Set exact position.
State mapping:
 - The numeric state 'CLSID-STATE-POSITION-PERCENTAGE' is inverted compared to Home Assistant:
   HA 100% (open) corresponds to 0% in Lifedomus, and HA 0% (closed) to 100% in Lifedomus.
 - If no <value> exists under <state>, the entity remains available but its position is unknown
   (current_cover_position=None, assumed_state=True).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Any
from xml.etree.ElementTree import Element

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .api import LifedomusApi, LifedomusApiError, build_action_descriptor
from .const import (
    CONF_SITE_KEY,
    CONF_USER_KEY,
    DOMAIN,
    LD_ACTION_DOWN,
    LD_ACTION_STOP,
    LD_ACTION_UP,
    LD_ACTION_VALUE,
    LD_CLSID_DEVICE_TYPE_ACTUATOR_MOTOR,
    LD_PROP_MOTOR_SW_STOP,
    LD_PROP_MOTOR_UD,
    LD_PROP_MOTOR_VA_POS,
    LD_STATE_POSITION_PERCENTAGE,
)
from .coordinator import LdCoordinator, LdCoordinatorConfig
from .helpers import EntityDependencies, build_device_info, get_update_interval

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class _LdCoverDevice:
    """Container for a parsed Lifedomus motor device."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str
    position_ha: (
        int | None
    )  # None means unknown; 0..100 uses HA semantics (0=closed, 100=open)


def _parse_cover_device_element(
    api: LifedomusApi, dev_el: Element
) -> _LdCoverDevice | None:
    """Parse a <device> element into a cover snapshot with HA-inverted position."""
    device_key = api.txt("device_key", dev_el)
    if not device_key:
        return None

    device_clsid = api.txt("device_clsid", dev_el)
    label = api.txt("label", dev_el) or device_key
    room_label = api.txt("room_label", dev_el)

    states_el = dev_el.find("./states")
    if states_el is None or states_el.find(".//value") is None:
        return _LdCoverDevice(
            device_key=device_key,
            device_clsid=device_clsid,
            label=label,
            room_label=room_label,
            position_ha=None,
        )

    position_ha: int | None = None
    for st_el in states_el.findall("./state"):
        state_clsid = api.txt("state_clsid", st_el)
        if state_clsid != LD_STATE_POSITION_PERCENTAGE:
            continue
        val_txt = api.txt_path(st_el, "./values/value/value")
        if val_txt is None:
            continue
        try:
            ld_position = max(0, min(100, int(val_txt)))
            position_ha = 100 - ld_position
        except ValueError:
            position_ha = None
        break

    return _LdCoverDevice(
        device_key=device_key,
        device_clsid=device_clsid,
        label=label,
        room_label=room_label,
        position_ha=position_ha,
    )


class LifedomusCover(CoverEntity):
    """Lifedomus shutter/cover entity."""

    _attr_should_poll = False
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )
    _attr_device_class = CoverDeviceClass.SHUTTER

    def __init__(
        self,
        coordinator: LdCoordinator[_LdCoverDevice],
        device: _LdCoverDevice,
        dependencies: EntityDependencies,
    ) -> None:
        """Initialize the cover entity and attach the coordinator by composition."""
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

    def _apply_device_snapshot(self, device: _LdCoverDevice) -> None:
        """Apply the coordinator snapshot to HA attributes."""
        self._attr_name = device.label
        self._attr_current_cover_position = device.position_ha
        if device.position_ha is None:
            # Unknown position; keep entity available with assumed state.
            self._attr_is_closed = None
            self._attr_assumed_state = True
        else:
            self._attr_is_closed = device.position_ha == 0
            self._attr_assumed_state = False

    @property
    def _dev(self) -> _LdCoverDevice | None:
        """Return the current device snapshot from the coordinator."""
        if self._attr_unique_id is None:
            return None
        return self.coordinator.data.get(self._attr_unique_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle state update from the coordinator."""
        if self._dev is not None:
            self._apply_device_snapshot(self._dev)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register coordinator update listener and publish initial state."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        if self._dev is not None:
            self._apply_device_snapshot(self._dev)
        self.async_write_ha_state()

    async def _async_refresh_instant_state(self) -> None:
        """Fetch and apply instant state for this device using GetDeviceState."""
        if self._attr_unique_id is None:
            return

        updated = await self.coordinator.async_fetch_device_snapshot(
            self._attr_unique_id
        )
        if updated is None:
            _LOGGER.debug(
                "Instant state fetch returned no data for %s", self._attr_unique_id
            )
            return

        self._apply_device_snapshot(updated)
        self.async_write_ha_state()

        self.coordinator.data[self._attr_unique_id] = updated

    async def async_open_cover(self, **_kwargs: Any) -> None:
        """Open the cover using UP action on MOTOR-UD."""
        if not self._dev or not self._attr_unique_id:
            return

        # Optimistic update
        self._attr_is_closed = False
        self._attr_current_cover_position = 100
        self._attr_assumed_state = True
        self.async_write_ha_state()

        try:
            await self.coordinator.api.async_execute_one_action(
                target_key=self._attr_unique_id,
                prop_clsid=LD_PROP_MOTOR_UD,
                action_clsid=LD_ACTION_UP,
            )
        except LifedomusApiError as err:
            _LOGGER.warning(
                "Failed to execute UP action for %s: %s", self._attr_unique_id, err
            )

    async def async_close_cover(self, **_kwargs: Any) -> None:
        """Close the cover using DOWN action on MOTOR-UD."""
        if not self._dev or not self._attr_unique_id:
            return

        # Optimistic update
        self._attr_is_closed = True
        self._attr_current_cover_position = 0
        self._attr_assumed_state = True
        self.async_write_ha_state()

        try:
            await self.coordinator.api.async_execute_one_action(
                target_key=self._attr_unique_id,
                prop_clsid=LD_PROP_MOTOR_UD,
                action_clsid=LD_ACTION_DOWN,
            )
        except LifedomusApiError as err:
            _LOGGER.warning(
                "Failed to execute DOWN action for %s: %s",
                self._attr_unique_id,
                err,
            )

    async def async_stop_cover(self, **_kwargs: Any) -> None:
        """Stop the cover using STOP on MOTOR-SW-STOP."""
        if not self._dev or not self._attr_unique_id:
            return

        try:
            await self.coordinator.api.async_execute_one_action(
                target_key=self._attr_unique_id,
                prop_clsid=LD_PROP_MOTOR_SW_STOP,
                action_clsid=LD_ACTION_STOP,
            )
        except LifedomusApiError as err:
            _LOGGER.warning(
                "Failed to execute STOP action for %s: %s",
                self._attr_unique_id,
                err,
            )

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the cover position using VALUE on MOTOR-VA-POS (with inverted mapping)."""
        if not self._dev or not self._attr_unique_id:
            return

        ha_position = int(kwargs.get(ATTR_POSITION, 0))
        ha_position = max(0, min(100, ha_position))
        ld_position = 100 - ha_position  # Inversion HA -> Lifedomus

        # Optimistic update
        self._attr_current_cover_position = ha_position
        self._attr_is_closed = ha_position == 0
        self._attr_assumed_state = True
        self.async_write_ha_state()

        try:
            await self.coordinator.api.async_execute_one_action(
                target_key=self._attr_unique_id,
                prop_clsid=LD_PROP_MOTOR_VA_POS,
                action_clsid=LD_ACTION_VALUE,
                descriptor=build_action_descriptor({"position": ld_position}),
            )
        except LifedomusApiError as err:
            _LOGGER.warning(
                "Failed to execute VALUE action for %s: %s",
                self._attr_unique_id,
                err,
            )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Callable[[list[CoverEntity]], None],
) -> None:
    """Set up the Lifedomus cover platform from a config entry."""
    api: LifedomusApi = entry.runtime_data

    cfg = LdCoordinatorConfig[_LdCoverDevice](
        name="Lifedomus cover coordinator",
        update_interval=get_update_interval(entry),
        category_clsid=LD_CLSID_DEVICE_TYPE_ACTUATOR_MOTOR,
        parse_device=_parse_cover_device_element,
    )
    coordinator = LdCoordinator(hass, api, cfg)
    await coordinator.async_config_entry_first_refresh()

    # Share the coordinator for potential reuse.
    hass.data.setdefault(DOMAIN, {})["cover_coordinator"] = coordinator

    dependencies = EntityDependencies(
        api=api, entry=entry, uuid=str(hass.data.setdefault(DOMAIN, {}).get("uuid", ""))
    )

    entities: list[CoverEntity] = [
        LifedomusCover(coordinator, dev, dependencies)
        for dev in coordinator.data.values()
    ]

    async_add_entities(entities)
