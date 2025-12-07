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
from typing import Generic, TypeVar
from xml.etree.ElementTree import Element

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LifedomusApi, LifedomusApiError

_LOGGER = logging.getLogger(__name__)

TDev = TypeVar("TDev")


@dataclass(frozen=True, slots=True)
class LdCoordinatorConfig(Generic[TDev]):
    """Configuration holder for the generic Lifedomus coordinator.

    Attributes:
        name: Human-readable coordinator name for logs/HA.
        update_interval: Polling interval for periodic refresh.
        category_clsid: Category CLSID used by Mobile/GetDevicesFromCatg.
        parse_device: Callable used to convert a <device> XML element to a snapshot instance.
        list_namespace: SOAP namespace used for listing devices (defaults to 'Mobile').
        list_action: SOAP action used for listing devices (defaults to 'GetDevicesFromCatg').
        state_namespace: SOAP namespace used to fetch a single device (defaults to 'Mobile').
        state_action: SOAP action used to fetch a single device (defaults to 'GetDeviceState').
    """

    name: str
    update_interval: timedelta
    category_clsid: str
    parse_device: Callable[[LifedomusApi, Element], TDev | None]
    list_namespace: str = "Mobile"
    list_action: str = "GetDevicesFromCatg"
    state_namespace: str = "Mobile"
    state_action: str = "GetDeviceState"


class LdCoordinator(DataUpdateCoordinator[dict[str, TDev]], Generic[TDev]):
    """Generic DataUpdateCoordinator for Lifedomus device categories."""

    @property
    def api(self) -> LifedomusApi:
        """Expose the shared API client."""
        return self._api

    def __init__(
        self,
        hass: HomeAssistant,
        api: LifedomusApi,
        config: LdCoordinatorConfig[TDev],
    ) -> None:
        """Initialize the generic coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=config.name,
            update_interval=config.update_interval,
        )
        self._api = api
        self._cfg = config

    async def async_fetch_device_snapshot(self, device_key: str) -> TDev | None:
        """Fetch a single device snapshot using the configured state action."""
        try:
            returns = await self._api.async_request(
                namespace=self._cfg.state_namespace,
                action=self._cfg.state_action,
                params={"device_key": device_key},
            )
        except LifedomusApiError as err:
            _LOGGER.debug("Failed to fetch device %s: %s", device_key, err)
            return None

        for dev_el in self._iter_device_elements(returns):
            parsed = self._cfg.parse_device(self._api, dev_el)
            if parsed is None:
                continue
            # Duck-typing: snapshots must expose a 'device_key' attribute
            parsed_key = getattr(parsed, "device_key", None)
            if parsed_key == device_key:
                return parsed
        return None

    async def _async_update_data(self) -> dict[str, TDev]:
        """Fetch and parse devices using the configured list action."""
        try:
            returns = await self._api.async_request(
                namespace=self._cfg.list_namespace,
                action=self._cfg.list_action,
                params={"category_clsid": self._cfg.category_clsid},
            )
        except LifedomusApiError as err:
            raise UpdateFailed(
                f"Failed to fetch Lifedomus category {self._cfg.category_clsid}: {err}"
            ) from err

        devices: dict[str, TDev] = {}
        for dev_el in self._iter_device_elements(returns):
            parsed = self._cfg.parse_device(self._api, dev_el)
            if parsed is None:
                continue
            key = getattr(parsed, "device_key", None)
            if isinstance(key, str) and key:
                devices[key] = parsed
        return devices

    @staticmethod
    def _iter_device_elements(returns: list[Element]) -> Iterable[Element]:
        """Yield device-like elements from a Mobile SOAP response.

        Supports all known shapes:
         - <return> with one or more <device> children (GetDevicesFromCatg),
         - <device> as the element itself,
         - <return> containing device fields inline (GetDeviceState without <device> wrapper).
        """
        for ret in returns:
            children = ret.findall("device")
            if children:
                yield from children
                continue
            if ret.tag == "device":
                yield ret
                continue
            # Fallback for inline device fields under <return>
            # Detect by presence of at least a 'device_key' child (and usually 'device_clsid')
            if ret.find("device_key") is not None:
                yield ret
