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

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
import logging
from typing import cast
from xml.etree.ElementTree import Element

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .alarm import (
    ALARM_OPERATING_MODE_ICON_BY_VALUE,
    LdAlarmDevice,
    get_or_create_alarm_coordinator,
)
from .api import LifedomusApi, LifedomusApiError, parse_number
from .const import (
    CONF_SITE_KEY,
    DOMAIN,
    LD_CLSID_SYSTEM_VARIABLES,
    LD_STATE_VALUE,
    LD_VALUE_ALARM_MODE_ARMED_FULL,
    LD_VALUE_ALARM_MODE_ARMED_PARTIAL,
    LD_VALUE_ALARM_MODE_MAINTENANCE,
    LD_VALUE_ALARM_MODE_STOP,
    MODEL,
    LdDeviceCategory,
)
from .coordinator import LdCoordinator, LdCoordinatorConfig
from .energy import LdEnergyMeter, get_or_create_energy_coordinator
from .helpers import EntityDependencies, build_device_info, get_update_interval

_LOGGER = logging.getLogger(__name__)


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
class _LdRawSensor:
    """Container for a parsed Lifedomus raw sensor."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str
    unit: str | None
    value: float | int | None


def _parse_raw_sensor_device_element(
    api: LifedomusApi, dev_el: Element
) -> _LdRawSensor | None:
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

    return _LdRawSensor(
        device_key=device_key,
        device_clsid=device_clsid,
        label=label,
        room_label=room_label,
        unit=unit,
        value=value,
    )


async def get_or_create_sensor_coordinator(
    hass: HomeAssistant, api: LifedomusApi, entry: ConfigEntry
) -> LdCoordinator[_LdRawSensor]:
    """Return the shared raw sensor coordinator, creating and refreshing it if missing.

    The raw sensor coordinator manages devices from the "environment measurement"
    category and is shared across platforms to support targeted refreshes triggered
    by the SSH monitor.
    """
    shared = hass.data.setdefault(DOMAIN, {})
    coord = shared.get("sensor_coordinator")
    if isinstance(coord, LdCoordinator):
        return coord

    cfg = LdCoordinatorConfig[_LdRawSensor](
        name="Lifedomus sensor coordinator",
        update_interval=get_update_interval(entry),
        category_clsid=LdDeviceCategory.MEASURE_SENSOR,
        parse_device=_parse_raw_sensor_device_element,
    )
    coord: LdCoordinator[_LdRawSensor] = LdCoordinator(hass, api, cfg)
    await coord.async_config_entry_first_refresh()
    shared["sensor_coordinator"] = coord
    return coord


class LifedomusRawSensor(SensorEntity):
    """Lifedomus raw sensor entity."""

    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: LdCoordinator[_LdRawSensor],
        device: _LdRawSensor,
        dependencies: EntityDependencies,
    ) -> None:
        """Initialize the sensor entity and attach the coordinator by composition."""
        super().__init__()
        self.coordinator = coordinator
        self._api = dependencies.api

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

    def _apply_device_snapshot(self, device: _LdRawSensor) -> None:
        """Apply the coordinator snapshot to HA attributes."""
        self._attr_name = device.label
        self._attr_native_value = device.value
        self._attr_native_unit_of_measurement = device.unit

        # Try to set a device class when unit is known (best-effort).
        device_class: SensorDeviceClass | None = None
        if device.unit:
            if "°C" in device.unit:
                device_class = SensorDeviceClass.TEMPERATURE
            elif "W/m²" in device.unit:
                device_class = SensorDeviceClass.IRRADIANCE
        self._attr_device_class = device_class

    @property
    def _dev(self) -> _LdRawSensor | None:
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


class LifedomusAlarmOperatingModeSensor(SensorEntity):
    """Alarm 'Operating mode' sensor (text) with mode-specific icon."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_translation_key = "operating_mode"

    def __init__(
        self,
        coordinator: LdCoordinator,
        device: LdAlarmDevice,
        dependencies: EntityDependencies,
    ) -> None:
        """Initialize the alarm operating mode sensor."""
        super().__init__()
        self.coordinator = coordinator
        self._api = dependencies.api
        self._device_key = device.device_key

        self._attr_unique_id = f"{device.device_key}::operating_mode"

        self._attr_device_info = build_device_info(
            device_key=device.device_key,
            device_clsid=device.device_clsid,
            label=device.label,
            room_label=device.room_label,
            uuid=dependencies.uuid,
        )

        current_mode: str | None = device.operating_mode
        norm_mode = normalize_operating_mode_value(current_mode)
        self._attr_native_value = norm_mode

        raw_for_icon = current_mode or (norm_mode.upper() if norm_mode else None)
        self._attr_icon = self._resolve_icon(raw_for_icon)

    @staticmethod
    def _resolve_icon(mode: str | None) -> str:
        """Return an icon representing the current operating mode."""
        if not mode:
            return "mdi:help-circle-outline"
        return ALARM_OPERATING_MODE_ICON_BY_VALUE.get(
            mode.upper(), "mdi:help-circle-outline"
        )

    @property
    def _dev(self) -> LdAlarmDevice | None:
        """Return the current alarm device snapshot."""
        return self.coordinator.data.get(self._device_key)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle update from alarm coordinator."""
        device = self._dev
        if device is not None:
            norm_mode = normalize_operating_mode_value(device.operating_mode)
            self._attr_native_value = norm_mode
            raw_for_icon = device.operating_mode or (
                norm_mode.upper() if norm_mode else None
            )
            self._attr_icon = self._resolve_icon(raw_for_icon)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register update listener and publish initial state."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self.async_write_ha_state()


class LifedomusEnergyMeterSensor(SensorEntity):
    """Energy meter sensor exposing total consumption."""

    _attr_should_poll = False
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = "Wh"

    def __init__(
        self,
        coordinator: LdCoordinator,
        device: LdEnergyMeter,
        dependencies: EntityDependencies,
    ) -> None:
        """Initialize the energy meter sensor."""
        super().__init__()
        self.coordinator = coordinator
        self._api = dependencies.api
        self._device_key = device.device_key

        self._attr_unique_id = f"{device.device_key}::total_energy"
        self._attr_name = device.label

        self._attr_device_info = build_device_info(
            device_key=device.device_key,
            device_clsid=device.device_clsid,
            label=device.label,
            room_label=device.room_label,
            uuid=dependencies.uuid,
        )

        self._apply_device_snapshot(device)

    def _apply_device_snapshot(self, device: LdEnergyMeter) -> None:
        """Apply the coordinator snapshot to HA attributes."""
        self._attr_native_value = device.total_value

    @property
    def _dev(self) -> LdEnergyMeter | None:
        """Return the current device snapshot."""
        return self.coordinator.data.get(self._device_key)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose additional energy meter attributes."""
        device = self._dev
        if device is None:
            return {}
        return {
            "value_reset": device.total_value_reset,
            "date": device.date,
            "date_reset": device.date_reset,
        }

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle update from energy coordinator."""
        device = self._dev
        if device is not None:
            self._apply_device_snapshot(device)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register update listener and publish initial state."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self.async_write_ha_state()


class LifedomusSystemVariableSensor(SensorEntity):
    """System variable sensor exposed by the Lifedomus hub."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        api: LifedomusApi,
        site_key: str,
        uuid: str,
        variable_key: str,
    ) -> None:
        """Initialize the system variable sensor."""
        super().__init__()
        self._hass = hass
        self._api = api
        self._site_key = site_key
        self.variable_key = variable_key

        config = LD_CLSID_SYSTEM_VARIABLES[variable_key]

        self._attr_unique_id = f"{uuid}::system::{variable_key}"
        self._attr_translation_key = config.translation_key
        self._attr_icon = config.icon
        self._attr_entity_registry_enabled_default = config.enabled

        if config.value_type in (date, datetime):
            if isinstance(config.sensor_class, SensorDeviceClass):
                self._attr_device_class = config.sensor_class
            elif config.value_type is datetime:
                self._attr_device_class = SensorDeviceClass.TIMESTAMP
            elif config.value_type is date:
                self._attr_device_class = SensorDeviceClass.DATE

        if config.unit:
            self._attr_native_unit_of_measurement = config.unit

        if isinstance(config.sensor_class, SensorStateClass):
            self._attr_state_class = config.sensor_class

        self._attr_device_info = build_device_info(
            device_key=uuid,
            device_clsid=MODEL,
            label=MODEL,
            room_label="",
            uuid=uuid,
        )

        self._attr_native_value = None

    def _apply_value(self, value: bool | date | datetime | float | str | None) -> None:
        """Apply and validate a system variable value based on its declared type."""
        config = LD_CLSID_SYSTEM_VARIABLES[self.variable_key]

        if config.value_type is int and isinstance(value, (int, float)):
            self._attr_native_value = int(value)
        elif config.value_type is float and isinstance(value, (int, float)):
            self._attr_native_value = float(value)
        elif (
            (config.value_type is str and isinstance(value, str))
            or (config.value_type is date and isinstance(value, date))
            or (config.value_type is datetime and isinstance(value, datetime))
        ):
            self._attr_native_value = value

    async def async_added_to_hass(self) -> None:
        """Fetch initial value when entity is added to Home Assistant."""
        await super().async_added_to_hass()
        if self.enabled:
            await self.async_update()
        self.async_write_ha_state()

    async def async_update(self) -> None:
        """Fetch the current system variable value."""
        try:
            value = await self._api.async_get_system_variable(
                site_key=self._site_key, variable_key=self.variable_key
            )
        except LifedomusApiError as err:
            _LOGGER.warning(
                "Failed to fetch system variable %s: %s", self.variable_key, err
            )
            return

        self._apply_value(value)

    def handle_push_update(
        self, value: bool | date | datetime | float | str | None
    ) -> None:
        """Handle a push notification update for this system variable."""
        self._apply_value(value)
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Callable[[list[SensorEntity]], None],
) -> None:
    """Set up the Lifedomus raw sensors platform from a config entry."""
    api: LifedomusApi = entry.runtime_data
    site_key = str(entry.data.get(CONF_SITE_KEY, ""))
    shared = hass.data.setdefault(DOMAIN, {})
    uuid = str(shared.get("uuid", ""))

    sensor_coordinator = await get_or_create_sensor_coordinator(hass, api, entry)
    shared["sensor_coordinator"] = sensor_coordinator

    alarm_coordinator = await get_or_create_alarm_coordinator(hass, api, entry)
    shared["alarm_coordinator"] = alarm_coordinator

    energy_coordinator = await get_or_create_energy_coordinator(hass, api, entry)
    shared["energy_coordinator"] = energy_coordinator

    dependencies = EntityDependencies(api=api, entry=entry, uuid=uuid)

    system_sensors = [
        LifedomusSystemVariableSensor(hass, api, site_key, uuid, var_key)
        for var_key, config in LD_CLSID_SYSTEM_VARIABLES.items()
        if config.value_type is not bool
    ]
    shared["system_sensors"] = {s.variable_key: s for s in system_sensors}

    entities = cast(
        list[SensorEntity],
        [
            LifedomusRawSensor(sensor_coordinator, device, dependencies)
            for device in sensor_coordinator.data.values()
        ]
        + [
            LifedomusAlarmOperatingModeSensor(alarm_coordinator, device, dependencies)
            for device in alarm_coordinator.data.values()
        ]
        + [
            LifedomusEnergyMeterSensor(energy_coordinator, device, dependencies)
            for device in energy_coordinator.data.values()
            if device.device_clsid == "CLSID-DEVC-M-CP13"
        ]
        + system_sensors,
    )

    async_add_entities(entities)
