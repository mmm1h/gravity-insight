from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import zipfile

from gravity_sdk.agent_runtime_contracts import canonical_digest, load_json_object
from gravity_sdk.journey_contract import journey_artifact, journey_artifacts
from gravity_sdk.journey_service import JourneyService
from gravity_sdk.skill_contract import (
    compile_skill_manifest,
    skill_artifacts,
    validate_skill_journey_parity,
)
from gravity_sdk.skill_hub_archive import validate_skill_archive
from gravity_sdk.skill_hub_contract import compile_hub_index, compile_hub_source
from gravity_sdk.skill_hub_locks import compile_skills_lock
from gravity_sdk.thinkingai_inventory import load_inventory_snapshot
from gravity_sdk.thinkingai_representative import (
    ThinkingAIRepresentativeError,
    compile_representative_eval,
    compile_representative_set,
    validate_representative_eval,
    validate_representative_set,
)
from scripts.generate_thinkingai_representatives import (
    EVAL_TARGET,
    INDEX_TARGET,
    LOCK_TARGET,
    SET_TARGET,
    SOURCE_TARGET,
    render_outputs,
)


ROOT = Path(__file__).resolve().parents[1]
CONTENT_ROOT = ROOT / "content" / "thinkingai" / "representative"
SKILL_ROOT = CONTENT_ROOT / "skills"
SNAPSHOT = next(
    (
        ROOT / "src" / "gravity_sdk" / "contracts" / "thinkingai" / "snapshots"
    ).glob("*.json")
)


class _NoClientSDK:
    def __init__(self, workspace):
        self.workspace = workspace

    @property
    def insight(self):
        raise AssertionError("CT02 inspection constructed an Insight client")

    @property
    def sql(self):
        raise AssertionError("CT02 inspection constructed a SQL client")


class ThinkingAIRepresentativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = load_inventory_snapshot(SNAPSHOT)
        cls.source = compile_hub_source(load_json_object(SOURCE_TARGET, "CT02 source"))
        cls.index = compile_hub_index(
            load_json_object(INDEX_TARGET, "CT02 index"), runtime_version="0.3.0"
        )
        cls.representative_set = validate_representative_set(
            load_json_object(SET_TARGET, "CT02 representative set")
        )
        cls.evaluation = validate_representative_eval(
            load_json_object(EVAL_TARGET, "CT02 representative eval")
        )

    def assert_reason(self, reason_code: str, function, *args) -> None:
        with self.assertRaises(ThinkingAIRepresentativeError) as raised:
            function(*args)
        self.assertEqual(reason_code, raised.exception.reason_code)

    def test_five_standard_manifests_journeys_and_packages_validate(self) -> None:
        self.assertEqual(5, len(self.index["skills"]))
        self.assertEqual(11, len(journey_artifacts()))
        self.assertEqual(1, len(skill_artifacts()), "Team Skills must not become Built-ins")
        for identity, entry in self.index["skills"].items():
            with self.subTest(skill_uri=identity):
                manifest = compile_skill_manifest(entry["manifest"])
                journey = journey_artifact(manifest["covers_journeys"][0])
                self.assertIsNotNone(journey)
                self.assertEqual(identity, journey["contract"]["required_skill"])
                validate_skill_journey_parity(manifest, journey["contract"])
                archive_path = ROOT.joinpath(*entry["archive"]["path"].split("/"))
                content = archive_path.read_bytes()
                validate_skill_archive(content, entry)
                with zipfile.ZipFile(archive_path) as archive:
                    names = archive.namelist()
                self.assertNotIn("scripts/", repr(names))
                self.assertEqual(sorted(names), names)

    def test_selection_and_eval_are_derived_from_sources(self) -> None:
        records = [
            {
                "manifest": entry["manifest"],
                "archive_sha256": entry["archive"]["sha256"],
            }
            for entry in self.index["contract"]["skills"]
        ]
        compiled = compile_representative_set(records, self.snapshot)
        self.assertEqual(self.representative_set, compiled)
        self.assertEqual(self.evaluation, compile_representative_eval(compiled))
        self.assertEqual(
            {
                "capability_only",
                "project_semantic",
                "deterministic_operator",
                "required_context",
                "blocked_model",
            },
            {item["dependency_shape"] for item in compiled["representatives"]},
        )
        self.assertEqual(
            {"happy", "empty", "partial", "gap", "invalid", "claim_boundary", "prompt_injection", "marketing_leakage"},
            {item["scenario"] for item in self.evaluation["cases"]},
        )
        for case in self.evaluation["cases"]:
            if case["expected_outcome"] in {"blocked", "reject"}:
                self.assertEqual([], case["allowed_claims"])
            self.assertFalse(case["network_called"])

    def test_current_generic_journey_readiness_is_precise_and_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = JourneyService(
                _NoClientSDK(SimpleNamespace(root=root, state_root=root / "state"))
            )
            cases = {
                "analysis.thinkingai.device-segment-event-review": {"SKILL_DEPENDENCY_UNRESOLVED"},
                "analysis.thinkingai.project-metric-contract-check": {
                    "SEMANTIC_DEFINITION_MISSING", "SKILL_DEPENDENCY_UNRESOLVED"
                },
                "analysis.thinkingai.returned-filter-comparison": {"SKILL_DEPENDENCY_UNRESOLVED"},
                "analysis.thinkingai.community-context-correlation": {
                    "CONTEXT_REQUIRED_MISSING", "SKILL_DEPENDENCY_UNRESOLVED"
                },
                "analysis.thinkingai.revenue-forecast-readiness": {
                    "MODEL_UNVALIDATED", "SKILL_DEPENDENCY_UNRESOLVED"
                },
            }
            self.assertEqual(11, service.list()["count"])
            for journey_id, expected in cases.items():
                with self.subTest(journey_id=journey_id):
                    described = service.describe(journey_id)
                    readiness = service.can_run(journey_id)
                    self.assertEqual("blocked", readiness["can_run_status"])
                    self.assertTrue(expected <= set(readiness["reason_codes"]))
                    self.assertEqual(
                        journey_id, described["journey"]["journey_id"]
                    )
                    self.assertNotIn("argv", repr(described))
                    self.assertFalse(readiness["network_called"])

    def test_independent_content_has_no_source_title_marketing_or_injection_text(self) -> None:
        source_titles = {
            item["source_id"]: item["source_title"]
            for item in self.snapshot["items"]
        }
        forbidden = (
            "ignore previous instructions",
            "customer result improved",
            "guaranteed lift",
            "marketing effect",
        )
        for path in sorted(SKILL_ROOT.glob("*.json")):
            manifest = load_json_object(path, path.name)
            text = "\n".join(
                [
                    manifest["summary"],
                    manifest["description"],
                    manifest["guide"]["title"],
                    manifest["guide"]["applicability"],
                    manifest["guide"]["context_boundary"],
                    *manifest["guide"]["steps"],
                ]
            )
            with self.subTest(source_id=manifest["skill_id"]):
                self.assertNotIn(source_titles[manifest["skill_id"]].casefold(), text.casefold())
                self.assertFalse(any(marker in text.casefold() for marker in forbidden))
                self.assertNotRegex(text, r"\b\d+(?:\.\d+)?\s*(?:%|x\b|倍)")

    def test_digest_content_and_eval_tampering_fail_closed(self) -> None:
        changed = copy.deepcopy(self.representative_set)
        changed["representatives"][0]["archive_sha256"] = "0" * 64
        self.assert_reason(
            "THINKINGAI_REPRESENTATIVE_DIGEST_INVALID",
            validate_representative_set,
            changed,
        )

        records = [
            {
                "manifest": copy.deepcopy(entry["manifest"]),
                "archive_sha256": entry["archive"]["sha256"],
            }
            for entry in self.index["contract"]["skills"]
        ]
        records[0]["manifest"]["description"] = next(
            item["source_title"]
            for item in self.snapshot["items"]
            if item["source_id"] == records[0]["manifest"]["skill_id"]
        )
        self.assert_reason(
            "THINKINGAI_REPRESENTATIVE_CONTENT_LEAKAGE",
            compile_representative_set,
            records,
            self.snapshot,
        )

        evaluation = copy.deepcopy(self.evaluation)
        blocked = next(
            case for case in evaluation["cases"] if case["expected_outcome"] == "blocked"
        )
        blocked["allowed_claims"] = ["causality"]
        evaluation.pop("eval_sha256")
        evaluation["eval_sha256"] = canonical_digest(evaluation)
        self.assert_reason(
            "THINKINGAI_REPRESENTATIVE_EVAL_INVALID",
            validate_representative_eval,
            evaluation,
        )

    def test_generator_outputs_are_deterministic_before_or_after_lock_binding(self) -> None:
        revision = None
        if LOCK_TARGET.is_file():
            lock = compile_skills_lock(
                load_json_object(LOCK_TARGET, "CT02 representative lock")
            )
            revision = lock["source"]["source_revision"]
        outputs = render_outputs(revision)
        self.assertTrue(outputs)
        for path, content in outputs.items():
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertTrue(path.is_file())
                self.assertEqual(content, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
