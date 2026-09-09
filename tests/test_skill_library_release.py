from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import generate_skill_library as builder
from scripts.verify_skill_library_release import (
    PUBLISH_BASE,
    SkillLibraryReleaseError,
    verify_release,
)


class SkillLibraryReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        source = Path(temporary.name) / "source"
        source.mkdir()
        override = patch("scripts.verify_skill_library_release.ROOT", source)
        override.start()
        self.addCleanup(override.stop)

    @classmethod
    def setUpClass(cls) -> None:
        cls.outputs = builder.render_outputs()

    def fetch(self, outputs: dict[str, bytes]):
        def selected(url: str, maximum: int) -> bytes:
            prefix = f"{PUBLISH_BASE}/"
            self.assertTrue(url.startswith(prefix))
            content = outputs[url.removeprefix(prefix)]
            return content[:maximum]

        return selected

    def test_complete_downloaded_release_validates_outside_checkout(self) -> None:
        receipt = verify_release(self.fetch(self.outputs))

        self.assertEqual("passed", receipt["status"])
        self.assertEqual(93, receipt["release_asset_count"])
        self.assertEqual(92, receipt["receipt_bound_asset_count"])
        self.assertEqual(44, receipt["runtime_archive_count"])
        self.assertEqual(44, receipt["agent_archive_count"])
        self.assertTrue(receipt["validated_outside_checkout"])
        self.assertFalse(receipt["network_called"])

    def test_changed_archive_fails_digest_readback(self) -> None:
        changed = copy.deepcopy(self.outputs)
        path = next(
            name for name in changed if name.startswith("agent-skill-")
        )
        changed[path] += b"tampered"

        with self.assertRaisesRegex(
            SkillLibraryReleaseError, "size or digest changed"
        ):
            verify_release(self.fetch(changed))

    def test_corrected_seed_rejects_self_consistent_stale_public_library(self) -> None:
        from gravity_insight.skill_package import SkillPackageError

        manifests = copy.deepcopy(builder.load_canonical_skills())
        manifests[0]["summary"] += " (corrected declaration)"
        with patch.object(builder, "load_canonical_skills", return_value=manifests):
            corrected = builder.render_outputs()
            with self.assertRaisesRegex(SkillPackageError, "pin drifted"):
                builder.main(["--check"])
            with self.assertRaisesRegex(SkillPackageError, "pin drifted"):
                builder.render_seed(corrected)
        corrected_pin = hashlib.sha256(corrected["build-manifest.json"]).hexdigest()
        with patch.object(builder, "PINNED_BUILD_MANIFEST_SHA256", corrected_pin):
            self.assertTrue(builder.render_seed(corrected))
            self.assertEqual("passed", verify_release(self.fetch(corrected))["status"])
            with self.assertRaisesRegex(SkillLibraryReleaseError, "pin drifted"):
                verify_release(self.fetch(self.outputs))

    def test_readback_inside_source_checkout_remains_rejected(self) -> None:
        with patch("scripts.verify_skill_library_release.ROOT", Path(tempfile.gettempdir()).resolve()):
            with self.assertRaisesRegex(SkillLibraryReleaseError, "inside the source checkout"):
                verify_release(self.fetch(self.outputs))


if __name__ == "__main__":
    unittest.main()
