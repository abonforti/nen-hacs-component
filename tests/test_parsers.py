"""Tests for the pure parsing helpers in coordinator.py.

Payload shapes follow what the NeN API actually returns, including the
Italian decimal notation used for prices.
"""

import unittest
from datetime import date

from custom_components.nen.coordinator import (
    _parse_bill,
    _parse_consumptions,
    _parse_contract,
    _parse_date,
    _parse_detail,
    _safe_float,
)


class SafeFloatTest(unittest.TestCase):
    def test_italian_decimal_comma_is_accepted(self) -> None:
        self.assertEqual(_safe_float("0,13943"), 0.13943)

    def test_plain_numbers_pass_through(self) -> None:
        self.assertEqual(_safe_float(83.28), 83.28)
        self.assertEqual(_safe_float("29.8"), 29.8)
        self.assertEqual(_safe_float(0), 0.0)

    def test_unparseable_values_return_none(self) -> None:
        for value in (None, "", "n/a", {}, []):
            self.assertIsNone(_safe_float(value), msg=repr(value))


class ParseDateTest(unittest.TestCase):
    def test_iso_date_becomes_date_object(self) -> None:
        self.assertEqual(_parse_date("2034-10-01"), date(2034, 10, 1))

    def test_missing_or_invalid_returns_none(self) -> None:
        for value in (None, "", "01/10/2034", "not-a-date"):
            self.assertIsNone(_parse_date(value), msg=repr(value))


class ParseContractTest(unittest.TestCase):
    def test_electricity_contract(self) -> None:
        parsed = _parse_contract(
            {
                "subscriptionPrice": 83.28,
                "subscriptionDiscount": 0,
                "renewalDate": "2034-10-01",
                "recalculationDate": "2026-10-01",
                "offerType": "EE_120",
            }
        )

        self.assertEqual(
            parsed,
            {
                "monthly_rate": 83.28,
                "monthly_rate_gross": 83.28,
                "discount": None,
                "cost_breakdown": None,
                "end_date": date(2034, 10, 1),
                "recalculation_date": date(2026, 10, 1),
                "offer_type": "EE_120",
            },
        )

    def test_discount_is_subtracted_from_the_rate(self) -> None:
        parsed = _parse_contract(
            {"subscriptionPrice": 100.00, "subscriptionDiscount": -1}
        )

        self.assertEqual(parsed["monthly_rate"], 99.0)
        self.assertEqual(parsed["monthly_rate_gross"], 100.0)
        self.assertEqual(parsed["discount"], -1.0)

    def test_missing_discount_leaves_the_rate_untouched(self) -> None:
        parsed = _parse_contract({"subscriptionPrice": 29.8})

        self.assertEqual(parsed["monthly_rate"], 29.8)
        self.assertIsNone(parsed["discount"])

    def test_cost_breakdown_is_summarised(self) -> None:
        parsed = _parse_contract(
            {
                "subscriptionPrice": 83.28,
                "billDetails": [
                    {
                        "id": "notOnNeN",
                        "categoryLabel": "Che non dipendono da noi",
                        "categoryLabelValue": 35.54532973330833,
                        "expandedContent": [{"labelType": "Tasse", "value": 7.6}],
                    },
                    {
                        "id": "fixedPrice",
                        "categoryLabel": "Quota fissa",
                        "categoryLabelValue": 10,
                    },
                    {"id": "broken", "categoryLabel": "No value"},
                ],
            }
        )

        self.assertEqual(
            parsed["cost_breakdown"],
            [
                {
                    "id": "notOnNeN",
                    "label": "Che non dipendono da noi",
                    "value": 35.55,
                },
                {"id": "fixedPrice", "label": "Quota fissa", "value": 10.0},
            ],
        )

    def test_unusable_bill_details_yield_no_breakdown(self) -> None:
        for value in (None, [], {}, "nope", [1, 2]):
            self.assertIsNone(
                _parse_contract({"billDetails": value})["cost_breakdown"],
                msg=repr(value),
            )

    def test_empty_payload_yields_none_values(self) -> None:
        self.assertEqual(
            _parse_contract({}),
            {
                "monthly_rate": None,
                "monthly_rate_gross": None,
                "discount": None,
                "cost_breakdown": None,
                "end_date": None,
                "recalculation_date": None,
                "offer_type": None,
            },
        )


class ParseDetailTest(unittest.TestCase):
    def test_consumption_price_wins_over_price(self) -> None:
        parsed = _parse_detail(
            {
                "productVersion": {
                    "consumptionPrice": "0,13943",
                    "price": "0,129",
                    "annualFixedPrice": "121,3183",
                }
            }
        )

        self.assertEqual(parsed["unit_price"], 0.13943)
        self.assertEqual(parsed["annual_fixed_price"], 121.3183)

    def test_falls_back_to_price_when_consumption_price_missing(self) -> None:
        parsed = _parse_detail({"productVersion": {"price": "0,129"}})

        self.assertEqual(parsed["unit_price"], 0.129)
        self.assertIsNone(parsed["annual_fixed_price"])

    def test_missing_product_version(self) -> None:
        self.assertEqual(
            _parse_detail({}), {"unit_price": None, "annual_fixed_price": None}
        )


class ParseBillTest(unittest.TestCase):
    def test_full_invoice(self) -> None:
        parsed = _parse_bill(
            {
                "amount": "12,34",
                "emissionDate": "2026-04-01",
                "chargeDate": "2026-04-15",
                "status": "PAY_OK",
                "number": "2026/123",
                "residual": 0,
            }
        )

        self.assertEqual(
            parsed,
            {
                "amount": 12.34,
                "emission_date": date(2026, 4, 1),
                "charge_date": date(2026, 4, 15),
                "status": "PAY_OK",
                "number": "2026/123",
                "residual": 0.0,
            },
        )

    def test_missing_invoice_yields_empty_dict(self) -> None:
        self.assertEqual(_parse_bill(None), {})
        self.assertEqual(_parse_bill({}), {})


class ParseConsumptionsTest(unittest.TestCase):
    def test_smart_meter_readings_and_cap_percentage(self) -> None:
        parsed = _parse_consumptions(
            {
                "annualConsumptions": {
                    "totalConsumption": 1617.59,
                    "maxConsumption": 2630,
                    "deltaPercentage": 0,
                },
                "consumptions": {
                    "g2": {
                        "data": [
                            {"period": "2026-04-21T00:00:00.000+00:00", "value": 7.1},
                            {"period": "2026-04-22T00:00:00.000+00:00", "value": 8.306},
                        ]
                    }
                },
            }
        )

        self.assertEqual(parsed["ytd"], 1617.59)
        self.assertEqual(parsed["cap"], 2630.0)
        self.assertEqual(parsed["cap_usage_percentage"], 61.5)
        self.assertEqual(parsed["delta_percentage"], 0.0)
        self.assertEqual(parsed["latest_value"], 8.306)
        self.assertEqual(parsed["latest_date"], "2026-04-22T00:00:00.000+00:00")

    def test_missing_partial_and_zero_readings_are_skipped(self) -> None:
        parsed = _parse_consumptions(
            {
                "annualConsumptions": {},
                "consumptions": {
                    "g2": {
                        "data": [
                            {"period": "2026-04-20T00:00:00.000+00:00", "value": 5.0},
                            {"period": "2026-04-21T00:00:00.000+00:00", "value": 0},
                            {
                                "period": "2026-04-22T00:00:00.000+00:00",
                                "value": 9.9,
                                "isPartial": True,
                            },
                            {
                                "period": "2026-04-23T00:00:00.000+00:00",
                                "value": 9.9,
                                "isMissing": True,
                            },
                        ]
                    }
                },
            }
        )

        self.assertEqual(parsed["latest_value"], 5.0)
        self.assertEqual(parsed["latest_date"], "2026-04-20T00:00:00.000+00:00")

    def test_falls_back_to_past_months_for_non_smart_meters(self) -> None:
        parsed = _parse_consumptions(
            {
                "annualConsumptions": {"totalConsumption": 168.45},
                "consumptions": {
                    "g2": {"data": []},
                    "pastMonths": [
                        {"period": "2026-02", "realConsumption": 20.0},
                        {"period": "2026-03", "estimatedConsumption": 14.5},
                    ],
                },
            }
        )

        self.assertEqual(parsed["latest_value"], 14.5)
        self.assertEqual(parsed["latest_date"], "2026-03")

    def test_cap_percentage_is_none_without_a_cap(self) -> None:
        parsed = _parse_consumptions(
            {"annualConsumptions": {"totalConsumption": 100, "maxConsumption": 0}}
        )

        self.assertIsNone(parsed["cap_usage_percentage"])
        self.assertIsNone(parsed["latest_value"])


if __name__ == "__main__":
    unittest.main()
