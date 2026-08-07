import unittest

from models import (
    iter_subscriptions,
    latest_bills_by_utility,
    legacy_subscription_ids,
    preferred_subscriptions,
    subscription_identity,
)


class SubscriptionModelTest(unittest.TestCase):
    def test_single_home_keeps_legacy_subscription_ids(self) -> None:
        homes = [
            {
                "id": "home-1",
                "subscriptions": [
                    {"id": "electricity-1", "utility": "EE"},
                    {"id": "gas-1", "utility": "GA"},
                ],
            }
        ]

        self.assertEqual(
            legacy_subscription_ids(homes),
            {"EE": "electricity-1", "GA": "gas-1"},
        )
        self.assertEqual(
            iter_subscriptions(homes),
            [
                (homes[0], homes[0]["subscriptions"][0]),
                (homes[0], homes[0]["subscriptions"][1]),
            ],
        )

    def test_multiple_homes_return_every_subscription(self) -> None:
        homes = [
            {
                "id": "old-home",
                "subscriptions": [
                    {
                        "id": "old-electricity",
                        "utility": "EE",
                        "status": "CLOSED",
                    }
                ],
            },
            {
                "id": "new-home",
                "subscriptions": [
                    {"id": "new-electricity", "utility": "EE", "status": "ACTIVE"},
                    {"id": "new-gas", "utility": "GA", "status": "ACTIVE"},
                ],
            },
        ]

        subscriptions = iter_subscriptions(homes)

        self.assertEqual(
            [sub["id"] for _, sub in subscriptions],
            ["old-electricity", "new-electricity", "new-gas"],
        )
        self.assertEqual(
            legacy_subscription_ids(homes), {"EE": "new-electricity", "GA": "new-gas"}
        )

    def test_active_subscriptions_exclude_closed_contracts(self) -> None:
        homes = [
            {
                "id": "old-home",
                "subscriptions": [
                    {"id": "old-electricity", "utility": "EE", "status": "CLOSED"}
                ],
            },
            {
                "id": "current-home",
                "subscriptions": [
                    {"id": "current-electricity", "utility": "EE", "status": "ACTIVE"},
                    {"id": "old-gas", "utility": "GA", "status": "CLOSED"},
                    {"id": "current-gas", "utility": "GA", "status": "ACTIVE"},
                ],
            },
        ]

        subscriptions = preferred_subscriptions(homes)

        self.assertEqual(
            [sub["id"] for _, sub in subscriptions],
            ["current-electricity", "current-gas"],
        )
        self.assertEqual(
            legacy_subscription_ids(homes),
            {"EE": "current-electricity", "GA": "current-gas"},
        )

    def test_subscriptions_fall_back_when_none_are_active(self) -> None:
        homes = [
            {
                "id": "home",
                "subscriptions": [
                    {"id": "electricity", "utility": "EE", "status": "CLOSED"},
                    {"id": "gas", "utility": "GA"},
                ],
            }
        ]

        self.assertEqual(
            preferred_subscriptions(homes),
            iter_subscriptions(homes),
        )

    def test_legacy_selection_matches_previous_last_utility_wins_behavior(self) -> None:
        homes = [
            {
                "subscriptions": [
                    {"id": "electricity-1", "utility": "EE"},
                    {"id": "electricity-2", "utility": "EE"},
                ]
            }
        ]

        self.assertEqual(
            legacy_subscription_ids(homes), {"EE": "electricity-2"}
        )

    def test_subscription_identities_do_not_collide(self) -> None:
        legacy_ids = {"EE": "electricity-1"}

        self.assertEqual(
            subscription_identity("entry", "EE", "electricity-1", legacy_ids),
            ("entry", "EE"),
        )
        self.assertEqual(
            subscription_identity("entry", "EE", "electricity-2", legacy_ids),
            ("entry_electricity-2", "electricity-2"),
        )

    def test_latest_bill_is_selected_per_utility(self) -> None:
        newest_electricity = {"utility": "EE", "number": "new-ee"}
        invoices = [
            newest_electricity,
            {"utility": "GA", "number": "new-ga"},
            {"utility": "EE", "number": "old-ee"},
            {"number": "missing-utility"},
        ]

        self.assertEqual(
            latest_bills_by_utility(invoices),
            {
                "EE": newest_electricity,
                "GA": {"utility": "GA", "number": "new-ga"},
            },
        )


if __name__ == "__main__":
    unittest.main()
