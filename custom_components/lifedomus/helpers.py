"""Helper functions for the Lifedomus integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo

from .api import LifedomusApi
from .const import (
    DOMAIN,
    LD_CLSID_DEVICE_CATEGORIES,
    MANUFACTURER,
    OPTION_UPDATE_INTERVAL,
    OPTION_UPDATE_INTERVAL_DEFAULT,
)


@dataclass(frozen=True, slots=True)
class EntityDependencies:
    """Minimal shared dependencies container for entity constructors.

    This container groups the shared API client instance, the originating
    config entry and the device registry id of the hub device, so entities can
    access credentials/options and link their device to the hub without
    inflating constructor signatures.
    """

    api: LifedomusApi
    entry: ConfigEntry
    hub_device_id: str | None = None


def build_entity_dependencies(
    hass: HomeAssistant, api: LifedomusApi, entry: ConfigEntry
) -> EntityDependencies:
    """Return the entity dependencies resolved from integration shared data."""
    hub_device_id = hass.data.get(DOMAIN, {}).get("hub_device_id")
    return EntityDependencies(
        api=api,
        entry=entry,
        hub_device_id=hub_device_id if isinstance(hub_device_id, str) else None,
    )


def _resolve_device_model(device_clsid: str) -> str:
    """Return the model name for a device type CLSID.

    Device type CLSIDs embed their category CLSID as a prefix, allowing a direct
    lookup in the nested category mapping. Unknown CLSIDs are returned unchanged
    so the raw identifier remains visible in the device registry.
    """
    for category, types in LD_CLSID_DEVICE_CATEGORIES.items():
        if device_clsid.startswith(category):
            return types.get(device_clsid, device_clsid)
    return device_clsid


def build_device_info(
    *,
    device_key: str,
    device_clsid: str,
    label: str,
    room_label: str | None,
    via_device_id: str | None = None,
) -> DeviceInfo:
    """Create a standard DeviceInfo for a Lifedomus device.

    The hub link is expressed through the device registry id of the hub
    (via_device_id); when it is unknown, the device is created without parent.
    """
    device_info = DeviceInfo(
        identifiers={(DOMAIN, device_key)},
        manufacturer=MANUFACTURER,
        model=_resolve_device_model(device_clsid),
        name=label,
        suggested_area=room_label or None,
    )
    if via_device_id is not None:
        device_info["via_device_id"] = via_device_id
    return device_info


def get_update_interval(entry: ConfigEntry) -> timedelta:
    """Return the global update interval as a timedelta, clamped to sensible bounds."""
    try:
        seconds = int(
            entry.options.get(OPTION_UPDATE_INTERVAL, OPTION_UPDATE_INTERVAL_DEFAULT)
        )
    except (TypeError, ValueError):
        seconds = OPTION_UPDATE_INTERVAL_DEFAULT
    # Clamp between 5s and 1h to avoid pathological values.
    seconds = max(5, min(3600, seconds))
    return timedelta(seconds=seconds)
