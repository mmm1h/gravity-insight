from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk.errors import InputValidationError
from gravity_sdk.plan import AdapterContext


class _Workspace:
    def __init__(self) -> None:
        self.recipes = {}
        self.products = {}

    def recipe(self, name):
        if name not in self.recipes:
            raise KeyError(name)
        return self.recipes[name]

    def product(self, name):
        if name not in self.products:
            raise KeyError(name)
        return self.products[name]

    def resolve_app(self, _value):
        return 17


class _Insight:
    def __init__(self) -> None:
        self.input_schema = {}
        self.validation = {"ok": True}

    def operations(self, **_options):
        return [{"operation_id": "stable.operation"}]

    def describe(self, _operation_id):
        return {"input_schema": self.input_schema}

    def validate(self, _operation_id, _inputs):
        return self.validation


def _context(
    workspace=None,
    *,
    dynamic=(),
    fields=(),
    max_pages=5,
    max_items=10,
):
    return AdapterContext(
        node_id="node",
        execution_id="node",
        kind="composite",
        workspace=workspace or _Workspace(),
        output_fields=tuple(fields),
        dynamic_targets=tuple(dynamic),
        max_pages=max_pages,
        max_items=max_items,
    )


def _caught(call):
    try:
        call()
    except InputValidationError as error:
        return str(error)
    raise AssertionError("expected InputValidationError")


class PlanErrorActualRound2Tests(unittest.TestCase):
    def test_key_list_summaries_cover_request_shapes(self):
        from gravity_sdk.plan_advertiser_profile_adapter import (
            validate_advertiser_profile_plan,
        )
        from gravity_sdk.plan_bilibili_account_performance_adapter import (
            validate_bilibili_account_performance_plan,
        )
        from gravity_sdk.plan_material_performance_adapter import (
            validate_material_performance_plan,
        )
        from gravity_sdk.plan_promotion_performance_adapter import (
            validate_promotion_performance_plan,
        )
        from gravity_sdk.plan_pulse_adapter import validate_business_pulse
        from gravity_sdk.plan_receipt_adapter import validate_receipt_query
        from gravity_sdk.plan_validation import validate_plan

        secret = "business-value-must-not-spread"
        cases = {
            "advertiser": lambda: validate_advertiser_profile_plan(
                {"name": "advertiser_profile", "start": "2026-08-01", "end": "2026-08-02", "unexpected": secret},
                _context(),
                frozenset(),
            ),
            "bilibili": lambda: validate_bilibili_account_performance_plan(
                {"name": "bilibili_account_performance", "start": "2026-08-01", "end": "2026-08-02", "unexpected": secret},
                _context(),
                object(),
            ),
            "material": lambda: validate_material_performance_plan(
                {"name": "material_performance", "unexpected": secret},
                _context(),
                _Workspace(),
            ),
            "promotion": lambda: validate_promotion_performance_plan(
                {"name": "promotion_performance", "unexpected": secret},
                _context(),
                _Workspace(),
            ),
            "pulse": lambda: validate_business_pulse(
                {"name": "business_pulse", "unexpected": secret},
                _context(),
                _Workspace(),
                frozenset(),
            ),
            "receipt": lambda: validate_receipt_query(
                {"action": "list", "unexpected": secret}, _context()
            ),
            "plan": lambda: validate_plan(
                {
                    "schema_version": "gravity.plan.v1",
                    "nodes": [
                        {
                            "id": "node",
                            "kind": "run",
                            "request": {"workspace": secret},
                        }
                    ],
                }
            ),
        }
        for label, call in cases.items():
            with self.subTest(label=label):
                rendered = _caught(call)
                self.assertIn("actual value:", rendered)
                self.assertIn("unexpected" if label != "plan" else "workspace", rendered)
                self.assertNotIn(secret, rendered)

    def test_name_and_enum_summaries_cover_adapter_families(self):
        from gravity_sdk.plan_adapters import build_plan_adapters
        from gravity_sdk.plan_analysis_adapter import validate_analysis_query_plan
        from gravity_sdk.plan_bilibili_account_performance_adapter import (
            validate_bilibili_account_performance_plan,
        )
        from gravity_sdk.plan_dashboard_analysis_adapter import (
            validate_dashboard_analysis_plan,
        )
        from gravity_sdk.plan_dashboard_snapshot_adapter import (
            validate_dashboard_snapshot_plan,
        )
        from gravity_sdk.plan_material_performance_adapter import (
            validate_material_performance_plan,
        )
        from gravity_sdk.plan_multidim_adapter import validate_multidim_plan
        from gravity_sdk.plan_promotion_performance_adapter import (
            validate_promotion_performance_plan,
        )
        from gravity_sdk.plan_segment_adapter import validate_segment_evaluate_plan
        from gravity_sdk.plan_segment_members_adapter import (
            validate_segment_members_plan,
        )
        from gravity_sdk.plan_segment_snapshot_adapter import (
            validate_segment_snapshot_plan,
        )

        workspace, insight = _Workspace(), _Insight()
        sdk = SimpleNamespace(workspace=workspace, insight=insight)
        wrong = "wrong_composite"
        cases = {
            "central": lambda: build_plan_adapters(sdk).composite.validate(
                {"name": wrong}, _context(workspace)
            ),
            "analysis": lambda: validate_analysis_query_plan(
                insight, workspace, {"name": wrong}, _context(workspace)
            ),
            "bilibili": lambda: validate_bilibili_account_performance_plan(
                {"name": wrong, "start": "2026-08-01", "end": "2026-08-02"},
                _context(workspace),
                workspace,
            ),
            "dashboard_analysis": lambda: validate_dashboard_analysis_plan(
                {"name": wrong}, _context(workspace), workspace
            ),
            "dashboard_snapshot": lambda: validate_dashboard_snapshot_plan(
                {"name": wrong}, _context(workspace), workspace
            ),
            "material": lambda: validate_material_performance_plan(
                {"name": wrong}, _context(workspace), workspace
            ),
            "multidim": lambda: validate_multidim_plan(
                insight, workspace, {"name": wrong}, _context(workspace)
            ),
            "promotion": lambda: validate_promotion_performance_plan(
                {"name": wrong}, _context(workspace), workspace
            ),
            "segment": lambda: validate_segment_evaluate_plan(
                insight, workspace, {"name": wrong}, _context(workspace)
            ),
            "segment_members": lambda: validate_segment_members_plan(
                {"name": wrong}, _context(workspace), workspace
            ),
            "segment_snapshot": lambda: validate_segment_snapshot_plan(
                {"name": wrong}, _context(workspace), workspace
            ),
        }
        for label, call in cases.items():
            with self.subTest(label=label):
                self.assertIn(f'actual value: "{wrong}"', _caught(call))

    def test_count_and_limit_summaries_are_value_free(self):
        from gravity_sdk.plan_dashboard_analysis_adapter import (
            validate_dashboard_analysis_plan,
        )
        from gravity_sdk.plan_dashboard_snapshot_adapter import (
            validate_dashboard_snapshot_plan,
        )
        from gravity_sdk.plan_material_performance_adapter import (
            validate_material_performance_plan,
        )
        from gravity_sdk.plan_pulse_adapter import validate_business_pulse
        from gravity_sdk.plan_receipt_adapter import validate_receipt_query
        from gravity_sdk.plan_segment_snapshot_adapter import (
            validate_segment_snapshot_plan,
        )
        from gravity_sdk.plan_validation import MAX_DECLARED_NODES, validate_plan

        workspace = _Workspace()
        cases = {
            "dashboard_analysis": (
                lambda: validate_dashboard_analysis_plan(
                    {"name": "dashboard_analysis", "ref": "dashboard", "start": "2026-08-01", "end": "2026-08-02"},
                    _context(workspace, dynamic=("/app",), max_items=2),
                    workspace,
                ),
                "[2,3]",
            ),
            "dashboard_snapshot": (
                lambda: validate_dashboard_snapshot_plan(
                    {"name": "dashboard_snapshot"},
                    _context(workspace, dynamic=("/app", "/ref"), max_items=1),
                    workspace,
                ),
                "[1,7]",
            ),
            "material": (
                lambda: validate_material_performance_plan(
                    {"name": "material_performance", "apps": ["main"], "start": "2026-08-01", "end": "2026-08-02", "platforms": ["tencent"]},
                    _context(workspace, max_items=0),
                    workspace,
                ),
                "[1,0]",
            ),
            "pulse": (
                lambda: validate_business_pulse(
                    {"apps": ["main"], "start": "2026-08-01", "end": "2026-08-02", "platforms": ["bytedance"]},
                    _context(workspace, max_items=1),
                    workspace,
                    frozenset(),
                ),
                "[2,1]",
            ),
            "receipt": (
                lambda: validate_receipt_query(
                    {"action": "list", "limit": 3},
                    _context(workspace, max_items=2),
                ),
                "[3,2]",
            ),
            "segment_snapshot": (
                lambda: validate_segment_snapshot_plan(
                    {"name": "segment_snapshot", "ref": 8, "date": "2026-08-01"},
                    _context(workspace, dynamic=("/app",), max_items=1),
                    workspace,
                ),
                "[1,4]",
            ),
            "declared_nodes": (
                lambda: validate_plan(
                    {
                        "schema_version": "gravity.plan.v1",
                        "nodes": [{}] * (MAX_DECLARED_NODES + 1),
                    }
                ),
                f"[{MAX_DECLARED_NODES + 1},{MAX_DECLARED_NODES}]",
            ),
        }
        for label, (call, expected) in cases.items():
            with self.subTest(label=label):
                self.assertIn(f"actual value: {expected}", _caught(call))

    def test_result_type_summaries_do_not_echo_payloads(self):
        from gravity_sdk.plan_analysis_adapter import safe_analysis_envelope
        from gravity_sdk.plan_segment_adapter import safe_segment_envelope

        secret = "raw-result-must-not-spread"
        for label, call in {
            "analysis": lambda: safe_analysis_envelope(secret),
            "segment": lambda: safe_segment_envelope(secret),
        }.items():
            with self.subTest(label=label):
                rendered = _caught(call)
                self.assertIn('actual value: "str"', rendered)
                self.assertNotIn(secret, rendered)

    def test_run_sql_cli_and_shape_summaries_are_structural(self):
        from gravity_sdk.plan_adapters import build_plan_adapters
        from gravity_sdk.plan_multidim_adapter import _product_schema
        from gravity_sdk.plan_promotion_performance_adapter import _literal_metrics
        from gravity_sdk.plan_pulse_adapter import validate_business_pulse
        from gravity_sdk.read_cli import dispatch

        workspace, insight = _Workspace(), _Insight()
        sdk = SimpleNamespace(workspace=workspace, insight=insight)
        adapters = build_plan_adapters(sdk)
        secret = "private-business-name"

        insight.input_schema = []
        self.assertIn(
            'actual value: "list"',
            _caught(lambda: adapters.run.validate({"selector": "stable.operation"}, _context(workspace))),
        )

        insight.input_schema = {"field": {"type": "string"}}
        insight.validation = {"ok": False, "reason": secret}
        rendered = _caught(
            lambda: adapters.run.validate(
                {"selector": "stable.operation", "inputs": {"field": secret}},
                _context(workspace),
            )
        )
        self.assertIn("actual value: false", rendered)
        self.assertNotIn(secret, rendered)

        cases = (
            (
                lambda: adapters.run.validate(
                    {"selector": "stable.operation"},
                    _context(workspace, dynamic=("/private-target",)),
                ),
                'actual value: "/private-target"',
                None,
            ),
            (
                lambda: adapters.run.validate(
                    {"selector": f"@{secret}"}, _context(workspace)
                ),
                'actual value: {"configured":false,"kind":"recipe"}',
                secret,
            ),
            (
                lambda: adapters.run.validate(
                    {"selector": "unstable.operation"}, _context(workspace)
                ),
                'actual value: "unstable.operation"',
                None,
            ),
            (
                lambda: adapters.run.validate(
                    {"selector": "stable.operation", "parameters": {"region": secret}},
                    _context(workspace),
                ),
                'actual value: ["region"]',
                secret,
            ),
        )
        for call, expected, forbidden in cases:
            with self.subTest(expected=expected):
                rendered = _caught(call)
                self.assertIn(expected, rendered)
                if forbidden:
                    self.assertNotIn(forbidden, rendered)

        workspace.recipes["declared"] = SimpleNamespace(
            operation="stable.operation",
            parameters={"declared": "field"},
            required_parameters={"needed"},
        )
        for parameters, expected in (
            ({"extra": secret, "needed": secret}, '["extra"]'),
            ({}, '["needed"]'),
        ):
            with self.subTest(parameters=parameters):
                rendered = _caught(
                    lambda parameters=parameters: adapters.run.validate(
                        {"selector": "@declared", "parameters": parameters},
                        _context(workspace),
                    )
                )
                self.assertIn(f"actual value: {expected}", rendered)
                self.assertNotIn(secret, rendered)

        missing_product = _caught(
            lambda: adapters.sql_product.validate(
                {"product": secret, "start": "2026-08-01", "end": "2026-08-02"},
                _context(workspace),
            )
        )
        self.assertIn('actual value: {"configured":false}', missing_product)
        self.assertNotIn(secret, missing_product)

        workspace.products["known"] = {"max_rows": 8, "output_fields": []}
        sql_cases = (
            (
                {"product": "known", "start": "2026-08-01", "end": "2026-08-02"},
                _context(workspace, max_items=3),
                "[8,3]",
                None,
            ),
            (
                {"product": "known", "start": "2026-08-01", "end": "2026-08-02", "app_id": 1, "app_ids": [1]},
                _context(workspace, max_items=10),
                '["app_id","app_ids"]',
                None,
            ),
            (
                {"product": "known", "start": "2026-08-01", "end": "2026-08-02", "app_ids": secret},
                _context(workspace, max_items=10),
                '"str"',
                secret,
            ),
        )
        for request, context, expected, forbidden in sql_cases:
            with self.subTest(request_fields=tuple(request)):
                rendered = _caught(lambda request=request, context=context: adapters.sql_product.validate(request, context))
                self.assertIn(f"actual value: {expected}", rendered)
                if forbidden:
                    self.assertNotIn(forbidden, rendered)

        with patch(
            "gravity_sdk.multidim_product.multidim_input_schema",
            return_value={"properties": []},
        ):
            self.assertIn('actual value: "list"', _caught(_product_schema))
        metric_shape = _caught(lambda: _literal_metrics([secret + " metric"]))
        self.assertIn('actual value: {"count":1,"item_types":["str"]}', metric_shape)
        self.assertNotIn(secret, metric_shape)
        self.assertIn(
            'actual value: ["unknown-platform"]',
            _caught(
                lambda: validate_business_pulse(
                    {"apps": ["main"], "start": "2026-08-01", "end": "2026-08-02", "platforms": ["unknown-platform"]},
                    _context(workspace),
                    workspace,
                    frozenset(),
                )
            ),
        )

        args = SimpleNamespace(
            all_pages=False,
            limit=10,
            max_items=20,
        )
        self.assertIn(
            'actual value: ["--limit","--max-items"]',
            _caught(lambda: dispatch(args, lambda _value: {})),
        )


if __name__ == "__main__":
    unittest.main()
