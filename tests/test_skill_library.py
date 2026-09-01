from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

from gravity_insight.external_method_registry import SOURCE_REF_PREFIX, load_source_registry
from gravity_insight.journey_contract import journey_artifact
from gravity_insight.skill_contract import compile_skill_manifest, skill_uri
from scripts.generate_skill_library import load_canonical_skills


ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "skills" / "library"
CORE_SKILLS = {
    "analysis-metric-definition-alignment",
    "dashboard-no-data-diagnosis",
    "data-access-assistant",
    "data-integration-assistant",
    "filter-result-bias-diagnosis",
    "operation-journey-canvas-creation",
    "sql-performance-optimization",
    "system-field-reference-guide",
    "trino-metadata-query-analysis",
    "user-tag-system-design",
}
JOURNEYS = {
    "analysis.gravity.core.project-metric-contract-check",
    "analysis.gravity.core.returned-filter-comparison",
    "analysis.gravity.game.community-context-correlation",
    "analysis.gravity.game.device-segment-event-review",
    "analysis.gravity.game.revenue-forecast-readiness",
}


class SkillLibraryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifests = load_canonical_skills()
        cls.by_id = {item["skill_id"]: item for item in cls.manifests}
        cls.registry = load_source_registry()

    def test_library_has_one_canonical_manifest_per_skill(self) -> None:
        self.assertEqual(40, len(self.manifests))
        self.assertEqual(40, len(list(LIBRARY.glob("*.json"))))
        self.assertEqual(40, len(self.by_id))

    def test_every_canonical_manifest_matches_skill_schema(self) -> None:
        for path in sorted(LIBRARY.glob("*.json")):
            with self.subTest(path=path.name):
                value = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(value, compile_skill_manifest(value, label=path.name))

    def test_core_namespace_is_used_only_for_reusable_methods(self) -> None:
        actual = {
            item["skill_id"] for item in self.manifests
            if item["namespace"] == "gravity.core"
        }
        self.assertEqual(CORE_SKILLS, actual)

    def test_remaining_methods_use_cross_game_namespace(self) -> None:
        game = [item for item in self.manifests if item["namespace"] == "gravity.game"]
        self.assertEqual(30, len(game))

    def test_machine_identities_are_stable_english(self) -> None:
        for manifest in self.manifests:
            with self.subTest(skill=manifest["skill_id"]):
                self.assertRegex(manifest["skill_id"], r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
                self.assertRegex(skill_uri(manifest), r"^skill://[a-z0-9./-]+@[0-9.]+$")

    def test_visible_method_content_defaults_to_chinese(self) -> None:
        chinese = re.compile(r"[\u3400-\u9fff]")
        for manifest in self.manifests:
            visible = [
                manifest["summary"], manifest["description"],
                manifest["guide"]["title"], manifest["guide"]["applicability"],
                manifest["guide"]["context_boundary"], *manifest["guide"]["steps"],
            ]
            with self.subTest(skill=manifest["skill_id"]):
                self.assertTrue(all(chinese.search(text) for text in visible))

    def test_provenance_uses_only_opaque_registry_refs(self) -> None:
        refs = {SOURCE_REF_PREFIX + item["opaque_id"] for item in self.registry["items"]}
        for manifest in self.manifests:
            with self.subTest(skill=manifest["skill_id"]):
                self.assertIn(manifest["provenance"]["source_ref"], refs)
                self.assertEqual("independently_authored", manifest["provenance"]["authorship"])

    def test_every_applicable_source_has_one_canonical_manifest(self) -> None:
        expected = {
            item["future_skill_uri"]
            for item in self.registry["items"]
            if item["mapping_kind"] == "future_skill"
        }
        self.assertEqual(
            expected,
            {skill_uri(manifest) for manifest in self.manifests},
        )

    def test_five_library_journeys_use_neutral_ids(self) -> None:
        actual = {
            journey for manifest in self.manifests for journey in manifest["covers_journeys"]
        }
        self.assertEqual(JOURNEYS, actual)

    def test_journey_and_skill_bindings_are_exact(self) -> None:
        for journey_id in JOURNEYS:
            artifact = journey_artifact(journey_id)
            self.assertIsNotNone(artifact)
            manifest = next(
                item for item in self.manifests if journey_id in item["covers_journeys"]
            )
            self.assertEqual(skill_uri(manifest), artifact["contract"]["required_skill"])

    def test_canonical_skill_files_contain_no_source_urls(self) -> None:
        for path in LIBRARY.glob("*.json"):
            with self.subTest(path=path.name):
                self.assertNotIn("https://", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
