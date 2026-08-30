"""Lock the root package's deliberately additive lazy export surface."""

from __future__ import annotations

import ast
import json
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
    for target, owner in (
        ("_sdk_error_name", ".error_types"),
        ("_sql_error_name", ".error_sql"),
    ):
        errors = next(
            node.iter
            for node in module.body
            if isinstance(node, ast.For)
            and isinstance(node.target, ast.Name)
            and node.target.id == target
        )
        exports.update({error.value: [owner, error.value] for error in errors.elts})
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

    def test_owner_migration_ledger_changes_only_the_declared_owner(self) -> None:
        migration = [{
            "symbol": "capabilities_many",
            "from": ".agent_batch",
            "to": ".agents.agent_batch",
        }]
        with tempfile.TemporaryDirectory() as raw:
            ledger = Path(raw) / "ledger.json"
            ledger.write_text(json.dumps(migration), encoding="utf-8")
            expected = expected_public_exports(ledger=ledger)
        self.assertEqual(
            [".agents.agent_batch", "capabilities_many"],
            expected["capabilities_many"],
        )

    def test_every_snapshot_symbol_is_reachable_from_the_root_package(self) -> None:
        """An entry in the map is worthless if `from gravity_insight import X` fails."""

        import gravity_insight

        expected = expected_public_exports()
        missing = [name for name in expected if not hasattr(gravity_insight, name)]

        self.assertEqual([], missing)


if __name__ == "__main__":
    unittest.main()
