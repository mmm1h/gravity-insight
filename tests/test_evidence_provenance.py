"""Offline self-proofs for drift attribution and credential-scope receipts."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gravity_insight.receipt import (
    record_completed_http_response,
    request_receipt_context,
)
from gravity_insight.receipt_query import list_http_receipts
from gravity_insight.response_drift import (
    ResponseDriftRecorder,
    merge_response_drifts,
    normalize_response_drift,
)
from gravity_insight.runtime_scope import (
    RuntimeScopeKey,
    credential_scope_opaque_id,
    principal_state_root,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _scope(credential_generation_material: str) -> RuntimeScopeKey:
    return RuntimeScopeKey(
        resolved_env_path_hash=_digest("path-coordinate")[:32],
        account_fingerprint=_digest("account-coordinate")[:32],
        principal_fingerprint=_digest("principal-coordinate")[:32],
        credential_generation=_digest(credential_generation_material)[:32],
        workspace_fingerprint=_digest("workspace-coordinate")[:32],
    )


def _expectation_provenance(baseline_type: str) -> dict[str, object]:
    return {
        "operation_contract": {
            "digest": _digest("operation-contract"),
            "version": "gravity.operation-contract.v1",
        },
        "runtime_version": "0.3.11",
        "request_shape_fingerprint": _digest("common-request-shape"),
        "accepted_upstream_baseline": {
            "observed_type": baseline_type,
            "response_shape_fingerprint": _digest(
                f"baseline-response-shape:{baseline_type}"
            ),
            "observed_at": "2026-09-01T08:00:00Z",
            "app_environment_fingerprint": _digest("fixture-app-environment"),
        },
        "current_observation": {
            "response_shape_fingerprint": _digest("current-response-shape:object"),
            "observed_at": "2026-09-07T08:00:00.123456Z",
            "app_environment_fingerprint": _digest("fixture-app-environment"),
        },
    }


def _breaking_record(baseline_type: str) -> dict[str, object]:
    recorder = ResponseDriftRecorder()
    recorder.add_breaking_field(
        ("data", "list"),
        "array",
        {},
        expectation_provenance=_expectation_provenance(baseline_type),
    )
    record = recorder.to_contract()
    assert record is not None
    return normalize_response_drift(record)


def _attribution(record: dict[str, object]) -> str:
    [field] = record["fields"]
    provenance = field["expectation_provenance"]
    baseline = provenance["accepted_upstream_baseline"]
    current = provenance["current_observation"]
    if (
        baseline["app_environment_fingerprint"]
        != current["app_environment_fingerprint"]
    ):
        return "indeterminate"
    expected = field["expected_type"]
    observed = field["observed_type"]
    baseline_observed = baseline["observed_type"]
    if baseline_observed == observed and observed != expected:
        return "local_expectation_was_wrong"
    if baseline_observed == expected and observed != expected:
        return "upstream_changed"
    return "indeterminate"


class EvidenceProvenanceSelfProofTests(unittest.TestCase):
    def test_drift_records_self_attribute_local_error_and_upstream_change(self) -> None:
        local_error = _breaking_record("object")
        upstream_change = _breaking_record("array")

        self.assertEqual("local_expectation_was_wrong", _attribution(local_error))
        self.assertEqual("upstream_changed", _attribution(upstream_change))
        self.assertNotEqual(local_error, upstream_change)

    def test_conflicting_or_incomplete_provenance_is_never_claimed(self) -> None:
        local_error = _breaking_record("object")
        upstream_change = _breaking_record("array")
        merged = merge_response_drifts((local_error, upstream_change))
        assert merged is not None
        [field] = merged["fields"]
        self.assertNotIn("expectation_provenance", field)

        incomplete = _expectation_provenance("array")
        incomplete.pop("runtime_version")
        recorder = ResponseDriftRecorder()
        with self.assertRaisesRegex(ValueError, "provenance fields changed"):
            recorder.add_breaking_field(
                ("data", "list"),
                "array",
                {},
                expectation_provenance=incomplete,
            )

    def test_receipts_alone_prove_different_credential_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first_scope = _scope("credential-generation-one")
            second_scope = _scope("credential-generation-two")
            first_root = principal_state_root(root, first_scope)
            second_root = principal_state_root(root, second_scope)
            context = request_receipt_context(
                operation_id="app.list",
                method="GET",
                path="/fixture/read",
            )
            response = type("Response", (), {"status_code": 200})()
            record_completed_http_response(response, context, first_root)
            record_completed_http_response(response, context, second_root)
            [first] = list_http_receipts(first_root)["items"]
            [second] = list_http_receipts(second_root)["items"]
            [stored_path] = (first_root / "receipts" / "http").glob("*.json")
            stored = json.loads(stored_path.read_text(encoding="utf-8"))

        self.assertNotEqual(
            first["credential_scope_opaque_id"],
            second["credential_scope_opaque_id"],
        )
        self.assertEqual(
            first["credential_scope_opaque_id"],
            stored["credential_scope_opaque_id"],
        )
        rendered = json.dumps([first, second, stored])
        for private in (
            first_scope.credential_generation,
            second_scope.credential_generation,
            first_scope.fingerprint,
            second_scope.fingerprint,
        ):
            self.assertNotIn(private, rendered)

    def test_scope_opaque_id_is_random_not_credential_derived(self) -> None:
        credential_material = "credential-material-with-no-public-representation"
        scope = _scope(credential_material)
        generated = "f" * 64
        with tempfile.TemporaryDirectory() as raw, mock.patch(
            "gravity_insight.runtime_scope.secrets.token_hex",
            return_value=generated,
        ) as token_hex:
            state_root = principal_state_root(Path(raw), scope)
            first = credential_scope_opaque_id(state_root)
            second = credential_scope_opaque_id(state_root)

        self.assertEqual(generated, first)
        self.assertEqual(first, second)
        token_hex.assert_called_once_with(32)
        self.assertNotIn(credential_material, str(first))
        self.assertNotIn(scope.credential_generation, str(first))
        self.assertNotIn(scope.fingerprint, str(first))

    def test_receipt_rejects_drift_bound_to_another_request_shape(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            directory = root / "receipts" / "http"
            directory.mkdir(parents=True)
            receipt = {
                "schema_version": "gravity.http-receipt.v1",
                "receipt_id": "1" * 32,
                "completed_at": "2026-09-07T08:00:00.123456Z",
                "operation_id": "app.list",
                "method": "GET",
                "path": "/fixture/read",
                "http_status": 200,
                "page_number": None,
                "attempt": 1,
                "retry": False,
                "request_shape_fingerprint": _digest("another-request-shape"),
                "response_drift": _breaking_record("array"),
            }
            (directory / f"999999-{'0' * 32}-{'1' * 32}.json").write_text(
                json.dumps(receipt),
                encoding="utf-8",
            )
            queried = list_http_receipts(root)

        self.assertEqual("partial", queried["status"])
        self.assertEqual([], queried["items"])
        self.assertEqual("corrupt_receipt", queried["gaps"][0]["kind"])


if __name__ == "__main__":
    unittest.main()
