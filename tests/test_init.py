"""Tests for entry setup, unload and device pruning."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.nen import (
    _purge_unselected_devices,
    async_remove_config_entry_device,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.nen.const import CONF_EXCLUDED, DOMAIN

COORDINATOR_DATA = {
    "legacy_subscription_ids": {"EE": "ee-1"},
    "subscriptions": {
        "ee-1": {"utility": "EE"},
        "ga-1": {"utility": "GA"},
        "broken": {},
    },
}


def make_entry(options=None) -> MagicMock:
    entry = MagicMock()
    entry.entry_id = "entry"
    entry.data = {"username": "user@example.com", "password": "hunter2"}
    entry.options = options if options is not None else {}
    return entry


def make_device(*suffixes: str) -> MagicMock:
    device = MagicMock()
    device.id = "-".join(suffixes)
    device.identifiers = {(DOMAIN, f"entry_{suffix}") for suffix in suffixes}
    return device


class SetupEntryTest(unittest.IsolatedAsyncioTestCase):
    async def _setup(self, entry, registry_devices=()):
        hass = MagicMock()
        hass.data = {}
        hass.config_entries.async_forward_entry_setups = AsyncMock()
        coordinator = MagicMock()
        coordinator.data = COORDINATOR_DATA
        coordinator.async_config_entry_first_refresh = AsyncMock()

        registry = MagicMock()
        with (
            patch("custom_components.nen.NenApiClient") as client,
            patch("custom_components.nen.async_get_clientsession"),
            patch(
                "custom_components.nen.NenDataCoordinator", return_value=coordinator
            ) as factory,
            patch("custom_components.nen.dr.async_get", return_value=registry),
            patch(
                "custom_components.nen.dr.async_entries_for_config_entry",
                return_value=list(registry_devices),
            ),
        ):
            result = await async_setup_entry(hass, entry)
        return result, hass, factory, client, registry, coordinator

    async def test_setup_stores_the_coordinator_and_forwards_platforms(self) -> None:
        entry = make_entry()

        ok, hass, _, _, _, coordinator = await self._setup(entry)

        self.assertTrue(ok)
        self.assertIs(hass.data[DOMAIN]["entry"], coordinator)
        coordinator.async_config_entry_first_refresh.assert_awaited_once()
        hass.config_entries.async_forward_entry_setups.assert_awaited_once()

    async def test_credentials_are_taken_from_the_entry(self) -> None:
        entry = make_entry()

        _, _, _, client, _, _ = await self._setup(entry)

        self.assertEqual(client.call_args.args[0], "user@example.com")
        self.assertEqual(client.call_args.args[1], "hunter2")

    async def test_exclusions_are_passed_to_the_coordinator(self) -> None:
        entry = make_entry({CONF_EXCLUDED: ["ga-1"]})

        _, _, factory, _, _, _ = await self._setup(entry)

        self.assertEqual(factory.call_args.kwargs["excluded"], {"ga-1"})

    async def test_no_options_means_no_exclusions(self) -> None:
        _, _, factory, _, _, _ = await self._setup(make_entry())

        self.assertEqual(factory.call_args.kwargs["excluded"], set())

    async def test_an_update_listener_is_registered(self) -> None:
        entry = make_entry()

        await self._setup(entry)

        entry.add_update_listener.assert_called_once()
        entry.async_on_unload.assert_called_once()

    async def test_devices_no_longer_selected_are_dropped_on_setup(self) -> None:
        stale = make_device("ee-old")

        _, _, _, _, registry, _ = await self._setup(make_entry(), [stale])

        registry.async_update_device.assert_called_once_with(
            stale.id, remove_config_entry_id="entry"
        )


class PurgeTest(unittest.TestCase):
    def _purge(self, devices):
        hass = MagicMock()
        entry = make_entry()
        coordinator = MagicMock()
        coordinator.data = COORDINATOR_DATA
        registry = MagicMock()

        with (
            patch("custom_components.nen.dr.async_get", return_value=registry),
            patch(
                "custom_components.nen.dr.async_entries_for_config_entry",
                return_value=devices,
            ),
        ):
            _purge_unselected_devices(hass, entry, coordinator)
        return registry

    def test_selected_devices_survive(self) -> None:
        registry = self._purge([make_device("EE"), make_device("ga-1")])

        registry.async_update_device.assert_not_called()

    def test_unselected_devices_are_removed(self) -> None:
        stale = make_device("ee-old")

        registry = self._purge([make_device("EE"), stale])

        registry.async_update_device.assert_called_once_with(
            stale.id, remove_config_entry_id="entry"
        )

    def test_a_device_matching_on_any_identifier_survives(self) -> None:
        registry = self._purge([make_device("ee-old", "EE")])

        registry.async_update_device.assert_not_called()

    def test_no_coordinator_data_removes_everything(self) -> None:
        hass = MagicMock()
        entry = make_entry()
        coordinator = MagicMock()
        coordinator.data = None
        registry = MagicMock()
        device = make_device("EE")

        with (
            patch("custom_components.nen.dr.async_get", return_value=registry),
            patch(
                "custom_components.nen.dr.async_entries_for_config_entry",
                return_value=[device],
            ),
        ):
            _purge_unselected_devices(hass, entry, coordinator)

        registry.async_update_device.assert_called_once()


class RemoveDeviceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.entry = make_entry()
        coordinator = MagicMock()
        coordinator.data = COORDINATOR_DATA
        self.hass = MagicMock()
        self.hass.data = {DOMAIN: {"entry": coordinator}}

    async def test_legacy_device_is_kept(self) -> None:
        allowed = await async_remove_config_entry_device(
            self.hass, self.entry, make_device("EE")
        )
        self.assertFalse(allowed)

    async def test_suffixed_device_is_kept(self) -> None:
        allowed = await async_remove_config_entry_device(
            self.hass, self.entry, make_device("ga-1")
        )
        self.assertFalse(allowed)

    async def test_unknown_device_can_go(self) -> None:
        allowed = await async_remove_config_entry_device(
            self.hass, self.entry, make_device("ee-old")
        )
        self.assertTrue(allowed)


class UnloadTest(unittest.IsolatedAsyncioTestCase):
    async def test_successful_unload_forgets_the_coordinator(self) -> None:
        hass = MagicMock()
        hass.data = {DOMAIN: {"entry": MagicMock()}}
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

        self.assertTrue(await async_unload_entry(hass, make_entry()))
        self.assertEqual(hass.data[DOMAIN], {})

    async def test_failed_unload_keeps_the_coordinator(self) -> None:
        coordinator = MagicMock()
        hass = MagicMock()
        hass.data = {DOMAIN: {"entry": coordinator}}
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=False)

        self.assertFalse(await async_unload_entry(hass, make_entry()))
        self.assertIs(hass.data[DOMAIN]["entry"], coordinator)


class OptionsUpdateTest(unittest.IsolatedAsyncioTestCase):
    async def test_changing_options_reloads_the_entry(self) -> None:
        from custom_components.nen import _async_options_updated

        hass = MagicMock()
        hass.config_entries.async_reload = AsyncMock()

        await _async_options_updated(hass, make_entry())

        hass.config_entries.async_reload.assert_awaited_once_with("entry")


if __name__ == "__main__":
    unittest.main()
