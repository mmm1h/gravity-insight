from __future__ import annotations

import copy
import unittest

from scripts import generate_skill_library as builder
from scripts.verify_skill_library_release import (
    PUBLISH_BASE,
    SkillLibraryReleaseError,
    verify_release,
)


class SkillLibraryReleaseTests(unittest.TestCase):
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
        self.assertEqual(91, receipt["release_asset_count"])
        self.assertEqual(90, receipt["receipt_bound_asset_count"])
        self.assertEqual(43, receipt["runtime_archive_count"])
        self.assertEqual(43, receipt["agent_archive_count"])
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


if __name__ == "__main__":
    unittest.main()
