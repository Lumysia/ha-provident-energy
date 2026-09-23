"""Provident MeterConnex usage integration."""

import asyncio
import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import AuthenticationError, ConnectionError, Meter, ProvidentClient
from .const import DOMAIN
from .data import Hour, select_hour, utility_type

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]
LAG_HOURS = {
    "electricity": 24,
    "cold_water": 2,
    "hot_water": 2,
    "heating": 2,
    "cooling": 2,
}


class ProvidentCoordinator(DataUpdateCoordinator[dict[str, Hour | None]]):
    """Poll yesterday and today for each discovered meter."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: ProvidentClient,
        meters: list[Meter],
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(hours=1),
        )
        self.client = client
        self.meters = [
            meter for meter in meters if utility_type(f"{meter.title} {meter.name}")
        ]

    async def _async_update_data(self) -> dict[str, Hour | None]:
        now = dt_util.now()
        readings: dict[str, Hour | None] = {}
        try:
            for meter in self.meters:
                slots = await self.client.graph(meter.id, now)
                kind = utility_type(f"{meter.title} {meter.name}")
                readings[meter.id] = select_hour(slots, now, LAG_HOURS[kind])
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed("MeterConnex authentication failed") from err
        except ConnectionError as err:
            raise UpdateFailed("MeterConnex usage request failed") from err
        return readings


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Discover meters, fetch initial data, and set up the sensors."""
    session = async_create_clientsession(hass)
    client = ProvidentClient(
        session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD]
    )
    try:
        try:
            meters = await client.meters()
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed("MeterConnex authentication failed") from err
        except ConnectionError as err:
            raise ConfigEntryNotReady("MeterConnex meter discovery failed") from err
        coordinator = ProvidentCoordinator(hass, entry, client, meters)
        if not coordinator.meters:
            raise ConfigEntryNotReady("No supported MeterConnex meters found")
        await coordinator.async_config_entry_first_refresh()
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except (Exception, asyncio.CancelledError):
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        session.detach()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the sensor platform and entry-owned session."""
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)
        return True
    return False
