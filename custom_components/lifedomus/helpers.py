"""Helper functions for the Lifedomus integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

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

    This container groups the shared API client instance and the originating
    config entry so entities can access credentials/options/device registry
    context without inflating constructor signatures.
    """

    api: LifedomusApi
    entry: ConfigEntry
    uuid: str

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
    uuid: str,
) -> DeviceInfo:
    """Create a standard DeviceInfo for all Lifedomus devices, linked to the hub."""
    return DeviceInfo(
        identifiers={(DOMAIN, device_key)},
        manufacturer=MANUFACTURER,
        model=_resolve_device_model(device_clsid),
        name=label,
        suggested_area=room_label or None,
        via_device=(DOMAIN, uuid),
    )


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
