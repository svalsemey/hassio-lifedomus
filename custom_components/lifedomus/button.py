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
from operator import attrgetter
from typing import Final
from xml.etree.ElementTree import Element

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .alarm import LdAlarmDevice
from .api import LifedomusApi, build_action_descriptor
from .const import (
    LD_ACTION_ALARM_EVENTS_ACKNOWLEDGE,
    LD_ACTION_ALARM_FULL_ARMING,
    LD_ACTION_ALARM_STOP,
    LD_ACTION_PUSH,
    LdDeviceCategory,
)
from .coordinator import LdCoordinator, LdCoordinatorConfig
from .data import LifedomusConfigEntry, LifedomusRuntimeData
from .entity import LifedomusEntity

# Actions are serialized per platform to keep the load on the gateway moderate.
PARALLEL_UPDATES = 1


@dataclass(slots=True)
class LdPushButtonDevice:
    """Container for a parsed Lifedomus push button device."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str
    push_prop_clsid: str | None


@dataclass(frozen=True, slots=True)
class _AlarmActionSpec:
    """Specification of one alarm action button.

    Attributes:
        key: Suffix of the unique id.
        translation_key: Key of the entity name in the translation files.
        action_clsid: Action sent on press.
        prop_of: Returns the property CLSID carrying the action, from the alarm snapshot.
    """

    key: str
    translation_key: str
    action_clsid: str
    prop_of: Callable[[LdAlarmDevice], str | None]


ALARM_ACTION_SPECS: Final[tuple[_AlarmActionSpec, ...]] = (
    _AlarmActionSpec(
        "full_arming",
        "alarm_full_arming",
        LD_ACTION_ALARM_FULL_ARMING,
        attrgetter("prop_operating_mode"),
    ),
    _AlarmActionSpec(
        "stop", "alarm_stop", LD_ACTION_ALARM_STOP, attrgetter("prop_operating_mode")
    ),
    _AlarmActionSpec(
        "ack_events",
        "alarm_ack_events",
        LD_ACTION_ALARM_EVENTS_ACKNOWLEDGE,
        attrgetter("prop_ack_events"),
    ),
)


def _parse_push_button_device_element(
    api: LifedomusApi, dev_el: Element
) -> LdPushButtonDevice | None:
    """Parse a <device> element returned by GetDevicesFromCatg into a push button snapshot."""
    device_key = api.txt("device_key", dev_el)
    if not device_key:
        return None

    return LdPushButtonDevice(
        device_key=device_key,
        device_clsid=api.txt("device_clsid", dev_el),
        label=api.txt("label", dev_el) or device_key,
        room_label=api.txt("room_label", dev_el),
        push_prop_clsid=next(
            (
                api.txt("prop_clsid", action_el) or None
                for action_el in dev_el.findall("./actions/action")
                if api.txt("action_clsid", action_el) == LD_ACTION_PUSH
            ),
            None,
        ),
    )


PUSH_BUTTON_COORDINATOR_CONFIG: Final[LdCoordinatorConfig[LdPushButtonDevice]] = (
    LdCoordinatorConfig(
        name="Lifedomus push button coordinator",
        category_clsid=LdDeviceCategory.ACTUATOR_REMOTE_CONTROL,
        parse_device=_parse_push_button_device_element,
    )
)


class LifedomusPushButton(LifedomusEntity[LdPushButtonDevice], ButtonEntity):
    """Lifedomus native push button entity."""

    _attr_name = None

    def __init__(
        self,
        coordinator: LdCoordinator[LdPushButtonDevice],
        device: LdPushButtonDevice,
        runtime: LifedomusRuntimeData,
    ) -> None:
        """Initialize the push button entity."""
        super().__init__(coordinator, device, runtime)
        self._attr_unique_id = device.device_key

    @property
    def _push_prop_clsid(self) -> str | None:
        """Return the property carrying the PUSH action, when the device exposes one."""
        return device.push_prop_clsid if (device := self.device) is not None else None

    @property
    def available(self) -> bool:
        """Return False when the device exposes no PUSH action."""
        return super().available and self._push_prop_clsid is not None

    async def async_press(self) -> None:
        """Send the PUSH action to the device."""
        if (prop_clsid := self._push_prop_clsid) is not None:
            await self._async_execute_action(prop_clsid, LD_ACTION_PUSH)


class LifedomusAlarmActionButton(LifedomusEntity[LdAlarmDevice], ButtonEntity):
    """Alarm action button (Full arming, Stop, Acknowledge events)."""

    def __init__(
        self,
        coordinator: LdCoordinator[LdAlarmDevice],
        device: LdAlarmDevice,
        runtime: LifedomusRuntimeData,
        spec: _AlarmActionSpec,
    ) -> None:
        """Initialize the alarm action button."""
        super().__init__(coordinator, device, runtime)
        self._spec = spec
        self._alarm_code = runtime.alarm_code
        self._attr_unique_id = f"{device.device_key}::alarm_btn::{spec.key}"
        self._attr_translation_key = spec.translation_key

    @property
    def _prop_clsid(self) -> str | None:
        """Return the property carrying the action, when the alarm exposes it."""
        return self._spec.prop_of(device) if (device := self.device) is not None else None

    @property
    def available(self) -> bool:
        """Return False when the alarm does not expose the action property."""
        return super().available and self._prop_clsid is not None

    async def async_press(self) -> None:
        """Send the alarm action with the stored access code."""
        if (prop_clsid := self._prop_clsid) is not None:
            await self._async_execute_action(
                prop_clsid,
                self._spec.action_clsid,
                build_action_descriptor({"password": self._alarm_code}),
            )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LifedomusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Lifedomus buttons from a config entry."""
    runtime = entry.runtime_data
    entities: list[ButtonEntity] = [
        LifedomusPushButton(runtime.push_button, device, runtime)
        for device in runtime.push_button.data.values()
    ]
    entities.extend(
        LifedomusAlarmActionButton(runtime.alarm, device, runtime, spec)
        for device in runtime.alarm.data.values()
        for spec in ALARM_ACTION_SPECS
    )
    async_add_entities(entities)
