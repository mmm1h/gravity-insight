from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gravity_sdk.errors import InputValidationError
from gravity_sdk.recipe import run_recipe_command
from gravity_sdk.recipe_repin import apply_recipe_repin, assess_recipe_repin
from gravity_sdk.workspace import Recipe, RecipeBindings, load_workspace


def _recipe(**changes: object) -> Recipe:
    values = dict(
        name="weekly",
        operation="analysis.example.query",
        description="Example",
        bindings=RecipeBindings("main", "app_id", "saved-report", "query_id"),
        parameters={"start": "date_list.0.start_date", "end": "date_list.0.end_date"},
        required_parameters=("start", "end"),
        input={"query_item_list": []},
        output_fields=("total",),
        contract_fingerprint="a" * 64,
    )
    values.update(changes)
    return Recipe(**values)  # type: ignore[arg-type]


def _description(**changes: object) -> dict:
    payload = {
        "operation_id": "analysis.example.query",
        "stability": "stable",
        "executable": True,
        "input_schema": {
            "app_id": {"type": "string", "required": True},
            "query_id": {"type": "string", "required": True},
            "date_list": {"type": "array", "item_type": "object", "required": True},
            "query_item_list": {"type": "array", "required": True},
        },
        "response_projection": {"data_keys": ["total", "values"]},
        "health": {"contract_fingerprint": "b" * 64},
    }
    payload.update(changes)
    return payload


class _Client:
    def __init__(self, description: dict) -> None:
        self.description = description

    def describe(self, _operation_id: str) -> dict:
        return self.description


class RecipeRepinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "gravity.toml"
        self.path.write_text(
            """schema_version = 1
[apps]
main = 1001
[defaults]
app = "main"
timezone = "Asia/Shanghai"
time_window = "latest-safe-day"
[datasources]
[products]
[recipes.weekly]
operation = "analysis.example.query"
required_parameters = ["start", "end"]
output_fields = ["total"]
contract_fingerprint = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
[recipes.weekly.bindings]
app_ref = "main"
app_input = "app_id"
report_ref = "saved-report"
report_input = "query_id"
[recipes.weekly.parameters]
start = "date_list.0.start_date"
end = "date_list.0.end_date"
[recipes.weekly.input]
query_item_list = []
""",
            encoding="utf-8",
        )
        self.workspace = load_workspace(self.path, environ={}, cache_root=self.root / "cache")

    def test_additive_accept_rewrites_only_the_fingerprint(self) -> None:
        client = _Client(_description())
        result = apply_recipe_repin(
            self.workspace, _recipe(), assess_recipe_repin(_recipe(), client)
        )
        self.assertEqual("accepted", result["status"])
        self.assertEqual("additive", result["classification"])
        self.assertIn("output.values", result["contract_diff"]["added"])
        self.assertEqual([], result["contract_diff"]["removed"])
        self.assertTrue(result["written"])
        reloaded = load_workspace(self.path, environ={}, cache_root=self.root / "cache")
        self.assertEqual("b" * 64, reloaded.recipe("weekly").contract_fingerprint)
        self.assertEqual(["total"], list(reloaded.recipe("weekly").output_fields))

    def test_breaking_change_stays_blocked_without_explicit_ack(self) -> None:
        client = _Client(_description(response_projection={"data_keys": ["other"]}))
        preview = apply_recipe_repin(
            self.workspace,
            _recipe(),
            assess_recipe_repin(_recipe(), client),
            dry_run=True,
        )
        self.assertEqual("blocked", preview["status"])
        self.assertIn("output.total", preview["contract_diff"]["removed"])
        self.assertFalse(preview["written"])
        with self.assertRaises(InputValidationError) as raised:
            apply_recipe_repin(
                self.workspace,
                _recipe(),
                assess_recipe_repin(_recipe(), client),
                allow_breaking=True,
            )
        self.assertEqual("reason", raised.exception.field)
        accepted = apply_recipe_repin(
            self.workspace,
            _recipe(),
            assess_recipe_repin(_recipe(), client),
            allow_breaking=True,
            reason="caller reviewed deleted output.total",
        )
        self.assertEqual("accepted", accepted["status"])
        self.assertEqual("caller reviewed deleted output.total", accepted["reason"])

    def test_cli_dry_run_does_not_write(self) -> None:
        args = type("Args", (), {
            "recipe_command": "accept-contract",
            "name": "weekly",
            "allow_breaking": False,
            "reason": None,
            "dry_run": True,
        })()
        result = run_recipe_command(
            args, lambda _args: _Client(_description()), workspace=self.workspace
        )
        self.assertEqual("preview", result["status"])
        self.assertFalse(result["written"])
        self.assertIn("aaaaaaaa", self.path.read_text(encoding="utf-8"))
