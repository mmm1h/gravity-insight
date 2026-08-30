"""R11 private PAP parity, source-boundary, drift and storage gates."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from gravity_insight import GravitySDK, PreparedAnalysisPlanService, execute_host_plan
from gravity_insight.errors import InputValidationError
from gravity_insight.host_effects import ACTION_SCHEMA_VERSION, HOST_PLAN_SCHEMA_VERSION, host_source
from gravity_insight.shared_runtime import reset_shared_runtimes
from gravity_insight.workspace import load_workspace


OPERATION_ID = "analysis.fixture.read"
SCOPE_A = "a" * 32
SCOPE_B = "b" * 32
NOW = datetime(2026, 8, 22, 4, 0, 0, tzinfo=timezone.utc)


class FixtureInsight:
    def __init__(self) -> None:
        self.catalog = {
            "operation_id": OPERATION_ID,
            "stability": "stable",
            "effect": "read",
            "executable": True,
            "contract_version": "1",
        }
        self.contract = {
            "operation_id": OPERATION_ID,
            "stability": "stable",
            "effect": "read",
            "input_schema": {
                "page": {"type": "integer", "minimum": 1},
                "filter": {"type": "string"},
            },
            "response_projection": {"data_keys": ["list"]},
        }

    def operations(self, **_options: object) -> list[dict[str, object]]:
        return [copy.deepcopy(self.catalog)]

    def describe(self, operation_id: str) -> dict[str, object]:
        if operation_id != OPERATION_ID:
            raise AssertionError("unexpected fixture selector")
        return copy.deepcopy(self.contract)

    def validate(self, operation_id: str, inputs: object) -> dict[str, object]:
        return {"ok": operation_id == OPERATION_ID and isinstance(inputs, dict)}


class FixtureSDK(GravitySDK):
    def __init__(self, workspace: object, *, scope_bound: bool = True) -> None:
        self.fixture_insight = FixtureInsight()
        self.target_calls: list[dict[str, object]] = []
        self.native_result: dict[str, object] = _native_result("success")
        super().__init__(
            insight=self.fixture_insight,
            workspace=workspace,
            _runtime_scope_bound=scope_bound,
        )

    def run(
        self,
        selector: str,
        inputs: object,
        **options: object,
    ) -> dict[str, object]:
        self.target_calls.append(
            {
                "selector": selector,
                "inputs": copy.deepcopy(inputs),
                "max_workers": options.get("max_workers"),
                "max_pages": options.get("max_pages"),
                "max_items": options.get("max_items"),
            }
        )
        return {"ok": True, "result": copy.deepcopy(self.native_result)}


def _workspace(root: Path, scope: str = SCOPE_A) -> SimpleNamespace:
    return SimpleNamespace(
        root=root,
        path=root / "gravity.toml",
        state_root=root / "state" / "principals" / scope,
        recipes={},
        products={},
        datasources={},
        semantic_context=None,
    )


def _native_result(status: str) -> dict[str, object]:
    if status == "error":
        return {
            "schema_version": "gravity-insight.read.v1",
            "ok": False,
            "status": "contract_changed",
            "operation_id": OPERATION_ID,
            "completeness": "unknown",
            "exit_code": 3,
            "error": {
                "code": "CONTRACT_CHANGED",
                "category": "upstream",
                "message": "fixture contract changed",
                "next_action": "stop",
            },
        }
    rows = [] if status == "empty" else [{"safe": 7}]
    return {
        "schema_version": "gravity-insight.read.v1",
        "ok": True,
        "status": status,
        "operation_id": OPERATION_ID,
        "completeness": "complete",
        "data": {"list": rows},
    }


def _plan(filter_value: str = "private-filter") -> dict[str, object]:
    return {
        "schema_version": "gravity.plan.v1",
        "budget": {"max_workers": 3, "max_total_items": 20},
        "nodes": [
            {
                "id": "read",
                "kind": "run",
                "request": {
                    "selector": OPERATION_ID,
                    "inputs": {"page": 1, "filter": filter_value},
                },
                "limits": {"max_pages": 1, "max_items": 20},
            }
        ],
    }


def _host_plan(
    plan: dict[str, object] | None = None,
    *,
    kind: str = "run",
    request_key: str = "selector",
    request_value: str = OPERATION_ID,
) -> tuple[dict[str, object], dict[str, object]]:
    selected_plan = copy.deepcopy(plan or _plan())
    sources = {
        "user.task": host_source("user", "instruction", "private user task"),
        "sdk.tool": host_source("sdk_contract", "instruction", "gravity.plan"),
        "sdk.operation": host_source("sdk_contract", "instruction", OPERATION_ID),
        "sdk.path": host_source("sdk_contract", "instruction", "gravity plan run"),
        "sdk.kind": host_source("sdk_contract", "instruction", kind),
        "sdk.selector": host_source("sdk_contract", "instruction", request_value),
        "unused.tool": host_source("tool_result", "data", "Bearer unused-secret"),
    }
    action = {
        "schema_version": ACTION_SCHEMA_VERSION,
        "task_source": "user.task",
        "effect": "read",
        "phase": "read",
        "controls": {
            "tool": "sdk.tool",
            "operation": "sdk.operation",
            "path": "sdk.path",
            "object_ids": [],
            "destination": None,
        },
        "request": copy.deepcopy(selected_plan),
        "permission_source": None,
        "confirmation_source": None,
        "preview_fingerprint": None,
    }
    host_plan = {
        "schema_version": HOST_PLAN_SCHEMA_VERSION,
        "plan": selected_plan,
        "action": action,
        "control_sources": {
            "/nodes/0/kind": "sdk.kind",
            f"/nodes/0/request/{request_key}": "sdk.selector",
        },
    }
    return host_plan, sources


def _composite_host_plan() -> tuple[dict[str, object], dict[str, object]]:
    plan = {
        "schema_version": "gravity.plan.v1",
        "nodes": [
            {
                "id": "composite",
                "kind": "composite",
                "request": {"name": "business_pulse"},
            }
        ],
    }
    return _host_plan(
        plan,
        kind="composite",
        request_key="name",
        request_value="business_pulse",
    )


def _artifact_path(workspace: object) -> Path:
    paths = list((workspace.state_root / "prepared-analysis-plans").glob("*.json"))
    if len(paths) != 1:
        raise AssertionError(f"expected one PAP artifact, found {len(paths)}")
    return paths[0]


class PreparedAnalysisPlanParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = _workspace(self.root)
        self.sdk = FixtureSDK(self.workspace)
        self.host_plan, self.sources = _host_plan()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_prepare_is_zero_target_and_execute_matches_direct_host_plan(self) -> None:
        direct = execute_host_plan(self.sdk, self.host_plan, self.sources, max_workers=4)
        direct_calls = copy.deepcopy(self.sdk.target_calls)
        self.sdk.target_calls.clear()

        with mock.patch("gravity_insight.prepared_analysis_plan._utcnow", return_value=NOW):
            summary = self.sdk.prepared_plans.prepare_host(
                self.host_plan, self.sources, max_workers=4
            )
            self.assertEqual([], self.sdk.target_calls)
            self.assertEqual(
                (
                    "gravity.prepared-analysis-plan-summary.v1",
                    "prepared",
                    "host_plan",
                    1,
                    4,
                ),
                (
                    summary["schema_version"],
                    summary["status"],
                    summary["source_kind"],
                    summary["node_count"],
                    summary["max_workers"],
                ),
            )
            prepared = self.sdk.prepared_plans.execute_host(
                summary["pap_id"], self.host_plan, self.sources
            )
        self.assertEqual(direct, prepared)
        self.assertEqual(direct_calls, self.sdk.target_calls)

    def test_success_empty_error_and_completeness_envelopes_are_exact(self) -> None:
        for status in ("success", "empty", "error"):
            with self.subTest(status=status):
                self.sdk.native_result = _native_result(status)
                direct = execute_host_plan(self.sdk, self.host_plan, self.sources)
                self.sdk.target_calls.clear()
                summary = self.sdk.prepared_plans.prepare_host(
                    self.host_plan, self.sources
                )
                actual = self.sdk.prepared_plans.execute_host(
                    summary["pap_id"], self.host_plan, self.sources
                )
                self.assertEqual(direct, actual)
                self.assertEqual(1, len(self.sdk.target_calls))

    def test_private_artifact_and_public_summary_contain_no_plan_values_or_scope(self) -> None:
        summary = self.sdk.prepared_plans.prepare_host(self.host_plan, self.sources)
        artifact = _artifact_path(self.workspace).read_text(encoding="utf-8")
        rendered = json.dumps(summary, sort_keys=True) + artifact
        for private in (
            "private-filter",
            "private user task",
            "Bearer unused-secret",
            "gravity plan run",
            SCOPE_A,
        ):
            self.assertNotIn(private, rendered)
        schema = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "src/gravity_insight/contracts/schema/prepared-analysis-plan-v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(set(schema["required"]), set(json.loads(artifact)))
        summary_schema = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "src/gravity_insight/contracts/schema/prepared-analysis-plan-summary-v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(set(summary_schema["required"]), set(summary))

    def test_internal_plan_and_direct_call_remain_available_after_pap_blocker(self) -> None:
        with self.assertRaises(InputValidationError) as raised:
            self.sdk.prepared_plans.execute_host(
                "not-a-pap", self.host_plan, self.sources
            )
        self.assertEqual("PAP_REFERENCE_INVALID", raised.exception.code)
        direct = self.sdk.run(OPERATION_ID, {"page": 1})
        plan = self.sdk.execute_plan(_plan("ordinary-plan"))
        self.assertTrue(direct["ok"])
        self.assertTrue(plan["ok"])

    def test_composite_and_mutation_paths_stop_without_affecting_ordinary_plan(self) -> None:
        composite, sources = _composite_host_plan()
        with self.assertRaises(InputValidationError) as raised:
            self.sdk.prepared_plans.prepare_host(composite, sources)
        self.assertEqual("PAP_UNSUPPORTED_PATH", raised.exception.code)
        self.assertEqual([], self.sdk.target_calls)
        self.sdk.fixture_insight.catalog["effect"] = "mutation"
        with self.assertRaises(InputValidationError) as mutation:
            self.sdk.prepared_plans.prepare_host(self.host_plan, self.sources)
        self.assertEqual("EFFECT_SOURCE_REJECTED", mutation.exception.code)
        self.assertEqual([], self.sdk.target_calls)


class PreparedAnalysisPlanDriftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = _workspace(self.root)
        self.sdk = FixtureSDK(self.workspace)
        self.host_plan, self.sources = _host_plan()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _prepare(self) -> str:
        return self.sdk.prepared_plans.prepare_host(
            self.host_plan, self.sources
        )["pap_id"]

    def _assert_blocked(
        self,
        expected: str,
        pap_id: str,
        host_plan: dict[str, object] | None = None,
        sources: dict[str, object] | None = None,
    ) -> None:
        self.sdk.target_calls.clear()
        with self.assertRaises(InputValidationError) as raised:
            self.sdk.prepared_plans.execute_host(
                pap_id,
                host_plan or self.host_plan,
                sources or self.sources,
            )
        self.assertEqual(expected, raised.exception.code)
        self.assertEqual([], self.sdk.target_calls)
        self.assertNotIn(SCOPE_A, str(raised.exception))
        self.assertNotIn("private-filter", str(raised.exception))

    def test_plan_and_referenced_source_drift_fail_before_target(self) -> None:
        pap_id = self._prepare()
        changed_plan, changed_sources = _host_plan(_plan("changed-filter"))
        self._assert_blocked("PAP_INPUT_DRIFT", pap_id, changed_plan, changed_sources)
        changed_sources = copy.deepcopy(self.sources)
        changed_sources["user.task"] = host_source(
            "user", "instruction", "different task"
        )
        self._assert_blocked("PAP_SOURCE_DRIFT", pap_id, sources=changed_sources)
        unreferenced = copy.deepcopy(self.sources)
        unreferenced["unused.tool"] = host_source(
            "tool_result", "data", "changed but still unused"
        )
        result = self.sdk.prepared_plans.execute_host(
            pap_id, self.host_plan, unreferenced
        )
        self.assertTrue(result["ok"])

    def test_contract_catalog_and_workspace_drift_fail_before_target(self) -> None:
        pap_id = self._prepare()
        self.sdk.fixture_insight.contract["description"] = "changed"
        self._assert_blocked("PAP_CONTRACT_DRIFT", pap_id)
        self.sdk.fixture_insight.contract.pop("description")
        self.sdk.fixture_insight.catalog["contract_version"] = "2"
        self._assert_blocked("PAP_CATALOG_DRIFT", pap_id)
        self.sdk.fixture_insight.catalog["contract_version"] = "1"
        self.workspace.semantic_context = SimpleNamespace(
            contract=lambda: {"schema_version": "fixture.semantic.v1"}
        )
        self._assert_blocked("PAP_CATALOG_DRIFT", pap_id)

    def test_tool_result_cannot_replace_sdk_control_during_execute(self) -> None:
        pap_id = self._prepare()
        attacked = copy.deepcopy(self.sources)
        attacked["sdk.selector"] = host_source(
            "tool_result", "data", OPERATION_ID
        )
        self._assert_blocked("EFFECT_SOURCE_REJECTED", pap_id, sources=attacked)

    def test_tamper_expiry_missing_and_identity_drift_are_local(self) -> None:
        pap_id = self._prepare()
        path = _artifact_path(self.workspace)
        artifact = json.loads(path.read_text(encoding="utf-8"))
        artifact["contract_fingerprint"] = "0" * 64
        path.write_text(json.dumps(artifact), encoding="utf-8")
        self._assert_blocked("PAP_TAMPERED", pap_id)

        fresh_root = self.root / "expiry"
        workspace = _workspace(fresh_root)
        sdk = FixtureSDK(workspace)
        host_plan, sources = _host_plan()
        with mock.patch("gravity_insight.prepared_analysis_plan._utcnow", return_value=NOW):
            expired_id = sdk.prepared_plans.prepare_host(
                host_plan, sources, ttl_seconds=1
            )["pap_id"]
        with mock.patch(
            "gravity_insight.prepared_analysis_plan._utcnow",
            return_value=NOW + timedelta(seconds=2),
        ):
            with self.assertRaises(InputValidationError) as expired:
                sdk.prepared_plans.execute_host(expired_id, host_plan, sources)
        self.assertEqual("PAP_EXPIRED", expired.exception.code)
        self.assertEqual([], sdk.target_calls)

        other = FixtureSDK(_workspace(self.root / "other", SCOPE_B))
        with self.assertRaises(InputValidationError) as identity:
            other.prepared_plans.execute_host(expired_id, host_plan, sources)
        self.assertEqual("PAP_IDENTITY_DRIFT", identity.exception.code)
        self.assertEqual([], other.target_calls)

        expiry_path = _artifact_path(workspace)
        expiry_path.unlink()
        with mock.patch("gravity_insight.prepared_analysis_plan._utcnow", return_value=NOW):
            with self.assertRaises(InputValidationError) as missing:
                sdk.prepared_plans.execute_host(expired_id, host_plan, sources)
        self.assertEqual("PAP_NOT_FOUND", missing.exception.code)

    def test_hardlink_and_store_bound_are_rejected(self) -> None:
        pap_id = self._prepare()
        path = _artifact_path(self.workspace)
        link = path.with_suffix(".link")
        os.link(path, link)
        try:
            self._assert_blocked("PAP_TAMPERED", pap_id)
        finally:
            link.unlink(missing_ok=True)

        bounded = FixtureSDK(_workspace(self.root / "bounded"))
        host_plan, sources = _host_plan()
        with mock.patch(
            "gravity_insight.prepared_analysis_plan.MAX_STORED_ARTIFACTS", 1
        ):
            bounded.prepared_plans.prepare_host(host_plan, sources)
            with self.assertRaises(InputValidationError) as raised:
                bounded.prepared_plans.prepare_host(host_plan, sources)
        self.assertEqual("PAP_STORE_BOUND_EXCEEDED", raised.exception.code)
        self.assertEqual([], bounded.target_calls)

    def test_expired_cleanup_and_failed_commit_leave_no_partial_artifact(self) -> None:
        with mock.patch("gravity_insight.prepared_analysis_plan._utcnow", return_value=NOW):
            self.sdk.prepared_plans.prepare_host(
                self.host_plan, self.sources, ttl_seconds=1
            )
        with mock.patch(
            "gravity_insight.prepared_analysis_plan._utcnow",
            return_value=NOW + timedelta(seconds=2),
        ), mock.patch(
            "gravity_insight.prepared_analysis_plan.MAX_STORED_ARTIFACTS", 1
        ):
            self.sdk.prepared_plans.prepare_host(self.host_plan, self.sources)
        self.assertEqual(
            1,
            len(list((self.workspace.state_root / "prepared-analysis-plans").glob("*.json"))),
        )

        failed = FixtureSDK(_workspace(self.root / "failed"))
        host_plan, sources = _host_plan()
        with mock.patch("gravity_insight.prepared_analysis_plan.os.replace", side_effect=OSError("fixture")):
            with self.assertRaises(OSError):
                failed.prepared_plans.prepare_host(host_plan, sources)
        store = failed.workspace.state_root / "prepared-analysis-plans"
        self.assertEqual([], list(store.glob("*")))
        self.assertEqual([], failed.target_calls)


class PreparedAnalysisPlanScopeTests(unittest.TestCase):
    def tearDown(self) -> None:
        reset_shared_runtimes()

    def test_unscoped_sdk_and_non_scope_path_fail_without_state_or_target_calls(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = _workspace(Path(raw), "not-a-runtime-scope")
            sdk = FixtureSDK(workspace, scope_bound=False)
            with self.assertRaises(InputValidationError) as raised:
                _ = sdk.prepared_plans
        self.assertEqual("PAP_SCOPE_UNBOUND", raised.exception.code)
        self.assertEqual([], sdk.target_calls)

    def test_public_constructor_is_lazy_and_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            workspace = _workspace(Path(raw))
            sdk = FixtureSDK(workspace)
            service = PreparedAnalysisPlanService(sdk)
        self.assertEqual("<PreparedAnalysisPlanService private>", repr(service))
        self.assertNotIn(SCOPE_A, repr(service))

    def test_from_env_real_catalog_prepares_offline_without_calling_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env_path = root / "fixture.env.gravity.local"
            env_path.write_text(
                "GRAVITY_USERNAME=pap-fixture\nGRAVITY_PASSWORD=fixture-only\n",
                encoding="utf-8",
            )
            workspace = load_workspace(
                Path(__file__).resolve().parents[1] / "examples/workspace",
                cache_root=root / "cache",
            )
            sdk = GravitySDK.from_env(workspace=workspace, env_path=env_path)
            plan = {
                "schema_version": "gravity.plan.v1",
                "nodes": [
                    {
                        "id": "apps",
                        "kind": "run",
                        "request": {
                            "selector": "app.list",
                            "inputs": {"page": 1, "page_size": 1},
                        },
                    }
                ],
            }
            host_plan, sources = _host_plan(plan, request_value="app.list")
            with mock.patch.object(
                sdk, "run", side_effect=AssertionError("prepare called target")
            ):
                summary = sdk.prepared_plans.prepare_host(host_plan, sources)
            env_path.write_text(
                env_path.read_text(encoding="utf-8")
                + "GRAVITY_AUTH_UPDATED_AT=next-generation\n",
                encoding="utf-8",
            )
            changed = GravitySDK.from_env(workspace=workspace, env_path=env_path)
            self.assertNotEqual(sdk.workspace.state_root, changed.workspace.state_root)
            with mock.patch.object(
                changed, "run", side_effect=AssertionError("identity drift called target")
            ), self.assertRaises(InputValidationError) as identity:
                changed.prepared_plans.execute_host(
                    summary["pap_id"], host_plan, sources
                )
        self.assertEqual("prepared", summary["status"])
        self.assertRegex(summary["pap_id"], r"^pap1_[0-9a-f_]+$")
        self.assertEqual("PAP_IDENTITY_DRIFT", identity.exception.code)


if __name__ == "__main__":
    unittest.main()
