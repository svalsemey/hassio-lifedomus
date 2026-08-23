"""Lifedomus integration setup.

This module wires the integration into Home Assistant: it validates connectivity,
sets up config entries, forwards platforms, and ensures the hub device in the
device registry uses the discovered name as friendly_name.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .alarm import get_or_create_alarm_coordinator
from .api import LifedomusApi, LifedomusApiError, LifedomusAuthError
from .const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_SITE_KEY,
    CONF_USER_KEY,
    DOMAIN,
    LD_PORT,
    MANUFACTURER,
    MODEL,
    OPTION_UPDATE_INTERVAL,
    OPTION_UPDATE_INTERVAL_DEFAULT,
)
from .monitor import LifedomusMonitor

# This integration is configured exclusively via config entries (no YAML).
# Declaring a module-level CONFIG_SCHEMA satisfies hassfest when async_setup is present.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.LIGHT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update by reloading the config entry to propagate changes."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Lifedomus integration at Home Assistant start.

    Home Assistant passes the global YAML configuration mapping as 'config'.
    The ConfigType type annotation is required for proper typing checks.
    """
    # No global YAML schema to process; config flow handles user input.
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry[LifedomusApi]
) -> bool:
    """Set up Lifedomus from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    host = entry.data.get(CONF_HOST)
    if not host:
        raise ConfigEntryNotReady("Missing host in config entry")

    api = LifedomusApi(
        hass,
        host=host,
        verify_ssl=False,
        request_timeout=int(
            entry.options.get(OPTION_UPDATE_INTERVAL, OPTION_UPDATE_INTERVAL_DEFAULT)
        ),
    )

    # Validate connectivity and retrieve the UUID for stable device identification.
    try:
        uuid = await api.async_get_uuid()
    except LifedomusApiError as err:
        # Defer setup until gateway is reachable.
        raise ConfigEntryNotReady(err) from err

    # Retrieve gateway version for hub device model
    try:
        version = await api.async_get_version()
    except LifedomusApiError:
        version = "Unknown"

    # Inject stored auth context from the config entry.
    api.set_auth_context(
        site_key=str(entry.data.get(CONF_SITE_KEY)),
        user_key=str(entry.data.get(CONF_USER_KEY)),
        password=str(entry.data.get(CONF_PASSWORD)),
    )

    try:
        await api.async_refresh_session()
    except (LifedomusAuthError, LifedomusApiError) as err:
        # Postpone entry setup until the gateway or session becomes usable.
        # This avoids raising ConfigEntryNotReady from forwarded platforms.
        raise ConfigEntryNotReady(err) from err

    # Store the API instance in the config entry for use in platforms.
    entry.runtime_data = api

    # Ensure the config entry title reflects the discovered name when present.
    discovered_name = entry.data.get(CONF_NAME)
    if discovered_name and entry.title != discovered_name:
        hass.config_entries.async_update_entry(entry, title=discovered_name)

    # Register the gateway as a hub device and keep its registry id so that
    # child devices can reference it through via_device_id.
    hub_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, uuid)},
        manufacturer=MANUFACTURER,
        model=MODEL,
        name=MODEL,
        sw_version=version,
        hw_version=uuid,
        configuration_url=f"https://{host}:{LD_PORT}/",
    )

    # Store gateway UUID and hub device registry id for use by platforms
    shared = hass.data.setdefault(DOMAIN, {})
    shared["uuid"] = uuid
    shared["hub_device_id"] = hub_device.id

    # Reload the entry whenever options are updated to apply global changes.
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # Ensure the alarm coordinator exists before starting the push monitor.
    # Push notifications may arrive immediately and must be routed to the right coordinator.
    await get_or_create_alarm_coordinator(hass, api, entry)

    # Start SSH monitoring tunnel (local_push) alongside regular polling.
    monitor = LifedomusMonitor(hass, api, host=str(host))
    await monitor.async_start()
    shared["monitor"] = monitor

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: ConfigEntry[LifedomusApi]
) -> bool:
    """Unload a config entry."""

    # Stop the monitoring tunnel first.
    shared = hass.data.setdefault(DOMAIN, {})
    monitor: LifedomusMonitor | None = None
    if isinstance(shared, dict):
        monitor = shared.pop("monitor", None)
    if monitor is not None:
        await monitor.async_stop()

    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)
