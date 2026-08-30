from __future__ import annotations

import unittest
import tempfile

import io
import json
import os
import subprocess
import sys
import tomllib
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock


from gravity_insight.sql import __main__ as sql_cli
from gravity_insight.sql.products import build_sql, day_window, product_names
from gravity_insight.workspace import (
    WorkspaceError,
    find_workspace,
    load_workspace,
    user_cache_root,
)


ROOT = Path(__file__).resolve().parents[1]


def test_user_cache_root_uses_current_distribution_identity(tmp_path: Path) -> None:
    assert user_cache_root({"XDG_CACHE_HOME": str(tmp_path)}) == (
        tmp_path / "gravity-insight"
    ).resolve()


def _workspace_text(*, app_id: int = 101, product: str = "daily-summary") -> str:
    return f"""schema_version = 1

[apps]
main = {app_id}

[defaults]
app = "main"
timezone = "Asia/Shanghai"
time_window = "latest-safe-day"

[datasources.primary]
id = "test_datasource"
verification_status = "verified"

[products.{product}]
kind = "custom-sql"
datasource = "primary"
apps = ["main"]
forbidden_claims = ["not financial accounting"]
privacy = "aggregate"
output_fields = ["app_id", "event_count"]
max_rows = 100
sql = "SELECT app_id, COUNT(*) AS event_count FROM event WHERE app_id IN ({{app_ids}}) AND create_time >= '{{start}}' AND create_time < '{{end}}' GROUP BY app_id LIMIT {{limit}}"
"""



class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.tmp_path = Path(self._temporary_directory.name).resolve()

    def test_no_workspace_falls_back_to_cache_without_creating_it(self):
        start = self.tmp_path / "project" / "nested"
        start.mkdir(parents=True)
        cache = self.tmp_path / "cache"

        workspace = load_workspace(start=start, environ={}, cache_root=cache)

        assert workspace.configured is False
        assert workspace.path is None
        assert workspace.root == cache / "default"
        assert workspace.state_root == cache / "default"
        assert workspace.products == {}
        assert not cache.exists()


    def test_workspace_is_found_upward(self):
        workspace_path = self.tmp_path / "gravity.toml"
        workspace_path.write_text(_workspace_text(), encoding="utf-8")
        nested = self.tmp_path / "one" / "two"
        nested.mkdir(parents=True)

        assert find_workspace(nested) == workspace_path
        workspace = load_workspace(start=nested, environ={}, cache_root=self.tmp_path / "cache")
        assert workspace.path == workspace_path
        assert workspace.root == self.tmp_path


    def test_app_aliases_and_default_app_are_resolved(self):
        path = self.tmp_path / "gravity.toml"
        path.write_text(_workspace_text(app_id=1001), encoding="utf-8")

        workspace = load_workspace(path, environ={}, cache_root=self.tmp_path / "cache")

        assert workspace.resolve_app() == 1001
        assert workspace.resolve_app("main") == 1001
        assert workspace.resolve_app("1002") == 1002
        with self.assertRaisesRegex(WorkspaceError, "unknown Gravity app"):
            workspace.resolve_app("missing")


    def test_workspace_example_exposes_validated_recipe_shape(self):
        workspace = load_workspace(
            ROOT / "examples" / "workspace" / "gravity.toml",
            environ={},
            cache_root=self.tmp_path / "cache",
        )

        recipe = workspace.recipe("demo-retention")
        assert recipe.operation == "analysis.retention.query"
        assert recipe.bindings.app_ref == "demo"
        assert recipe.required_parameters == ("start", "end")
        assert recipe.output_fields == ("total", "x", "y")


    def test_workspace_rejects_invalid_recipe_fingerprint(self):
        path = self.tmp_path / "gravity.toml"
        path.write_text(
            _workspace_text()
            + """
[recipes.bad]
operation = "analysis.retention.query"
required_parameters = []
output_fields = ["total"]
contract_fingerprint = "not-a-fingerprint"

[recipes.bad.bindings]
app_ref = "main"
app_input = "app_id"

[recipes.bad.parameters]
[recipes.bad.input]
""",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(WorkspaceError, "contract_fingerprint"):
            load_workspace(path, environ={}, cache_root=self.tmp_path / "cache")


    def test_gravity_workspace_environment_overrides_upward_search(self):
        discovered = self.tmp_path / "discovered"
        override = self.tmp_path / "override"
        nested = discovered / "nested"
        nested.mkdir(parents=True)
        override.mkdir()
        (discovered / "gravity.toml").write_text(
            _workspace_text(app_id=101), encoding="utf-8"
        )
        override_path = override / "gravity.toml"
        override_path.write_text(_workspace_text(app_id=202), encoding="utf-8")

        workspace = load_workspace(
            start=nested,
            environ={"GRAVITY_WORKSPACE": str(override_path)},
            cache_root=self.tmp_path / "cache",
        )

        assert workspace.path == override_path
        assert workspace.resolve_app() == 202


    def test_explicit_workspace_beats_environment_override(self):
        explicit = self.tmp_path / "explicit.toml"
        environment = self.tmp_path / "environment.toml"
        explicit.write_text(_workspace_text(app_id=303), encoding="utf-8")
        environment.write_text(_workspace_text(app_id=404), encoding="utf-8")

        workspace = load_workspace(
            explicit,
            environ={"GRAVITY_WORKSPACE": str(environment)},
            cache_root=self.tmp_path / "cache",
        )

        assert workspace.path == explicit
        assert workspace.resolve_app() == 303


    def test_paths_use_cache_state_outside_checkout(self):
        project = self.tmp_path / "plain-project"
        cache = self.tmp_path / "cache"
        project.mkdir()
        environment = os.environ.copy()
        environment.pop("GRAVITY_WORKSPACE", None)
        environment["GRAVITY_CACHE_HOME"] = str(cache)
        environment["PYTHONPATH"] = str(ROOT / "src")
        command = (
            "import json; from gravity_insight.paths import EVIDENCE_ROOT, TMP_ROOT; "
            "print(json.dumps({'evidence': str(EVIDENCE_ROOT), 'tmp': str(TMP_ROOT)}))"
        )

        completed = subprocess.run(
            [sys.executable, "-c", command],
            cwd=project,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        paths = json.loads(completed.stdout)

        assert Path(paths["evidence"]) == cache / "default" / "evidence"
        assert Path(paths["tmp"]) == cache / "default" / "tmp"


    def test_sql_cli_reports_unconfigured_products_without_crashing(self):
        stderr = io.StringIO()
        with mock.patch.dict(
            os.environ,
            {"GRAVITY_CACHE_HOME": str(self.tmp_path / "cache")},
            clear=True,
        ), mock.patch("pathlib.Path.cwd", return_value=self.tmp_path), redirect_stdout(
            io.StringIO()
        ), redirect_stderr(stderr):
            exit_code = sql_cli.main(
                [
                    "query",
                    "anything",
                    "--start",
                    "2026-07-22T00:00:00",
                    "--end",
                    "2026-07-23T00:00:00",
                ]
            )

        assert exit_code == 2
        assert "no SQL products are configured" in stderr.getvalue()


    def test_custom_sql_product_is_added_only_by_workspace_data(self):
        path = self.tmp_path / "gravity.toml"
        path.write_text(
            _workspace_text(product="daily-orders"),
            encoding="utf-8",
        )
        start_at, end_at = day_window(date(2026, 7, 22))

        with mock.patch.dict(os.environ, {"GRAVITY_WORKSPACE": str(path)}):
            assert product_names() == ("daily-orders",)
            rendered = build_sql("daily-orders", start_at, end_at, ())

        assert "app_id IN (101)" in rendered
        assert "2026-07-22 00:00:00" in rendered
        assert "LIMIT 101" in rendered


    def test_custom_sql_rejects_case_variant_user_level_output(self):
        path = self.tmp_path / "gravity.toml"
        path.write_text(
            _workspace_text().replace(
                'output_fields = ["app_id", "event_count"]',
                'output_fields = ["app_id", "User_ID"]',
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(WorkspaceError, "user-level field"):
            load_workspace(path, environ={}, cache_root=self.tmp_path / "cache")


    def test_custom_sql_rejects_incomplete_output_semantics(self):
        path = self.tmp_path / "gravity.toml"
        path.write_text(_workspace_text() + '\n[products.daily-summary.output_semantics]\napp_id = "App"\n', encoding="utf-8")
        with self.assertRaisesRegex(WorkspaceError, "describe every output field"):
            load_workspace(path, environ={}, cache_root=self.tmp_path / "cache")


    def test_census_console_script_is_not_published(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

        assert "gravity-census" not in project["project"]["scripts"]


    def test_sdk_contract_and_example_are_generic(self):
        catalog = json.loads((
            ROOT / "src" / "gravity_insight" / "contracts" / "sql-products" / "catalog.json"
        ).read_text(encoding="utf-8"))
        example = tomllib.loads(
            (ROOT / "examples" / "workspace" / "gravity.toml").read_text(encoding="utf-8")
        )

        assert set(catalog["product_kinds"]) == {"custom-sql"}
        assert example["apps"] == {"demo": 1001}
        assert set(example["products"]) == {"daily-event-summary"}
        assert set(tomllib.loads((ROOT / "examples/workspace/sql-capability-recipes.toml").read_text(encoding="utf-8"))["products"]) == {"payment-summary", "first-scene-coverage", "event-coverage"}


    def test_global_workspace_flag_is_applied_before_cli_modules_import(self):
        workspace_path = self.tmp_path / "selected.toml"
        workspace_path.write_text(_workspace_text(product="selected-product"), encoding="utf-8")
        environment = os.environ.copy()
        environment.pop("GRAVITY_WORKSPACE", None)
        environment["PYTHONPATH"] = str(ROOT / "src")

        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "gravity_insight",
                "--workspace",
                str(workspace_path),
                "sql",
                "--dry-run",
            ],
            cwd=self.tmp_path,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )

        assert completed.returncode == 0, completed.stderr
