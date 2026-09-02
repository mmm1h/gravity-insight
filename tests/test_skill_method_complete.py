from __future__ import annotations

import copy
from pathlib import Path
import unittest

from gravity_insight.agent_runtime_contracts import (
    AgentRuntimeContractError,
    validate_schema,
)
from gravity_insight.skill_contract import SkillContractError, compile_skill_manifest
from gravity_insight.model_registry import ModelRegistry
from gravity_insight.operator_registry import OperatorRegistry
from gravity_insight.project_skill_overlay import compile_project_skill_overlay
from gravity_insight.semantic_contract import compile_semantic_source
from gravity_insight.skill_render import render_project_bindings_template
from scripts.generate_method_gap_report import CRITERIA, compact_report, library_report
from scripts.generate_skill_library import load_canonical_skills


ROOT = Path(__file__).resolve().parents[1]
COMPLETE_SKILLS = {
    "ad-delivery-analysis",
    "ap-cost-anomaly-localization",
    "analysis-metric-definition-alignment",
    "app-device-performance-analysis",
    "channel-quality-analysis",
    "churn-user-identification-persona",
    "community-comment-analysis",
    "community-daily-report",
    "community-hot-topic-analysis",
    "community-weekly-report",
    "dashboard-no-data-diagnosis",
    "data-access-assistant",
    "data-integration-assistant",
    "filter-result-bias-diagnosis",
    "first-purchase-analysis",
    "funnel-analysis-misunderstanding-diagnosis",
    "game-campaign-effect-evaluation",
    "game-revenue-forecast",
    "gift-package-push-strategy",
    "gift-penetration-optimization",
    "level-churn-diagnosis",
    "lt-prediction",
    "ltv-analysis-monitoring",
    "ltv-curve-fitting-segmented-calculation",
    "ltv-dashboard-setup",
    "ltv-payback-period-prediction",
    "new-hero-launch-insight",
    "operation-journey-canvas-creation",
    "payment-attribution-analysis",
    "payment-conversion-funnel",
    "payment-funnel-setup",
    "payment-rate-anomaly-diagnosis",
    "product-pricing-optimization",
    "pvp-win-rate-analysis",
    "repurchase-analysis",
    "report-data-mismatch-diagnosis",
    "retention-analysis-data-verification",
    "single-user-behavior-analysis",
    "sql-performance-optimization",
    "system-field-reference-guide",
    "tracking-plan-generation",
    "trino-metadata-query-analysis",
    "user-tag-system-design",
    "user-id-binding-diagnosis",
}


def materialize_semantic_source(template: dict, skill_id: str) -> dict:
    source = copy.deepcopy(template)
    source.update(
        {
            "source_id": f"audit/{skill_id}",
            "project_id": "audit",
            "owner": "audit-owner",
        }
    )
    for definition in source["definitions"]:
        definition.update(
            {
                "owner": "audit-owner",
                "display_name": f"Audit {definition['uri']}",
                "description": "Synthetic contract-shape validation only.",
                "effective_range": {"start": None, "end": None},
                "claim_policy": {
                    "allowed": ["returned-row observation"],
                    "forbidden": ["causality"],
                },
            }
        )
        if definition["kind"] == "metric":
            definition.update(
                {
                    "unit": {
                        "kind": "count",
                        "symbol": "count",
                        "currency": None,
                        "scale": 0,
                    },
                    "aggregation": {
                        "method": "sum",
                        "additivity": "additive",
                    },
                    "time": {
                        "grains": ["day"],
                        "timezone": "UTC",
                        "attribution_window": None,
                    },
                    "entity_uri": "entity://gravity/app@1",
                    "formula": {
                        "operator": "source",
                        "dependencies": [],
                        "parameters": [],
                    },
                }
            )
    for index, binding in enumerate(source["bindings"], 1):
        binding.update(
            {
                "binding_uri": f"binding://audit/{skill_id}-{index}@1",
                "project_id": "audit",
                "owner": "audit-owner",
                "app_alias": "audit-app",
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
                        }
                    },
                },
                "parameters": {},
            }
        )
    return source


def materialize_overlay(template: dict, skill_id: str) -> dict:
    overlay = copy.deepcopy(template)
    overlay.update(
        {
            "overlay_uri": f"skill://project.audit/{skill_id}@1.0.0",
            "project_id": "audit",
            "owner": "audit-owner",
            "journey_id": "analysis.audit",
            "semantic_sources": ["semantic.json"],
            "semantic_scope": {"app_alias": "audit-app"},
            "default_scope": {"app_alias": "audit-app"},
        }
    )
    for index, requirement in enumerate(overlay["context_requirements"], 1):
        requirement.update(
            {
                "journey_id": "analysis.audit",
                "subject_entities": ["entity://gravity/app@1"],
                "required_windows": ["current", "reference"],
                "authority_policy": {
                    "required": ["project_authoritative"],
                    "allow_supporting": False,
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
            }
        )
        requirement["items"][0].update(
            {
                "item_id": f"context-{index}",
                "fact_id": f"fact-{index}",
                "path": f"docs/context-{index}.md",
                "title": f"Context {index}",
                "resource_type": "contract",
                "entity_refs": ["entity://gravity/app@1"],
                "valid_time": {
                    "start": None,
                    "end": None,
                    "timezone": "UTC",
                },
                "effective_range": {"start": None, "end": None},
                "authority": "project_authoritative",
                "sensitivity": "internal",
                "supersedes": [],
                "max_age_days": None,
            }
        )
    return overlay


class SkillMethodCompleteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = library_report(ROOT)

    def test_gate_has_exactly_seventeen_traceable_criteria(self) -> None:
        self.assertEqual(list(range(1, 18)), [item.item for item in CRITERIA])
        self.assertEqual(17, len({item.key for item in CRITERIA}))
        self.assertEqual({"structural", "proxy"}, {item.evaluation for item in CRITERIA})
        for item in CRITERIA:
            with self.subTest(item=item.item):
                self.assertEqual(item.evaluation == "proxy", item.proxy_for is not None)
                self.assertEqual(item.evaluation == "proxy", item.cannot_prove is not None)

    def test_report_covers_every_canonical_skill_and_every_item(self) -> None:
        self.assertEqual(44, self.report["summary"]["skill_count"])
        self.assertEqual(44, len(self.report["skills"]))
        for row in self.report["skills"]:
            with self.subTest(skill=row["skill_uri"]):
                self.assertEqual(17, len(row["items"]))
                self.assertEqual(17, row["achieved_count"] + row["missing_count"])
                self.assertEqual(row["method_complete"], not row["missing_items"])

    def test_compact_command_report_retains_each_skill_item_result(self) -> None:
        compact = compact_report(self.report)
        self.assertEqual(self.report["summary"], compact["summary"])
        self.assertTrue(all(len(row["items"]) == 17 for row in compact["skills"]))

    def test_all_canonical_methods_are_complete(self) -> None:
        complete = {
            row["skill_id"] for row in self.report["skills"]
            if row["method_complete"]
        }
        self.assertEqual(COMPLETE_SKILLS, complete)
        self.assertEqual(44, self.report["summary"]["method_complete_true"])
        self.assertEqual(0, self.report["summary"]["method_complete_false"])
        manifests = {
            item["skill_id"]: item for item in load_canonical_skills()
        }
        for row in self.report["skills"]:
            if row["skill_id"] in COMPLETE_SKILLS:
                with self.subTest(skill=row["skill_id"]):
                    self.assertEqual(17, row["achieved_count"])
                    examples = manifests[row["skill_id"]]["method"]["examples"][
                        "run_examples"
                    ]
                    self.assertGreaterEqual(len(examples), 3)
                    self.assertEqual(
                        {"success", "empty_or_partial", "blocked_or_gap"},
                        {item["scenario"] for item in examples},
                    )

    def test_incomplete_skills_are_sorted_by_completion_cost(self) -> None:
        costs = [
            row["estimated_completion_cost"]
            for row in self.report["skills"]
            if not row["method_complete"]
        ]
        self.assertEqual(sorted(costs), costs)

    def test_unfinished_method_is_state_not_contract_failure(self) -> None:
        manifest = load_canonical_skills()[0]
        manifest.pop("method", None)
        self.assertEqual(manifest, compile_skill_manifest(manifest))

    def test_method_cross_references_fail_closed(self) -> None:
        complete = next(
            (item for item in load_canonical_skills() if "method" in item),
            None,
        )
        self.assertIsNotNone(complete)
        invalid = copy.deepcopy(complete)
        invalid["method"]["examples"]["eval_cases"][0]["expected_sections"] = [
            "missing-section",
            invalid["method"]["result"]["sections"][0]["section_id"],
        ]
        with self.assertRaisesRegex(SkillContractError, "unknown result section"):
            compile_skill_manifest(invalid)

    def test_unregistered_dependency_cannot_masquerade_as_available(self) -> None:
        complete = next(
            item for item in load_canonical_skills()
            if item["skill_id"] == "ltv-payback-period-prediction"
        )
        invalid = copy.deepcopy(complete)
        dependency = next(
            item for item in invalid["method"]["dependency_status"]
            if item["kind"] == "operator"
        )
        missing = "operator://gravity/not-registered@1"
        invalid["operator_dependencies"] = [
            missing if item == dependency["identity"] else item
            for item in invalid["operator_dependencies"]
        ]
        dependency["identity"] = missing
        with self.assertRaisesRegex(SkillContractError, "not registered"):
            compile_skill_manifest(invalid)

    def test_unavailable_runtime_dependencies_require_blocked_readiness(self) -> None:
        complete = next(
            item for item in load_canonical_skills()
            if item["skill_id"] == "ltv-payback-period-prediction"
        )
        invalid = copy.deepcopy(complete)
        dependency = next(
            item for item in invalid["method"]["dependency_status"]
            if item["kind"] == "operator"
        )
        dependency.update(
            {
                "status": "unavailable",
                "reason_code": "OPERATOR_UNAVAILABLE",
                "evidence": "Runtime dependency is intentionally unavailable in this negative fixture.",
            }
        )
        with self.assertRaisesRegex(SkillContractError, "blocked readiness"):
            compile_skill_manifest(invalid)

    def test_m4_runtime_dependencies_and_project_templates_are_exact(self) -> None:
        manifests = load_canonical_skills()
        operator_uris = sorted(
            {uri for item in manifests for uri in item["operator_dependencies"]}
        )
        model_uris = sorted(
            {uri for item in manifests for uri in item["model_dependencies"]}
        )
        self.assertTrue(OperatorRegistry().dependencies(operator_uris)["ok"])
        self.assertTrue(ModelRegistry().dependencies(model_uris)["ok"])
        self.assertTrue(
            all(
                item["readiness"] == "executable"
                and item["validation"] == "validated"
                for item in manifests
            )
        )
        self.assertTrue(
            all(
                gap["kind"] in {"semantic", "context"}
                for row in self.report["skills"]
                for gap in row["dependency_gaps"]
            )
        )
        for manifest in manifests:
            with self.subTest(skill=manifest["skill_id"]):
                template = render_project_bindings_template(manifest)
                self.assertEqual(
                    manifest["semantic_dependencies"],
                    [item["uri"] for item in template["semantic_dependencies"]],
                )
                self.assertEqual(
                    manifest["context_dependencies"]["required"],
                    [
                        item["uri"]
                        for item in template["context_dependencies"]
                        if item["required"]
                    ],
                )

    def test_project_templates_materialize_into_canonical_contract_shapes(self) -> None:
        for manifest in load_canonical_skills():
            with self.subTest(skill=manifest["skill_id"]):
                template = render_project_bindings_template(manifest)
                source = materialize_semantic_source(
                    template["semantic_source_template"],
                    manifest["skill_id"],
                )
                overlay = materialize_overlay(
                    template["overlay_template"],
                    manifest["skill_id"],
                )
                self.assertEqual(
                    len(manifest["semantic_dependencies"]),
                    len(compile_semantic_source(source)["definitions"]),
                )
                self.assertEqual(
                    len(manifest["context_dependencies"]["required"]),
                    len(
                        compile_project_skill_overlay(overlay)["contract"][
                            "context_requirements"
                        ]
                    ),
                )

    def test_project_template_schema_rejects_nested_shape_drift(self) -> None:
        manifest = next(
            item
            for item in load_canonical_skills()
            if item["skill_id"] == "tracking-plan-generation"
        )
        template = render_project_bindings_template(manifest)
        invalid = copy.deepcopy(template)
        invalid["semantic_source_template"]["unexpected"] = True
        with self.assertRaises(AgentRuntimeContractError):
            validate_schema(
                invalid,
                "skill-project-bindings-template-v1.schema.json",
                "invalid project template",
            )

        invalid = copy.deepcopy(template)
        invalid["context_dependencies"][0]["requirement_template"]["items"][0].pop(
            "fact_id"
        )
        with self.assertRaises(AgentRuntimeContractError):
            validate_schema(
                invalid,
                "skill-project-bindings-template-v1.schema.json",
                "invalid project template",
            )

        invalid = copy.deepcopy(template)
        invalid["semantic_source_template"]["bindings"][0]["provider"]["members"][
            "unexpected"
        ] = None
        with self.assertRaises(AgentRuntimeContractError):
            validate_schema(
                invalid,
                "skill-project-bindings-template-v1.schema.json",
                "invalid project template",
            )

    def test_project_owned_dependencies_are_resolved_at_runtime(self) -> None:
        complete = next(
            item for item in load_canonical_skills()
            if item["skill_id"] == "analysis-metric-definition-alignment"
        )
        self.assertEqual("executable", complete["readiness"])
        self.assertTrue(
            any(
                item["status"] == "requires_project_binding"
                for item in complete["method"]["dependency_status"]
            )
        )
        self.assertEqual(complete, compile_skill_manifest(complete))


if __name__ == "__main__":
    unittest.main()
