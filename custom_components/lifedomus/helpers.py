"""Helper functions for the Lifedomus integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

from .api import LifedomusApi
from .const import (
    DOMAIN,
    LD_CLSID_DEVICE_TYPES,
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
        model=LD_CLSID_DEVICE_TYPES.get(device_clsid, device_clsid),
        name=label,
        suggested_area=room_label or None,
        via_device=(DOMAIN, uuid),
    )


def get_shared(hass: HomeAssistant) -> dict[str, Any]:
    """Return the shared integration storage under hass.data[DOMAIN]."""
    return hass.data.setdefault(DOMAIN, {})


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
