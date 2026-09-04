from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from gravity_insight.agent_runtime_contracts import AgentRuntimeContractError, validate_schema
from gravity_insight.contracts.envelope_obligations import (
    CompletenessState,
    DataCompleteness,
    DiagnosticEvidence,
    DiagnosticState,
    EnvelopeObligations,
    ExecutionState,
    ExecutionStatus,
    MutationCertainty,
    MutationState,
    SemanticState,
    SemanticValidity,
    serialize_envelope,
)
from gravity_insight.governance.envelope_obligation_gate import (
    BASELINE_PATH,
    baseline_document,
    compare_baselines,
    evaluate,
    inspect_repository,
    validate,
)


ROOT = Path(__file__).resolve().parents[1]


def _obligations() -> EnvelopeObligations:
    return EnvelopeObligations(
        execution_status=ExecutionStatus(ExecutionState.COMPLETE, "READ_FINISHED"),
        data_completeness=DataCompleteness(
            CompletenessState.COMPLETE,
            "ALL_PAGES_EXHAUSTED",
            {"returned_items": 2, "has_more": False},
        ),
        semantic_validity=SemanticValidity(
            SemanticState.VALID, ("SET_INVARIANTS_SATISFIED",)
        ),
        diagnostic_evidence=DiagnosticEvidence(DiagnosticState.NONE),
        mutation_certainty=MutationCertainty(
            MutationState.NOT_APPLICABLE, "READ_ONLY_PATH"
        ),
    )


class EnvelopeObligationTests(unittest.TestCase):
    def test_typed_obligations_serialize_to_the_machine_schema(self) -> None:
        result = serialize_envelope({"status": "complete", "data": []}, _obligations())
        self.assertEqual("complete", result["obligations"]["execution_status"]["state"])
        self.assertEqual(
            "complete", result["obligations"]["data_completeness"]["state"]
        )
        validate_schema(
            result["obligations"],
            "envelope-obligations-v1.schema.json",
            "test obligations",
        )

    def test_serializer_rejects_prebuilt_or_untyped_obligations(self) -> None:
        with self.assertRaises(TypeError):
            serialize_envelope({}, _obligations().to_dict())  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            serialize_envelope({"obligations": {}}, _obligations())
        invalid = _obligations().to_dict()
        invalid["diagnostic_evidence"] = {"state": "available", "evidence_codes": []}
        with self.assertRaises(AgentRuntimeContractError):
            validate_schema(
                invalid,
                "envelope-obligations-v1.schema.json",
                "invalid diagnostics",
            )
        with self.assertRaises(ValueError):
            DataCompleteness(
                CompletenessState.UNKNOWN,
                "NON_FINITE_FACT",
                {"returned_items": math.nan},
            )
        with self.assertRaises(TypeError):
            ExecutionStatus("complete", "UNTYPED_STATE")  # type: ignore[arg-type]

    def test_repository_gate_passes_checked_in_baseline(self) -> None:
        self.assertEqual([], validate(ROOT))

    def test_new_untyped_envelope_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src/gravity_insight/new_surface.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "def result():\n"
                "    return {'schema_version': 'example.v1', 'ok': True, "
                "'status': 'success', 'data': []}\n",
                encoding="utf-8",
                newline="\n",
            )
            paths = inspect_repository(root)
            errors = evaluate(paths, baseline_document(()))
        self.assertEqual(1, len(errors))
        self.assertIn("new untyped consumer envelope path", errors[0])

    def test_a_literal_obligations_dictionary_does_not_satisfy_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src/gravity_insight/fake_typed.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "def result():\n"
                "    return {'schema_version': 'example.v1', 'ok': True, "
                "'status': 'success', 'obligations': {}}\n",
                encoding="utf-8",
                newline="\n",
            )
            [path] = inspect_repository(root)
        self.assertFalse(path.typed)

    def test_outer_complete_literal_or_exception_string_is_not_typed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src/gravity_insight/reconstructed.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "from gravity_insight.contracts.envelope_obligations import "
                "serialize_envelope\n"
                "def result(obligations):\n"
                "    try:\n"
                "        payload = {'status': 'complete', 'data': []}\n"
                "    except ValueError as exc:\n"
                "        payload = {'status': str(exc), 'data': []}\n"
                "    return serialize_envelope(payload, obligations)\n",
                encoding="utf-8",
                newline="\n",
            )
            [path] = inspect_repository(root)
        self.assertFalse(path.typed)

    def test_baseline_cannot_register_a_new_violation_or_exemption(self) -> None:
        base = json.loads((ROOT / BASELINE_PATH).read_text(encoding="utf-8"))
        current = json.loads(json.dumps(base))
        current["legacy_violations"]["new"] = {
            "path": "new.py", "qualname": "new", "structural_keys": ["ok", "status"]
        }
        current["exemptions"]["false-positive"] = {
            "path": "new.py",
            "qualname": "new",
            "structural_keys": ["ok", "status"],
            "classification": "internal_state",
            "reason": "not a consumer surface",
        }
        errors = compare_baselines(current, base)
        self.assertEqual(2, len(errors))
        self.assertTrue(any("legacy_violations" in error for error in errors))
        self.assertTrue(any("exemptions" in error for error in errors))

    def test_false_positive_exemption_binds_the_exact_structural_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src/gravity_insight/internal_state.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                "def snapshot():\n"
                "    return {'schema_version': 'internal.v1', 'status': 'ready', "
                "'items': []}\n",
                encoding="utf-8",
                newline="\n",
            )
            [path] = inspect_repository(root)
        baseline = baseline_document(())
        baseline["exemptions"][path.identity] = {
            "path": path.path,
            "qualname": path.qualname,
            "structural_keys": list(path.structural_keys),
            "classification": "internal_state",
            "reason": "This value never crosses a consumer serialization boundary.",
        }
        self.assertEqual([], evaluate([path], baseline))
        baseline["exemptions"][path.identity]["structural_keys"] = ["status"]
        self.assertIn("invalid envelope obligation exemption", evaluate([path], baseline)[0])


if __name__ == "__main__":
    unittest.main()
