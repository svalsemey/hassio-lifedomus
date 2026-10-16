"""Binary sensor platform for Lifedomus.

This platform queries the Lifedomus gateway for all detectors in the "detector"
category (CLSID-DEVC-S-DT) and exposes them as Home Assistant binary_sensor entities.
It also exposes alarm boolean states for devices in "alarm" category (CLSID-DEVC-S-PR)
as binary sensors attached to the alarm device.

Heat demand indicators (CLSID-DEVC-A-CC15) from the climate control category
are exposed as read-only binary sensors fed by the shared climate coordinator,
since they only report CLSID-STATE-DEVC-FLOOR-HEATING and have no actuator.

State handling:

 - The state with state_clsid 'CLSID-STATE-TRIGGERRED' (Note: spelling as returned by Lifedomus
   XML) is prioritized:
   * If it has no <value>, the entity state is unknown (is_on=None).
   * If it has a boolean value ("true"/"false"), it is used.
 - Otherwise, the first state with <type>BOOLEAN is used as on/off value.
 - If no boolean <value> exists, the entity remains available with an unknown state (is_on=None).

 Alarm boolean mapping comes from alarm.ALARM_BOOL_STATES.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Final
from xml.etree.ElementTree import Element

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .alarm import (
    ALARM_BOOL_STATES,
    ALARM_FAULT_LABEL_TO_CATEGORY,
    AlarmBoolDef,
    LdAlarmDevice,
)
from .api import LifedomusApi, LifedomusApiError, SystemVariableValue
from .climate import LdClimateDevice
from .const import (
    LD_CLSID_SYSTEM_VARIABLES,
    LD_DEFAULT_ITEMS_LIMIT,
    LD_DEVICE_TYPE_FLOOR_HEATING,
    LD_STATE_ALARM_WARN_EVENTS_UNACKNOWLEDGED,
    LD_STATE_TRIGGERED,
    LdDeviceCategory,
)
from .coordinator import LdCoordinator, LdCoordinatorConfig
from .data import LifedomusConfigEntry, LifedomusRuntimeData
from .entity import LifedomusEntity, LifedomusSystemVariableEntity

_LOGGER = logging.getLogger(__name__)

# Map device clsid to HA device class.
DEVICE_CLASS_BY_CLSID: Final[dict[str, BinarySensorDeviceClass]] = {
    "CLSID-DEVC-S-DT01": BinarySensorDeviceClass.PROBLEM,
    "CLSID-DEVC-S-DT05": BinarySensorDeviceClass.MOISTURE,
    "CLSID-DEVC-S-DT08": BinarySensorDeviceClass.SMOKE,
    "CLSID-DEVC-S-DT09": BinarySensorDeviceClass.MOTION,
    "CLSID-DEVC-S-DT10": BinarySensorDeviceClass.OPENING,
}


def _parse_alarm_fault_objects(
    returns: list[Element],
    expected_label: str | None,
    allowed_labels: set[str] | None = None,
) -> tuple[list[dict[str, str | int | None]], set[str]]:
    """Parse <return> entries from GetAlarmFaultObjectList into structured attributes.

    Only entries whose <label> matches expected_label are returned in the parsed list.
    Labels which differ from expected_label but are part of allowed_labels are ignored
    without warning to avoid false positives when a category groups several labels.

    Args:
        returns: List of <return> elements from the SOAP response body.
        expected_label: Label used to select relevant fault entries for the sensor,
            or None to disable parsing.
        allowed_labels: Set of labels considered valid for the requested category.
            When provided, labels not equal to expected_label but present in this set
            will not be reported as unknown.

    Returns:
        A tuple (parsed, unknown_labels):
          - parsed: list of dicts suitable to expose in entity attributes, each dict contains:
              product_id, product_name, product_type, zone
          - unknown_labels: set of labels seen which are not expected_label and not in allowed_labels
    """
    parsed: list[dict[str, str | int | None]] = []
    unknown: set[str] = set()

    if expected_label is None:
        return parsed, unknown

    for ret in returns:
        lbl_el = ret.find("label")
        label = (
            lbl_el.text.strip() if lbl_el is not None and lbl_el.text else ""
        ) or ""

        if label != expected_label:
            # Accept other known labels from the same category without warning
            if label.startswith("{CLSID-LBL-XXD-FAULTS-"):
                if not allowed_labels or label not in allowed_labels:
                    unknown.add(label)
            continue

        pid_el = ret.find("productId")
        pname_el = ret.find("productName")
        ptype_el = ret.find("productType")
        z_el = ret.find("zone")

        zone_val: int | None = None
        if z_el is not None and z_el.text:
            ztxt = z_el.text.strip()
            try:
                zone_val = int(ztxt)
            except ValueError:
                zone_val = None

        parsed.append(
            {
                "product_id": pid_el.text.strip()
                if (pid_el is not None and pid_el.text)
                else "",
                "product_name": (
                    pname_el.text.strip()
                    if (pname_el is not None and pname_el.text)
                    else ""
                ),
                "product_type": (
                    ptype_el.text.strip()
                    if (ptype_el is not None and ptype_el.text)
                    else ""
                ),
                "zone": zone_val,
            }
        )

    return parsed, unknown


def _parse_alarm_history_objects(returns: list[Element]) -> list[dict[str, str]]:
    """Parse alarm history items into attribute-ready dictionaries.

    This helper converts the <return> elements produced by the alarm history request
    into a list of dictionaries suitable for exposure through entity attributes.

    The 'index' field is intentionally ignored as it is redundant when the result is
    exposed as a list. Empty or missing values are skipped.

    Args:
        returns: List of <return> XML elements from the response body.

    Returns:
        A list of dictionaries where each dictionary contains the non-empty child
        tags of a single <return> element, excluding 'index'.
    """
    parsed: list[dict[str, str]] = []

    for ret in returns:
        event: dict[str, str] = {}
        for child in list(ret):
            tag = child.tag
            if tag == "index":
                continue
            if child.text is None:
                continue
            value = child.text.strip()
            if value:
                event[tag] = value

        if event:
            parsed.append(event)

    return parsed


def _device_class_from_string(name: str | None) -> BinarySensorDeviceClass | None:
    """Return BinarySensorDeviceClass from its standard string value, or None on invalid input.

    The alarm module stores device class as a string to avoid import cycles.
    This helper converts those strings (e.g. 'battery', 'tamper') into the HA enum.
    """
    if not name:
        return None
    try:
        # BinarySensorDeviceClass members have string values (e.g. 'battery');
        # constructing the enum from the value is supported.
        return BinarySensorDeviceClass(name)
    except ValueError:
        return None


@dataclass(slots=True)
class LdDetectorDevice:
    """Container for a parsed Lifedomus binary sensor."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str
    is_on: bool | None  # None means unknown


def _parse_detector_device_element(
    api: LifedomusApi, dev_el: Element
) -> LdDetectorDevice | None:
    """Parse a <device> element returned by GetDevicesFromCatg into a sensor snapshot."""
    device_key = api.txt("device_key", dev_el)
    if not device_key:
        return None

    device_clsid = api.txt("device_clsid", dev_el)
    label = api.txt("label", dev_el) or device_key
    room_label = api.txt("room_label", dev_el)

    result: bool | None = None
    states_el = dev_el.find("./states")
    if states_el is not None:
        triggered_el: Element | None = None
        for st in states_el.findall("./state"):
            if api.txt("state_clsid", st) == LD_STATE_TRIGGERED:
                triggered_el = st
                break

        if triggered_el is not None:
            val_txt = api.txt_path(triggered_el, "./values/value/value")
            if val_txt is None:
                result = None
            else:
                txt = val_txt.lower()
                result = True if txt == "true" else False if txt == "false" else None
        else:
            for st_el in states_el.findall("./state"):
                st_type = api.txt("type", st_el).upper()
                if st_type != "BOOLEAN":
                    continue
                val_txt = api.txt_path(st_el, "./values/value/value")
                if val_txt is None:
                    continue
                txt = val_txt.lower()
                if txt in {"true", "false"}:
                    result = txt == "true"
                    break

    return LdDetectorDevice(
        device_key=device_key,
        device_clsid=device_clsid,
        label=label,
        room_label=room_label,
        is_on=result,
    )


DETECTOR_COORDINATOR_CONFIG: Final[LdCoordinatorConfig[LdDetectorDevice]] = (
    LdCoordinatorConfig(
        name="Lifedomus binary sensor coordinator",
        category_clsid=LdDeviceCategory.SURVEILLANCE_DETECTOR,
        parse_device=_parse_detector_device_element,
    )
)


class LifedomusBinarySensor(LifedomusEntity[LdDetectorDevice], BinarySensorEntity):
    """Lifedomus detector entity."""

    def __init__(
        self,
        coordinator: LdCoordinator[LdDetectorDevice],
        device: LdDetectorDevice,
        runtime: LifedomusRuntimeData,
    ) -> None:
        """Initialize the detector entity."""
        super().__init__(coordinator, device, runtime)
        self._attr_unique_id = device.device_key
        self._attr_device_class = DEVICE_CLASS_BY_CLSID.get(device.device_clsid)
        self._apply_device_snapshot(device)

    def _apply_device_snapshot(self, device: LdDetectorDevice) -> None:
        """Copy the label and boolean state from the snapshot."""
        self._attr_name = device.label
        self._attr_is_on = device.is_on


class LifedomusHeatingDemandBinarySensor(
    LifedomusEntity[LdClimateDevice], BinarySensorEntity
):
    """Heat demand indicator of a heating channel (CLSID-DEVC-A-CC15).

    The device only reports the boolean state CLSID-STATE-DEVC-FLOOR-HEATING
    and exposes no actuator, so it is read through the shared climate
    coordinator and exposed as a single entity named after the device.
    """

    _attr_has_entity_name = True
    _attr_name = None
    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(
        self,
        coordinator: LdCoordinator[LdClimateDevice],
        device: LdClimateDevice,
        runtime: LifedomusRuntimeData,
    ) -> None:
        """Initialize the heat demand entity."""
        super().__init__(coordinator, device, runtime)
        self._attr_unique_id = device.device_key
        self._apply_device_snapshot(device)

    def _apply_device_snapshot(self, device: LdClimateDevice) -> None:
        """Copy the heat demand flag from the snapshot."""
        self._attr_is_on = device.is_heating


class LifedomusAlarmBinarySensor(LifedomusEntity[LdAlarmDevice], BinarySensorEntity):
    """Alarm boolean state as a binary sensor with type-specific icon and detail attributes.

    Warning states tied to a fault label expose the matching fault objects in the
    'items' attribute; the unacknowledged events state exposes the alarm history
    entries. Details are fetched only while the state is active.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: LdCoordinator[LdAlarmDevice],
        device: LdAlarmDevice,
        runtime: LifedomusRuntimeData,
        state_clsid: str,
        definition: AlarmBoolDef,
    ) -> None:
        """Initialize the alarm boolean entity."""
        super().__init__(coordinator, device, runtime)
        self._api = runtime.api
        self._site_key = runtime.site_key
        self._alarm_code = runtime.alarm_code
        self._state_clsid = state_clsid
        self._definition = definition

        self._fault_label = definition.fault_label
        self._fault_category = (
            ALARM_FAULT_LABEL_TO_CATEGORY.get(definition.fault_label)
            if definition.fault_label
            else None
        )
        self._tracks_faults = self._fault_category is not None
        self._tracks_history = state_clsid == LD_STATE_ALARM_WARN_EVENTS_UNACKNOWLEDGED
        self._items: list[dict[str, str | int | None]] | list[dict[str, str]] = []
        self._items_lock = asyncio.Lock()

        self._attr_unique_id = f"{device.device_key}::{state_clsid}"
        self._attr_translation_key = definition.translation_key
        self._attr_device_class = _device_class_from_string(definition.device_class)
        self._apply_device_snapshot(device)

    def _apply_device_snapshot(self, device: LdAlarmDevice) -> None:
        """Copy the boolean state and derive the matching icon."""
        self._attr_is_on = device.bool_states.get(self._state_clsid)
        self._attr_icon = (
            "mdi:help-circle-outline"
            if self._attr_is_on is None
            else self._definition.icon_on
            if self._attr_is_on
            else self._definition.icon_off
        )

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose the detail items while the state is active."""
        if self._attr_is_on is True and (self._tracks_faults or self._tracks_history):
            return {"items": list(self._items)}
        return {}

    def _schedule_details_refresh(self) -> None:
        """Schedule the background refresh of the detail items when supported."""
        if self._tracks_faults:
            self.hass.async_create_task(self._async_refresh_fault_objects())
        elif self._tracks_history:
            self.hass.async_create_task(self._async_refresh_unacknowledged_events())

    @callback
    def _handle_coordinator_update(self) -> None:
        """Apply the snapshot, then refresh the detail items."""
        super()._handle_coordinator_update()
        self._schedule_details_refresh()

    async def async_added_to_hass(self) -> None:
        """Populate the detail items once the entity is registered."""
        await super().async_added_to_hass()
        self._schedule_details_refresh()

    def _can_fetch_details(self) -> bool:
        """Return True when the state is active and the access context is complete."""
        return self._attr_is_on is True and bool(self._site_key and self._alarm_code)

    async def _async_refresh_fault_objects(self) -> None:
        """Refresh the fault objects of the current warning state.

        The cache is cleared when the state is inactive or the access context
        is missing, so stale objects are never exposed.
        """
        async with self._items_lock:
            if not self._can_fetch_details():
                self._items = []
                return
            try:
                returns = await self._api.async_request(
                    namespace="Mobile",
                    action="GetAlarmFaultObjectList",
                    params={
                        "site_key": self._site_key,
                        "device_key": self._device_key,
                        "access_code": self._alarm_code,
                        "category": self._fault_category,
                        "rowIndex": 0,
                        "count": LD_DEFAULT_ITEMS_LIMIT,
                    },
                )
            except LifedomusApiError as err:
                _LOGGER.debug(
                    "Failed to fetch alarm faults (%s/%s) for %s: %s",
                    self._fault_category,
                    self._fault_label,
                    self._device_key,
                    err,
                )
                return

            parsed, unknown = _parse_alarm_fault_objects(
                returns,
                expected_label=self._fault_label,
                allowed_labels={
                    label
                    for label, category in ALARM_FAULT_LABEL_TO_CATEGORY.items()
                    if category == self._fault_category
                },
            )
            if unknown:
                _LOGGER.warning(
                    "Unknown alarm fault label(s) for %s in category %s: %s",
                    self._device_key,
                    self._fault_category,
                    ", ".join(sorted(unknown)),
                )
            self._items = parsed
        self.async_write_ha_state()

    async def _async_refresh_unacknowledged_events(self) -> None:
        """Refresh the unacknowledged alarm history entries.

        The cache is cleared when the state is inactive or the access context
        is missing, so stale events are never exposed.
        """
        async with self._items_lock:
            if not self._can_fetch_details():
                self._items = []
                return
            try:
                returns = await self._api.async_request(
                    namespace="Mobile",
                    action="GetAlarmHistoryObjectList",
                    params={
                        "site_key": self._site_key,
                        "device_key": self._device_key,
                        "access_code": self._alarm_code,
                        "category": "UNACKNOWLEDGED",
                        "rowIndex": 0,
                        "count": LD_DEFAULT_ITEMS_LIMIT,
                    },
                )
            except LifedomusApiError as err:
                _LOGGER.debug(
                    "Failed to fetch unacknowledged alarm history for %s: %s",
                    self._device_key,
                    err,
                )
                return
            self._items = _parse_alarm_history_objects(returns)
        self.async_write_ha_state()


class LifedomusSystemVariableBinarySensor(
    LifedomusSystemVariableEntity, BinarySensorEntity
):
    """Boolean system variable of the hub."""

    def __init__(self, entry: LifedomusConfigEntry, variable_key: str) -> None:
        """Initialize the entity and apply the configured device class."""
        super().__init__(entry, variable_key)
        if isinstance(self._config.sensor_class, BinarySensorDeviceClass):
            self._attr_device_class = self._config.sensor_class

    def _apply_value(self, value: SystemVariableValue) -> None:
        """Accept boolean values only; anything else leaves the state unknown."""
        self._attr_is_on = value if isinstance(value, bool) else None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LifedomusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Lifedomus binary_sensor platform from a config entry."""
    runtime = entry.runtime_data
    entities: list[BinarySensorEntity] = [
        LifedomusBinarySensor(runtime.detector, device, runtime)
        for device in runtime.detector.data.values()
    ]
    entities.extend(
        LifedomusAlarmBinarySensor(
            runtime.alarm, device, runtime, state_clsid, definition
        )
        for device in runtime.alarm.data.values()
        for state_clsid, definition in ALARM_BOOL_STATES.items()
        if state_clsid in device.bool_states
    )
    entities.extend(
        LifedomusHeatingDemandBinarySensor(runtime.climate, device, runtime)
        for device in runtime.climate.data.values()
        if device.device_clsid == LD_DEVICE_TYPE_FLOOR_HEATING
    )
    entities.extend(
        LifedomusSystemVariableBinarySensor(entry, variable_key)
        for variable_key, config in LD_CLSID_SYSTEM_VARIABLES.items()
        if config.value_type is bool
    )
    async_add_entities(entities)
