"""Cover platform for Lifedomus.

This platform queries the Lifedomus gateway for all shutter/motor devices in the
"motor" category (CLSID-DEVC-A-MO) and exposes them as Home Assistant cover entities.
Supported operations:
 - Open/Close.
 - Stop.
 - Set exact position.
State mapping:
 - The numeric state 'CLSID-STATE-POSITION-PERCENTAGE' is inverted compared to Home Assistant:
   HA 100% (open) corresponds to 0% in Lifedomus, and HA 0% (closed) to 100% in Lifedomus.
 - If no <value> exists under <state>, the entity remains available but its position is unknown
   (current_cover_position=None, assumed_state=True).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from xml.etree.ElementTree import Element

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import LifedomusApi, build_action_descriptor
from .const import (
    LD_ACTION_DOWN,
    LD_ACTION_STOP,
    LD_ACTION_UP,
    LD_ACTION_VALUE,
    LD_PROP_MOTOR_SW_STOP,
    LD_PROP_MOTOR_UD,
    LD_PROP_MOTOR_VA_POS,
    LD_STATE_POSITION_PERCENTAGE,
    LdDeviceCategory,
)
from .coordinator import LdCoordinator, LdCoordinatorConfig
from .data import LifedomusConfigEntry, LifedomusRuntimeData
from .entity import LifedomusEntity


@dataclass(slots=True)
class LdCoverDevice:
    """Container for a parsed Lifedomus motor device."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str
    position_ha: (
        int | None
    )  # None means unknown; 0..100 uses HA semantics (0=closed, 100=open)


def _parse_cover_device_element(
    api: LifedomusApi, dev_el: Element
) -> LdCoverDevice | None:
    """Parse a <device> element into a cover snapshot with HA-inverted position."""
    device_key = api.txt("device_key", dev_el)
    if not device_key:
        return None

    device_clsid = api.txt("device_clsid", dev_el)
    label = api.txt("label", dev_el) or device_key
    room_label = api.txt("room_label", dev_el)

    states_el = dev_el.find("./states")
    if states_el is None or states_el.find(".//value") is None:
        return LdCoverDevice(
            device_key=device_key,
            device_clsid=device_clsid,
            label=label,
            room_label=room_label,
            position_ha=None,
        )

    position_ha: int | None = None
    for st_el in states_el.findall("./state"):
        state_clsid = api.txt("state_clsid", st_el)
        if state_clsid != LD_STATE_POSITION_PERCENTAGE:
            continue
        val_txt = api.txt_path(st_el, "./values/value/value")
        if val_txt is None:
            continue
        try:
            ld_position = max(0, min(100, int(val_txt)))
            position_ha = 100 - ld_position
        except ValueError:
            position_ha = None
        break

    return LdCoverDevice(
        device_key=device_key,
        device_clsid=device_clsid,
        label=label,
        room_label=room_label,
        position_ha=position_ha,
    )


COVER_COORDINATOR_CONFIG: Final[LdCoordinatorConfig[LdCoverDevice]] = (
    LdCoordinatorConfig(
        name="Lifedomus cover coordinator",
        category_clsid=LdDeviceCategory.ACTUATOR_MOTOR,
        parse_device=_parse_cover_device_element,
    )
)


class LifedomusCover(LifedomusEntity[LdCoverDevice], CoverEntity):
    """Lifedomus shutter/cover entity."""

    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
        | CoverEntityFeature.SET_POSITION
    )
    _attr_device_class = CoverDeviceClass.SHUTTER

    def __init__(
        self,
        coordinator: LdCoordinator[LdCoverDevice],
        device: LdCoverDevice,
        runtime: LifedomusRuntimeData,
    ) -> None:
        """Initialize the cover entity."""
        super().__init__(coordinator, device, runtime)
        self._attr_unique_id = device.device_key
        self._apply_device_snapshot(device)

    def _apply_device_snapshot(self, device: LdCoverDevice) -> None:
        """Apply the position; an unknown position keeps the entity in assumed mode."""
        self._attr_name = device.label
        self._attr_current_cover_position = device.position_ha
        self._attr_is_closed = (
            None if device.position_ha is None else device.position_ha == 0
        )
        self._attr_assumed_state = device.position_ha is None

    def _write_optimistic_position(self, position: int) -> None:
        """Publish the target position as an assumed state while the motor runs."""
        self._attr_current_cover_position = position
        self._attr_is_closed = position == 0
        self._attr_assumed_state = True
        self.async_write_ha_state()

    async def async_open_cover(self, **_kwargs: Any) -> None:
        """Open the cover using UP on MOTOR-UD."""
        self._write_optimistic_position(100)
        await self._async_execute_action(LD_PROP_MOTOR_UD, LD_ACTION_UP)

    async def async_close_cover(self, **_kwargs: Any) -> None:
        """Close the cover using DOWN on MOTOR-UD."""
        self._write_optimistic_position(0)
        await self._async_execute_action(LD_PROP_MOTOR_UD, LD_ACTION_DOWN)

    async def async_stop_cover(self, **_kwargs: Any) -> None:
        """Stop the cover using STOP on MOTOR-SW-STOP."""
        await self._async_execute_action(LD_PROP_MOTOR_SW_STOP, LD_ACTION_STOP)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set the position using VALUE on MOTOR-VA-POS, inverting the HA scale."""
        position = max(0, min(100, int(kwargs[ATTR_POSITION])))
        self._write_optimistic_position(position)
        await self._async_execute_action(
            LD_PROP_MOTOR_VA_POS,
            LD_ACTION_VALUE,
            build_action_descriptor({"position": 100 - position}),
        )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LifedomusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Lifedomus cover platform from a config entry."""
    runtime = entry.runtime_data
    async_add_entities(
        LifedomusCover(runtime.cover, device, runtime)
        for device in runtime.cover.data.values()
    )
