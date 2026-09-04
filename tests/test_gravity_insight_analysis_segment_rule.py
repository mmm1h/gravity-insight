from __future__ import annotations

import json
import threading
import unittest
from pathlib import Path
from typing import Any, Mapping

try:
    from gravity_insight import GravityInsightClient
    from gravity_insight.errors import InputValidationError
    from gravity_insight.segment_spec import compile_segment_spec
    from gravity_insight.transport import TransportResponse
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_insight import GravityInsightClient
    from gravity_insight.errors import InputValidationError
    from gravity_insight.segment_spec import compile_segment_spec
    from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "src" / "gravity_insight" / "manifests"
SEGMENT_RULE_MANIFEST = MANIFEST_DIR / "analysis_segment_rule.json"
TARGET_PATH = "/report/api/v3/dataanalysis/segment/from_rule/evaluate_percent/"
BOUNDARY_FIXTURE = json.loads(
    (ROOT / "tests" / "fixtures" / "segment_custom_event_boundary.json").read_text(
        encoding="utf-8"
    )
)


class RoutingTransport:
    is_test_transport = True

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.lock = threading.Lock()

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        with self.lock:
            self.calls.append((method, path, kwargs))
        return TransportResponse(
            200,
            self.handler(method, path, kwargs),
            "2026-08-08T10:00:00Z",
        )


def all_repository_operations() -> dict[str, dict[str, Any]]:
    operations: dict[str, dict[str, Any]] = {}
    for path in sorted(MANIFEST_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for operation in document.get("operations", []):
            operations[operation["operation_id"]] = operation
    return operations


def repository_manifest(*operation_ids: str) -> dict[str, Any]:
    all_operations = all_repository_operations()
    selected: dict[str, dict[str, Any]] = {}
    pending = list(operation_ids)
    while pending:
        operation_id = pending.pop()
        if operation_id in selected:
            continue
        operation = all_operations.get(operation_id)
        if operation is None:
            raise AssertionError(f"missing repository operation: {operation_id}")
        selected[operation_id] = operation
        pending.extend(operation.get("required_parent", ()))
    return {"manifest_version": 1, "operations": list(selected.values())}


def client_for(*operation_ids: str, handler):
    transport = RoutingTransport(handler)
    client = GravityInsightClient._from_manifest_for_tests(
        repository_manifest(*operation_ids),
        transport=transport,
    )
    return client, transport


def page(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
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


def property_metadata() -> dict[str, Any]:
    return {
        "name": "region",
        "cname": "region",
        "data_type": "STRING",
        "visible": True,
    }


def event_info() -> dict[str, Any]:
    return {
        "code": 0,
        "data": {
            "properties": {
                "common": [property_metadata()],
                "custom": [],
                "preset": [],
            }
        },
    }


def base_inputs() -> dict[str, Any]:
    return {
        "app_id": "101",
        "name": "contract probe",
        "remark": "",
        "update_type": "Manual",
        "date_range": {
            "start_date": "2026-08-08",
            "end_date": "2026-08-08",
        },
        "cond_logic": "AND",
        "user_property_rules": {"cond_logic": "AND", "groups": []},
        "user_event_rules": {"cond_logic": "AND", "groups": []},
    }


class GravityInsightAnalysisSegmentRuleTests(unittest.TestCase):
    def test_manifest_is_stable_structured_and_never_exposes_raw_fe_config(
        self,
    ) -> None:
        document = json.loads(SEGMENT_RULE_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(1, document["manifest_version"])
        self.assertEqual(1, len(document["operations"]))
        operation = document["operations"][0]
        self.assertEqual("analysis.segment.evaluate_percent", operation["operation_id"])
        self.assertEqual("stable", operation["stability"])
        self.assertEqual("POST", operation["upstream_method"])
        self.assertEqual(TARGET_PATH, operation["path_template"])
        self.assertEqual(
            {
                "app_id",
                "name",
                "remark",
                "update_type",
                "date_range",
                "cond_logic",
                "user_property_rules",
                "user_event_rules",
            },
            set(operation["input_fields"]),
        )
        self.assertEqual(
            ["part", "percent", "total"],
            operation["response_projection"]["numeric_paths"],
        )
        self.assertTrue(operation["live_probe"]["enabled"])
        self.assertNotIn("FE_CONFIG", operation["input_fields"])
        self.assertNotIn("FE_CONFIG", operation["request"]["body_fields"])
        self.assertNotIn("FE_CONFIG", operation["privacy_policy"]["redact_keys"])
        serialized = json.dumps(operation, ensure_ascii=False)
        self.assertNotIn("raw_body", serialized)

        probe_inputs = json.loads(json.dumps(operation["live_probe"]["input"]))
        probe_inputs["app_id"] = "101"
        probe_inputs["date_range"] = {
            "start_date": "2026-08-08",
            "end_date": "2026-08-08",
        }
        client, transport = client_for(
            "analysis.segment.evaluate_percent",
            handler=lambda *_args, **_kwargs: self.fail("validation sent a request"),
        )
        validation = client.validate(
            "analysis.segment.evaluate_percent", probe_inputs
        )
        self.assertEqual(
            (True, "valid_offline"),
            (validation["ok"], validation["status"]),
        )
        self.assertEqual([], transport.calls)

    def test_empty_rule_evaluation_derives_exact_frontend_body(self) -> None:
        def handler(method: str, path: str, kwargs: Mapping[str, Any]):
            if path == TARGET_PATH:
                self.assertEqual("POST", method)
                body = kwargs["body"]
                self.assertEqual(101, body["app_id"])
                self.assertEqual("contract probe", body["segment_name"])
                self.assertEqual("", body["segment_remark"])
                self.assertEqual("Manual", body["update_type"])
                self.assertEqual(
                    {"start_date": "2026-08-08", "end_date": "2026-08-08"},
                    body["update_date_range"],
                )
                self.assertEqual(
                    {"cond_logic": "AND", "list": []}, body["from_user_prop"]
                )
                self.assertEqual(
                    {"cond_logic": "AND", "list": []}, body["from_event_prop"]
                )
                self.assertEqual(
                    {"userPropertyRules": [], "userBehaviorRules": []},
                    json.loads(body["FE_CONFIG"]),
                )
                return {"code": 0, "data": {"part": 0, "percent": 0, "total": 0}}
            raise AssertionError(f"unexpected path: {path}")

        client, transport = client_for(
            "analysis.segment.evaluate_percent", handler=handler
        )
        result = client.read("analysis.segment.evaluate_percent", base_inputs())
        self.assertEqual("success", result["status"])
        self.assertEqual({"part": 0, "percent": 0, "total": 0}, result["data"])
        self.assertEqual(1, len(transport.calls))

    def test_property_and_event_rules_compile_from_metadata_backed_shape(self) -> None:
        def handler(_method: str, path: str, kwargs: Mapping[str, Any]):
            if path.endswith("user_property_list/"):
                return page([property_metadata()])
            if path.endswith("event_list/"):
                return page(
                    [
                        {
                            "name": "purchase",
                            "cname": "purchase",
                            "visible": True,
                        }
                    ]
                )
            if path.endswith("event_property_list/"):
                return page([])
            if path.endswith("event_info/"):
                return event_info()
            if path == TARGET_PATH:
                body = kwargs["body"]
                self.assertEqual(
                    {
                        "cond_logic": "OR",
                        "list": [
                            {
                                "cond_logic": "AND",
                                "list": [
                                    {
                                        "operator": "EQUALS",
                                        "field": "region",
                                        "type": "user",
                                        "value": ["north"],
                                    }
                                ],
                            }
                        ],
                    },
                    body["from_user_prop"],
                )
                event = body["from_event_prop"]["list"][0]["list"][0]
                self.assertEqual("purchase", event["event_name"])
                self.assertTrue(event["did"])
                self.assertEqual(
                    {"name": "PresetAllCount", "field": "PresetAllCount"},
                    event["target"],
                )
                self.assertEqual([20260801, 20260807], event["time_zone"]["fixed_date"])
                self.assertEqual([], event["time_zone"]["dynamic_date"])
                self.assertEqual([], event["time_zone"]["mixed_date"])
                self.assertEqual("region", event["conditions"][0]["field"])
                config = json.loads(body["FE_CONFIG"])
                self.assertEqual(
                    "region",
                    config["userPropertyRules"][0]["conditions"][0]["filed_value"],
                )
                self.assertEqual(
                    "purchase",
                    config["userBehaviorRules"][0]["conditions"][0]["eventValue"],
                )
                return {"code": 0, "data": {"part": 1, "percent": 10, "total": 10}}
            raise AssertionError(f"unexpected path: {path}")

        client, transport = client_for(
            "analysis.segment.evaluate_percent", handler=handler
        )
        inputs = base_inputs()
        inputs["cond_logic"] = "OR"
        inputs["user_property_rules"] = {
            "cond_logic": "OR",
            "groups": [
                {
                    "cond_logic": "AND",
                    "conditions": [
                        {
                            "field": "region",
                            "type": "user",
                            "operator": "EQUALS",
                            "value": ["north"],
                        }
                    ],
                }
            ],
        }
        inputs["user_event_rules"] = {
            "cond_logic": "AND",
            "groups": [
                {
                    "cond_logic": "AND",
                    "conditions": [
                        {
                            "event_name": "purchase",
                            "did": True,
                            "target": {
                                "name": "PresetAllCount",
                                "field": "PresetAllCount",
                            },
                            "did_condition": {
                                "operator": "EQUALS",
                                "value": [],
                            },
                            "date_range": {
                                "date_type": "static",
                                "date": ["2026-08-01", "2026-08-07"],
                            },
                            "cond_logic": "AND",
                            "conditions": [
                                {
                                    "field": "region",
                                    "type": "event",
                                    "operator": "EQUALS",
                                    "value": ["north"],
                                }
                            ],
                        }
                    ],
                }
            ],
        }

        result = client.read("analysis.segment.evaluate_percent", inputs)
        self.assertEqual("success", result["status"])
        self.assertTrue(any(path == TARGET_PATH for _, path, _ in transport.calls))

    def test_positive_custom_event_control_reaches_aggregate_success(self) -> None:
        compiled = compile_segment_spec(
            BOUNDARY_FIXTURE["positive_custom_event"], app=101
        )
        event_name = compiled.inputs["user_event_rules"]["groups"][0][
            "conditions"
        ][0]["event_name"]

        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path.endswith("user_property_list/"):
                return page([])
            if path.endswith("event_list/"):
                return page([{"name": event_name, "cname": "fixture", "visible": True}])
            if path.endswith("event_property_list/"):
                return page([])
            if path.endswith("event_info/"):
                return event_info()
            if path == TARGET_PATH:
                return {"code": 0, "data": {"part": 3, "percent": 30, "total": 10}}
            raise AssertionError(f"unexpected path: {path}")

        client, transport = client_for(
            "analysis.segment.evaluate_percent", handler=handler
        )
        result = client.read(compiled.operation_id, compiled.inputs)

        self.assertEqual("success", result["status"])
        self.assertEqual({"part": 3, "percent": 30, "total": 10}, result["data"])
        self.assertEqual(1, sum(path == TARGET_PATH for _, path, _ in transport.calls))

    def test_rejected_static_count_custom_event_returns_named_gap_error(self) -> None:
        compiled = compile_segment_spec(
            BOUNDARY_FIXTURE["rejected_custom_event"], app=101
        )
        event_name = compiled.inputs["user_event_rules"]["groups"][0][
            "conditions"
        ][0]["event_name"]

        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path.endswith("user_property_list/"):
                return page([])
            if path.endswith("event_list/"):
                return page([{"name": event_name, "cname": "fixture", "visible": True}])
            if path.endswith("event_property_list/"):
                return page([])
            if path.endswith("event_info/"):
                return event_info()
            if path == TARGET_PATH:
                return {
                    "code": 400,
                    "extra": {"error": "fixture-private-upstream-rejection"},
                }
            raise AssertionError(f"unexpected path: {path}")

        client, transport = client_for(
            "analysis.segment.evaluate_percent", handler=handler
        )
        result = client.read(compiled.operation_id, compiled.inputs)

        error = result["error"]
        self.assertEqual("semantic_error", result["status"])
        self.assertEqual(
            (
                "SEGMENT_EVENT_RULE_ACCEPTANCE_UNPROVEN",
                "upstream",
                "user_event_rules.groups[0].conditions[0]",
                False,
            ),
            (
                error["code"],
                error["category"],
                error["field"],
                error["retryable"],
            ),
        )
        self.assertIn("metadata validity does not establish", error["message"])
        self.assertIn("sanitized current-main paired Segment receipt", error["next_action"])
        self.assertIn("not an equivalent first-exposure result", error["next_action"])
        self.assertNotIn(event_name, repr(result))
        self.assertNotIn("fixture-private-upstream-rejection", repr(result))
        self.assertEqual(1, sum(path == TARGET_PATH for _, path, _ in transport.calls))

    def test_raw_fe_config_and_unknown_nested_keys_fail_before_evaluation(self) -> None:
        client, transport = client_for(
            "analysis.segment.evaluate_percent",
            handler=lambda _method, _path, _kwargs: (_ for _ in ()).throw(
                AssertionError("evaluation request must not be sent")
            ),
        )
        raw = {**base_inputs(), "FE_CONFIG": "{}"}
        with self.assertRaises(InputValidationError):
            client.read("analysis.segment.evaluate_percent", raw)
        self.assertEqual([], transport.calls)

        invalid = base_inputs()
        invalid["user_property_rules"] = {
            "cond_logic": "AND",
            "groups": [{"cond_logic": "AND", "conditions": [], "query_sql": "x"}],
        }
        with self.assertRaises(InputValidationError):
            client.read("analysis.segment.evaluate_percent", invalid)
        self.assertFalse(any(path == TARGET_PATH for _, path, _ in transport.calls))

        private = base_inputs()
        private["name"] = "secret-segment-name"
        private["remark"] = "private-remark"
        private["user_property_rules"] = {
            "cond_logic": "AND",
            "groups": [{"cond_logic": "AND", "conditions": [{
                "field": "region", "type": "user", "operator": "EQUALS",
                "value": ["north-secret"],
            }]}],
        }
        rendered = json.dumps(
            client.validate(
                "analysis.segment.evaluate_percent", private, render_wire=True
            ),
            ensure_ascii=False,
        )
        for authorized_value in (
            "secret-segment-name",
            "private-remark",
            "north-secret",
        ):
            self.assertIn(authorized_value, rendered)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
