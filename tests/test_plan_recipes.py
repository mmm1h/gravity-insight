from __future__ import annotations

import copy
import io
import json
import os
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from gravity_sdk import cli
from gravity_sdk.cli import build_parser
from gravity_sdk.plan import PlanAdapter, PlanAdapters, execute_plan
from gravity_sdk.plan_cli import run_plan_command
from gravity_sdk.sdk import GravitySDK
from gravity_sdk.workspace import load_workspace
from gravity_sdk.workspace_plan_recipe import PlanRecipeError, expand_plan_recipe


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "workspace" / "gravity.toml"


def _adapter(calls: list[dict]) -> PlanAdapter:
    return PlanAdapter(
        validate=lambda request, context: None,
        execute=lambda request, context: calls.append(copy.deepcopy(request)) or {
            "ok": True, "status": "success", "rows": [],
        },
    )


class PlanRecipeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = load_workspace(EXAMPLE, environ={})
        self.recipe = self.workspace.plan_recipe("demo-order-window")
        self.parameters = {"date": "2026-08-14", "app": "demo"}

    def test_example_expands_typed_parameters_to_every_declared_request(self) -> None:
        expanded = expand_plan_recipe(self.recipe, self.parameters)

        self.assertEqual(("demo-order-window",), self.workspace.plan_recipe_names)
        self.assertEqual(2, len(expanded["nodes"]))
        self.assertTrue(all(
            node["request"]["date"] == "2026-08-14"
            and node["request"]["app"] == "demo"
            for node in expanded["nodes"]
        ))
        self.assertEqual(
            {"type": "string", "format": "date", "required": True,
             "bindings": ["/nodes/0/request/date", "/nodes/1/request/date"]},
            self.recipe.parameter_contract()["date"],
        )
        self.assertNotIn("format", self.recipe.parameter_contract()["app"])

    def test_missing_type_and_nonexistent_path_fail_locally_before_execution(self) -> None:
        invalid_parameters = ({"app": "demo"}, {"date": 7, "app": "demo"})
        for parameters in invalid_parameters:
            with self.subTest(parameters=parameters), self.assertRaises(PlanRecipeError) as raised:
                expand_plan_recipe(self.recipe, parameters)
            self.assertEqual("local", raised.exception.category.value)

        with TemporaryDirectory() as directory:
            broken = Path(directory) / "gravity.toml"
            broken.write_text(
                EXAMPLE.read_text(encoding="utf-8").replace(
                    "/nodes/1/request/date", "/nodes/1/request/missing"
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(PlanRecipeError, "path does not exist") as raised:
                load_workspace(broken, environ={})
            stderr = io.StringIO()
            with mock.patch.dict(
                os.environ, {"GRAVITY_WORKSPACE": str(broken)}
            ), mock.patch("gravity_sdk.sdk.GravitySDK.from_env") as factory, redirect_stderr(stderr):
                exit_code = cli.main([
                    "plan", "run", "--recipe", "demo-order-window",
                    "--param", "date=2026-08-14", "--param", "app=demo", "--dry-run",
                ])
            detail = json.loads(stderr.getvalue())["error"]
            self.assertEqual((4, "PLAN_RECIPE_INVALID", "local"), (
                exit_code, detail["code"], detail["category"],
            ))
            factory.assert_not_called()
        self.assertEqual("local", raised.exception.category.value)

    def test_cli_parameter_errors_exit_four_before_sdk_construction(self) -> None:
        cases = (
            ["--param", "app=demo"],
            ["--param", "date=2026-08-14", "--param", "app=7"],
        )
        for parameters in cases:
            stderr = io.StringIO()
            with self.subTest(parameters=parameters), mock.patch.dict(
                os.environ, {"GRAVITY_WORKSPACE": str(EXAMPLE)}
            ), mock.patch("gravity_sdk.sdk.GravitySDK.from_env") as factory, redirect_stderr(stderr):
                exit_code = cli.main([
                    "plan", "run", "--recipe", "demo-order-window",
                    *parameters, "--dry-run",
                ])
            detail = json.loads(stderr.getvalue())["error"]
            self.assertEqual((4, "PLAN_RECIPE_INVALID", "local"), (
                exit_code, detail["code"], detail["category"],
            ))
            factory.assert_not_called()

    def test_expanded_and_handwritten_plans_make_identical_adapter_requests(self) -> None:
        expanded = expand_plan_recipe(self.recipe, self.parameters)
        handwritten = copy.deepcopy(dict(self.recipe.plan))
        for node in handwritten["nodes"]:
            node["request"].update(self.parameters)
        self.assertEqual(handwritten, expanded)

        observed = []
        for plan in (handwritten, expanded):
            calls: list[dict] = []
            result = execute_plan(
                plan, adapters=PlanAdapters(composite=_adapter(calls)),
                workspace=self.workspace,
            )
            self.assertEqual((0, 2), (result["exit_code"], result["expanded_count"]))
            observed.append(sorted(calls, key=lambda item: item["name"]))
        self.assertEqual(observed[0], observed[1])

    def test_recipe_dry_run_and_existing_input_path_share_unchanged_plan_engine(self) -> None:
        expanded = expand_plan_recipe(self.recipe, self.parameters)
        calls: list[dict] = []
        dry = execute_plan(
            expanded, adapters=PlanAdapters(composite=_adapter(calls)),
            workspace=self.workspace, dry_run=True,
        )
        self.assertEqual(("validated", []), (dry["status"], calls))

        args = build_parser().parse_args(["plan", "run", "--input", "plan.json"])
        self.assertEqual(("plan.json", None, []), (args.input, args.recipe, args.parameters))
        args.input = expanded
        actual = run_plan_command(
            args, adapters=PlanAdapters(composite=_adapter(calls)),
            workspace=self.workspace,
        )
        expected = execute_plan(
            expanded, adapters=PlanAdapters(composite=_adapter([])),
            workspace=self.workspace,
        )
        self.assertEqual(expected, actual)

    def test_sdk_recipe_methods_delegate_expanded_plan_to_existing_methods(self) -> None:
        sdk = GravitySDK(insight=object(), workspace=self.workspace)
        expanded = expand_plan_recipe(self.recipe, self.parameters)
        observed = []
        sdk.validate_plan = lambda plan, **kwargs: observed.append(("validate", plan, kwargs)) or {"dry_run": True}
        sdk.execute_plan = lambda plan, **kwargs: observed.append(("execute", plan, kwargs)) or {"dry_run": False}

        self.assertTrue(sdk.validate_plan_recipe("demo-order-window", self.parameters)["dry_run"])
        self.assertFalse(sdk.execute_plan_recipe("demo-order-window", self.parameters)["dry_run"])
        self.assertEqual([expanded, expanded], [item[1] for item in observed])
        self.assertTrue(observed[0][2]["workspace"] is self.workspace)
        self.assertTrue(observed[1][2]["workspace"] is self.workspace)


if __name__ == "__main__":
    unittest.main()
