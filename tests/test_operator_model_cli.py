from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gravity_sdk import ModelRegistry, OperatorRegistry
from gravity_sdk.cli import main
from gravity_sdk.operator_ids import RETURNED_DIMENSION_CHANGE_URI
from tests.test_model_registry import MODEL_URI, model_artifact


class OperatorModelCliTests(unittest.TestCase):
    def invoke(self, *argv: str) -> tuple[int, dict, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch(
                "gravity_sdk.runtime.build_client",
                side_effect=AssertionError("client constructed"),
            ),
            patch("socket.socket", side_effect=AssertionError("network attempted")),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = main(list(argv))
        rendered = stdout.getvalue() or stderr.getvalue()
        return code, json.loads(rendered), stderr.getvalue()

    def test_root_exports_and_operator_inspection_are_offline(self) -> None:
        self.assertEqual(1, OperatorRegistry().list()["count"])
        self.assertEqual(0, ModelRegistry().list()["count"])

        code, listed, stderr = self.invoke("operators", "list")
        self.assertEqual(0, code)
        self.assertEqual(1, listed["count"])
        self.assertEqual("", stderr)

        code, described, stderr = self.invoke(
            "operators", "describe", RETURNED_DIMENSION_CHANGE_URI
        )
        self.assertEqual(0, code)
        self.assertEqual(RETURNED_DIMENSION_CHANGE_URI, described["operator"]["contract"]["uri"])
        self.assertEqual("", stderr)

    def test_operator_validate_and_missing_model_have_machine_exits(self) -> None:
        contract = OperatorRegistry().artifact(RETURNED_DIMENSION_CHANGE_URI)["contract"]
        code, validated, stderr = self.invoke(
            "operators", "validate", "--input", json.dumps(contract)
        )
        self.assertEqual(0, code)
        self.assertEqual("valid", validated["status"])
        self.assertEqual("", stderr)

        code, missing, stderr = self.invoke(
            "models", "evaluate", MODEL_URI, "--at", "2026-08-22"
        )
        self.assertEqual(4, code)
        self.assertEqual(["MODEL_UNVALIDATED"], missing["reason_codes"])
        self.assertEqual("", stderr)

    def test_explicit_model_source_can_be_evaluated_but_never_predicts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "model.json"
            source.write_text(json.dumps(model_artifact()), encoding="utf-8")
            code, result, stderr = self.invoke(
                "models",
                "evaluate",
                MODEL_URI,
                "--source",
                str(source),
                "--at",
                "2026-08-22",
                "--horizon-days",
                "7",
                "--unit",
                "currency",
            )
        self.assertEqual(4, code)
        self.assertEqual("blocked", result["status"])
        self.assertIn("MODEL_SOURCE_UNTRUSTED", result["reason_codes"])
        self.assertFalse(result["production_claims_allowed"])
        self.assertNotIn("prediction", result)
        self.assertEqual("", stderr)


if __name__ == "__main__":
    unittest.main()
