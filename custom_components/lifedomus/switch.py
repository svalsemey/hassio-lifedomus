"""Switch platform for Lifedomus alarm zones.

Creates one switch per zone from CLSID-STATE-ALARM-ZONESTATUS for all alarms in
category CLSID-DEVC-S-PR. Toggling the switch sends:
 - ON  -> CLSID-ACTION-ALARM-ZONE-ENABLE
 - OFF -> CLSID-ACTION-ALARM-ZONE-DISABLE
on prop CLSID-DEVC-PROP-ALARM-ZONE-SW with descriptor including the 'index'.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
from typing import Any, cast

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

from .alarm import (
    AlarmZone,
    LdAlarmDevice,
    LifedomusAlarmCoordinator,
    get_or_create_alarm_coordinator,
)
from .api import LifedomusApi, LifedomusApiError, build_action_descriptor
from .const import (
    CONF_ALARM_CODE,
    CONF_SITE_KEY,
    CONF_USER_KEY,
    DOMAIN,
    LD_ACTION_ALARM_ZONE_DISABLE,
    LD_ACTION_ALARM_ZONE_ENABLE,
)
from .helpers import EntityDependencies, build_device_info

_LOGGER = logging.getLogger(__name__)


class LifedomusAlarmZoneSwitch(SwitchEntity):
    """Switch controlling a single alarm zone."""

    _attr_should_poll = False

    def __init__(
        self,
        coord: LifedomusAlarmCoordinator,
        device: LdAlarmDevice,
        zone: AlarmZone,
        dependencies: EntityDependencies,
    ) -> None:
        """Initialize the alarm zone switch."""
        super().__init__()
        self.coordinator = coord
        self._api = dependencies.api
        self._entry = dependencies.entry
        self._site_key = str(self._entry.data.get(CONF_SITE_KEY))
        self._user_key = str(self._entry.data.get(CONF_USER_KEY))
        self._alarm_code = str(self._entry.data.get(CONF_ALARM_CODE, "") or "")

        self._device_key = device.device_key
        self._zone_index = int(zone.index)
        self._prop_zone_sw = device.prop_zone_sw

        self._attr_unique_id = f"{device.device_key}::zone::{zone.index}"
        self._attr_name = f"{device.label} {zone.label}"

        self._attr_device_info = build_device_info(
            device_key=device.device_key,
            device_clsid=device.device_clsid,
            label=device.label,
            room_label=device.room_label,
            uuid=dependencies.uuid,
        )

        # Initial state from coordinator snapshot
        zstate = zone.enabled
        self._attr_is_on = zstate
        self._attr_assumed_state = zstate is None

        # Not available if property is missing
        self._attr_available = self._prop_zone_sw is not None

    @property
    def _dev(self) -> LdAlarmDevice | None:
        """Return current device snapshot."""
        return self.coordinator.data.get(self._device_key)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update switch state from coordinator snapshot."""
        device = self._dev
        if device is None:
            # No device snapshot available yet; keep current optimistic state
            self.async_write_ha_state()
            return

        new_state: bool | None = None
        for z in device.zones:
            if z.index == self._zone_index:
                new_state = z.enabled
                break

        self._attr_is_on = new_state
        # When a concrete snapshot is available, this is no longer an assumed state
        if new_state is not None:
            self._attr_assumed_state = False
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Register coordinator listener and publish initial state."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self.async_write_ha_state()

    async def _send_zone_action(self, enable: bool) -> None:
        """Send zone enable/disable action."""
        if not self._prop_zone_sw:
            return

        action = LD_ACTION_ALARM_ZONE_ENABLE if enable else LD_ACTION_ALARM_ZONE_DISABLE

        try:
            await self.coordinator.api.async_execute_one_action(
                site_key=self._site_key,
                user_key=self._user_key,
                target_key=self._device_key,
                prop_clsid=self._prop_zone_sw,
                action_clsid=action,
                descriptor=build_action_descriptor(
                    {"index": self._zone_index, "password": self._alarm_code}
                ),
            )
        except LifedomusApiError as err:
            _LOGGER.warning(
                "Failed to execute %s for %s zone %s: %s",
                action,
                self._device_key,
                self._zone_index,
                err,
            )

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Enable zone."""
        self._attr_is_on = True
        self._attr_assumed_state = True
        self.async_write_ha_state()
        await self._send_zone_action(True)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Disable zone."""
        self._attr_is_on = False
        self._attr_assumed_state = True
        self.async_write_ha_state()
        await self._send_zone_action(False)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: Callable[[list[SwitchEntity]], None],
) -> None:
    """Set up Lifedomus alarm zone switches from a config entry."""
    api: LifedomusApi = entry.runtime_data

    shared = hass.data.setdefault(DOMAIN, {})
    coord = await get_or_create_alarm_coordinator(hass, api, entry)
    shared["alarm_coordinator"] = coord

    dependencies = EntityDependencies(
        api=api, entry=entry, uuid=str(hass.data[DOMAIN].get("uuid", ""))
    )

    entities = cast(
        list[SwitchEntity],
        [
            LifedomusAlarmZoneSwitch(coord, device, zone, dependencies)
            for device in coord.data.values()
            for zone in device.zones
        ],
    )

    async_add_entities(entities)
