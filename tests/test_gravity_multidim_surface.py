from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gravity_sdk import GravitySDK, InputValidationError
from gravity_sdk.errors import PaginationError
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_multidim_adapter import (
    execute_multidim_plan,
    multidim_result_item_count,
)


PRODUCT_INPUT = {
    "date_list": ["2026-08-01", "2026-08-02"],
    "time_dims": "day",
    "metrics_list": ["cost"],
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
            "validation": {"status": "not_required", "metadata_operations": []},
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
                    SDK(), {"name": "multidim", "app": "main", "inputs": PRODUCT_INPUT}, context
                )
            safe = execute_multidim_plan(
                SDK(), {"name": "multidim", "app": "main", "inputs": PRODUCT_INPUT},
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
            "validation": {"status": "not_required", "metadata_operations": []},
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
                SDK(), {"name": "multidim", "app": "main", "inputs": PRODUCT_INPUT}, context
            )
        self.assertFalse(safe["ok"])
        self.assertNotIn("token=secret", repr(safe))
        self.assertNotIn("C:/private", repr(safe))
        self.assertNotIn("data", safe["query"])


if __name__ == "__main__":
    unittest.main()
