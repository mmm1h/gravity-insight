from __future__ import annotations

import copy
import json
import unittest

from gravity_insight.operator_registry import OperatorRegistry
from gravity_insight.skill_render import render_agent_export
from scripts.generate_skill_library import _artifact, load_canonical_skills


MIGRATIONS = {
    "payment-conversion-funnel": ("funnel-diagnosis", "cumulative"),
    "level-churn-diagnosis": ("funnel-diagnosis", "rowwise"),
    "funnel-analysis-misunderstanding-diagnosis": ("funnel-diagnosis", "cumulative"),
    "gift-penetration-optimization": ("metric-decomposition", "rowwise"),
    "game-campaign-effect-evaluation": ("campaign-outcome-evaluation", "rowwise"),
    "community-weekly-report": ("sentiment-aggregation", "aggregate"),
    "community-daily-report": ("sentiment-aggregation", "aggregate"),
    "community-comment-analysis": ("sentiment-aggregation", "aggregate"),
}


class SkillTriggerContentTests(unittest.TestCase):
    """Content and arithmetic contracts, not real-host trigger-quality evals."""

    @classmethod
    def setUpClass(cls):
        cls.manifests = load_canonical_skills()
        cls.by_id = {item["skill_id"]: item for item in cls.manifests}
        cls.registry = OperatorRegistry()

    def test_every_revision_has_scope_and_missing_input_examples_in_projection(self):
        for manifest in self.manifests:
            with self.subTest(skill=manifest["skill_id"]):
                examples = manifest["method"]["examples"]["run_examples"]
                near = next(e for e in examples if e["example_id"] == "near-neighbor-out-of-scope")
                missing = [e for e in examples if e["example_id"] == "missing-required-contract"]
                self.assertTrue(missing)
                self.assertTrue(any(e["scenario"] == "success" for e in examples))
                self.assertEqual(("gap", [], False), (
                    near["expected"]["status"], near["expected"]["allowed_claims"],
                    near["expected"]["network_called"],
                ))
                export = render_agent_export(_artifact(manifest), self.manifests)
                files = {row["path"]: row["content"] for row in export["files"]}
                description = json.loads(files["SKILL.md"].splitlines()[2].split(":", 1)[1])
                self.assertEqual(manifest["description"], description)
                self.assertIn(near["question"], files["references/EXAMPLES.md"])
                self.assertIn(missing[0]["question"], files["references/EXAMPLES.md"])

    def test_payment_subset_keeps_local_conversion_and_boundary_loss_distinct(self):
        manifest = self.by_id["payment-conversion-funnel"]
        example = next(e for e in manifest["method"]["examples"]["run_examples"]
                       if e["example_id"] == "operator-v2-subset-boundary")
        request = example["input_template"]
        result = self.registry.execute(request["operator_uri"], request["operator_input"])
        self.assertTrue(result["ok"], result)
        self.assertEqual("0.4", result["result"]["metrics"]["cumulative_conversion"])
        rows = {r["key"]: r for r in result["result"]["ranked_rows"]}
        self.assertEqual("0.666667", rows["payment"]["value"])
        self.assertEqual("20", rows["payment"]["contribution"])
        self.assertIn("entities_entering_step_k", manifest["method"]["formulas"][0]["expression"])

    def test_host_handoff_order_commands_and_legacy_render_boundary(self):
        from gravity_insight.cli import build_parser
        from gravity_insight.skill_render import _host_handoff, render_guide
        manifest = self.by_id["retention-analysis-data-verification"]
        guide = render_guide(manifest)
        commands = [
            ["agent-catalog", "categories"],
            ["agent-catalog", "category", "analysis"],
            ["agent-catalog", "describe", "analysis.query.spec:event"],
            ["agent-catalog", "host"],
            ["agent", "--host-selection", "selection.json"],
            ["agent", "question", "--routing", "recognizer"],
        ]
        for argv in commands:
            build_parser().parse_args(argv)
        self.assertLess(guide.index("1. "), guide.index("gravity agent-catalog categories"))
        self.assertLess(guide.index("gravity agent-catalog host"), guide.index("--routing recognizer"))
        self.assertIn("schema_argv", guide)
        self.assertIn("next.argv", guide)
        legacy = copy.deepcopy(manifest)
        legacy["method"]["method_revision"] = 1
        self.assertEqual([], _host_handoff(legacy))
        self.assertNotIn("## Host Entry and Handoff", render_guide(legacy))

    def test_eight_canonical_requests_execute_with_their_scoped_golden_results(self):
        for skill_id, (method, mode) in MIGRATIONS.items():
            with self.subTest(skill=skill_id):
                manifest = self.by_id[skill_id]
                uri = f"operator://gravity/{method}@2"
                self.assertEqual([uri], manifest["operator_dependencies"])
                example = next(e for e in manifest["method"]["examples"]["run_examples"]
                               if e["example_id"] == "operator-v2-conformance")
                request = example["input_template"]
                self.assertEqual(uri, request["operator_uri"])
                result = self.registry.execute(uri, request["operator_input"])
                self.assertTrue(result["ok"], result)
                self.assertFalse(result["network_called"])
                self.assertEqual(mode, result["result"]["mode"])
                metrics = result["result"]["metrics"]
                if mode == "cumulative":
                    self.assertEqual("0.4", metrics["cumulative_conversion"])
                elif mode == "aggregate":
                    self.assertEqual("100", metrics["returned_total"])
                    self.assertEqual(["0.6", "0.4"], [r["contribution"] for r in result["result"]["ranked_rows"]])
                elif method == "funnel-diagnosis":
                    self.assertNotIn("cumulative_conversion", metrics)
                    self.assertEqual(["0.5", "0.8"], [r["value"] for r in result["result"]["ranked_rows"]])
                else:
                    self.assertEqual({}, metrics)
                    self.assertEqual(["0.04", "-0.04"], [r["contribution"] for r in result["result"]["ranked_rows"]])

    def test_cross_row_examples_fail_closed_without_evidence_and_preserve_partial(self):
        for skill_id, (method, mode) in MIGRATIONS.items():
            with self.subTest(skill=skill_id):
                example = next(e for e in self.by_id[skill_id]["method"]["examples"]["run_examples"]
                               if e["example_id"] == "operator-v2-conformance")
                request = copy.deepcopy(example["input_template"]["operator_input"])
                uri = example["input_template"]["operator_uri"]
                if mode == "cumulative":
                    del request["rows"][1]["lineage"]
                elif mode == "aggregate":
                    del request["aggregation"]
                else:
                    for scope in request["rows"][0]["scopes"].values():
                        scope["completeness"] = "prefix"
                result = self.registry.execute(uri, request)
                if mode == "rowwise":
                    self.assertTrue(result["ok"], result)
                    self.assertEqual("prefix", result["result"]["completeness"])
                else:
                    self.assertFalse(result["ok"], result)
                    self.assertIsNone(result["result"])
