"""Light platform for Lifedomus.

This platform queries the Lifedomus gateway for all lights in the "light" category
(CLSID-DEVC-A-EC) and exposes them as Home Assistant light entities. It supports
three device kinds based on their available actions:
 - RGBWW LED strips (presence of prop_clsid: CLSID-DEVC-PROP-LEDRGB-SW)
 - Dimmable lights (presence of prop_clsid: CLSID-DEVC-PROP-DIMMER-VA-POS)
 - On/off (TOR) lights (none of the properties above)

Behavior when state is missing:
 - If no <value> exists in <states>, the entity remains available but its state is
   unknown (is_on=None, assumed_state=True; brightness and color stay None).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final
from xml.etree.ElementTree import Element

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGBWW_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .api import LifedomusApi, build_action_descriptor
from .const import (
    LD_ACTION_OFF,
    LD_ACTION_ON,
    LD_ACTION_VALUE,
    LD_PROP_DIMMER_SW,
    LD_PROP_DIMMER_VA_POS,
    LD_PROP_LEDRGB_SW,
    LD_PROP_LEDRGB_VA_B,
    LD_PROP_LEDRGB_VA_CW,
    LD_PROP_LEDRGB_VA_G,
    LD_PROP_LEDRGB_VA_R,
    LD_PROP_LEDRGB_VA_WW,
    LD_PROP_TOR_SW,
    LD_STATE_LED,
    LD_STATE_LIGHT,
    LD_STATE_POSITION_PERCENTAGE,
    LD_STATE_SOCKET,
    LD_STATE_VALUE_LED_BLUE,
    LD_STATE_VALUE_LED_COLD_WHITE,
    LD_STATE_VALUE_LED_GREEN,
    LD_STATE_VALUE_LED_RED,
    LD_STATE_VALUE_LED_WARM_WHITE,
    LdDeviceCategory,
)
from .coordinator import LdCoordinator, LdCoordinatorConfig
from .data import LifedomusConfigEntry, LifedomusRuntimeData
from .entity import LifedomusEntity

# Actions are serialized per platform to keep the load on the gateway moderate.
PARALLEL_UPDATES = 1

# Raw RGBWW channel levels ordered as the HA rgbww_color tuple (R, G, B, CW, WW).
RgbwwColor = tuple[int, int, int, int, int]

# CLSIDs with a binary on/off state (true/false); LED strips report CLSID-STATE-LED.
LIGHTS_ONOFF: Final[frozenset[str]] = frozenset(
    {LD_STATE_LED, LD_STATE_LIGHT, LD_STATE_SOCKET}
)

# LED channel state CLSIDs, ordered as the HA rgbww_color tuple.
RGBWW_CHANNEL_STATES: Final[tuple[str, str, str, str, str]] = (
    LD_STATE_VALUE_LED_RED,
    LD_STATE_VALUE_LED_GREEN,
    LD_STATE_VALUE_LED_BLUE,
    LD_STATE_VALUE_LED_COLD_WHITE,
    LD_STATE_VALUE_LED_WARM_WHITE,
)

# LED channel value properties, ordered as the HA rgbww_color tuple.
RGBWW_CHANNEL_PROPS: Final[tuple[str, str, str, str, str]] = (
    LD_PROP_LEDRGB_VA_R,
    LD_PROP_LEDRGB_VA_G,
    LD_PROP_LEDRGB_VA_B,
    LD_PROP_LEDRGB_VA_CW,
    LD_PROP_LEDRGB_VA_WW,
)

# Neutral color used when a channel command must be built without any known color.
RGBWW_FALLBACK_COLOR: Final[RgbwwColor] = (255, 255, 255, 255, 255)

# Minimum raw warm-white level written to the strip. The gateway treats a zero
# warm-white level as a switch-off command, which saturated colors coming from the
# Home Assistant color picker would otherwise trigger; one unit is enough to keep
# the strip on and is visually negligible.
RGBWW_WARM_WHITE_MIN: Final[int] = 1

def _scale_rgbww(color: RgbwwColor, numerator: int, denominator: int) -> RgbwwColor:
    """Scale each channel by numerator/denominator, clamped to the 0-255 range."""
    red, green, blue, cold_white, warm_white = (
        min(255, max(0, round(channel * numerator / denominator))) for channel in color
    )
    return (red, green, blue, cold_white, warm_white)


@dataclass(slots=True)
class LdLightDevice:
    """Container for a parsed Lifedomus light device."""

    device_key: str
    device_clsid: str
    label: str
    room_label: str
    is_dimmer: bool
    is_rgb: bool
    is_on: bool | None
    brightness_pct: int | None  # 0..100; None means unknown
    rgbww: RgbwwColor | None  # Raw channel levels 0..255; None means unknown


def _parse_light_capabilities(api: LifedomusApi, dev_el: Element) -> tuple[bool, bool]:
    """Return (is_dimmer, is_rgb) from the properties exposed under <actions>."""
    is_dimmer = False
    is_rgb = False
    for action_el in dev_el.findall("./actions/action"):
        prop_clsid = api.txt("prop_clsid", action_el)
        if prop_clsid == LD_PROP_DIMMER_VA_POS:
            is_dimmer = True
        elif prop_clsid == LD_PROP_LEDRGB_SW:
            is_rgb = True
    return is_dimmer, is_rgb


def _parse_light_states(
    api: LifedomusApi, dev_el: Element, *, is_dimmer: bool, is_rgb: bool
) -> tuple[bool | None, int | None, RgbwwColor | None]:
    """Extract on/off, brightness percentage and RGBWW channels from <states>.

    The boolean on/off state accepts several CLSID aliases (light, socket, LED).
    Dimmers additionally report a 0-100 position percentage, while LED strips
    report one raw 0-255 level per RGBWW channel.
    """
    states_el = dev_el.find("./states")
    if states_el is None or states_el.find(".//value") is None:
        return None, None, None

    bool_state: bool | None = None
    pct: int | None = None
    channels: dict[str, int] = {}

    for st_el in states_el.findall("./state"):
        state_clsid = api.txt("state_clsid", st_el)
        val_txt_raw = api.txt_path(st_el, "./values/value/value")
        val_txt = val_txt_raw.lower() if val_txt_raw else None
        if not val_txt:
            continue

        if (
            bool_state is None
            and state_clsid in LIGHTS_ONOFF
            and val_txt in ("true", "false")
        ):
            bool_state = val_txt == "true"
        elif is_dimmer and pct is None and state_clsid == LD_STATE_POSITION_PERCENTAGE:
            try:
                pct = max(0, min(100, int(val_txt)))
            except ValueError:
                pass
        elif is_rgb and state_clsid in RGBWW_CHANNEL_STATES:
            try:
                channels[state_clsid] = max(0, min(255, int(val_txt)))
            except ValueError:
                pass

    if is_rgb:
        rgbww: RgbwwColor | None = None
        if channels:
            red, green, blue, cold_white, warm_white = (
                channels.get(clsid, 0) for clsid in RGBWW_CHANNEL_STATES
            )
            rgbww = (red, green, blue, cold_white, warm_white)
        return bool_state, None, rgbww

    if is_dimmer:
        is_on = bool_state
        if is_on is None and pct is not None:
            is_on = pct > 0
        return is_on, pct, None

    if bool_state is None:
        return None, None, None
    return bool_state, (100 if bool_state else 0), None


def _parse_light_device_element(
    api: LifedomusApi, dev_el: Element
) -> LdLightDevice | None:
    """Parse a <device> element returned by GetDevicesFromCatg into a device snapshot."""
    device_key = api.txt("device_key", dev_el)
    if not device_key:
        return None

    is_dimmer, is_rgb = _parse_light_capabilities(api, dev_el)
    is_on, brightness_pct, rgbww = _parse_light_states(
        api, dev_el, is_dimmer=is_dimmer, is_rgb=is_rgb
    )

    return LdLightDevice(
        device_key=device_key,
        device_clsid=api.txt("device_clsid", dev_el),
        label=api.txt("label", dev_el) or device_key,
        room_label=api.txt("room_label", dev_el),
        is_dimmer=is_dimmer,
        is_rgb=is_rgb,
        is_on=is_on,
        brightness_pct=brightness_pct,
        rgbww=rgbww,
    )


class _LdBaseLight(LifedomusEntity[LdLightDevice], LightEntity):
    """Base HA light for Lifedomus."""

    _attr_name = None
    # Property CLSID carrying the plain ON/OFF actions; defined by each subclass.
    _switch_prop_clsid: str

    def __init__(
        self,
        coordinator: LdCoordinator[LdLightDevice],
        device: LdLightDevice,
        runtime: LifedomusRuntimeData,
    ) -> None:
        """Initialize the light entity."""
        super().__init__(coordinator, device, runtime)
        self._attr_unique_id = device.device_key
        self._apply_device_snapshot(device)

    def _apply_device_snapshot(self, device: LdLightDevice) -> None:
        """Apply the coordinator snapshot to HA attributes."""
        # is_on must always be bool for HA. When unknown, default to False and mark as assumed
        if device.is_on is None:
            self._attr_is_on = False
            self._attr_assumed_state = True
            self._attr_icon = "mdi:lightbulb-question"
        else:
            self._attr_is_on = device.is_on
            self._attr_assumed_state = False
            self._attr_icon = None

    def _write_optimistic_power(self, is_on: bool) -> None:
        """Publish an optimistic on/off state and restore the default icon."""
        self._attr_is_on = is_on
        self._attr_assumed_state = False
        self._attr_icon = None
        self.async_write_ha_state()

    async def async_turn_on(self, **_kwargs: Any) -> None:
        """Turn on the light through its switch property."""
        self._write_optimistic_power(True)
        await self._async_execute_action(self._switch_prop_clsid, LD_ACTION_ON)

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off the light through its switch property."""
        self._write_optimistic_power(False)
        await self._async_execute_action(self._switch_prop_clsid, LD_ACTION_OFF)


class LifedomusTorLight(_LdBaseLight):
    """On/off (TOR) Lifedomus light."""

    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF
    _switch_prop_clsid = LD_PROP_TOR_SW


class LifedomusDimmerLight(_LdBaseLight):
    """Dimmable Lifedomus light."""

    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}
    _attr_color_mode = ColorMode.BRIGHTNESS
    _switch_prop_clsid = LD_PROP_DIMMER_SW

    def _apply_device_snapshot(self, device: LdLightDevice) -> None:
        """Apply snapshot, including brightness mapping for dimmers."""
        super()._apply_device_snapshot(device)
        self._attr_brightness = (
            None
            if device.brightness_pct is None
            else round(device.brightness_pct * 255 / 100)
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the dimmer, optionally setting brightness."""
        if ATTR_BRIGHTNESS not in kwargs:
            await super().async_turn_on()
            return

        try:
            brightness = int(kwargs[ATTR_BRIGHTNESS])
        except (TypeError, ValueError):
            brightness = 255
        percentage = round(max(0, min(255, brightness)) * 100 / 255)

        self._attr_brightness = round(percentage * 255 / 100)
        self._write_optimistic_power(percentage > 0)

        await self._async_execute_action(
            LD_PROP_DIMMER_VA_POS,
            LD_ACTION_VALUE,
            build_action_descriptor({"percentage": percentage}),
        )

    async def async_turn_off(self, **_kwargs: Any) -> None:
        """Turn off the dimmer."""
        self._attr_brightness = 0
        await super().async_turn_off()


class LifedomusRgbLight(_LdBaseLight):
    """RGBWW LED strip Lifedomus light (device type CLSID-DEVC-A-EC05)."""

    _attr_supported_color_modes = {ColorMode.RGBWW}
    _attr_color_mode = ColorMode.RGBWW
    _switch_prop_clsid = LD_PROP_LEDRGB_SW

    def _apply_device_snapshot(self, device: LdLightDevice) -> None:
        """Apply snapshot, splitting raw channels into brightness and color.

        The gateway exposes one raw 0-255 level per channel without a separate
        brightness. Brightness is therefore derived from the brightest channel
        and rgbww_color holds the channel ratios rescaled to full range, so the
        Home Assistant brightness slider and color picker stay independent.
        """
        super()._apply_device_snapshot(device)
        if device.rgbww is None:
            self._attr_brightness = None
            self._attr_rgbww_color = None
            return

        raw_max = max(device.rgbww)
        self._attr_brightness = raw_max
        self._attr_rgbww_color = (
            _scale_rgbww(device.rgbww, 255, raw_max) if raw_max else device.rgbww
        )

    async def _async_write_channels(self, raw: RgbwwColor) -> None:
        """Write one raw 0-255 level per LED channel through VALUE actions.

        The warm-white level is floored to RGBWW_WARM_WHITE_MIN after brightness
        scaling, because the gateway interprets a zero warm-white level as a
        switch-off command regardless of the other channels.
        """
        red, green, blue, cold_white, warm_white = raw
        for prop_clsid, level in zip(
            RGBWW_CHANNEL_PROPS,
            (red, green, blue, cold_white, max(RGBWW_WARM_WHITE_MIN, warm_white)),
            strict=True,
        ):
            await self._async_execute_action(
                prop_clsid,
                LD_ACTION_VALUE,
                build_action_descriptor({"color": level}),
            )

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the strip, optionally applying color and brightness.

        Without arguments, the plain switch-on action is used. Otherwise raw
        channel levels are computed by scaling the requested (or current) color
        by the requested (or current) brightness, then written channel by
        channel. The switch-on action is sent first when the strip is not known
        to be on; the gateway forces the warm-white channel on switch-on, which
        the subsequent channel writes deterministically override. The warm-white
        level is never written at zero since the gateway would switch the strip
        off (see _async_write_channels).
        """
        rgbww: RgbwwColor | None = kwargs.get(ATTR_RGBWW_COLOR)
        brightness: int | None = kwargs.get(ATTR_BRIGHTNESS)

        if rgbww is None and brightness is None:
            await super().async_turn_on()
            return

        color: RgbwwColor = rgbww or self._attr_rgbww_color or RGBWW_FALLBACK_COLOR
        if brightness is None:
            brightness = self._attr_brightness or 255
        brightness = max(1, min(255, brightness))

        needs_switch_on = self._attr_is_on is not True

        self._attr_brightness = brightness
        self._attr_rgbww_color = color
        self._write_optimistic_power(True)

        if needs_switch_on:
            await self._async_execute_action(self._switch_prop_clsid, LD_ACTION_ON)
        await self._async_write_channels(_scale_rgbww(color, brightness, 255))


def _light_entity_class(device: LdLightDevice) -> type[_LdBaseLight]:
    """Return the light entity class matching the parsed device capabilities."""
    if device.is_rgb:
        return LifedomusRgbLight
    if device.is_dimmer:
        return LifedomusDimmerLight
    return LifedomusTorLight


LIGHT_COORDINATOR_CONFIG: Final[LdCoordinatorConfig[LdLightDevice]] = (
    LdCoordinatorConfig(
        name="Lifedomus light coordinator",
        category_clsid=LdDeviceCategory.ACTUATOR_LIGHT,
        parse_device=_parse_light_device_element,
    )
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: LifedomusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Lifedomus light platform from a config entry."""
    runtime = entry.runtime_data
    async_add_entities(
        _light_entity_class(device)(runtime.light, device, runtime)
        for device in runtime.light.data.values()
    )
