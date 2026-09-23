"""Configure MeterConnex usage credentials."""

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import AuthenticationError, ConnectionError, ProvidentClient
from .const import DOMAIN
from .data import utility_type


class ProvidentConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Verify the usage account and its meter tree before creating an entry."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect MeterConnex username and password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            session = async_create_clientsession(self.hass, auto_cleanup=False)
            try:
                meters = await ProvidentClient(
                    session, user_input[CONF_USERNAME], user_input[CONF_PASSWORD]
                ).meters()
                if not meters:
                    errors["base"] = "no_meters"
                elif not any(
                    utility_type(f"{meter.title} {meter.name}") for meter in meters
                ):
                    errors["base"] = "no_supported_meters"
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except ConnectionError:
                errors["base"] = "cannot_connect"
            finally:
                session.detach()

            if not errors:
                await self.async_set_unique_id(
                    user_input[CONF_USERNAME].strip().casefold()
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="Provident usage",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )
