from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from gravity_insight import GravityInsightClient, GravitySDK
from gravity_insight.capability_contract import capability_contract
from gravity_insight.journey_service import JourneyService
from gravity_insight.runtime_skill_resolver import RuntimeSkillResolver
from gravity_insight.workspace import Workspace, WorkspaceDefaults
from tests.locked_skill_fixture import canonical_skill_manifest, locked_skill, materialize_skill_cas, write_skill_lock
from tests.test_gravity_analysis_default_dictionary import _manifest as dictionary_manifest
from tests.test_gravity_realtime_event_catalog import _manifest as realtime_manifest
from tests.test_reference_journey import stable_trust
from gravity_insight.transport import TransportResponse


DICTIONARY = "analysis.default-value-dictionary"
REALTIME = "analysis.realtime-event-catalog"
DEVICE = "analysis.gravity.game.device-segment-event-review"
WINDOW = {"start": "2026-09-01 00:00:00", "end": "2026-09-01 23:59:59"}


class Trust:
    """Explicit offline validation evidence; production Trust remains untouched."""

    def __init__(self):
        self.status = "stable"
        self.completeness = "complete"
        self.quality = "pass"

    def trust(self, kind, selector):
        artifact = capability_contract(kind, selector)
        value = stable_trust()
        value.update(
            identity_kind=kind, selector=selector,
            contract_version=artifact["contract"]["contract_version"],
            contract_digest=artifact["digest"], trust_status=self.status,
            completeness=self.completeness,
        )
        value["data_quality"]["status"] = self.quality
        return value


class Transport:
    is_test_transport = True

    def __init__(self):
        self.calls = []
        self.after_request = lambda: None
        self.data = {"api": ["v1"]}

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        self.after_request()
        return TransportResponse(200, {"code": 0, "data": self.data}, "2026-09-01T00:00:00Z")


class JourneyExecutionReadinessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.workspace = Workspace(
            path=None, root=root, state_root=root / "state", apps={"main": 7},
            defaults=WorkspaceDefaults(app="main", timezone="Asia/Shanghai", time_window=None),
            datasources={}, products={}, recipes={},
        )
        manifest = dictionary_manifest()
        manifest["operations"].append(realtime_manifest()["operations"][1])
        self.transport = Transport()
        self.client = GravityInsightClient._from_manifest_for_tests(manifest, transport=self.transport)
        self.sdk = GravitySDK(workspace=self.workspace, insight_factory=lambda: self.client)
        self.trust = Trust()
        self.service = JourneyService(self.sdk, capability_trust=self.trust)

    def tearDown(self):
        self.temp.cleanup()

    def test_three_states_do_not_confuse_dependency_readiness_with_binding(self):
        executable = self.service.can_run(DICTIONARY, {"app": "main"})
        unbound = self.service.can_run("analysis.event-trend")
        self.trust.status = "quarantined"
        blocked = self.service.can_run(DICTIONARY, {"app": "main"})

        self.assertEqual(
            ["executable", "unbound", "dependency_blocked"],
            [result["execution_readiness"] for result in (executable, unbound, blocked)],
        )
        self.assertTrue(executable["ok"])
        self.assertEqual("blocked", unbound["can_run_status"])
        self.assertEqual(["JOURNEY_EXECUTION_NOT_BOUND"], unbound["reason_codes"])
        self.assertEqual("bound", blocked["execution_binding"]["status"])
        self.assertEqual(["DEPENDENCY_QUARANTINED"], blocked["reason_codes"])
        self.assertEqual([], self.transport.calls)

    def test_only_characterized_journeys_have_bound_owners(self):
        rows = self.service.list()["journeys"]
        self.assertEqual(
            {DICTIONARY, REALTIME, "analysis.merge2.ap-cost-anomaly-localization"},
            {row["journey_id"] for row in rows if row["execution_binding"]["status"] == "bound"},
        )

    def test_null_standalone_skill_is_not_an_optional_journey_dependency(self):
        result = RuntimeSkillResolver(workspace=self.workspace).resolve(None)
        self.assertEqual(["SKILL_DEPENDENCY_UNRESOLVED"], result["reason_codes"])

    def test_verified_products_execute_once_and_preserve_native_results(self):
        for identity, method, inputs, data in (
            (DICTIONARY, "analysis_default_dictionary", {"app": "main"}, {"api": ["v1"]}),
            (REALTIME, "realtime_event_catalog", {"app": "main", **WINDOW}, {"list": [{"event_name": "profile_set"}]}),
        ):
            with self.subTest(identity=identity):
                self.transport.data = data
                self.transport.calls.clear()
                self.trust.completeness = "unknown"
                readiness = self.service.can_run(identity, inputs)
                self.assertTrue(readiness["ok"])
                native = []
                owner = getattr(self.sdk, method)

                def record(*args, **kwargs):
                    native.append(owner(*args, **kwargs))
                    return native[-1]

                with patch.object(self.sdk, method, side_effect=record):
                    result = self.service.run(identity, inputs)
                self.assertIs(native[0], result)
                self.assertEqual("success", result["status"])
                self.assertEqual(readiness["execution_binding"]["result_schema_version"], result["schema_version"])
                self.assertEqual(1, len(self.transport.calls))
                self.assertNotIn("findings", result)
                self.assertNotIn("main", repr(readiness))
                self.assertNotIn(WINDOW["start"], repr(readiness))
                self.assertEqual("unknown", readiness["dependencies"]["capabilities"][0]["completeness"])

    def test_current_and_new_dependency_drift_fail_with_specific_reasons(self):
        self.assertTrue(self.service.can_run(DICTIONARY)["ok"])
        self.trust.status = "quarantined"
        before_io = self.service.run(DICTIONARY)
        self.assertEqual(["DEPENDENCY_QUARANTINED"], before_io["reason_codes"])
        self.assertEqual([], self.transport.calls)

        self.trust.status = "stable"
        self.transport.after_request = lambda: setattr(self.trust, "status", "quarantined")
        during_io = self.service.run(DICTIONARY)
        self.assertEqual(
            {"DEPENDENCY_QUARANTINED", "DEPENDENCY_SNAPSHOT_CHANGED", "DEPENDENCY_CAPABILITIES_CHANGED"},
            set(during_io["reason_codes"]),
        )
        self.assertEqual([], during_io["findings"])
        self.assertTrue(during_io["network_called"])

    def test_missing_inputs_and_sdk_owner_never_promise_execution(self):
        missing_app = self.service.can_run(DICTIONARY, {"app": "missing-private-app"})
        missing_window = self.service.can_run(REALTIME, {"app": "main"})
        self.assertEqual(["PROJECT_APP_BINDING_MISSING"], missing_app["reason_codes"])
        self.assertNotIn("missing-private-app", repr(missing_app))
        self.assertEqual("invalid", missing_window["can_run_status"])
        self.assertFalse(self.service.run(REALTIME, {"app": "main"})["network_called"])
        with patch.object(self.sdk, "analysis_default_dictionary", None):
            readiness = self.service.can_run(DICTIONARY, {"app": "main"})
            result = self.service.run(DICTIONARY, {"app": "main"})
        self.assertEqual("unbound", readiness["execution_readiness"])
        self.assertEqual(["JOURNEY_EXECUTION_NOT_BOUND"], result["reason_codes"])
        self.assertEqual([], self.transport.calls)

    def test_app_binding_changes_discard_results_without_exposing_identifiers(self):
        self.transport.after_request = lambda: self.workspace.apps.update(main=9)
        result = self.service.run(DICTIONARY, {"app": "main"})
        self.assertIn("PROJECT_APP_BINDING_CHANGED", result["reason_codes"])
        self.assertEqual([], result["findings"])
        self.assertNotIn("main", repr(result))

    def test_trust_quality_and_complete_requirements_are_not_weakened(self):
        self.trust.status = "degraded"
        self.assertIn("DEPENDENCY_TRUST_INSUFFICIENT", self.service.can_run(DICTIONARY)["reason_codes"])
        self.trust.status = "stable"
        self.trust.quality = "fail"
        self.assertIn("DATA_QUALITY_FAILED", self.service.can_run(DICTIONARY)["reason_codes"])
        self.trust.quality = "pass"
        self.trust.completeness = "prefix"
        self.assertIn("COMPLETENESS_INSUFFICIENT", self.service.can_run("analysis.readable-app-catalog")["reason_codes"])
        self.assertEqual([], self.transport.calls)

    def test_native_empty_and_contract_failure_are_not_analysis_success(self):
        self.transport.data = {"api": []}
        self.assertEqual("empty", self.service.run(DICTIONARY)["status"])
        self.transport.data = {"api": "not-an-array"}
        failed = self.service.run(DICTIONARY)
        self.assertEqual("contract_changed", failed["status"])
        self.assertFalse(failed["ok"])
        self.assertNotIn("allowed_claims", failed)

    def test_result_schema_drift_is_a_gap_not_a_native_success(self):
        with patch.object(self.sdk, "analysis_default_dictionary", return_value={"schema_version": "unexpected", "ok": True}):
            result = self.service.run(DICTIONARY)
        self.assertEqual(["JOURNEY_RESULT_CONTRACT_CHANGED"], result["reason_codes"])
        self.assertEqual([], result["findings"])

    def test_unbound_journey_does_not_gate_direct_or_composite_products(self):
        self.trust.status = "quarantined"
        self.assertFalse(self.service.can_run("analysis.event-trend")["ok"])
        with patch.object(JourneyService, "can_run", side_effect=AssertionError("Journey must not gate Products")):
            direct = self.sdk.analysis_default_dictionary("main")
            from gravity_insight.plan import AdapterContext
            from gravity_insight.plan_analysis_default_adapter import execute_analysis_default_dictionary_plan

            composite = execute_analysis_default_dictionary_plan(
                self.sdk, {"name": "analysis_default_dictionary", "app": "main"},
                AdapterContext("defaults", "run", "composite", self.workspace, ("data",), (), 1, 10),
            )
        self.assertEqual(("success", "success"), (direct["status"], composite["status"]))

    def install_skill(self, skill_id):
        artifact, lock = locked_skill(canonical_skill_manifest(skill_id))
        write_skill_lock(self.workspace.root, lock)
        self.git("init", "-b", "test")
        self.git("add", "gravity.skills.lock.json")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-m", "lock")
        return materialize_skill_cas(self.workspace.state_root, artifact)

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.workspace.root), *args], check=True, capture_output=True)

    def test_real_locked_skill_resolves_but_does_not_install_an_executor(self):
        cas = self.install_skill("app-device-performance-analysis")
        ready = self.service.can_run(DEVICE)
        self.assertEqual("verified", ready["dependency_status"])
        self.assertEqual("locked", ready["skill"]["resolution"])
        self.assertEqual("unbound", ready["execution_readiness"])
        self.assertNotIn("SKILL_DEPENDENCY_UNRESOLVED", ready["reason_codes"])
        (cas / "SKILL.md").write_text("tampered", encoding="utf-8")
        drift = self.service.run(DEVICE)
        self.assertIn("HUB_CAS_TAMPERED", drift["reason_codes"])
        self.assertEqual([], drift["findings"])
        self.assertEqual([], self.transport.calls)

    def test_diagnostic_missing_project_facts_remain_a_legal_gap(self):
        self.install_skill("analysis-metric-definition-alignment")
        identity = "analysis.gravity.core.project-metric-contract-check"
        readiness = self.service.can_run(identity)
        result = self.service.run(identity)
        self.assertEqual("locked", readiness["skill"]["resolution"])
        self.assertEqual("dependency_blocked", readiness["execution_readiness"])
        self.assertIn("PROJECT_SKILL_OVERLAY_MISSING", result["reason_codes"])
        self.assertEqual([], result["allowed_claims"])
        self.assertFalse(result["network_called"])

    def test_deterministic_model_validation_never_promises_project_forecast(self):
        self.install_skill("game-revenue-forecast")
        identity = "analysis.gravity.game.revenue-forecast-readiness"
        readiness = self.service.can_run(identity)
        model = readiness["dependencies"]["models"][0]
        self.assertEqual(["deterministic-scenario-over-caller-bound-parameters"], model["allowed_claims"])
        self.assertIn("project-accuracy-guarantee", model["forbidden_claims"])
        self.assertEqual("method_guidance", readiness["execution_binding"]["status"])
        self.assertEqual("unbound", readiness["execution_readiness"])
        self.assertEqual([], self.service.run(identity)["allowed_claims"])


if __name__ == "__main__":
    unittest.main()
