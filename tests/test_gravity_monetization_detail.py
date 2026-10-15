from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import gravity_insight
from gravity_insight import cli
from gravity_insight._field_policy_detail import validate_analysis_detail
from gravity_insight.monetization_detail import (
    DEVICE_INFO_FIELDS,
    OPERATION_ID,
    SAFE_ROW_FIELDS,
    monetization_detail,
    sanitize_monetization_detail_result,
)
from gravity_insight.monetization_query import normalize_monetization_query
from gravity_insight.contracts.envelope_obligations import EnvelopeObligations
from gravity_insight.models import load_operation_manifest
from gravity_insight.onboarding import command_requires_credentials
from gravity_insight.plan import AdapterContext, execute_plan
from gravity_insight.plan_adapters import build_plan_adapters
from gravity_insight.sdk import GravitySDK
from gravity_insight.registry import _analysis_monetization_detail_request_parts
DAY = "2026-08-08"
SAFE = {
    "CreateTime": "2026-08-08 12:00:00",
    "AdEventTime": "2026-08-08T12:00:01",
    "AdPlatform": "demo-platform",
    "event$ecpm": 12.5,
    "samount": 3,
    "re_attribute_info": {
        "ReAttributeAdPlatform": "demo-platform",
        "ReAttributeAdAid": "ad-safe",
    },
}; RESTORED = {
    "user_id": "user-secret",
    "event_user_id": "event-user-secret",
    "device_id": "device-secret",
    "ClientID": "client-secret",
    "TraceID": "trace-secret",
    "device_info": {field: f"value-{field}" for field in DEVICE_INFO_FIELDS},
    "user$ad_count": 99,
    "user$ad_avg_ecpm": 88,
    "user$ad_ltv": 77,
    "Name": "name-secret",
    "WXOpenID": "openid-secret",
}
DEFAULT_QUERY = normalize_monetization_query().receipt()
DEFAULT_QUERY_OPTIONS = {
    "fields": tuple(SAFE_ROW_FIELDS),
    "global_conditions": (),
    "cond_logic": "AND",
    "local_conditions": (),
    "local_cond_logic": "AND",
    "order_by": (),
    "segment_id": None,
    "tmp_segment_id": None,
}
def _read(row, *, workers=2):
    rows = [] if row is None else [copy.deepcopy(row)]
    return {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": OPERATION_ID,
        "status": "empty" if not rows else "success",
        "error": None,
        "data": {"list": rows, "total": {**RESTORED, "samount": 3}},
        "page": {
            "number": 1,
            "size": 100,
            "item_count": len(rows),
            "total_pages": 1,
            "total_items": len(rows),
            "has_more": False,
            "pages_fetched": 1,
            "fetch_strategy": "single_page",
            "max_workers": workers,
        },
    }
class Client:
    def __init__(self, value):
        self.value, self.calls = value, []

    def read_all(self, operation_id, inputs=None, **options):
        self.calls.append((operation_id, copy.deepcopy(inputs), options))
        if isinstance(self.value, BaseException):
            raise self.value
        return copy.deepcopy(self.value)
class Workspace:
    def resolve_app(self, value=None):
        if value in {7, "7", "main"}:
            return 7
        raise ValueError("unknown app")
def _product_result(*, app=7, workers=1):
    return monetization_detail(
        Client(_read(SAFE, workers=workers)), app, DAY,
        max_workers=workers, max_pages=5, max_items=10,
    )
class ProductSDK:
    workspace, insight = Workspace(), type("Insight", (), {"operations": lambda *_a, **_k: []})()

    def __init__(self, value=None):
        self.value, self.calls = value or _product_result(), []

    def monetization_detail(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return copy.deepcopy(self.value)
class MonetizationDetailTests(unittest.TestCase):
    def test_happy_path_uses_fixed_fields_and_returns_registered_identifiers(self):
        raw = {**SAFE, **RESTORED}
        client = Client(_read(raw))
        result = monetization_detail(
            client, "007", DAY, max_workers=2, max_pages=5, max_items=10
        )
        self.assertEqual(("success", "7", [raw]),
                         (result["status"], result["app_id"], result["data"]["list"]))
        self.assertEqual(DEFAULT_QUERY, result["query"])
        self.assertEqual([{**RESTORED, "samount": 3}], result["data"]["total"])
        self.assertEqual(
            "Consume the complete contracted monetization rows.",
            result["next_action"],
        )
        empty = monetization_detail(
            Client(_read(None)), "007", DAY, max_workers=2, max_pages=5, max_items=10
        )
        self.assertEqual("empty", empty["status"])
        self.assertIn("permission-profile", empty["next_action"])
        self.assertIsInstance(result["data"]["list"][0]["device_info"], dict)
        self.assertIsInstance(result["data"]["list"][0]["user$ad_ltv"], int)
        operation, inputs, options = client.calls[0]
        self.assertEqual((OPERATION_ID, list(SAFE_ROW_FIELDS), 1, 100),
                         (operation, inputs["fields"], inputs["page"], inputs["page_size"]))
        self.assertEqual(("AND", "AND"), (inputs["cond_logic"], inputs["local_cond_logic"]))
        self.assertEqual({"max_workers": 2, "max_pages": 5, "max_items": 10}, options)
        self.assertEqual(1, result["page"]["pages_fetched"])
        obligations = EnvelopeObligations.from_dict(result["obligations"])
        self.assertEqual("complete", obligations.data_completeness.state.value)
        self.assertEqual("valid", obligations.semantic_validity.state.value)
    def test_failure_envelopes_do_not_copy_exception_or_error_values(self):
        secrets = ("exception-secret", "error-secret")
        results = [
            monetization_detail(Client(RuntimeError("exception-secret")), 7, DAY, max_workers=2),
            monetization_detail(Client({
                "status": "permission_unavailable",
                "error": {"code": "PERMISSION_UNAVAILABLE", "message": "error-secret"},
            }), 7, DAY, max_workers=2),
        ]
        self.assertEqual(["error", "error"],
                         [result["status"] for result in results])
        rendered = repr(results)
        self.assertFalse(any(secret in rendered for secret in secrets))
    def test_request_bound_sanitizer_rejects_identity_receipt_and_public_extras(self):
        result = monetization_detail(
            Client(_read(SAFE, workers=1)), 7, DAY,
            max_workers=1, max_pages=5, max_items=10,
        )
        mutations = []
        for path, value in (
            (("app_id",), "8"),
            (("limits", "max_items"), 11),
            (("page", "pages_fetched"), 2),
            (("data", "list", 0, "UnregisteredField"), "public-secret"),
            (("query", "cond_logic"), "OR"),
        ):
            forged = copy.deepcopy(result)
            target = forged
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            mutations.append(forged)
        for forged in mutations:
            rebuilt = sanitize_monetization_detail_result(
                forged, 7, DAY, max_workers=1, max_pages=5, max_items=10
            )
            self.assertEqual("contract_changed", rebuilt["status"])
            self.assertNotIn("public-secret", repr(rebuilt))
    def test_raw_operation_policy_uses_metadata_and_allows_user_filters(self):
        root = Path(__file__).resolve().parents[1]
        operation = next(
            item for item in load_operation_manifest(
                root / "src" / "gravity_insight" / "manifests" / "analysis.json"
            ) if item.operation_id == OPERATION_ID
        )
        calls = []
        def loader(operation_id, inputs):
            calls.append((operation_id, inputs))
            return {"status": "empty", "data": {"list": []}}
        base = {"app_id": "7", "date": DAY, "page": 1, "page_size": 100}
        validate_analysis_detail(
            operation, {**base, "fields": list(SAFE_ROW_FIELDS)},
            loader,
        )
        self.assertEqual([], calls)
        validate_analysis_detail(
            operation, {**base, "fields": ["user_id"]}, loader,
        )
        self.assertEqual(3, len(calls))
        condition = {
            "operator": "EQUALS", "field": "user_id", "type": "default_user",
            "value": ["user-1"],
        }
        validate_analysis_detail(
            operation,
            {**base, "fields": ["user_id"], "global_conditions": [condition]},
            loader,
        )
        with self.assertRaisesRegex(ValueError, "absent from live metadata"):
            validate_analysis_detail(
                operation, {**base, "fields": ["future_user_metric"]}, loader
            )
        with self.assertRaises(ValueError):
            operation.validate_inputs(
                {**base, "fields": list(SAFE_ROW_FIELDS), "future_control": True}
            )
    def test_query_profile_binds_conditions_order_segment_and_projection(self):
        client = Client(_read(SAFE, workers=1))
        global_condition = {
            "operator": "GREATER", "field": "samount", "type": "event",
            "value": [0],
        }
        local_condition = {
            "operator": "EQUALS", "field": "AdPlatform", "type": "event",
            "value": ["demo-platform"],
        }
        result = monetization_detail(
            client, 7, DAY,
            fields=("AdEventTime", "samount"),
            global_conditions=(global_condition,), cond_logic="OR",
            local_conditions=(local_condition,), local_cond_logic="AND",
            order_by=({"field": "samount", "sort": 1},),
            segment_id="42", max_workers=1, max_pages=5, max_items=10,
        )
        inputs = client.calls[0][1]
        self.assertEqual(("42", "42"), (inputs["segment_id"], inputs["tmp_segment_id"]))
        self.assertEqual(("OR", [global_condition]),
                         (inputs["cond_logic"], inputs["global_conditions"]))
        self.assertEqual([{"AdEventTime": SAFE["AdEventTime"], "samount": 3}],
                         result["data"]["list"])
        self.assertEqual([{"samount": 3}], result["data"]["total"])
        self.assertEqual(inputs["fields"], result["query"]["fields"])

        for options in (
            {"fields": ("unknown",)},
            {"global_conditions": ({"field": "create_time"},)},
            {"tmp_segment_id": "42"},
            {"segment_id": "42", "tmp_segment_id": "43"},
        ):
            blocked = Client(_read(SAFE))
            with self.subTest(options=options), self.assertRaises(ValueError):
                monetization_detail(blocked, 7, DAY, **options)
            self.assertEqual([], blocked.calls)

    def test_wire_codec_preserves_query_controls_and_owns_the_day_boundary(self):
        global_condition = {
            "operator": "GREATER",
            "field": "samount",
            "type": "event",
            "value": [0],
        }
        local_condition = {
            "operator": "EQUALS",
            "field": "AdPlatform",
            "type": "event",
            "value": ["demo-platform"],
        }
        with patch("gravity_insight.registry.time.time", return_value=1_723_000_000.0), \
             patch("gravity_insight.registry.secrets.token_hex", return_value="a" * 20):
            query, body = _analysis_monetization_detail_request_parts({
                "app_id": "7",
                "date": DAY,
                "fields": ["AdEventTime", "samount"],
                "global_conditions": [global_condition],
                "cond_logic": "OR",
                "local_conditions": [local_condition],
                "local_cond_logic": "AND",
                "order_by_list": [{"field": "samount", "sort": 1}],
                "segment_id": "42",
                "tmp_segment_id": "42",
                "page": 2,
                "page_size": 100,
            })
        self.assertEqual({}, query)
        self.assertEqual("1723000000000" + "a" * 19, body["query_id"])
        self.assertEqual((7, 42, 42), (
            body["app_id"], body["segment_id"], body["tmp_segment_id"]
        ))
        self.assertEqual(("OR", "AND"), (
            body["cond_logic"], body["local_cond_logic"]
        ))
        self.assertEqual([local_condition], body["local_conditions"])
        self.assertEqual([{"field": "samount", "sort": 1}], body["order_by_list"])
        self.assertEqual(["AdEventTime", "samount"], body["field_map"])
        self.assertEqual(global_condition, body["global_conditions"][0])
        self.assertEqual([{
            "operator": "RANGE_IN",
            "field": "create_time",
            "type": "event",
            "value": [f"{DAY} 00:00:00", f"{DAY} 23:59:59"],
        }], [
            item for item in body["global_conditions"]
            if item.get("field") == "create_time"
        ])

    def test_field_policy_validates_same_app_segment_and_rejects_time_override(self):
        root = Path(__file__).resolve().parents[1]
        operation = next(
            item for item in load_operation_manifest(
                root / "src" / "gravity_insight" / "manifests" / "analysis.json"
            ) if item.operation_id == OPERATION_ID
        )
        def loader(operation_id, _inputs):
            rows = [{"segment_id": 42}] if operation_id == "analysis.segment.list" else []
            return {"status": "success" if rows else "empty", "data": {"list": rows}}
        base = {
            "app_id": "7", "date": DAY, "fields": list(SAFE_ROW_FIELDS),
            "page": 1, "page_size": 100,
            "segment_id": "42", "tmp_segment_id": "42",
        }
        validate_analysis_detail(operation, base, loader)
        with self.assertRaisesRegex(ValueError, "absent from live metadata"):
            validate_analysis_detail(
                operation, {**base, "segment_id": "43", "tmp_segment_id": "43"}, loader
            )
        with self.assertRaisesRegex(ValueError, "cannot contain create_time"):
            validate_analysis_detail(
                operation,
                {**base, "global_conditions": [{
                    "operator": "RANGE_IN", "field": "create_time",
                    "type": "event", "value": [DAY, DAY],
                }]},
                loader,
            )
    def test_cli_sdk_and_plan_share_one_preflighted_product(self):
        base = [
            "analysis", "monetization", "detail", "--app", "main",
            "--date", DAY, "--max-pages", "5", "--max-items", "10",
        ]
        parser = cli.build_parser()
        selected = parser.parse_args(base)
        self.assertEqual(("monetization", "detail", 6), (
            selected.analysis_command, selected.monetization_command,
            selected.concurrency,
        ))
        invalid = [*base]
        invalid[6] = "bad"
        with patch("gravity_insight.monetization_detail_cli.load_workspace", return_value=Workspace()), \
             patch("gravity_insight.monetization_detail_cli.runtime.build_client") as factory:
            self.assertTrue(command_requires_credentials(base, cli.build_parser))
            self.assertFalse(command_requires_credentials(invalid, cli.build_parser))
            with self.assertRaises(ValueError):
                args = parser.parse_args(invalid)
                args._gravity_handler(args, lambda _value: {})
        factory.assert_not_called()
        client = object()
        with patch("gravity_insight.monetization_detail_cli.load_workspace", return_value=Workspace()), \
             patch("gravity_insight.monetization_detail_cli.runtime.build_client", return_value=client), \
             patch("gravity_insight.monetization_detail.monetization_detail", return_value=_product_result()) as core:
            selected._gravity_handler(selected, lambda _value: {})
        core.assert_called_once_with(
            client, "7", DAY, **DEFAULT_QUERY_OPTIONS,
            max_workers=6, max_pages=5, max_items=10
        )
        lazy = Mock(return_value=client)
        sdk = GravitySDK(insight_factory=lazy, workspace=Workspace())
        with self.assertRaises(ValueError):
            sdk.monetization_detail("main", "bad")
        lazy.assert_not_called()
        with patch("gravity_insight.monetization_detail.monetization_detail", return_value=_product_result()) as core:
            sdk.monetization_detail("main", DAY, max_pages=5, max_items=10)
        core.assert_called_once_with(
            client, "7", DAY, **DEFAULT_QUERY_OPTIONS,
            max_workers=6, max_pages=5, max_items=10
        )
        self.assertLessEqual(
            {"monetization_detail", "validate_monetization_detail_request"},
            set(gravity_insight.__all__),
        )
    def test_plan_is_request_bound_serial_and_dry_run_safe(self):
        request = {"name": "monetization_detail", "app": "main", "date": DAY}
        context = AdapterContext(
            "detail", "detail", "composite", Workspace(), ("data",), (), 5, 10
        )
        sdk = ProductSDK()
        adapter = build_plan_adapters(sdk).composite
        safe = adapter.execute(request, context)
        self.assertEqual(("7", 1), (safe["app_id"], sdk.calls[0][1]["max_workers"]))
        projected = adapter.project(safe, ("data",), context)
        self.assertEqual([SAFE], projected["data"]["list"])
        forged = _product_result(app=8)
        failed = build_plan_adapters(ProductSDK(forged)).composite.execute(request, context)
        self.assertEqual(("contract_changed", []),
                         (failed["status"], failed["data"]["list"]))
        plan = {"schema_version": "gravity.plan.v1", "nodes": [{
            "id": "detail", "kind": "composite", "request": request,
            "limits": {"max_pages": 5, "max_items": 10},
        }]}
        dry_sdk = ProductSDK()
        receipt = execute_plan(
            plan, adapters={"composite": build_plan_adapters(dry_sdk).composite},
            workspace=Workspace(), dry_run=True,
        )
        self.assertEqual(("validated", []), (receipt["status"], dry_sdk.calls))
if __name__ == "__main__":
    unittest.main()
