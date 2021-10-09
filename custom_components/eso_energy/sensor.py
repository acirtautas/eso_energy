import asyncio
import logging
from datetime import timedelta

import aiohttp
import async_timeout

import datetime
import requests
import json
import voluptuous as vol

from homeassistant.components.sensor import PLATFORM_SCHEMA

from homeassistant.const import (
    ATTR_NAME,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_ID,
)

from homeassistant.helpers.aiohttp_client import async_get_clientsession

import homeassistant.helpers.config_validation as cv

from homeassistant.helpers.entity import Entity


_LOGGER = logging.getLogger(__name__)

# Time between updating data from GitHub
SCAN_INTERVAL = timedelta(minutes=10)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Optional(CONF_USERNAME): cv.string,
        vol.Optional(CONF_PASSWORD): cv.string,
        vol.Optional(CONF_ID): cv.string,
    }
)

def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up the Swedish Electricity Price sensor."""

    sensors = [EsoEnergySensor(hass, 'consumed', config), EsoEnergySensor(hass, 'produced', config)]
    async_add_devices(sensors, True)

class EsoEnergySensor(Entity):
    """Implementation of a ESO Energy sensor."""

    def __init__(self, hass, name, config):
        """Initialize the ESO Energy sensor."""
        self.hass = hass
        self._name = name
        self._state = None
        self.attrs = {}
        self._unit_of_measurement = 'kWh'
        self.config = config

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the device."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        return self._unit_of_measurement

    @property
    def device_state_attributes(self):
        """Return the state attributes of the sensor."""
        return self.attrs

    async def async_update(self):
        """Get the latest data from website and update the state."""
        from bs4 import BeautifulSoup

        today = datetime.date.today()
        yesterday = today + datetime.timedelta(days=-1)
        tomorrow = today + datetime.timedelta(days=1)

        username = self.config[CONF_USERNAME]
        password = self.config[CONF_PASSWORD]
        object_id = self.config[CONF_ID]

        login_url = 'https://mano.eso.lt'
        login_data = {
            'name': username,
            'pass': password,
            'login_type': '1',
            'form_id': '########',
            'form_build_id': '########',
            'op': 'Prisijungti'
        }

        history_url = 'https://mano.eso.lt/consumption'

        consumption_url = 'https://mano.eso.lt/consumption?ajax_form=1&_wrapper_format=drupal_ajax'
        consumption_data = {
            'objects[]': object_id,
            'objects_mock': '',
            'scales': 'total',
            'display_type': 'hourly',
            'period': 'day',
            'energy_type': 'general',
            'made_energy_status': '1',
            'visible_scales_field': '0',
            'day_period': today.strftime("%Y-%m-%d"),
            'active_date_value': today.strftime("%Y-%m-%d %H:%M"),
            'back_button_value': yesterday.strftime("%Y-%m-%d %H:%M"),
            'next_button_value': tomorrow.strftime("%Y-%m-%d %H:%M"),
            'form_build_id': '########',
            'form_token': '########',
            'form_id': '########',
            '_triggering_element_name': 'display_type',
            '_drupal_ajax': '1'
        }

        daily_produced = 0.0
        daily_consumed = 0.0

        try:
            session = async_get_clientsession(self.hass)
            with async_timeout.timeout(5, loop=self.hass.loop):
                with requests.Session() as s:

                    # Login form
                    login_result = s.get(login_url)
                    soup = BeautifulSoup(login_result.text, 'html.parser')

                    inputs = soup.select('form.user-login-form input')
                    for i in inputs:
                        name = i.attrs['name']
                        if name == 'form_id' or name == 'form_build_id':
                            value = i.attrs['value']
                            login_data[name] = value

                    # Login
                    login_result = s.post(login_url, login_data)

                    # History
                    history_result = s.get(history_url)
                    soup = BeautifulSoup(history_result.text, 'html.parser')

                    inputs = soup.select('form.eso-consumption-history-form input')

                    for i in inputs:
                        name = i.attrs['name']
                        if name == 'form_id' or name == 'form_build_id' or name == 'form_token':
                            value = i.attrs['value']
                            consumption_data[name] = value

                    # Consumption
                    consumption_result = s.post(consumption_url, consumption_data)
                    consumption = json.loads(consumption_result.text)

                    daily_dataset = consumption[-1]['settings']['eso_consumption_history_form']['graphics_data'][
                        'datasets']

                    for key, value in daily_dataset[0]['record'].items():
                        daily_produced += abs(float(value['value']))

                    for key, value in daily_dataset[1]['record'].items():
                        daily_consumed += float(value['value'])

                    # print('{ produced:', daily_produced, ', consumed:', daily_consumed, '}')

        except (asyncio.TimeoutError, aiohttp.ClientError):
            _LOGGER.error("Error while accessing ESO")

        self.attrs = [daily_produced, daily_consumed]
        self._state = "The current values"