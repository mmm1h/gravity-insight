"""R14-C fixed Variant contracts, corpus, Trust, and privacy gates."""

from __future__ import annotations

import copy
import inspect
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from gravity_insight import (
    ExecutionVariantService,
    GravitySDK,
    validate_execution_variant,
    validate_execution_variant_characterization,
    validate_execution_variant_selection,
)
from gravity_insight.analysis_query_execution_variant import (
    execute_fixed_analysis_query_event_variant,
)
from gravity_insight.errors import InputValidationError
from gravity_insight.execution_variant import ExecutionVariantContractError
from gravity_insight.execution_variant_characterization import (
    build_execution_variant_characterization,
    load_execution_variant_characterization,
)
from gravity_insight.execution_variant_contract import (
    DIRECT_VARIANT_URI,
    PLAN_VARIANT_URI,
    PRODUCT_SELECTOR,
    REFERENCE_JOURNEY,
    execution_variant_descriptors,
)
from gravity_insight.execution_variant_selection import selection_digest
from gravity_insight.plan import AdapterContext
from gravity_insight.plan_analysis_adapter import execute_analysis_query_plan
from gravity_insight.workspace import load_workspace
from scripts.generate_execution_variant_characterization import (
    PRIVATE_EVENT,
    PRIVATE_ROW,
    ROOT,
    _FixtureInsight,
    _request,
    _result,
)


_EVIDENCE_FIELDS = {
    "input_semantics": "input_sha256",
    "output_semantics": "output_sha256",
    "completeness": "completeness_sha256",
    "data_quality": "data_quality_sha256",
    "allowed_claims": "allowed_claims_sha256",
    "privacy": "privacy_sha256",
    "freshness": "freshness_sha256",
    "request_count": "request_count",
    "journey_regression": "journey_sha256",
}
_PRODUCT_DIGEST = "598f9af7dfa77e81a0398c1123a6cf188795044002d428276e78e576c93ce8fa"


def _selection_service(status="stable", reasons=()):
    class Trust:
        @staticmethod
        def trust(identity_kind, selector):
            return {
                "identity_kind": identity_kind,
                "selector": selector,
                "contract_digest": _PRODUCT_DIGEST,
                "trust_status": status,
                "reason_codes": list(reasons),
            }

    return ExecutionVariantService(lambda: Trust())


class ExecutionVariantContractTests(unittest.TestCase):
    def test_registry_is_closed_fixed_and_bound_to_the_real_product_contract(self) -> None:
        descriptors = execution_variant_descriptors()
        self.assertEqual((DIRECT_VARIANT_URI, PLAN_VARIANT_URI), tuple(
            item["variant_uri"] for item in descriptors
        ))
        self.assertEqual(("direct_product", "plan_adapter"), tuple(
            item["implementation"]["topology"] for item in descriptors
        ))
        for descriptor in descriptors:
            self.assertEqual(descriptor, validate_execution_variant(descriptor))
            self.assertEqual((
                PRODUCT_SELECTOR,
                "598f9af7dfa77e81a0398c1123a6cf188795044002d428276e78e576c93ce8fa",
                ["returned-event-metric-observation"],
                "user_level",
                [REFERENCE_JOURNEY],
                True,
                False,
                False,
            ), (
                descriptor["product"]["selector"],
                descriptor["product"]["contract_digest"],
                descriptor["semantics"]["allowed_claims"],
                descriptor["semantics"]["privacy_classification"],
                descriptor["semantics"]["journey_ids"],
                descriptor["rollback"]["capability_preserved"],
                descriptor["automatic_selection"],
                descriptor["network_called"],
            ))

        service = ExecutionVariantService()
        for name in ("register", "execute", "pin", "benchmark"):
            self.assertFalse(hasattr(service, name))
        self.assertTrue(callable(service.select))
        source = inspect.getsource(sys.modules[ExecutionVariantService.__module__])
        self.assertNotIn("entry_points", source)
        self.assertNotIn("import_module", source)

    def test_descriptor_identity_semantics_and_digest_tamper_fail_closed(self) -> None:
        descriptor = execution_variant_descriptors()[0]
        mutations = (
            lambda item: item["product"].__setitem__("contract_digest", "0" * 64),
            lambda item: item["implementation"].__setitem__("owner", "caller"),
            lambda item: item["semantics"].__setitem__("allowed_claims", []),
            lambda item: item["rollback"].__setitem__("strategy", "switch_anywhere"),
            lambda item: item.__setitem__("automatic_selection", True),
            lambda item: item.__setitem__("descriptor_sha256", "0" * 64),
        )
        for mutate in mutations:
            changed = copy.deepcopy(descriptor)
            mutate(changed)
            with self.subTest(mutate=mutate), self.assertRaises(
                ExecutionVariantContractError
            ):
                validate_execution_variant(changed)


class ExecutionVariantCharacterizationTests(unittest.TestCase):
    def test_generated_corpus_is_current_value_free_and_nine_dimensional(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "generate_execution_variant_characterization.py"),
                "--check",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        artifact = load_execution_variant_characterization()
        self.assertEqual(
            artifact, validate_execution_variant_characterization(artifact)
        )
        self.assertEqual((4, True, True, []), (
            artifact["corpus"]["case_count"], artifact["equivalent"],
            artifact["fixed"], artifact["mismatches"],
        ))
        self.assertEqual(
            {"equivalent"}, set(artifact["dimensions"].values())
        )
        for case in artifact["corpus"]["cases"]:
            self.assertEqual(case["baseline"], case["candidate"])
            self.assertEqual(1, case["baseline"]["request_count"])
        rendered = json.dumps(artifact, sort_keys=True)
        for private in (
            PRIVATE_EVENT,
            PRIVATE_ROW,
            "1787554279563Y7jyuoWZwFBto1tlFsR",
            '"demo"',
            "2026-08-01",
            "PresetAllCount",
            "compiled_trace",
        ):
            self.assertNotIn(private, rendered)

    def test_direct_and_plan_adapter_paths_have_exact_outputs_and_wire_inputs(self) -> None:
        workspace = load_workspace(ROOT / "examples" / "workspace")
        request = _request()
        for case_id in ("success", "empty", "contract_drift", "runtime_failure"):
            outputs = []
            traces = []
            for variant_uri in (DIRECT_VARIANT_URI, PLAN_VARIANT_URI):
                insight = _FixtureInsight(_result(case_id))
                sdk = GravitySDK(insight=insight, workspace=workspace)
                context = AdapterContext(
                    "variant", "variant", "composite", workspace, (), (), 5, 200
                )
                outputs.append(
                    execute_fixed_analysis_query_event_variant(
                        sdk, copy.deepcopy(request), context, variant_uri
                    )
                )
                traces.append(insight.reads)
            with self.subTest(case_id=case_id):
                self.assertEqual(outputs[0], outputs[1])
                self.assertEqual(traces[0], traces[1])
                self.assertEqual("analysis.event.query", traces[0][0]["operation_id"])
                self.assertEqual(1, len(traces[0]))

    def test_each_semantic_dimension_mismatch_is_machine_decidable(self) -> None:
        artifact = load_execution_variant_characterization()
        original = artifact["corpus"]["cases"]
        for dimension, field in _EVIDENCE_FIELDS.items():
            cases = copy.deepcopy(original)
            current = cases[0]["candidate"][field]
            cases[0]["candidate"][field] = (
                current + 1 if field == "request_count" else "0" * 64
            )
            changed = build_execution_variant_characterization(cases)
            with self.subTest(dimension=dimension):
                self.assertFalse(changed["equivalent"])
                self.assertEqual("mismatch", changed["dimensions"][dimension])
                self.assertEqual(dimension, changed["mismatches"][0]["dimension"])
                self.assertEqual(
                    changed,
                    validate_execution_variant_characterization(changed),
                )

    def test_artifact_product_variant_corpus_result_and_rollback_tamper_stop(self) -> None:
        artifact = load_execution_variant_characterization()
        mutations = (
            lambda item: item["product"].__setitem__("contract_digest", "0" * 64),
            lambda item: item["variants"][0].__setitem__(
                "descriptor_sha256", "0" * 64
            ),
            lambda item: item["corpus"].__setitem__("corpus_sha256", "0" * 64),
            lambda item: item["dimensions"].__setitem__(
                "privacy", "mismatch"
            ),
            lambda item: item["rollback"].__setitem__(
                "capability_preserved", False
            ),
            lambda item: item.__setitem__("artifact_sha256", "0" * 64),
            lambda item: item.__setitem__("extra", "not allowed"),
        )
        for mutate in mutations:
            changed = copy.deepcopy(artifact)
            mutate(changed)
            with self.subTest(mutate=mutate), self.assertRaises(
                ExecutionVariantContractError
            ):
                validate_execution_variant_characterization(changed)


class ExecutionVariantServiceTests(unittest.TestCase):
    def test_service_attaches_current_trust_but_never_enables_selection(self) -> None:
        class Trust:
            @staticmethod
            def trust(identity_kind, selector):
                return {
                    "identity_kind": identity_kind,
                    "selector": selector,
                    "contract_digest": (
                        "598f9af7dfa77e81a0398c1123a6cf188795044002d428276e78e576c93ce8fa"
                    ),
                    "trust_status": "stable",
                    "reason_codes": [],
                }

        service = ExecutionVariantService(lambda: Trust())
        listing = service.list(PRODUCT_SELECTOR)
        described = service.describe(DIRECT_VARIANT_URI)
        report = service.characterization(PRODUCT_SELECTOR)
        self.assertEqual((2, "direct_product", "stable"), (
            listing["count"], described["variant"]["implementation"]["topology"],
            report["current_trust"]["trust_status"],
        ))
        self.assertEqual(
            ("trust_gated", "trust_gated"),
            (listing["selection_status"], described["selection_status"]),
        )
        self.assertEqual(("disabled_until_r14_d", False, False), (
            report["selection_status"], report["automatic_selection"],
            report["network_called"],
        ))

        sdk = GravitySDK(
            insight_factory=lambda: self.fail("Variant inspection must not build Insight"),
            sql_factory=lambda: self.fail("Variant inspection must not build SQL"),
            workspace=load_workspace(ROOT / "examples" / "workspace"),
        )
        self.assertIs(sdk.execution_variants, sdk.execution_variants)
        self.assertEqual(2, sdk.execution_variants.list()["count"])
        current = sdk.execution_variants.characterization(PRODUCT_SELECTOR)
        self.assertIn(
            current["current_trust"]["trust_status"],
            {"unknown", "degraded", "blocked", "quarantined"},
        )
        self.assertFalse(current["automatic_selection"])
        with patch.dict(
            os.environ, {"GRAVITY_EXECUTION_VARIANT_MODE": "automatic"}
        ):
            decision = sdk.execution_variants.select(
                PRODUCT_SELECTOR, pinned_variant_uri=PLAN_VARIANT_URI
            )
        self.assertEqual(DIRECT_VARIANT_URI, decision["selected_variant_uri"])
        self.assertFalse(decision["network_called"])
        rendered = json.dumps(decision, sort_keys=True)
        for private in (PRIVATE_EVENT, PRIVATE_ROW, "2026-08-01", "compiled_trace"):
            self.assertNotIn(private, rendered)

    def test_nonstable_trust_falls_back_before_evaluating_a_plan_pin(self) -> None:
        for status in ("unknown", "degraded", "blocked", "quarantined"):
            service = _selection_service(status, ("CAPABILITY_VALIDATION_MISSING",))
            with patch.dict(
                os.environ, {"GRAVITY_EXECUTION_VARIANT_MODE": "automatic"}
            ):
                result = service.select(
                    PRODUCT_SELECTOR, pinned_variant_uri=PLAN_VARIANT_URI
                )
            with self.subTest(status=status):
                self.assertEqual(DIRECT_VARIANT_URI, result["selected_variant_uri"])
                self.assertEqual("canonical_fallback", result["selection_status"])
                self.assertEqual(
                    {"requested": True, "evaluated": False, "variant_uri": None},
                    result["pin"],
                )
                self.assertEqual(
                    ["passed", "failed", "not_evaluated", "not_evaluated", "not_evaluated"],
                    [item["outcome"] for item in result["gates"]],
                )
                self.assertFalse(any(item["eligible"] for item in result["candidates"]))
                self.assertFalse(result["automatic_selection"])

    def test_stable_automatic_selection_uses_only_bound_objective_facts(self) -> None:
        service = _selection_service()
        with patch.dict(os.environ, {}, clear=True):
            first = service.select(PRODUCT_SELECTOR)
            second = service.select(PRODUCT_SELECTOR)

        self.assertEqual(first, second)
        self.assertEqual("automatic", first["mode"])
        self.assertEqual(first, validate_execution_variant_selection(first))
        self.assertEqual(DIRECT_VARIANT_URI, first["selected_variant_uri"])
        self.assertEqual("automatic_selection", first["selection_status"])
        self.assertTrue(first["automatic_selection"])
        self.assertEqual([1, 2], [
            item["local_topology_hops"] for item in first["candidates"]
        ])
        self.assertTrue(all(item["eligible"] for item in first["candidates"]))
        self.assertEqual(("unavailable", "unavailable"), (
            first["objective_facts"]["latency_evidence"],
            first["objective_facts"]["cost_evidence"],
        ))
        self.assertEqual(first["decision_sha256"], selection_digest(first))

    def test_stable_exact_pin_selects_either_fixed_variant(self) -> None:
        service = _selection_service()
        with patch.dict(
            os.environ, {"GRAVITY_EXECUTION_VARIANT_MODE": "automatic"}
        ):
            for uri in (DIRECT_VARIANT_URI, PLAN_VARIANT_URI):
                result = service.select(PRODUCT_SELECTOR, pinned_variant_uri=uri)
                with self.subTest(uri=uri):
                    self.assertEqual(uri, result["selected_variant_uri"])
                    self.assertEqual("pinned_selection", result["selection_status"])
                    self.assertEqual(
                        {"requested": True, "evaluated": True, "variant_uri": uri},
                        result["pin"],
                    )
                    self.assertEqual(
                        [uri],
                        [
                            item["variant_uri"]
                            for item in result["candidates"]
                            if item["eligible"]
                        ],
                    )
                    self.assertFalse(result["automatic_selection"])

    def test_public_analysis_entry_executes_the_selected_direct_or_plan_owner(self) -> None:
        workspace = load_workspace(ROOT / "examples" / "workspace")
        request = _request()
        owner_calls = []
        outputs = []

        with patch.dict(
            os.environ,
            {"GRAVITY_EXECUTION_VARIANT_MODE": "automatic"},
            clear=True,
        ):
            for uri in (DIRECT_VARIANT_URI, PLAN_VARIANT_URI):
                insight = _FixtureInsight(_result("success"))
                sdk = GravitySDK(insight=insight, workspace=workspace)
                service = _selection_service()
                sdk._execution_variants_service = service
                with (
                    patch.object(
                        service, "select", wraps=service.select
                    ) as select_owner,
                    patch.object(
                        sdk,
                        "_analysis_query_direct",
                        wraps=sdk._analysis_query_direct,
                    ) as direct_owner,
                    patch(
                        "gravity_insight.plan_analysis_adapter.execute_analysis_query_plan",
                        wraps=execute_analysis_query_plan,
                    ) as plan_owner,
                ):
                    result = sdk.analysis_query(
                        request["kind"],
                        copy.deepcopy(request["spec"]),
                        app=request["app"],
                        pinned_variant_uri=uri,
                    )

                with self.subTest(uri=uri):
                    self.assertEqual("success", result["status"])
                    select_owner.assert_called_once_with(
                        PRODUCT_SELECTOR, pinned_variant_uri=uri
                    )
                    self.assertEqual(1, direct_owner.call_count)
                    self.assertEqual(uri == PLAN_VARIANT_URI, plan_owner.called)
                    self.assertEqual(1, len(insight.reads))
                    self.assertEqual(
                        "analysis.event.query", insight.reads[0]["operation_id"]
                    )
                owner_calls.append((direct_owner.call_count, plan_owner.call_count))
                outputs.append(result)

        self.assertEqual([(1, 0), (1, 1)], owner_calls)
        self.assertEqual(outputs[0], outputs[1])
        self.assertNotIn("request", outputs[0])

    def test_public_analysis_entry_applies_trust_and_kill_switch_before_plan(self) -> None:
        workspace = load_workspace(ROOT / "examples" / "workspace")
        request = _request()
        cases = (
            ("blocked", "automatic"),
            ("stable", "disabled"),
        )
        for trust_status, mode in cases:
            insight = _FixtureInsight(_result("success"))
            sdk = GravitySDK(insight=insight, workspace=workspace)
            sdk._execution_variants_service = _selection_service(
                trust_status, ("CAPABILITY_VALIDATION_MISSING",)
            )
            with (
                patch.dict(
                    os.environ,
                    {"GRAVITY_EXECUTION_VARIANT_MODE": mode},
                    clear=True,
                ),
                patch.object(
                    sdk,
                    "_analysis_query_direct",
                    wraps=sdk._analysis_query_direct,
                ) as direct_owner,
                patch(
                    "gravity_insight.plan_analysis_adapter.execute_analysis_query_plan",
                    wraps=execute_analysis_query_plan,
                ) as plan_owner,
            ):
                result = sdk.analysis_query(
                    request["kind"],
                    copy.deepcopy(request["spec"]),
                    app=request["app"],
                    pinned_variant_uri=PLAN_VARIANT_URI,
                )

            with self.subTest(trust_status=trust_status, mode=mode):
                self.assertEqual("success", result["status"])
                self.assertEqual(1, direct_owner.call_count)
                self.assertFalse(plan_owner.called)
                self.assertEqual(1, len(insight.reads))

    def test_public_analysis_entry_fails_closed_before_invalid_selection_executes(self) -> None:
        workspace = load_workspace(ROOT / "examples" / "workspace")
        request = _request()
        cases = (
            ("automatic", "gravity.execution-variant/unknown/path@1"),
            ("experimental", PLAN_VARIANT_URI),
        )
        for mode, uri in cases:
            insight = _FixtureInsight(_result("success"))
            sdk = GravitySDK(insight=insight, workspace=workspace)
            sdk._execution_variants_service = _selection_service()
            with (
                patch.dict(
                    os.environ,
                    {"GRAVITY_EXECUTION_VARIANT_MODE": mode},
                    clear=True,
                ),
                self.assertRaises(InputValidationError),
            ):
                sdk.analysis_query(
                    request["kind"],
                    copy.deepcopy(request["spec"]),
                    app=request["app"],
                    pinned_variant_uri=uri,
                )
            with self.subTest(mode=mode, uri=uri):
                self.assertEqual([], insight.reads)

    def test_disabled_mode_is_canonical_and_unknown_mode_fails_after_trust(self) -> None:
        calls = []

        class Trust:
            @staticmethod
            def trust(identity_kind, selector):
                calls.append((identity_kind, selector))
                return {
                    "identity_kind": identity_kind,
                    "selector": selector,
                    "contract_digest": _PRODUCT_DIGEST,
                    "trust_status": "stable",
                    "reason_codes": [],
                }

        service = ExecutionVariantService(lambda: Trust())
        with patch.dict(
            os.environ, {"GRAVITY_EXECUTION_VARIANT_MODE": "disabled"}
        ):
            disabled = service.select(
                PRODUCT_SELECTOR, pinned_variant_uri="private-unvalidated-pin"
            )
        self.assertEqual(DIRECT_VARIANT_URI, disabled["selected_variant_uri"])
        self.assertEqual("canonical_fallback", disabled["selection_status"])
        self.assertFalse(disabled["pin"]["evaluated"])
        self.assertIn("EXECUTION_VARIANT_MODE_DISABLED", disabled["reason_codes"])

        with patch.dict(
            os.environ, {"GRAVITY_EXECUTION_VARIANT_MODE": "experimental"}
        ), self.assertRaises(InputValidationError) as raised:
            service.select(PRODUCT_SELECTOR)
        self.assertEqual("EXECUTION_VARIANT_MODE_INVALID", raised.exception.code)
        self.assertEqual(2, len(calls))

    def test_fixed_characterization_is_validated_before_current_trust(self) -> None:
        trust_factories = []
        service = ExecutionVariantService(
            lambda: trust_factories.append("constructed") or object()
        )
        error = ExecutionVariantContractError(
            "EXECUTION_VARIANT_CHARACTERIZATION_STALE", "fixture is stale"
        )
        with patch(
            "gravity_insight.execution_variant.load_execution_variant_characterization",
            side_effect=error,
        ), self.assertRaises(ExecutionVariantContractError) as raised:
            service.select(PRODUCT_SELECTOR)
        self.assertEqual(
            "EXECUTION_VARIANT_CHARACTERIZATION_STALE",
            raised.exception.reason_code,
        )
        self.assertEqual([], trust_factories)

    def test_unknown_pin_fails_only_when_pin_gate_is_reached(self) -> None:
        with patch.dict(
            os.environ, {"GRAVITY_EXECUTION_VARIANT_MODE": "automatic"}
        ), self.assertRaises(InputValidationError) as raised:
            _selection_service().select(
                PRODUCT_SELECTOR,
                pinned_variant_uri="gravity.execution-variant/unknown/path@1",
            )
        self.assertEqual("EXECUTION_VARIANT_UNKNOWN", raised.exception.code)

    def test_selection_schema_digest_and_policy_tamper_fail_closed(self) -> None:
        with patch.dict(
            os.environ, {"GRAVITY_EXECUTION_VARIANT_MODE": "automatic"}
        ):
            result = _selection_service().select(PRODUCT_SELECTOR)
        mutations = (
            lambda item: item["characterization"].__setitem__(
                "artifact_sha256", "0" * 64
            ),
            lambda item: item["candidates"][0].__setitem__(
                "local_topology_hops", 2
            ),
            lambda item: item.__setitem__("selected_variant_uri", PLAN_VARIANT_URI),
            lambda item: item["gates"].reverse(),
            lambda item: item["rollback"].__setitem__(
                "capability_preserved", False
            ),
            lambda item: item.__setitem__("extra", "not allowed"),
        )
        for mutate in mutations:
            changed = copy.deepcopy(result)
            mutate(changed)
            changed["decision_sha256"] = selection_digest(changed)
            with self.subTest(mutate=mutate), self.assertRaises(
                ExecutionVariantContractError
            ):
                validate_execution_variant_selection(changed)

        changed = copy.deepcopy(result)
        changed["decision_sha256"] = "0" * 64
        with self.assertRaises(ExecutionVariantContractError):
            validate_execution_variant_selection(changed)

    def test_unknown_product_variant_and_runner_scope_are_actionable(self) -> None:
        service = ExecutionVariantService()
        calls = (
            lambda: service.list("product:unknown"),
            lambda: service.characterization("product:unknown"),
            lambda: service.describe("gravity.execution-variant/unknown/path@1"),
        )
        expected = (
            "EXECUTION_VARIANT_PRODUCT_UNKNOWN",
            "EXECUTION_VARIANT_PRODUCT_UNKNOWN",
            "EXECUTION_VARIANT_UNKNOWN",
        )
        for call, code in zip(calls, expected, strict=True):
            with self.subTest(code=code), self.assertRaises(
                InputValidationError
            ) as raised:
                call()
            self.assertEqual(code, raised.exception.code)

        class SDK:
            insight = object()

        workspace = load_workspace(ROOT / "examples" / "workspace")
        context = AdapterContext(
            "variant", "variant", "composite", workspace, (), (), 5, 200
        )
        request = _request()
        request["kind"] = "funnel"
        with self.assertRaises(InputValidationError) as product:
            execute_fixed_analysis_query_event_variant(
                SDK(), request, context, DIRECT_VARIANT_URI
            )
        self.assertEqual("EXECUTION_VARIANT_PRODUCT_UNKNOWN", product.exception.code)
        request["kind"] = "event"
        with self.assertRaises(InputValidationError) as variant:
            execute_fixed_analysis_query_event_variant(
                SDK(), request, context, "unknown"
            )
        self.assertEqual("EXECUTION_VARIANT_UNKNOWN", variant.exception.code)

    def test_root_exports_are_lazy_and_exact(self) -> None:
        import gravity_insight

        self.assertIs(gravity_insight.ExecutionVariantService, ExecutionVariantService)
        self.assertIs(
            gravity_insight.validate_execution_variant,
            validate_execution_variant,
        )
        self.assertIs(
            gravity_insight.validate_execution_variant_characterization,
            validate_execution_variant_characterization,
        )
        self.assertIs(
            gravity_insight.validate_execution_variant_selection,
            validate_execution_variant_selection,
        )


if __name__ == "__main__":
    unittest.main()
