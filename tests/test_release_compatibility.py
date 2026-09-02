from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from gravity_insight.compiler import JsonSchemaValidator
from gravity_insight.contracts import load_release_compatibility
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
        self.assertEqual("unreleased", releases["0.3.6"]["release_status"])
        self.assertEqual("none", releases["0.3.6"]["breaking_status"])
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
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            changelog = root / "CHANGELOG.md"
            migration_dir = root / "docs/migration"
            migration_dir.mkdir(parents=True)
            for version in ("0.3.3", "0.3.4", "0.3.5", "0.3.6"):
                (migration_dir / f"{version}.md").write_text(
                    f"# Synthetic {version} migration\n", encoding="utf-8"
                )
            source = CHANGELOG_PATH.read_text(encoding="utf-8")
            marker = "Target release: `0.3.6`\n\n### Breaking changes\n\n- None."
            self.assertIn(marker, source)
            changelog.write_text(
                source.replace(
                    marker,
                    "Target release: `0.3.6`\n\n"
                    "Migration guide: [0.3.6](docs/migration/0.3.6.md)\n\n"
                    "### Breaking changes\n\n"
                    "- **Hard break:** synthetic stale-contract proof.",
                    1,
                ),
                encoding="utf-8",
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
