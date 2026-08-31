from __future__ import annotations

import threading
from threading import Barrier
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from gravity_insight.sql import client as sql_client
from gravity_insight.sql.client import GravityClient, SqlBatchRequest
from gravity_insight.sql.failures import (
    classify_sql_failure,
    diagnostic_fields,
)
try:
    from gravity_insight.errors import (
        SqlResponseError,
        SqlValidationError,
        TransportError,
    )
    from gravity_insight.credentials import CredentialProvider
    from gravity_insight.http_runtime import GravityHttpRuntime, SQL_PROFILE
except ModuleNotFoundError:  # pragma: no cover - source-tree test execution.
    from gravity_insight.errors import (
        SqlResponseError,
        SqlValidationError,
        TransportError,
    )
    from gravity_insight.credentials import CredentialProvider
    from gravity_insight.http_runtime import GravityHttpRuntime, SQL_PROFILE


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

    def test_extract_rows_characterizes_supported_and_rejected_envelopes(self):
        direct = [{"value": 1}]
        cases = (
            ("direct rows", direct, direct),
            ("mixed direct rows", [{"value": 1}, [2]], None),
            ("scalar", "not-tabular", None),
            (
                "tabular result",
                {
                    "result": {
                        "columns": [{"name": "first"}, "second"],
                        "rows": [[1, 2, 3], [4], "ignored"],
                    }
                },
                [{"first": 1, "second": 2}, {"first": 4}],
            ),
            (
                "invalid tabular columns block fallback",
                {
                    "result": {"columns": [{"name": ""}], "rows": [[1]]},
                    "data": [{"fallback": True}],
                },
                None,
            ),
            ("data rows", {"data": direct}, direct),
            ("rows rows", {"rows": direct}, direct),
            ("result rows", {"result": direct}, direct),
            (
                "invalid earlier list permits later key",
                {"data": [1], "rows": direct},
                direct,
            ),
            ("nested data", {"data": {"result": direct}}, direct),
            ("nested rows", {"rows": {"data": direct}}, direct),
            ("nested result", {"result": {"rows": direct}}, direct),
            ("no rows", {"data": {"value": 1}}, None),
        )
        for name, payload, expected in cases:
            with self.subTest(shape=name):
                self.assertEqual(expected, sql_client._extract_rows(payload))
        self.assertIs(direct, sql_client._extract_rows(direct))

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

    def test_six_client_failures_have_stable_shared_diagnostics(self):
        unsafe = "SELECT private_value FROM secret_table WHERE app_id=76543210"
        cases = (
            (
                "transport",
                RuntimeError(unsafe),
                None,
                TransportError,
                ("execute", "transport_failure", "SQL_TRANSPORT_FAILED", True, "no"),
            ),
            (
                "invalid-status",
                None,
                SimpleNamespace(status_code="invalid", payload={"msg": unsafe}),
                TransportError,
                ("shape", "http_status_shape", "SQL_HTTP_STATUS_INVALID", False, "unknown"),
            ),
            (
                "redirect",
                None,
                SimpleNamespace(status_code=302, payload={"msg": unsafe}),
                TransportError,
                ("execute", "redirect_blocked", "SQL_REDIRECT_BLOCKED", False, "no"),
            ),
            (
                "http",
                None,
                SimpleNamespace(
                    status_code=503,
                    payload={"code": "SERVICE_BUSY", "msg": unsafe},
                ),
                TransportError,
                ("execute", "http_server_error", "SQL_HTTP_SERVER_ERROR", True, "unknown"),
            ),
            (
                "engine",
                None,
                SimpleNamespace(
                    status_code=200,
                    payload={
                        "data": {
                            "status": "REJECTED",
                            "code": "JOIN_REJECTED_FIXTURE",
                            "msg": unsafe,
                            "extra": {"error": [unsafe]},
                        },
                    },
                ),
                SqlResponseError,
                ("plan", "engine_rejected", "SQL_ENGINE_REJECTED", False, "yes"),
            ),
            (
                "shape",
                None,
                SimpleNamespace(
                    status_code=200,
                    payload={"status": "SUCCESS", "code": "OK", "msg": unsafe},
                ),
                SqlResponseError,
                ("shape", "tabular_shape_drift", "SQL_RESPONSE_SHAPE_INVALID", False, "yes"),
            ),
        )
        for name, side_effect, response, error_type, expected in cases:
            runtime = mock.Mock()
            runtime.request.side_effect = side_effect
            if side_effect is None:
                runtime.request.return_value = response
            with self.subTest(name=name), self.assertRaises(error_type) as caught:
                GravityClient(runtime).execute_sql("SELECT fixture")
            failure = classify_sql_failure(caught.exception, request_count=1)
            self.assertEqual(
                expected,
                (
                    failure.stage,
                    failure.upstream_category,
                    failure.code,
                    failure.retryable,
                    failure.reached_sql_engine,
                ),
            )
            rendered = str(
                diagnostic_fields(
                    failure,
                    elapsed_seconds=0.01,
                    request_count=1,
                    request_count_bound=1,
                )
            )
            self.assertNotIn(unsafe, rendered)
            if name == "engine":
                protocol = failure.protocol_status
                self.assertIsNotNone(protocol)
                self.assertEqual("JOIN_REJECTED_FIXTURE", protocol["code"]["value"])
                self.assertEqual("array", protocol["extra_error"]["value_type"])

    def test_local_sql_validation_has_zero_upstream_requests(self):
        runtime = mock.Mock()
        with self.assertRaises(SqlValidationError) as caught:
            GravityClient(runtime).execute_sql("")

        runtime.request.assert_not_called()
        failure = classify_sql_failure(caught.exception)
        diagnostic = diagnostic_fields(
            failure,
            elapsed_seconds=0,
            request_count=1,
            request_count_bound=1,
        )
        self.assertEqual("bind", diagnostic["stage"])
        self.assertFalse(diagnostic["retryable"])
        self.assertEqual(0, diagnostic["execution_evidence"]["request_count"])
        capped = diagnostic_fields(
            failure,
            elapsed_seconds=10**9,
            request_count=1,
            request_count_bound=1,
        )["execution_evidence"]
        self.assertEqual(capped["elapsed_ms_bound"], capped["elapsed_ms"])
        self.assertTrue(capped["elapsed_ms_capped"])

    def test_http_status_retryability_uses_status_class_not_upstream_text(self):
        for status, code, retryable in (
            (400, "SQL_HTTP_REQUEST_REJECTED", False),
            (408, "SQL_HTTP_TIMEOUT", True),
            (429, "SQL_HTTP_RATE_LIMITED", True),
            (500, "SQL_HTTP_SERVER_ERROR", True),
        ):
            runtime = mock.Mock()
            runtime.request.return_value = SimpleNamespace(
                status_code=status,
                payload={"code": "HTTP_FIXTURE", "msg": "PRIVATE_EVENT_SENTINEL"},
            )
            with self.subTest(status=status), self.assertRaises(TransportError) as caught:
                GravityClient(runtime).execute_sql("SELECT fixture")
            failure = classify_sql_failure(caught.exception, request_count=1)
            self.assertEqual((code, retryable), (failure.code, failure.retryable))
            rendered = str(failure.protocol_status)
            self.assertNotIn("PRIVATE_EVENT_SENTINEL", rendered)

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
        lock, rendezvous = threading.Lock(), Barrier(2, timeout=20)
        active = 0
        max_active = 0

        class ConcurrentRuntime(_FakeRuntime):
            def request(self, *args, **kwargs):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                try:
                    rendezvous.wait()
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

    def test_batch_dispatch_cannot_early_stop_already_submitted_work(self):
        class RejectingRuntime(_FakeRuntime):
            def request(self, *args, **kwargs):
                response = super().request(*args, **kwargs)
                sql = kwargs["json_body"]["sql"]
                if sql == "REJECT JOIN":
                    return SimpleNamespace(
                        status_code=200,
                        payload={"status": "REJECTED", "code": "JOIN_REJECTED_FIXTURE"},
                    )
                return response

        engine_runtime = RejectingRuntime()
        engine_results = GravityClient(engine_runtime).execute_batch(
            ["SELECT 1", "REJECT JOIN", "SELECT 2", "SELECT 3"], max_workers=2
        )
        self.assertEqual(4, len(engine_runtime.calls))
        self.assertEqual([True, False, True, True], [item["ok"] for item in engine_results])

        local_runtime = _FakeRuntime()
        local_results = GravityClient(local_runtime).execute_batch(
            ["SELECT 1", "", "SELECT 2", "SELECT 3"], max_workers=2
        )
        self.assertEqual(3, len(local_runtime.calls))
        self.assertEqual([True, False, True, True], [item["ok"] for item in local_results])

    def test_direct_calls_delegate_concurrency_to_the_runtime_owner(self):
        rendezvous = threading.Barrier(6, timeout=5)

        class ConcurrentRuntime(_FakeRuntime):
            def request(self, *args, **kwargs):
                rendezvous.wait()
                return super().request(*args, **kwargs)

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

    def test_build_sql_client_reuses_one_long_lived_instance(self):
        runtime = _FakeRuntime()
        with mock.patch.object(sql_client, "get_shared_runtime", return_value=runtime) as factory:
            first = sql_client.build_sql_client()
            second = sql_client.build_sql_client()

        self.assertIs(first, second)
        factory.assert_called_once_with(env_path=None)

    def test_fast_lane_structured_failures_preserve_all_five_sql_stages(self):
        class StagedFailure(Exception):
            code = "SQL_FAST_LANE_FIXTURE"
            safe_message = "safe staged fixture"
            sql_category = "contract"
            retryable = False
            reached_sql_engine = "unknown"
            next_action = "Use the stage to correct the request."

        for stage in ("bind", "compile", "plan", "execute", "shape"):
            error = StagedFailure()
            error.sql_stage = stage
            with self.subTest(stage=stage):
                self.assertEqual(stage, classify_sql_failure(error).stage)


if __name__ == "__main__":
    unittest.main()
