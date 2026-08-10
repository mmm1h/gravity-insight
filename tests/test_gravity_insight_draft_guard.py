from __future__ import annotations

import unittest
from types import SimpleNamespace

try:
    from gravity_sdk.catalog import CapabilityCatalog
    from gravity_sdk.client import GravityInsightClient
    from gravity_sdk.drift import (
        AUTH_ERROR,
        CONTRACT_CHANGED_ADDITIVE,
        DEGRADED,
        HEALTHY,
        SUSPECT,
        UPSTREAM_CHANGED,
        DriftSignal,
        HealthOverlay,
    )
    from gravity_sdk.errors import (
        AuthenticationError,
        ContractChangedError,
        OperationNotImplementedError,
        error_envelope,
    )
    from gravity_sdk.executor import ReadExecutor
    from gravity_sdk.models import load_operation_manifest
    from gravity_sdk.registry import PolicyEngine, Registry
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_sdk.catalog import CapabilityCatalog
    from gravity_sdk.client import GravityInsightClient
    from gravity_sdk.drift import (
        AUTH_ERROR,
        CONTRACT_CHANGED_ADDITIVE,
        DEGRADED,
        HEALTHY,
        SUSPECT,
        UPSTREAM_CHANGED,
        DriftSignal,
        HealthOverlay,
    )
    from gravity_sdk.errors import (
        AuthenticationError,
        ContractChangedError,
        OperationNotImplementedError,
        error_envelope,
    )
    from gravity_sdk.executor import ReadExecutor
    from gravity_sdk.models import load_operation_manifest
    from gravity_sdk.registry import PolicyEngine, Registry


DRAFT_ID = "promotion.tencent.account.list"
OPERATION_ID = "example.health.list"


class _NeverTransport:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("catalog-only operations and health guards must not use transport")


class _SuccessTransport:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, *_args, **_kwargs):
        self.calls += 1
        return SimpleNamespace(
            payload={"code": 0, "data": []},
            fetched_at="2026-08-09T00:00:00Z",
        )


def _operation() -> dict[str, object]:
    return {
        "operation_id": OPERATION_ID,
        "domain": "example",
        "resource": "health",
        "action": "list",
        "contract_version": 1,
        "upstream_method": "GET",
        "path_template": "/report/api/v3/example/health/",
        "auth_profile": "gravity_authorization",
        "stability": "stable",
        "input_fields": {},
        "request": {
            "path_fields": [],
            "query_fields": [],
            "body_fields": [],
            "defaults": {},
            "fixed_query": {},
            "fixed_body": {},
        },
        "response_projection": {
            "data_shape": "list",
            "data_keys": [],
            "required_data_keys": [],
            "item_keys": [],
            "dynamic_item_fields": [],
        },
        "pagination": {"kind": "none"},
        "semantic_error_rules": [],
        "privacy_policy": {
            "classification": "configuration",
            "redact_keys": ["authorization", "token", "cookie"],
        },
        "required_parent": [],
        "live_probe": {"enabled": True, "input": {}},
    }


def _client(overlay: HealthOverlay, transport):
    operations = load_operation_manifest(
        {"manifest_version": 1, "operations": [_operation()]}
    )
    registry = Registry(operations)
    policy = PolicyEngine(registry)
    catalog = CapabilityCatalog(operations, health_overlay=overlay)
    return GravityInsightClient(
        registry,
        ReadExecutor(registry, policy, transport),
        capability_catalog=catalog,
    )


class DraftCatalogTests(unittest.TestCase):
    def test_real_draft_is_discoverable_described_and_never_executed(self) -> None:
        transport = _NeverTransport()
        client = GravityInsightClient.from_env(transport=transport)

        found = client._capability_catalog.search(DRAFT_ID)
        target = next(
            item for item in found["capabilities"] if item["operation_id"] == DRAFT_ID
        )
        self.assertEqual("draft_catalog_only", target["catalog_status"])
        self.assertFalse(target["executable"])
        self.assertEqual("experimental", target["stability"])

        described = client.describe(DRAFT_ID)
        self.assertEqual("known", described["blockers_status"])
        self.assertIn("not_probed", {item["code"] for item in described["blockers"]})
        self.assertEqual(
            "/turbo_engine/api/v1/tencent/manage/account/list/",
            described["provenance"]["census_route"]["path"],
        )
        self.assertFalse(described["currently_callable"])

        with self.assertRaises(OperationNotImplementedError) as raised:
            client.read(DRAFT_ID, {})
        envelope = error_envelope(raised.exception, operation_id=DRAFT_ID)
        self.assertEqual("NOT_IMPLEMENTED", envelope["error"]["code"])
        self.assertIn("not_probed", envelope["error"]["next_action"])
        self.assertEqual(0, transport.calls)


class HealthGuardBoundaryTests(unittest.TestCase):
    def test_frontend_disappearance_needs_failed_targeted_probe_to_isolate(self) -> None:
        overlay = HealthOverlay()
        transport = _SuccessTransport()
        client = _client(overlay, transport)

        suspect = overlay.apply(
            DriftSignal(OPERATION_ID, "route_removed", census_complete=True)
        )
        self.assertEqual(SUSPECT, suspect.status)
        self.assertTrue(overlay.call_decision(OPERATION_ID)["allowed"])
        self.assertEqual("empty", client.read(OPERATION_ID)["status"])

        recovered = overlay.apply_probe_evidence(OPERATION_ID, outcome="success")
        self.assertEqual(HEALTHY, recovered.status)
        self.assertTrue(overlay.call_decision(OPERATION_ID)["allowed"])

        overlay.apply(DriftSignal(OPERATION_ID, "route_removed", census_complete=True))
        isolated = overlay.apply_probe_evidence(
            OPERATION_ID,
            outcome="route_missing",
            probe_confirmed=True,
            evidence_refs=("targeted-probe:404",),
        )
        self.assertEqual(UPSTREAM_CHANGED, isolated.status)
        with self.assertRaises(ContractChangedError):
            client.read(OPERATION_ID)
        self.assertEqual(1, transport.calls)

    def test_non_drift_health_states_keep_their_own_call_semantics(self) -> None:
        overlay = HealthOverlay()
        transport = _SuccessTransport()
        client = _client(overlay, transport)

        additive = overlay.apply_probe_evidence(
            OPERATION_ID,
            outcome="success",
            raw_schema_diff={"classification": "additive"},
            probe_confirmed=True,
        )
        self.assertEqual(CONTRACT_CHANGED_ADDITIVE, additive.status)
        self.assertEqual("empty", client.read(OPERATION_ID)["status"])

        degraded = overlay.apply(DriftSignal(OPERATION_ID, "http_5xx"))
        self.assertEqual(DEGRADED, degraded.status)
        self.assertEqual("empty", client.read(OPERATION_ID)["status"])

        auth = overlay.apply_probe_evidence(OPERATION_ID, outcome="auth_failure")
        self.assertEqual(AUTH_ERROR, auth.status)
        with self.assertRaises(AuthenticationError):
            client.read(OPERATION_ID)
        self.assertNotEqual(UPSTREAM_CHANGED, overlay.state_for(OPERATION_ID).status)

        overlay.apply_probe_evidence(OPERATION_ID, outcome="permission_failure")
        permission = client.read(OPERATION_ID)
        self.assertEqual("PERMISSION_UNAVAILABLE", permission["error"]["code"])
        self.assertNotEqual(UPSTREAM_CHANGED, overlay.state_for(OPERATION_ID).status)

    def test_frontend_method_change_also_requires_probe_confirmation(self) -> None:
        overlay = HealthOverlay()

        suspect = overlay.apply(
            DriftSignal(OPERATION_ID, "method_changed", census_complete=True)
        )
        self.assertEqual(SUSPECT, suspect.status)
        unconfirmed = overlay.apply_probe_evidence(
            OPERATION_ID,
            outcome="method_rejected",
        )
        self.assertEqual(SUSPECT, unconfirmed.status)
        isolated = overlay.apply_probe_evidence(
            OPERATION_ID,
            outcome="method_rejected",
            probe_confirmed=True,
        )
        self.assertEqual(UPSTREAM_CHANGED, isolated.status)

    def test_confirmed_required_field_and_type_breakage_still_fail_closed(self) -> None:
        for raw_schema_diff in (
            {
                "classification": "potentially_breaking",
                "removed_required_paths": ["$/data/list"],
            },
            {
                "classification": "potentially_breaking",
                "removed_required_paths": [],
            },
        ):
            with self.subTest(raw_schema_diff=raw_schema_diff):
                overlay = HealthOverlay()
                transport = _SuccessTransport()
                client = _client(overlay, transport)

                isolated = overlay.apply_probe_evidence(
                    OPERATION_ID,
                    outcome="success",
                    raw_schema_diff=raw_schema_diff,
                    probe_confirmed=True,
                )

                self.assertEqual(UPSTREAM_CHANGED, isolated.status)
                self.assertFalse(overlay.call_decision(OPERATION_ID)["allowed"])
                with self.assertRaises(ContractChangedError):
                    client.read(OPERATION_ID)
                self.assertEqual(0, transport.calls)


if __name__ == "__main__":
    unittest.main()
