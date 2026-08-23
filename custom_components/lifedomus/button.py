"""Lifedomus button platform.

This platform exposes native Lifedomus "Push" buttons found in category
CLSID-DEVC-A-PC. Each entity triggers a CoreServices/ExecuteOneAction with
action_clsid 'CLSID-ACTION-PUSH' on press.

It also exposes 3 alarm actions per alarm device (CLSID-DEVC-S-PR):
 - "Full arming": CLSID-ACTION-ALARM-FULL-ARMING on prop CLSID-DEVC-PROP-ALARM-OPERATING-MODE
 - "Stop": CLSID-ACTION-ALARM-STOP on prop CLSID-DEVC-PROP-ALARM-OPERATING-MODE
 - "Acknowledge events": CLSID-ACTION-ALARM-ACKNOWLEDGE-EVENTS on prop CLSID-DEVC-PROP-ALARM-ACKNOWLEDGE-EVENTS
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import logging
from xml.etree.ElementTree import Element

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .alarm import LdAlarmDevice, get_or_create_alarm_coordinator
from .api import LifedomusApi, LifedomusApiError, build_action_descriptor
from .const import (
    CONF_ALARM_CODE,
    CONF_SITE_KEY,
    CONF_USER_KEY,
    DOMAIN,
    LD_ACTION_ALARM_EVENTS_ACKNOWLEDGE,
    LD_ACTION_ALARM_FULL_ARMING,
    LD_ACTION_ALARM_STOP,
    LD_ACTION_PUSH,
    LdDeviceCategory,
)
from .coordinator import LdCoordinator, LdCoordinatorConfig
from .helpers import EntityDependencies, build_device_info, get_update_interval

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class _LdPushButtonDevice:
    """Container for a parsed Lifedomus push button device."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str
    push_prop_clsid: str | None
    push_prop_numr: int


@dataclass(frozen=True, slots=True)
class _AlarmActionSpec:
    """Specification for a single alarm action button."""

    button_kind: str
    prop_clsid: str | None
    action_clsid: str


def _parse_push_button_device_element(
    api: LifedomusApi, dev_el: Element
) -> _LdPushButtonDevice | None:
    """Parse a <device> element returned by GetDevicesFromCatg into a push button snapshot."""
    device_key = api.txt("device_key", dev_el)
    if not device_key:
        return None

    device_clsid = api.txt("device_clsid", dev_el)
    label = api.txt("label", dev_el) or device_key
    room_label = api.txt("room_label", dev_el)

    push_prop_clsid: str | None = None
    push_prop_numr = 0

    for action_el in dev_el.findall("./actions/action"):
        action_clsid = api.txt("action_clsid", action_el)
        if action_clsid != LD_ACTION_PUSH:
            continue
        push_prop_clsid = api.txt("prop_clsid", action_el) or None
        push_prop_numr = 0
        break

    return _LdPushButtonDevice(
        device_key=device_key,
        device_clsid=device_clsid,
        label=label,
        room_label=room_label,
        push_prop_clsid=push_prop_clsid,
        push_prop_numr=push_prop_numr,
    )


class LifedomusPushButton(ButtonEntity):
    """Lifedomus native push button entity."""

    _attr_should_poll = False

    def __init__(
        self,
        coordinator: LdCoordinator,
        device: _LdPushButtonDevice,
        dependencies: EntityDependencies,
    ) -> None:
        """Initialize the push button entity and attach the coordinator by composition."""
        super().__init__()
        self.coordinator = coordinator
        self._api = dependencies.api
        self._site_key = str(dependencies.entry.data.get(CONF_SITE_KEY))
        self._user_key = str(dependencies.entry.data.get(CONF_USER_KEY))
        self._push_prop_clsid = device.push_prop_clsid
        self._push_prop_numr = int(device.push_prop_numr)

        self._attr_unique_id = device.device_key
        self._attr_name = device.label

        self._attr_device_info = build_device_info(
            device_key=device.device_key,
            device_clsid=device.device_clsid,
            label=self._attr_name,
            room_label=device.room_label,
            uuid=dependencies.uuid,
        )

        # Available only when a PUSH action is known for this device.
        self._attr_available = self._push_prop_clsid is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle state update from the coordinator."""
        device = (
            self.coordinator.data.get(self._attr_unique_id)
            if self._attr_unique_id
            else None
        )
        if device is not None:
            self._attr_available = device.push_prop_clsid is not None
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register coordinator update listener and publish initial state."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self.async_write_ha_state()

    async def async_press(self) -> None:
        """Send a PUSH action to the device using ExecuteOneAction."""
        if not self._attr_unique_id or not self._push_prop_clsid:
            return

        try:
            await self.coordinator.api.async_execute_one_action(
                target_key=self._attr_unique_id,
                prop_clsid=self._push_prop_clsid,
                prop_numr=self._push_prop_numr,
                action_clsid=LD_ACTION_PUSH,
            )
        except LifedomusApiError as err:
            _LOGGER.warning(
                "Failed to execute PUSH action for %s: %s", self._attr_unique_id, err
            )


class LifedomusAlarmActionButton(ButtonEntity):
    """Alarm action button (Full arming, Stop, Acknowledge events)."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        alarm_coordinator: LdCoordinator,
        dependencies: EntityDependencies,
        device: LdAlarmDevice,
        spec: _AlarmActionSpec,
    ) -> None:
        """Initialize the alarm action button."""
        super().__init__()
        self.coordinator = alarm_coordinator
        self._api = dependencies.api
        self._site_key = str(dependencies.entry.data.get(CONF_SITE_KEY))
        self._user_key = str(dependencies.entry.data.get(CONF_USER_KEY))
        self._device_key = device.device_key
        self._prop_clsid = spec.prop_clsid
        self._action_clsid = spec.action_clsid
        self._button_kind = spec.button_kind
        self._alarm_code = str(dependencies.entry.data.get(CONF_ALARM_CODE, "") or "")

        self._attr_unique_id = f"{device.device_key}::alarm_btn::{self._button_kind}"
        if self._button_kind == "full_arming":
            self._attr_translation_key = "alarm_full_arming"
        elif self._button_kind == "stop":
            self._attr_translation_key = "alarm_stop"
        elif self._button_kind == "ack_events":
            self._attr_translation_key = "alarm_ack_events"
        else:
            self._attr_translation_key = "button_kind_unknown"

        self._attr_device_info = build_device_info(
            device_key=device.device_key,
            device_clsid=device.device_clsid,
            label=device.label,
            room_label=device.room_label,
            uuid=dependencies.uuid,
        )

        self._attr_available = self._prop_clsid is not None

    async def async_press(self) -> None:
        """Send the alarm action via ExecuteOneAction."""
        if not self._prop_clsid:
            return

        try:
            await self.coordinator.api.async_execute_one_action(
                target_key=self._device_key,
                prop_clsid=self._prop_clsid,
                action_clsid=self._action_clsid,
                descriptor=build_action_descriptor({"password": self._alarm_code}),
            )
        except LifedomusApiError as err:
            _LOGGER.warning(
                "Failed to execute alarm action %s for %s: %s",
                self._action_clsid,
                self._device_key,
                err,
            )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Callable[[list[ButtonEntity]], None],
) -> None:
    """Set up Lifedomus buttons from a config entry."""
    api: LifedomusApi = entry.runtime_data

    cfg = LdCoordinatorConfig[_LdPushButtonDevice](
        name="Lifedomus push button coordinator",
        update_interval=get_update_interval(entry),
        category_clsid=LdDeviceCategory.ACTUATOR_REMOTE_CONTROL,
        parse_device=_parse_push_button_device_element,
    )
    button_coordinator = LdCoordinator(hass, api, cfg)
    await button_coordinator.async_config_entry_first_refresh()
    shared = hass.data.setdefault(DOMAIN, {})
    shared["button_coordinator"] = button_coordinator

    alarm_coordinator = await get_or_create_alarm_coordinator(hass, api, entry)
    shared["alarm_coordinator"] = alarm_coordinator
    shared["button_coordinator"] = button_coordinator

    dependencies = EntityDependencies(
        api=api, entry=entry, uuid=str(hass.data.setdefault(DOMAIN, {}).get("uuid", ""))
    )

    # Native PUSH buttons
    push_entities: list[ButtonEntity] = [
        LifedomusPushButton(button_coordinator, device, dependencies)
        for device in button_coordinator.data.values()
    ]

    # Alarm action buttons
    alarm_specs_per_device = {
        device.device_key: [
            _AlarmActionSpec(
                button_kind="full_arming",
                prop_clsid=device.prop_operating_mode,
                action_clsid=LD_ACTION_ALARM_FULL_ARMING,
            ),
            _AlarmActionSpec(
                button_kind="stop",
                prop_clsid=device.prop_operating_mode,
                action_clsid=LD_ACTION_ALARM_STOP,
            ),
            _AlarmActionSpec(
                button_kind="ack_events",
                prop_clsid=device.prop_ack_events,
                action_clsid=LD_ACTION_ALARM_EVENTS_ACKNOWLEDGE,
            ),
        ]
        for device in alarm_coordinator.data.values()
    }

    alarm_entities: list[ButtonEntity] = [
        LifedomusAlarmActionButton(alarm_coordinator, dependencies, device, spec)
        for device in alarm_coordinator.data.values()
        for spec in alarm_specs_per_device.get(device.device_key, [])
    ]

    entities: list[ButtonEntity] = []
    entities.extend(push_entities)
    entities.extend(alarm_entities)

    if callable(async_add_entities):
        async_add_entities(entities)
