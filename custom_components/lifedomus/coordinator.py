"""Data update coordinator for Lifedomus integration.

This module provides a generic coordinator for managing device data updates
from the Lifedomus API, supporting different device categories through
configurable SOAP actions and parsing functions.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import timedelta
import logging
from typing import Protocol
from xml.etree.ElementTree import Element

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LifedomusApi, LifedomusApiError
from .const import OPTION_UPDATE_INTERVAL, OPTION_UPDATE_INTERVAL_DEFAULT

_LOGGER = logging.getLogger(__name__)


class LdDeviceSnapshot(Protocol):
    """Fields shared by every parsed device snapshot."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str


@dataclass(frozen=True, slots=True)
class LdCoordinatorConfig[TDev: LdDeviceSnapshot]:
    """Static description of a device category handled by LdCoordinator.

    Attributes:
        name: Human-readable coordinator name for logs/HA.
        category_clsid: Category CLSID used by Mobile/GetDevicesFromCatg.
        parse_device: Callable used to convert a <device> XML element to a snapshot instance.
        list_namespace: SOAP namespace used for listing devices (defaults to 'Mobile').
        list_action: SOAP action used for listing devices (defaults to 'GetDevicesFromCatg').
        state_namespace: SOAP namespace used to fetch a single device (defaults to 'Mobile').
        state_action: SOAP action used to fetch a single device (defaults to 'GetDeviceState').
    """

    name: str
    category_clsid: str
    parse_device: Callable[[LifedomusApi, Element], TDev | None]
    list_namespace: str = "Mobile"
    list_action: str = "GetDevicesFromCatg"
    state_namespace: str = "Mobile"
    state_action: str = "GetDeviceState"


def _get_update_interval(entry: ConfigEntry) -> timedelta:
    """Return the polling interval from the entry options, clamped to 5 s - 1 h."""
    try:
        seconds = int(
            entry.options.get(OPTION_UPDATE_INTERVAL, OPTION_UPDATE_INTERVAL_DEFAULT)
        )
    except (TypeError, ValueError):
        seconds = OPTION_UPDATE_INTERVAL_DEFAULT
    return timedelta(seconds=max(5, min(3600, seconds)))


class LdCoordinator[TDev: LdDeviceSnapshot](DataUpdateCoordinator[dict[str, TDev]]):
    """Generic DataUpdateCoordinator for one Lifedomus device category."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: LifedomusApi,
        entry: ConfigEntry,
        config: LdCoordinatorConfig[TDev],
    ) -> None:
        """Initialize the coordinator for the configured category."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=config.name,
            config_entry=entry,
            update_interval=_get_update_interval(entry),
        )
        self.api = api
        self._cfg = config

    async def async_fetch_device_snapshot(self, device_key: str) -> TDev | None:
        """Fetch a single device snapshot using the configured state action."""
        try:
            returns = await self.api.async_request(
                namespace=self._cfg.state_namespace,
                action=self._cfg.state_action,
                params={"device_key": device_key},
            )
        except LifedomusApiError as err:
            _LOGGER.debug("Failed to fetch device %s: %s", device_key, err)
            return None
        return next(
            (
                parsed
                for parsed in self._parse_devices(returns)
                if parsed.device_key == device_key
            ),
            None,
        )

    async def _async_update_data(self) -> dict[str, TDev]:
        """Fetch and parse devices using the configured list action."""
        try:
            returns = await self.api.async_request(
                namespace=self._cfg.list_namespace,
                action=self._cfg.list_action,
                params={"category_clsid": self._cfg.category_clsid},
            )
        except LifedomusApiError as err:
            raise UpdateFailed(
                f"Failed to fetch Lifedomus category {self._cfg.category_clsid}: {err}"
            ) from err
        return {parsed.device_key: parsed for parsed in self._parse_devices(returns)}

    def _parse_devices(self, returns: list[Element]) -> Iterable[TDev]:
        """Yield the snapshots parsed from every device-like element of a response."""
        for dev_el in self._iter_device_elements(returns):
            if (parsed := self._cfg.parse_device(self.api, dev_el)) is not None:
                yield parsed

    @staticmethod
    def _iter_device_elements(returns: list[Element]) -> Iterable[Element]:
        """Yield device-like elements from a Mobile SOAP response.

        Supports all known shapes:
         - <return> with one or more <device> children (GetDevicesFromCatg),
         - <device> as the element itself,
         - <return> containing device fields inline (GetDeviceState without <device> wrapper).
        """
        for ret in returns:
            if children := ret.findall("device"):
                yield from children
            elif ret.tag == "device" or ret.find("device_key") is not None:
                yield ret
