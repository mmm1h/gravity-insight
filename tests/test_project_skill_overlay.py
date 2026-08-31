from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from gravity_insight.project_skill_overlay import (
    ProjectSkillOverlayError,
    compile_project_skill_overlay,
    load_project_skill_overlay,
)


SKILL_URI = "skill://gravity.game/ap-cost-anomaly-localization@1.0.0"
JOURNEY_ID = "analysis.merge2.ap-cost-anomaly-localization"


def context_requirement(paths=("docs/metric.md", "docs/attribution.md")):
    return {
        "artifact_kind": "context_requirement",
        "schema_version": "gravity.context-requirement.v1",
        "requirement_id": "context://project-repo/merge2-acquisition-boundaries@1",
        "provider_uri": "context-provider://gravity/project-repo@1",
        "skill_uri": SKILL_URI,
        "journey_id": JOURNEY_ID,
        "subject_entities": [
            "app://project/merge2-legacy",
            "metric://project/acquisition-spend@1",
        ],
        "required_windows": ["current", "reference"],
        "authority_policy": {
            "required": ["canonical"],
            "allow_supporting": True,
            "allow_declared_intent": False,
            "allow_unverified": False,
        },
        "allowed_sensitivity": ["internal"],
        "freshness_policy": {"as_of": None, "max_age_days": None},
        "budget": {
            "max_files": 4,
            "max_file_bytes": 262144,
            "max_total_bytes": 524288,
            "max_total_lines": 10000,
        },
        "items": [
            {
                "item_id": f"r01-context-{index + 1}",
                "fact_id": f"r01-fact-{index + 1}",
                "required": True,
                "path": path,
                "title": path,
                "resource_type": "document",
                "entity_refs": ["app://project/merge2-legacy"],
                "valid_time": {
                    "start": None,
                    "end": None,
                    "timezone": "Asia/Shanghai",
                },
                "effective_range": {"start": None, "end": None},
                "authority": "canonical" if index == 0 else "supporting",
                "sensitivity": "internal",
                "supersedes": [],
                "max_age_days": None,
            }
            for index, path in enumerate(paths)
        ],
    }


def project_semantic_source():
    return {
        "artifact_kind": "semantic_source",
        "schema_version": "gravity.semantic-source.v1",
        "source_id": "work-dashboard/merge2-r01",
        "source_kind": "project_json",
        "project_id": "merge2",
        "owner": "growth-data",
        "definitions": [
            {
                "artifact_kind": "semantic_definition",
                "schema_version": "gravity.semantic-definition.v1",
                "uri": "metric://project/acquisition-spend@1",
                "kind": "metric",
                "version": 1,
                "owner": "growth-data",
                "authority": "project",
                "display_name": "Acquisition spend",
                "description": "Platform-reported acquisition spend for returned rows.",
                "effective_range": {"start": None, "end": None},
                "unit": {
                    "kind": "currency",
                    "symbol": "platform_reported_cost",
                    "currency": None,
                    "scale": 2,
                },
                "aggregation": {"method": "sum", "additivity": "additive"},
                "time": {
                    "grains": ["total"],
                    "timezone": "unknown",
                    "attribution_window": None,
                },
                "entity_uri": "entity://gravity/app@1",
                "formula": {
                    "operator": "source",
                    "dependencies": [],
                    "parameters": [],
                },
                "binding_required": True,
                "claim_policy": {
                    "allowed": ["returned-row observation"],
                    "forbidden": ["causality", "complete total"],
                },
            }
        ],
        "bindings": [
            {
                "artifact_kind": "semantic_binding",
                "schema_version": "gravity.semantic-binding.v1",
                "binding_uri": "binding://project/acquisition-spend.merge2-legacy@1",
                "semantic_uri": "metric://project/acquisition-spend@1",
                "project_id": "merge2",
                "owner": "growth-data",
                "app_alias": "merge2-legacy",
                "effective_range": {"start": None, "end": None},
                "provider": {
                    "kind": "semantic_compose",
                    "definition": {
                        "definition_id": "report.ap-cost-observation",
                        "version": 2,
                    },
                    "members": {
                        "metric": {
                            "definition_id": "report.metric.ap-cost",
                            "version": 1,
                        },
                        "dimension": {
                            "definition_id": "report.dimension.click-company",
                            "version": 1,
                        },
                        "filter": {
                            "definition_id": "report.filter.click-company",
                            "version": 1,
                        },
                        "grain": {
                            "definition_id": "report.grain.total",
                            "version": 1,
                        },
                        "join": {
                            "definition_id": "report.join.adreport-click-company",
                            "version": 1,
                        },
                    },
                },
                "parameters": {},
            }
        ],
    }


def project_overlay():
    return {
        "artifact_kind": "project_skill_overlay",
        "schema_version": "gravity.project-skill-overlay.v1",
        "overlay_uri": "skill://project.merge2/ap-cost-anomaly-localization@1.0.0",
        "version": "1.0.0",
        "project_id": "merge2",
        "owner": "growth-data",
        "extends": {"skill_uri": SKILL_URI},
        "journey_id": JOURNEY_ID,
        "semantic_sources": ["semantic.json"],
        "semantic_scope": {"app_alias": "merge2-legacy"},
        "context_requirements": [context_requirement()],
        "default_scope": {"app_alias": "merge2-legacy"},
    }


class ProjectSkillOverlayTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "metric.md").write_text("# Metric\nFact.", encoding="utf-8")
        (self.root / "docs" / "attribution.md").write_text("# Attribution\nData.", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "init", "-b", "test"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "R09A Test"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "r09a@example.invalid"], check=True)

    def tearDown(self):
        self.temporary.cleanup()

    def write_and_commit(self, value=None):
        (self.root / "overlay.json").write_text(json.dumps(value or project_overlay()), encoding="utf-8")
        (self.root / "semantic.json").write_text(json.dumps(project_semantic_source()), encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.root), "commit", "-m", "fixture"], check=True, capture_output=True)

    def test_compile_and_load_exact_tracked_overlay(self):
        expected = compile_project_skill_overlay(project_overlay())
        self.write_and_commit()

        result = load_project_skill_overlay(self.root, contract_path="overlay.json")

        self.assertEqual(expected["digest"], result["digest"])
        self.assertEqual(SKILL_URI, result["contract"]["extends"]["skill_uri"])
        self.assertEqual(["semantic.json"], result["contract"]["semantic_sources"])
        self.assertEqual(1, len(result["semantic_sources"]))
        self.assertFalse(result["network_called"])

    def test_override_fields_and_context_authority_drift_fail_closed(self):
        for field in ("trust", "claim_policy", "selector", "effects", "privacy"):
            value = project_overlay()
            value[field] = {}
            with self.subTest(field=field), self.assertRaises(ProjectSkillOverlayError):
                compile_project_skill_overlay(value)

        wrong = project_overlay()
        wrong["context_requirements"][0]["skill_uri"] = "skill://gravity.game/other@1.0.0"
        with self.assertRaisesRegex(ProjectSkillOverlayError, "local Skill boundary"):
            compile_project_skill_overlay(wrong)

    def test_dirty_missing_and_escaping_sources_are_rejected(self):
        self.write_and_commit()
        (self.root / "semantic.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(ProjectSkillOverlayError):
            load_project_skill_overlay(self.root, contract_path="overlay.json")

        escaping = project_overlay()
        escaping["semantic_sources"] = ["../semantic.json"]
        with self.assertRaises(ProjectSkillOverlayError):
            compile_project_skill_overlay(escaping)

    def test_project_change_updates_digest_without_runtime_change(self):
        first = project_overlay()
        second = copy.deepcopy(first)
        second["context_requirements"][0]["items"][0]["title"] = "Updated project title"

        self.assertNotEqual(
            compile_project_skill_overlay(first)["digest"],
            compile_project_skill_overlay(second)["digest"],
        )


if __name__ == "__main__":
    unittest.main()
