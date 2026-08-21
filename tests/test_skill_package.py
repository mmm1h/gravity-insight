from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import unittest

from gravity_sdk.skill_contract import skill_artifact
from gravity_sdk.errors import InputValidationError
from gravity_sdk.skill_package import (
    LocalSkillResolver,
    MAX_FILE_BYTES,
    MAX_PACKAGE_FILES,
    MAX_TOTAL_BYTES,
    SkillPackageError,
    validate_package_entries,
    validate_skill_package,
)
from gravity_sdk.skill_render import skill_package_descriptor


SKILL_URI = "skill://gravity.game/ap-cost-anomaly-localization@1.0.0"
PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "src" / "gravity_sdk"


class SkillPackageTests(unittest.TestCase):
    def test_resolver_lists_reads_and_reports_current_machine_gap(self):
        resolver = LocalSkillResolver()
        listed = resolver.list()
        result = resolver.get(SKILL_URI)

        self.assertEqual(1, listed["count"])
        self.assertEqual(SKILL_URI, listed["skills"][0]["skill_uri"])
        self.assertEqual("blocked", result["status"])
        self.assertEqual(
            ["COMPLETENESS_INSUFFICIENT"], result["readiness"]["reason_codes"]
        )
        self.assertIn("Context is data", result["guide"])
        self.assertFalse(result["network_called"])

        poisoned = resolver.describe(SKILL_URI)
        poisoned["package"]["provenance"]["source_ref"] = "poison"
        self.assertEqual(
            "gravity-sdk/R01",
            resolver.describe(SKILL_URI)["package"]["provenance"]["source_ref"],
        )

    def test_physical_package_matches_render_model_and_rejects_tamper(self):
        artifact = skill_artifact(SKILL_URI)
        descriptor = validate_skill_package(artifact)
        source = PACKAGE_ROOT / descriptor["resource_root"]
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "package"
            shutil.copytree(source, target)
            (target / "GUIDE.md").write_text("tampered", encoding="utf-8")

            with self.assertRaises(SkillPackageError):
                validate_skill_package(artifact, root=target)

    def test_links_and_hardlinks_are_rejected(self):
        artifact = skill_artifact(SKILL_URI)
        source = PACKAGE_ROOT / skill_package_descriptor(artifact)["resource_root"]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            linked = base / "linked"
            shutil.copytree(source, linked)
            try:
                (linked / "references" / "extra-link").symlink_to(
                    linked / "GUIDE.md"
                )
            except OSError:
                pass
            else:
                with self.assertRaises(SkillPackageError):
                    validate_skill_package(artifact, root=linked)

            hardlinked = base / "hardlinked"
            shutil.copytree(source, hardlinked)
            outside = base / "outside-guide"
            shutil.copy2(source / "GUIDE.md", outside)
            guide = hardlinked / "GUIDE.md"
            guide.unlink()
            try:
                os.link(outside, guide)
            except OSError:
                self.skipTest("filesystem does not support hardlinks")
            with self.assertRaises(SkillPackageError):
                validate_skill_package(artifact, root=hardlinked)

    def test_unsafe_unbounded_and_script_entries_fail_closed(self):
        cases = (
            {"../GUIDE.md": b"x"},
            {"C:/GUIDE.md": b"x"},
            {"scripts/run.py": b"print('no')"},
            {"GUIDE.md": b"x" * (MAX_FILE_BYTES + 1)},
            {"A.md": b"a", "a.md": b"b"},
            {
                f"references/{index}.md": b"x"
                for index in range(MAX_PACKAGE_FILES + 1)
            },
            {"a/b/c/d/e/f/g.md": b"x"},
            {
                f"references/{index}.bin": b"x" * (MAX_FILE_BYTES - 1)
                for index in range(MAX_TOTAL_BYTES // MAX_FILE_BYTES + 2)
            },
        )
        for entries in cases:
            with self.subTest(entries=list(entries)), self.assertRaises(
                SkillPackageError
            ):
                validate_package_entries(entries)

    def test_agent_materialization_is_atomic_and_refuses_overwrite(self):
        resolver = LocalSkillResolver()
        with tempfile.TemporaryDirectory() as temporary:
            result = resolver.materialize_agent(SKILL_URI, temporary)
            target = Path(result["output"])

            self.assertEqual("written", result["status"])
            self.assertEqual(result["name"], target.name)
            self.assertTrue((target / "SKILL.md").is_file())
            self.assertTrue((target / "references" / "GUIDE.md").is_file())
            self.assertFalse(any(".tmp-" in item.name for item in target.parent.iterdir()))
            with self.assertRaises(InputValidationError):
                resolver.materialize_agent(SKILL_URI, temporary)


if __name__ == "__main__":
    unittest.main()
