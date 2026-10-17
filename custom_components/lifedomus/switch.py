"""Switch platform for Lifedomus alarm zones.

Creates one switch per zone from CLSID-STATE-ALARM-ZONESTATUS for all alarms in
category CLSID-DEVC-S-PR. Toggling the switch sends:
 - ON  -> CLSID-ACTION-ALARM-ZONE-ENABLE
 - OFF -> CLSID-ACTION-ALARM-ZONE-DISABLE
on prop CLSID-DEVC-PROP-ALARM-ZONE-SW with descriptor including the 'index'.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .alarm import AlarmZone, LdAlarmDevice
from .api import build_action_descriptor
from .const import LD_ACTION_ALARM_ZONE_DISABLE, LD_ACTION_ALARM_ZONE_ENABLE
from .coordinator import LdCoordinator
from .data import LifedomusConfigEntry, LifedomusRuntimeData
from .entity import LifedomusEntity

# Actions are serialized per platform to keep the load on the gateway moderate.
PARALLEL_UPDATES = 1


class LifedomusAlarmZoneSwitch(LifedomusEntity[LdAlarmDevice], SwitchEntity):
    """Switch controlling a single alarm zone."""

    def __init__(
        self,
        coordinator: LdCoordinator[LdAlarmDevice],
        device: LdAlarmDevice,
        zone: AlarmZone,
        runtime: LifedomusRuntimeData,
    ) -> None:
        """Initialize the alarm zone switch."""
        super().__init__(coordinator, device, runtime)
        self._zone_index = zone.index
        self._alarm_code = runtime.alarm_code
        self._attr_unique_id = f"{device.device_key}::zone::{zone.index}"
        self._attr_name = zone.label
        self._apply_device_snapshot(device)

    def _apply_device_snapshot(self, device: LdAlarmDevice) -> None:
        """Read the zone state; an unreported state keeps the entity in assumed mode."""
        self._attr_is_on = next(
            (zone.enabled for zone in device.zones if zone.index == self._zone_index),
            None,
        )
        self._attr_assumed_state = self._attr_is_on is None

    @property
    def available(self) -> bool:
        """Return False when the alarm exposes no zone switch property."""
        return (
            super().available
            and (device := self.device) is not None
            and device.prop_zone_sw is not None
        )

    async def _async_set_zone(self, enable: bool) -> None:
        """Publish the optimistic state and send the zone action."""
        if (device := self.device) is None or device.prop_zone_sw is None:
            return
        self._attr_is_on = enable
        self._attr_assumed_state = True
        self.async_write_ha_state()
        await self._async_execute_action(
            device.prop_zone_sw,
            LD_ACTION_ALARM_ZONE_ENABLE if enable else LD_ACTION_ALARM_ZONE_DISABLE,
            build_action_descriptor(
                {"index": self._zone_index, "password": self._alarm_code}
            ),
        )

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Enable the zone."""
        await self._async_set_zone(True)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Disable the zone."""
        await self._async_set_zone(False)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LifedomusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Lifedomus alarm zone switches from a config entry."""
    runtime = entry.runtime_data
    async_add_entities(
        LifedomusAlarmZoneSwitch(runtime.alarm, device, zone, runtime)
        for device in runtime.alarm.data.values()
        for zone in device.zones
    )
