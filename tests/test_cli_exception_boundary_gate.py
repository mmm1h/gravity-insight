from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.check_cli_exception_boundaries import (
    CliBoundaryGateError,
    SCHEMA_VERSION,
    check_repository,
    inventory,
    load_allowlist,
)


ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = ROOT / "scripts" / "cli_exception_boundary_allowlist.json"


def _fixture(root: Path, body: str) -> None:
    path = root / "src" / "gravity_insight" / "new_surface_cli.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8", newline="\n")


class CliExceptionBoundaryGateTests(unittest.TestCase):
    def test_repository_has_no_unreviewed_cli_exception_collapses(self) -> None:
        code, receipt = check_repository(
            ROOT, allowlist_path=ALLOWLIST, today=date(2026, 9, 4)
        )
        self.assertEqual(0, code, receipt)
        self.assertEqual([], receipt["unreviewed_findings"])
        self.assertEqual([], receipt["unused_allowlist_entries"])

    def test_new_plain_text_exception_collapse_makes_gate_fail(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _fixture(
                root,
                """import sys

def main():
    try:
        raise RichFailure()
    except RichFailure as exc:
        print(f\"ERROR: {exc}\", file=sys.stderr)
""",
            )
            allowlist = root / "allowlist.json"
            allowlist.write_text(
                json.dumps({"schema_version": SCHEMA_VERSION, "entries": []}),
                encoding="utf-8",
                newline="\n",
            )
            code, receipt = check_repository(
                root, allowlist_path=allowlist, today=date(2026, 9, 4)
            )
        self.assertEqual(1, code)
        self.assertEqual(
            "exception-to-plain-output",
            receipt["unreviewed_findings"][0]["detector"],
        )

    def test_allowlist_without_reason_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _fixture(
                root,
                """def main():
    try:
        raise ValueError('x')
    except ValueError as exc:
        detail = str(exc)
        return detail
""",
            )
            finding = inventory(root)[0]
            allowlist = root / "allowlist.json"
            allowlist.write_text(
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "entries": [
                            {
                                "path": finding.path,
                                "line": finding.line,
                                "detector": finding.detector,
                                "handler_sha256": finding.handler_sha256,
                                "reason": "",
                                "review_expires": "2027-03-31",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
                newline="\n",
            )
            with self.assertRaisesRegex(CliBoundaryGateError, "specific reason"):
                load_allowlist(allowlist, today=date(2026, 9, 4))

    def test_flattened_exception_binding_is_rejected_before_later_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _fixture(
                root,
                """def main():
    try:
        raise ValueError('x')
    except ValueError as exc:
        detail = f\"workspace failed: {exc}\"
    return detail
""",
            )
            detectors = {finding.detector for finding in inventory(root)}
        self.assertIn("flattened-exception-binding", detectors)

    def test_structured_json_serialization_is_not_plain_text_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _fixture(
                root,
                """import json
import sys

def main():
    try:
        raise ValueError('x')
    except ValueError as exc:
        payload = error_envelope(exc)
        sys.stderr.write(json.dumps(payload))
""",
            )
            findings = inventory(root)
        self.assertEqual([], findings)

    def test_json_wrapper_does_not_hide_a_flattened_exception(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _fixture(
                root,
                """import json
import sys

def main():
    try:
        raise ValueError('x')
    except ValueError as exc:
        sys.stderr.write(json.dumps({'error': str(exc)}))
""",
            )
            detectors = {finding.detector for finding in inventory(root)}
        self.assertEqual({"exception-to-plain-output"}, detectors)

    def test_handler_change_invalidates_location_bound_exemption(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _fixture(
                root,
                """def main():
    try:
        raise ValueError('x')
    except ValueError as exc:
        print(exc)
""",
            )
            finding = inventory(root)[0]
            allowlist = root / "allowlist.json"
            allowlist.write_text(
                json.dumps(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "entries": [
                            {
                                "path": finding.path,
                                "line": finding.line,
                                "detector": finding.detector,
                                "handler_sha256": finding.handler_sha256,
                                "reason": "This exact synthetic handler is reviewed for the hash-drift test.",
                                "review_expires": "2027-03-31",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
                newline="\n",
            )
            _fixture(
                root,
                """def main():
    try:
        raise ValueError('x')
    except ValueError as exc:
        print('changed', exc)
""",
            )
            code, receipt = check_repository(
                root, allowlist_path=allowlist, today=date(2026, 9, 4)
            )
        self.assertEqual(1, code)
        self.assertEqual(1, len(receipt["unreviewed_findings"]))
        self.assertEqual(1, len(receipt["unused_allowlist_entries"]))
