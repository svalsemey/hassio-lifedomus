"""Base entities for the Lifedomus integration."""

from __future__ import annotations

import logging

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import LifedomusApiError, SystemVariableValue
from .const import DOMAIN, LD_CLSID_SYSTEM_VARIABLES
from .coordinator import LdCoordinator, LdDeviceSnapshot
from .data import LifedomusConfigEntry, LifedomusRuntimeData
from .helpers import build_device_info, system_variable_signal

_LOGGER = logging.getLogger(__name__)


class LifedomusEntity[TDev: LdDeviceSnapshot](CoordinatorEntity[LdCoordinator[TDev]]):
    """Entity bound to one device snapshot of a Lifedomus coordinator.

    Subclasses exposing state copy the snapshot into entity attributes in
    _apply_device_snapshot(); they call it once at the end of their constructor
    and it runs again on every coordinator update.
    """

    def __init__(
        self,
        coordinator: LdCoordinator[TDev],
        device: TDev,
        runtime: LifedomusRuntimeData,
    ) -> None:
        """Initialize the entity and link its device to the hub."""
        super().__init__(coordinator)
        self._device_key = device.device_key
        self._attr_device_info = build_device_info(
            device, via_device_id=runtime.hub_device_id
        )

    @property
    def available(self) -> bool:
        """Return False when the last refresh failed or the device left the gateway."""
        return super().available and self._device_key in self.coordinator.data

    @property
    def device(self) -> TDev | None:
        """Return the current snapshot of the device, if still known."""
        return self.coordinator.data.get(self._device_key)

    def _apply_device_snapshot(self, device: TDev) -> None:
        """Copy the snapshot into entity attributes."""

    @callback
    def _handle_coordinator_update(self) -> None:
        """Apply the latest snapshot and publish the state."""
        if (device := self.device) is not None:
            self._apply_device_snapshot(device)
        super()._handle_coordinator_update()

    async def _async_execute_action(
        self, prop_clsid: str, action_clsid: str, descriptor: str | None = None
    ) -> None:
        """Execute a device action.

        Callers publish an optimistic state beforehand; on failure the last
        confirmed snapshot is restored and the error is surfaced to the caller.
        """
        try:
            await self.coordinator.api.async_execute_one_action(
                target_key=self._device_key,
                prop_clsid=prop_clsid,
                action_clsid=action_clsid,
                descriptor=descriptor,
            )
        except LifedomusApiError as err:
            self._handle_coordinator_update()
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="action_failed",
                translation_placeholders={
                    "action": action_clsid,
                    "entity": self.entity_id,
                    "error": str(err),
                },
            ) from err


class LifedomusSystemVariableEntity(Entity):
    """Hub system variable, fetched on demand and on push notifications.

    The push monitor only announces that a variable changed; the value is then
    read through State/GetNewValue. Disabled entities are never added to Home
    Assistant and therefore never subscribe to the signal.
    """

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, entry: LifedomusConfigEntry, variable_key: str) -> None:
        """Initialize the entity from the system variable configuration."""
        runtime = entry.runtime_data
        self._api = runtime.api
        self._site_key = runtime.site_key
        self._signal = system_variable_signal(entry.entry_id)
        self._variable_key = variable_key
        self._config = LD_CLSID_SYSTEM_VARIABLES[variable_key]

        self._attr_unique_id = f"{runtime.uuid}::system::{variable_key}"
        self._attr_translation_key = self._config.translation_key
        self._attr_icon = self._config.icon
        self._attr_entity_registry_enabled_default = self._config.enabled
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, runtime.uuid)})

    async def async_added_to_hass(self) -> None:
        """Subscribe to push notifications and schedule the initial fetch."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, self._signal, self._async_handle_push)
        )
        self.async_schedule_update_ha_state(force_refresh=True)

    @callback
    def _async_handle_push(self, variable_key: str) -> None:
        """Refresh the value when the notification targets this variable."""
        if variable_key == self._variable_key:
            self.async_schedule_update_ha_state(force_refresh=True)

    async def async_update(self) -> None:
        """Fetch the current value from the gateway."""
        try:
            value = await self._api.async_get_system_variable(
                site_key=self._site_key, variable_key=self._variable_key
            )
        except LifedomusApiError as err:
            _LOGGER.warning(
                "Failed to fetch system variable %s: %s", self._variable_key, err
            )
            return
        self._apply_value(value)

    def _apply_value(self, value: SystemVariableValue) -> None:
        """Store the fetched value in the entity attributes."""
