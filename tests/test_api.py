"""Tests for the API client.

No network: the aiohttp session and pycognito are both replaced.
"""

import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import aiohttp

from custom_components.nen.api import NenApiClient, NenApiError, NenAuthError


class FakeResponse:
    def __init__(self, status: int = 200, payload=None) -> None:
        self.status = status
        self._payload = payload if payload is not None else {}

    @property
    def ok(self) -> bool:
        return self.status < 400

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False


class FakeSession:
    """Hands out queued responses and records how they were requested."""

    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, headers=None, params=None):
        self.calls.append(
            {"url": url, "headers": dict(headers or {}), "params": params}
        )
        return self.responses.pop(0)


def make_client(session, token: str | None = "tok") -> NenApiClient:
    client = NenApiClient("user@example.com", "hunter2", session)
    if token is not None:
        client._id_token = token
        client._token_expiry = datetime.now(UTC) + timedelta(hours=1)
    return client


class EnsureTokenTest(unittest.IsolatedAsyncioTestCase):
    async def test_valid_token_is_reused_without_authenticating(self) -> None:
        client = make_client(FakeSession())

        with patch.object(client, "_authenticate_sync") as auth:
            self.assertEqual(await client._ensure_token(), "tok")

        auth.assert_not_called()

    async def test_expired_token_triggers_reauthentication(self) -> None:
        client = make_client(FakeSession())
        client._token_expiry = datetime.now(UTC) - timedelta(seconds=1)

        def reauthenticate() -> None:
            client._id_token = "fresh"

        with patch.object(client, "_authenticate_sync", side_effect=reauthenticate):
            self.assertEqual(await client._ensure_token(), "fresh")

    async def test_unreachable_cognito_is_a_transient_api_error(self) -> None:
        """Not an auth error: the credentials were never actually judged."""
        client = make_client(FakeSession(), token=None)

        with patch.object(client, "_authenticate_sync", side_effect=OSError("no dns")):
            with self.assertRaises(NenApiError) as caught:
                await client._ensure_token()

        self.assertNotIsInstance(caught.exception, NenAuthError)

    async def test_rejected_credentials_stay_an_auth_error(self) -> None:
        client = make_client(FakeSession(), token=None)

        with patch.object(
            client, "_authenticate_sync", side_effect=NenAuthError("rejected")
        ):
            with self.assertRaises(NenAuthError):
                await client._ensure_token()

    async def test_authentication_without_a_token_is_an_auth_error(self) -> None:
        client = make_client(FakeSession(), token=None)

        with patch.object(client, "_authenticate_sync"):
            with self.assertRaises(NenAuthError):
                await client._ensure_token()

    async def test_validate_credentials_reports_success_and_failure(self) -> None:
        client = make_client(FakeSession())

        with patch.object(client, "_ensure_token", return_value="tok"):
            self.assertTrue(await client.validate_credentials())

        with patch.object(client, "_ensure_token", side_effect=NenAuthError("bad")):
            self.assertFalse(await client.validate_credentials())


class AuthenticateSyncTest(unittest.TestCase):
    @staticmethod
    def _client_error(code: str):
        from botocore.exceptions import ClientError

        return ClientError({"Error": {"Code": code, "Message": code}}, "InitiateAuth")

    def test_rejected_credentials_raise_auth_error(self) -> None:
        """Only these codes may trigger a reauthentication prompt."""
        for code in (
            "NotAuthorizedException",
            "UserNotFoundException",
            "PasswordResetRequiredException",
            "UserNotConfirmedException",
        ):
            client = make_client(FakeSession(), token=None)
            cognito = MagicMock()
            cognito.authenticate.side_effect = self._client_error(code)

            with patch("pycognito.Cognito", return_value=cognito):
                with self.assertRaises(NenAuthError, msg=code):
                    client._authenticate_sync()

    def test_other_aws_errors_are_not_credential_failures(self) -> None:
        """A throttle or an outage must not ask the user for a new password."""
        client = make_client(FakeSession(), token=None)
        cognito = MagicMock()
        cognito.authenticate.side_effect = self._client_error(
            "TooManyRequestsException"
        )

        with patch("pycognito.Cognito", return_value=cognito):
            with self.assertRaises(Exception) as caught:
                client._authenticate_sync()

        self.assertNotIsInstance(caught.exception, NenAuthError)

    def test_token_and_expiry_are_stored(self) -> None:
        client = make_client(FakeSession(), token=None)
        cognito = MagicMock()
        cognito.id_token = "signed-jwt"

        with patch("pycognito.Cognito", return_value=cognito) as factory:
            client._authenticate_sync()

        factory.assert_called_once()
        cognito.authenticate.assert_called_once_with(password="hunter2")
        self.assertEqual(client._id_token, "signed-jwt")
        self.assertIsNotNone(client._token_expiry)
        self.assertGreater(client._token_expiry, datetime.now(UTC))


class RequestTest(unittest.IsolatedAsyncioTestCase):
    async def test_bearer_prefix_is_used_by_default(self) -> None:
        session = FakeSession(FakeResponse(payload={"ok": True}))
        client = make_client(session)

        result = await client._request("/thing")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(session.calls[0]["headers"]["Authorization"], "Bearer tok")
        self.assertTrue(session.calls[0]["url"].endswith("/thing"))

    async def test_raw_auth_sends_the_bare_token(self) -> None:
        session = FakeSession(FakeResponse(payload=[1, 2]))
        client = make_client(session)

        result = await client._request("/thing", raw_auth=True, params={"a": "b"})

        self.assertEqual(result, [1, 2])
        self.assertEqual(session.calls[0]["headers"]["Authorization"], "tok")
        self.assertEqual(session.calls[0]["params"], {"a": "b"})

    async def test_error_status_raises(self) -> None:
        client = make_client(FakeSession(FakeResponse(status=500)))

        with self.assertRaises(NenApiError):
            await client._request("/thing")

    async def test_401_reauthenticates_and_retries_once(self) -> None:
        session = FakeSession(
            FakeResponse(status=401), FakeResponse(payload={"retried": True})
        )
        client = make_client(session)

        async def refresh() -> str:
            client._id_token = "fresh"
            return "fresh"

        with patch.object(client, "_ensure_token", side_effect=refresh):
            result = await client._request("/thing")

        self.assertEqual(result, {"retried": True})
        self.assertEqual(session.calls[1]["headers"]["Authorization"], "Bearer fresh")

    async def test_401_then_failure_raises(self) -> None:
        session = FakeSession(FakeResponse(status=401), FakeResponse(status=403))
        client = make_client(session)

        with patch.object(client, "_ensure_token", return_value="fresh"):
            with self.assertRaises(NenApiError):
                await client._request("/thing")

    async def test_401_retry_keeps_raw_auth(self) -> None:
        session = FakeSession(FakeResponse(status=401), FakeResponse(payload={}))
        client = make_client(session)

        with patch.object(client, "_ensure_token", return_value="fresh"):
            await client._request("/thing", raw_auth=True)

        self.assertEqual(session.calls[1]["headers"]["Authorization"], "fresh")


class EndpointTest(unittest.IsolatedAsyncioTestCase):
    """Each endpoint's path, parameters and auth style."""

    async def _capture(self, call) -> dict:
        session = FakeSession(FakeResponse(payload={}))
        client = make_client(session)
        await call(client)
        return session.calls[0]

    async def test_home_contexts(self) -> None:
        call = await self._capture(lambda c: c.get_home_contexts())
        self.assertTrue(call["url"].endswith("/profile/home-contexts"))
        self.assertTrue(call["headers"]["Authorization"].startswith("Bearer "))

    async def test_contract_uses_raw_auth(self) -> None:
        call = await self._capture(lambda c: c.get_contract("sub-1"))
        self.assertTrue(call["url"].endswith("/subscriptions/contract/sub-1"))
        self.assertEqual(call["params"], {"origin": "Web"})
        self.assertEqual(call["headers"]["Authorization"], "tok")

    async def test_subscription_detail(self) -> None:
        call = await self._capture(lambda c: c.get_subscription_detail("CODE", "sub-1"))
        self.assertTrue(
            call["url"].endswith("/miaproxy-auth/users/subscription-detail")
        )
        self.assertEqual(call["params"], {"code": "CODE", "subscriptionId": "sub-1"})

    async def test_global_consumptions_uses_raw_auth(self) -> None:
        call = await self._capture(lambda c: c.get_global_consumptions("supply-1"))
        self.assertTrue(call["url"].endswith("/consumptions/b2c/global-consumptions"))
        self.assertEqual(call["params"], {"supplyId": "supply-1", "origin": "web"})
        self.assertEqual(call["headers"]["Authorization"], "tok")

    async def test_profile_details(self) -> None:
        call = await self._capture(lambda c: c.get_profile_details())
        self.assertTrue(call["url"].endswith("/profile/details"))

    async def test_bill_details_uses_raw_auth(self) -> None:
        call = await self._capture(lambda c: c.get_bill_details("home-1"))
        self.assertTrue(call["url"].endswith("/bills/details/home-1"))
        self.assertEqual(call["headers"]["Authorization"], "tok")


class ClientErrorTest(unittest.IsolatedAsyncioTestCase):
    async def test_transport_errors_propagate(self) -> None:
        session = MagicMock()
        session.get.side_effect = aiohttp.ClientError("boom")
        client = make_client(session)

        with self.assertRaises(aiohttp.ClientError):
            await client._request("/thing")


if __name__ == "__main__":
    unittest.main()
