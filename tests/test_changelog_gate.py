from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.check_changelog import (
    CHANGELOG_PATH,
    PYPROJECT_PATH,
    ChangelogError,
    validate_changelog,
)


class ChangelogGateTests(unittest.TestCase):
    def test_repository_changelog_contract_passes(self) -> None:
        report = validate_changelog()

        self.assertEqual("0.3.8", report.project_version)
        self.assertEqual("0.3.8", report.target_version)
        self.assertEqual(
            ("0.3.7", "0.3.6", "0.3.5", "0.3.4", "0.3.3", "0.3.2", "0.3.1"),
            report.released_versions,
        )
        self.assertEqual(8, report.breaking_entries)
        self.assertEqual(4, report.migration_guides)

    def test_version_bump_without_matching_entry_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            pyproject = Path(raw) / "pyproject.toml"
            source = PYPROJECT_PATH.read_text(encoding="utf-8")
            self.assertIn('version = "0.3.8"', source)
            pyproject.write_text(
                source.replace('version = "0.3.8"', 'version = "9.9.9"', 1),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ChangelogError, "project version 9.9.9 has no changelog entry"
            ):
                validate_changelog(pyproject_path=pyproject)

    def test_released_section_edit_fails_digest_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            changelog = Path(raw) / "CHANGELOG.md"
            source = CHANGELOG_PATH.read_text(encoding="utf-8")
            original = "增加 control-plane Ed25519 信任根校验"
            self.assertIn(original, source)
            changelog.write_text(
                source.replace(original, "篡改 control-plane 历史", 1),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ChangelogError, "released section 0.3.2 was modified"
            ):
                validate_changelog(changelog_path=changelog)

    def test_breaking_entry_requires_explicit_marker(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            changelog = Path(raw) / "CHANGELOG.md"
            source = CHANGELOG_PATH.read_text(encoding="utf-8")
            marker = "- **Hard break:** Python 导入根"
            self.assertIn(marker, source)
            changelog.write_text(
                source.replace(marker, "- Python 导入根", 1),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ChangelogError,
                r"breaking entries must start with `\*\*Hard break:\*\*`",
            ):
                validate_changelog(changelog_path=changelog)

    def test_breaking_entry_requires_existing_versioned_migration(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            changelog = Path(raw) / "CHANGELOG.md"
            source = CHANGELOG_PATH.read_text(encoding="utf-8")
            guide = "Migration guide: [0.3.4](docs/migration/0.3.4.md)\n"
            self.assertIn(guide, source)
            changelog.write_text(source.replace(guide, "", 1), encoding="utf-8")

            with self.assertRaisesRegex(
                ChangelogError, "has breaking changes but no migration guide"
            ):
                validate_changelog(changelog_path=changelog)

    def test_lock_inventory_must_cover_every_released_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            lock = Path(raw) / "lock.json"
            lock.write_text(
                '{"algorithm":"sha256","schema_version":'
                '"gravity.changelog-release-lock.v1","sections":{"0.3.2":'
                '"12dfd5e1fac242768d04092a70e9cc871130ef32135a64cb8f93a9f617415d81"}}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ChangelogError,
                r"lock inventory mismatch: missing=\['0.3.7', '0.3.6', '0.3.5', "
                r"'0.3.4', '0.3.3', '0.3.1'\]",
            ):
                validate_changelog(lock_path=lock)

    def test_breaking_marker_outside_dedicated_section_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            changelog = Path(raw) / "CHANGELOG.md"
            source = CHANGELOG_PATH.read_text(encoding="utf-8")
            changed_heading = "### Changed\n"
            self.assertIn(changed_heading, source)
            changelog.write_text(
                source.replace(
                    changed_heading,
                    changed_heading + "\n- **Hard break:** misplaced marker\n",
                    1,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ChangelogError, "breaking marker outside"
            ):
                validate_changelog(changelog_path=changelog)


if __name__ == "__main__":
    unittest.main()
