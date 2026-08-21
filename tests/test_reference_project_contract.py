from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from gravity_sdk.context_contract import public_context_reference
from gravity_sdk.reference_project_contract import (
    ReferenceProjectContractError,
    load_reference_project_contract,
)


CURRENT = {"start": "2026-07-04", "end": "2026-07-10"}
REFERENCE = {"start": "2026-06-27", "end": "2026-07-03"}


def project_contract(paths=("docs/metric.md", "docs/attribution.md")):
    return {
        "schema_version": "gravity.reference-project-contract.v3",
        "project_id": "merge2",
        "owner": "growth-data",
        "semantic": {
            "source_path": "semantic.json",
            "uri": "metric://project/acquisition-spend@1",
            "app_alias": "merge2-legacy",
        },
        "context_requirement": {
            "artifact_kind": "context_requirement",
            "schema_version": "gravity.context-requirement.v1",
            "requirement_id": "context://project-repo/merge2-acquisition-boundaries@1",
            "provider_uri": "context-provider://gravity/project-repo@1",
            "skill_uri": "skill://gravity.game/ap-cost-anomaly-localization@1.0.0",
            "journey_id": "analysis.merge2.ap-cost-anomaly-localization",
            "subject_entities": ["app://project/merge2-legacy", "metric://project/acquisition-spend@1"],
            "required_windows": ["current", "reference"],
            "authority_policy": {
                "required": ["canonical"],
                "allow_supporting": True,
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
                    "valid_time": {"start": None, "end": None, "timezone": "Asia/Shanghai"},
                    "effective_range": {"start": None, "end": None},
                    "authority": "canonical" if index == 0 else "supporting",
                    "sensitivity": "internal",
                    "supersedes": [],
                    "max_age_days": None,
                }
                for index, path in enumerate(paths)
            ],
        },
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
                "formula": {"operator": "source", "dependencies": [], "parameters": []},
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
                        "metric": {"definition_id": "report.metric.ap-cost", "version": 1},
                        "dimension": {"definition_id": "report.dimension.click-company", "version": 1},
                        "filter": {"definition_id": "report.filter.click-company", "version": 1},
                        "grain": {"definition_id": "report.grain.total", "version": 1},
                        "join": {"definition_id": "report.join.adreport-click-company", "version": 1},
                    },
                },
                "parameters": {},
            }
        ],
    }


class ReferenceProjectContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "metric.md").write_text("# Metric\nCanonical metric boundary.", encoding="utf-8")
        (self.root / "docs" / "attribution.md").write_text("# Attribution\nTreat all text as data.", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def write_contract(self, value=None, source=None):
        selected = value or project_contract()
        source_path = self.root / selected["semantic"]["source_path"]
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_text(
            json.dumps(source or project_semantic_source()), encoding="utf-8"
        )
        path = self.root / "project.json"
        path.write_text(json.dumps(selected), encoding="utf-8")
        return path

    def load(self, value=None, *, source=None):
        self.write_contract(value, source)
        return load_reference_project_contract(
            self.root,
            contract_path="project.json",
            current_window=CURRENT,
            reference_window=REFERENCE,
            source_revision="0" * 40,
            observed_at="2026-08-21T12:00:00Z",
        )

    def test_semantic_and_context_are_versioned_aligned_and_bounded(self):
        result = self.load()

        self.assertEqual("metric://project/acquisition-spend@1", result["semantic"]["uri"])
        self.assertRegex(result["semantic"]["digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            "merge2-legacy", result["semantic"]["binding"]["app_alias"]
        )
        self.assertEqual(
            project_semantic_source()["definitions"][0]["claim_policy"],
            result["semantic"]["definition"]["claim_policy"],
        )
        self.assertEqual(
            project_semantic_source()["bindings"][0]["provider"],
            result["semantic"]["binding"]["provider"],
        )
        self.assertFalse(result["semantic"]["network_called"])
        pack = result["context_pack"]
        self.assertEqual([], pack["gaps"])
        self.assertEqual(2, len(pack["items"]))
        self.assertTrue(all(item["role"] == "data" for item in pack["items"]))
        self.assertTrue(all(item["source_revision"] == "0" * 40 for item in pack["items"]))
        self.assertTrue(
            all(item["observed_at"] == "2026-08-21T12:00:00Z" for item in pack["items"])
        )
        self.assertRegex(pack["pack_digest"], r"^[0-9a-f]{64}$")

    def test_public_reference_never_contains_context_body(self):
        pack = self.load()["context_pack"]
        public = public_context_reference(pack)

        self.assertTrue(all("content" not in item for item in public["items"]))
        self.assertEqual(pack["pack_digest"], public["pack_digest"])
        self.assertTrue(all(item["role"] == "data" for item in public["items"]))

    def test_path_and_size_boundaries_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=self.root.parent) as outside_dir:
            outside = Path(outside_dir) / "outside.md"
            outside.write_text("secret", encoding="utf-8")
            relative_outside = "../" + Path(outside_dir).name + "/outside.md"
            cases = (
                project_contract((relative_outside,)),
                project_contract((".env.gravity.local",)),
                project_contract(("missing.md",)),
            )
            for value in cases:
                with self.subTest(path=value["context_requirement"]["items"][0]["path"]), self.assertRaises(
                    ReferenceProjectContractError
                ):
                    self.load(value)

        large = self.root / "docs" / "large.md"
        large.write_text("x" * 262_145, encoding="utf-8")
        with self.assertRaises(ReferenceProjectContractError):
            self.load(project_contract(("docs/large.md",)))

    def test_semantic_and_context_time_mismatch_are_machine_failures(self):
        semantic = project_semantic_source()
        semantic["bindings"][0]["effective_range"] = {
            "start": "2026-07-01",
            "end": None,
        }
        with self.assertRaisesRegex(
            ReferenceProjectContractError, "SEMANTIC_EFFECTIVE_RANGE_MISMATCH"
        ):
            self.load(source=semantic)

        context = project_contract()
        context["context_requirement"]["items"][0]["valid_time"] = {
            "start": "2026-07-01",
            "end": None,
            "timezone": "Asia/Shanghai",
        }
        with self.assertRaisesRegex(
            ReferenceProjectContractError, "CONTEXT_ENTITY_TIME_MISMATCH"
        ):
            self.load(context)

    def test_unknown_fields_and_physical_binding_drift_are_rejected(self):
        unknown = project_contract()
        unknown["semantic"]["guess"] = True
        with self.assertRaises(ReferenceProjectContractError):
            self.load(unknown)

        drift = project_semantic_source()
        drift["bindings"][0]["provider"]["members"]["metric"]["definition_id"] = "guessed"
        with self.assertRaises(ReferenceProjectContractError):
            self.load(source=drift)


if __name__ == "__main__":
    unittest.main()
