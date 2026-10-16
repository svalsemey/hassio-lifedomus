"""Energy meter coordinator and models for Lifedomus.

Parses energy meter devices (category CLSID-DEVC-M-CP) and enriches heating
managers with the totals returned by Mobile/GetTotalDataValue.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging
from typing import Final
from xml.etree.ElementTree import Element

from .api import LifedomusApi, LifedomusApiError
from .const import CONF_SITE_KEY, LD_DEVICE_TYPE_HEATING_MANAGER, LdDeviceCategory
from .coordinator import LdCoordinator, LdCoordinatorConfig

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class LdEnergyMeter:
    """Container for a parsed Lifedomus energy meter device."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str
    total_value: float | None = None
    total_value_reset: float | None = None
    date: str | None = None
    date_reset: str | None = None


def _parse_energy_device_element(
    api: LifedomusApi, dev_el: Element
) -> LdEnergyMeter | None:
    """Parse a <device> element into a meter snapshot without totals.

    Totals are fetched separately by the coordinator through GetTotalDataValue.
    """
    device_key = api.txt("device_key", dev_el)
    if not device_key:
        return None
    return LdEnergyMeter(
        device_key=device_key,
        device_clsid=api.txt("device_clsid", dev_el),
        label=api.txt("label", dev_el) or device_key,
        room_label=api.txt("room_label", dev_el),
    )


ENERGY_COORDINATOR_CONFIG: Final[LdCoordinatorConfig[LdEnergyMeter]] = (
    LdCoordinatorConfig(
        name="Lifedomus energy coordinator",
        category_clsid=LdDeviceCategory.MEASURE_CONSUMPTION,
        parse_device=_parse_energy_device_element,
    )
)


class LifedomusEnergyCoordinator(LdCoordinator[LdEnergyMeter]):
    """Coordinator for energy meters, enriching heating managers with their totals."""

    async def _async_enrich(self, meter: LdEnergyMeter) -> LdEnergyMeter:
        """Return the meter completed with its totals, unchanged when unsupported or on failure."""
        if meter.device_clsid != LD_DEVICE_TYPE_HEATING_MANAGER:
            return meter
        try:
            data = await self.api.async_get_total_data_value(
                site_key=str(self.config_entry.data.get(CONF_SITE_KEY) or ""),
                device_key=meter.device_key,
            )
        except LifedomusApiError as err:
            _LOGGER.debug(
                "Failed to fetch energy data for %s: %s", meter.device_key, err
            )
            return meter
        return replace(
            meter,
            total_value=data.get("value"),
            total_value_reset=data.get("value_reset"),
            date=data.get("date"),
            date_reset=data.get("date_reset"),
        )

    async def _async_update_data(self) -> dict[str, LdEnergyMeter]:
        """Fetch the device list and enrich heating managers."""
        devices = await super()._async_update_data()
        return {key: await self._async_enrich(meter) for key, meter in devices.items()}

    async def async_fetch_device_snapshot(
        self, device_key: str
    ) -> LdEnergyMeter | None:
        """Fetch a single meter snapshot with its totals."""
        stub = await super().async_fetch_device_snapshot(device_key)
        return None if stub is None else await self._async_enrich(stub)
