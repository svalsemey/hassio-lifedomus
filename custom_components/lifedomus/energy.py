"""Energy meter coordinator and models for Lifedomus.

Parses energy meter devices (category CLSID-DEVC-M-CP) and exposes snapshots
containing total consumption values fetched via Mobile/GetTotalDataValue.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from xml.etree.ElementTree import Element

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .api import LifedomusApi, LifedomusApiError
from .const import CONF_SITE_KEY, LD_CLSID_DEVICE_TYPE_SENSOR_ENERGY
from .coordinator import LdCoordinator, LdCoordinatorConfig
from .helpers import get_shared, get_update_interval

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class LdEnergyMeter:
    """Container for a parsed Lifedomus energy meter device."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str
    total_value: float | None
    total_value_reset: float | None
    date: str | None
    date_reset: str | None
    available: bool


def _parse_energy_device_element(
    api: LifedomusApi, dev_el: Element
) -> LdEnergyMeter | None:
    """Parse a <device> element into an LdEnergyMeter snapshot stub.

    Initial parsing extracts only device metadata; actual energy values
    are fetched separately via GetTotalDataValue during coordinator refresh.
    """
    device_key = api.txt("device_key", dev_el)
    if not device_key:
        return None

    device_clsid = api.txt("device_clsid", dev_el)
    label = api.txt("label", dev_el) or device_key
    room_label = api.txt("room_label", dev_el)

    return LdEnergyMeter(
        device_key=device_key,
        device_clsid=device_clsid,
        label=label,
        room_label=room_label,
        total_value=None,
        total_value_reset=None,
        date=None,
        date_reset=None,
        available=True,
    )


class LifedomusEnergyCoordinator(LdCoordinator[LdEnergyMeter]):
    """Coordinator for energy meters with enriched data fetch."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: LifedomusApi,
        config: LdCoordinatorConfig[LdEnergyMeter],
        site_key: str,
    ) -> None:
        """Initialize the energy coordinator."""
        super().__init__(hass, api, config)
        self._site_key = site_key

    async def _async_update_data(self) -> dict[str, LdEnergyMeter]:
        """Fetch device list and enrich each with GetTotalDataValue."""
        devices = await super()._async_update_data()

        for key, meter in list(devices.items()):
            if meter.device_clsid != "CLSID-DEVC-M-CP13":
                continue

            try:
                data = await self.api.async_get_total_data_value(
                    site_key=self._site_key, device_key=key, value_type="elec"
                )
                devices[key] = LdEnergyMeter(
                    device_key=meter.device_key,
                    device_clsid=meter.device_clsid,
                    label=meter.label,
                    room_label=meter.room_label,
                    total_value=data.get("value"),
                    total_value_reset=data.get("value_reset"),
                    date=data.get("date"),
                    date_reset=data.get("date_reset"),
                    available=True,
                )
            except LifedomusApiError as err:
                _LOGGER.debug("Failed to fetch energy data for %s: %s", key, err)

        return devices

    async def async_fetch_device_snapshot(
        self, device_key: str
    ) -> LdEnergyMeter | None:
        """Fetch a single energy meter snapshot with enriched data."""
        stub = await super().async_fetch_device_snapshot(device_key)
        if stub is None or stub.device_clsid != "CLSID-DEVC-M-CP13":
            return stub

        try:
            data = await self.api.async_get_total_data_value(
                site_key=self._site_key, device_key=device_key, value_type="elec"
            )
            return LdEnergyMeter(
                device_key=stub.device_key,
                device_clsid=stub.device_clsid,
                label=stub.label,
                room_label=stub.room_label,
                total_value=data.get("value"),
                total_value_reset=data.get("value_reset"),
                date=data.get("date"),
                date_reset=data.get("date_reset"),
                available=True,
            )
        except LifedomusApiError as err:
            _LOGGER.debug("Failed to fetch energy data for %s: %s", device_key, err)
            return stub


async def get_or_create_energy_coordinator(
    hass: HomeAssistant, api: LifedomusApi, entry: ConfigEntry
) -> LifedomusEnergyCoordinator:
    """Return the shared energy coordinator, creating and refreshing it if missing."""
    shared = get_shared(hass)
    coord = shared.get("energy_coordinator")
    if isinstance(coord, LifedomusEnergyCoordinator):
        return coord

    site_key = str(entry.data.get(CONF_SITE_KEY) or "")

    cfg = LdCoordinatorConfig[LdEnergyMeter](
        name="Lifedomus energy coordinator",
        update_interval=get_update_interval(entry),
        category_clsid=LD_CLSID_DEVICE_TYPE_SENSOR_ENERGY,
        parse_device=_parse_energy_device_element,
    )
    new_coord = LifedomusEnergyCoordinator(hass, api, cfg, site_key)
    await new_coord.async_config_entry_first_refresh()
    shared["energy_coordinator"] = new_coord
    return new_coord
