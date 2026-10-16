"""Diagnostics support for Lifedomus.

Config entry diagnostics include the redacted entry, the refresh state and
parsed snapshots of every coordinator, the push monitor status and the raw
XML returned by Mobile/GetDevicesFromCatg for each device category. Device
diagnostics include the snapshots and the raw Mobile/GetDeviceState response
of one device; the hub device yields the config entry diagnostics.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Final

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .api import LifedomusApiError
from .const import (
    CONF_ALARM_CODE,
    CONF_PASSWORD,
    CONF_SITE_KEY,
    CONF_USER_KEY,
    DOMAIN,
    LdDeviceCategory,
)
from .coordinator import LdCoordinator
from .data import LifedomusConfigEntry

TO_REDACT: Final[frozenset[str]] = frozenset(
    {CONF_ALARM_CODE, CONF_PASSWORD, CONF_SITE_KEY, CONF_USER_KEY}
)
REDACTED: Final = "**REDACTED**"


async def _async_raw_response(
    entry: LifedomusConfigEntry,
    namespace: str,
    action: str,
    params: dict[str, Any] | None = None,
) -> str:
    """Return the raw body of a gateway request with entry secrets blanked, or the error."""
    try:
        text = await entry.runtime_data.api.async_request_text(namespace, action, params)
    except LifedomusApiError as err:
        return f"ERROR: {err}"
    for secret in (str(entry.data.get(key) or "") for key in TO_REDACT):
        if secret:
            text = text.replace(secret, REDACTED)
    return text


def _coordinator_diagnostics(coordinator: LdCoordinator[Any]) -> dict[str, Any]:
    """Describe the refresh state of a coordinator and its parsed snapshots."""
    return {
        "last_update_success": coordinator.last_update_success,
        "last_exception": (
            None
            if coordinator.last_exception is None
            else str(coordinator.last_exception)
        ),
        "devices": {key: asdict(device) for key, device in coordinator.data.items()},
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: LifedomusConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    runtime = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(entry.data, TO_REDACT),
            "options": dict(entry.options),
        },
        "gateway": {
            "uuid": runtime.uuid,
            "version": await _async_raw_response(entry, "CoreServices", "GetVersion"),
            "monitor_connected": runtime.monitor.is_connected,
        },
        "coordinators": {
            coordinator.name: _coordinator_diagnostics(coordinator)
            for coordinator in runtime.coordinators
        },
        "raw_devices_by_category": {
            category.name: await _async_raw_response(
                entry, "Mobile", "GetDevicesFromCatg", {"category_clsid": category}
            )
            for category in LdDeviceCategory
        },
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: LifedomusConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for a device; the hub device yields the entry diagnostics."""
    runtime = entry.runtime_data
    device_key = next(
        (identifier for domain, identifier in device.identifiers if domain == DOMAIN),
        None,
    )
    if device_key is None or device_key == runtime.uuid:
        return await async_get_config_entry_diagnostics(hass, entry)
    return {
        "device_key": device_key,
        "snapshots": {
            coordinator.name: asdict(coordinator.data[device_key])
            for coordinator in runtime.coordinators
            if device_key in coordinator.data
        },
        "raw_device_state": await _async_raw_response(
            entry, "Mobile", "GetDeviceState", {"device_key": device_key}
        ),
    }
