"""Tests for the sensor platform.

`NenSensor` extends `CoordinatorEntity`, which only needs a coordinator
object, so the entities are built directly rather than through a running
Home Assistant.
"""

import unittest
from datetime import date
from unittest.mock import MagicMock

from custom_components.nen.const import DOMAIN
from custom_components.nen.sensor import (
    ELECTRICITY_SENSORS,
    GAS_SENSORS,
    NenSensor,
    async_setup_entry,
)

ELECTRICITY_SUB = {
    "id": "ee-1",
    "utility": "EE",
    "pod": "IT000E000001",
    "status": "ACTIVE",
    "home_name": "Current flat",
    "home_address": "Via Nuova 3C",
    "consumptions": {
        "ytd": 1617.59,
        "cap": 2630.0,
        "cap_usage_percentage": 61.5,
        "delta_percentage": 1.5,
        "latest_value": 8.306,
        "latest_date": "2026-04-22T00:00:00.000+00:00",
    },
    "contract": {
        "monthly_rate": 99.0,
        "monthly_rate_gross": 100.0,
        "discount": -1.0,
        "cost_breakdown": [{"id": "consumo", "label": "Consumo", "value": 28.27}],
        "activation_date": date(2020, 10, 1),
        "end_date": date(2034, 10, 1),
        "recalculation_date": date(2026, 10, 1),
        "offer_type": "EE_120",
    },
    "detail": {"unit_price": 0.13943},
    "last_bill": {
        "amount": 12.34,
        "emission_date": date(2026, 4, 1),
        "charge_date": date(2026, 4, 15),
        "status": "PAY_OK",
        "number": "2026/123",
        "residual": 0.0,
    },
}

GAS_SUB = {
    "id": "ga-1",
    "utility": "GA",
    "pod": "IT000G000002",
    "home_name": "Current flat",
    "consumptions": {"ytd": 168.45, "latest_value": 14.5},
    "contract": {"monthly_rate": 29.8},
    "detail": {"unit_price": 0.42},
    "last_bill": {"emission_date": date(2026, 3, 1), "status": "PAY_OK"},
}


def make_coordinator(subscriptions: dict, legacy_ids: dict | None = None) -> MagicMock:
    coordinator = MagicMock()
    coordinator.data = {
        "subscriptions": subscriptions,
        "legacy_subscription_ids": legacy_ids
        if legacy_ids is not None
        else {"EE": "ee-1", "GA": "ga-1"},
    }
    return coordinator


def make_entry(entry_id: str = "entry") -> MagicMock:
    entry = MagicMock()
    entry.entry_id = entry_id
    return entry


def build(description, subscription_id, subscriptions, legacy_ids=None) -> NenSensor:
    coordinator = make_coordinator(subscriptions, legacy_ids)
    return NenSensor(coordinator, make_entry(), description, subscription_id)


def by_key(descriptions, key):
    return next(d for d in descriptions if d.key == key)


class ValueFunctionTest(unittest.TestCase):
    """Every sensor's value_fn against a fully populated subscription."""

    def test_electricity_values(self) -> None:
        values = {d.key: d.value_fn(ELECTRICITY_SUB) for d in ELECTRICITY_SENSORS}

        self.assertEqual(
            values,
            {
                "ee_consumption_ytd": 1617.59,
                "ee_consumption_cap": 2630.0,
                "ee_consumption_cap_usage": 61.5,
                "ee_consumption_latest": 8.306,
                "ee_monthly_rate": 99.0,
                "ee_unit_price": 0.13943,
                "ee_last_bill_date": date(2026, 4, 1),
                "ee_last_bill_charge_date": date(2026, 4, 15),
                "ee_last_bill_status": "PAY_OK",
            },
        )

    def test_gas_values(self) -> None:
        values = {d.key: d.value_fn(GAS_SUB) for d in GAS_SENSORS}

        self.assertEqual(values["ga_consumption_ytd"], 168.45)
        self.assertEqual(values["ga_consumption_latest"], 14.5)
        self.assertEqual(values["ga_monthly_rate"], 29.8)
        self.assertEqual(values["ga_unit_price"], 0.42)
        self.assertEqual(values["ga_last_bill_date"], date(2026, 3, 1))
        self.assertIsNone(values["ga_last_bill_charge_date"])
        self.assertEqual(values["ga_last_bill_status"], "PAY_OK")

    def test_an_empty_subscription_yields_no_values(self) -> None:
        for description in (*ELECTRICITY_SENSORS, *GAS_SENSORS):
            self.assertIsNone(description.value_fn({}), msg=description.key)

    def test_null_consumptions_do_not_raise(self) -> None:
        """`consumptions` is None until the endpoint answers."""
        for description in (*ELECTRICITY_SENSORS, *GAS_SENSORS):
            self.assertIsNone(
                description.value_fn({"consumptions": None, "contract": {}}),
                msg=description.key,
            )


class SetupEntryTest(unittest.IsolatedAsyncioTestCase):
    async def test_one_entity_per_sensor_per_subscription(self) -> None:
        hass = MagicMock()
        entry = make_entry()
        coordinator = make_coordinator({"ee-1": ELECTRICITY_SUB, "ga-1": GAS_SUB})
        hass.data = {DOMAIN: {entry.entry_id: coordinator}}
        added: list = []

        await async_setup_entry(hass, entry, added.extend)

        self.assertEqual(len(added), len(ELECTRICITY_SENSORS) + len(GAS_SENSORS))

    async def test_unknown_utility_creates_nothing(self) -> None:
        hass = MagicMock()
        entry = make_entry()
        coordinator = make_coordinator({"x-1": {"utility": "WATER"}})
        hass.data = {DOMAIN: {entry.entry_id: coordinator}}
        added: list = []

        await async_setup_entry(hass, entry, added.extend)

        self.assertEqual(added, [])


class IdentityTest(unittest.TestCase):
    def test_legacy_subscription_keeps_the_short_unique_id(self) -> None:
        sensor = build(
            by_key(ELECTRICITY_SENSORS, "ee_monthly_rate"),
            "ee-1",
            {"ee-1": ELECTRICITY_SUB},
        )

        self.assertEqual(sensor.unique_id, "entry_ee_monthly_rate")
        self.assertIn((DOMAIN, "entry_EE"), sensor.device_info["identifiers"])

    def test_non_legacy_subscription_is_suffixed(self) -> None:
        sensor = build(
            by_key(ELECTRICITY_SENSORS, "ee_monthly_rate"),
            "ee-2",
            {"ee-2": {**ELECTRICITY_SUB, "id": "ee-2"}},
        )

        self.assertEqual(sensor.unique_id, "entry_ee-2_ee_monthly_rate")
        self.assertIn((DOMAIN, "entry_ee-2"), sensor.device_info["identifiers"])


class DeviceNameTest(unittest.TestCase):
    def test_single_device_per_utility_has_no_location_suffix(self) -> None:
        sensor = build(
            by_key(ELECTRICITY_SENSORS, "ee_monthly_rate"),
            "ee-1",
            {"ee-1": ELECTRICITY_SUB, "ga-1": GAS_SUB},
        )

        self.assertEqual(sensor.device_info["name"], "NeN Electricity")

    def test_two_devices_of_one_utility_are_disambiguated(self) -> None:
        second = {**ELECTRICITY_SUB, "id": "ee-2", "home_name": "Old flat"}
        sensor = build(
            by_key(ELECTRICITY_SENSORS, "ee_monthly_rate"),
            "ee-2",
            {"ee-1": ELECTRICITY_SUB, "ee-2": second},
        )

        self.assertEqual(sensor.device_info["name"], "NeN Electricity - Old flat")

    def test_location_falls_back_to_address_then_pod(self) -> None:
        no_name = {**ELECTRICITY_SUB, "id": "ee-2", "home_name": None}
        sensor = build(
            by_key(ELECTRICITY_SENSORS, "ee_monthly_rate"),
            "ee-2",
            {"ee-1": ELECTRICITY_SUB, "ee-2": no_name},
        )
        self.assertEqual(sensor.device_info["name"], "NeN Electricity - Via Nuova 3C")

        pod_only = {**no_name, "home_address": None}
        sensor = build(
            by_key(ELECTRICITY_SENSORS, "ee_monthly_rate"),
            "ee-2",
            {"ee-1": ELECTRICITY_SUB, "ee-2": pod_only},
        )
        self.assertEqual(sensor.device_info["name"], "NeN Electricity - IT000E000001")

    def test_no_location_leaves_the_name_bare(self) -> None:
        anonymous = {
            **ELECTRICITY_SUB,
            "id": "ee-2",
            "home_name": None,
            "home_address": None,
            "pod": None,
        }
        sensor = build(
            by_key(ELECTRICITY_SENSORS, "ee_monthly_rate"),
            "ee-2",
            {"ee-1": ELECTRICITY_SUB, "ee-2": anonymous},
        )

        self.assertEqual(sensor.device_info["name"], "NeN Electricity")

    def test_gas_device_is_labelled_gas(self) -> None:
        sensor = build(
            by_key(GAS_SENSORS, "ga_monthly_rate"), "ga-1", {"ga-1": GAS_SUB}
        )

        self.assertEqual(sensor.device_info["name"], "NeN Gas")


class NativeValueTest(unittest.TestCase):
    def test_value_comes_from_the_current_coordinator_data(self) -> None:
        sensor = build(
            by_key(ELECTRICITY_SENSORS, "ee_monthly_rate"),
            "ee-1",
            {"ee-1": ELECTRICITY_SUB},
        )

        self.assertEqual(sensor.native_value, 99.0)

    def test_a_vanished_subscription_reads_as_none(self) -> None:
        sensor = build(
            by_key(ELECTRICITY_SENSORS, "ee_monthly_rate"),
            "ee-1",
            {"ee-1": ELECTRICITY_SUB},
        )
        sensor.coordinator.data["subscriptions"] = {}

        self.assertIsNone(sensor.native_value)


class AttributesTest(unittest.TestCase):
    def _attrs(self, key, descriptions=ELECTRICITY_SENSORS, sub_id="ee-1"):
        sensor = build(by_key(descriptions, key), sub_id, {sub_id: ELECTRICITY_SUB})
        return sensor.extra_state_attributes

    def test_common_attributes_are_always_present(self) -> None:
        attrs = self._attrs("ee_unit_price")

        self.assertEqual(attrs["home"], "Current flat")
        self.assertEqual(attrs["address"], "Via Nuova 3C")
        self.assertEqual(attrs["pod"], "IT000E000001")
        self.assertEqual(attrs["contract_status"], "ACTIVE")

    def test_ytd_exposes_the_reading_date(self) -> None:
        attrs = self._attrs("ee_consumption_ytd")

        self.assertEqual(attrs["latest_date"], "2026-04-22T00:00:00.000+00:00")

    def test_cap_usage_exposes_the_pacing_indicator(self) -> None:
        attrs = self._attrs("ee_consumption_cap_usage")

        self.assertEqual(attrs["delta_percentage"], 1.5)

    def test_monthly_rate_exposes_the_discount_detail(self) -> None:
        attrs = self._attrs("ee_monthly_rate")

        self.assertEqual(attrs["rate_before_discount"], 100.0)
        self.assertEqual(attrs["discount"], -1.0)
        self.assertEqual(
            attrs["cost_breakdown"],
            [{"id": "consumo", "label": "Consumo", "value": 28.27}],
        )
        self.assertEqual(attrs["contract_activation_date"], date(2020, 10, 1))
        self.assertEqual(attrs["contract_end_date"], date(2034, 10, 1))
        self.assertEqual(attrs["contract_recalculation_date"], date(2026, 10, 1))
        self.assertEqual(attrs["offer_type"], "EE_120")

    def test_monthly_rate_attributes_match_what_the_parser_produces(self) -> None:
        """Guards against reading contract keys the coordinator never sets."""
        from custom_components.nen.coordinator import _parse_contract

        parsed_keys = set(_parse_contract({}))
        sensor = build(
            by_key(ELECTRICITY_SENSORS, "ee_monthly_rate"),
            "ee-1",
            {"ee-1": {**ELECTRICITY_SUB, "contract": dict.fromkeys(parsed_keys, "x")}},
        )

        read_keys = {
            "activation_date",
            "end_date",
            "recalculation_date",
            "offer_type",
            "monthly_rate_gross",
            "discount",
            "cost_breakdown",
        }
        self.assertLessEqual(read_keys, parsed_keys)
        self.assertEqual(len(sensor.extra_state_attributes), 4 + len(read_keys))

    def test_last_bill_exposes_amount_number_and_residual(self) -> None:
        attrs = self._attrs("ee_last_bill_status")

        self.assertEqual(attrs["amount"], 12.34)
        self.assertEqual(attrs["number"], "2026/123")
        self.assertEqual(attrs["residual"], 0.0)

    def test_missing_values_are_dropped_rather_than_reported_as_none(self) -> None:
        bare = {"utility": "EE"}
        sensor = build(
            by_key(ELECTRICITY_SENSORS, "ee_monthly_rate"), "ee-1", {"ee-1": bare}
        )

        self.assertEqual(sensor.extra_state_attributes, {})


if __name__ == "__main__":
    unittest.main()
