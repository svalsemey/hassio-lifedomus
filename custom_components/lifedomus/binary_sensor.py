"""Binary sensor platform for Lifedomus.

This platform queries the Lifedomus gateway for all detectors in the "detector"
category (CLSID-DEVC-S-DT) and exposes them as Home Assistant binary_sensor entities.
It also exposes alarm boolean states for devices in "alarm" category (CLSID-DEVC-S-PR)
as binary sensors attached to the alarm device.

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
from collections.abc import Callable
from dataclasses import dataclass
import logging
from typing import Final
from xml.etree.ElementTree import Element

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .alarm import (
    ALARM_BOOL_STATES,
    ALARM_FAULT_LABEL_TO_CATEGORY,
    AlarmBoolDef,
    LdAlarmDevice,
    get_or_create_alarm_coordinator,
)
from .api import LifedomusApi, LifedomusApiError
from .const import (
    CONF_ALARM_CODE,
    CONF_SITE_KEY,
    DOMAIN,
    LD_CLSID_DEVICE_TYPE_SENSOR,
    LD_STATE_TRIGGERED,
)
from .coordinator import LdCoordinator, LdCoordinatorConfig
from .helpers import EntityDependencies, build_device_info, get_update_interval

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
class _LdBinarySensor:
    """Container for a parsed Lifedomus binary sensor."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str
    is_on: bool | None  # None means unknown


def _parse_binary_sensor_device_element(
    api: LifedomusApi, dev_el: Element
) -> _LdBinarySensor | None:
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

    return _LdBinarySensor(
        device_key=device_key,
        device_clsid=device_clsid,
        label=label,
        room_label=room_label,
        is_on=result,
    )


class LifedomusBinarySensor(BinarySensorEntity):
    """Lifedomus binary sensor entity."""

    _attr_should_poll = False

    def __init__(
        self,
        coordinator: LdCoordinator[_LdBinarySensor],
        dependencies: EntityDependencies,
        device: _LdBinarySensor,
    ) -> None:
        """Initialize the binary sensor entity and attach the coordinator by composition."""
        super().__init__()
        self.coordinator = coordinator

        self._attr_unique_id = device.device_key
        self._attr_name = device.label
        self._attr_device_class = DEVICE_CLASS_BY_CLSID.get(device.device_clsid)

        self._attr_device_info = build_device_info(
            device_key=self._attr_unique_id,
            device_clsid=device.device_clsid,
            label=self._attr_name,
            room_label=device.room_label,
            uuid=dependencies.uuid,
        )

        self._apply_device_snapshot(device)

    def _apply_device_snapshot(self, device: _LdBinarySensor) -> None:
        """Apply the coordinator snapshot to HA attributes."""
        self._attr_name = device.label
        self._attr_is_on = device.is_on

    @property
    def _dev(self) -> _LdBinarySensor | None:
        """Return the current device snapshot from the coordinator."""
        if self._attr_unique_id is None:
            return None
        return self.coordinator.data.get(self._attr_unique_id)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle state update from the coordinator."""
        device = self._dev
        if device is not None:
            self._apply_device_snapshot(device)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register coordinator update listener and publish initial state."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        device = self._dev
        if device is not None:
            self._apply_device_snapshot(device)
        self.async_write_ha_state()


class LifedomusAlarmBinarySensor(BinarySensorEntity):
    """Alarm boolean state as a binary sensor with type-specific icon and FAULT attributes."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: LdCoordinator,
        dependencies: EntityDependencies,
        device: LdAlarmDevice,
        state_clsid: str,
        definition: AlarmBoolDef,
    ) -> None:
        """Initialize the alarm boolean entity."""
        super().__init__()
        self.coordinator = coordinator
        self._api = dependencies.api
        self._device_key = device.device_key
        self._state_clsid = state_clsid
        self._definition = definition

        # Access context for GetAlarmFaultObjectList
        self._site_key: str = str(dependencies.entry.data.get(CONF_SITE_KEY) or "")
        self._alarm_code: str = str(
            dependencies.entry.data.get(CONF_ALARM_CODE, "") or ""
        )

        # Faults-related fields
        self._fault_label: str | None = definition.fault_label
        self._fault_category: str | None = (
            ALARM_FAULT_LABEL_TO_CATEGORY.get(self._fault_label)
            if self._fault_label
            else None
        )
        self._fault_objects: list[dict[str, str | int | None]] = []
        self._fault_lock = asyncio.Lock()

        self._attr_unique_id = f"{device.device_key}::{state_clsid}"
        self._attr_translation_key = definition.translation_key

        # Convert string device class (from AlarmBoolDef) to BinarySensorDeviceClass when available.
        self._attr_device_class = _device_class_from_string(definition.device_class)

        self._attr_device_info = build_device_info(
            device_key=device.device_key,
            device_clsid=device.device_clsid,
            label=device.label,
            room_label=device.room_label,
            uuid=dependencies.uuid,
        )

        val = device.bool_states.get(state_clsid)
        self._attr_is_on = val
        self._attr_icon = self._resolve_icon(self._definition, val)

    @staticmethod
    def _resolve_icon(definition: AlarmBoolDef, is_on: bool | None) -> str:
        """Return a state-specific icon for the given alarm boolean."""
        if is_on is None:
            return "mdi:help-circle-outline"
        return definition.icon_on if is_on else definition.icon_off

    @property
    def _dev(self) -> LdAlarmDevice | None:
        """Return the current alarm device snapshot."""
        return self.coordinator.data.get(self._device_key)

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose fault attributes parsed from GetAlarmFaultObjectList for supported states.

        When this sensor is associated with a FAULT label, the following attributes are exposed:
         - fault_count: number of matching fault objects
         - fault_objects: list of objects with keys: product_id, product_name, product_type, zone
        Otherwise, no extra attributes are returned.
        """
        if not self._fault_label:
            return {}
        return {
            "fault_count": len(self._fault_objects),
            "fault_objects": list(self._fault_objects),
        }

    async def _async_refresh_fault_objects(self) -> None:
        """Fetch and parse fault objects for the associated category and update attributes.

        This method is called on each coordinator update (poll) and whenever the entity state updates.
        It requires:
         - a known mapping label for this state,
         - a resolvable category,
         - valid site key and alarm access code to authorize the request.
        """
        if not self._fault_label or not self._fault_category:
            return

        # Missing auth context: clear attributes to avoid stale exposure
        if not self._site_key or not self._alarm_code or not self._device_key:
            async with self._fault_lock:
                self._fault_objects.clear()
            return

        async with self._fault_lock:
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
                        "count": 7,
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

            # Build the set of allowed labels for this category to avoid false "unknown" warnings
            allowed_labels: set[str] = {
                lbl
                for lbl, cat in ALARM_FAULT_LABEL_TO_CATEGORY.items()
                if cat == self._fault_category
            }

            parsed, unknown = _parse_alarm_fault_objects(
                returns,
                expected_label=self._fault_label,
                allowed_labels=allowed_labels,
            )
            if unknown:
                _LOGGER.warning(
                    "Unknown alarm fault label(s) for %s in category %s: %s",
                    self._device_key,
                    self._fault_category,
                    ", ".join(sorted(unknown)),
                )

            # Update attributes and publish
            self._fault_objects = parsed
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle state update from the coordinator and refresh fault attributes."""
        device = self._dev
        if device is not None:
            val = device.bool_states.get(self._state_clsid)
            self._attr_is_on = val
            self._attr_icon = self._resolve_icon(self._definition, val)

        # Schedule a fault refresh on each coordinator update for supported states.
        if self._fault_label and self._fault_category:
            self.hass.async_create_task(self._async_refresh_fault_objects())

        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register coordinator update listener, publish initial state and refresh faults."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        # Initial fault fetch when supported.
        if self._fault_label and self._fault_category:
            self.hass.async_create_task(self._async_refresh_fault_objects())
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Callable[[list[BinarySensorEntity]], None],
) -> None:
    """Set up the Lifedomus binary_sensor platform from a config entry."""
    api: LifedomusApi = entry.runtime_data

    # Detectors coordinator
    cfg = LdCoordinatorConfig[_LdBinarySensor](
        name="Lifedomus binary sensor coordinator",
        update_interval=get_update_interval(entry),
        category_clsid=LD_CLSID_DEVICE_TYPE_SENSOR,
        parse_device=_parse_binary_sensor_device_element,
    )
    binary_sensor_coordinator = LdCoordinator(hass, api, cfg)
    await binary_sensor_coordinator.async_config_entry_first_refresh()
    shared = hass.data.setdefault(DOMAIN, {})
    shared["binary_sensor_coordinator"] = binary_sensor_coordinator

    # Shared alarm coordinator (create or reuse)
    alarm_coordinator: LdCoordinator
    shared = hass.data.setdefault(DOMAIN, {})
    alarm_coordinator = await get_or_create_alarm_coordinator(hass, api, entry)
    shared["alarm_coordinator"] = alarm_coordinator

    dependencies = EntityDependencies(
        api=api, entry=entry, uuid=str(hass.data[DOMAIN].get("uuid", ""))
    )

    # Build detector entities via list comprehension.
    detector_entities = [
        LifedomusBinarySensor(binary_sensor_coordinator, dependencies, device)
        for device in binary_sensor_coordinator.data.values()
    ]

    # Build alarm boolean entities via list comprehension.
    alarm_entities = [
        LifedomusAlarmBinarySensor(
            alarm_coordinator, dependencies, dev, stid, definition
        )
        for dev in alarm_coordinator.data.values()
        for stid, definition in ALARM_BOOL_STATES.items()
        if stid in dev.bool_states
    ]

    # Merge into a single list while preserving BinarySensorEntity typing.
    entities: list[BinarySensorEntity] = []
    entities.extend(detector_entities)
    entities.extend(alarm_entities)

    async_add_entities(entities)
