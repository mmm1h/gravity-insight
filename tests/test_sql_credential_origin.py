"""SQL credential failures name their origin and survive runtime retirement (#230)."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from gravity_insight.credential_storage import EXPIRY_KEY, session_path
from gravity_insight.credentials import CredentialProvider
from gravity_insight.errors import CredentialError
from gravity_insight.http_runtime import GravityHttpRuntime
from gravity_insight.shared_runtime import get_shared_runtime, reset_shared_runtimes
from gravity_insight.sql import client as sql_client
from gravity_insight.sql.client import GravityClient
from gravity_insight.sql.failures import classify_sql_failure, diagnostic_fields


def _code_and_origin(error: BaseException) -> tuple[str, str | None]:
    failure = classify_sql_failure(error, request_count=1)
    fields = diagnostic_fields(failure, elapsed_seconds=0, request_count=1, request_count_bound=1)
    return failure.code, fields["upstream_error"].get("credential_origin")


class _Response:
    headers: dict[str, str] = {}

    def __init__(self, payload: dict[str, object]) -> None:
        self.status_code = 200
        self._payload = payload

    def json(self):
        return self._payload


class _AuthRejectingSession:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, _method, _url, *, headers, **_kwargs):
        self.calls += 1
        return _Response({"code": 10000})


class SqlCredentialOriginTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_shared_runtimes()
        sql_client._CLIENT = None

    def tearDown(self) -> None:
        reset_shared_runtimes()
        sql_client._CLIENT = None

    def test_rebuilt_sql_client_follows_a_retired_shared_runtime(self):
        with tempfile.TemporaryDirectory() as raw:
            env_path = Path(raw) / "account.env"
            env_path.write_text("GRAVITY_USERNAME=fixture\nGRAVITY_PASSWORD=pw\n", encoding="utf-8")
            session = session_path(env_path)
            session.write_text("GRAVITY_AUTH_TOKEN=token-1\nGRAVITY_SESSION_USERNAME=fixture\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {"GRAVITY_ENV_FILE": str(env_path)}):
                first = sql_client.build_sql_client()
                self.assertIs(first, sql_client.build_sql_client())
                # A login elsewhere persists a new token; the next lookup retires that generation.
                session.write_text("GRAVITY_AUTH_TOKEN=token-2\nGRAVITY_SESSION_USERNAME=fixture\n", encoding="utf-8")
                current = get_shared_runtime()
                with self.assertRaises(CredentialError) as raised:
                    first.execute_sql("SELECT 1")
                rebuilt = sql_client.build_sql_client()
        self.assertEqual(("SQL_PRODUCT_CREDENTIALS_UNAVAILABLE", "runtime_retired"), _code_and_origin(raised.exception))
        self.assertIsNot(first, rebuilt)
        self.assertIs(current, rebuilt._runtime)

    def test_refresh_failure_states_whether_a_response_was_rejected_first(self):
        expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(timespec="seconds")
        cases = {
            "auth_rejection_refresh": ({"GRAVITY_AUTH_TOKEN": "token"}, 1),
            "token_refresh": ({"GRAVITY_AUTH_TOKEN": "token", EXPIRY_KEY: expired}, 0),
        }
        for origin, (environ, dispatched) in cases.items():
            session = _AuthRejectingSession()
            # Token-only credentials cannot log in, so every refresh fails locally.
            provider = CredentialProvider(Path("does-not-exist.env"), environ=environ, persist=False)
            runtime = GravityHttpRuntime(
                session=session,
                credentials=provider,
                requests_per_second=100,
                sleeper=lambda _delay: None,
                interval_jitter_ratio=0,
                persist_credentials=False,
            )
            with self.subTest(origin=origin):
                with self.assertRaises(CredentialError) as raised:
                    GravityClient(runtime).execute_sql("SELECT 1")
                self.assertEqual(("SQL_PRODUCT_CREDENTIALS_UNAVAILABLE", origin), _code_and_origin(raised.exception))
                self.assertEqual(dispatched, session.calls)


if __name__ == "__main__":
    unittest.main()
