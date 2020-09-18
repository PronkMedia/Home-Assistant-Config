"""Support for the Tuya lights."""
from datetime import timedelta

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_HS_COLOR,
    DOMAIN as SENSOR_DOMAIN,
    ENTITY_ID_FORMAT,
    SUPPORT_BRIGHTNESS,
    SUPPORT_COLOR,
    SUPPORT_COLOR_TEMP,
    LightEntity,
)
from homeassistant.const import CONF_PLATFORM
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import color as colorutil

from . import TuyaDevice
from .const import (
    CONF_BRIGHTNESS_RANGE_MODE,
    CONF_MAX_COLOR_TEMP,
    CONF_SUPPORT_COLOR,
    DOMAIN,
    TUYA_DATA,
    TUYA_DISCOVERY_NEW,
)

# PARALLEL_UPDATES = 0
SCAN_INTERVAL = timedelta(seconds=15)

TUYA_BRIGHTNESS_RANGE0 = (10, 1000)
TUYA_BRIGHTNESS_RANGE1 = (1, 255)
TUYA_DEF_MAX_COL_TEMP = 10000

BRIGHTNESS_MODES = {
    0: TUYA_BRIGHTNESS_RANGE0,
    1: TUYA_BRIGHTNESS_RANGE1,
}


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up tuya sensors dynamically through tuya discovery."""

    platform = config_entry.data[CONF_PLATFORM]

    async def async_discover_sensor(dev_ids):
        """Discover and add a discovered tuya sensor."""
        if not dev_ids:
            return
        entities = await hass.async_add_executor_job(
            _setup_entities, hass, dev_ids, platform,
        )
        async_add_entities(entities)

    async_dispatcher_connect(
        hass, TUYA_DISCOVERY_NEW.format(SENSOR_DOMAIN), async_discover_sensor
    )

    devices_ids = hass.data[DOMAIN]["pending"].pop(SENSOR_DOMAIN)
    await async_discover_sensor(devices_ids)


def _setup_entities(hass, dev_ids, platform):
    """Set up Tuya Light device."""
    tuya = hass.data[DOMAIN][TUYA_DATA]
    entities = []
    for dev_id in dev_ids:
        device = tuya.get_device_by_id(dev_id)
        if device is None:
            continue
        entities.append(TuyaLight(device, platform))
    return entities


class TuyaLight(TuyaDevice, LightEntity):
    """Tuya light device."""

    def __init__(self, tuya, platform):
        """Init Tuya light device."""
        super().__init__(tuya, platform)
        self.entity_id = ENTITY_ID_FORMAT.format(tuya.object_id())

    async def async_added_to_hass(self):
        """set config parameter when add to hass."""
        await super().async_added_to_hass()

        if self._dev_conf:
            # support color config
            supp_color = self._dev_conf.get(CONF_SUPPORT_COLOR, False)
            if supp_color:
                self._tuya.force_support_color()
            # brightness range config
            self._tuya.brightness_white_range = BRIGHTNESS_MODES.get(
                self._dev_conf.get(CONF_BRIGHTNESS_RANGE_MODE, 0),
                TUYA_BRIGHTNESS_RANGE0
            )
            # color temp range config
            max_color_temp = max(
                self._dev_conf.get(CONF_MAX_COLOR_TEMP, TUYA_DEF_MAX_COL_TEMP),
                TUYA_DEF_MAX_COL_TEMP
            )
            self._tuya.color_temp_range = (1000, max_color_temp)

        return

    @property
    def brightness(self):
        """Return the brightness of the light."""
        if self._tuya.brightness() is None:
            return None
        return int(self._tuya.brightness())

    @property
    def hs_color(self):
        """Return the hs_color of the light."""
        return tuple(map(int, self._tuya.hs_color()))

    @property
    def color_temp(self):
        """Return the color_temp of the light."""
        color_temp = int(self._tuya.color_temp())
        if color_temp is None:
            return None
        return colorutil.color_temperature_kelvin_to_mired(color_temp)

    @property
    def is_on(self):
        """Return true if light is on."""
        return self._tuya.state()

    @property
    def min_mireds(self):
        """Return color temperature min mireds."""
        return colorutil.color_temperature_kelvin_to_mired(self._tuya.min_color_temp())

    @property
    def max_mireds(self):
        """Return color temperature max mireds."""
        return colorutil.color_temperature_kelvin_to_mired(self._tuya.max_color_temp())

    def turn_on(self, **kwargs):
        """Turn on or control the light."""
        if (
            ATTR_BRIGHTNESS not in kwargs
            and ATTR_HS_COLOR not in kwargs
            and ATTR_COLOR_TEMP not in kwargs
        ):
            self._tuya.turn_on()
        if ATTR_BRIGHTNESS in kwargs:
            self._tuya.set_brightness(kwargs[ATTR_BRIGHTNESS])
        if ATTR_HS_COLOR in kwargs:
            self._tuya.set_color(kwargs[ATTR_HS_COLOR])
        if ATTR_COLOR_TEMP in kwargs:
            color_temp = colorutil.color_temperature_mired_to_kelvin(
                kwargs[ATTR_COLOR_TEMP]
            )
            self._tuya.set_color_temp(color_temp)

    def turn_off(self, **kwargs):
        """Instruct the light to turn off."""
        self._tuya.turn_off()

    @property
    def supported_features(self):
        """Flag supported features."""
        supports = SUPPORT_BRIGHTNESS
        if self._tuya.support_color():
            supports = supports | SUPPORT_COLOR
        if self._tuya.support_color_temp():
            supports = supports | SUPPORT_COLOR_TEMP
        return supports
