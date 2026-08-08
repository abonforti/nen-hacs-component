from __future__ import annotations

import aiohttp
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NenApiClient, NenAuthError
from .const import CONF_EXCLUDED, CONF_PASSWORD, CONF_USERNAME, DOMAIN

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


UTILITY_LABELS = {"EE": "Electricity", "GA": "Gas"}


def _subscription_label(entry: dict) -> str:
    """Describe a contract well enough to pick it out of a list."""
    utility = UTILITY_LABELS.get(entry.get("utility", ""), entry.get("utility", ""))
    location = entry.get("home_name") or entry.get("home_address") or entry.get("pod")
    return f"{utility} - {location}" if location else utility


class NenConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg]
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> NenOptionsFlow:
        return NenOptionsFlow()

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = NenApiClient(
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                session,
            )
            try:
                ok = await client.validate_credentials()
                if not ok:
                    errors["base"] = "invalid_auth"
            except NenAuthError:
                errors["base"] = "invalid_auth"
            except (TimeoutError, aiohttp.ClientError):
                errors["base"] = "cannot_connect"

            if not errors:
                await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )


class NenOptionsFlow(OptionsFlow):
    """Let the user pick which contracts to set up."""

    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        available = (getattr(coordinator, "data", None) or {}).get("available", [])

        if not available:
            return self.async_abort(reason="no_subscriptions")

        if user_input is not None:
            selected = set(user_input.get("subscriptions", []))
            excluded = [
                entry["id"] for entry in available if entry["id"] not in selected
            ]
            return self.async_create_entry(data={CONF_EXCLUDED: excluded})

        excluded = self.config_entry.options.get(CONF_EXCLUDED, [])
        schema = vol.Schema(
            {
                vol.Required(
                    "subscriptions",
                    default=[e["id"] for e in available if e["id"] not in excluded],
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(
                                value=entry["id"], label=_subscription_label(entry)
                            )
                            for entry in available
                        ],
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
