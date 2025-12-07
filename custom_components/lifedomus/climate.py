"""Climate platform for Lifedomus.

This platform queries the Lifedomus gateway for all thermostats in the
"thermostat" category (CLSID-DEVC-A-CC) and exposes them as Home Assistant
climate entities.

Two operating modes:
 - Direct setpoint thermostat:
    - states: CLSID-STATE-AMBIANT-TEMPERATURE (current temperature),
      CLSID-STATE-SETPOINT-TEMPERATURE (target temperature).
    - min/max allowed target range is derived from the action descriptor of
      prop_clsid CLSID-DEVC-PROP-ENVIRONMENTTHERMOSTAT-VA-GENERALCONST.
    - step is 0.5°C.
    - Turning ON is done by re-sending the target setpoint.
 - Preset-based thermostat:
    - actions on prop_clsid CLSID-DEVC-PROP-ENVIRONMENTTHERMOSTAT-VA-SETPOINT-6POS:
      ANTI-FROST, COMFORT, REDUCED, STOP.
    - STOP maps to HVAC OFF; others map to HVAC HEAT and HW presets.
State handling:
 - If a value is missing in states, the entity remains available with unknown
   value (None), consistent with other platforms.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import html
import logging
import re
from typing import Any, Final
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as ET

from homeassistant.components.climate import (
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_ECO,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant, callback

from .api import (
    LifedomusApi,
    LifedomusApiError,
    build_action_descriptor,
    parse_bool,
    parse_number,
)
from .const import (
    CONF_SITE_KEY,
    CONF_USER_KEY,
    DOMAIN,
    LD_ACTION_OFF,
    LD_ACTION_SETPOINT_6POS_ANTIFROST,
    LD_ACTION_SETPOINT_6POS_COMFORT,
    LD_ACTION_SETPOINT_6POS_ECO,
    LD_ACTION_SETPOINT_6POS_STOP,
    LD_ACTION_VALUE,
    LD_CLSID_DEVICE_TYPE_ACTUATOR_CLIMATECONTROL,
    LD_PROP_THERMOSTAT_SETPOINT,
    LD_PROP_THERMOSTAT_SETPOINT_6POS,
    LD_PROP_THERMOSTAT_STOP,
    LD_STATE_AUTH_HEAT,
    LD_STATE_FAULT_HEAT_TRANSFER,
    LD_STATE_FAULT_TSOC,
    LD_STATE_FAULT_TSR,
    LD_STATE_FAULT_TSSC,
    LD_STATE_FLAG_ANTI_FROST,
    LD_STATE_FLAG_ENTRANCE,
    LD_STATE_FLAG_HEAT_TRANSFER,
    LD_STATE_FLAG_LOAD_SHEDDING,
    LD_STATE_FLAG_PRESENCE,
    LD_STATE_FLAG_TEMPORARY,
    LD_STATE_SETPOINT_6POS,
    LD_STATE_TEMPERATURE_AMBIANT,
    LD_STATE_TEMPERATURE_SETPOINT,
    LD_STATE_THERMOSTAT,
    LD_VALUE_THERMOSTAT_6POS_ANTIFROST,
    LD_VALUE_THERMOSTAT_6POS_COMFORT,
    LD_VALUE_THERMOSTAT_6POS_ECO,
    LD_VALUE_THERMOSTAT_6POS_STOP,
    LD_VALUE_THERMOSTAT_MAX,
    LD_VALUE_THERMOSTAT_MIN,
    LD_VALUE_THERMOSTAT_STEP,
)
from .coordinator import LdCoordinator, LdCoordinatorConfig
from .helpers import EntityDependencies, build_device_info, get_update_interval

_LOGGER = logging.getLogger(__name__)

# HA preset mapping used when operating in 6POS mode.
HA_PRESET_TO_6POS: Final[dict[str, str]] = {
    PRESET_AWAY: LD_ACTION_SETPOINT_6POS_ANTIFROST,
    PRESET_COMFORT: LD_ACTION_SETPOINT_6POS_COMFORT,
    PRESET_ECO: LD_ACTION_SETPOINT_6POS_ECO,
}
_6POS_TO_HA_PRESET: Final[dict[str, str]] = {
    LD_VALUE_THERMOSTAT_6POS_ANTIFROST: PRESET_AWAY,
    LD_VALUE_THERMOSTAT_6POS_COMFORT: PRESET_COMFORT,
    LD_VALUE_THERMOSTAT_6POS_ECO: PRESET_ECO,
    LD_VALUE_THERMOSTAT_6POS_STOP: "",  # STOP is handled as HVAC OFF
}
THERMOSTAT_DIAGNOSTIC_STATES: Final[frozenset[str]] = frozenset(
    {
        LD_STATE_AUTH_HEAT,
        LD_STATE_FAULT_HEAT_TRANSFER,
        LD_STATE_FAULT_TSOC,
        LD_STATE_FAULT_TSR,
        LD_STATE_FAULT_TSSC,
        LD_STATE_FLAG_ANTI_FROST,
        LD_STATE_FLAG_ENTRANCE,
        LD_STATE_FLAG_HEAT_TRANSFER,
        LD_STATE_FLAG_LOAD_SHEDDING,
        LD_STATE_FLAG_PRESENCE,
        LD_STATE_FLAG_TEMPORARY,
    }
)


@dataclass(slots=True)
class _LdClimateDevice:
    """Container for a parsed Lifedomus climate device."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str

    # Operating mode detection flags
    supports_generalconst: bool
    supports_6pos: bool

    # Numeric state values
    current_temperature: float | None
    target_temperature: float | None

    # Current preset, only for 6POS mode
    preset_raw: str | None

    # Running state for direct setpoint devices
    is_heating: bool | None

    # Constraints derived from action descriptor
    min_temp: float | None
    max_temp: float | None

    # Diagnostic boolean states (FLAG/FAULT)
    diagnostic_states: dict[str, bool | None]

    # Availability flag
    available: bool


def _parse_climate_descriptor_limits(
    descriptor_text: str | None,
) -> tuple[float | None, float | None]:
    if not descriptor_text:
        return None, None
    try:
        root = ET.fromstring(html.unescape(descriptor_text))
    except ET.ParseError:
        min_match = re.search(r'min="([0-9]+(?:\.[0-9]+)?)"', descriptor_text)
        max_match = re.search(r'max="([0-9]+(?:\.[0-9]+)?)"', descriptor_text)
        try:
            min_v = float(min_match.group(1)) if min_match else None
            max_v = float(max_match.group(1)) if max_match else None
        except (ValueError, AttributeError):
            return None, None
        return min_v, max_v

    param = root.find(".//parameter[@name='temperature']")
    if param is None:
        return None, None
    min_attr = param.get("min")
    max_attr = param.get("max")
    try:
        return float(min_attr) if min_attr else None, float(
            max_attr
        ) if max_attr else None
    except ValueError:
        return None, None


def _parse_climate_actions_capabilities(
    api: LifedomusApi, dev_el: Element
) -> tuple[bool, bool, float | None, float | None]:
    supports_generalconst = False
    supports_6pos = False
    min_temp: float | None = None
    max_temp: float | None = None

    for action_el in dev_el.findall("./actions/action"):
        prop_clsid = api.txt("prop_clsid", action_el)
        if not prop_clsid:
            continue

        if prop_clsid == LD_PROP_THERMOSTAT_SETPOINT:
            action_clsid = api.txt("action_clsid", action_el)
            if action_clsid == LD_ACTION_VALUE:
                supports_generalconst = True
                descr_el = action_el.find("descriptor")
                if descr_el is not None and descr_el.text:
                    dmin, dmax = _parse_climate_descriptor_limits(descr_el.text)
                    min_temp = dmin if dmin is not None else min_temp
                    max_temp = dmax if dmax is not None else max_temp
            continue

        if prop_clsid == LD_PROP_THERMOSTAT_SETPOINT_6POS:
            supports_6pos = True
            continue

    return supports_generalconst, supports_6pos, min_temp, max_temp


def _parse_climate_states(
    api: LifedomusApi, dev_el: Element
) -> tuple[float | None, float | None, str | None, bool | None, dict[str, bool | None]]:
    """Extract numeric states, preset, heating flag and diagnostic boolean states."""
    current_temperature: float | None = None
    target_temperature: float | None = None
    preset_raw: str | None = None
    is_heating: bool | None = None
    diagnostic_states: dict[str, bool | None] = {}

    states_el = dev_el.find("./states")
    if states_el is None:
        return (
            current_temperature,
            target_temperature,
            preset_raw,
            is_heating,
            diagnostic_states,
        )

    for st_el in states_el.findall("./state"):
        state_clsid = api.txt("state_clsid", st_el)
        if not state_clsid:
            continue

        val_txt = api.txt_path(st_el, "./values/value/value")

        if state_clsid in (LD_STATE_TEMPERATURE_AMBIANT, LD_STATE_TEMPERATURE_SETPOINT):
            if val_txt is None:
                continue
            val = parse_number(val_txt)
            if state_clsid == LD_STATE_TEMPERATURE_AMBIANT:
                current_temperature = val
            else:
                target_temperature = val
            continue

        if state_clsid == LD_STATE_SETPOINT_6POS:
            if val_txt is not None:
                preset_raw = val_txt.strip().upper() or None
            continue

        if state_clsid == LD_STATE_THERMOSTAT:
            if val_txt is not None:
                is_heating = parse_bool(val_txt)
            continue

        if state_clsid in THERMOSTAT_DIAGNOSTIC_STATES:
            if val_txt is not None:
                diagnostic_states[state_clsid] = parse_bool(val_txt)
            continue

    return (
        current_temperature,
        target_temperature,
        preset_raw,
        is_heating,
        diagnostic_states,
    )


def _parse_climate_device_element(
    api: LifedomusApi, dev_el: Element
) -> _LdClimateDevice | None:
    device_key = api.txt("device_key", dev_el)
    if not device_key:
        return None

    device_clsid = api.txt("device_clsid", dev_el)
    label = api.txt("label", dev_el) or device_key
    room_label = api.txt("room_label", dev_el)

    supports_generalconst, supports_6pos, min_temp, max_temp = (
        _parse_climate_actions_capabilities(api, dev_el)
    )
    (
        current_temperature,
        target_temperature,
        preset_raw,
        is_heating,
        diagnostic_states,
    ) = _parse_climate_states(api, dev_el)

    return _LdClimateDevice(
        device_key=device_key,
        device_clsid=device_clsid,
        label=label,
        room_label=room_label,
        supports_generalconst=supports_generalconst,
        supports_6pos=supports_6pos,
        current_temperature=current_temperature,
        target_temperature=target_temperature,
        preset_raw=preset_raw,
        is_heating=is_heating,
        min_temp=min_temp,
        max_temp=max_temp,
        diagnostic_states=diagnostic_states,
        available=True,
    )


class LifedomusClimate(ClimateEntity):
    """Lifedomus climate entity."""

    _attr_should_poll = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_target_temperature_step = LD_VALUE_THERMOSTAT_STEP

    def __init__(
        self,
        coordinator: LdCoordinator[_LdClimateDevice],
        device: _LdClimateDevice,
        dependencies: EntityDependencies,
    ) -> None:
        """Initialize the climate entity and attach the coordinator by composition."""
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

        self._supports_generalconst = False
        self._supports_6pos = False

        self._apply_device_snapshot(device)

    def _apply_device_snapshot(self, device: _LdClimateDevice) -> None:
        """Apply the coordinator snapshot to HA attributes."""
        self._attr_name = device.label
        self._attr_current_temperature = device.current_temperature
        self._attr_target_temperature = device.target_temperature
        self._supports_generalconst = device.supports_generalconst
        self._supports_6pos = device.supports_6pos

        # Min/max allowed target temps when available.
        self._attr_min_temp = (
            device.min_temp if device.min_temp is not None else LD_VALUE_THERMOSTAT_MIN
        )
        self._attr_max_temp = (
            device.max_temp if device.max_temp is not None else LD_VALUE_THERMOSTAT_MAX
        )

        # Compute supported features from capabilities.
        feats = ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        if self._supports_generalconst:
            feats |= ClimateEntityFeature.TARGET_TEMPERATURE
        if self._supports_6pos:
            feats |= ClimateEntityFeature.PRESET_MODE
        self._attr_supported_features = feats

        # HVAC mode inference:
        # - 6POS: STOP -> OFF, otherwise HEAT.
        # - Direct setpoint: use boolean CLSID-STATE-THERMOSTAT when available.
        if self._supports_6pos:
            if device.preset_raw == "STOP":
                self._attr_hvac_mode = HVACMode.OFF
            else:
                self._attr_hvac_mode = HVACMode.HEAT
        elif device.is_heating is True:
            self._attr_hvac_mode = HVACMode.HEAT
        elif device.is_heating is False:
            self._attr_hvac_mode = HVACMode.OFF
        else:
            # Fallback when no explicit boolean state is provided
            self._attr_hvac_mode = HVACMode.HEAT

        # Preset mode mapping for 6POS devices.
        if self._supports_6pos and device.preset_raw:
            self._attr_preset_mode = _6POS_TO_HA_PRESET.get(device.preset_raw) or None
            self._attr_preset_modes = [PRESET_AWAY, PRESET_COMFORT, PRESET_ECO]
        else:
            self._attr_preset_mode = None
            self._attr_preset_modes = None

    @property
    def _dev(self) -> _LdClimateDevice | None:
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

    @property
    def extra_state_attributes(self) -> dict[str, bool | None]:
        """Expose diagnostic FLAG and FAULT states as entity attributes with simplified keys."""
        device = self._dev
        if device is None:
            return {}

        result: dict[str, bool | None] = {}
        for clsid, value in device.diagnostic_states.items():
            if clsid.startswith("CLSID-STATE-"):
                key = clsid[12:]  # Remove "CLSID-STATE-" prefix
            else:
                key = clsid
            result[key.lower().replace("-", "_")] = value
        return result

    async def async_added_to_hass(self) -> None:
        """Register coordinator update listener and publish initial state."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        if self._dev is not None:
            self._apply_device_snapshot(self._dev)
        self.async_write_ha_state()

    async def _async_send_setpoint(self, temp: float, *, set_hvac_heat: bool) -> None:
        """Send the GENERALCONST setpoint via a single ExecuteOneAction call.

        This method centralizes:
         - clamping and stepping,
         - optimistic HA state update (target temp and optional HVAC HEAT),
         - ExecuteOneAction call with VALUE on GENERALCONST,
         - instant state refresh.
        """
        if not self._supports_generalconst or self._attr_unique_id is None:
            return

        # Optimistic update
        # Clamp to allowed range and step to allowed increments
        self._attr_target_temperature = max(
            self.min_temp,
            min(self.max_temp, round(temp * 2) / 2),  # step of 0.5
        )
        if set_hvac_heat:
            self._attr_hvac_mode = HVACMode.HEAT
        self.async_write_ha_state()

        try:
            await self.coordinator.api.async_execute_one_action(
                site_key=self._site_key,
                user_key=self._user_key,
                target_key=self._attr_unique_id,
                prop_clsid=LD_PROP_THERMOSTAT_SETPOINT,
                action_clsid=LD_ACTION_VALUE,
                descriptor=build_action_descriptor(
                    {"temperature": self._attr_target_temperature}
                ),
            )
        except LifedomusApiError as err:
            _LOGGER.warning(
                "Failed to set temperature for %s: %s", self._attr_unique_id, err
            )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature for general-const capable devices."""
        if not self._supports_generalconst:
            return

        temperature = kwargs.get("temperature")
        if temperature is None:
            return

        try:
            temp = float(temperature)
        except (TypeError, ValueError):
            return

        await self._async_send_setpoint(temp, set_hvac_heat=True)

    async def async_turn_on(self) -> None:
        """Handle climate.turn_on by switching HVAC to HEAT using the same path as the UI."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Handle climate.turn_off by switching HVAC to OFF using the same path as the UI."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set a preset in 6POS mode."""
        if not self._supports_6pos or self._attr_unique_id is None:
            return

        # STOP is not a preset; handled via HVAC OFF.
        action = HA_PRESET_TO_6POS.get(preset_mode)
        if not action:
            return

        # Optimistic update
        self._attr_preset_mode = preset_mode
        self._attr_hvac_mode = HVACMode.HEAT
        self.async_write_ha_state()

        try:
            await self.coordinator.api.async_execute_one_action(
                site_key=self._site_key,
                user_key=self._user_key,
                target_key=self._attr_unique_id,
                prop_clsid=LD_PROP_THERMOSTAT_SETPOINT_6POS,
                action_clsid=action,
            )
        except LifedomusApiError as err:
            _LOGGER.warning(
                "Failed to set preset for %s: %s", self._attr_unique_id, err
            )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode using STOP or by re-sending the setpoint value on direct setpoint devices."""
        if self._attr_unique_id is None:
            return

        if hvac_mode == HVACMode.OFF:
            # Prefer 6POS STOP when available; otherwise use STOP property.
            try:
                if self._supports_6pos:
                    await self.coordinator.api.async_execute_one_action(
                        site_key=self._site_key,
                        user_key=self._user_key,
                        target_key=self._attr_unique_id,
                        prop_clsid=LD_PROP_THERMOSTAT_SETPOINT_6POS,
                        action_clsid=LD_ACTION_SETPOINT_6POS_STOP,
                    )
                else:
                    await self.coordinator.api.async_execute_one_action(
                        site_key=self._site_key,
                        user_key=self._user_key,
                        target_key=str(self._attr_unique_id),
                        prop_clsid=LD_PROP_THERMOSTAT_STOP,
                        prop_numr=0,
                        action_clsid=LD_ACTION_OFF,
                    )
            except LifedomusApiError as err:
                _LOGGER.warning(
                    "Failed to set HVAC OFF for %s: %s", self._attr_unique_id, err
                )

            # Optimistic state change
            self._attr_hvac_mode = HVACMode.OFF
            self.async_write_ha_state()
            return

        if hvac_mode == HVACMode.HEAT:
            if self._supports_6pos:
                # For 6POS devices, use COMFORT as default when turning on.
                await self.async_set_preset_mode(PRESET_COMFORT)
                return

            if self._supports_generalconst:
                # Use current known target or clamp a fallback value.
                temp = (
                    self._attr_target_temperature
                    if self._attr_target_temperature is not None
                    else (self._dev.target_temperature if self._dev else None)
                )
                if temp is None:
                    temp = self.min_temp

                await self._async_send_setpoint(float(temp), set_hvac_heat=True)
                return

            # If neither 6POS nor GENERALCONST are supported, nothing to do.
            return


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Callable[[list[ClimateEntity]], None],
) -> None:
    """Set up the Lifedomus climate platform from a config entry."""

    api: LifedomusApi = entry.runtime_data

    cfg = LdCoordinatorConfig[_LdClimateDevice](
        name="Lifedomus climate coordinator",
        update_interval=get_update_interval(entry),
        category_clsid=LD_CLSID_DEVICE_TYPE_ACTUATOR_CLIMATECONTROL,
        parse_device=_parse_climate_device_element,
    )
    coordinator = LdCoordinator(hass, api, cfg)
    await coordinator.async_config_entry_first_refresh()

    # Share the coordinator for potential reuse if needed.
    hass.data.setdefault(DOMAIN, {})["climate_coordinator"] = coordinator

    dependencies = EntityDependencies(
        api=api, entry=entry, uuid=str(hass.data[DOMAIN].get("uuid", ""))
    )

    entities: list[ClimateEntity] = [
        LifedomusClimate(coordinator, dev, dependencies)
        for dev in coordinator.data.values()
    ]

    async_add_entities(entities)
