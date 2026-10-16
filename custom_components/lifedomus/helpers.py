"""Helper functions for the Lifedomus integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, LD_CLSID_DEVICE_CATEGORIES, MANUFACTURER
from .coordinator import LdDeviceSnapshot


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


def build_device_info(device: LdDeviceSnapshot, *, via_device_id: str) -> DeviceInfo:
    """Create the DeviceInfo of a Lifedomus device linked to the hub device."""
    return DeviceInfo(
        identifiers={(DOMAIN, device.device_key)},
        manufacturer=MANUFACTURER,
        model=_resolve_device_model(device.device_clsid),
        name=device.label,
        suggested_area=device.room_label or None,
        via_device_id=via_device_id,
    )


def system_variable_signal(entry_id: str) -> str:
    """Return the dispatcher signal carrying system variable notifications of an entry."""
    return f"{DOMAIN}_{entry_id}_system_variable"
