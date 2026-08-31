"""R14-B adaptive scheduling, evidence, privacy, and boundary gates."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from gravity_insight.adaptive_governor import (
    ADAPTIVE,
    STATIC,
    AdaptiveRequestGovernor,
    GovernorRequest,
    GovernorRequestError,
    current_journey_key,
    governor_journey,
    validate_adaptive_governor_snapshot,
)
from gravity_insight.adaptive_governor_contract import (
    PROCESS_SCOPE,
    private_host_key,
    private_journey_key,
    private_scope_key,
)
from gravity_insight.adaptive_governor_http import build_governor_request
from gravity_insight.blob_models import RequestsBlobTransport
from gravity_insight.external_context_provider import ExternalContextProvider
from gravity_insight.http_runtime import GravityHttpRuntime, HostRateLimiter, SQL_PROFILE
from gravity_insight.plan import PlanAdapter, PlanAdapters, execute_plan
from gravity_insight.provider_rpc_transport import CallableProviderTransport
from gravity_insight.receipt import (
    PRODUCTION_HTTP_KIND,
    bind_request_counter,
    capture_http_receipt_references,
    count_http_requests,
    perform_http_request,
    request_receipt_context,
)
from tests.test_external_context_contracts import provider_descriptor, response
from tests.test_gravity_http_runtime import StaticCredentials


class _Response:
    def __init__(self, status_code: int = 200, payload: object = None) -> None:
        self.status_code = status_code
        self._payload = {} if payload is None else payload
        self.headers: dict[str, str] = {}

    def json(self) -> object:
        return self._payload


class _FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _request(
    *,
    scope: str = "scope",
    profile: str = "runtime",
    operation: str = "runtime.read",
    journey: str = "direct",
    request_key: str | None = None,
    coalesce_safe: bool = False,
    timeout: float = 5.0,
    cancellation: threading.Event | None = None,
    target_host: str = "example.invalid",
    attempt: int = 1,
) -> GovernorRequest:
    return GovernorRequest(
        scope_key=private_scope_key(scope),
        host_key=private_host_key("example.invalid"),
        operation_class=operation,
        profile=profile,
        journey_key=private_journey_key(journey),
        request_key=request_key,
        coalesce_safe=coalesce_safe,
        timeout_seconds=timeout,
        cancellation=cancellation,
        target_host=target_host,
        attempt=attempt,
    )


def _wait_for(predicate, *, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("concurrency fixture did not reach its expected state")


class AdaptiveGovernorCapacityTests(unittest.TestCase):
    def test_static_mode_enforces_24_business_two_sql_and_one_login_spare(self) -> None:
        governor = AdaptiveRequestGovernor(mode=STATIC)
        release = threading.Event()
        business_ready = threading.Event()
        login_ready = threading.Event()
        lock = threading.Lock()
        active = business_active = max_active = 0

        def call(profile: str) -> _Response:
            def network() -> _Response:
                nonlocal active, business_active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                    if profile != "login":
                        business_active += 1
                        if business_active == 24:
                            business_ready.set()
                    else:
                        login_ready.set()
                try:
                    self.assertTrue(release.wait(5))
                    return _Response()
                finally:
                    with lock:
                        active -= 1
                        if profile != "login":
                            business_active -= 1

            return governor.execute(
                _request(profile=profile, operation=f"{profile}.read"), network
            )

        with ThreadPoolExecutor(max_workers=26) as pool:
            business = [pool.submit(call, "insight") for _ in range(24)]
            self.assertTrue(business_ready.wait(5))
            extra_business = pool.submit(call, "insight")
            login = pool.submit(call, "login")
            self.assertTrue(login_ready.wait(5))
            with lock:
                self.assertEqual((25, 24, 25), (active, business_active, max_active))
            release.set()
            self.assertEqual(200, login.result(timeout=5).status_code)
            self.assertEqual(200, extra_business.result(timeout=5).status_code)
            self.assertTrue(all(item.result(timeout=5).status_code == 200 for item in business))

        release.clear()
        sql_ready = threading.Event()
        sql_active = sql_peak = 0

        def sql_call() -> _Response:
            def network() -> _Response:
                nonlocal sql_active, sql_peak
                with lock:
                    sql_active += 1
                    sql_peak = max(sql_peak, sql_active)
                    if sql_active == 2:
                        sql_ready.set()
                try:
                    self.assertTrue(release.wait(5))
                    return _Response()
                finally:
                    with lock:
                        sql_active -= 1

            return governor.execute(_request(profile="sql", operation="sql.query"), network)

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(sql_call) for _ in range(4)]
            self.assertTrue(sql_ready.wait(5))
            _wait_for(lambda: governor.snapshot("scope")["scope"]["queued"] == 2)
            self.assertEqual(2, sql_peak)
            release.set()
            self.assertTrue(all(item.result(timeout=5).status_code == 200 for item in futures))

    def test_fake_clock_aimd_slow_success_and_capacity_failure_are_exact(self) -> None:
        clock = _FakeClock()
        governor = AdaptiveRequestGovernor(mode=ADAPTIVE, clock=clock)
        request = _request(profile="insight", operation="insight.read")

        for _ in range(6):
            governor.execute(request, lambda: (clock.advance(0.1), _Response())[1])
        self.assertEqual(7, governor.snapshot("scope")["lanes"][0]["concurrency_limit"])

        governor.execute(request, lambda: (clock.advance(2.1), _Response())[1])
        self.assertEqual(6, governor.snapshot("scope")["lanes"][0]["concurrency_limit"])
        governor.execute(request, lambda: _Response(429))
        lane = governor.snapshot("scope")["lanes"][0]
        self.assertEqual((3, 1, 2), (
            lane["concurrency_limit"],
            lane["counters"]["capacity_failure"],
            lane["counters"]["aimd_decrease"],
        ))

    def test_circuit_opens_then_allows_one_half_open_recovery_probe(self) -> None:
        clock = _FakeClock()
        governor = AdaptiveRequestGovernor(mode=ADAPTIVE, clock=clock)
        request = _request()
        for _ in range(3):
            self.assertEqual(503, governor.execute(request, lambda: _Response(503)).status_code)

        lane = governor.snapshot("scope")["lanes"][0]
        self.assertEqual(("open", 30_000, 1), (
            lane["circuit_state"], lane["cooldown_remaining_ms"],
            lane["counters"]["circuit_open"],
        ))
        called = False

        def forbidden() -> _Response:
            nonlocal called
            called = True
            return _Response()

        with self.assertRaises(GovernorRequestError) as raised:
            governor.execute(request, forbidden)
        self.assertEqual("GOVERNOR_CIRCUIT_OPEN", raised.exception.code)
        self.assertFalse(called)

        diagnostics = raised.exception.diagnostics
        self.assertEqual("upstream_capacity", diagnostics["failure_class"])
        self.assertEqual("example.invalid", diagnostics["lane"]["host"])
        self.assertEqual(30_000, diagnostics["cooldown_remaining_ms"])
        self.assertEqual(
            ["server_error", "server_error", "server_error"],
            [item["status_class"] for item in diagnostics["failures"]],
        )
        self.assertEqual(
            [503, 503, 503],
            [item["http_status"] for item in diagnostics["failures"]],
        )
        self.assertIn("retry the same host once", raised.exception.next_action)

        clock.advance(30.0)
        self.assertEqual(200, governor.execute(request, lambda: _Response()).status_code)
        lane = governor.snapshot("scope")["lanes"][0]
        self.assertEqual(("closed", 0, 1), (
            lane["circuit_state"], lane["consecutive_failures"],
            lane["counters"]["half_open"],
        ))

        static = AdaptiveRequestGovernor(mode=STATIC)
        for _ in range(3):
            static.execute(request, lambda: _Response(503))
        self.assertEqual(200, static.execute(request, lambda: _Response()).status_code)

    def test_circuit_diagnostics_preserve_each_capacity_failure_kind(self) -> None:
        def transport_failure() -> _Response:
            raise TimeoutError("transport detail must not be rendered")

        cases = (
            ("transport_error", transport_failure, None, "TimeoutError"),
            ("rate_limited", lambda: _Response(429), 429, None),
            ("server_error", lambda: _Response(503), 503, None),
        )
        for status_class, fake_transport, http_status, exception_type in cases:
            with self.subTest(status_class=status_class):
                governor = AdaptiveRequestGovernor(mode=ADAPTIVE, clock=_FakeClock())
                for attempt in range(1, 4):
                    request = _request(attempt=attempt)
                    if status_class == "transport_error":
                        with self.assertRaises(TimeoutError):
                            governor.execute(request, fake_transport)
                    else:
                        governor.execute(request, fake_transport)

                with self.assertRaises(GovernorRequestError) as raised:
                    governor.execute(_request(attempt=4), lambda: _Response())

                error = raised.exception
                failures = error.diagnostics["failures"]
                self.assertEqual(
                    [1, 2, 3], [item["failure_index"] for item in failures]
                )
                self.assertEqual(
                    [1, 2, 3], [item["attempt"] for item in failures]
                )
                self.assertEqual(
                    [status_class] * 3,
                    [item["status_class"] for item in failures],
                )
                self.assertEqual(
                    [http_status] * 3,
                    [item["http_status"] for item in failures],
                )
                self.assertEqual(
                    [exception_type] * 3,
                    [item["exception_type"] for item in failures],
                )
                self.assertEqual(30_000, error.diagnostics["cooldown_remaining_ms"])

    def test_circuit_error_exposes_safe_host_but_no_credentials_or_query(self) -> None:
        sentinels = (
            "CREDENTIAL_SENTINEL_71",
            "PASSWORD_SENTINEL_72",
            "QUERY_SENTINEL_73",
            "AUTHORIZATION_SENTINEL_74",
            "TRANSPORT_SENTINEL_75",
        )
        receipt = request_receipt_context(
            operation_id="census_fetch",
            method="GET",
            path="/assets/private.js",
            effect="read",
        )
        descriptor = build_governor_request(
            (
                "https://CREDENTIAL_SENTINEL_71:PASSWORD_SENTINEL_72@"
                "static.example/assets/private.js?signature=QUERY_SENTINEL_73",
            ),
            {"headers": {"Authorization": "AUTHORIZATION_SENTINEL_74"}},
            receipt_context=receipt,
            governor_context={"profile": "census"},
        )
        governor = AdaptiveRequestGovernor(mode=ADAPTIVE, clock=_FakeClock())

        def failed_transport() -> _Response:
            raise TimeoutError("TRANSPORT_SENTINEL_75")

        for _ in range(3):
            with self.assertRaises(TimeoutError):
                governor.execute(descriptor, failed_transport)
        with self.assertRaises(GovernorRequestError) as raised:
            governor.execute(descriptor, lambda: _Response())

        rendered = json.dumps(
            {
                "error": str(raised.exception),
                "diagnostics": raised.exception.diagnostics,
                "next_action": raised.exception.next_action,
            },
            sort_keys=True,
        )
        self.assertIn("static.example", rendered)
        for sentinel in sentinels:
            self.assertNotIn(sentinel, rendered)


class AdaptiveGovernorWaitingTests(unittest.TestCase):
    def test_queue_full_timeout_and_cancellation_leave_no_leaked_lease(self) -> None:
        governor = AdaptiveRequestGovernor(
            mode=STATIC,
            total_capacity=2,
            business_capacity=1,
            sql_capacity=1,
            max_queue=1,
        )
        release = threading.Event()
        entered = threading.Event()
        cancellation = threading.Event()

        def held() -> _Response:
            entered.set()
            self.assertTrue(release.wait(5))
            return _Response()

        with ThreadPoolExecutor(max_workers=2) as pool:
            leader = pool.submit(governor.execute, _request(), held)
            self.assertTrue(entered.wait(5))
            cancelled = pool.submit(
                governor.execute,
                _request(cancellation=cancellation),
                lambda: _Response(),
            )
            _wait_for(lambda: governor.snapshot("scope")["scope"]["queued"] == 1)
            with self.assertRaises(GovernorRequestError) as full:
                governor.execute(_request(), lambda: _Response())
            self.assertEqual("GOVERNOR_BACKPRESSURE", full.exception.code)
            cancellation.set()
            with self.assertRaises(GovernorRequestError) as stopped:
                cancelled.result(timeout=5)
            self.assertEqual("GOVERNOR_CANCELLED", stopped.exception.code)

            with self.assertRaises(GovernorRequestError) as timed_out:
                governor.execute(_request(timeout=0.05), lambda: _Response())
            self.assertEqual("GOVERNOR_BACKPRESSURE", timed_out.exception.code)
            self.assertEqual((1, 0), (
                governor.snapshot("scope")["scope"]["active"],
                governor.snapshot("scope")["scope"]["queued"],
            ))
            release.set()
            self.assertEqual(200, leader.result(timeout=5).status_code)

        self.assertEqual(200, governor.execute(_request(), lambda: _Response()).status_code)
        snapshot = governor.snapshot("scope")
        self.assertEqual((0, 0, 1, 3), (
            snapshot["scope"]["active"], snapshot["scope"]["queued"],
            snapshot["scope"]["cancelled"], snapshot["scope"]["rejected"],
        ))

    def test_waiting_plan_journeys_alternate_when_capacity_is_saturated(self) -> None:
        governor = AdaptiveRequestGovernor(
            mode=STATIC,
            total_capacity=2,
            business_capacity=1,
            sql_capacity=1,
        )
        release = threading.Event()
        entered = threading.Event()
        order: list[str] = []
        lock = threading.Lock()

        def leader() -> _Response:
            entered.set()
            self.assertTrue(release.wait(5))
            return _Response()

        def queued(label: str, journey: str) -> _Response:
            with governor_journey(journey):
                request = _request(journey="unused")
                request = GovernorRequest(
                    **{**request.__dict__, "journey_key": current_journey_key()}
                )

                def network() -> _Response:
                    with lock:
                        order.append(label)
                    return _Response()

                return governor.execute(request, network)

        with ThreadPoolExecutor(max_workers=5) as pool:
            first = pool.submit(governor.execute, _request(journey="A"), leader)
            self.assertTrue(entered.wait(5))
            futures = []
            for label, journey in (("A1", "A"), ("A2", "A"), ("B1", "B"), ("B2", "B")):
                futures.append(pool.submit(queued, label, journey))
                expected = len(futures)
                _wait_for(
                    lambda expected=expected: (
                        governor.snapshot("scope")["scope"]["queued"] == expected
                    )
                )
            release.set()
            first.result(timeout=5)
            self.assertTrue(all(item.result(timeout=5).status_code == 200 for item in futures))
        self.assertEqual(["B1", "A1", "B2", "A2"], order)


class AdaptiveGovernorSingleFlightTests(unittest.TestCase):
    def test_runtime_identical_reads_share_one_attempt_counter_and_receipt(self) -> None:
        governor = AdaptiveRequestGovernor(mode=ADAPTIVE)
        entered = threading.Event()
        release = threading.Event()

        class Session:
            def __init__(self) -> None:
                self.calls = 0

            def request(self, *_args, **_kwargs) -> _Response:
                self.calls += 1
                entered.set()
                if not release.wait(5):
                    raise AssertionError("single-flight leader was not released")
                return _Response(payload=[{"value": 1}])

        session = Session()
        with tempfile.TemporaryDirectory() as raw:
            runtime = GravityHttpRuntime(
                session=session,
                credentials=StaticCredentials(),
                governor=governor,
                limiter=HostRateLimiter(
                    clock=lambda: 0.0,
                    random_source=lambda: 0.0,
                    interval_jitter_ratio=0.0,
                ),
                requests_per_second=100,
                sleeper=lambda _delay: None,
                rate_clock=lambda: 0.0,
                random_source=lambda: 0.0,
                interval_jitter_ratio=0.0,
                receipt_root=Path(raw),
                observation_scope_key="single-flight-scope",
            )

            def read() -> tuple[object, tuple[dict[str, str], ...]]:
                with capture_http_receipt_references() as references:
                    value = runtime.request(
                        SQL_PROFILE,
                        "POST",
                        "/custom_sql/api/sql/execute",
                        json_body={"sql": "SELECT 1", "tabId": "1"},
                        attempts=1,
                    )
                return value, tuple(references)

            with count_http_requests() as counter:
                bound = bind_request_counter()
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(bound, read)
                    self.assertTrue(entered.wait(5))
                    second = pool.submit(bound, read)
                    _wait_for(
                        lambda: governor.snapshot("single-flight-scope")["scope"]["queued"] == 1
                    )
                    release.set()
                    results = (first.result(timeout=5), second.result(timeout=5))

        self.assertEqual((1, 1), (session.calls, counter.count))
        self.assertEqual(1, sum(len(item[1]) for item in results))
        self.assertTrue(all(item[0].status_code == 200 for item in results))
        snapshot = governor.snapshot("single-flight-scope")
        self.assertEqual((1, 1), (
            snapshot["scope"]["coalesced"],
            snapshot["lanes"][0]["counters"]["coalesced"],
        ))

    def test_distinct_values_mutations_streams_and_static_mode_do_not_coalesce(self) -> None:
        cases = (
            (
                ADAPTIVE,
                request_receipt_context(
                    operation_id="insight.read", method="POST", path="/read",
                    effect="read", coalesce_safe=True,
                ),
                ({"json": {"value": "one"}}, {"json": {"value": "two"}}),
            ),
            (
                ADAPTIVE,
                request_receipt_context(
                    operation_id="object.update", method="POST", path="/mutate",
                    effect="mutation",
                ),
                ({"json": {"value": "same"}}, {"json": {"value": "same"}}),
            ),
            (
                ADAPTIVE,
                request_receipt_context(
                    operation_id="artifact.read", method="GET", path="/stream",
                    effect="read", coalesce_safe=True,
                ),
                ({"stream": True}, {"stream": True}),
            ),
            (
                STATIC,
                request_receipt_context(
                    operation_id="insight.read", method="POST", path="/read",
                    effect="read", coalesce_safe=True,
                ),
                ({"json": {"value": "same"}}, {"json": {"value": "same"}}),
            ),
        )
        for mode, receipt, options in cases:
            with self.subTest(mode=mode, operation=receipt["operation_id"]):
                self.assertEqual(2, self._parallel_attempts(mode, receipt, options))

    def _parallel_attempts(
        self,
        mode: str,
        receipt: dict[str, object],
        options: tuple[dict[str, object], dict[str, object]],
    ) -> int:
        governor = AdaptiveRequestGovernor(
            mode=mode, total_capacity=3, business_capacity=2, sql_capacity=1
        )
        release = threading.Event()
        both_entered = threading.Event()
        lock = threading.Lock()
        calls = 0

        def network(*_args, **_kwargs) -> _Response:
            nonlocal calls
            with lock:
                calls += 1
                if calls == 2:
                    both_entered.set()
            release.wait(30)
            return _Response()

        def call(kwargs: dict[str, object]) -> _Response:
            return perform_http_request(
                network,
                "POST",
                "https://example.invalid/read",
                kind=PRODUCTION_HTTP_KIND,
                **kwargs,
                http_receipt=receipt,
                governor_context={
                    "scope_key": "pair",
                    "profile": "insight",
                    "timeout_seconds": 2,
                },
                adaptive_governor=governor,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(call, item) for item in options]
            try:
                self.assertTrue(both_entered.wait(20))
            finally:
                release.set()
            self.assertTrue(all(item.result(timeout=3).status_code == 200 for item in futures))
        return calls

    def test_failed_leader_releases_follower_to_its_normal_attempt_path(self) -> None:
        governor = AdaptiveRequestGovernor(mode=ADAPTIVE)
        first_entered = threading.Event()
        release = threading.Event()
        lock = threading.Lock()
        calls = 0

        def network(*_args, **_kwargs) -> _Response:
            nonlocal calls
            with lock:
                calls += 1
                call = calls
            if call == 1:
                first_entered.set()
                release.wait(5)
                raise OSError("private transport failure")
            return _Response()

        receipt = request_receipt_context(
            operation_id="insight.read", method="POST", path="/read",
            effect="read", coalesce_safe=True,
        )

        def read() -> _Response:
            return perform_http_request(
                network,
                "POST",
                "https://example.invalid/read",
                kind=PRODUCTION_HTTP_KIND,
                json={"value": 1},
                http_receipt=receipt,
                governor_context={"scope_key": "failed", "profile": "insight"},
                adaptive_governor=governor,
            )

        with count_http_requests() as counter:
            bound = bind_request_counter()
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(bound, read)
                self.assertTrue(first_entered.wait(5))
                second = pool.submit(bound, read)
                _wait_for(lambda: governor.snapshot("failed")["scope"]["queued"] == 1)
                release.set()
                with self.assertRaises(OSError):
                    first.result(timeout=5)
                self.assertEqual(200, second.result(timeout=5).status_code)
        self.assertEqual((2, 2), (calls, counter.count))


class AdaptiveGovernorPrivacyAndBoundaryTests(unittest.TestCase):
    def test_snapshot_is_scope_private_bounded_and_contains_no_request_values(self) -> None:
        governor = AdaptiveRequestGovernor(mode=ADAPTIVE)
        receipt = request_receipt_context(
            operation_id="sensitive.read",
            method="POST",
            path="/private/{id}",
            body={"account": "secret-account"},
            effect="read",
            coalesce_safe=True,
        )
        descriptor = build_governor_request(
            ("POST", "https://secret.example/private/42?token=secret-token"),
            {
                "headers": {"Authorization": "secret-credential"},
                "json": {"account": "secret-account"},
            },
            receipt_context=receipt,
            governor_context={"scope_key": "secret-scope", "profile": "insight"},
        )
        governor.execute(descriptor, lambda: _Response())
        for index in range(257):
            governor.execute(
                _request(scope="secret-scope", operation=f"operation.{index}"),
                lambda: _Response(),
            )

        snapshot = governor.snapshot("secret-scope")
        rendered = json.dumps(snapshot, sort_keys=True)
        self.assertEqual(snapshot, validate_adaptive_governor_snapshot(snapshot))
        self.assertEqual((256, True, 0), (
            snapshot["lane_count"], snapshot["truncated"],
            governor.snapshot("other-scope")["lane_count"],
        ))
        for private in (
            "secret-account", "secret-token", "secret-credential", "secret-scope",
            "/private/42", "request_key", "journey_key", "scope_key",
            descriptor.request_key,
        ):
            with self.subTest(private=private):
                self.assertNotIn(str(private), rendered)

    def test_artifact_streams_are_governed_and_provider_rpc_is_excluded(self) -> None:
        governor = AdaptiveRequestGovernor(
            mode=STATIC,
            total_capacity=2,
            business_capacity=1,
            sql_capacity=1,
        )
        release = threading.Event()
        entered = threading.Event()
        lock = threading.Lock()
        active = peak = calls = 0

        class Session:
            def get(self, *_args, **_kwargs) -> _Response:
                nonlocal active, peak, calls
                with lock:
                    active += 1
                    calls += 1
                    peak = max(peak, active)
                    entered.set()
                try:
                    release.wait(5)
                    return _Response()
                finally:
                    with lock:
                        active -= 1

        with tempfile.TemporaryDirectory() as raw, mock.patch(
            "gravity_insight.adaptive_governor.get_process_governor",
            return_value=governor,
        ), mock.patch("gravity_insight.blob_models.STATE_ROOT", Path(raw)):
            transport = RequestsBlobTransport(Session())
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(
                    transport.open_download,
                    "https://artifact.invalid/signed?token=one",
                    headers={},
                    timeout=5,
                )
                self.assertTrue(entered.wait(5))
                second = pool.submit(
                    transport.open_download,
                    "https://artifact.invalid/signed?token=one",
                    headers={},
                    timeout=5,
                )
                _wait_for(
                    lambda: governor.snapshot(PROCESS_SCOPE)["scope"]["queued"] == 1
                )
                release.set()
                self.assertEqual(200, first.result(timeout=5).status_code)
                self.assertEqual(200, second.result(timeout=5).status_code)

            before = governor.snapshot(PROCESS_SCOPE)
            provider = ExternalContextProvider(
                provider_descriptor(),
                CallableProviderTransport(
                    "host", lambda request, _cancel: response(request["request_id"])
                ),
            )
            self.assertTrue(provider.read("provider://team/docs/fact")["ok"])
            after = governor.snapshot(PROCESS_SCOPE)

        self.assertEqual((2, 1), (calls, peak))
        self.assertEqual(before, after)
        self.assertEqual("artifact", before["lanes"][0]["profile"])

    def test_plan_adapter_call_binds_the_execution_id_as_journey_context(self) -> None:
        def execute(_request_value, _context):
            return {"status": "success", "journey": current_journey_key()}

        adapter = PlanAdapter(execute=execute, validate=lambda *_args: None)
        plan = {
            "schema_version": "gravity.plan.v1",
            "budget": {"max_workers": 2, "max_total_items": 2},
            "nodes": [
                {
                    "id": "first", "kind": "run", "request": {},
                    "limits": {"max_pages": 1, "max_items": 1},
                },
                {
                    "id": "second", "kind": "run", "request": {},
                    "limits": {"max_pages": 1, "max_items": 1},
                },
            ],
        }
        result = execute_plan(
            plan,
            adapters=PlanAdapters(run=adapter),
            workspace=object(),
        )
        journeys = {item["result"]["journey"] for item in result["results"]}
        self.assertEqual(
            {private_journey_key("first"), private_journey_key("second")}, journeys
        )


if __name__ == "__main__":
    unittest.main()
