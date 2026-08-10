from __future__ import annotations

import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from gravity_sdk.sql import client as sql_client
from gravity_sdk.sql.client import GravityClient, SqlBatchRequest
try:
    from gravity_sdk.errors import (
        SqlResponseError,
        SqlValidationError,
        TransportError,
    )
    from gravity_sdk.credentials import CredentialProvider
    from gravity_sdk.http_runtime import GravityHttpRuntime, SQL_PROFILE
except ModuleNotFoundError:  # pragma: no cover - source-tree test execution.
    from gravity_sdk.errors import (
        SqlResponseError,
        SqlValidationError,
        TransportError,
    )
    from gravity_sdk.credentials import CredentialProvider
    from gravity_sdk.http_runtime import GravityHttpRuntime, SQL_PROFILE


class _FakeRuntime:
    def __init__(self) -> None:
        self.calls: list[
            tuple[object, str, str, dict[str, object], frozenset[int], float]
        ] = []

    def request(
        self,
        profile,
        method,
        path,
        *,
        json_body,
        semantic_auth_codes,
        timeout,
    ):
        self.calls.append(
            (profile, method, path, dict(json_body), semantic_auth_codes, timeout)
        )
        sql = json_body["sql"]
        if sql == "FAIL secret SQL":
            raise TransportError("sanitized transport failure")
        if sql == "HTTP failure SQL":
            return SimpleNamespace(status_code=503, payload={"secret": "response-body"})
        if sql == "BAD envelope SQL":
            return SimpleNamespace(
                status_code=200,
                payload={"status": "REJECTED", "secret": "response-body"},
            )
        return SimpleNamespace(
            status_code=200,
            payload={
                "data": {
                    "status": "SUCCESS",
                    "result": {
                        "columns": [{"name": "value"}],
                        "rows": [[sql]],
                    },
                }
            }
        )


class GravitySqlClientTests(unittest.TestCase):
    def tearDown(self) -> None:
        sql_client._CLIENT = None

    def test_execute_sql_uses_only_the_fixed_sql_profile_and_envelope(self):
        runtime = _FakeRuntime()
        client = GravityClient(runtime)

        self.assertEqual([{"value": "SELECT 1"}], client.execute_sql("SELECT 1"))
        self.assertEqual(
            (
                SQL_PROFILE,
                "POST",
                "/custom_sql/api/sql/execute",
                {"sql": "SELECT 1", "tabId": "1"},
                frozenset({2001, 10000, 10001}),
                300.0,
            ),
            runtime.calls[0],
        )
        with self.assertRaises(TypeError):
            GravityClient(endpoint="https://example.invalid")

    def test_sql_401_relogs_and_replays_once(self):
        login_calls: list[tuple[str, str]] = []

        def login(username: str, password: str):
            login_calls.append((username, password))
            return {"data": {"user": {"Authorization": "fresh-token"}, "day": 1}}

        provider = CredentialProvider(
            Path("does-not-exist.env"),
            environ={
                "GRAVITY_AUTH_TOKEN": "stale-token",
                "GRAVITY_USERNAME": "account",
                "GRAVITY_PASSWORD": "password",
            },
            login=login,
            persist=False,
        )

        class Response:
            headers: dict[str, str] = {}

            def __init__(self, status_code: int, payload: dict[str, object]) -> None:
                self.status_code = status_code
                self._payload = payload

            def json(self):
                return self._payload

        class Session:
            def __init__(self) -> None:
                self.tokens: list[str] = []

            def request(self, _method, _url, *, headers, **_kwargs):
                self.tokens.append(headers["Authorization"])
                if headers["Authorization"] == "stale-token":
                    return Response(401, {})
                return Response(
                    200,
                    {
                        "status": "SUCCESS",
                        "result": {
                            "columns": [{"name": "value"}],
                            "rows": [[1]],
                        },
                    },
                )

        session = Session()
        runtime = GravityHttpRuntime(
            session=session,
            credentials=provider,
            requests_per_second=100,
            sleeper=lambda _delay: None,
            interval_jitter_ratio=0,
            persist_credentials=False,
        )

        self.assertEqual([{"value": 1}], GravityClient(runtime).execute_sql("SELECT 1"))
        self.assertEqual(["stale-token", "fresh-token"], session.tokens)
        self.assertEqual([("account", "password")], login_calls)

    def test_sql_validation_and_response_failures_are_layered_and_redacted(self):
        client = GravityClient(_FakeRuntime())
        for invalid in ("", "   ", None, True):
            with self.subTest(invalid=invalid), self.assertRaises(SqlValidationError):
                client.execute_sql(invalid)  # type: ignore[arg-type]

        with self.assertRaises(SqlResponseError) as raised:
            client.execute_sql("BAD envelope SQL")
        message = str(raised.exception)
        self.assertNotIn("BAD envelope SQL", message)
        self.assertNotIn("response-body", message)

        with self.assertRaisesRegex(TransportError, r"HTTP 503") as http_failure:
            client.execute_sql("HTTP failure SQL")
        self.assertNotIn("response-body", str(http_failure.exception))

        crashing_runtime = mock.Mock()
        crashing_runtime.request.side_effect = RuntimeError(
            "SELECT private_value FROM secret_response"
        )
        with self.assertRaises(TransportError) as unexpected:
            GravityClient(crashing_runtime).execute_sql("SELECT private_value")
        self.assertIsNone(unexpected.exception.__cause__)
        self.assertNotIn("private_value", str(unexpected.exception))
        self.assertNotIn("secret_response", str(unexpected.exception))

    def test_batch_preserves_order_and_isolates_one_failure(self):
        client = GravityClient(_FakeRuntime())
        results = client.execute_batch(
            [
                SqlBatchRequest("SELECT 1", "first"),
                {"sql": "FAIL secret SQL", "request_id": "failed"},
                {"sql": "", "request_id": "invalid"},
                "SELECT 3",
            ],
            max_workers=2,
        )

        self.assertEqual(
            ["first", "failed", "invalid", None],
            [item["request_id"] for item in results],
        )
        self.assertEqual([True, False, False, True], [item["ok"] for item in results])
        self.assertEqual([{"value": "SELECT 1"}], results[0]["rows"])
        self.assertEqual([{"value": "SELECT 3"}], results[3]["rows"])
        self.assertNotIn("FAIL secret SQL", str(results[1]))
        self.assertIsNone(results[1]["rows"])
        self.assertIsNone(results[2]["rows"])

    def test_batch_hard_caps_workers_at_live_verified_two(self):
        client = GravityClient(_FakeRuntime())
        for invalid in (0, 3, True):
            with self.subTest(invalid=invalid), self.assertRaises(SqlValidationError):
                client.execute_batch(["SELECT 1"], max_workers=invalid)

    def test_batch_runs_more_than_one_request_concurrently(self):
        lock = threading.Lock()
        active = 0
        max_active = 0

        class ConcurrentRuntime(_FakeRuntime):
            def request(self, *args, **kwargs):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                try:
                    time.sleep(0.02)
                    return super().request(*args, **kwargs)
                finally:
                    with lock:
                        active -= 1

        runtime = ConcurrentRuntime()
        results = GravityClient(runtime).execute_batch(
            [f"SELECT {index}" for index in range(8)], max_workers=2
        )
        self.assertTrue(all(item["ok"] for item in results))
        self.assertEqual(2, max_active)

    def test_process_sql_limit_covers_direct_calls_across_client_instances(self):
        lock = threading.Lock()
        active = 0
        max_active = 0

        class ConcurrentRuntime(_FakeRuntime):
            def request(self, *args, **kwargs):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                try:
                    time.sleep(0.02)
                    return super().request(*args, **kwargs)
                finally:
                    with lock:
                        active -= 1

        runtime = ConcurrentRuntime()
        clients = (GravityClient(runtime), GravityClient(runtime))
        with ThreadPoolExecutor(max_workers=6) as pool:
            rows = list(
                pool.map(
                    lambda index: clients[index % 2].execute_sql(f"SELECT {index}"),
                    range(6),
                )
            )

        self.assertEqual(6, len(rows))
        self.assertEqual(2, max_active)

    def test_build_sql_client_reuses_one_long_lived_instance(self):
        runtime = _FakeRuntime()
        with mock.patch.object(sql_client, "get_shared_runtime", return_value=runtime) as factory:
            first = sql_client.build_sql_client()
            second = sql_client.build_sql_client()

        self.assertIs(first, second)
        factory.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
