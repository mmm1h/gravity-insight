"""R14-A no-scheduling-change, value privacy and bounded observation gates."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gravity_sdk import (
    GovernorObservationService,
    GravitySDK,
    validate_adaptive_governor_snapshot,
    validate_governor_observation,
    validate_governor_observation_snapshot,
)
from gravity_sdk.errors import InputValidationError, TransportError
from gravity_sdk.external_context_provider import ExternalContextProvider
from gravity_sdk.governor_observation import (
    GovernorObservationContractError,
    GovernorObservationRecorder,
    governor_observation_mode,
    process_observation_snapshot,
)
from gravity_sdk.http_runtime import GravityHttpRuntime, SQL_PROFILE
from gravity_sdk.receipt import (
    PRODUCTION_HTTP_KIND,
    count_http_requests,
    perform_http_request,
    request_receipt_context,
)
from gravity_sdk.provider_rpc_transport import CallableProviderTransport
from gravity_sdk.workspace import Workspace, WorkspaceDefaults
from tests.test_external_context_contracts import provider_descriptor, response
from tests.test_gravity_http_runtime import FakeResponse, StaticCredentials


def _workspace(root: Path) -> Workspace:
    return Workspace(
        path=None,
        root=root,
        state_root=root,
        apps={},
        defaults=WorkspaceDefaults(app=None, timezone="UTC", time_window=None),
        datasources={},
        products={},
        recipes={},
    )


class _TimedSession:
    def __init__(self, now: list[float], responses: list[FakeResponse]) -> None:
        self.now = now
        self.responses = list(responses)
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append((method, url, copy.deepcopy(kwargs)))
        self.now[0] += 0.125
        return self.responses.pop(0)


def _runtime(
    session: object,
    scope: str,
    root: Path,
    *,
    now: list[float] | None = None,
    attempts: int = 2,
    sleeper=lambda _delay: None,
) -> GravityHttpRuntime:
    clock = (lambda: now[0]) if now is not None else (lambda: 0.0)
    return GravityHttpRuntime(
        session=session,
        credentials=StaticCredentials(),
        requests_per_second=100,
        attempts=attempts,
        sleeper=sleeper,
        rate_clock=clock,
        random_source=lambda: 0.0,
        interval_jitter_ratio=0.0,
        observation_scope_key=scope,
        receipt_root=root,
    )


def _sql(runtime: GravityHttpRuntime):
    return runtime.request(
        SQL_PROFILE,
        "POST",
        "/custom_sql/api/sql/execute",
        json_body={"sql": "SELECT 1", "tabId": "1"},
    )


def _observation_value() -> dict:
    return {
        "host_key": "sha256:" + "a" * 64,
        "operation_class": "sql.query",
        "profile": "sql",
        "method": "POST",
        "outcome": "response",
        "status_class": "success",
        "http_status": 200,
        "request_count": 1,
        "latency_ms": 10,
        "latency_capped": False,
        "rate_limit_delay_ms": 0,
        "rate_limit_delay_capped": False,
        "attempt": 1,
        "attempt_budget": 1,
        "retry_attempt": False,
        "budgets": {
            "business_limit": 24,
            "sql_limit": 2,
            "timeout_ms": 120_000,
        },
    }


class GovernorObservationEquivalenceTests(unittest.TestCase):
    def run_workload(self, enabled: bool, scope: str, root: Path) -> dict:
        now = [0.0]
        sleeps: list[float] = []

        def sleep(delay: float) -> None:
            sleeps.append(delay)
            now[0] += delay

        session = _TimedSession(
            now, [FakeResponse({}, 503), FakeResponse([{"one": 1}], 200)]
        )
        runtime = _runtime(session, scope, root, now=now, sleeper=sleep)
        with governor_observation_mode(enabled), count_http_requests() as counter:
            result = _sql(runtime)
            snapshot = runtime.governor_observations()
        return {
            "request_bytes": json.dumps(
                session.calls, ensure_ascii=True, sort_keys=True, default=str
            ).encode("utf-8"),
            "request_count": counter.count,
            "sleeps": sleeps,
            "response": (result.status_code, result.payload),
            "snapshot": snapshot,
        }

    def test_observe_and_disabled_modes_have_identical_request_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            disabled = self.run_workload(False, "disabled-trace", root / "disabled")
            observed = self.run_workload(True, "observed-trace", root / "observed")

        for field in ("request_bytes", "request_count", "sleeps", "response"):
            self.assertEqual(disabled[field], observed[field], field)
        self.assertEqual(2, observed["request_count"])
        self.assertEqual(("disabled", 0), (
            disabled["snapshot"]["mode"], disabled["snapshot"]["count"]
        ))
        self.assertEqual(("observe", 2), (
            observed["snapshot"]["mode"], observed["snapshot"]["count"]
        ))
        first, second = observed["snapshot"]["observations"]
        self.assertEqual(("server_error", 503, 1, False), (
            first["status_class"], first["http_status"], first["attempt"],
            first["retry_attempt"],
        ))
        self.assertEqual(("success", 200, 2, True), (
            second["status_class"], second["http_status"], second["attempt"],
            second["retry_attempt"],
        ))
        self.assertEqual((125, 24, 2, 2), (
            first["latency_ms"], first["budgets"]["business_limit"],
            first["budgets"]["sql_limit"], first["attempt_budget"],
        ))

    def test_observation_failure_cannot_change_request_outcome(self) -> None:
        response_value = FakeResponse({"ok": True})
        with mock.patch(
            "gravity_sdk.governor_observation.observe_http_attempt",
            side_effect=RuntimeError("observer failed"),
        ):
            result = perform_http_request(
                lambda: response_value, kind=PRODUCTION_HTTP_KIND
            )
        self.assertIs(response_value, result)

    def test_status_classes_and_rate_delay_are_exact_under_fake_time(self) -> None:
        expected = {
            200: "success",
            400: "client_error",
            429: "rate_limited",
            503: "server_error",
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for status, status_class in expected.items():
                with self.subTest(status=status):
                    runtime = _runtime(
                        _TimedSession([0.0], [FakeResponse({}, status)]),
                        f"status-{status}",
                        root / str(status),
                        attempts=1,
                    )
                    _sql(runtime)
                    observation = runtime.governor_observations()["observations"][0]
                    self.assertEqual((status, status_class), (
                        observation["http_status"], observation["status_class"]
                    ))

            now = [0.0]
            sleeps: list[float] = []

            def sleep(delay: float) -> None:
                sleeps.append(delay)
                now[0] += delay

            session = _TimedSession(now, [FakeResponse([]), FakeResponse([])])
            runtime = GravityHttpRuntime(
                session=session,
                credentials=StaticCredentials(),
                requests_per_second=2,
                attempts=1,
                sleeper=sleep,
                rate_clock=lambda: now[0],
                random_source=lambda: 0.0,
                interval_jitter_ratio=0.0,
                observation_scope_key="rate-delay",
                receipt_root=root / "rate",
            )
            _sql(runtime)
            _sql(runtime)
            observations = runtime.governor_observations()["observations"]
        self.assertEqual([0, 375], [
            item["rate_limit_delay_ms"] for item in observations
        ])
        self.assertEqual([0.375], sleeps)


class GovernorObservationPrivacyAndScopeTests(unittest.TestCase):
    def test_scope_partitions_are_isolated_and_not_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first_session = _TimedSession([0.0], [FakeResponse([])])
            second_session = _TimedSession([0.0], [FakeResponse([])])
            first = _runtime(first_session, "private-account-one", root / "one", attempts=1)
            second = _runtime(second_session, "private-account-two", root / "two", attempts=1)
            _sql(first)
            _sql(second)
            one = first.governor_observations()
            two = second.governor_observations()

        self.assertEqual(([1], [1]), (
            [item["sequence"] for item in one["observations"]],
            [item["sequence"] for item in two["observations"]],
        ))
        rendered = json.dumps([one, two], sort_keys=True)
        self.assertNotIn("private-account", rendered)
        self.assertNotIn("scope_key", rendered.casefold())

    def test_signed_url_request_and_response_values_never_enter_snapshot(self) -> None:
        before = process_observation_snapshot()["next_sequence"]
        secret_url = "https://cdn.example.test/file.bin?token=private-token"
        secret_payload = {"customer": "private-response"}
        with tempfile.TemporaryDirectory() as raw:
            perform_http_request(
                lambda _url, **_kwargs: FakeResponse(secret_payload),
                secret_url,
                kind=PRODUCTION_HTTP_KIND,
                headers={"Authorization": "private-credential"},
                http_receipt=request_receipt_context(
                    operation_id="material.asset.fetch",
                    method="GET",
                    path="/<response-bound-artifact-binary>",
                ),
                receipt_root=Path(raw),
            )
        snapshot = process_observation_snapshot(after_sequence=before)
        rendered = json.dumps(snapshot, sort_keys=True)
        self.assertEqual((1, "artifact"), (
            snapshot["count"], snapshot["observations"][0]["profile"]
        ))
        for secret in (
            "private-token", "private-response", "private-credential",
            "cdn.example.test", "file.bin", "response-bound",
        ):
            self.assertNotIn(secret, rendered)

    def test_transport_error_is_classified_without_exception_content(self) -> None:
        class BrokenSession:
            @staticmethod
            def request(*_args, **_kwargs):
                raise OSError("private socket path")

        with tempfile.TemporaryDirectory() as raw:
            runtime = _runtime(
                BrokenSession(), "transport-error", Path(raw), attempts=1
            )
            with self.assertRaises(TransportError) as raised:
                _sql(runtime)
            snapshot = runtime.governor_observations()
        self.assertNotIn("private socket path", str(raised.exception))
        observation = snapshot["observations"][0]
        self.assertEqual(("transport_error", "transport_error", None), (
            observation["outcome"], observation["status_class"],
            observation["http_status"],
        ))
        self.assertNotIn("private socket path", json.dumps(snapshot))

    def test_provider_rpc_does_not_enter_runtime_http_observations(self) -> None:
        before = process_observation_snapshot()["next_sequence"]
        provider = ExternalContextProvider(
            provider_descriptor(),
            CallableProviderTransport(
                "host", lambda request, _cancel: response(request["request_id"])
            ),
        )
        self.assertTrue(provider.read("provider://team/docs/fact")["ok"])
        after = process_observation_snapshot(after_sequence=before)
        self.assertEqual(0, after["count"])


class GovernorObservationContractTests(unittest.TestCase):
    def test_recorder_is_bounded_paginated_and_explicit_about_drops(self) -> None:
        recorder = GovernorObservationRecorder(max_observations=2, max_scopes=2)
        for _index in range(3):
            recorder.record("scope-a", _observation_value())
        snapshot = recorder.snapshot("scope-a", limit=1)
        self.assertEqual((1, True, True, 1, 2), (
            snapshot["count"], snapshot["has_more"], snapshot["truncated"],
            snapshot["dropped_observations"], snapshot["next_sequence"],
        ))
        second = recorder.snapshot(
            "scope-a", after_sequence=snapshot["next_sequence"]
        )
        self.assertEqual([3], [item["sequence"] for item in second["observations"]])

        recorder.record("scope-b", _observation_value())
        recorder.record("scope-c", _observation_value())
        self.assertEqual(0, recorder.snapshot("scope-a")["count"])

    def test_schema_tamper_and_query_bounds_fail_closed(self) -> None:
        observation = {
            **_observation_value(),
            "schema_version": "gravity.governor-observation.v1",
            "sequence": 1,
        }
        self.assertEqual(observation, validate_governor_observation(observation))
        changed = copy.deepcopy(observation)
        changed["host_key"] = "https://private.example"
        with self.assertRaises(GovernorObservationContractError):
            validate_governor_observation(changed)

        recorder = GovernorObservationRecorder()
        for field, kwargs, code in (
            ("after_sequence", {"after_sequence": -1}, "GOVERNOR_CURSOR_INVALID"),
            ("limit", {"limit": 0}, "GOVERNOR_LIMIT_INVALID"),
        ):
            with self.subTest(field=field), self.assertRaises(InputValidationError) as raised:
                recorder.snapshot("scope", **kwargs)
            self.assertEqual(code, raised.exception.code)

    def test_sdk_service_is_lazy_scope_bound_and_offline(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            session = _TimedSession([0.0], [FakeResponse([])])
            runtime = _runtime(session, "sdk-scope", root, attempts=1)
            sdk = GravitySDK(
                insight_factory=lambda: self.fail("Insight must remain lazy"),
                sql_factory=lambda: self.fail("SQL must remain lazy"),
                workspace=_workspace(root),
                _runtime_scope_bound=True,
                _runtime_factory=lambda: runtime,
            )
            self.assertIs(sdk.governor, sdk.governor)
            self.assertIsInstance(sdk.governor, GovernorObservationService)
            empty = sdk.governor.observations()
            empty_policy = sdk.governor.policy()
            _sql(runtime)
            populated = sdk.governor.observations(after_sequence=empty["next_sequence"])
            populated_policy = sdk.governor.policy()

            unbound = GravitySDK(
                insight_factory=lambda: self.fail("Insight must remain lazy"),
                workspace=_workspace(root / "unbound"),
            )
            with self.assertRaises(InputValidationError) as raised:
                unbound.governor.observations()
            with self.assertRaises(InputValidationError) as policy_raised:
                unbound.governor.policy()

        self.assertEqual((0, 1, 1), (
            empty["count"], populated["count"], len(session.calls)
        ))
        self.assertEqual("GOVERNOR_SCOPE_UNBOUND", raised.exception.code)
        self.assertEqual("GOVERNOR_SCOPE_UNBOUND", policy_raised.exception.code)
        self.assertEqual((0, 1, False), (
            empty_policy["lane_count"], populated_policy["lane_count"],
            populated_policy["network_called"],
        ))
        self.assertEqual(
            populated_policy,
            validate_adaptive_governor_snapshot(populated_policy),
        )
        self.assertEqual(
            populated, validate_governor_observation_snapshot(populated)
        )

    def test_root_exports_are_lazy_and_exact(self) -> None:
        import gravity_sdk

        self.assertIs(gravity_sdk.GovernorObservationService, GovernorObservationService)
        self.assertIs(
            gravity_sdk.validate_governor_observation,
            validate_governor_observation,
        )
        self.assertIs(
            gravity_sdk.validate_governor_observation_snapshot,
            validate_governor_observation_snapshot,
        )
        self.assertIs(
            gravity_sdk.validate_adaptive_governor_snapshot,
            validate_adaptive_governor_snapshot,
        )


if __name__ == "__main__":
    unittest.main()
