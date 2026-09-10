from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gravity_insight.blob import BlobTransferError
from gravity_insight.errors import ManifestError
from gravity_insight.export_cli import export_cli_error
from gravity_insight.export_client import ExportClientMixin
from gravity_insight.export_contracts import ExportContractRegistry
from gravity_insight.export_gateway import call_export_effect
from gravity_insight.export_models import ExportResult, ExportRuntimeError, ExportState, _export_error
from gravity_insight.export_results import export_result_envelope
from gravity_insight.registry import PolicyEngine
from tests.test_gravity_insight_export_integration import CONTRACT_PATH, FakeRuntime, read_registry
from tests.test_gravity_http_runtime import FakeResponse, QueueSession, StaticCredentials, runtime_for


START = "export.analysis.origin_event.start"
EVALUATE = "export.analysis.origin_event.evaluate"
DRAFT = {"type": "user", "field": "synthetic_property", "operator": "EQUALS", "value": [1]}


class Client(ExportClientMixin):
    def __init__(self, contracts, responses=()):
        self._export_contracts = contracts
        self._export_policy = PolicyEngine(read_registry(), effect_routes=contracts.effect_routes())
        self._export_runtime = FakeRuntime(responses)


def payload(conditions):
    return {
        "app_id": 1, "task_name": "synthetic-export", "task_type": "origin_event_data",
        "time_range": ["2026-01-01", "2026-01-02"], "event_name_list": ["synthetic_event"],
        "cond_logic": "AND", "conditions": conditions,
    }


class ExportConditionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contracts = ExportContractRegistry.from_file(CONTRACT_PATH)
        cls.columns = tuple(cls.contracts.get(START).privacy["allowed_columns"])

    def invoke(self, client, method, body, destination="unused.csv.gz"):
        if method == "evaluate":
            return client.export_evaluate(EVALUATE, body)
        args = (START, body, destination) if method == "run" else (START, body)
        return getattr(client, "export_" + method)(
            *args, requested_columns=self.columns, idempotency_key="synthetic-export-218")

    def public_error(self, error, method="evaluate"):
        return export_cli_error(SimpleNamespace(
            operation_id=EVALUATE if method == "evaluate" else START,
            export_command=method), error)

    def test_routes_share_versioned_schema_and_publish_draft_not_acceptance(self):
        document = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        refs = [r["request"]["input_schema"] for r in document["routes"]
                if r["operation_id"] in {START, EVALUATE}]
        self.assertEqual([{"$ref": "#/definitions/origin_event_input_v1"}] * 2, refs)
        start = self.contracts.describe(START)["input_schema"]
        self.assertEqual(start, self.contracts.describe(EVALUATE)["input_schema"])
        conditions = start["properties"]["conditions"]
        self.assertEqual(0, conditions["max_items"])
        self.assertEqual("gravity.export.origin-event-condition.v1", conditions["items"]["schema_version"])
        self.assertEqual(("unverified_client_draft", False),
                         (conditions["items"]["status"], conditions["items"]["executable"]))
        self.assertNotIn('"unknown"', json.dumps(start))

    def test_empty_conditions_keep_evaluate_and_start_wire_unchanged(self):
        client = Client(self.contracts, [{"code": 0, "data": {"total": 7}},
                                       {"code": 0, "data": {"task_id": "synthetic-job"}}])
        body = payload([])
        before = deepcopy(body)
        self.assertEqual(7, self.invoke(client, "evaluate", body)["estimated_rows"])
        self.assertEqual("synthetic-job", self.invoke(client, "start", body)["job_id"])
        self.assertEqual([before, before], [call[3] for call in client._export_runtime.calls])
        self.assertEqual(before, body)

    def test_schema_references_are_local_existing_and_acyclic(self):
        for ref in ("https://example.test/schema", "#/definitions/missing",
                    "#/definitions/origin_event_condition_v1"):
            with self.subTest(ref=ref), tempfile.TemporaryDirectory() as directory:
                document = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
                document["definitions"]["origin_event_condition_v1"] = {"$ref": ref}
                path = Path(directory) / "routes.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(ManifestError):
                    ExportContractRegistry.from_file(path)

    def test_conditions_are_rejected_before_all_io_with_safe_precise_diagnostics(self):
        cases = [
            ([DRAFT], "conditions[0]", "EXPORT_CONDITIONS_UNSUPPORTED"),
            ([{**DRAFT, "operator": "RANGE_IN", "value": [1, 2]}], "conditions[0]", "EXPORT_CONDITIONS_UNSUPPORTED"),
            ([{k: v for k, v in DRAFT.items() if k != "type"}], "conditions[0].type", "INPUT_INVALID"),
            ([{**DRAFT, "PRIVATE_SENTINEL": "PRIVATE_SENTINEL"}], "conditions[0]", "INPUT_INVALID"),
            ([{**DRAFT, "type": "user_property"}], "conditions[0].type", "INPUT_INVALID"),
            ([{**DRAFT, "operator": "UNKNOWN"}], "conditions[0].operator", "INPUT_INVALID"),
            ([{**DRAFT, "value": [None]}], "conditions[0].value[0]", "INPUT_INVALID"),
            ([{**DRAFT, "value": [1, 2]}], "conditions[0].value", "INPUT_INVALID"),
            ([{**DRAFT, "operator": "RANGE_IN", "value": [2, 1]}], "conditions[0].value", "INPUT_INVALID"),
            ([{**DRAFT, "operator": "RANGE_IN", "value": [True, 2]}], "conditions[0].value[0]", "INPUT_INVALID"),
            ([DRAFT, {**DRAFT, "field": []}], "conditions[1].field", "INPUT_INVALID"),
            ([{**DRAFT, "value": [float("nan")]}], "conditions[0].value[0]", "INPUT_INVALID"),
            (["PRIVATE_SENTINEL"], "conditions[0]", "INPUT_INVALID"),
            ({}, "conditions", "INPUT_INVALID"),
        ]
        for conditions, field, code in cases:
            for method in ("evaluate", "start", "run"):
                with self.subTest(field=field, code=code, method=method):
                    client = Client(self.contracts)
                    with patch("gravity_insight.export_client.validate_export_live_fields") as metadata:
                        with self.assertRaises(ExportRuntimeError) as raised:
                            self.invoke(client, method, payload(deepcopy(conditions)))
                        metadata.assert_not_called()
                    envelope = self.public_error(raised.exception, method)
                    self.assertEqual((code, field), (envelope["error"]["code"], envelope["error"]["field"]))
                    self.assertIn("Preserve required business filters", envelope["error"]["next_action"])
                    self.assertEqual([], client._export_runtime.calls)
                    self.assertNotIn("PRIVATE_SENTINEL", json.dumps(envelope))

    def test_direct_gateway_cannot_bypass_condition_rejection(self):
        client = Client(self.contracts)
        with self.assertRaises(ExportRuntimeError):
            call_export_effect(client._export_policy, client._export_runtime,
                               self.contracts.get(START), payload([DRAFT]), timeout_seconds=1)
        self.assertEqual([], client._export_runtime.calls)

    def test_deep_condition_value_is_input_invalid_before_copy_or_io(self):
        nested = json.loads("[" * 600 + "1" + "]" * 600)
        for method in ("evaluate", "start", "run"):
            with self.subTest(method=method):
                client = Client(self.contracts)
                body = payload([{**DRAFT, "value": [nested]}])
                with self.assertRaises(ExportRuntimeError) as raised:
                    self.invoke(client, method, body)
                error = self.public_error(raised.exception, method)["error"]
                self.assertEqual(("INPUT_INVALID", "conditions[0].value[0]"),
                                 (error["code"], error["field"]))
                self.assertIs(nested, body["conditions"][0]["value"][0])
                self.assertEqual([], client._export_runtime.calls)

    def test_condition_count_limit_rejects_before_item_validation_or_io(self):
        for method in ("evaluate", "start", "run"):
            with self.subTest(method=method):
                client = Client(self.contracts)
                body = payload([dict(DRAFT) for _ in range(101)])
                with patch("gravity_insight.export_models._validate_item") as validate_item:
                    with self.assertRaises(ExportRuntimeError) as raised:
                        self.invoke(client, method, body)
                    validate_item.assert_not_called()
                error = self.public_error(raised.exception, method)["error"]
                self.assertEqual(("INPUT_INVALID", "conditions"), (error["code"], error["field"]))
                self.assertIn("100", error["next_action"])
                self.assertEqual([], client._export_runtime.calls)

    def test_schema_reference_resolution_has_depth_and_expansion_budgets(self):
        chain = {f"node_{i}": {"$ref": f"#/definitions/node_{i + 1}"} for i in range(1100)}
        chain["node_1100"] = {"type": "string"}
        # Wide-and-shallow, not deep: a binary-branching tree reaches the depth budget
        # at roughly the same size it reaches the expansion budget, so it cannot isolate
        # the two. Fan out one level instead: max depth stays ~4 regardless of fan-out
        # width, while each sibling still costs resolver calls against the shared budget.
        dag = {"node_0": {f"leg_{i}": {"$ref": "#/definitions/node_0_leaf"} for i in range(1500)}}
        dag["node_0_leaf"] = {"type": "string"}
        for definitions, budget in ((chain, "depth"), (dag, "expansion")):
            with self.subTest(budget=budget), tempfile.TemporaryDirectory() as directory:
                document = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
                document["definitions"].update(definitions)
                document["definitions"]["origin_event_condition_v1"] = {"$ref": "#/definitions/node_0"}
                path = Path(directory) / "routes.json"
                path.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(ManifestError, budget + " budget"):
                    ExportContractRegistry.from_file(path)

    def test_semantic_failure_and_contradiction_survive_run_create_catch(self):
        cases = [
            ({"code": 400}, "EXPORT_SEMANTIC_REJECTED", "response.code", "400"),
            ({"code": "PRIVATE_SENTINEL"}, "EXPORT_SEMANTIC_REJECTED", "response.code", "redacted"),
            ({"code": 0}, "EXPORT_RESPONSE_CONTRADICTED", "response.extra.error", "0"),
        ]
        for response, code, field, semantic_code in cases:
            response = {**response, "msg": "PRIVATE_SENTINEL", "extra": {"error": "PRIVATE_SENTINEL"},
                        "data": {"total": 7, "task_id": "synthetic-job"}}
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                client = Client(self.contracts, [response, response])
                with self.assertRaises(ExportRuntimeError) as raised:
                    self.invoke(client, "evaluate", payload([]))
                self.assertIsInstance(raised.exception, BlobTransferError)
                evaluate = self.public_error(raised.exception)
                result = self.invoke(client, "run", payload([]), str(Path(directory) / "result.csv.gz"))
                for envelope in (evaluate, result):
                    self.assertEqual((code, field, False), (envelope["error"]["code"],
                                     envelope["error"]["field"], envelope["error"]["retryable"]))
                    self.assertEqual("unclassified", envelope["diagnostics"]["responsibility"])
                    self.assertEqual(semantic_code, envelope["diagnostics"]["semantic_code"])
                    self.assertNotIn("PRIVATE_SENTINEL", json.dumps(envelope))
                self.assertEqual(evaluate["error"], result["error"])
                self.assertEqual(2, len(client._export_runtime.calls))
                self.assertEqual([], list(Path(directory).iterdir()))

    def test_error_layers_do_not_collapse_into_schema_drift(self):
        for code, stage, expected in (
            ("EXPORT_SCHEMA_MISMATCH", "headers", "CONTRACT_CHANGED"),
            ("EXPORT_PROTOCOL_ERROR", "export_job_create", "CONTRACT_CHANGED"),
            ("EXPORT_UPSTREAM_FAILED", "export_job_create", "UPSTREAM_UNAVAILABLE"),
        ):
            with self.subTest(code=code):
                error = _export_error("synthetic failure", code=code, stage=stage)
                result = ExportResult(ExportState.FAILED, None, (ExportState.CREATING, ExportState.FAILED), error=error)
                self.assertEqual(expected, self.public_error(error)["error"]["code"])
                self.assertEqual(expected, export_result_envelope(START, result)["error"]["code"])

    def test_non_scalar_status_is_protocol_failure_not_python_type_error(self):
        for code in ([], {}, False):
            with self.subTest(code=code):
                session = QueueSession([FakeResponse({"code": code}), FakeResponse({"code": code})])
                credentials = StaticCredentials()
                client = Client(self.contracts)
                client._export_runtime = runtime_for(session, credentials=credentials)
                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaises(ExportRuntimeError) as raised:
                        self.invoke(client, "evaluate", payload([]))
                    self.assertEqual("EXPORT_PROTOCOL_ERROR", raised.exception.code)
                    result = self.invoke(client, "run", payload([]), str(Path(directory) / "result.csv.gz"))
                    self.assertEqual("CONTRACT_CHANGED", result["error"]["code"])
                    self.assertEqual("response.code", result["error"]["field"])
                self.assertEqual((2, 0), (len(session.calls), credentials.refreshes))

    def test_empty_error_indicator_preserves_success(self):
        for error in (None, "", [], {}):
            with self.subTest(error=error):
                client = Client(self.contracts, [{"code": 0, "extra": {"error": error}, "data": {"total": 0}}])
                self.assertTrue(self.invoke(client, "evaluate", payload([]))["ok"])
