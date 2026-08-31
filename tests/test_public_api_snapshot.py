"""Lock the root package's deliberately additive lazy export surface."""

from __future__ import annotations

import ast
import tempfile
import unittest
from pathlib import Path

from tests.agent_migration_characterization import expected_public_exports


ROOT = Path(__file__).resolve().parents[1]
INIT = ROOT / "src" / "gravity_insight" / "__init__.py"


def _lazy_exports() -> dict[str, list[str]]:
    module = ast.parse(INIT.read_text(encoding="utf-8"))
    assignment = next(
        node.value
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_EXPORTS"
            for target in node.targets
        )
    )
    exports = {
        key.value: [value.elts[0].value, value.elts[1].value]
        for key, value in zip(assignment.keys, assignment.values)
    }
    return dict(sorted(exports.items()))


class PublicApiSnapshotTests(unittest.TestCase):
    """The root surface may grow, but never silently, and never shrink.

    Consumers here are agents, not humans reading an IDE completion list, so a
    symbol disappearing costs them a working entry point with no warning. This
    snapshot exists to make both directions of drift visible in review.
    """

    def test_lazy_root_exports_match_public_api_snapshot(self) -> None:
        expected = expected_public_exports()

        self.assertEqual(expected, _lazy_exports())
        self.assertEqual(147, len(expected))

    def test_manifest_rejects_a_duplicate_public_name(self) -> None:
        from scripts.generate_public_api_exports import load_manifest

        with tempfile.TemporaryDirectory() as raw:
            manifest = Path(raw) / "manifest.json"
            manifest.write_text(
                '{"schema_version":"gravity.public-api-manifest.v1","exports":['
                '{"name":"same","module":".sdk","attribute":"connect"},'
                '{"name":"same","module":".sdk","attribute":"connect"}]}'
            )
            with self.assertRaisesRegex(ValueError, "repeats export 'same'"):
                load_manifest(manifest)

    def test_every_snapshot_symbol_is_reachable_from_the_root_package(self) -> None:
        """An entry in the map is worthless if `from gravity_insight import X` fails."""

        import gravity_insight

        expected = expected_public_exports()
        missing = [name for name in expected if not hasattr(gravity_insight, name)]

        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
