from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NenApiClient, NenApiError, NenAuthError
from .const import DOMAIN, SCAN_INTERVAL_HOURS

_LOGGER = logging.getLogger(__name__)


class NenDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, client: NenApiClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(hours=SCAN_INTERVAL_HOURS),
        )
        self.client = client

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self._fetch_all()
        except NenAuthError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
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

        home = home_contexts[0]
        home_id = home.get("id")
        result: dict[str, Any] = {
            "home": {
                "id": home_id,
                "name": home.get("name"),
                "address": home.get("address"),
            },
            "subscriptions": {},
        }

        # Latest bill per utility, keyed off the home context rather than the
        # subscription: /bills/details/{homeContextId} returns every invoice
        # for the home in one call, each tagged with its own "utility".
        bills_by_utility: dict[str, dict] = {}
        if home_id:
            try:
                bills_data = await self.client.get_bill_details(home_id)
                for inv in bills_data.get("invoices", []):
                    utility = inv.get("utility")
                    if not utility:
                        continue
                    # API returns newest-first; keep only the first (latest) per utility.
                    if utility not in bills_by_utility:
                        bills_by_utility[utility] = inv
            except NenApiError:
                _LOGGER.warning("Could not fetch bill details for home %s", home_id)

        for sub in home.get("subscriptions", []):
            utility = sub.get("utility")  # "EE" or "GA"
            if not utility:
                continue

            sub_id = sub.get("id")
            pod = sub.get("podName")
            opp_code = opp_codes.get(sub_id, "")

            # supplyId is already present in home-contexts subscriptions
            supply_id = sub.get("supplyId")

            entry: dict[str, Any] = {
                "id": sub_id,
                "pod": pod,
                "status": sub.get("status"),
                "utility": utility,
                "supply_id": supply_id,
                "is2g": sub.get("is2g", False),
                "tariff_name": sub.get("contractInformation", {}).get("name"),
                "contract": {},
                "consumptions": None,
                "last_bill": _parse_bill(bills_by_utility.get(utility)),
            }

            # Contract details (monthly rate, renewal date)
            try:
                contract_data = await self.client.get_contract(sub_id)
                entry["contract"] = _parse_contract(contract_data)
            except NenApiError:
                _LOGGER.warning("Could not fetch contract for %s %s", utility, sub_id)

            # Subscription detail (pricing)
            try:
                detail_data = await self.client.get_subscription_detail(opp_code, sub_id)
                entry["detail"] = _parse_detail(detail_data)
            except NenApiError:
                _LOGGER.debug("Could not fetch subscription detail for %s", sub_id)
                entry["detail"] = {}

            # Consumptions
            if supply_id:
                try:
                    consumptions_raw = await self.client.get_global_consumptions(supply_id)
                    entry["consumptions"] = _parse_consumptions(consumptions_raw)
                except NenApiError:
                    _LOGGER.warning("Could not fetch consumptions for %s supply %s", utility, supply_id)

            result["subscriptions"][utility] = entry

        # Invoices for current and previous month
        # NOTE: kept for backwards compatibility, but a live capture of
        # nen.it's own network traffic (2026-07) no longer showed any call to
        # this endpoint — the frontend now uses get_bill_details() above
        # instead. This may be stale/deprecated; left in place rather than
        # removed since it's not causing failures (NenApiError is caught) and
        # someone's account/tariff might still depend on it.
        pods = [
            s.get("pod")
            for s in result["subscriptions"].values()
            if s.get("pod")
        ]
        if pods:
            now = datetime.now().astimezone()
            invoices: list[dict] = []
            for month_offset in range(3):
                dt = now.replace(day=1) - timedelta(days=30 * month_offset)
                try:
                    inv = await self.client.get_invoices(dt.month, dt.year, pods)
                    invoices.extend(inv.get("podInvoices", []))
                except NenApiError:
                    break
            result["invoices"] = invoices

        return result


def _parse_contract(data: dict) -> dict:
    return {
        "monthly_rate": _safe_float(data.get("subscriptionPrice")),
        "end_date": _parse_date(data.get("renewalDate")),
        "recalculation_date": _parse_date(data.get("recalculationDate")),
        "offer_type": data.get("offerType"),
    }


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
    cap_usage_percentage = round((ytd / cap) * 100, 1) if ytd is not None and cap else None

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
            v = _safe_float(month.get("realConsumption") or month.get("estimatedConsumption"))
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
