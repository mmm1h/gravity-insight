from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from gravity_insight.model_registry import ModelRegistry
from gravity_insight.operator_ids import RETURNED_DIMENSION_CHANGE_URI
from gravity_insight.operator_model_receipt import operator_model_receipt_facet
from gravity_insight.operator_registry import OperatorRegistry
from gravity_insight.receipt import build_receipt
from gravity_insight.trusted_pack_contract import (
    TrustedPackContractError,
    compile_trusted_pack_descriptor,
)
from tests.test_model_registry import MODEL_URI, model_artifact, trusted_registry


def trusted_pack(**overrides):
    value = {
        "artifact_kind": "trusted_pack_descriptor",
        "schema_version": "gravity.trusted-pack-descriptor.v1",
        "pack_id": "trusted-pack://team/forecast-methods@1",
        "distribution": "gravity-team-forecast-methods",
        "version": "1.2.3",
        "wheel_sha256": "a" * 64,
        "runtime_compatibility": {"minimum": "0.3.0", "maximum": "0.9.0"},
        "allowed_groups": ["gravity.models", "gravity.operators"],
        "operators": [RETURNED_DIMENSION_CHANGE_URI],
        "models": [MODEL_URI],
        "installation_owner": "external_installer",
        "activation": "runtime_startup_verify",
    }
    value.update(overrides)
    return value


class OperatorModelContractTests(unittest.TestCase):
    def test_trusted_pack_descriptor_is_deterministic_and_code_free(self) -> None:
        first = compile_trusted_pack_descriptor(trusted_pack())
        reordered = trusted_pack(
            allowed_groups=["gravity.operators", "gravity.models"]
        )
        second = compile_trusted_pack_descriptor(reordered)

        self.assertEqual(first["digest"], second["digest"])
        self.assertEqual(
            ["gravity.models", "gravity.operators"],
            first["contract"]["allowed_groups"],
        )
        rendered = repr(first)
        for forbidden in ("entry_point", "install_command", "path", "url"):
            self.assertNotIn(forbidden, rendered)

    def test_trusted_pack_rejects_skill_shape_groups_runtime_and_install_fields(self) -> None:
        invalid = []
        skill = trusted_pack()
        skill["artifact_kind"] = "skill_package"
        invalid.append((skill, "TRUSTED_PACK_INVALID"))

        group = trusted_pack(allowed_groups=["gravity.operators"])
        invalid.append((group, "TRUSTED_PACK_GROUP_INVALID"))

        runtime = trusted_pack(
            runtime_compatibility={"minimum": "2.0.0", "maximum": "1.0.0"}
        )
        invalid.append((runtime, "TRUSTED_PACK_RUNTIME_INVALID"))

        empty = trusted_pack(allowed_groups=[], operators=[], models=[])
        invalid.append((empty, "TRUSTED_PACK_INVALID"))

        command = trusted_pack()
        command["install_command"] = "pip install something"
        invalid.append((command, "TRUSTED_PACK_INVALID"))

        for value, reason in invalid:
            with self.subTest(reason=reason), self.assertRaisesRegex(
                TrustedPackContractError, reason
            ):
                compile_trusted_pack_descriptor(value)

    def test_registry_and_descriptor_never_scan_python_entry_points(self) -> None:
        with patch(
            "importlib.metadata.entry_points",
            side_effect=AssertionError("environment scan attempted"),
        ):
            OperatorRegistry()
            ModelRegistry()
            result = compile_trusted_pack_descriptor(trusted_pack())
        self.assertRegex(result["digest"], r"^[0-9a-f]{64}$")

    def test_receipt_operator_model_facet_is_additive_and_value_free(self) -> None:
        operator = OperatorRegistry().resolve(RETURNED_DIMENSION_CHANGE_URI)["operator"]
        model = trusted_registry(model_artifact()).evaluate(
            MODEL_URI, at="2026-08-22"
        )["model"]
        facet = operator_model_receipt_facet(
            operators=[operator], models=[model]
        )
        common = {
            "operation_id": "example.read",
            "inputs": {"sensitive": "not-copied"},
            "contract_fingerprint": "b" * 64,
            "output": {"rows": [{"value": "not-copied"}]},
            "status": "success",
            "duration_ms": 1.5,
            "request_count": 0,
        }
        legacy = build_receipt(**common)
        enriched = build_receipt(**common, operator_model=facet)

        self.assertEqual("gravity.receipt.v1", legacy["schema_version"])
        self.assertNotIn("operator_model", legacy)
        self.assertEqual(facet, enriched["operator_model"])
        rendered = repr(enriched["operator_model"])
        self.assertNotIn("not-copied", rendered)
        self.assertNotIn("parameters", rendered)
        self.assertNotIn("path", rendered)

        tampered = copy.deepcopy(facet)
        tampered["dependencies_digest"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "dependency digest"):
            build_receipt(**common, operator_model=tampered)


if __name__ == "__main__":
    unittest.main()
