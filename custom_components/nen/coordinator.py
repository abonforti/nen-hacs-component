from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NenApiClient, NenApiError, NenAuthError
from .const import DOMAIN, SCAN_INTERVAL_HOURS
from .models import (
    latest_bills_by_utility,
    legacy_subscription_ids,
    preferred_subscriptions,
)

_LOGGER = logging.getLogger(__name__)


class NenDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(
        self,
        hass: HomeAssistant,
        client: NenApiClient,
        excluded: set[str] | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=SCAN_INTERVAL_HOURS),
        )
        self.client = client
        self.excluded = excluded or set()

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch_all()
        except NenAuthError as err:
            # Only raised once Cognito has actually rejected the credentials,
            # so this starts a reauthentication flow rather than retrying.
            raise ConfigEntryAuthFailed(f"Authentication error: {err}") from err
        except NenApiError as err:
            raise UpdateFailed(f"API error: {err}") from err

    async def _fetch_all(self) -> dict[str, Any]:
        home_contexts = await self.client.get_home_contexts()
        if not home_contexts:
            raise UpdateFailed("No home contexts returned")

        # Opportunity codes live in profile/details, not home-contexts
        opp_codes: dict[str, str] = {}
        try:
            profile = await self.client.get_profile_details()
            for s in profile.get("subscriptions", []):
                sid = s.get("id")
                code = s.get("code")
                if sid and code:
                    opp_codes[sid] = code
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Could not fetch profile details for opportunity codes")

        result: dict[str, Any] = {
            "homes": {},
            "subscriptions": {},
            # Legacy IDs are derived from every active contract, not just the
            # selected ones, so excluding a property cannot renumber the
            # entities of the ones that remain.
            "legacy_subscription_ids": legacy_subscription_ids(home_contexts),
            "available": _available_subscriptions(home_contexts),
        }

        # Bill details are scoped by home context. Keep each home's utility
        # invoices separate so properties cannot receive each other's bill.
        bills_by_home: dict[str, dict[str, dict]] = {}
        for home in home_contexts:
            home_id = home.get("id")
            if not home_id:
                continue
            try:
                bills_data = await self.client.get_bill_details(home_id)
                bills_by_home[home_id] = latest_bills_by_utility(
                    bills_data.get("invoices", [])
                )
            except NenApiError:
                _LOGGER.warning("Could not fetch bill details for home %s", home_id)

        for home, sub in preferred_subscriptions(home_contexts):
            utility = sub.get("utility")  # "EE" or "GA"
            if not utility:
                continue

            sub_id = sub.get("id")
            if not sub_id or sub_id in self.excluded:
                continue

            home_id = home.get("id")
            if home_id:
                result["homes"][home_id] = {
                    "id": home_id,
                    "name": home.get("name"),
                    "address": home.get("address") or home.get("fullAddress"),
                    "is_default": home.get("isDefault", False),
                }

            pod = sub.get("podName")
            opp_code = opp_codes.get(sub_id, "")

            # supplyId is already present in home-contexts subscriptions
            supply_id = sub.get("supplyId")
            home_bills = bills_by_home.get(home_id, {}) if home_id else {}

            entry: dict[str, Any] = {
                "id": sub_id,
                "home_id": home_id,
                "home_name": home.get("name"),
                "home_address": home.get("address") or home.get("fullAddress"),
                "home_is_default": home.get("isDefault", False),
                "pod": pod,
                "status": sub.get("status"),
                "utility": utility,
                "supply_id": supply_id,
                "is2g": sub.get("is2g", False),
                "tariff_name": sub.get("contractInformation", {}).get("name"),
                "contract": {},
                "consumptions": None,
                "last_bill": _parse_bill(home_bills.get(utility)),
            }

            # Contract details (monthly rate, renewal date)
            try:
                contract_data = await self.client.get_contract(sub_id)
                entry["contract"] = _parse_contract(contract_data)
            except NenApiError:
                _LOGGER.warning("Could not fetch contract for %s %s", utility, sub_id)

            # Subscription detail (pricing)
            try:
                detail_data = await self.client.get_subscription_detail(
                    opp_code, sub_id
                )
                entry["detail"] = _parse_detail(detail_data)
            except NenApiError:
                _LOGGER.debug("Could not fetch subscription detail for %s", sub_id)
                entry["detail"] = {}

            # Consumptions
            if supply_id:
                try:
                    consumptions_raw = await self.client.get_global_consumptions(
                        supply_id
                    )
                    entry["consumptions"] = _parse_consumptions(consumptions_raw)
                except NenApiError:
                    _LOGGER.warning(
                        "Could not fetch consumptions for %s supply %s",
                        utility,
                        supply_id,
                    )

            result["subscriptions"][sub_id] = entry

        return result


def _available_subscriptions(home_contexts: list[dict]) -> list[dict]:
    """List every active contract, including ones the user excluded.

    The options flow needs the full set to render its checkboxes; the
    coordinator's own data only holds the selected ones.
    """
    available: list[dict] = []
    for home, sub in preferred_subscriptions(home_contexts):
        sub_id = sub.get("id")
        utility = sub.get("utility")
        if not sub_id or not utility:
            continue
        available.append(
            {
                "id": sub_id,
                "utility": utility,
                "home_name": home.get("name"),
                "home_address": home.get("address") or home.get("fullAddress"),
                "pod": sub.get("podName"),
            }
        )
    return available


def _parse_contract(data: dict) -> dict:
    # subscriptionPrice is the rate before discounts; subscriptionDiscount is
    # already signed negative, so the net rate the NeN app shows is their sum.
    gross = _safe_float(data.get("subscriptionPrice"))
    discount = _safe_float(data.get("subscriptionDiscount")) or 0.0
    return {
        "monthly_rate": None if gross is None else round(gross + discount, 2),
        "monthly_rate_gross": gross,
        "discount": discount or None,
        "cost_breakdown": _parse_cost_breakdown(data.get("billDetails")),
        # "prospected" is NeN's wording: on a supply still being activated this
        # is a planned date, not a historical one.
        "activation_date": _parse_date(data.get("prospectedActivationDate")),
        "end_date": _parse_date(data.get("renewalDate")),
        "recalculation_date": _parse_date(data.get("recalculationDate")),
        "offer_type": data.get("offerType"),
    }


def _parse_cost_breakdown(bill_details: Any) -> list[dict] | None:
    """Summarise the categories that make up the monthly rate.

    `billDetails` splits the rate into categories such as "Consumo" or
    "Quota fissa", whose values add up to `subscriptionPrice`. A discount
    appears here as its own category only when the account has one.
    """
    if not isinstance(bill_details, list):
        return None

    breakdown: list[dict] = []
    for category in bill_details:
        if not isinstance(category, dict):
            continue
        value = _safe_float(category.get("categoryLabelValue"))
        if value is None:
            continue
        breakdown.append(
            {
                "id": category.get("id"),
                "label": category.get("categoryLabel"),
                "value": round(value, 2),
            }
        )
    return breakdown or None


def _parse_detail(data: dict) -> dict:
    pv = data.get("productVersion", {})
    return {
        # consumptionPrice uses Italian decimal format ("0,13943") — _safe_float handles comma
        "unit_price": _safe_float(pv.get("consumptionPrice") or pv.get("price")),
        "annual_fixed_price": _safe_float(pv.get("annualFixedPrice")),
    }


def _parse_bill(invoice: dict | None) -> dict:
    if not invoice:
        return {}
    return {
        "amount": _safe_float(invoice.get("amount")),
        "emission_date": _parse_date(invoice.get("emissionDate")),
        "charge_date": _parse_date(invoice.get("chargeDate")),
        "status": invoice.get("status"),
        "number": invoice.get("number"),
        "residual": _safe_float(invoice.get("residual")),
    }


def _parse_consumptions(data: dict) -> dict:
    ac = data.get("annualConsumptions", {})
    ytd = _safe_float(ac.get("totalConsumption"))
    cap = _safe_float(ac.get("maxConsumption"))
    cap_usage_percentage = (
        round((ytd / cap) * 100, 1) if ytd is not None and cap else None
    )

    # Daily 2G smart meter readings: consumptions.g2.data[].{period, value, isMissing}
    daily: list[dict] = data.get("consumptions", {}).get("g2", {}).get("data", [])
    latest_value = None
    latest_date = None
    # Walk backwards to find last non-missing, non-zero 2G entry
    for entry in reversed(daily):
        if not entry.get("isMissing") and not entry.get("isPartial"):
            v = _safe_float(entry.get("value"))
            if v is not None and v > 0:
                latest_value = v
                latest_date = entry.get("period")
                break

    # Fallback for non-2G meters: use latest month from pastMonths
    if latest_value is None:
        past_months: list[dict] = data.get("consumptions", {}).get("pastMonths", [])
        for month in reversed(past_months):
            v = _safe_float(
                month.get("realConsumption") or month.get("estimatedConsumption")
            )
            if v is not None and v > 0:
                latest_value = v
                latest_date = month.get("period")
                break

    return {
        "ytd": ytd,
        "cap": cap,
        "cap_usage_percentage": cap_usage_percentage,
        # NeN's own pacing indicator (projected vs actual trajectory toward
        # the annual cap). Meaning isn't documented anywhere; exposed as-is
        # as an attribute rather than a standalone sensor for that reason.
        "delta_percentage": _safe_float(ac.get("deltaPercentage")),
        "daily": daily,
        "latest_value": latest_value,
        "latest_date": latest_date,
    }


def _parse_date(value: str | None) -> date | None:
    """Parse an ISO 'YYYY-MM-DD' string into a date object.

    Required for anything fed into a SensorDeviceClass.DATE sensor's
    native_value - Home Assistant expects an actual date object there, not a
    string, and silently marks the entity unavailable otherwise.
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if isinstance(value, str):
            value = value.replace(",", ".")
        return float(value)
    except (ValueError, TypeError):
        return None
