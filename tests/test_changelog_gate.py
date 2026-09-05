from __future__ import annotations

import re
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

        # Every expectation is re-derived from the source files instead of being
        # spelled out. A literal here is a snapshot of the release state, so it
        # goes stale the moment a version is cut, and the failure then lands on
        # the release -- far from anyone who would recognise it as a stale
        # constant rather than a real contract break. 0.3.8, 0.3.9 and 0.3.10
        # each had to hand-edit numbers in this file for exactly that reason.
        # This is not circular: the right-hand side comes from check_changelog's
        # parser and the left from an independent scan of the same text, so a
        # parser that miscounts or misorders still fails the case.
        changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
        pyproject = PYPROJECT_PATH.read_text(encoding="utf-8")

        self.assertEqual(
            re.search(r'(?m)^version = "([^"]+)"', pyproject).group(1),
            report.project_version,
        )
        self.assertEqual(
            re.search(r"(?m)^Target release: `([^`]+)`", changelog).group(1),
            report.target_version,
        )
        self.assertEqual(
            tuple(re.findall(r"(?m)^## \[(\d+\.\d+\.\d+)\] - ", changelog)),
            report.released_versions,
        )
        self.assertEqual(
            len(re.findall(r"(?m)^- \*\*(?:Hard|Soft) break:\*\*", changelog)),
            report.breaking_entries,
        )
        self.assertEqual(
            len(re.findall(r"(?m)^Migration guide: ", changelog)),
            report.migration_guides,
        )

    def test_version_bump_without_matching_entry_fails(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            pyproject = Path(raw) / "pyproject.toml"
            source = PYPROJECT_PATH.read_text(encoding="utf-8")
            # Read the version out rather than naming it. The literal it
            # replaces was a second place every release had to hand-edit; the
            # assertIn guard that used to sit here caught the drift, but it
            # caught it during the release, which is the worst time to discover
            # that a test only needed a constant bumped.
            current = re.search(r'(?m)^version = "([^"]+)"', source).group(1)
            pyproject.write_text(
                source.replace(f'version = "{current}"', 'version = "9.9.9"', 1),
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

            # Derived from the changelog, not listed. The property is that every
            # released section except the one the fixture locks is reported as
            # missing; spelling the versions out means this goes red on the next
            # release cut for no reason, which is what it just did.
            expected = [
                version
                for version in validate_changelog().released_versions
                if version != "0.3.2"
            ]
            with self.assertRaisesRegex(
                ChangelogError,
                r"lock inventory mismatch: missing=" + re.escape(repr(expected)),
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
