"""Tests for coordinator._fetch_all against a fake API client.

No HTTP and no Home Assistant runtime: the coordinator is driven directly so
the data-shaping logic can be exercised in isolation.
"""

import unittest
from datetime import timedelta
from unittest.mock import MagicMock, patch

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.nen.api import NenApiError, NenAuthError
from custom_components.nen.coordinator import NenDataCoordinator

CLOSED_HOME = {
    "id": "home-old",
    "name": "Old flat",
    "address": "Via Vecchia 1",
    "subscriptions": [
        {
            "id": "ee-old",
            "utility": "EE",
            "status": "CLOSED",
            "podName": "IT001E000001",
            "supplyId": "supply-ee-old",
        }
    ],
}

ACTIVE_HOME = {
    "id": "home-current",
    "name": "Current flat",
    "address": "Via Nuova 3C",
    "isDefault": True,
    "subscriptions": [
        {
            "id": "ee-current",
            "utility": "EE",
            "status": "ACTIVE",
            "podName": "IT253E16276610",
            "supplyId": "supply-ee-current",
            "is2g": True,
            "contractInformation": {"name": "NeN Special"},
        },
        {
            "id": "ga-current",
            "utility": "GA",
            "status": "ACTIVE",
            "podName": "IT002G000002",
            "supplyId": "supply-ga-current",
        },
    ],
}


class FakeClient:
    """Stands in for NenApiClient, recording calls and returning fixtures."""

    def __init__(self, home_contexts, bills=None, fail=()):
        self.home_contexts = home_contexts
        self.bills = bills or {}
        self.fail = set(fail)
        self.bill_calls: list[str] = []
        self.consumption_calls: list[str] = []

    def _maybe_fail(self, name: str) -> None:
        if name in self.fail:
            raise NenApiError(f"boom in {name}")

    async def get_home_contexts(self):
        self._maybe_fail("get_home_contexts")
        return self.home_contexts

    async def get_profile_details(self):
        self._maybe_fail("get_profile_details")
        return {"subscriptions": [{"id": "ee-current", "code": "RJ7VW"}]}

    async def get_bill_details(self, home_context_id):
        self._maybe_fail("get_bill_details")
        self.bill_calls.append(home_context_id)
        return {"invoices": self.bills.get(home_context_id, [])}

    async def get_contract(self, subscription_id):
        self._maybe_fail("get_contract")
        return {"subscriptionPrice": 83.28, "renewalDate": "2034-10-01"}

    async def get_subscription_detail(self, code, subscription_id):
        self._maybe_fail("get_subscription_detail")
        return {"productVersion": {"consumptionPrice": "0,13943"}}

    async def get_global_consumptions(self, supply_id):
        self._maybe_fail("get_global_consumptions")
        self.consumption_calls.append(supply_id)
        return {"annualConsumptions": {"totalConsumption": 100, "maxConsumption": 200}}


def make_coordinator(client, excluded=None) -> NenDataCoordinator:
    """Build a coordinator bound to a fake client, skipping HA wiring."""
    coordinator = NenDataCoordinator.__new__(NenDataCoordinator)
    coordinator.client = client
    coordinator.excluded = set(excluded or ())
    return coordinator


class FetchAllTest(unittest.IsolatedAsyncioTestCase):
    async def test_closed_contracts_do_not_produce_subscriptions(self) -> None:
        client = FakeClient([CLOSED_HOME, ACTIVE_HOME])

        result = await make_coordinator(client)._fetch_all()

        self.assertEqual(sorted(result["subscriptions"]), ["ee-current", "ga-current"])
        self.assertNotIn("ee-old", result["subscriptions"])

    async def test_only_homes_with_active_contracts_are_reported(self) -> None:
        client = FakeClient([CLOSED_HOME, ACTIVE_HOME])

        result = await make_coordinator(client)._fetch_all()

        self.assertEqual(list(result["homes"]), ["home-current"])
        self.assertEqual(result["homes"]["home-current"]["name"], "Current flat")
        self.assertTrue(result["homes"]["home-current"]["is_default"])

    async def test_legacy_ids_follow_the_active_contracts(self) -> None:
        client = FakeClient([CLOSED_HOME, ACTIVE_HOME])

        result = await make_coordinator(client)._fetch_all()

        self.assertEqual(
            result["legacy_subscription_ids"],
            {"EE": "ee-current", "GA": "ga-current"},
        )

    async def test_bills_stay_scoped_to_their_own_home(self) -> None:
        client = FakeClient(
            [CLOSED_HOME, ACTIVE_HOME],
            bills={
                "home-old": [{"utility": "EE", "number": "old-bill", "amount": 10}],
                "home-current": [
                    {"utility": "EE", "number": "current-bill", "amount": 20}
                ],
            },
        )

        result = await make_coordinator(client)._fetch_all()

        self.assertEqual(
            result["subscriptions"]["ee-current"]["last_bill"]["number"],
            "current-bill",
        )
        self.assertEqual(result["subscriptions"]["ga-current"]["last_bill"], {})

    async def test_subscription_fields_are_carried_through(self) -> None:
        client = FakeClient([ACTIVE_HOME])

        entry = (await make_coordinator(client)._fetch_all())["subscriptions"][
            "ee-current"
        ]

        self.assertEqual(entry["pod"], "IT253E16276610")
        self.assertEqual(entry["home_address"], "Via Nuova 3C")
        self.assertEqual(entry["tariff_name"], "NeN Special")
        self.assertEqual(entry["contract"]["monthly_rate"], 83.28)
        self.assertEqual(entry["detail"]["unit_price"], 0.13943)
        self.assertEqual(entry["consumptions"]["ytd"], 100.0)

    async def test_subscription_without_supply_id_skips_consumptions(self) -> None:
        home = {
            "id": "home-x",
            "subscriptions": [{"id": "ee-x", "utility": "EE", "status": "ACTIVE"}],
        }
        client = FakeClient([home])

        result = await make_coordinator(client)._fetch_all()

        self.assertIsNone(result["subscriptions"]["ee-x"]["consumptions"])
        self.assertEqual(client.consumption_calls, [])

    async def test_endpoint_failures_are_tolerated(self) -> None:
        client = FakeClient(
            [ACTIVE_HOME],
            fail={
                "get_profile_details",
                "get_bill_details",
                "get_contract",
                "get_subscription_detail",
                "get_global_consumptions",
            },
        )

        result = await make_coordinator(client)._fetch_all()

        entry = result["subscriptions"]["ee-current"]
        self.assertEqual(entry["contract"], {})
        self.assertEqual(entry["detail"], {})
        self.assertEqual(entry["last_bill"], {})
        self.assertIsNone(entry["consumptions"])

    async def test_a_home_without_an_id_is_handled(self) -> None:
        """No id means no bill lookup, and no entry in `homes`."""
        home = {
            "name": "Nameless",
            "subscriptions": [{"id": "ee-z", "utility": "EE", "status": "ACTIVE"}],
        }
        client = FakeClient([home])

        result = await make_coordinator(client)._fetch_all()

        self.assertEqual(client.bill_calls, [])
        self.assertEqual(result["homes"], {})
        self.assertIn("ee-z", result["subscriptions"])
        self.assertIsNone(result["subscriptions"]["ee-z"]["home_id"])

    async def test_profile_entries_without_a_code_are_skipped(self) -> None:
        class PartialProfileClient(FakeClient):
            async def get_profile_details(self):
                return {
                    "subscriptions": [
                        {"id": "ee-current"},
                        {"code": "ORPHAN"},
                        {"id": "ga-current", "code": "GOOD"},
                    ]
                }

        result = await make_coordinator(
            PartialProfileClient([ACTIVE_HOME])
        )._fetch_all()

        self.assertIn("ee-current", result["subscriptions"])

    async def test_no_home_contexts_fails_the_update(self) -> None:
        with self.assertRaises(UpdateFailed):
            await make_coordinator(FakeClient([]))._fetch_all()

    async def test_subscription_without_utility_is_ignored(self) -> None:
        home = {
            "id": "home-y",
            "subscriptions": [
                {"id": "unknown", "status": "ACTIVE"},
                {"id": "ee-y", "utility": "EE", "status": "ACTIVE"},
            ],
        }

        result = await make_coordinator(FakeClient([home]))._fetch_all()

        self.assertEqual(list(result["subscriptions"]), ["ee-y"])


class CoordinatorConstructionTest(unittest.TestCase):
    """Real construction, unlike the rest of this file.

    `DataUpdateCoordinator.__init__` reports deprecations through Home
    Assistant's frame helper, which only exists inside a running instance, so
    that one call is silenced.
    """

    def setUp(self) -> None:
        patcher = patch("homeassistant.helpers.frame.report_usage")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_client_and_exclusions_are_stored(self) -> None:
        client = FakeClient([])

        coordinator = NenDataCoordinator(MagicMock(), client, excluded={"ga-1"})

        self.assertIs(coordinator.client, client)
        self.assertEqual(coordinator.excluded, {"ga-1"})
        self.assertEqual(coordinator.update_interval, timedelta(hours=6))

    def test_exclusions_default_to_empty(self) -> None:
        coordinator = NenDataCoordinator(MagicMock(), FakeClient([]))

        self.assertEqual(coordinator.excluded, set())


class UpdateDataTest(unittest.IsolatedAsyncioTestCase):
    async def test_successful_update_returns_the_data(self) -> None:
        coordinator = make_coordinator(FakeClient([ACTIVE_HOME]))

        result = await coordinator._async_update_data()

        self.assertIn("ee-current", result["subscriptions"])

    async def test_rejected_credentials_ask_for_reauthentication(self) -> None:
        """ConfigEntryAuthFailed is what makes Home Assistant prompt the user."""
        coordinator = make_coordinator(FakeClient([ACTIVE_HOME]))

        with patch.object(
            coordinator, "_fetch_all", side_effect=NenAuthError("rejected")
        ):
            with self.assertRaises(ConfigEntryAuthFailed) as caught:
                await coordinator._async_update_data()

        self.assertIn("Authentication error", str(caught.exception))

    async def test_api_errors_become_update_failed(self) -> None:
        coordinator = make_coordinator(FakeClient([ACTIVE_HOME]))

        with patch.object(coordinator, "_fetch_all", side_effect=NenApiError("503")):
            with self.assertRaises(UpdateFailed) as caught:
                await coordinator._async_update_data()

        self.assertIn("API error", str(caught.exception))


class ExcludedSubscriptionsTest(unittest.IsolatedAsyncioTestCase):
    async def test_excluded_contracts_are_not_set_up(self) -> None:
        client = FakeClient([ACTIVE_HOME])

        result = await make_coordinator(client, excluded={"ga-current"})._fetch_all()

        self.assertEqual(list(result["subscriptions"]), ["ee-current"])

    async def test_excluding_every_contract_of_a_home_drops_the_home(self) -> None:
        client = FakeClient([ACTIVE_HOME])

        result = await make_coordinator(
            client, excluded={"ee-current", "ga-current"}
        )._fetch_all()

        self.assertEqual(result["subscriptions"], {})
        self.assertEqual(result["homes"], {})

    async def test_available_still_lists_excluded_contracts(self) -> None:
        client = FakeClient([CLOSED_HOME, ACTIVE_HOME])

        result = await make_coordinator(client, excluded={"ga-current"})._fetch_all()

        self.assertEqual(
            [entry["id"] for entry in result["available"]],
            ["ee-current", "ga-current"],
        )
        self.assertEqual(result["available"][0]["home_name"], "Current flat")

    async def test_legacy_ids_ignore_exclusions(self) -> None:
        """Excluding one contract must not renumber the entities of another."""
        client = FakeClient([ACTIVE_HOME])

        result = await make_coordinator(client, excluded={"ee-current"})._fetch_all()

        self.assertEqual(
            result["legacy_subscription_ids"],
            {"EE": "ee-current", "GA": "ga-current"},
        )


class RemoveDeviceTest(unittest.IsolatedAsyncioTestCase):
    """Covers async_remove_config_entry_device in __init__.py."""

    def setUp(self) -> None:
        from custom_components.nen import async_remove_config_entry_device
        from custom_components.nen.const import DOMAIN

        self.remove = async_remove_config_entry_device
        self.domain = DOMAIN
        self.entry = MagicMock()
        self.entry.entry_id = "entry"
        self.hass = MagicMock()
        coordinator = MagicMock()
        coordinator.data = {
            "legacy_subscription_ids": {"EE": "ee-current"},
            "subscriptions": {
                "ee-current": {"utility": "EE"},
                "ga-current": {"utility": "GA"},
            },
        }
        self.hass.data = {self.domain: {"entry": coordinator}}

    def _device(self, suffix: str) -> MagicMock:
        device = MagicMock()
        device.identifiers = {(self.domain, f"entry_{suffix}")}
        return device

    async def test_active_legacy_device_cannot_be_removed(self) -> None:
        self.assertFalse(await self.remove(self.hass, self.entry, self._device("EE")))

    async def test_active_suffixed_device_cannot_be_removed(self) -> None:
        self.assertFalse(
            await self.remove(self.hass, self.entry, self._device("ga-current"))
        )

    async def test_stale_device_can_be_removed(self) -> None:
        self.assertTrue(
            await self.remove(self.hass, self.entry, self._device("ee-old"))
        )


if __name__ == "__main__":
    unittest.main()
