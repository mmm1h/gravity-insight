from __future__ import annotations

import json
import unittest
import threading
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

from gravity_insight import GravityInsightClient
from gravity_insight.analysis_query_batch import (
    BATCH_SCHEMA_VERSION,
    MULTI_APP_BATCH_SCHEMA_VERSION,
    analysis_query_batch_schema,
    execute_analysis_query_batch,
    validate_analysis_query_batch,
)
from gravity_insight.analysis_query_batch_cli import run_analysis_query_batch_command
from gravity_insight.analysis_query_multi_app import analysis_query_multi_app_schema
from gravity_insight.analysis_spec_cli import run_analysis_query_command
from gravity_insight.errors import InputValidationError
from gravity_insight.cli import build_parser
from gravity_insight.onboarding import command_requires_credentials
from gravity_insight.errors import PermissionUnavailableError
from gravity_insight.sdk import GravitySDK
from gravity_insight.transport import TransportResponse
from gravity_insight.workspace import load_workspace


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "src" / "gravity_insight" / "manifests"
RENDEZVOUS_TIMEOUT_SECONDS = 20


def _repository_manifest(*operation_ids: str) -> dict[str, Any]:
    operations: dict[str, dict[str, Any]] = {}
    for path in sorted(MANIFEST_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        operations.update(
            (item["operation_id"], item) for item in document.get("operations", [])
        )
    selected: dict[str, dict[str, Any]] = {}
    pending = list(operation_ids)
    while pending:
        operation_id = pending.pop()
        operation = operations[operation_id]
        if operation_id in selected:
            continue
        selected[operation_id] = operation
        for parent in operation.get("required_parent", ()):
            if isinstance(parent, str):
                pending.append(parent)
            elif isinstance(parent, Mapping) and parent.get("operation_id"):
                pending.append(str(parent["operation_id"]))
    return {"manifest_version": 1, "operations": list(selected.values())}


def _event_result() -> dict[str, Any]:
    return {
        "code": 0,
        "data": {
            "list": [[{
                "start_date": "2026-07-01",
                "end_date": "2026-07-01",
                "target": {"registered": 1},
                "list": [{"registered": 1}],
                "event_index": 0,
            }]],
            "target_list": ["registered"],
            "default_limit": 50,
            "date_list": [{"start_date": "2026-07-01", "end_date": "2026-07-01"}],
        },
    }


def _issue_24_spec(index: int) -> dict[str, Any]:
    selected = (date(2026, 7, 1) + timedelta(days=index)).isoformat()
    return {
        "start": selected,
        "end": selected,
        "time_grain": "day",
        "global_filters": [
            {
                "type": "user",
                "field": "registered_at",
                "operator": "RANGE_IN",
                "value": [f"{selected} 00:00:00", f"{selected} 23:59:59"],
            },
            {
                "type": "user",
                "field": "account_kind",
                "operator": "EQUALS",
                "value": ["fixture"],
            },
        ],
        "global_logic": "AND",
        "steps": [
            {
                "event": "registered",
                "metric": {"field": "PresetUserCount", "aggregation": "PresetUserCount"},
            },
            {
                "event": "level_changed",
                "metric": {"field": "PresetUserCount", "aggregation": "PresetUserCount"},
            },
        ],
        "group_by": [{"field": "level", "source": "event", "bucket": "default"}],
    }


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw(item) for item in value]
    return value


class RequestCaptureTransport:
    is_test_transport = True

    def __init__(self, response: Any, *, rendezvous_parties: int = 1) -> None:
        self.response = dict(response) if isinstance(response, Mapping) else response
        self.calls: list[tuple[str, str, Mapping[str, Any]]] = []
        self.active = 0
        self.peak = 0
        self.lock = threading.Lock()
        self.rendezvous = (
            threading.Barrier(
                rendezvous_parties, timeout=RENDEZVOUS_TIMEOUT_SECONDS
            )
            if rendezvous_parties > 1
            else None
        )
        self.rendezvous_started = 0
        self.rendezvous_failures: list[str] = []

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        with self.lock:
            self.calls.append((method, path, kwargs))
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.rendezvous_started += 1
            synchronize = (
                self.rendezvous is not None
                and self.rendezvous_started <= self.rendezvous.parties
            )
        try:
            if synchronize:
                self._wait_for_first_wave(path)
            response = (
                self.response(method, path, kwargs)
                if callable(self.response)
                else deepcopy(self.response)
            )
            return TransportResponse(
                200, response, "2026-08-20T00:00:00Z"
            )
        finally:
            with self.lock:
                self.active -= 1

    def _wait_for_first_wave(self, path: str) -> None:
        assert self.rendezvous is not None
        try:
            self.rendezvous.wait()
        except threading.BrokenBarrierError as exc:
            with self.lock:
                message = (
                    "request concurrency rendezvous timed out or broke after "
                    f"{RENDEZVOUS_TIMEOUT_SECONDS}s: path={path!r}, "
                    f"parties={self.rendezvous.parties}, active={self.active}, "
                    f"peak={self.peak}"
                )
                self.rendezvous_failures.append(message)
            raise AssertionError(message) from exc

    @property
    def bodies(self) -> list[dict[str, Any]]:
        return [_thaw(call[2]["body"]) for call in self.calls]


class AdaptiveRejectionTransport(RequestCaptureTransport):
    def __init__(
        self, rejection_rounds: int, *, first_round_successes: frozenset[str] = frozenset()
    ) -> None:
        super().__init__({})
        self.rejection_rounds = rejection_rounds
        self.first_round_successes = first_round_successes
        self.query_calls: dict[str, int] = {}
        self.phase_calls: dict[int, int] = {}
        self.phase_active: dict[int, int] = {}
        self.phase_peaks: dict[int, int] = {}
        self.phase_started: dict[int, int] = {}
        self.phase_barriers = {
            1: threading.Barrier(4, timeout=RENDEZVOUS_TIMEOUT_SECONDS),
            2: threading.Barrier(2, timeout=RENDEZVOUS_TIMEOUT_SECONDS),
        }

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        body = _thaw(kwargs["body"])
        query = body["date_list"][0]["start_date"]
        with self.lock:
            phase = self.query_calls.get(query, 0) + 1
            self.query_calls[query] = phase
            self.phase_calls[phase] = self.phase_calls.get(phase, 0) + 1
            self.phase_started[phase] = self.phase_started.get(phase, 0) + 1
            self.phase_active[phase] = self.phase_active.get(phase, 0) + 1
            self.phase_peaks[phase] = max(
                self.phase_peaks.get(phase, 0), self.phase_active[phase]
            )
            self.calls.append((method, path, kwargs))
            synchronize = (
                phase in self.phase_barriers
                and self.phase_started[phase] <= self.phase_barriers[phase].parties
            )
        try:
            if synchronize:
                self.phase_barriers[phase].wait()
            first_success = phase == 1 and query in self.first_round_successes
            payload = _event_result() if first_success or phase > self.rejection_rounds else {
                "code": 0, "extra": {"error": "fixture capacity rejection"}
            }
            return TransportResponse(200, payload, "2026-08-20T00:00:00Z")
        finally:
            with self.lock:
                self.phase_active[phase] -= 1


def _transport_sdk(
    response: Any,
    *,
    operation_id: str = "analysis.event.query",
    disable_field_validation: bool = True,
    rendezvous_parties: int = 1,
) -> tuple[GravitySDK, RequestCaptureTransport]:
    transport = RequestCaptureTransport(
        response, rendezvous_parties=rendezvous_parties
    )
    insight = GravityInsightClient._from_manifest_for_tests(
        _repository_manifest(operation_id), transport=transport
    )
    if disable_field_validation:
        insight._executor._field_validator = lambda *_args, **_kwargs: None
    return GravitySDK(insight=insight, workspace="examples/workspace"), transport


def _adaptive_transport_sdk(
    rejection_rounds: int,
    *,
    first_round_successes: frozenset[str] = frozenset(),
) -> tuple[GravitySDK, AdaptiveRejectionTransport]:
    transport = AdaptiveRejectionTransport(
        rejection_rounds, first_round_successes=first_round_successes
    )
    insight = GravityInsightClient._from_manifest_for_tests(
        _repository_manifest("analysis.event.query"), transport=transport
    )
    insight._executor._field_validator = lambda *_args, **_kwargs: None
    return GravitySDK(insight=insight, workspace="examples/workspace"), transport


def _issue_24_batch() -> dict[str, Any]:
    return {
        "schema_version": BATCH_SCHEMA_VERSION,
        "queries": [
            {
                "id": f"day_{index + 1:02d}",
                "kind": "event",
                "app": "demo",
                "spec": _issue_24_spec(index),
                "limits": {"max_items": 200},
            }
            for index in range(31)
        ],
    }


def _issue_24_property_batch() -> dict[str, Any]:
    group_by = [{"field": "level_c", "source": "user", "bucket": "dispersed"}]

    def spec(field: str, aggregation: str) -> dict[str, Any]:
        return {
            "property": {
                "field": field,
                "aggregation": aggregation,
                "data_type": "INT",
                "source": "user_property",
            },
            "group_by": deepcopy(group_by),
        }

    return {
        "schema_version": MULTI_APP_BATCH_SCHEMA_VERSION,
        "queries": [
            {
                "id": "property_a",
                "kind": "property",
                "apps": ["demo"],
                "spec": spec("score_a", "ValueAvg"),
                "limits": {"max_items": 200},
            },
            {
                "id": "property_b",
                "kind": "property",
                "apps": ["demo"],
                "spec": spec("score_b", "ValueAvg"),
                "limits": {"max_items": 200},
            },
            {
                "id": "property_users",
                "kind": "property",
                "apps": ["demo"],
                "spec": spec("PresetUserCount", "PresetUserCount"),
                "limits": {"max_items": 200},
            },
        ],
    }


def _property_batch_response(
    _method: str, path: str, _kwargs: Mapping[str, Any]
) -> dict[str, Any]:
    if path.endswith("user_property_list/"):
        rows = [
            {"name": name, "cname": name, "data_type": "INT", "visible": True}
            for name in ("score_a", "score_b", "level_c")
        ]
        return {
            "code": 0,
            "data": {
                "list": rows,
                "page_info": {
                    "page": 1,
                    "page_size": 2_000,
                    "total_page": 1,
                    "total_number": len(rows),
                },
            },
        }
    return {
        "code": 0,
        "data": {
            "target": "fixture",
            "list": [{"level_c": index, "value": index} for index in range(201)],
        },
    }


def _query(query_id: str, kind: str = "event", *, secret: str = "open") -> dict[str, Any]:
    metric = {"field": "PresetAllCount", "aggregation": "PresetAllCount"}
    dated = {"start": "2026-08-01", "end": "2026-08-02"}
    specs: dict[str, dict[str, Any]] = {
        "event": {**dated, "steps": [{"event": secret, "metric": metric}]},
        "funnel": {
            **dated,
            "steps": [
                {"event": secret, "metric": metric},
                {"event": "pay", "metric": metric},
            ],
            "window": {"unit": "day", "value": 1},
        },
        "retention": {
            **dated,
            "steps": [
                {"event": secret, "metric": metric},
                {"event": "return", "metric": metric},
            ],
            "offset": 7,
            "period_calc_method": "SUM",
            "custom_before_method": "SUM",
            "total_calc_type": "DAY",
            "week_first_day": 1,
        },
        "property": {
            "property": {
                "field": "PresetUserCount",
                "aggregation": "PresetUserCount",
                "data_type": "INT",
            }
        },
        "scatter": {**dated, "steps": [{"event": secret, "metric": metric}]},
    }
    return {"id": query_id, "kind": kind, "app": "demo", "spec": specs[kind]}


class FakeSDK:
    def __init__(self) -> None:
        self.workspace = load_workspace("examples/workspace")
        self.calls: list[tuple[str, Mapping[str, Any], int]] = []

    def validate_plan(self, plan: Mapping[str, Any], **options: Any) -> dict[str, Any]:
        self.calls.append(("validate", deepcopy(plan), options["max_workers"]))
        return {
            "schema_version": "gravity.plan-result.v1",
            "ok": True,
            "status": "validated",
            "dry_run": True,
            "declared_count": len(plan["nodes"]),
            "max_workers": options["max_workers"],
            "exit_code": 0,
            "results": [],
            "request": plan,
        }

    def execute_plan(self, plan: Mapping[str, Any], **options: Any) -> dict[str, Any]:
        self.calls.append(("execute", deepcopy(plan), options["max_workers"]))
        return {
            "schema_version": "gravity.plan-result.v1",
            "ok": True,
            "status": "success",
            "dry_run": False,
            "declared_count": len(plan["nodes"]),
            "success_count": len(plan["nodes"]),
            "failure_count": 0,
            "exit_code": 0,
            "max_workers": options["max_workers"],
            "results": [
                {"node_id": node["id"], "ok": True, "result": {"data": {}}}
                for node in plan["nodes"]
            ],
            "compiled_input": plan,
        }


class CountingInsight:
    def __init__(self, workers: int) -> None:
        self.active = 0
        self.peak = 0
        self.read_app_ids: list[str] = []
        self.lock = threading.Lock()
        self.rendezvous = (
            threading.Barrier(workers, timeout=RENDEZVOUS_TIMEOUT_SECONDS)
            if workers > 1
            else None
        )
        self.rendezvous_failures: list[str] = []

    def validate(self, _operation_id: str, _inputs: Mapping[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": "needs_live_metadata"}

    def operations(self, **_options: Any) -> list[dict[str, str]]:
        return [{"operation_id": "analysis.retention.query"}]

    def read(self, operation_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
        app_id = str(inputs["app_id"])
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
            self.read_app_ids.append(app_id)
        try:
            if self.rendezvous is not None:
                self._wait_for_reads(app_id)
            if app_id == "202":
                raise PermissionUnavailableError("not available")
            status = "empty" if app_id == "303" else "success"
            return {
                "schema_version": "gravity-insight.read.v1",
                "operation_id": operation_id,
                "ok": True,
                "status": status,
                "data": {"list": [] if status == "empty" else [{"total": int(app_id)}]},
            }
        finally:
            with self.lock:
                self.active -= 1

    def _wait_for_reads(self, app_id: str) -> None:
        assert self.rendezvous is not None
        try:
            self.rendezvous.wait()
        except threading.BrokenBarrierError as exc:
            with self.lock:
                message = (
                    "Insight read rendezvous timed out or broke after "
                    f"{RENDEZVOUS_TIMEOUT_SECONDS}s: app_id={app_id!r}, "
                    f"parties={self.rendezvous.parties}, active={self.active}, "
                    f"peak={self.peak}"
                )
                self.rendezvous_failures.append(message)
            raise AssertionError(message) from exc

class AnalysisQueryBatchTests(unittest.TestCase):
    def test_31_component_batch_matches_scalar_wire_shape_and_global_budget(self) -> None:
        scalar_sdk, scalar_transport = _transport_sdk(_event_result())
        scalar_sdk.analysis_query("event", _issue_24_spec(0), app="demo")
        scalar_body = scalar_transport.bodies[0]

        batch_sdk, batch_transport = _transport_sdk(
            _event_result(), rendezvous_parties=4
        )
        result = batch_sdk.analysis_queries(_issue_24_batch(), max_workers=4)
        representative = next(
            body
            for body in batch_transport.bodies
            if body["date_list"][0]["start_date"] == "2026-07-01"
        )
        differing = {
            key
            for key in scalar_body.keys() | representative.keys()
            if scalar_body.get(key) != representative.get(key)
        }
        self.assertEqual({"query_id"}, differing)

        fixed_spec = _issue_24_spec(0)
        fixed_spec["query_id"] = representative["query_id"]
        fixed_sdk, fixed_transport = _transport_sdk(_event_result())
        fixed_sdk.analysis_query("event", fixed_spec, app="demo")
        self.assertEqual(representative, fixed_transport.bodies[0])
        self.assertEqual([], batch_transport.rendezvous_failures)
        self.assertEqual((31, 4), (len(batch_transport.calls), batch_transport.peak))
        self.assertEqual(("success", 31, 0, 0, 0), (
            result["status"], result["success_count"], result["failure_count"],
            result["skipped_count"], result["exit_code"],
        ))
        self.assertEqual((4, 4, False, 0, 31, "completed"), (
            result["adaptive_execution"]["requested_max_workers"],
            result["adaptive_execution"]["final_max_workers"],
            result["adaptive_execution"]["degraded"],
            result["adaptive_execution"]["retry_count"],
            result["adaptive_execution"]["total_component_attempts"],
            result["adaptive_execution"]["terminal_reason"],
        ))

    def test_31_capacity_rejections_degrade_4_to_2_to_1_then_succeed(self) -> None:
        sdk, transport = _adaptive_transport_sdk(rejection_rounds=2)

        with patch("gravity_insight.analysis_query_batch_retry.time.sleep") as sleeper:
            result = sdk.analysis_queries(_issue_24_batch(), max_workers=4)

        self.assertEqual(("success", 31, 0, 0, 0), (
            result["status"], result["success_count"], result["failure_count"],
            result["skipped_count"], result["exit_code"],
        ))
        self.assertEqual([1.0, 2.0], [call.args[0] for call in sleeper.call_args_list])
        self.assertEqual({1: 31, 2: 31, 3: 31}, transport.phase_calls)
        self.assertEqual({1: 4, 2: 2, 3: 1}, transport.phase_peaks)
        self.assertEqual(93, len(transport.calls))
        self.assertEqual({3}, set(transport.query_calls.values()))
        adaptive = result["adaptive_execution"]
        self.assertEqual((4, 1, True, 2, 93, "completed"), (
            adaptive["requested_max_workers"], adaptive["final_max_workers"],
            adaptive["degraded"], adaptive["retry_count"],
            adaptive["total_component_attempts"], adaptive["terminal_reason"],
        ))
        self.assertEqual(
            [
                (1, 4, 31, 0, 31, 31, 0, 0),
                (2, 2, 31, 0, 31, 31, 0, 1000),
                (3, 1, 31, 31, 0, 0, 0, 2000),
            ],
            [
                (
                    item["attempt"], item["max_workers"], item["component_count"],
                    item["success_count"], item["retryable_upstream_failure_count"],
                    item["scheduled_retry_count"], item["terminal_failure_count"],
                    item["backoff_ms_before_attempt"],
                )
                for item in adaptive["attempts"]
            ],
        )
        self.assertEqual(
            [f"day_{index:02d}" for index in range(1, 32)],
            [item["node_id"] for item in result["results"]],
        )
        self.assertNotIn("fixture capacity rejection", repr(result))

    def test_31_capacity_rejections_stop_after_serial_attempt(self) -> None:
        sdk, transport = _adaptive_transport_sdk(rejection_rounds=3)

        with patch("gravity_insight.analysis_query_batch_retry.time.sleep") as sleeper:
            result = sdk.analysis_queries(_issue_24_batch(), max_workers=4)

        self.assertEqual(("error", 0, 31, 0, 3), (
            result["status"], result["success_count"], result["failure_count"],
            result["skipped_count"], result["exit_code"],
        ))
        self.assertEqual([1.0, 2.0], [call.args[0] for call in sleeper.call_args_list])
        self.assertEqual({1: 31, 2: 31, 3: 31}, transport.phase_calls)
        self.assertEqual({1: 4, 2: 2, 3: 1}, transport.phase_peaks)
        self.assertEqual(93, len(transport.calls))
        adaptive = result["adaptive_execution"]
        self.assertEqual((4, 1, 2, 93, "serial_retryable_failure"), (
            adaptive["requested_max_workers"], adaptive["final_max_workers"],
            adaptive["retry_count"], adaptive["total_component_attempts"],
            adaptive["terminal_reason"],
        ))
        self.assertEqual(
            [(31, 0), (31, 0), (0, 31)],
            [
                (item["scheduled_retry_count"], item["terminal_failure_count"])
                for item in adaptive["attempts"]
            ],
        )
        for item in result["results"]:
            error = item["error"]
            self.assertEqual(
                ("UPSTREAM_UNAVAILABLE", "upstream", "input", True),
                (error["code"], error["category"], error["field"], error["retryable"]),
            )
            self.assertIn("reached concurrency 1", error["next_action"])
        self.assertNotIn("fixture capacity rejection", repr(result))

    def test_adaptive_retry_does_not_replay_a_successful_component(self) -> None:
        first_day = "2026-07-01"
        sdk, transport = _adaptive_transport_sdk(
            rejection_rounds=1,
            first_round_successes=frozenset({first_day}),
        )

        with patch("gravity_insight.analysis_query_batch_retry.time.sleep") as sleeper:
            result = sdk.analysis_queries(_issue_24_batch(), max_workers=4)

        self.assertEqual("success", result["status"])
        self.assertEqual([1.0], [call.args[0] for call in sleeper.call_args_list])
        self.assertEqual({1: 31, 2: 30}, transport.phase_calls)
        self.assertEqual({1: 4, 2: 2}, transport.phase_peaks)
        self.assertEqual(61, len(transport.calls))
        self.assertEqual(1, transport.query_calls[first_day])
        self.assertEqual({2}, set(transport.query_calls.values()) - {1})
        adaptive = result["adaptive_execution"]
        self.assertEqual((2, 1, 61, "completed"), (
            adaptive["final_max_workers"], adaptive["retry_count"],
            adaptive["total_component_attempts"], adaptive["terminal_reason"],
        ))
        self.assertEqual(
            [(1, 30, 30), (30, 0, 0)],
            [
                (
                    item["success_count"],
                    item["retryable_upstream_failure_count"],
                    item["scheduled_retry_count"],
                )
                for item in adaptive["attempts"]
            ],
        )

    def test_v2_property_batch_reports_shared_dispersed_group_item_limit(self) -> None:
        payload = _issue_24_property_batch()
        scalar_sdk, _scalar_transport = _transport_sdk(
            _property_batch_response,
            operation_id="analysis.property.query",
            disable_field_validation=False,
        )
        scalar_statuses = [
            scalar_sdk.analysis_query("property", query["spec"], app="demo")["status"]
            for query in payload["queries"]
        ]
        dry_sdk, dry_transport = _transport_sdk(
            _property_batch_response,
            operation_id="analysis.property.query",
            disable_field_validation=False,
        )
        dry_run = dry_sdk.analysis_queries(payload, max_workers=3, dry_run=True)
        batch_sdk, batch_transport = _transport_sdk(
            _property_batch_response,
            operation_id="analysis.property.query",
            disable_field_validation=False,
        )

        result = batch_sdk.analysis_queries(payload, max_workers=3)

        self.assertEqual(["success", "success", "success"], scalar_statuses)
        self.assertEqual(("validated", 0), (dry_run["status"], dry_run["exit_code"]))
        self.assertEqual([], dry_transport.calls)
        self.assertEqual(("error", 0, 3, 2), (
            result["status"], result["success_count"], result["failure_count"],
            result["exit_code"],
        ))
        self.assertEqual(
            ["property_a", "property_b", "property_users"],
            [item["query_id"] for item in result["results"]],
        )
        self.assertEqual(3, sum(
            path.endswith("user/properties/")
            for _method, path, _kwargs in batch_transport.calls
        ))
        self.assertEqual(1, sum(
            path.endswith("user_property_list/")
            for _method, path, _kwargs in batch_transport.calls
        ))
        for item in result["results"]:
            error = item["error"]
            self.assertEqual(
                (
                    "PAGINATION_LIMIT",
                    "caller",
                    "limits.max_items",
                    False,
                    "output_budget",
                    "max_items_exceeded",
                ),
                (
                    error["code"],
                    error["category"],
                    error["field"],
                    error["retryable"],
                    error["stage"],
                    error["cause"],
                ),
            )
            self.assertIsNone(item["result"])

    def test_all_five_specs_become_same_layer_plan_nodes_and_dry_run_delegates(self) -> None:
        sdk = FakeSDK()
        kinds = ("event", "funnel", "retention", "property", "scatter")
        payload = {
            "schema_version": BATCH_SCHEMA_VERSION,
            "queries": [_query(kind, kind) for kind in kinds],
        }
        result = validate_analysis_query_batch(sdk, payload, max_workers=5)
        action, plan, workers = sdk.calls[0]
        self.assertEqual(("validate", 5), (action, workers))
        self.assertEqual(list(kinds), [node["id"] for node in plan["nodes"]])
        self.assertTrue(all(node["kind"] == "composite" for node in plan["nodes"]))
        self.assertTrue(all(node["request"]["name"] == "analysis_query" for node in plan["nodes"]))
        self.assertTrue(all("depends_on" not in node for node in plan["nodes"]))
        self.assertEqual((True, 5, []), (result["dry_run"], result["query_count"], result["results"]))
        self.assertNotIn("request", result)
        schema = analysis_query_batch_schema()
        adaptive = schema["execution"]["adaptive_concurrency"]
        self.assertEqual(
            (
                "gravity.analysis-query-batch.adaptive-concurrency.v1",
                1000,
                30000,
                "terminal for this batch invocation",
            ),
            (
                adaptive["policy"],
                adaptive["base_backoff_ms"],
                adaptive["max_backoff_ms"],
                adaptive["serial_failure"],
            ),
        )
        self.assertTrue(schema["output"]["adaptive_execution"]["live_only"])
        arguments = [
            "analysis", "query", "batch", "--input", "queries.json",
            "--concurrency", "5", "--dry-run",
        ]
        parsed = build_parser().parse_args(arguments)
        self.assertEqual("batch", parsed.analysis_query_command)
        self.assertFalse(command_requires_credentials(arguments, build_parser))
        parsed.input = payload
        with patch(
            "gravity_insight.analysis_query_batch_cli.run_analysis_query_batch",
            return_value={"ok": True},
        ) as run:
            run_analysis_query_batch_command(
                parsed, sdk=sdk, object_input=lambda value: value
            )
        self.assertIs(sdk.workspace, run.call_args.kwargs["workspace"])
        scalar = build_parser().parse_args([
            "analysis", "query", "--kind", "event", "--spec-schema",
            "batch", "--input", "{}",
        ])
        with self.assertRaises(InputValidationError):
            run_analysis_query_batch_command(
                scalar, sdk=sdk, object_input=lambda value: value
            )
        self.assertEqual(1, len(sdk.calls))

    def test_invalid_or_duplicate_item_stops_before_any_sdk_plan_call(self) -> None:
        sdk = FakeSDK()
        invalid = _query("bad")
        invalid["spec"]["unknown"] = "private-value"
        payloads = [
            {"schema_version": BATCH_SCHEMA_VERSION, "queries": [_query("ok"), invalid]},
            {"schema_version": BATCH_SCHEMA_VERSION, "queries": [_query("same"), _query("same")]},
            {"schema_version": BATCH_SCHEMA_VERSION, "queries": [_query(f"q{i}") for i in range(33)]},
        ]
        for payload in payloads:
            with self.subTest(count=len(payload["queries"])), self.assertRaises(InputValidationError):
                execute_analysis_query_batch(sdk, payload)
            self.assertEqual([], sdk.calls)

    def test_execution_delegates_once_preserves_order_and_never_echoes_input(self) -> None:
        private = "person@example.com"
        sdk = FakeSDK()
        payload = {
            "schema_version": BATCH_SCHEMA_VERSION,
            "queries": [_query("slow", secret=private), _query("fast", "scatter")],
        }
        result = execute_analysis_query_batch(sdk, payload, max_workers=2)
        self.assertEqual(["slow", "fast"], [item["node_id"] for item in result["results"]])
        self.assertEqual(["execute"], [call[0] for call in sdk.calls])
        self.assertEqual(2, result["max_workers"])
        self.assertNotIn(private, repr(result))
        self.assertNotIn("compiled_input", result)

    def test_explicit_apps_share_plan_budget_and_preserve_per_app_failures(self) -> None:
        query = _query("retention", "retention")
        query.pop("app")
        query["apps"] = [101, 202, 303]
        payload = {
            "schema_version": MULTI_APP_BATCH_SCHEMA_VERSION,
            "queries": [query],
        }

        observations = []
        for workers in (1, 3):
            insight = CountingInsight(workers)
            result = execute_analysis_query_batch(
                GravitySDK(insight=insight, workspace="examples/workspace"),
                payload,
                max_workers=workers,
            )
            if insight.rendezvous_failures:
                self.fail(
                    f"workers={workers}: " + "; ".join(insight.rendezvous_failures)
                )
            observations.append((insight, result))

        serial, concurrent = observations
        self.assertEqual((1, 3), (serial[0].peak, concurrent[0].peak))
        self.assertEqual(
            (["101", "202", "303"], ["101", "202", "303"]),
            (sorted(serial[0].read_app_ids), sorted(concurrent[0].read_app_ids)),
        )
        result = concurrent[1]
        self.assertEqual(("partial", 3, 2, 1, 1, 3), (
            result["status"], result["component_count"], result["success_count"],
            result["empty_count"], result["failure_count"], result["exit_code"],
        ))
        self.assertFalse(result["cross_app_aggregation"])
        self.assertEqual([101, 202, 303], [item["app"] for item in result["results"]])
        self.assertEqual((False, 0, 3, "non_retryable_failure"), (
            result["adaptive_execution"]["degraded"],
            result["adaptive_execution"]["retry_count"],
            result["adaptive_execution"]["total_component_attempts"],
            result["adaptive_execution"]["terminal_reason"],
        ))
        failed = result["results"][1]
        self.assertEqual(("retention", False, "error", "PERMISSION_UNAVAILABLE"), (
            failed["query_id"], failed["ok"], failed["status"], failed["error"]["code"],
        ))
        self.assertIsNone(failed["result"])
        self.assertEqual("empty", result["results"][2]["status"])

        rejected = deepcopy(payload)
        for apps, kind in (
            (["*"], "retention"),
            ([101, 101], "retention"),
            (["demo", 1001], "retention"),
            (list(range(1, 34)), "retention"),
            ([101], "scatter"),
        ):
            rejected["queries"][0]["apps"] = apps
            rejected["queries"][0]["kind"] = kind
            with self.subTest(apps=apps, kind=kind), self.assertRaises(InputValidationError):
                execute_analysis_query_batch(FakeSDK(), rejected)

        schema = analysis_query_multi_app_schema()
        self.assertEqual(
            (["id", "kind", "apps", "spec"], False, 32),
            (
                schema["input"]["required"],
                schema["output"]["all_apps_selector"],
                schema["execution"]["max_expanded_components"],
            ),
        )

    def test_scalar_cli_apps_only_changes_the_app_parameter(self) -> None:
        parsed = build_parser().parse_args([
            "analysis", "query", "--kind", "retention", "--spec", "spec.json",
            "--apps", "main,overseas", "--concurrency", "3",
        ])
        with patch(
            "gravity_insight.sdk.GravitySDK.analysis_queries",
            return_value={"schema_version": "gravity.analysis-query-batch-result.v2"},
        ) as run:
            result = run_analysis_query_command(
                parsed,
                lambda **_options: type("Client", (), {
                    "schema": lambda _self, _operation: {"stability": "stable"}
                })(),
                lambda _value: _query("retention", "retention")["spec"],
                lambda *_args: ({}, []),
                lambda *_args: {},
            )
        payload = run.call_args.args[0]
        self.assertEqual("gravity.analysis-query-batch-result.v2", result["schema_version"])
        self.assertEqual(("gravity.analysis-query-batch.v2", ["main", "overseas"], 3), (
            payload["schema_version"], payload["queries"][0]["apps"],
            run.call_args.kwargs["max_workers"],
        ))


if __name__ == "__main__":
    unittest.main()
