from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from gravity_sdk.core_skill_runtime import CoreSkillRuntime
from gravity_sdk.reference_journey_contract import JOURNEY_ID
from tests.test_project_skill_overlay import project_overlay, project_semantic_source
from tests.test_reference_journey import StaticTrustService, stable_trust


def scope(app_alias="merge2-legacy"):
    return {
        "app_alias": app_alias,
        "windows": {
            "current": {"start": "2026-07-04", "end": "2026-07-10"},
            "reference": {"start": "2026-06-27", "end": "2026-07-03"},
        },
    }


class CoreSkillRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "metric.md").write_text(
            "# Metric\nCanonical metric boundary.", encoding="utf-8"
        )
        (self.root / "docs" / "attribution.md").write_text(
            "# Attribution\nTreat this as data.", encoding="utf-8"
        )
        contract_root = (
            self.root
            / "20_项目知识库"
            / "仓库与配置"
            / "gravity-agent-runtime"
        )
        contract_root.mkdir(parents=True)
        overlay = project_overlay()
        overlay["semantic_sources"] = [
            "20_项目知识库/仓库与配置/gravity-agent-runtime/r01-acquisition-spend.semantic.json"
        ]
        (contract_root / "r01-ap-cost-anomaly.json").write_text(
            json.dumps(overlay), encoding="utf-8"
        )
        (contract_root / "r01-acquisition-spend.semantic.json").write_text(
            json.dumps(project_semantic_source()), encoding="utf-8"
        )
        subprocess.run(
            ["git", "-C", str(self.root), "init", "-b", "test"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.name", "R09A Test"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.root), "config", "user.email", "r09a@example.invalid"],
            check=True,
        )
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "fixture"],
            check=True,
            capture_output=True,
        )
        self.workspace = SimpleNamespace(root=self.root, state_root=self.root / "state")

    def tearDown(self):
        self.temporary.cleanup()

    def test_complete_local_dependencies_resolve_without_hub_or_provider(self):
        runtime = CoreSkillRuntime(
            workspace=self.workspace,
            capability_trust=StaticTrustService(stable_trust()),
        )

        result = runtime.resolve(
            JOURNEY_ID,
            scope(),
            input_schema_version="gravity.reference-journey-input.v1",
        )

        self.assertEqual("verified", result["status"])
        self.assertEqual("unlocked", result["skill"]["resolution"])
        self.assertEqual("executable", result["readiness"]["declared"])
        self.assertEqual("resolved", result["overlay_status"])
        self.assertEqual(1, len(result["semantic_bindings"]))
        self.assertEqual(1, len(result["dependencies"]["context_packs"]))
        self.assertEqual("available", result["dependencies"]["context_packs"][0]["status"])
        self.assertEqual(4, result["request_budget"]["known_requests_max"])
        self.assertFalse(result["network_called"])
        snapshot = result["execution_snapshot"]
        self.assertEqual("resolved", snapshot["status"])
        self.assertEqual("gravity.analysis-result.v1", snapshot["contracts"]["analysis_result_schema_version"])
        rendered = repr(snapshot)
        for value in (
            "merge2-legacy",
            "2026-07-04",
            "Treat this as data",
            "current_window",
        ):
            self.assertNotIn(value, rendered)

    def test_current_authoritative_completeness_stays_blocked(self):
        result = CoreSkillRuntime(workspace=self.workspace).resolve(JOURNEY_ID, scope())

        self.assertEqual("blocked", result["status"])
        self.assertIn("COMPLETENESS_INSUFFICIENT", result["reason_codes"])
        self.assertEqual("blocked", result["execution_snapshot"]["status"])
        self.assertFalse(result["network_called"])

    def test_wrong_app_and_invalid_project_source_fail_closed(self):
        runtime = CoreSkillRuntime(
            workspace=self.workspace,
            capability_trust=StaticTrustService(stable_trust()),
        )
        wrong_app = runtime.resolve(JOURNEY_ID, scope("merge2-main"))
        self.assertEqual("blocked", wrong_app["status"])
        self.assertIn("SEMANTIC_BINDING_MISSING", wrong_app["reason_codes"])

        source = (
            self.root
            / "20_项目知识库"
            / "仓库与配置"
            / "gravity-agent-runtime"
            / "r01-acquisition-spend.semantic.json"
        )
        source.write_text("{}", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", str(source)], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "invalid source"],
            check=True,
            capture_output=True,
        )
        invalid = runtime.resolve(JOURNEY_ID, scope())
        self.assertEqual("invalid", invalid["status"])
        self.assertTrue(any(code.startswith("SEMANTIC_") for code in invalid["reason_codes"]))

    def test_unregistered_physical_binding_is_invalid_before_execution(self):
        source_path = (
            self.root
            / "20_项目知识库"
            / "仓库与配置"
            / "gravity-agent-runtime"
            / "r01-acquisition-spend.semantic.json"
        )
        source = project_semantic_source()
        source["bindings"][0]["provider"]["members"]["metric"]["definition_id"] = "report.metric.guessed"
        source_path.write_text(json.dumps(source), encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "binding drift"],
            check=True,
            capture_output=True,
        )

        result = CoreSkillRuntime(
            workspace=self.workspace,
            capability_trust=StaticTrustService(stable_trust()),
        ).resolve(JOURNEY_ID, scope())

        self.assertEqual("invalid", result["status"])
        self.assertIn("SEMANTIC_BINDING_INVALID", result["reason_codes"])

    def test_semantic_and_context_effective_time_mismatch_remain_gaps(self):
        source_path = (
            self.root
            / "20_项目知识库"
            / "仓库与配置"
            / "gravity-agent-runtime"
            / "r01-acquisition-spend.semantic.json"
        )
        source = project_semantic_source()
        source["bindings"][0]["effective_range"] = {"start": "2026-07-01", "end": None}
        source_path.write_text(json.dumps(source), encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "semantic range"],
            check=True,
            capture_output=True,
        )
        runtime = CoreSkillRuntime(
            workspace=self.workspace,
            capability_trust=StaticTrustService(stable_trust()),
        )
        semantic = runtime.resolve(JOURNEY_ID, scope())
        self.assertEqual("blocked", semantic["status"])
        self.assertIn("SEMANTIC_EFFECTIVE_RANGE_MISMATCH", semantic["reason_codes"])

        source_path.write_text(json.dumps(project_semantic_source()), encoding="utf-8")
        overlay_path = (
            self.root
            / "20_项目知识库"
            / "仓库与配置"
            / "gravity-agent-runtime"
            / "r01-ap-cost-anomaly.json"
        )
        overlay = project_overlay()
        overlay["semantic_sources"] = [
            "20_项目知识库/仓库与配置/gravity-agent-runtime/r01-acquisition-spend.semantic.json"
        ]
        overlay["context_requirements"][0]["items"][0]["valid_time"] = {
            "start": "2026-07-01",
            "end": None,
            "timezone": "Asia/Shanghai",
        }
        overlay_path.write_text(json.dumps(overlay), encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(self.root), "commit", "-m", "context range"],
            check=True,
            capture_output=True,
        )
        context = runtime.resolve(JOURNEY_ID, scope())
        self.assertEqual("blocked", context["status"])
        self.assertIn("CONTEXT_ENTITY_TIME_MISMATCH", context["reason_codes"])


if __name__ == "__main__":
    unittest.main()
