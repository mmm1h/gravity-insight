from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gravity_sdk import GravitySDK, InputValidationError
from gravity_sdk.composite_result import multidim_envelope
from gravity_sdk.errors import ContractChangedError, PaginationError
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_multidim_adapter import (
    execute_multidim_plan,
    multidim_result_item_count,
    validate_multidim_plan,
)
from gravity_sdk.plan_multidim_result import sanitize_multidim_result


PRODUCT_INPUT = {
    "date_list": ["2026-08-01", "2026-08-02"],
    "time_dims": "day",
    "metrics_list": ["cost"],
}
PRODUCT_REQUEST = {
    "name": "multidim",
    "input_schema_version": "gravity-insight.multidim-input.v1",
    "app": "main",
    "inputs": PRODUCT_INPUT,
}
VALIDATION = {
    "status": "not_required",
    "metrics": "not_requested",
    "data_dims": "not_validated_without_selected_metrics",
    "metadata_operations": [],
}


class _Workspace:
    def resolve_app(self, value):
        if value in {"main", 17, "17"}:
            return 17
        raise ValueError("unknown private alias")


class MultidimSurfaceTests(unittest.TestCase):
    def test_sdk_preflight_stays_lazy_and_validates_bounds_before_factory(self):
        built = []
        sdk = GravitySDK(
            insight_factory=lambda: built.append(True), workspace=_Workspace()
        )
        with patch(
            "gravity_sdk.multidim_product.prepare_multidim_query",
            return_value={"ok": True, "network_called": False},
        ) as prepare:
            result = sdk.prepare_multidim_query(PRODUCT_INPUT, app="main")
        self.assertEqual((True, []), (result["ok"], built))
        self.assertEqual(17, prepare.call_args.kwargs["app_id"])
        with self.assertRaises(InputValidationError):
            sdk.multidim_query(PRODUCT_INPUT, app="main", max_workers=25)
        self.assertEqual([], built)

    def test_cli_product_offline_modes_never_build_client(self):
        from gravity_sdk import cli

        workspace = _Workspace()
        with (
            patch("gravity_sdk.multidim_cli.load_workspace", return_value=workspace),
            patch("gravity_sdk.multidim_cli.runtime.build_client") as build,
        ):
            args = cli.build_parser().parse_args([
                "multidim", "query", "--app", "main", "--input",
                '{"date_list":["2026-08-01","2026-08-02"],"time_dims":"day","metrics_list":[]}',
                "--all-pages", "--dry-run",
            ])
            preview = getattr(args, "_gravity_handler")(args, cli._object_input)
            schema_args = cli.build_parser().parse_args(
                ["multidim", "query", "--input-schema"]
            )
            schema = getattr(schema_args, "_gravity_handler")(
                schema_args, cli._object_input
            )
            invalid = cli.build_parser().parse_args([
                "multidim", "query", "--app", "main", "--input",
                '{"date_list":["2026-08-01","2026-08-02"],"time_dims":"day","metrics_list":[]}',
                "--max-items", "100001",
            ])
            with self.assertRaises(InputValidationError):
                getattr(invalid, "_gravity_handler")(invalid, cli._object_input)
            for argv in (
                ["multidim", "query", "--input", '{}', "--dry-run"],
                ["--dry-run", "multidim", "query", "--app", "main", "--input", '{}'],
            ):
                with self.subTest(argv=argv), self.assertRaises(InputValidationError):
                    selected = cli.build_parser().parse_args(argv)
                    getattr(selected, "_gravity_handler")(selected, cli._object_input)
        self.assertFalse(preview["network_called"])
        self.assertEqual("gravity-insight.multidim-input.v1", schema["schema_version"])
        build.assert_not_called()

    def test_onboarding_requires_a_locally_complete_product_request(self):
        from gravity_sdk import cli
        from gravity_sdk.onboarding import command_requires_credentials

        encoded = (
            '{"date_list":["2026-08-01","2026-08-02"],'
            '"time_dims":"day","metrics_list":[]}'
        )
        base = ["multidim", "query", "--app", "main", "--input", encoded]
        with patch("gravity_sdk.workspace.load_workspace", return_value=_Workspace()):
            self.assertTrue(command_requires_credentials(base, cli.build_parser))
            self.assertFalse(command_requires_credentials(
                [*base[:3], "missing", *base[4:]], cli.build_parser
            ))
            self.assertFalse(command_requires_credentials(
                [*base[:-1], '{}'], cli.build_parser
            ))
            self.assertFalse(command_requires_credentials(
                [*base, "--max-pages", "1001"], cli.build_parser
            ))
            self.assertFalse(command_requires_credentials(
                [*base, "--all-pages"], cli.build_parser
            ))
            self.assertFalse(command_requires_credentials(
                [*base, "--dry-run"], cli.build_parser
            ))
            self.assertFalse(command_requires_credentials(
                ["multidim", "query", "--input-schema"], cli.build_parser
            ))

    def test_plan_projection_counts_actual_rows_and_strips_continuations(self):
        rows = [{"day": f"2026-08-{(index % 28) + 1:02d}"} for index in range(201)]
        native = {
            "schema_version": "gravity-insight.composite.multidim.v1",
            "ok": True,
            "status": "success",
            "exit_code": 0,
            "app_id": "17",
            "network_called": True,
            "query_executed": True,
            "input_schema_version": "gravity-insight.multidim-input.v1",
            "validation": VALIDATION,
            "query": {
                "operation_id": "report.multidim.query",
                "ok": True,
                "status": "success",
                "data": {"list": rows},
                "page": {"item_count": 0},
                "next_page_input": {"filters": ["token=secret"]},
            },
            "total": None,
        }

        class Insight:
            pass

        class SDK:
            insight = Insight()

        context = AdapterContext(
            node_id="q", execution_id="q", kind="composite",
            workspace=_Workspace(), output_fields=(), dynamic_targets=(),
            max_pages=2, max_items=200,
        )
        with patch(
            "gravity_sdk.multidim_product.run_multidim_query", return_value=native
        ) as run:
            with self.assertRaises(PaginationError):
                execute_multidim_plan(
                    SDK(), PRODUCT_REQUEST, context
                )
            safe = execute_multidim_plan(
                SDK(), PRODUCT_REQUEST,
                AdapterContext(**{**context.__dict__, "max_items": 201}),
            )
        self.assertEqual(1, run.call_args.kwargs["max_workers"])
        self.assertEqual(201, multidim_result_item_count(native))
        self.assertNotIn("next_page_input", repr(safe))
        self.assertNotIn("token=secret", repr(safe))

    def test_plan_failure_drops_raw_error_paths_and_values(self):
        native = {
            "schema_version": "gravity-insight.composite.multidim.v1",
            "ok": False,
            "status": "error",
            "exit_code": 3,
            "app_id": "17",
            "network_called": True,
            "query_executed": True,
            "input_schema_version": "gravity-insight.multidim-input.v1",
            "validation": VALIDATION,
            "error": {
                "code": "UPSTREAM_UNAVAILABLE", "category": "upstream",
                "message": "token=secret", "field": "C:/private/request.json", "stage": "query",
            },
            "query": {
                "ok": False, "status": "error", "data": {"list": ["secret"]},
                "error": {"code": "UPSTREAM_UNAVAILABLE", "message": "token=secret"},
            },
            "total": None,
        }

        class SDK:
            insight = object()

        context = AdapterContext(
            node_id="q", execution_id="q", kind="composite",
            workspace=_Workspace(), output_fields=(), dynamic_targets=(),
            max_pages=1, max_items=10,
        )
        with patch(
            "gravity_sdk.multidim_product.run_multidim_query", return_value=native
        ):
            safe = execute_multidim_plan(
                SDK(), PRODUCT_REQUEST, context
            )
        self.assertFalse(safe["ok"])
        self.assertNotIn("token=secret", repr(safe))
        self.assertNotIn("C:/private", repr(safe))
        self.assertNotIn("data", safe["query"])

    def test_multidim_ndjson_streams_each_query_row(self):
        from gravity_sdk import cli

        rows = [{"day": index} for index in range(201)]
        envelope = {
            "schema_version": "gravity-insight.composite.multidim.v1",
            "status": "partial",
            "query": {
                "operation_id": "report.multidim.query",
                "status": "success",
                "truncated": True,
                "page": {"total_items": 201},
                "data": {"list": rows},
            },
            "total": {"operation_id": "report.multidim.calc_total", "status": "error"},
        }
        streamed, metadata = cli._ndjson_rows(envelope)
        self.assertEqual(rows, streamed)
        self.assertEqual(
            (201, "report.multidim.query", "partial", True, 201),
            (
                metadata["rows_written"], metadata["operation_id"], metadata["status"],
                metadata["truncated"], metadata["total"],
            ),
        )
        generic = {
            "operation_id": "example.list",
            "status": "success",
            "data": {"list": [{"safe": True}]},
            "next_page_input": {"nested": {"authorization": "Bearer secret"}},
        }
        rendered_metadata = list(cli._iter_ndjson_lines(generic))[-1]
        self.assertNotIn("secret", rendered_metadata)
        self.assertNotIn(
            "authorization", json.loads(rendered_metadata)["_gravity_insight"]["next_page_input"]["nested"]
        )

    def test_multidim_structured_error_category_is_normalized(self):
        for category in ([], {}):
            with self.subTest(category=category):
                result = multidim_envelope(
                    VALIDATION,
                    {
                        "operation_id": "report.multidim.query",
                        "ok": False,
                        "status": "error",
                        "error": {
                            "code": "UPSTREAM_UNAVAILABLE",
                            "category": category,
                        },
                    },
                    None,
                    query_operation="report.multidim.query",
                    total_operation="report.multidim.calc_total",
                )
                self.assertEqual("upstream", result["error"]["category"])

    def test_plan_projector_rejects_top_success_with_failed_component(self):
        native = {
            "schema_version": "gravity-insight.composite.multidim.v1",
            "ok": True, "status": "success", "exit_code": 0, "app_id": "17",
            "network_called": True, "query_executed": True,
            "input_schema_version": "gravity-insight.multidim-input.v1",
            "validation": VALIDATION,
            "query": {
                "operation_id": "report.multidim.query", "ok": True,
                "status": "success", "data": {"list": []},
            },
            "total": None,
        }
        failures = {
            "query": {
                "operation_id": "report.multidim.query", "ok": False,
                "status": "error", "error": {"code": "UPSTREAM_UNAVAILABLE"},
            },
            "total": {
                "operation_id": "report.multidim.calc_total", "ok": False,
                "status": "error", "error": {"code": "UPSTREAM_UNAVAILABLE"},
            },
        }
        for field, component in failures.items():
            with self.subTest(field=field), self.assertRaises(ContractChangedError):
                selected = copy.deepcopy(native)
                selected[field] = component
                sanitize_multidim_result(selected, "17")

    def test_plan_product_marker_preserves_legacy_and_rejects_nonscalar_bindings(self):
        class Insight:
            supplied = None

            def schema(self, _operation_id):
                return {"input_fields": {
                    "time_dims": {"type": "string", "enum": ["day"]},
                    "date_list": {"type": "array"},
                    "metrics_list": {"type": "array"},
                    "filters": {"type": "array"},
                }}

            def validate(self, _operation_id, inputs):
                self.supplied = inputs
                return {"ok": True}

        insight = Insight()
        base = AdapterContext(
            node_id="q", execution_id="q", kind="composite", workspace=_Workspace(),
            output_fields=(), dynamic_targets=(), max_pages=1, max_items=10,
        )
        legacy = {"name": "multidim", "app": "main", "inputs": {
            **PRODUCT_INPUT,
            "filters": [{"field": "legacy", "operator": 8, "values": [1]}],
        }}
        validate_multidim_plan(insight, _Workspace(), legacy, base)
        self.assertEqual(8, insight.supplied["filters"][0]["operator"])
        with self.assertRaises(InputValidationError):
            validate_multidim_plan(
                insight, _Workspace(), PRODUCT_REQUEST,
                AdapterContext(**{**base.__dict__, "dynamic_targets": ("/inputs/date_list",)}),
            )
        with self.assertRaises(InputValidationError):
            validate_multidim_plan(
                insight, _Workspace(), {key: value for key, value in PRODUCT_REQUEST.items() if key != "app"}, base
            )
        validate_multidim_plan(
            insight, _Workspace(), PRODUCT_REQUEST,
            AdapterContext(**{**base.__dict__, "dynamic_targets": ("/inputs/time_dims",)}),
        )

    def test_plan_projector_fails_closed_on_discriminator_drift(self):
        native = {
            "schema_version": "gravity-insight.composite.multidim.v1",
            "ok": True, "status": "success", "exit_code": 0, "app_id": "17",
            "network_called": True, "query_executed": True,
            "input_schema_version": "gravity-insight.multidim-input.v1",
            "validation": VALIDATION,
            "query": {
                "operation_id": "report.multidim.query", "ok": True,
                "status": "success", "data": {"list": [{"day": "2026-08-01"}]},
            },
            "total": None,
        }
        mutations = (
            ("operation_id", []),
            ("validation.status", []),
            ("validation.metadata_operations", [{}]),
            ("query.operation_id", []),
        )
        for path, value in mutations:
            with self.subTest(path=path):
                selected = copy.deepcopy(native)
                target, key = (selected, path) if "." not in path else (selected[path.split('.')[0]], path.split('.')[1])
                target[key] = value
                with self.assertRaises(ContractChangedError):
                    sanitize_multidim_result(selected, "17")


if __name__ == "__main__":
    unittest.main()
