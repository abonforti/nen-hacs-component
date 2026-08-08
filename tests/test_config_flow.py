"""Tests for the config and options flows.

The flow objects are driven directly with a mocked `hass`; no Home Assistant
runtime is started.
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import aiohttp

from custom_components.nen.api import NenAuthError
from custom_components.nen.config_flow import (
    NenConfigFlow,
    NenOptionsFlow,
    _subscription_label,
)
from custom_components.nen.const import CONF_EXCLUDED, DOMAIN

CREDENTIALS = {"username": "User@Example.com", "password": "hunter2"}

AVAILABLE = [
    {
        "id": "ee-1",
        "utility": "EE",
        "home_name": "Current flat",
        "home_address": "Via Nuova 3C",
        "pod": "IT000E000001",
    },
    {
        "id": "ga-1",
        "utility": "GA",
        "home_name": "Current flat",
        "home_address": "Via Nuova 3C",
        "pod": "IT000G000002",
    },
]


def make_config_flow() -> NenConfigFlow:
    flow = NenConfigFlow()
    flow.hass = MagicMock()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    return flow


class ConfigFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_form_is_shown_without_input(self) -> None:
        flow = make_config_flow()

        result = await flow.async_step_user()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "user")
        self.assertEqual(result["errors"], {})

    async def _submit(self, client: MagicMock):
        flow = make_config_flow()
        with (
            patch(
                "custom_components.nen.config_flow.NenApiClient", return_value=client
            ),
            patch("custom_components.nen.config_flow.async_get_clientsession"),
        ):
            return flow, await flow.async_step_user(dict(CREDENTIALS))

    async def test_valid_credentials_create_the_entry(self) -> None:
        client = MagicMock()
        client.validate_credentials = AsyncMock(return_value=True)

        flow, result = await self._submit(client)

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["title"], CREDENTIALS["username"])
        self.assertEqual(result["data"], CREDENTIALS)

    async def test_unique_id_is_the_lowercased_email(self) -> None:
        client = MagicMock()
        client.validate_credentials = AsyncMock(return_value=True)

        flow, _ = await self._submit(client)

        flow.async_set_unique_id.assert_called_once_with("user@example.com")
        flow._abort_if_unique_id_configured.assert_called_once()

    async def test_rejected_credentials_show_invalid_auth(self) -> None:
        client = MagicMock()
        client.validate_credentials = AsyncMock(return_value=False)

        _, result = await self._submit(client)

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["errors"], {"base": "invalid_auth"})

    async def test_auth_error_shows_invalid_auth(self) -> None:
        client = MagicMock()
        client.validate_credentials = AsyncMock(side_effect=NenAuthError("bad"))

        _, result = await self._submit(client)

        self.assertEqual(result["errors"], {"base": "invalid_auth"})

    async def test_transport_failures_show_cannot_connect(self) -> None:
        for failure in (aiohttp.ClientError("down"), TimeoutError()):
            client = MagicMock()
            client.validate_credentials = AsyncMock(side_effect=failure)

            _, result = await self._submit(client)

            self.assertEqual(
                result["errors"], {"base": "cannot_connect"}, msg=repr(failure)
            )


class OptionsFlowFactoryTest(unittest.TestCase):
    def test_the_config_flow_exposes_an_options_handler(self) -> None:
        handler = NenConfigFlow.async_get_options_flow(MagicMock())

        self.assertIsInstance(handler, NenOptionsFlow)


class SubscriptionLabelTest(unittest.TestCase):
    def test_utility_and_location(self) -> None:
        self.assertEqual(
            _subscription_label(AVAILABLE[0]), "Electricity - Current flat"
        )
        self.assertEqual(_subscription_label(AVAILABLE[1]), "Gas - Current flat")

    def test_location_falls_back_to_address_then_pod(self) -> None:
        entry = {**AVAILABLE[0], "home_name": None}
        self.assertEqual(_subscription_label(entry), "Electricity - Via Nuova 3C")

        entry = {**entry, "home_address": None}
        self.assertEqual(_subscription_label(entry), "Electricity - IT000E000001")

    def test_no_location_leaves_the_utility_alone(self) -> None:
        entry = {"utility": "EE"}
        self.assertEqual(_subscription_label(entry), "Electricity")

    def test_unknown_utility_is_passed_through(self) -> None:
        self.assertEqual(_subscription_label({"utility": "WATER"}), "WATER")


class OptionsFlowTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.entry = MagicMock()
        self.entry.entry_id = "entry"
        self.entry.options = {}
        # `config_entry` is a read-only property on OptionsFlow, normally
        # populated by Home Assistant when it starts the flow.
        patcher = patch.object(
            NenOptionsFlow,
            "config_entry",
            new_callable=PropertyMock,
            return_value=self.entry,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _flow(self, available=AVAILABLE, excluded=()) -> NenOptionsFlow:
        flow = NenOptionsFlow()
        coordinator = MagicMock()
        coordinator.data = {"available": list(available)}
        self.entry.options = {CONF_EXCLUDED: list(excluded)}
        flow.hass = MagicMock()
        flow.hass.data = {DOMAIN: {"entry": coordinator}}
        return flow

    async def test_form_lists_every_contract(self) -> None:
        result = await self._flow().async_step_init()

        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "init")

    async def test_abort_when_the_account_has_no_contracts(self) -> None:
        result = await self._flow(available=[]).async_step_init()

        self.assertEqual(result["type"], "abort")
        self.assertEqual(result["reason"], "no_subscriptions")

    async def test_abort_when_the_coordinator_has_no_data_yet(self) -> None:
        flow = self._flow()
        flow.hass.data = {DOMAIN: {}}

        result = await flow.async_step_init()

        self.assertEqual(result["reason"], "no_subscriptions")

    async def test_selecting_a_subset_stores_the_rest_as_excluded(self) -> None:
        result = await self._flow().async_step_init({"subscriptions": ["ee-1"]})

        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"], {CONF_EXCLUDED: ["ga-1"]})

    async def test_selecting_everything_stores_no_exclusions(self) -> None:
        result = await self._flow().async_step_init({"subscriptions": ["ee-1", "ga-1"]})

        self.assertEqual(result["data"], {CONF_EXCLUDED: []})

    async def test_selecting_nothing_excludes_everything(self) -> None:
        result = await self._flow().async_step_init({"subscriptions": []})

        self.assertEqual(result["data"], {CONF_EXCLUDED: ["ee-1", "ga-1"]})

    async def test_a_previously_excluded_contract_can_be_reselected(self) -> None:
        flow = self._flow(excluded=["ga-1"])

        result = await flow.async_step_init({"subscriptions": ["ee-1", "ga-1"]})

        self.assertEqual(result["data"], {CONF_EXCLUDED: []})


if __name__ == "__main__":
    unittest.main()
