"""Lifedomus integration setup.

This module validates connectivity to the gateway, registers the hub device,
creates the device coordinators shared by the platforms, starts the push
monitor and forwards the config entry to the platforms.
"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .alarm import ALARM_COORDINATOR_CONFIG
from .api import LifedomusApi, LifedomusApiError, LifedomusAuthError
from .binary_sensor import DETECTOR_COORDINATOR_CONFIG
from .button import PUSH_BUTTON_COORDINATOR_CONFIG
from .climate import CLIMATE_COORDINATOR_CONFIG
from .const import (
    CONF_ALARM_CODE,
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
from .coordinator import LdCoordinator
from .cover import COVER_COORDINATOR_CONFIG
from .data import LifedomusConfigEntry, LifedomusRuntimeData
from .energy import ENERGY_COORDINATOR_CONFIG, LifedomusEnergyCoordinator
from .light import LIGHT_COORDINATOR_CONFIG
from .monitor import LifedomusMonitor
from .sensor import SENSOR_COORDINATOR_CONFIG

# This integration is configured exclusively via config entries (no YAML).
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


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Lifedomus integration at Home Assistant start."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: LifedomusConfigEntry) -> bool:
    """Set up Lifedomus from a config entry."""
    host: str = entry.data[CONF_HOST]
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
        raise ConfigEntryNotReady(err) from err

    try:
        version = await api.async_get_version()
    except LifedomusApiError:
        version = "Unknown"

    api.set_auth_context(
        site_key=entry.data[CONF_SITE_KEY],
        user_key=entry.data[CONF_USER_KEY],
        password=entry.data[CONF_PASSWORD],
    )
    try:
        await api.async_refresh_session()
    except LifedomusAuthError as err:
        raise ConfigEntryAuthFailed(err) from err
    except LifedomusApiError as err:
        raise ConfigEntryNotReady(err) from err

    if (name := entry.data.get(CONF_NAME)) and entry.title != name:
        hass.config_entries.async_update_entry(entry, title=name)

    # Register the gateway as the hub device; child devices link to it through via_device_id.
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

    runtime = LifedomusRuntimeData(
        api=api,
        uuid=uuid,
        hub_device_id=hub_device.id,
        site_key=entry.data[CONF_SITE_KEY],
        alarm_code=str(entry.data.get(CONF_ALARM_CODE) or ""),
        monitor=LifedomusMonitor(hass, entry, api, host=host),
        alarm=LdCoordinator(hass, api, entry, ALARM_COORDINATOR_CONFIG),
        climate=LdCoordinator(hass, api, entry, CLIMATE_COORDINATOR_CONFIG),
        cover=LdCoordinator(hass, api, entry, COVER_COORDINATOR_CONFIG),
        detector=LdCoordinator(hass, api, entry, DETECTOR_COORDINATOR_CONFIG),
        energy=LifedomusEnergyCoordinator(hass, api, entry, ENERGY_COORDINATOR_CONFIG),
        light=LdCoordinator(hass, api, entry, LIGHT_COORDINATOR_CONFIG),
        push_button=LdCoordinator(hass, api, entry, PUSH_BUTTON_COORDINATOR_CONFIG),
        sensor=LdCoordinator(hass, api, entry, SENSOR_COORDINATOR_CONFIG),
    )
    # Sequential refreshes keep the load on the embedded gateway moderate and
    # avoid concurrent session refreshes on the shared API client.
    for coordinator in runtime.coordinators:
        await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = runtime

    # The push monitor starts before the platforms so that notifications
    # arriving during setup already reach the coordinators.
    await runtime.monitor.async_start()
    entry.async_on_unload(runtime.monitor.async_stop)

    await hass.config_entries.async_forward_entry_setups(entry, _PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: LifedomusConfigEntry
) -> bool:
    """Unload the platforms; the monitor is stopped by its unload callback."""
    return await hass.config_entries.async_unload_platforms(entry, _PLATFORMS)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: LifedomusConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing a device that the gateway no longer reports.

    The hub device and devices still present in a coordinator are kept, since
    their entities would be recreated on the next reload.
    """
    runtime = entry.runtime_data
    known = {runtime.uuid}.union(
        *(coordinator.data for coordinator in runtime.coordinators)
    )
    return not any(
        domain == DOMAIN and identifier in known
        for domain, identifier in device_entry.identifiers
    )
