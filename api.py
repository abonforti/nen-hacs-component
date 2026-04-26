from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from .const import API_BASE_URL, COGNITO_CLIENT_ID, COGNITO_USER_POOL_ID


class NenAuthError(Exception):
    pass


class NenApiError(Exception):
    pass


class NenApiClient:
    def __init__(self, username: str, password: str, session: aiohttp.ClientSession) -> None:
        self._username = username
        self._password = password
        self._session = session
        self._id_token: str | None = None
        self._token_expiry: datetime | None = None

    async def _ensure_token(self) -> None:
        if (
            self._id_token
            and self._token_expiry
            and datetime.now(timezone.utc) < self._token_expiry
        ):
            return
        try:
            await asyncio.get_event_loop().run_in_executor(None, self._authenticate_sync)
        except Exception as err:
            raise NenAuthError(f"Authentication failed: {err}") from err

    def _authenticate_sync(self) -> None:
        from pycognito import Cognito  # noqa: PLC0415

        u = Cognito(COGNITO_USER_POOL_ID, COGNITO_CLIENT_ID, username=self._username)
        u.authenticate(password=self._password)
        self._id_token = u.id_token
        # Conservative expiry: refresh 5 min before actual expiry
        self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=3300)

    async def _request(self, path: str, *, raw_auth: bool = False, params: dict | None = None) -> Any:
        await self._ensure_token()
        auth_value = self._id_token if raw_auth else f"Bearer {self._id_token}"
        headers = {
            "Authorization": auth_value,
            "Content-Type": "application/json",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Origin": "https://nen.it",
            "Referer": "https://nen.it/",
        }
        url = f"{API_BASE_URL}{path}"
        async with self._session.get(url, headers=headers, params=params) as resp:
            if resp.status == 401:
                # Token may have expired — force re-auth once
                self._id_token = None
                await self._ensure_token()
                auth_value = self._id_token if raw_auth else f"Bearer {self._id_token}"
                headers["Authorization"] = auth_value
                async with self._session.get(url, headers=headers, params=params) as retry:
                    if not retry.ok:
                        raise NenApiError(f"API error {retry.status} on {path}")
                    return await retry.json()
            if not resp.ok:
                raise NenApiError(f"API error {resp.status} on {path}")
            return await resp.json()

    async def validate_credentials(self) -> bool:
        try:
            await self._ensure_token()
            return True
        except NenAuthError:
            return False

    async def get_home_contexts(self) -> list[dict]:
        return await self._request("/profile/home-contexts")

    async def get_contract(self, subscription_id: str) -> dict:
        return await self._request(
            f"/subscriptions/contract/{subscription_id}",
            raw_auth=True,
            params={"origin": "Web"},
        )

    async def get_subscription_detail(self, code: str, subscription_id: str) -> dict:
        return await self._request(
            "/miaproxy-auth/users/subscription-detail",
            params={"code": code, "subscriptionId": subscription_id},
        )

    async def get_global_consumptions(self, supply_id: str) -> dict:
        return await self._request(
            "/consumptions/b2c/global-consumptions",
            raw_auth=True,
            params={"supplyId": supply_id, "origin": "web"},
        )

    async def get_profile_details(self) -> dict:
        return await self._request("/profile/details")

    async def get_invoices(self, month: int, year: int, pods: list[str]) -> dict:
        return await self._request(
            "/invoices",
            params={"month": f"{month:02d}", "year": str(year), "pods": ",".join(pods)},
        )
