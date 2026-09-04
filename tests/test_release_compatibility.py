from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from gravity_insight.compiler import JsonSchemaValidator
from gravity_insight.contracts import load_release_compatibility
from scripts.check_changelog import validate_changelog
from scripts.build_offline_wheel import build_offline_wheel
from scripts.generate_release_compatibility import (
    CHANGELOG_PATH,
    OUTPUT_PATH,
    CompatibilityContractError,
    build_release_compatibility,
    check_generated_contract,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = (
    ROOT
    / "src/gravity_insight/contracts/schema/release-compatibility-v1.schema.json"
)
WHEEL_CONTRACT_PATH = (
    "gravity_insight/contracts/generated/release-compatibility.v1.json"
)
_PLACEHOLDER = "- None.\n"
_SYNTHETIC = "- **Hard break:** synthetic stale-contract proof.\n"


def _with_extra_hard_break(source: str, target: str) -> str:
    """Add one hard break to the Unreleased section, whichever state it is in.

    A freshly cut release leaves `- None.` as the only breaking entry, and a
    section holding both that and a real break fails the marker rule before it
    can reach the staleness check this test is about -- so the placeholder has
    to be replaced, not prepended to. Once real breaks are declared there is no
    placeholder and no migration line to add. Pinning either shape means the
    test goes red on the next release cut for no reason, which is what the
    hardcoded `0.3.9` marker did here.
    """
    heading = f"Target release: `{target}`\n\n### Breaking changes\n\n"
    if heading not in source:
        raise AssertionError(f"no Unreleased breaking section for {target}")
    start = source.index(heading) + len(heading)
    if source.startswith(_PLACEHOLDER, start):
        migration = f"\nMigration guide: [{target}](docs/migration/{target}.md)\n"
        return (
            source[:start]
            + _SYNTHETIC
            + migration
            + source[start + len(_PLACEHOLDER) :]
        )
    return source[:start] + _SYNTHETIC + source[start:]


class ReleaseCompatibilityTests(unittest.TestCase):
    def test_checked_in_contract_is_generated_from_changelog(self) -> None:
        expected = check_generated_contract()
        actual = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))

        self.assertEqual(expected, actual)

    def test_release_statuses_preserve_historical_unknowns(self) -> None:
        contract = build_release_compatibility()
        releases = {release["version"]: release for release in contract["releases"]}

        self.assertEqual("breaking", releases["0.3.3"]["breaking_status"])
        self.assertEqual(2, len(releases["0.3.3"]["hard_breaks"]))
        self.assertEqual(1, len(releases["0.3.3"]["soft_breaks"]))
        self.assertEqual(
            "docs/migration/0.3.3.md", releases["0.3.3"]["migration_guide"]
        )
        self.assertEqual("released", releases["0.3.3"]["release_status"])
        self.assertEqual("breaking", releases["0.3.4"]["breaking_status"])
        self.assertEqual(1, len(releases["0.3.4"]["hard_breaks"]))
        self.assertEqual([], releases["0.3.4"]["soft_breaks"])
        self.assertEqual(
            "docs/migration/0.3.4.md", releases["0.3.4"]["migration_guide"]
        )
        self.assertEqual("released", releases["0.3.4"]["release_status"])
        self.assertEqual("released", releases["0.3.5"]["release_status"])
        self.assertEqual("breaking", releases["0.3.5"]["breaking_status"])
        self.assertEqual(1, len(releases["0.3.5"]["hard_breaks"]))
        self.assertEqual(
            "docs/migration/0.3.5.md", releases["0.3.5"]["migration_guide"]
        )
        self.assertEqual("released", releases["0.3.6"]["release_status"])
        self.assertEqual("none", releases["0.3.6"]["breaking_status"])
        self.assertEqual("released", releases["0.3.7"]["release_status"])
        self.assertEqual("none", releases["0.3.7"]["breaking_status"])
        self.assertEqual("released", releases["0.3.8"]["release_status"])
        self.assertEqual("breaking", releases["0.3.8"]["breaking_status"])
        self.assertEqual(2, len(releases["0.3.8"]["hard_breaks"]))
        self.assertEqual(2, len(releases["0.3.8"]["soft_breaks"]))
        self.assertEqual(
            "docs/migration/0.3.8.md", releases["0.3.8"]["migration_guide"]
        )
        for version in ("0.3.1", "0.3.2"):
            with self.subTest(version=version):
                self.assertEqual("unknown", releases[version]["breaking_status"])
                self.assertEqual([], releases[version]["hard_breaks"])
                self.assertEqual([], releases[version]["soft_breaks"])
                self.assertIsNone(releases[version]["migration_guide"])

    def test_contract_matches_schema(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        contract = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))

        JsonSchemaValidator(schema, str(SCHEMA_PATH)).validate(contract)

    def test_stable_api_loads_packaged_contract(self) -> None:
        self.assertEqual(
            json.loads(OUTPUT_PATH.read_text(encoding="utf-8")),
            load_release_compatibility(),
        )

    def test_new_hard_break_without_regeneration_is_rejected(self) -> None:
        target = validate_changelog().target_version
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            changelog = root / "CHANGELOG.md"
            migration_dir = root / "docs/migration"
            migration_dir.mkdir(parents=True)
            for version in (
                "0.3.3", "0.3.4", "0.3.5", "0.3.6", "0.3.7", "0.3.8", target,
            ):
                (migration_dir / f"{version}.md").write_text(
                    f"# Synthetic {version} migration\n", encoding="utf-8"
                )
            source = CHANGELOG_PATH.read_text(encoding="utf-8")
            changelog.write_text(
                _with_extra_hard_break(source, target), encoding="utf-8"
            )

            with self.assertRaisesRegex(
                CompatibilityContractError, "generated contract is stale"
            ):
                check_generated_contract(root=root, changelog_path=changelog)

    def test_offline_wheel_contains_exact_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            wheel = build_offline_wheel(ROOT, Path(raw))
            with zipfile.ZipFile(wheel) as bundle:
                packaged = json.loads(bundle.read(WHEEL_CONTRACT_PATH))
                names = bundle.namelist()
                root_init = bundle.read("gravity_insight/__init__.py")

        self.assertEqual(load_release_compatibility(), packaged)
        self.assertFalse(
            any(
                name.startswith("gravity_insight/skills/")
                or name.startswith("gravity_insight/contracts/skills/")
                for name in names
            )
        )
        self.assertNotIn(b"LocalSkillResolver", root_init)


if __name__ == "__main__":
    unittest.main()
