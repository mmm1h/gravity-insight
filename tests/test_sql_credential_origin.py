"""SQL credential failures name their origin and survive runtime retirement (#230)."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from gravity_insight import runtime_scope
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


class _TabularSession:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, _method, _url, **_kwargs):
        self.calls += 1
        return _Response({"status": "success", "result": {"columns": [{"name": "n"}], "rows": [[1]]}})


class _UnreadableOnce:
    def __init__(self, original) -> None:
        self.original, self.armed = original, False

    def __call__(self, path):
        if self.armed:
            self.armed = False
            raise CredentialError("could not read the Gravity credential file")
        return self.original(path)


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

    def _account(self, raw: str) -> Path:
        env_path = Path(raw) / "account.env"
        env_path.write_text("GRAVITY_USERNAME=fixture\nGRAVITY_PASSWORD=pw\n", encoding="utf-8")
        session_path(env_path).write_text("GRAVITY_AUTH_TOKEN=token-1\nGRAVITY_SESSION_USERNAME=fixture\n", encoding="utf-8")
        return env_path

    def _new_generation(self, env_path: Path) -> None:
        # A login elsewhere in the process persists a token; the next lookup retires the old runtime.
        session_path(env_path).write_text("GRAVITY_AUTH_TOKEN=token-2\nGRAVITY_SESSION_USERNAME=fixture\n", encoding="utf-8")
        get_shared_runtime()

    def test_held_cli_facade_rebinds_once_when_a_request_fails_before_dispatch(self):
        # verify and query hold one facade across products; a failure that never
        # reached the engine must not fail every later product (#230).
        reader = _UnreadableOnce(runtime_scope.read_env_file)
        disturbances = {"runtime_retired": self._new_generation, "credential_load": lambda _path: setattr(reader, "armed", True)}
        for origin, disturb in disturbances.items():
            with self.subTest(origin=origin), tempfile.TemporaryDirectory() as raw:
                reset_shared_runtimes()
                sql_client._CLIENT = None
                session, env_path = _TabularSession(), self._account(raw)
                with mock.patch.dict(os.environ, {"GRAVITY_ENV_FILE": str(env_path)}), mock.patch(
                    "gravity_insight.http_runtime._build_session", return_value=session
                ), mock.patch.object(runtime_scope, "read_env_file", reader), mock.patch.object(sql_client.time, "sleep"):
                    facade = sql_client.build_sql_client()
                    facade.execute_sql("SELECT 1")
                    disturb(env_path)
                    self.assertEqual([{"n": 1}], facade.execute_sql("SELECT 2"))
                self.assertEqual(2, session.calls)

    def test_held_cli_facade_never_rebinds_to_another_account(self):
        with tempfile.TemporaryDirectory() as raw:
            session, env_path = _TabularSession(), self._account(raw)
            with mock.patch.dict(os.environ, {"GRAVITY_ENV_FILE": str(env_path)}), mock.patch(
                "gravity_insight.http_runtime._build_session", return_value=session
            ):
                facade = sql_client.build_sql_client()
                facade.execute_sql("SELECT 1")
                env_path.write_text("GRAVITY_USERNAME=other\nGRAVITY_PASSWORD=pw\n", encoding="utf-8")
                get_shared_runtime()
                with self.assertRaises(CredentialError) as raised:
                    facade.execute_sql("SELECT 2")
        self.assertEqual(("SQL_PRODUCT_CREDENTIALS_UNAVAILABLE", "runtime_retired"), _code_and_origin(raised.exception))
        self.assertEqual(1, session.calls)

    def test_held_cli_facade_never_retries_a_request_the_service_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            env_path = Path(raw) / "account.env"
            env_path.write_text("", encoding="utf-8")
            session_path(env_path).write_text("GRAVITY_AUTH_TOKEN=token-1\n", encoding="utf-8")
            session = _AuthRejectingSession()
            with mock.patch.dict(os.environ, {"GRAVITY_ENV_FILE": str(env_path)}), mock.patch(
                "gravity_insight.http_runtime._build_session", return_value=session
            ):
                with self.assertRaises(CredentialError) as raised:
                    sql_client.build_sql_client().execute_sql("SELECT 1")
        self.assertEqual(("SQL_PRODUCT_CREDENTIALS_UNAVAILABLE", "auth_rejection_refresh"), _code_and_origin(raised.exception))
        self.assertEqual(1, session.calls)

    def test_sdk_pinned_client_still_fails_closed_on_a_retired_runtime(self):
        with tempfile.TemporaryDirectory() as raw:
            env_path = self._account(raw)
            with mock.patch.dict(os.environ, {"GRAVITY_ENV_FILE": str(env_path)}), mock.patch(
                "gravity_insight.http_runtime._build_session", return_value=_TabularSession()
            ):
                pinned = GravityClient(get_shared_runtime())
                self._new_generation(env_path)
                with self.assertRaises(CredentialError) as raised:
                    pinned.execute_sql("SELECT 1")
        self.assertEqual(("SQL_PRODUCT_CREDENTIALS_UNAVAILABLE", "runtime_retired"), _code_and_origin(raised.exception))

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
                # The remedy names what fixes the failed step, not a status check that passes.
                self.assertIn("GRAVITY_USERNAME and GRAVITY_PASSWORD", classify_sql_failure(raised.exception).next_action)


if __name__ == "__main__":
    unittest.main()
