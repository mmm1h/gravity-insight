"""R14-C fixed Variant contracts, corpus, Trust, and privacy gates."""

from __future__ import annotations

import copy
import inspect
import json
import subprocess
import sys
import unittest

from gravity_sdk import (
    ExecutionVariantService,
    GravitySDK,
    validate_execution_variant,
    validate_execution_variant_characterization,
)
from gravity_sdk.analysis_query_execution_variant import (
    execute_fixed_analysis_query_event_variant,
)
from gravity_sdk.errors import InputValidationError
from gravity_sdk.execution_variant import ExecutionVariantContractError
from gravity_sdk.execution_variant_characterization import (
    build_execution_variant_characterization,
    load_execution_variant_characterization,
)
from gravity_sdk.execution_variant_contract import (
    DIRECT_VARIANT_URI,
    PLAN_VARIANT_URI,
    PRODUCT_SELECTOR,
    REFERENCE_JOURNEY,
    execution_variant_descriptors,
)
from gravity_sdk.plan import AdapterContext
from gravity_sdk.workspace import load_workspace
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
                "76342fbd1eaebf3f9f23c506badd5c76d5e163d300c16aec1daf33ce498640dd",
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
        for name in ("register", "execute", "select", "pin", "benchmark"):
            self.assertFalse(hasattr(service, name))
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
                        "76342fbd1eaebf3f9f23c506badd5c76d5e163d300c16aec1daf33ce498640dd"
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
        import gravity_sdk

        self.assertIs(gravity_sdk.ExecutionVariantService, ExecutionVariantService)
        self.assertIs(
            gravity_sdk.validate_execution_variant,
            validate_execution_variant,
        )
        self.assertIs(
            gravity_sdk.validate_execution_variant_characterization,
            validate_execution_variant_characterization,
        )


if __name__ == "__main__":
    unittest.main()
