"""Climate platform for Lifedomus.

This platform queries the Lifedomus gateway for all devices in the climate
control category (CLSID-DEVC-A-CC) and exposes thermostats as Home Assistant
climate entities.

Capabilities are detected from the <actions> block of each device:
 - Direct setpoint: CLSID-ACTION-VALUE on
   CLSID-DEVC-PROP-ENVIRONMENTTHERMOSTAT-VA-GENERALCONST; the allowed range is
   read from the action descriptor and the step is 0.5 °C.
 - Preset family, one of two mutually exclusive properties:
    * 6POS (CLSID-DEVC-PROP-ENVIRONMENTTHERMOSTAT-VA-SETPOINT-6POS): ANTI-FROST,
      COMFORT, REDUCED and STOP actions; STOP maps to HVAC OFF.
    * HEATMODE (CLSID-DEVC-PROP-ENVIRONMENTTHERMOSTAT-VA-HEATMODE): COMFORT,
      REDUCED, ECONOMIC and FROST actions. The family has no off position and
      the reported state values differ from the action names, hence explicit
      lookup tables in both directions.
 - On/off switch: CLSID-ACTION-ON / CLSID-ACTION-OFF on a known switch property
   (regulation switch of virtual thermostats, stop property of direct setpoint
   devices).

HVAC OFF, together with the TURN_ON / TURN_OFF features, is only advertised when
the device exposes a way to switch off (preset off action or switch property);
otherwise the entity is heat-only and reports HEAT regardless of its flags.

Device specifics:
 - Floor heating devices (CLSID-DEVC-A-CC15) only report the boolean state
   CLSID-STATE-DEVC-FLOOR-HEATING and expose no actuator; they are parsed by
   the shared climate coordinator but exposed by the binary_sensor platform.
 - Virtual thermostats (CLSID-DEVC-A-CC16) report CLSID-STATE-REGULATION-ON
   (drives the HVAC mode), CLSID-STATE-THERMOSTAT (drives the HVAC action) and
   CLSID-STATE-THERMOSTAT-THERM-MODE (exposed as an entity attribute).

State handling:
 - Temperature and heating states accept several CLSID aliases; the first
   non-empty value wins.
 - A missing or empty value leaves the matching attribute unknown (None) while
   the entity stays available, consistent with other platforms.
 - On preset-based devices the reported setpoint follows the active preset and
   may change without any command from Home Assistant.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import html
import re
from typing import Any, Final
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as ET

from homeassistant.components.climate import (
    PRESET_AWAY,
    PRESET_COMFORT,
    PRESET_ECO,
    PRESET_HOME,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, Platform, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import LifedomusApi, build_action_descriptor, parse_bool, parse_number
from .const import (
    DOMAIN,
    LD_ACTION_HEATMODE_COMFORT,
    LD_ACTION_HEATMODE_ECONOMIC,
    LD_ACTION_HEATMODE_FROST,
    LD_ACTION_HEATMODE_REDUCED,
    LD_ACTION_OFF,
    LD_ACTION_ON,
    LD_ACTION_SETPOINT_6POS_ANTIFROST,
    LD_ACTION_SETPOINT_6POS_COMFORT,
    LD_ACTION_SETPOINT_6POS_ECO,
    LD_ACTION_SETPOINT_6POS_STOP,
    LD_ACTION_VALUE,
    LD_DEVICE_TYPE_FLOOR_HEATING,
    LD_PROP_THERMOSTAT_HEATMODE,
    LD_PROP_THERMOSTAT_REGULATION_SW,
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
    LD_STATE_FLOOR_HEATING,
    LD_STATE_HEATMODE,
    LD_STATE_REGULATION_ON,
    LD_STATE_SETPOINT_6POS,
    LD_STATE_TEMPERATURE,
    LD_STATE_TEMPERATURE_AMBIANT,
    LD_STATE_TEMPERATURE_COMFORT,
    LD_STATE_TEMPERATURE_SETPOINT,
    LD_STATE_THERMOSTAT,
    LD_STATE_THERMOSTAT_THERM_MODE,
    LD_VALUE_THERMOSTAT_6POS_ANTIFROST,
    LD_VALUE_THERMOSTAT_6POS_COMFORT,
    LD_VALUE_THERMOSTAT_6POS_ECO,
    LD_VALUE_THERMOSTAT_6POS_STOP,
    LD_VALUE_THERMOSTAT_HEATMODE_COMFORT,
    LD_VALUE_THERMOSTAT_HEATMODE_ECO,
    LD_VALUE_THERMOSTAT_HEATMODE_FROST,
    LD_VALUE_THERMOSTAT_HEATMODE_REDUCED,
    LD_VALUE_THERMOSTAT_MAX,
    LD_VALUE_THERMOSTAT_MIN,
    LD_VALUE_THERMOSTAT_STEP,
    LdDeviceCategory,
)
from .coordinator import LdCoordinator, LdCoordinatorConfig
from .data import LifedomusConfigEntry, LifedomusRuntimeData
from .entity import LifedomusEntity

# Actions are serialized per platform to keep the load on the gateway moderate.
PARALLEL_UPDATES = 1


@dataclass(frozen=True, slots=True)
class _PresetFamily:
    """Preset-based thermostat property family.

    Attributes:
        prop_clsid: Property carrying the preset actions.
        state_clsid: State reporting the active preset.
        action_by_preset: Home Assistant preset -> action CLSID.
        preset_by_value: Reported state value -> Home Assistant preset.
        off_action: Action switching the device off, when the family has one.
        off_value: State value reported when the device is off, when any.
    """

    prop_clsid: str
    state_clsid: str
    action_by_preset: Mapping[str, str]
    preset_by_value: Mapping[str, str]
    off_action: str | None = None
    off_value: str | None = None


PRESET_FAMILIES: Final[tuple[_PresetFamily, ...]] = (
    _PresetFamily(
        prop_clsid=LD_PROP_THERMOSTAT_SETPOINT_6POS,
        state_clsid=LD_STATE_SETPOINT_6POS,
        action_by_preset={
            PRESET_AWAY: LD_ACTION_SETPOINT_6POS_ANTIFROST,
            PRESET_COMFORT: LD_ACTION_SETPOINT_6POS_COMFORT,
            PRESET_ECO: LD_ACTION_SETPOINT_6POS_ECO,
        },
        preset_by_value={
            LD_VALUE_THERMOSTAT_6POS_ANTIFROST: PRESET_AWAY,
            LD_VALUE_THERMOSTAT_6POS_COMFORT: PRESET_COMFORT,
            LD_VALUE_THERMOSTAT_6POS_ECO: PRESET_ECO,
        },
        off_action=LD_ACTION_SETPOINT_6POS_STOP,
        off_value=LD_VALUE_THERMOSTAT_6POS_STOP,
    ),
    # Presets follow the decreasing setpoint ladder comfort > home > eco > away.
    _PresetFamily(
        prop_clsid=LD_PROP_THERMOSTAT_HEATMODE,
        state_clsid=LD_STATE_HEATMODE,
        action_by_preset={
            PRESET_AWAY: LD_ACTION_HEATMODE_FROST,
            PRESET_COMFORT: LD_ACTION_HEATMODE_COMFORT,
            PRESET_ECO: LD_ACTION_HEATMODE_ECONOMIC,
            PRESET_HOME: LD_ACTION_HEATMODE_REDUCED,
        },
        preset_by_value={
            LD_VALUE_THERMOSTAT_HEATMODE_FROST: PRESET_AWAY,
            LD_VALUE_THERMOSTAT_HEATMODE_COMFORT: PRESET_COMFORT,
            LD_VALUE_THERMOSTAT_HEATMODE_ECO: PRESET_ECO,
            LD_VALUE_THERMOSTAT_HEATMODE_REDUCED: PRESET_HOME,
        },
    ),
)
PRESET_FAMILY_BY_PROP: Final[dict[str, _PresetFamily]] = {
    family.prop_clsid: family for family in PRESET_FAMILIES
}
PRESET_STATE_CLSIDS: Final[frozenset[str]] = frozenset(
    family.state_clsid for family in PRESET_FAMILIES
)
# Properties carrying plain ON/OFF actions that switch the regulation.
HVAC_SWITCH_PROPS: Final[frozenset[str]] = frozenset(
    {LD_PROP_THERMOSTAT_REGULATION_SW, LD_PROP_THERMOSTAT_STOP}
)
# State CLSID groups: the reported CLSIDs vary across device types,
# so each logical value accepts several aliases.
AMBIENT_TEMPERATURE_STATES: Final[frozenset[str]] = frozenset(
    {LD_STATE_TEMPERATURE_AMBIANT, LD_STATE_TEMPERATURE}
)
SETPOINT_TEMPERATURE_STATES: Final[frozenset[str]] = frozenset(
    {LD_STATE_TEMPERATURE_SETPOINT, LD_STATE_TEMPERATURE_COMFORT}
)
HEATING_STATES: Final[frozenset[str]] = frozenset(
    {LD_STATE_THERMOSTAT, LD_STATE_FLOOR_HEATING}
)
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
class LdClimateDevice:
    """Container for a parsed Lifedomus climate device."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str

    # Capabilities detected from the <actions> block
    supports_generalconst: bool
    preset_family: _PresetFamily | None
    on_prop_clsid: str | None
    off_prop_clsid: str | None

    # Numeric state values
    current_temperature: float | None
    target_temperature: float | None

    # Raw value of the preset family state
    preset_raw: str | None

    # Running state (CLSID-STATE-THERMOSTAT or CLSID-STATE-DEVC-FLOOR-HEATING)
    is_heating: bool | None

    # Regulation flag and raw thermal mode for virtual thermostats
    regulation_on: bool | None
    therm_mode: str | None

    # Constraints derived from action descriptor
    min_temp: float | None
    max_temp: float | None

    # Diagnostic boolean states (FLAG/FAULT)
    diagnostic_states: dict[str, bool | None]


@dataclass(slots=True)
class _LdClimateCapabilities:
    """Mutable accumulator for capabilities parsed from the <actions> block."""

    supports_generalconst: bool = False
    preset_family: _PresetFamily | None = None
    on_prop_clsid: str | None = None
    off_prop_clsid: str | None = None
    min_temp: float | None = None
    max_temp: float | None = None


@dataclass(slots=True)
class _LdClimateStates:
    """Mutable accumulator for state values parsed from the <states> block."""

    current_temperature: float | None = None
    target_temperature: float | None = None
    preset_raw: str | None = None
    is_heating: bool | None = None
    regulation_on: bool | None = None
    therm_mode: str | None = None
    diagnostic_states: dict[str, bool | None] = field(default_factory=dict)


def _parse_climate_descriptor_limits(
    descriptor_text: str | None,
) -> tuple[float | None, float | None]:
    """Return the (min, max) bounds of the 'temperature' parameter of an action descriptor.

    The descriptor is an HTML-escaped XML fragment; a regex fallback covers
    fragments that do not parse. Non-numeric bounds (e.g. "null") yield None.
    """
    if not descriptor_text:
        return None, None
    try:
        root = ET.fromstring(html.unescape(descriptor_text))
    except ET.ParseError:
        min_match = re.search(r'min="([0-9]+(?:\.[0-9]+)?)"', descriptor_text)
        max_match = re.search(r'max="([0-9]+(?:\.[0-9]+)?)"', descriptor_text)
        return (
            float(min_match.group(1)) if min_match else None,
            float(max_match.group(1)) if max_match else None,
        )

    param = root.find(".//parameter[@name='temperature']")
    if param is None:
        return None, None
    min_attr = param.get("min")
    max_attr = param.get("max")
    try:
        return (
            float(min_attr) if min_attr else None,
            float(max_attr) if max_attr else None,
        )
    except ValueError:
        return None, None


def _parse_climate_actions_capabilities(
    api: LifedomusApi, dev_el: Element
) -> _LdClimateCapabilities:
    """Extract supported properties and setpoint bounds from the <actions> block."""
    caps = _LdClimateCapabilities()

    for action_el in dev_el.findall("./actions/action"):
        prop_clsid = api.txt("prop_clsid", action_el)
        action_clsid = api.txt("action_clsid", action_el)

        if prop_clsid == LD_PROP_THERMOSTAT_SETPOINT and action_clsid == LD_ACTION_VALUE:
            caps.supports_generalconst = True
            caps.min_temp, caps.max_temp = _parse_climate_descriptor_limits(
                api.txt_path(action_el, "descriptor")
            )
        elif prop_clsid in PRESET_FAMILY_BY_PROP:
            caps.preset_family = PRESET_FAMILY_BY_PROP[prop_clsid]
        elif prop_clsid in HVAC_SWITCH_PROPS and action_clsid == LD_ACTION_ON:
            caps.on_prop_clsid = prop_clsid
        elif prop_clsid in HVAC_SWITCH_PROPS and action_clsid == LD_ACTION_OFF:
            caps.off_prop_clsid = prop_clsid

    return caps


def _parse_climate_states(api: LifedomusApi, dev_el: Element) -> _LdClimateStates:
    """Extract temperatures, preset, running flags and diagnostic states.

    Temperature and heating states accept several CLSID aliases; the first
    non-empty value wins so canonical and variant CLSIDs can coexist safely.
    """
    states = _LdClimateStates()

    states_el = dev_el.find("./states")
    if states_el is None:
        return states

    for st_el in states_el.findall("./state"):
        state_clsid = api.txt("state_clsid", st_el)
        if not state_clsid:
            continue

        val_txt = api.txt_path(st_el, "./values/value/value")

        if state_clsid in AMBIENT_TEMPERATURE_STATES:
            if states.current_temperature is None:
                states.current_temperature = parse_number(val_txt)
        elif state_clsid in SETPOINT_TEMPERATURE_STATES:
            if states.target_temperature is None:
                states.target_temperature = parse_number(val_txt)
        elif state_clsid in PRESET_STATE_CLSIDS:
            if val_txt is not None:
                states.preset_raw = val_txt.strip().upper() or None
        elif state_clsid in HEATING_STATES:
            if val_txt is not None:
                states.is_heating = parse_bool(val_txt)
        elif state_clsid == LD_STATE_REGULATION_ON:
            if val_txt is not None:
                states.regulation_on = parse_bool(val_txt)
        elif state_clsid == LD_STATE_THERMOSTAT_THERM_MODE:
            if val_txt is not None:
                states.therm_mode = val_txt.strip() or None
        elif state_clsid in THERMOSTAT_DIAGNOSTIC_STATES and val_txt is not None:
            states.diagnostic_states[state_clsid] = parse_bool(val_txt)

    return states


def _parse_climate_device_element(
    api: LifedomusApi, dev_el: Element
) -> LdClimateDevice | None:
    """Parse a <device> element returned by GetDevicesFromCatg into a snapshot."""
    device_key = api.txt("device_key", dev_el)
    if not device_key:
        return None

    caps = _parse_climate_actions_capabilities(api, dev_el)
    states = _parse_climate_states(api, dev_el)

    return LdClimateDevice(
        device_key=device_key,
        device_clsid=api.txt("device_clsid", dev_el),
        label=api.txt("label", dev_el) or device_key,
        room_label=api.txt("room_label", dev_el),
        supports_generalconst=caps.supports_generalconst,
        preset_family=caps.preset_family,
        on_prop_clsid=caps.on_prop_clsid,
        off_prop_clsid=caps.off_prop_clsid,
        current_temperature=states.current_temperature,
        target_temperature=states.target_temperature,
        preset_raw=states.preset_raw,
        is_heating=states.is_heating,
        regulation_on=states.regulation_on,
        therm_mode=states.therm_mode,
        min_temp=caps.min_temp,
        max_temp=caps.max_temp,
        diagnostic_states=states.diagnostic_states,
    )


CLIMATE_COORDINATOR_CONFIG: Final[LdCoordinatorConfig[LdClimateDevice]] = (
    LdCoordinatorConfig(
        name="Lifedomus climate coordinator",
        category_clsid=LdDeviceCategory.ACTUATOR_CLIMATECONTROL,
        parse_device=_parse_climate_device_element,
    )
)


class LifedomusClimate(LifedomusEntity[LdClimateDevice], ClimateEntity):
    """Lifedomus climate entity."""

    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = LD_VALUE_THERMOSTAT_STEP

    def __init__(
        self,
        coordinator: LdCoordinator[LdClimateDevice],
        device: LdClimateDevice,
        runtime: LifedomusRuntimeData,
    ) -> None:
        """Initialize the climate entity."""
        super().__init__(coordinator, device, runtime)
        self._attr_unique_id = device.device_key
        self._apply_device_snapshot(device)

    def _apply_device_snapshot(self, device: LdClimateDevice) -> None:
        """Apply the coordinator snapshot to HA attributes."""
        self._device = device
        self._attr_current_temperature = device.current_temperature
        self._attr_target_temperature = device.target_temperature
        self._attr_min_temp = (
            device.min_temp if device.min_temp is not None else LD_VALUE_THERMOSTAT_MIN
        )
        self._attr_max_temp = (
            device.max_temp if device.max_temp is not None else LD_VALUE_THERMOSTAT_MAX
        )

        family = device.preset_family
        # OFF is only advertised when the device exposes a way to switch off.
        can_turn_off = device.off_prop_clsid is not None or (
            family is not None and family.off_action is not None
        )
        self._attr_hvac_modes = (
            [HVACMode.HEAT, HVACMode.OFF] if can_turn_off else [HVACMode.HEAT]
        )

        features = ClimateEntityFeature(0)
        if can_turn_off:
            features |= ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF
        if device.supports_generalconst:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        if family is not None:
            features |= ClimateEntityFeature.PRESET_MODE
        self._attr_supported_features = features

        # The inferred mode is constrained to the advertised modes: a heat-only
        # device reporting an idle flag stays in HEAT.
        hvac_mode = self._infer_hvac_mode(device)
        self._attr_hvac_mode = (
            hvac_mode if hvac_mode in self._attr_hvac_modes else HVACMode.HEAT
        )

        # HVAC action is only known when both the regulation flag and the
        # heating demand flag are reported (virtual thermostats).
        if device.regulation_on is None or device.is_heating is None:
            self._attr_hvac_action = None
        elif not device.regulation_on:
            self._attr_hvac_action = HVACAction.OFF
        else:
            self._attr_hvac_action = (
                HVACAction.HEATING if device.is_heating else HVACAction.IDLE
            )

        if family is None:
            self._attr_preset_modes = None
            self._attr_preset_mode = None
        else:
            self._attr_preset_modes = list(family.action_by_preset)
            self._attr_preset_mode = (
                family.preset_by_value.get(device.preset_raw)
                if device.preset_raw
                else None
            )

    @staticmethod
    def _infer_hvac_mode(device: LdClimateDevice) -> HVACMode:
        """Infer the HVAC mode from the preset family, the regulation flag or the running state."""
        if (family := device.preset_family) is not None:
            return (
                HVACMode.OFF
                if family.off_value is not None and device.preset_raw == family.off_value
                else HVACMode.HEAT
            )
        if device.regulation_on is not None:
            return HVACMode.HEAT if device.regulation_on else HVACMode.OFF
        if device.is_heating is not None:
            return HVACMode.HEAT if device.is_heating else HVACMode.OFF
        return HVACMode.HEAT

    @property
    def extra_state_attributes(self) -> dict[str, bool | str | None]:
        """Expose diagnostic FLAG/FAULT states and the raw thermal mode."""
        result: dict[str, bool | str | None] = {
            clsid.removeprefix("CLSID-STATE-").lower().replace("-", "_"): value
            for clsid, value in self._device.diagnostic_states.items()
        }
        if self._device.therm_mode is not None:
            result["therm_mode"] = self._device.therm_mode
        return result

    async def _async_send_setpoint(self, temp: float) -> None:
        """Clamp and step the setpoint, publish it optimistically and send it on GENERALCONST."""
        self._attr_target_temperature = max(
            self.min_temp,
            min(
                self.max_temp,
                round(temp / LD_VALUE_THERMOSTAT_STEP) * LD_VALUE_THERMOSTAT_STEP,
            ),
        )
        self.async_write_ha_state()
        await self._async_execute_action(
            LD_PROP_THERMOSTAT_SETPOINT,
            LD_ACTION_VALUE,
            build_action_descriptor({"temperature": self._attr_target_temperature}),
        )

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set the target temperature on direct setpoint devices."""
        if (
            self._device.supports_generalconst
            and (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None
        ):
            await self._async_send_setpoint(float(temperature))

    async def async_turn_on(self) -> None:
        """Handle climate.turn_on by switching HVAC to HEAT."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        """Handle climate.turn_off by switching HVAC to OFF."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Select a preset through the preset family of the device."""
        if (family := self._device.preset_family) is None or (
            action := family.action_by_preset.get(preset_mode)
        ) is None:
            return

        self._attr_preset_mode = preset_mode
        self._attr_hvac_mode = HVACMode.HEAT
        self.async_write_ha_state()
        await self._async_execute_action(family.prop_clsid, action)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode through the most specific capability of the device.

        OFF uses the preset family off action or the switch property. HEAT uses
        the switch property, then falls back to the comfort preset, then to
        re-sending the current setpoint on direct setpoint devices.
        """
        if HVACMode.OFF not in self._attr_hvac_modes:
            # Heat-only device: there is nothing to switch.
            return

        device = self._device
        family = device.preset_family

        if hvac_mode == HVACMode.OFF:
            if family is not None and family.off_action is not None:
                prop_clsid, action_clsid = family.prop_clsid, family.off_action
            elif device.off_prop_clsid is not None:
                prop_clsid, action_clsid = device.off_prop_clsid, LD_ACTION_OFF
            else:
                return
            self._attr_hvac_mode = HVACMode.OFF
            self.async_write_ha_state()
            await self._async_execute_action(prop_clsid, action_clsid)
            return

        if device.on_prop_clsid is not None:
            self._attr_hvac_mode = HVACMode.HEAT
            self.async_write_ha_state()
            await self._async_execute_action(device.on_prop_clsid, LD_ACTION_ON)
        elif family is not None:
            await self.async_set_preset_mode(PRESET_COMFORT)
        elif device.supports_generalconst:
            # Re-sending the setpoint is the only way to resume heating.
            self._attr_hvac_mode = HVACMode.HEAT
            await self._async_send_setpoint(
                self._attr_target_temperature
                if self._attr_target_temperature is not None
                else self.min_temp
            )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LifedomusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Lifedomus climate platform from a config entry.

    Heat demand indicators (CLSID-DEVC-A-CC15) are exposed by the binary_sensor
    platform; any climate entity previously registered for them is removed from
    the entity registry so no orphan remains after an upgrade.
    """
    runtime = entry.runtime_data
    registry = er.async_get(hass)

    entities: list[ClimateEntity] = []
    for device in runtime.climate.data.values():
        if device.device_clsid != LD_DEVICE_TYPE_FLOOR_HEATING:
            entities.append(LifedomusClimate(runtime.climate, device, runtime))
        elif entity_id := registry.async_get_entity_id(
            Platform.CLIMATE, DOMAIN, device.device_key
        ):
            registry.async_remove(entity_id)

    async_add_entities(entities)
