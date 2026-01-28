"""Alarm shared coordinator and models for Lifedomus.

Parses alarm devices (category CLSID-DEVC-S-PR) and exposes a snapshot
containing boolean states, operating mode, and zone list with labels.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Final
from xml.etree.ElementTree import Element

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import LifedomusApi, parse_bool
from .const import (
    DOMAIN,
    LD_CLSID_DEVICE_TYPE_SENSOR_ALARM,
    LD_LABEL_FAULT_BATTERY,
    LD_LABEL_FAULT_INHIBITION,
    LD_LABEL_FAULT_INTRUSION,
    LD_LABEL_FAULT_IP,
    LD_LABEL_FAULT_MONITORING,
    LD_LABEL_FAULT_POWER,
    LD_LABEL_FAULT_SELFPROTECTION,
    LD_LABEL_FAULT_TECHNICAL,
    LD_PROP_ALARM_EVENTS_ACKNOWLEDGE,
    LD_PROP_ALARM_OPERATINGMODE,
    LD_PROP_ALARM_ZONE_SW,
    LD_STATE_ALARM_ALERT_DELAYED,
    LD_STATE_ALARM_ALERT_SILENT,
    LD_STATE_ALARM_INTRUSION,
    LD_STATE_ALARM_OPERATINGMODE,
    LD_STATE_ALARM_WARN_BATTERY,
    LD_STATE_ALARM_WARN_EVENTS_UNACKNOWLEDGED,
    LD_STATE_ALARM_WARN_INHIBITED,
    LD_STATE_ALARM_WARN_MONITORING,
    LD_STATE_ALARM_WARN_OPENENTRANCES,
    LD_STATE_ALARM_WARN_POWER,
    LD_STATE_ALARM_WARN_REMOTE_COMMUNICATION,
    LD_STATE_ALARM_WARN_REMOTE_MONITORING,
    LD_STATE_ALARM_WARN_REMOVAL,
    LD_STATE_ALARM_WARN_SIM,
    LD_STATE_ALARM_WARN_TAMPERING,
    LD_STATE_ALARM_WARN_TECHNICALFAULT,
    LD_STATE_ALARM_WARN_VIDEO_LINK,
    LD_STATE_ALARM_ZONESTATUS,
    LD_STATE_TRIGGERED,
    LD_VALUE_ALARM_MODE_ARMED_FULL,
    LD_VALUE_ALARM_MODE_ARMED_PARTIAL,
    LD_VALUE_ALARM_MODE_MAINTENANCE,
    LD_VALUE_ALARM_MODE_STOP,
)
from .coordinator import LdCoordinator, LdCoordinatorConfig
from .helpers import get_update_interval

# Mapping from FAULT label returned by GetAlarmFaultObjectList to request category.
ALARM_FAULT_LABEL_TO_CATEGORY: Final[dict[str, str]] = {
    LD_LABEL_FAULT_BATTERY: "OTHERS",
    LD_LABEL_FAULT_INHIBITION: "INHIBITIONS",
    LD_LABEL_FAULT_INTRUSION: "OPEN_ENTRANCE",
    LD_LABEL_FAULT_IP: "OTHERS",
    LD_LABEL_FAULT_MONITORING: "OTHERS",
    LD_LABEL_FAULT_POWER: "OTHERS",
    LD_LABEL_FAULT_SELFPROTECTION: "SELF_PROTECTIONS",
    LD_LABEL_FAULT_TECHNICAL: "OTHERS",
}

# Icon mapping for alarm operating modes.
ALARM_OPERATING_MODE_ICON_BY_VALUE: Final[dict[str, str]] = {
    LD_VALUE_ALARM_MODE_ARMED_FULL: "mdi:shield",
    LD_VALUE_ALARM_MODE_MAINTENANCE: "mdi:wrench",
    LD_VALUE_ALARM_MODE_ARMED_PARTIAL: "mdi:shield-half-full",
    LD_VALUE_ALARM_MODE_STOP: "mdi:shield-off-outline",
}


_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AlarmBoolDef:
    """Definition for an alarm boolean state mapping.

    Fields:
        translation_key: Key used by the translation files for the entity name.
        device_class: Binary sensor device class name (string value) or None.
        icon_on: Icon to display when the state is True.
        icon_off: Icon to display when the state is False.
        fault_label: Associated FAULT label used to fetch fault objects, or None.
    """

    translation_key: str
    device_class: str | None
    icon_on: str
    icon_off: str
    fault_label: str | None


# Unified mapping for alarm-related boolean states.
ALARM_BOOL_STATES: Final[dict[str, AlarmBoolDef]] = {
    LD_STATE_ALARM_ALERT_DELAYED: AlarmBoolDef(
        translation_key="state_alarm_alert_delayed",
        device_class=None,
        icon_on="mdi:timer-outline",
        icon_off="mdi:timer-alert",
        fault_label=None,
    ),
    LD_STATE_ALARM_ALERT_SILENT: AlarmBoolDef(
        translation_key="state_alarm_alert_silent",
        device_class=None,
        icon_on="mdi:bell-off",
        icon_off="mdi:bell",
        fault_label=None,
    ),
    LD_STATE_ALARM_INTRUSION: AlarmBoolDef(
        translation_key="state_alarm_intrusion",
        device_class=None,
        icon_on="mdi:home-alert",
        icon_off="mdi:home-outline",
        fault_label=None,
    ),
    LD_STATE_ALARM_WARN_BATTERY: AlarmBoolDef(
        translation_key="state_alarm_warn_battery",
        device_class="battery",
        icon_on="mdi:battery-alert",
        icon_off="mdi:battery",
        fault_label=LD_LABEL_FAULT_BATTERY,
    ),
    LD_STATE_ALARM_WARN_EVENTS_UNACKNOWLEDGED: AlarmBoolDef(
        translation_key="state_alarm_warn_event_unacknowledged",
        device_class="problem",
        icon_on="mdi:bell-outline",
        icon_off="mdi:bell-alert",
        fault_label=None,
    ),
    LD_STATE_ALARM_WARN_INHIBITED: AlarmBoolDef(
        translation_key="state_alarm_warn_products_inhibited",
        device_class=None,
        icon_on="mdi:cancel",
        icon_off="mdi:check-circle-outline",
        fault_label=LD_LABEL_FAULT_INHIBITION,
    ),
    LD_STATE_ALARM_WARN_MONITORING: AlarmBoolDef(
        translation_key="state_alarm_warn_monitoring",
        device_class="problem",
        icon_on="mdi:access-point-remove",
        icon_off="mdi:access-point-check",
        fault_label=LD_LABEL_FAULT_MONITORING,
    ),
    LD_STATE_ALARM_WARN_OPENENTRANCES: AlarmBoolDef(
        translation_key="state_alarm_warn_entrances_open",
        device_class="opening",
        icon_on="mdi:door-open",
        icon_off="mdi:door-closed",
        fault_label=LD_LABEL_FAULT_INTRUSION,
    ),
    LD_STATE_ALARM_WARN_POWER: AlarmBoolDef(
        translation_key="state_alarm_warn_power",
        device_class="problem",
        icon_on="mdi:power-plug-off",
        icon_off="mdi:power-plug",
        fault_label=LD_LABEL_FAULT_POWER,
    ),
    LD_STATE_ALARM_WARN_REMOTE_COMMUNICATION: AlarmBoolDef(
        translation_key="state_alarm_warn_telecommunication",
        device_class="problem",
        icon_on="mdi:lan-disconnect",
        icon_off="mdi:lan-connect",
        fault_label=LD_LABEL_FAULT_IP,
    ),
    LD_STATE_ALARM_WARN_REMOTE_MONITORING: AlarmBoolDef(
        translation_key="state_alarm_warn_telemonitoring",
        device_class="problem",
        icon_on="mdi:account-eye",
        icon_off="mdi:account-eye-outline",
        fault_label=None,
    ),
    LD_STATE_ALARM_WARN_REMOVAL: AlarmBoolDef(
        translation_key="state_alarm_warn_removal_doubt",
        device_class="tamper",
        icon_on="mdi:shield-alert",
        icon_off="mdi:shield-check",
        fault_label=None,
    ),
    LD_STATE_ALARM_WARN_SIM: AlarmBoolDef(
        translation_key="state_alarm_warn_sim",
        device_class="problem",
        icon_on="mdi:sim-alert",
        icon_off="mdi:sim",
        fault_label=None,
    ),
    LD_STATE_ALARM_WARN_TAMPERING: AlarmBoolDef(
        translation_key="state_alarm_warn_self_protection",
        device_class="tamper",
        icon_on="mdi:shield-alert",
        icon_off="mdi:shield-check",
        fault_label=LD_LABEL_FAULT_SELFPROTECTION,
    ),
    LD_STATE_ALARM_WARN_TECHNICALFAULT: AlarmBoolDef(
        translation_key="state_alarm_warn_fault_technical",
        device_class="problem",
        icon_on="mdi:alert-circle",
        icon_off="mdi:check-circle-outline",
        fault_label=LD_LABEL_FAULT_TECHNICAL,
    ),
    LD_STATE_ALARM_WARN_VIDEO_LINK: AlarmBoolDef(
        translation_key="state_alarm_warn_link_video",
        device_class="problem",
        icon_on="mdi:video-off",
        icon_off="mdi:video-check",
        fault_label=None,
    ),
    LD_STATE_TRIGGERED: AlarmBoolDef(
        translation_key="state_triggered",
        device_class=None,
        icon_on="mdi:alarm-light",
        icon_off="mdi:alarm-light-off",
        fault_label=None,
    ),
}


@dataclass(slots=True)
class AlarmZone:
    """Represent a single alarm zone entry."""

    index: int
    label: str
    enabled: bool | None


@dataclass(slots=True)
class LdAlarmDevice:
    """Container for a parsed Lifedomus alarm device."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str

    # Boolean states mapping: state_clsid -> bool|None
    bool_states: dict[str, bool | None]
    # Operating mode text (e.g., STOP)
    operating_mode: str | None

    # Zones exposed by CLSID-STATE-ALARM-ZONESTATUS
    zones: list[AlarmZone]

    # Related properties for actions
    prop_operating_mode: str | None
    prop_zone_sw: str | None
    prop_ack_events: str | None

    available: bool


def _parse_alarm_action_properties(
    api: LifedomusApi, dev_el: Element
) -> tuple[str | None, str | None, str | None]:
    """Extract alarm-related property CLSIDs from the device actions."""
    prop_operating_mode: str | None = None
    prop_zone_sw: str | None = None
    prop_ack_events: str | None = None

    for action_el in dev_el.findall("./actions/action"):
        prop_clsid = api.txt("prop_clsid", action_el)
        if not prop_clsid:
            continue

        if prop_clsid == LD_PROP_ALARM_OPERATINGMODE:
            if prop_operating_mode is None:
                prop_operating_mode = prop_clsid
            continue

        if prop_clsid == LD_PROP_ALARM_ZONE_SW:
            if prop_zone_sw is None:
                prop_zone_sw = prop_clsid
            continue

        if prop_clsid == LD_PROP_ALARM_EVENTS_ACKNOWLEDGE and prop_ack_events is None:
            prop_ack_events = prop_clsid

    return prop_operating_mode, prop_zone_sw, prop_ack_events


def _parse_alarm_zone_status(api: LifedomusApi, st_el: Element) -> list[AlarmZone]:
    """Parse the list of zones from a ZONESTATUS state element."""
    zones: list[AlarmZone] = []
    for v_el in st_el.findall("./values/value"):
        idx_text = api.txt_path(v_el, "index")
        if not idx_text:
            continue
        try:
            idx = int(idx_text)
        except ValueError:
            continue

        value_txt = api.txt_path(v_el, "value")
        enabled = parse_bool(value_txt) if value_txt is not None else None
        zlabel = api.txt_path(v_el, "label") or f"Zone {idx}"
        zones.append(AlarmZone(index=idx, label=zlabel, enabled=enabled))
    return zones


def _parse_alarm_states(
    api: LifedomusApi, dev_el: Element
) -> tuple[dict[str, bool | None], str | None, list[AlarmZone]]:
    """Parse boolean states, operating mode and zones."""
    bool_states: dict[str, bool | None] = {}
    operating_mode: str | None = None
    zones: list[AlarmZone] = []

    states_el = dev_el.find("./states")
    if states_el is None:
        return bool_states, operating_mode, zones

    for st_el in states_el.findall("./state"):
        st_clsid = api.txt("state_clsid", st_el)
        if not st_clsid:
            continue

        if st_clsid in ALARM_BOOL_STATES:
            val_txt = api.txt_path(st_el, "./values/value/value")
            val = parse_bool(val_txt) if val_txt is not None else None
            bool_states[st_clsid] = val
            continue

        if st_clsid == LD_STATE_ALARM_OPERATINGMODE:
            operating_mode = api.txt_path(st_el, "./values/value/value")
            continue

        if st_clsid == LD_STATE_ALARM_ZONESTATUS:
            zones.extend(_parse_alarm_zone_status(api, st_el))

    zones.sort(key=lambda z: z.index)
    return bool_states, operating_mode, zones


def _parse_alarm_device_element(
    api: LifedomusApi, dev_el: Element
) -> LdAlarmDevice | None:
    """Parse a <device> element into an LdAlarmDevice snapshot."""
    device_key = api.txt("device_key", dev_el)
    if not device_key:
        return None

    device_clsid = api.txt("device_clsid", dev_el)
    label = api.txt("label", dev_el) or device_key
    room_label = api.txt("room_label", dev_el)

    prop_operating_mode, prop_zone_sw, prop_ack_events = _parse_alarm_action_properties(
        api, dev_el
    )
    bool_states, operating_mode, zones = _parse_alarm_states(api, dev_el)

    return LdAlarmDevice(
        device_key=device_key,
        device_clsid=device_clsid,
        label=label,
        room_label=room_label,
        bool_states=bool_states,
        operating_mode=operating_mode,
        zones=zones,
        prop_operating_mode=prop_operating_mode,
        prop_zone_sw=prop_zone_sw,
        prop_ack_events=prop_ack_events,
        available=True,
    )


class LifedomusAlarmCoordinator(LdCoordinator[LdAlarmDevice]):
    """Typed alias maintained for backward imports."""

    # No custom behavior; inherits everything from LdCoordinator.


async def get_or_create_alarm_coordinator(
    hass: HomeAssistant, api: LifedomusApi, entry: ConfigEntry
) -> LifedomusAlarmCoordinator:
    """Return the shared alarm coordinator, creating and refreshing it if missing."""
    shared = hass.data.setdefault(DOMAIN, {})
    coord = shared.get("alarm_coordinator")
    if isinstance(coord, LifedomusAlarmCoordinator):
        return coord

    cfg = LdCoordinatorConfig[LdAlarmDevice](
        name="Lifedomus alarm coordinator",
        update_interval=get_update_interval(entry),
        category_clsid=LD_CLSID_DEVICE_TYPE_SENSOR_ALARM,
        parse_device=_parse_alarm_device_element,
    )
    coord = LifedomusAlarmCoordinator(hass, api, cfg)
    await coord.async_config_entry_first_refresh()
    shared["alarm_coordinator"] = coord
    return coord
