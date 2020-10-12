"""Support for Tuya Smart devices."""
import asyncio
from datetime import timedelta
import logging

from .tuyaha.tuyaapi import (
    TuyaApi,
    TuyaAPIException,
    TuyaNetException,
    TuyaServerException,
    TuyaFrequentlyInvokeException,
)

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_PLATFORM,
    CONF_UNIT_OF_MEASUREMENT,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.exceptions import ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.dispatcher import (
    async_dispatcher_connect,
    async_dispatcher_send,
)
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_time_interval

from .const import (
    CONF_BRIGHTNESS_RANGE_MODE,
    CONF_DISCOVERY_INTERVAL,
    CONF_QUERY_INTERVAL,
    CONF_MAX_KELVIN,
    CONF_MIN_KELVIN,
    CONF_MAX_TUYA_TEMP,
    CONF_COUNTRYCODE,
    CONF_CURR_TEMP_DIVIDER,
    CONF_EXT_TEMP_SENSOR,
    CONF_DEVICE_NAME,
    CONF_SUPPORT_COLOR,
    CONF_TEMP_DIVIDER,
    DEFAULT_DISCOVERY_INTERVAL,
    DEFAULT_QUERY_INTERVAL,
    DOMAIN,
    TUYA_DATA,
    TUYA_DEVICES_CONF,
    TUYA_DISCOVERY_NEW,
    TUYA_PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)

ATTR_TUYA_DEV_ID = "tuya_device_id"
ENTRY_IS_SETUP = "tuya_entry_is_setup"

# PARALLEL_UPDATES = 0

SERVICE_FORCE_UPDATE = "force_update"
SERVICE_PULL_DEVICES = "pull_devices"

SIGNAL_DELETE_ENTITY = "tuya_delete"
SIGNAL_UPDATE_ENTITY = "tuya_update"

TUYA_TYPE_TO_HA = {
    "climate": "climate",
    "cover": "cover",
    "fan": "fan",
    "light": "light",
    "scene": "scene",
    "switch": "switch",
}

TUYA_TRACKER = "tuya_tracker"

TUYA_DEVICE_CONF_SCHEMA = {
    vol.Optional(TUYA_DEVICES_CONF): vol.All(
        cv.ensure_list,
        [
            vol.Schema(
                {
                    vol.Required(CONF_DEVICE_NAME): cv.string,
                    vol.Optional(CONF_UNIT_OF_MEASUREMENT): cv.temperature_unit,
                    vol.Optional(CONF_TEMP_DIVIDER, default=0): cv.positive_int,
                    vol.Optional(CONF_CURR_TEMP_DIVIDER, default=0): cv.positive_int,
                    vol.Optional(CONF_EXT_TEMP_SENSOR): cv.string,
                    vol.Optional(CONF_SUPPORT_COLOR): cv.boolean,
                    vol.Optional(CONF_BRIGHTNESS_RANGE_MODE, default=0): cv.positive_int,
                    vol.Optional(CONF_MIN_KELVIN): cv.positive_int,
                    vol.Optional(CONF_MAX_KELVIN): cv.positive_int,
                    vol.Optional(CONF_MAX_TUYA_TEMP): cv.positive_int,
                }
            )
        ],
    )
}

CONFIG_SCHEMA = vol.Schema(
    vol.All(
        {
            DOMAIN: vol.Schema(
                {
                    vol.Optional(CONF_USERNAME): cv.string,
                    vol.Optional(CONF_COUNTRYCODE): cv.string,
                    vol.Optional(CONF_PASSWORD): cv.string,
                    vol.Optional(CONF_PLATFORM, default="tuya"): cv.string,
                }
            ).extend(TUYA_DEVICE_CONF_SCHEMA)
        },
    ),
    extra=vol.ALLOW_EXTRA,
)


def _update_discovery_interval(hass, interval):
    tuya = hass.data[DOMAIN].get(TUYA_DATA)
    if not tuya:
        return

    try:
        tuya.discovery_interval = interval
        _LOGGER.info(
            "Tuya discovery device poll interval set to %s seconds", interval
        )
    except ValueError as ex:
        _LOGGER.warning(ex)


def _update_query_interval(hass, interval):
    tuya = hass.data[DOMAIN].get(TUYA_DATA)
    if not tuya:
        return

    try:
        tuya.query_interval = interval
        _LOGGER.info(
            "Tuya query device poll interval set to %s seconds", interval
        )
    except ValueError as ex:
        _LOGGER.warning(ex)


async def async_setup(hass, config):
    """Set up the Tuya integration."""

    hass.data[DOMAIN] = {
        TUYA_DEVICES_CONF: {}
    }
    conf = config.get(DOMAIN)
    if conf is not None:
        devices_config = conf.get(TUYA_DEVICES_CONF)
        if devices_config:
            hass.data[DOMAIN][TUYA_DEVICES_CONF] = devices_config

        user = conf.get(CONF_USERNAME)
        pwd = conf.get(CONF_PASSWORD)
        country = conf.get(CONF_COUNTRYCODE)
        if user and pwd and country:
            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": SOURCE_IMPORT}, data=conf
                )
            )

    return True


async def async_setup_entry(hass, entry):
    """Set up Tuya platform."""

    tuya = TuyaApi()
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    country_code = entry.data[CONF_COUNTRYCODE]
    platform = entry.data[CONF_PLATFORM]

    try:
        await hass.async_add_executor_job(
            tuya.init, username, password, country_code, platform
        )
    except (TuyaNetException, TuyaServerException, TuyaFrequentlyInvokeException):
        raise ConfigEntryNotReady()

    except TuyaAPIException as exc:
        _LOGGER.error(
            "Connection error during integration setup. Error: %s", exc,
        )
        return False

    hass.data.setdefault(DOMAIN, {}).update({
        TUYA_DATA: tuya,
        TUYA_TRACKER: None,
        ENTRY_IS_SETUP: set(),
        "entities": {},
        "pending": {},
        entry.entry_id:
        {
            "listener": [entry.add_update_listener(update_listener)],
        }
    })

    _update_discovery_interval(
        hass, entry.options.get(
            CONF_DISCOVERY_INTERVAL, DEFAULT_DISCOVERY_INTERVAL
        )
    )

    _update_query_interval(
        hass, entry.options.get(
            CONF_QUERY_INTERVAL, DEFAULT_QUERY_INTERVAL
        )
    )

    async def async_load_devices(device_list):
        """Load new devices by device_list."""
        device_type_list = {}
        for device in device_list:
            dev_type = device.device_type()
            if (
                dev_type in TUYA_TYPE_TO_HA
                and device.object_id() not in hass.data[DOMAIN]["entities"]
            ):
                ha_type = TUYA_TYPE_TO_HA[dev_type]
                if ha_type not in device_type_list:
                    device_type_list[ha_type] = []
                device_type_list[ha_type].append(device.object_id())
                hass.data[DOMAIN]["entities"][device.object_id()] = None

        for ha_type, dev_ids in device_type_list.items():
            config_entries_key = f"{ha_type}.tuya"
            if config_entries_key not in hass.data[DOMAIN][ENTRY_IS_SETUP]:
                hass.data[DOMAIN]["pending"][ha_type] = dev_ids
                hass.async_create_task(
                    hass.config_entries.async_forward_entry_setup(entry, ha_type)
                )
                hass.data[DOMAIN][ENTRY_IS_SETUP].add(config_entries_key)
            else:
                async_dispatcher_send(hass, TUYA_DISCOVERY_NEW.format(ha_type), dev_ids)

    await async_load_devices(tuya.get_all_devices())

    def _get_updated_devices():
        try:
            tuya.poll_devices_update()
        except TuyaFrequentlyInvokeException as ex:
            _LOGGER.warning(ex)
        return tuya.get_all_devices()

    async def async_poll_devices_update(event_time):
        """Check if accesstoken is expired and pull device list from server."""
        _LOGGER.debug("Pull devices from Tuya.")
        # Add new discover device.
        device_list = await hass.async_add_executor_job(_get_updated_devices)
        await async_load_devices(device_list)
        # Delete not exist device.
        newlist_ids = []
        for device in device_list:
            newlist_ids.append(device.object_id())
        for dev_id in list(hass.data[DOMAIN]["entities"]):
            if dev_id not in newlist_ids:
                async_dispatcher_send(hass, SIGNAL_DELETE_ENTITY, dev_id)
                hass.data[DOMAIN]["entities"].pop(dev_id)

    hass.data[DOMAIN][TUYA_TRACKER] = async_track_time_interval(
        hass, async_poll_devices_update, timedelta(minutes=5)
    )

    hass.services.async_register(
        DOMAIN, SERVICE_PULL_DEVICES, async_poll_devices_update
    )

    async def async_force_update(call):
        """Force all devices to pull data."""
        async_dispatcher_send(hass, SIGNAL_UPDATE_ENTITY)

    hass.services.async_register(DOMAIN, SERVICE_FORCE_UPDATE, async_force_update)

    return True


async def async_unload_entry(hass, entry):
    """Unloading the Tuya platforms."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(
                    entry, component.split(".", 1)[0]
                )
                for component in hass.data[DOMAIN][ENTRY_IS_SETUP]
            ]
        )
    )
    if unload_ok:
        for listener in hass.data[DOMAIN][entry.entry_id]["listener"]:
            listener()
        hass.data[DOMAIN].pop(entry.entry_id)
        hass.data[DOMAIN][ENTRY_IS_SETUP] = set()
        hass.data[DOMAIN][TUYA_TRACKER]()
        hass.data[DOMAIN][TUYA_TRACKER] = None
        hass.data[DOMAIN][TUYA_DATA] = None
        hass.data[DOMAIN].pop(TUYA_DEVICES_CONF)
        hass.services.async_remove(DOMAIN, SERVICE_FORCE_UPDATE)
        hass.services.async_remove(DOMAIN, SERVICE_PULL_DEVICES)
        hass.data.pop(DOMAIN)

    return unload_ok


async def update_listener(hass, entry):
    """Update when config_entry options update."""
    _update_discovery_interval(
        hass, entry.options.get(
            CONF_DISCOVERY_INTERVAL, DEFAULT_DISCOVERY_INTERVAL
        )
    )
    _update_query_interval(
        hass, entry.options.get(
            CONF_QUERY_INTERVAL, DEFAULT_QUERY_INTERVAL
        )
    )


async def cleanup_device_registry(hass, device_id):
    """Remove device registry entry if there are no remaining entities."""

    device_registry = await hass.helpers.device_registry.async_get_registry()
    entity_registry = await hass.helpers.entity_registry.async_get_registry()
    if device_id and not hass.helpers.entity_registry.async_entries_for_device(
        entity_registry, device_id
    ):
        device_registry.async_remove_device(device_id)


class TuyaDevice(Entity):
    """Tuya base device."""

    def __init__(self, tuya, platform):
        """Init Tuya devices."""
        self._tuya = tuya
        self._tuya_platform = platform
        self._dev_conf = None

    """Static attribute"""
    _device_count = 0

    def _inc_device_count(self):
        dev_type = self._tuya.device_type()
        if any(c in dev_type for c in ["scene", "switch"]):
            return
        TuyaDevice._device_count += 1

    def _dec_device_count(self):
        dev_type = self._tuya.device_type()
        if any(c in dev_type for c in ["scene", "switch"]):
            return
        if TuyaDevice._device_count > 0:
            TuyaDevice._device_count -= 1

    def _get_device_config(self):
        devices_config = self.hass.data[DOMAIN].get(TUYA_DEVICES_CONF)
        if devices_config:
            dev_id = self.object_id
            dev_name = (self.name.lower()).replace(" ", "_")
            for conf_info in devices_config:
                conf_id = conf_info[CONF_DEVICE_NAME]
                conf_name = (conf_id.lower()).replace(" ", "_")
                if conf_name == dev_name or conf_id == dev_id:
                    _LOGGER.debug("Configuration for device: %s", str(conf_info))
                    return conf_info
        return []

    async def async_added_to_hass(self):
        """Call when entity is added to hass."""
        if self._dev_conf is None:
            self._dev_conf = self._get_device_config()
        dev_id = self._tuya.object_id()
        self.hass.data[DOMAIN]["entities"][dev_id] = self.entity_id
        async_dispatcher_connect(self.hass, SIGNAL_DELETE_ENTITY, self._delete_callback)
        async_dispatcher_connect(self.hass, SIGNAL_UPDATE_ENTITY, self._update_callback)
        self._inc_device_count()

    @property
    def object_id(self):
        """Return Tuya device id."""
        return self._tuya.object_id()

    @property
    def unique_id(self):
        """Return a unique ID."""
        return f"tuya.{self._tuya.object_id()}"

    @property
    def name(self):
        """Return Tuya device name."""
        return self._tuya.name()

    @property
    def available(self):
        """Return if the device is available."""
        return self._tuya.available()

    @property
    def device_state_attributes(self):
        """Return the optional state attributes."""
        data = {
            ATTR_TUYA_DEV_ID: self.object_id,
        }
        return data

    @property
    def device_info(self):
        """Return a device description for device registry."""
        _device_info = {
            "identifiers": {(DOMAIN, f"{self.unique_id}")},
            "manufacturer": TUYA_PLATFORMS.get(
                self._tuya_platform, self._tuya_platform
            ),
            "name": self.name,
            "model": self._tuya.object_type(),
        }
        return _device_info

    def update(self):
        """Refresh Tuya device data."""
        try:
            self._tuya.update(use_discovery=(TuyaDevice._device_count > 1))
        except TuyaFrequentlyInvokeException as ex:
            _LOGGER.warning(ex)

    async def _delete_callback(self, dev_id):
        """Remove this entity."""
        if dev_id == self.object_id:
            self._dec_device_count()
            entity_registry = (
                await self.hass.helpers.entity_registry.async_get_registry()
            )
            if entity_registry.async_is_registered(self.entity_id):
                entity_entry = entity_registry.async_get(self.entity_id)
                entity_registry.async_remove(self.entity_id)
                await cleanup_device_registry(self.hass, entity_entry.device_id)
            else:
                await self.async_remove()

    @callback
    def _update_callback(self):
        """Call update method."""
        self.async_schedule_update_ha_state(True)
