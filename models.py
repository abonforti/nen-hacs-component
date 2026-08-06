from __future__ import annotations


def iter_subscriptions(home_contexts: list[dict]) -> list[tuple[dict, dict]]:
    return [
        (home, sub)
        for home in home_contexts
        for sub in home.get("subscriptions", [])
    ]


def legacy_subscription_ids(home_contexts: list[dict]) -> dict[str, str]:
    """Return subscriptions selected by versions using home_contexts[0]."""
    if not home_contexts:
        return {}

    legacy_ids: dict[str, str] = {}
    for sub in home_contexts[0].get("subscriptions", []):
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
