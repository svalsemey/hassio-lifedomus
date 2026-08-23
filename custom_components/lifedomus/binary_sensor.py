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
from datetime import date, datetime
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
    LD_CLSID_SYSTEM_VARIABLES,
    LD_DEFAULT_ITEMS_LIMIT,
    LD_STATE_ALARM_WARN_EVENTS_UNACKNOWLEDGED,
    LD_STATE_TRIGGERED,
    LD_SYSTEM_VAR_WEB_STATUS,
    MODEL,
    LdDeviceCategory,
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

        self._history_events: list[dict[str, str]] = []
        self._history_lock = asyncio.Lock()

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
        """Expose alarm extra attributes for supported warning states.

        For alarm warning binary sensors, detailed data is exposed through a single
        normalized attribute named 'items'. The content depends on the sensor type:

        - Fault-oriented sensors expose parsed objects associated with the current fault.
        - The unacknowledged events sensor exposes parsed alarm history entries.

        When the binary sensor is not active (state is not True), this property returns
        an empty list for 'items' without triggering any network operation.

        Returns:
            A mapping of extra state attributes. For supported sensors, it includes:
            - items: list of parsed dictionaries representing the detailed objects/events.
        """
        if self._attr_is_on is True:
            if self._fault_label:
                return {"items": list(self._fault_objects)}

            if self._state_clsid == LD_STATE_ALARM_WARN_EVENTS_UNACKNOWLEDGED:
                return {"items": list(self._history_events)}

        return {}

    async def _async_refresh_fault_objects(self) -> None:
        """Refresh fault-related objects for the current alarm warning state.

        When this entity is associated with a fault label and a resolvable fault category,
        this method queries the gateway for the corresponding fault objects and updates
        the local cache used for attribute exposure.

        Network access is performed only when the entity state is active (True). If the
        entity is inactive or required context is missing, the cached objects are cleared
        to prevent exposing stale data.

        This method schedules a state write after updating the cache.

        Returns:
            None.
        """
        if not self._fault_label or not self._fault_category:
            return

        if self._attr_is_on is not True:
            async with self._fault_lock:
                self._fault_objects.clear()
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

    async def _async_refresh_unacknowledged_events(self) -> None:
        """Refresh unacknowledged alarm history events for the alarm device.

        This method fetches the list of unacknowledged alarm history entries and updates
        the local cache used to populate the 'items' attribute.

        Network access is performed only when the entity state is active (True). If the
        entity is inactive or required context is missing, the cached events are cleared
        to prevent exposing stale data.

        The request is performed using the 'UNACKNOWLEDGED' category and a bounded count
        to limit payload size.

        Returns:
            None.
        """
        if self._state_clsid != LD_STATE_ALARM_WARN_EVENTS_UNACKNOWLEDGED:
            return

        if self._attr_is_on is not True:
            async with self._history_lock:
                self._history_events.clear()
            return

        if not self._site_key or not self._alarm_code or not self._device_key:
            async with self._history_lock:
                self._history_events.clear()
            return

        async with self._history_lock:
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

            self._history_events = _parse_alarm_history_objects(returns)
            self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator updates and schedule attribute refresh when needed.

        This callback updates the entity state and icon from the latest coordinator
        snapshot. For supported warning sensors, it also schedules a background refresh
        task responsible for fetching additional details (fault objects or alarm history
        events) only when the entity is active.

        The entity state is written after applying the snapshot update.

        Returns:
            None.
        """
        device = self._dev
        if device is not None:
            val = device.bool_states.get(self._state_clsid)
            self._attr_is_on = val
            self._attr_icon = self._resolve_icon(self._definition, val)

        # Schedule a fault refresh on each coordinator update for supported states.
        if self._fault_label and self._fault_category:
            self.hass.async_create_task(self._async_refresh_fault_objects())

        if self._state_clsid == LD_STATE_ALARM_WARN_EVENTS_UNACKNOWLEDGED:
            self.hass.async_create_task(self._async_refresh_unacknowledged_events())

        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register update listeners and trigger initial refresh for supported attributes.

        This method registers the entity as a listener of the shared coordinator and
        publishes the initial Home Assistant state.

        For supported warning sensors, an initial background refresh is scheduled to
        populate the cached attribute data. Network access is still conditioned by the
        current entity state to avoid unnecessary requests.

        Returns:
            None.
        """
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        # Initial fault fetch when supported.
        if self._fault_label and self._fault_category:
            self.hass.async_create_task(self._async_refresh_fault_objects())
        if self._state_clsid == LD_STATE_ALARM_WARN_EVENTS_UNACKNOWLEDGED:
            self.hass.async_create_task(self._async_refresh_unacknowledged_events())

        self.async_write_ha_state()


class LifedomusSystemVariableBinarySensor(BinarySensorEntity):
    """System variable binary sensor for connectivity status."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "state_system_var_web_status"
    _attr_icon = "mdi:web"

    def __init__(
        self,
        hass: HomeAssistant,
        api: LifedomusApi,
        site_key: str,
        uuid: str,
        variable_key: str,
    ) -> None:
        """Initialize the system variable binary sensor."""
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

        if isinstance(config.sensor_class, BinarySensorDeviceClass):
            self._attr_device_class = config.sensor_class

        self._attr_device_info = build_device_info(
            device_key=uuid,
            device_clsid=MODEL,
            label=MODEL,
            room_label="",
            uuid=uuid,
        )

        self._attr_is_on = None

    def _apply_value(self, value: bool | date | datetime | float | str | None) -> None:
        """Apply and validate a boolean system variable value."""
        if isinstance(value, bool):
            self._attr_is_on = value
        else:
            self._attr_is_on = None

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

    def handle_push_update(self, value: bool | float | str | datetime | None) -> None:
        """Handle a push notification update for this system variable."""
        self._apply_value(value)
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
        category_clsid=LdDeviceCategory.SURVEILLANCE_DETECTOR,
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
        api=api, entry=entry, uuid=str(hass.data.setdefault(DOMAIN, {}).get("uuid", ""))
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

    # Build system variable binary sensor (web status)
    web_status_sensor = LifedomusSystemVariableBinarySensor(
        hass,
        api,
        str(entry.data.get(CONF_SITE_KEY, "")),
        str(hass.data.setdefault(DOMAIN, {}).get("uuid", "")),
        LD_SYSTEM_VAR_WEB_STATUS,
    )

    # Store reference for push updates
    shared = hass.data.setdefault(DOMAIN, {})
    system_binary_sensors = shared.setdefault("system_binary_sensors", {})
    system_binary_sensors[LD_SYSTEM_VAR_WEB_STATUS] = web_status_sensor

    # Merge into a single list while preserving BinarySensorEntity typing.
    entities: list[BinarySensorEntity] = []
    entities.extend(detector_entities)
    entities.extend(alarm_entities)
    entities.append(web_status_sensor)

    async_add_entities(entities)
