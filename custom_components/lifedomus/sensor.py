"""Raw sensor platform for Lifedomus.

This platform queries the Lifedomus gateway for all "measurement" devices
in category CLSID-DEVC-M-CS and exposes them as Home Assistant sensors.

Data source:
 - Mobile/GetDevicesFromCatg with category_clsid=CLSID-DEVC-M-CS, which returns a list
   of devices providing a numeric <value> and a suggested <unit> under <states>.
Parsing rules:
 - Use state_clsid 'CLSID-STATE-VALUE' when present to extract the numeric value.
 - Accept both '.' and ',' as decimal separator (e.g., '9,7' -> 9.7).
 - Use the suggested unit string as native_unit_of_measurement.

It also exposes the alarm "Operating mode" state (OPERATING_MODE) for devices in
category CLSID-DEVC-S-PR as generic sensors.

Notes:
 - The category mapping and device examples (CS15, CS22) are standard for Lifedomus
   measurement devices.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Final
from xml.etree.ElementTree import Element

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .alarm import ALARM_OPERATING_MODE_ICON_BY_VALUE, LdAlarmDevice
from .api import LifedomusApi, SystemVariableValue, parse_number
from .const import (
    LD_CLSID_SYSTEM_VARIABLES,
    LD_DEVICE_TYPE_HEATING_MANAGER,
    LD_STATE_VALUE,
    LD_VALUE_ALARM_MODE_ARMED_FULL,
    LD_VALUE_ALARM_MODE_ARMED_PARTIAL,
    LD_VALUE_ALARM_MODE_MAINTENANCE,
    LD_VALUE_ALARM_MODE_STOP,
    LdDeviceCategory,
)
from .coordinator import LdCoordinator, LdCoordinatorConfig
from .data import LifedomusConfigEntry, LifedomusRuntimeData
from .energy import LdEnergyMeter
from .entity import LifedomusEntity, LifedomusSystemVariableEntity

# Read-only entities fed by shared coordinators
PARALLEL_UPDATES = 0

def normalize_operating_mode_value(mode: str | None) -> str | None:
    """Normalize raw operating mode values to translation state keys.

    Translations are defined with lowercase keys using snake-case for consistency.
    """
    if not mode:
        return None
    raw = mode.strip().upper()
    mapping = {
        LD_VALUE_ALARM_MODE_ARMED_FULL: "full_arming",
        LD_VALUE_ALARM_MODE_ARMED_PARTIAL: "partial_arming",
        LD_VALUE_ALARM_MODE_STOP: "stop",
        LD_VALUE_ALARM_MODE_MAINTENANCE: "maintenance",
    }
    # Default: fall back to lowercase of the raw value to keep a stable key
    return mapping.get(raw, raw.lower())


@dataclass(slots=True)
class LdRawSensor:
    """Container for a parsed Lifedomus raw sensor."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str
    unit: str | None
    value: float | int | None


def _parse_raw_sensor_device_element(
    api: LifedomusApi, dev_el: Element
) -> LdRawSensor | None:
    """Parse a <device> element returned by GetDevicesFromCatg into a sensor snapshot."""
    device_key = api.txt("device_key", dev_el)
    if not device_key:
        return None

    device_clsid = api.txt("device_clsid", dev_el)
    label = api.txt("label", dev_el) or device_key
    room_label = api.txt("room_label", dev_el)

    unit: str | None = None
    value: float | int | None = None

    states_el = dev_el.find("./states")
    if states_el is not None:
        for st_el in states_el.findall("./state"):
            state_clsid = api.txt("state_clsid", st_el)
            if state_clsid != LD_STATE_VALUE:
                continue

            val_txt = api.txt_path(st_el, "./values/value/value")
            unit_txt = api.txt_path(st_el, "./values/value/unit")
            if val_txt is not None:
                value = parse_number(val_txt)
            if unit_txt is not None:
                unit = unit_txt
            break

    return LdRawSensor(
        device_key=device_key,
        device_clsid=device_clsid,
        label=label,
        room_label=room_label,
        unit=unit,
        value=value,
    )


SENSOR_COORDINATOR_CONFIG: Final[LdCoordinatorConfig[LdRawSensor]] = (
    LdCoordinatorConfig(
        name="Lifedomus sensor coordinator",
        category_clsid=LdDeviceCategory.MEASURE_SENSOR,
        parse_device=_parse_raw_sensor_device_element,
    )
)


def _device_class_for_unit(unit: str | None) -> SensorDeviceClass | None:
    """Return a best-effort device class inferred from the unit reported by the gateway."""
    if not unit:
        return None
    if "°C" in unit:
        return SensorDeviceClass.TEMPERATURE
    if "W/m²" in unit:
        return SensorDeviceClass.IRRADIANCE
    return None


class LifedomusRawSensor(LifedomusEntity[LdRawSensor], SensorEntity):
    """Lifedomus raw measurement sensor."""

    _attr_name = None
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: LdCoordinator[LdRawSensor],
        device: LdRawSensor,
        runtime: LifedomusRuntimeData,
    ) -> None:
        """Initialize the sensor entity."""
        super().__init__(coordinator, device, runtime)
        self._attr_unique_id = device.device_key
        self._apply_device_snapshot(device)

    def _apply_device_snapshot(self, device: LdRawSensor) -> None:
        """Copy the value and unit, deriving the device class from the unit."""
        self._attr_native_value = device.value
        self._attr_native_unit_of_measurement = device.unit
        self._attr_device_class = _device_class_for_unit(device.unit)


class LifedomusAlarmOperatingModeSensor(LifedomusEntity[LdAlarmDevice], SensorEntity):
    """Alarm 'Operating mode' sensor (text) with mode-specific icon."""

    _attr_translation_key = "operating_mode"

    def __init__(
        self,
        coordinator: LdCoordinator[LdAlarmDevice],
        device: LdAlarmDevice,
        runtime: LifedomusRuntimeData,
    ) -> None:
        """Initialize the alarm operating mode sensor."""
        super().__init__(coordinator, device, runtime)
        self._attr_unique_id = f"{device.device_key}::operating_mode"
        self._apply_device_snapshot(device)

    def _apply_device_snapshot(self, device: LdAlarmDevice) -> None:
        """Normalize the mode for translations and pick the matching icon."""
        self._attr_native_value = normalize_operating_mode_value(device.operating_mode)
        self._attr_icon = ALARM_OPERATING_MODE_ICON_BY_VALUE.get(
            (device.operating_mode or "").strip().upper(), "mdi:help-circle-outline"
        )


class LifedomusEnergyMeterSensor(LifedomusEntity[LdEnergyMeter], SensorEntity):
    """Energy meter sensor exposing total consumption."""

    _attr_name = None
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR

    def __init__(
        self,
        coordinator: LdCoordinator[LdEnergyMeter],
        device: LdEnergyMeter,
        runtime: LifedomusRuntimeData,
    ) -> None:
        """Initialize the energy meter sensor."""
        super().__init__(coordinator, device, runtime)
        self._attr_unique_id = f"{device.device_key}::total_energy"
        self._apply_device_snapshot(device)

    def _apply_device_snapshot(self, device: LdEnergyMeter) -> None:
        """Copy the total and expose the reset values as attributes."""
        self._attr_native_value = device.total_value
        self._attr_extra_state_attributes = {
            "value_reset": device.total_value_reset,
            "date": device.date,
            "date_reset": device.date_reset,
        }


class LifedomusSystemVariableSensor(LifedomusSystemVariableEntity, SensorEntity):
    """Non-boolean system variable of the hub."""

    def __init__(self, entry: LifedomusConfigEntry, variable_key: str) -> None:
        """Initialize the entity and apply the configured classes and unit."""
        super().__init__(entry, variable_key)
        config = self._config
        if config.value_type is datetime:
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
        elif config.value_type is date:
            self._attr_device_class = SensorDeviceClass.DATE
        if isinstance(config.sensor_class, SensorStateClass):
            self._attr_state_class = config.sensor_class
        self._attr_native_unit_of_measurement = config.unit

    def _apply_value(self, value: SystemVariableValue) -> None:
        """Keep the value only when it matches the declared type of the variable."""
        config = self._config
        if config.value_type is int and isinstance(value, (int, float)):
            self._attr_native_value = int(value)
        elif config.value_type is float and isinstance(value, (int, float)):
            self._attr_native_value = float(value)
        elif config.value_type in (str, date, datetime) and isinstance(
            value, config.value_type
        ):
            self._attr_native_value = value


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LifedomusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Lifedomus sensor platform from a config entry."""
    runtime = entry.runtime_data
    entities: list[SensorEntity] = [
        LifedomusRawSensor(runtime.sensor, device, runtime)
        for device in runtime.sensor.data.values()
    ]
    entities.extend(
        LifedomusAlarmOperatingModeSensor(runtime.alarm, device, runtime)
        for device in runtime.alarm.data.values()
    )
    entities.extend(
        LifedomusEnergyMeterSensor(runtime.energy, device, runtime)
        for device in runtime.energy.data.values()
        if device.device_clsid == LD_DEVICE_TYPE_HEATING_MANAGER
    )
    entities.extend(
        LifedomusSystemVariableSensor(entry, variable_key)
        for variable_key, config in LD_CLSID_SYSTEM_VARIABLES.items()
        if config.value_type is not bool
    )
    async_add_entities(entities)
