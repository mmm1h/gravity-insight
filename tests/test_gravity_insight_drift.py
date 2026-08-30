from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

try:
    from gravity_insight.catalog import OperationCatalog
    from gravity_insight.drift import (
        AUTH_ERROR,
        CONTRACT_CHANGED_ADDITIVE,
        DEGRADED,
        HEALTHY,
        SUSPECT,
        UPSTREAM_CHANGED,
        DriftSignal,
        HealthOverlay,
    )
    from gravity_insight.errors import ContractChangedError
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_insight.catalog import OperationCatalog
    from gravity_insight.drift import (
        AUTH_ERROR,
        CONTRACT_CHANGED_ADDITIVE,
        DEGRADED,
        HEALTHY,
        SUSPECT,
        UPSTREAM_CHANGED,
        DriftSignal,
        HealthOverlay,
    )
    from gravity_insight.errors import ContractChangedError

from gravity_insight.census.schema import (
    build_raw_schema_sketch,
    compare_raw_schema_sketches,
    fingerprint_contract,
    fingerprint_set,
)


class _Operation:
    operation_id = "analysis.fixture.list"
    upstream_method = "GET"
    path_template = "/api/v1/fixture/"

    def operation_summary(self):
        return {
            "operation_id": self.operation_id,
            "domain": "analysis",
            "resource": "fixture",
            "action": "list",
            "platform": None,
            "description": "fixture",
            "contract_version": 1,
            "stability": "stable",
            "executable": True,
            "block_reason": None,
        }

    def schema(self):
        return {
            **self.operation_summary(),
            "input_fields": {},
            "response_projection": {"data_keys": ["items"]},
            "pagination": {"kind": "none"},
        }


class RawSchemaSketchTests(unittest.TestCase):
    def test_sketch_is_value_free_and_marks_empty_array_items_unknown(self) -> None:
        sketch = build_raw_schema_sketch(
            (
                {"data": {"items": [], "name": "Alice", "enabled": True}},
                {"data": {"items": [], "name": "Bob"}},
            )
        )

        self.assertEqual(["array"], sketch["paths"]["$/data/items"]["types"])
        self.assertEqual([], sketch["paths"]["$/data/items/[]"]["types"])
        self.assertTrue(sketch["paths"]["$/data/items/[]"]["item_unknown"])
        self.assertTrue(sketch["paths"]["$/data/name"]["required"])
        self.assertFalse(sketch["paths"]["$/data/enabled"]["required"])
        encoded = json.dumps(sketch, sort_keys=True)
        self.assertNotIn("Alice", encoded)
        self.assertNotIn("Bob", encoded)

    def test_nonempty_sample_resolves_unknown_items_without_false_additive_drift(self) -> None:
        before = build_raw_schema_sketch(({"data": {"items": []}},))
        after = build_raw_schema_sketch(({"data": {"items": [{"id": 7}]}},))

        diff = compare_raw_schema_sketches(before, after)

        self.assertEqual("observational_expansion", diff["classification"])
        self.assertEqual(["$/data/items/[]/id"], diff["newly_observed_paths"])
        self.assertEqual([], diff["added_paths"])

    def test_fingerprints_remain_three_separate_questions(self) -> None:
        contract = fingerprint_contract({"method": "GET", "path": "/api/v1/list/"})
        raw = build_raw_schema_sketch(({"data": {"items": []}},))
        fingerprints = fingerprint_set(
            contract_fingerprint=contract,
            raw_schema_sketch=raw,
            projected_fingerprint="f" * 64,
        )

        self.assertEqual(contract, fingerprints["contract_fingerprint"])
        self.assertEqual(raw["raw_schema_fingerprint"], fingerprints["raw_schema_fingerprint"])
        self.assertEqual("f" * 64, fingerprints["projected_fingerprint"])
        self.assertEqual(3, len(set(fingerprints.values())))


class HealthOverlayTests(unittest.TestCase):
    def test_catalog_distinguishes_additive_from_breaking_probe_results(self) -> None:
        catalog = OperationCatalog([_Operation()])

        catalog.record(
            _Operation.operation_id,
            status="contract_changed_additive",
            warnings_count=1,
        )
        additive = catalog.describe(_Operation.operation_id)
        self.assertEqual(
            CONTRACT_CHANGED_ADDITIVE, additive["health"]["status"]
        )
        self.assertTrue(additive["currently_callable"])

        # The legacy contract_changed status is reserved for breaking evidence
        # and must continue to drive the upstream_changed stop state.
        catalog.record(
            _Operation.operation_id,
            status="contract_changed",
            warnings_count=1,
        )
        breaking = catalog.describe(_Operation.operation_id)
        self.assertEqual(UPSTREAM_CHANGED, breaking["health"]["status"])

    def test_evidence_is_graded_and_recovery_requires_reviewed_clean_probes(self) -> None:
        overlay = HealthOverlay(clean_probes_required=2)
        operation_id = "analysis.fixture.list"

        suspect = overlay.apply(DriftSignal(operation_id, "bundle_changed"))
        self.assertEqual(SUSPECT, suspect.status)
        self.assertTrue(overlay.call_decision(operation_id)["allowed"])

        additive = overlay.apply_probe_evidence(
            operation_id,
            outcome="success",
            raw_schema_diff={"classification": "additive"},
            probe_confirmed=True,
        )
        self.assertEqual(CONTRACT_CHANGED_ADDITIVE, additive.status)
        self.assertTrue(overlay.call_decision(operation_id)["allowed"])

        breaking = {
            "classification": "potentially_breaking",
            "removed_required_paths": [],
        }
        unconfirmed = overlay.apply_probe_evidence(
            operation_id,
            outcome="success",
            raw_schema_diff=breaking,
        )
        self.assertEqual(SUSPECT, unconfirmed.status)
        confirmed = overlay.apply_probe_evidence(
            operation_id,
            outcome="success",
            raw_schema_diff=breaking,
            probe_confirmed=True,
        )
        self.assertEqual(UPSTREAM_CHANGED, confirmed.status)
        self.assertFalse(overlay.call_decision(operation_id)["allowed"])
        with self.assertRaises(ContractChangedError):
            overlay.guard(operation_id)

        unchanged = overlay.apply(DriftSignal(operation_id, "clean_probe"))
        self.assertEqual(UPSTREAM_CHANGED, unchanged.status)
        overlay.apply(DriftSignal(operation_id, "contract_updated"))
        first_clean = overlay.apply(DriftSignal(operation_id, "clean_probe"))
        self.assertEqual(UPSTREAM_CHANGED, first_clean.status)
        self.assertEqual(1, first_clean.recovery_clean_probes)
        recovered = overlay.apply(DriftSignal(operation_id, "clean_probe"))
        self.assertEqual(HEALTHY, recovered.status)

    def test_transient_auth_and_incomplete_census_never_become_contract_drift(self) -> None:
        overlay = HealthOverlay()
        operation_id = "analysis.fixture.list"

        incomplete = overlay.apply(
            DriftSignal(operation_id, "route_removed", census_complete=False)
        )
        self.assertEqual(SUSPECT, incomplete.status)
        transient = overlay.apply(DriftSignal(operation_id, "http_5xx"))
        self.assertEqual(DEGRADED, transient.status)
        self.assertTrue(overlay.call_decision(operation_id)["retry"])
        auth = overlay.apply_probe_evidence(operation_id, outcome="auth_failure")
        self.assertEqual(AUTH_ERROR, auth.status)
        self.assertNotEqual(UPSTREAM_CHANGED, auth.status)

    def test_overlay_persists_without_contract_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "health-overlay.json"
            overlay = HealthOverlay(state_path)
            overlay.apply(
                DriftSignal(
                    "analysis.fixture.list",
                    "route_removed",
                    census_complete=True,
                    evidence_refs=("removed:GET:/api/v1/fixture/",),
                )
            )
            # 前端消失只到 suspect；隔离需要定向 probe 的第二重证据。
            overlay.apply(
                DriftSignal(
                    "analysis.fixture.list",
                    "route_missing",
                    census_complete=True,
                    probe_confirmed=True,
                )
            )
            restored = HealthOverlay(state_path)

            self.assertEqual(
                UPSTREAM_CHANGED,
                restored.state_for("analysis.fixture.list").status,
            )
            payload = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertNotIn("source_contract", payload)

    def test_catalog_preserves_description_shape_and_applies_overlay_availability(self) -> None:
        overlay = HealthOverlay()
        overlay.apply(
            DriftSignal(
                _Operation.operation_id,
                "method_changed",
                census_complete=True,
            )
        )
        # 静态 census 只给 suspect，guard 此时不应拦截；补上 probe 确认才隔离。
        overlay.apply(
            DriftSignal(
                _Operation.operation_id,
                "method_rejected",
                census_complete=True,
                probe_confirmed=True,
            )
        )
        catalog = OperationCatalog([_Operation()], health_overlay=overlay)

        described = catalog.describe(_Operation.operation_id)
        merged = catalog.merge([_Operation().operation_summary()])

        self.assertEqual(
            {"status", "probe", "contract_fingerprint"},
            set(described["health"]),
        )
        self.assertEqual(UPSTREAM_CHANGED, described["health"]["status"])
        self.assertEqual("contract_changed", merged[0]["availability_status"])
        with self.assertRaises(ContractChangedError):
            overlay.guard(_Operation.operation_id)


if __name__ == "__main__":
    unittest.main()
