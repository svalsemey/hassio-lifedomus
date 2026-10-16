"""Runtime data attached to a Lifedomus config entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry

from .api import LifedomusApi
from .coordinator import LdCoordinator

if TYPE_CHECKING:
    from .alarm import LdAlarmDevice
    from .binary_sensor import LdDetectorDevice
    from .button import LdPushButtonDevice
    from .climate import LdClimateDevice
    from .cover import LdCoverDevice
    from .energy import LifedomusEnergyCoordinator
    from .light import LdLightDevice
    from .sensor import LdRawSensor


@dataclass(frozen=True, slots=True, kw_only=True)
class LifedomusRuntimeData:
    """Objects shared by the platforms of one config entry.

    Coordinators are created and refreshed once during entry setup, so every
    platform and the push monitor work on the same instances.
    """

    api: LifedomusApi
    uuid: str
    hub_device_id: str
    site_key: str
    alarm_code: str
    alarm: LdCoordinator[LdAlarmDevice]
    climate: LdCoordinator[LdClimateDevice]
    cover: LdCoordinator[LdCoverDevice]
    detector: LdCoordinator[LdDetectorDevice]
    energy: LifedomusEnergyCoordinator
    light: LdCoordinator[LdLightDevice]
    push_button: LdCoordinator[LdPushButtonDevice]
    sensor: LdCoordinator[LdRawSensor]

    @property
    def coordinators(self) -> tuple[LdCoordinator[Any], ...]:
        """Return every device coordinator, in a stable order."""
        return (
            self.alarm,
            self.climate,
            self.cover,
            self.detector,
            self.energy,
            self.light,
            self.push_button,
            self.sensor,
        )


type LifedomusConfigEntry = ConfigEntry[LifedomusRuntimeData]
