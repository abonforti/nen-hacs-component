from __future__ import annotations


def iter_subscriptions(home_contexts: list[dict]) -> list[tuple[dict, dict]]:
    return [
        (home, sub)
        for home in home_contexts
        for sub in home.get("subscriptions", [])
    ]


def preferred_subscriptions(home_contexts: list[dict]) -> list[tuple[dict, dict]]:
    """Return active subscriptions, falling back to all when none are active."""
    subscriptions = iter_subscriptions(home_contexts)
    active = [
        (home, sub)
        for home, sub in subscriptions
        if sub.get("status") == "ACTIVE"
    ]
    return active or subscriptions


def legacy_subscription_ids(home_contexts: list[dict]) -> dict[str, str]:
    """Return preferred subscriptions receiving legacy entity IDs."""
    subscriptions = preferred_subscriptions(home_contexts)
    if not subscriptions:
        return {}

    legacy_home = subscriptions[0][0]
    legacy_ids: dict[str, str] = {}
    for home, sub in subscriptions:
        if home is not legacy_home:
            continue
        utility = sub.get("utility")
        subscription_id = sub.get("id")
        if utility and subscription_id:
            legacy_ids[utility] = subscription_id
    return legacy_ids


def subscription_identity(
    entry_id: str,
    utility: str,
    subscription_id: str,
    legacy_ids: dict[str, str],
) -> tuple[str, str]:
    """Return unique ID prefix and device suffix for a subscription."""
    if legacy_ids.get(utility) == subscription_id:
        return entry_id, utility
    return f"{entry_id}_{subscription_id}", subscription_id


def latest_bills_by_utility(invoices: list[dict]) -> dict[str, dict]:
    """Return the first, newest invoice for each utility."""
    latest: dict[str, dict] = {}
    for invoice in invoices:
        utility = invoice.get("utility")
        if utility and utility not in latest:
            latest[utility] = invoice
    return latest
