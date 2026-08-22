from __future__ import annotations

import copy
import contextlib
import io
import json
from pathlib import Path
import unittest

from gravity_sdk import ExperimentHandoffService, GravitySDK
from gravity_sdk import cli
from gravity_sdk.agent_runtime_contracts import canonical_digest, validate_schema
from gravity_sdk.execution_snapshot import build_execution_snapshot
from gravity_sdk.experiment_handoff import (
    ExperimentContractError,
    OUTCOME_JOURNEY_ID,
    compile_experiment_power_analysis,
    compile_experiment_proposal,
    compile_outcome_evaluation_handoff,
    validate_experiment_proposal,
    validate_outcome_evaluation_handoff,
)
from tests.test_analysis_result_contract import success_result


PRIMARY_URI = "metric://project/activation-rate@1"
GUARDRAIL_URI = "metric://project/error-rate@1"
POWER_URI = "operator://gravity/experiment-power@1"
SEGMENT_DIGEST = "1" * 64


def source_analysis(*, window_verified: bool = True) -> dict[str, object]:
    value = success_result()
    value["question"] = "private source question"
    value["findings"][0]["statement"] = "private source finding"
    if window_verified:
        value["scope"]["timezone"] = "UTC"
    return value


def semantic(uri: str, digit: str = "2", *, status: str = "resolved") -> dict[str, object]:
    return {
        "uri": uri,
        "version": 1 if status == "resolved" else None,
        "definition_digest": digit * 64 if status == "resolved" else None,
        "binding_digest": chr(ord(digit) + 1) * 64 if status == "resolved" else None,
        "source_digest": chr(ord(digit) + 2) * 64 if status == "resolved" else None,
        "registry_digest": chr(ord(digit) + 3) * 64 if status == "resolved" else None,
        "status": status,
    }


def planning_snapshot(
    analysis: dict[str, object],
    *,
    primary_status: str = "resolved",
    guardrail_status: str = "resolved",
    operator_uri: str = POWER_URI,
) -> dict[str, object]:
    source = analysis["execution_snapshot"]
    return build_execution_snapshot(
        status="resolved",
        journey=source["journey"],
        skill=source["skill"],
        project_overlay=source["project_overlay"],
        capabilities=source["capabilities"],
        semantics=[
            semantic(PRIMARY_URI, "2", status=primary_status),
            semantic(GUARDRAIL_URI, "6", status=guardrail_status),
        ],
        operators=[
            {
                "uri": operator_uri,
                "version": 1,
                "digest": "a" * 64,
                "assumptions_digest": "b" * 64,
                "status": "available",
            }
        ],
        models=[],
        context_packs=source["context_packs"],
        contracts=source["contracts"],
        runtime_version=source["runtime"]["version"],
    )


def power_analysis(
    *,
    metric_uri: str = PRIMARY_URI,
    target_digest: str = SEGMENT_DIGEST,
    operator_uri: str = POWER_URI,
    alpha: float = 0.05,
    power: float = 0.8,
    effect: float = 0.02,
) -> dict[str, object]:
    value = {
        "schema_version": "gravity.experiment-power-analysis.v1",
        "status": "complete",
        "operator": {
            "uri": operator_uri,
            "version": 1,
            "digest": "a" * 64,
            "assumptions_digest": "b" * 64,
        },
        "primary_metric_uri": metric_uri,
        "target_segment_digest": target_digest,
        "alpha": alpha,
        "power": power,
        "minimum_detectable_effect": effect,
        "minimum_sample_size_per_arm": 800,
        "reason_codes": [],
        "result_digest": None,
    }
    value["result_digest"] = canonical_digest(
        {key: item for key, item in value.items() if key != "result_digest"}
    )
    return value


def unavailable_power() -> dict[str, object]:
    return {
        "schema_version": "gravity.experiment-power-analysis.v1",
        "status": "unavailable",
        "operator": None,
        "primary_metric_uri": None,
        "target_segment_digest": None,
        "alpha": None,
        "power": None,
        "minimum_detectable_effect": None,
        "minimum_sample_size_per_arm": None,
        "reason_codes": ["OPERATOR_UNAVAILABLE"],
        "result_digest": None,
    }


def proposal_request(
    *,
    analysis: dict[str, object] | None = None,
    snapshot: dict[str, object] | None = None,
) -> dict[str, object]:
    selected_analysis = analysis or source_analysis()
    selected_snapshot = snapshot or planning_snapshot(selected_analysis)
    [context] = selected_snapshot["context_packs"]
    return {
        "schema_version": "gravity.experiment-proposal-request.v1",
        "source_analysis_result": selected_analysis,
        "planning_snapshot": selected_snapshot,
        "hypothesis": {
            "statement": "The treatment may improve activation without increasing errors.",
            "direction": "increase",
            "rationale_digest": "c" * 64,
        },
        "source_window": {
            "start": "2026-08-01",
            "end": "2026-08-07",
            "timezone": "UTC",
        },
        "target_segment": {
            "uri": "segment://project/eligible-users@1",
            "digest": SEGMENT_DIGEST,
            "source": "registered_segment",
        },
        "primary_metric": {
            "uri": PRIMARY_URI,
            "success_direction": "increase",
        },
        "guardrails": [
            {"uri": GUARDRAIL_URI, "breach_direction": "increase"}
        ],
        "power_analysis": power_analysis(),
        "context_assumptions": [
            {
                "assumption_id": "release.freeze",
                "assumption_digest": "d" * 64,
                "requirement_uri": context["requirement_uri"],
                "pack_digest": context["pack_digest"],
            }
        ],
        "created_at": "2026-08-08T00:00:00Z",
    }


def observation(
    proposal: dict[str, object],
    *,
    status: str = "completed",
    started_at: str = "2026-08-10T00:00:00Z",
    ended_at: str = "2026-08-20T00:00:00Z",
) -> dict[str, object]:
    return {
        "schema_version": "gravity.experiment-observation.v1",
        "experiment_ref": "experiment://external/activation-test@1",
        "proposal_id": proposal["proposal_id"],
        "proposal_digest": proposal["proposal_digest"],
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at,
        "assignment_digest": "e" * 64 if status == "completed" else None,
        "evidence_digest": "f" * 64 if status == "completed" else None,
    }


def outcome_request(
    proposal: dict[str, object],
    *,
    observed: dict[str, object] | None = None,
    start: str = "2026-08-10",
    end: str = "2026-08-20",
    timezone: str = "UTC",
) -> dict[str, object]:
    return {
        "schema_version": "gravity.outcome-evaluation-handoff-request.v1",
        "proposal": proposal,
        "observation": observed or observation(proposal),
        "evidence_window": {"start": start, "end": end, "timezone": timezone},
        "created_at": "2026-08-21T00:00:00Z",
    }


def resign_proposal(value: dict[str, object]) -> dict[str, object]:
    selected = copy.deepcopy(value)
    body = {
        key: item
        for key, item in selected.items()
        if key not in {"proposal_id", "proposal_digest"}
    }
    selected["proposal_id"] = "exp1_" + canonical_digest(body)[:32]
    selected["proposal_digest"] = canonical_digest(
        {key: item for key, item in selected.items() if key != "proposal_digest"}
    )
    return selected


def resign_handoff(value: dict[str, object]) -> dict[str, object]:
    selected = copy.deepcopy(value)
    body = {
        key: item
        for key, item in selected.items()
        if key not in {"handoff_id", "handoff_digest"}
    }
    selected["handoff_id"] = "out1_" + canonical_digest(body)[:32]
    selected["handoff_digest"] = canonical_digest(
        {key: item for key, item in selected.items() if key != "handoff_digest"}
    )
    return selected


class ExperimentProposalTests(unittest.TestCase):
    def test_dependency_complete_proposal_is_review_only_and_value_bounded(self) -> None:
        request = proposal_request()
        first = compile_experiment_proposal(request)
        second = ExperimentHandoffService().propose(request)

        self.assertEqual(first, second)
        self.assertEqual("ready_for_review", first["status"])
        self.assertTrue(all(value == "satisfied" for value in first["readiness"].values()))
        self.assertFalse(first["experiment_creation_authorized"])
        self.assertFalse(first["automatic_execution"])
        self.assertFalse(first["network_called"])
        self.assertEqual(first, validate_experiment_proposal(first))
        rendered = repr(first)
        for private in (
            "private source question",
            "private source finding",
            "Example context",
            "docs/context.md",
            "receipt_references",
        ):
            self.assertNotIn(private, rendered)

    def test_missing_dependencies_stay_proposal_only_with_stable_reasons(self) -> None:
        request = proposal_request(analysis=source_analysis(window_verified=False))
        request.update(
            {
                "target_segment": None,
                "primary_metric": None,
                "guardrails": [],
                "power_analysis": None,
                "context_assumptions": [],
            }
        )
        result = compile_experiment_proposal(request)

        self.assertEqual("proposal_only", result["status"])
        self.assertEqual(
            {
                "EXPERIMENT_SOURCE_WINDOW_UNPROVEN",
                "EXPERIMENT_TARGET_SEGMENT_MISSING",
                "EXPERIMENT_PRIMARY_METRIC_MISSING",
                "EXPERIMENT_GUARDRAILS_MISSING",
                "EXPERIMENT_POWER_ANALYSIS_MISSING",
                "EXPERIMENT_CONTEXT_ASSUMPTIONS_MISSING",
            },
            set(result["reason_codes"]),
        )
        self.assertFalse(result["experiment_creation_authorized"])

    def test_unresolved_semantic_power_and_context_never_promote_readiness(self) -> None:
        analysis = source_analysis()
        request = proposal_request(
            analysis=analysis,
            snapshot=planning_snapshot(
                analysis, primary_status="unresolved", guardrail_status="unresolved"
            ),
        )
        request["power_analysis"] = unavailable_power()
        request["context_assumptions"][0]["pack_digest"] = "0" * 64
        result = compile_experiment_proposal(request)

        self.assertEqual("proposal_only", result["status"])
        self.assertEqual("unresolved", result["readiness"]["primary_metric"])
        self.assertEqual("unresolved", result["readiness"]["guardrails"])
        self.assertEqual("unresolved", result["readiness"]["power_analysis"])
        self.assertEqual("unresolved", result["readiness"]["context_assumptions"])
        self.assertIn("OPERATOR_UNAVAILABLE", result["reason_codes"])

    def test_power_contract_and_cross_dependency_tamper_fail_closed(self) -> None:
        valid = power_analysis()
        self.assertEqual(valid, compile_experiment_power_analysis(valid))

        digest = copy.deepcopy(valid)
        digest["result_digest"] = "0" * 64
        with self.assertRaisesRegex(ExperimentContractError, "digest changed"):
            compile_experiment_power_analysis(digest)

        probability = power_analysis(alpha=0.0)
        with self.assertRaisesRegex(ExperimentContractError, "between 0 and 1"):
            compile_experiment_power_analysis(probability)

        request = proposal_request()
        request["guardrails"] = [
            {"uri": PRIMARY_URI, "breach_direction": "increase"}
        ]
        with self.assertRaisesRegex(ExperimentContractError, "Metric roles"):
            compile_experiment_proposal(request)

        changed_operator = proposal_request()
        changed_operator["power_analysis"] = power_analysis(
            operator_uri="operator://gravity/other-power@1"
        )
        result = compile_experiment_proposal(changed_operator)
        self.assertEqual("proposal_only", result["status"])
        self.assertIn(
            "EXPERIMENT_POWER_OPERATOR_UNRESOLVED", result["reason_codes"]
        )

    def test_source_snapshot_and_proposal_identity_tamper_fail_closed(self) -> None:
        request = proposal_request()
        request["planning_snapshot"]["snapshot_digest"] = "0" * 64
        with self.assertRaises(ExperimentContractError):
            compile_experiment_proposal(request)

        proposal = compile_experiment_proposal(proposal_request())
        proposal["hypothesis"]["statement"] = "changed"
        with self.assertRaisesRegex(ExperimentContractError, "identity changed"):
            validate_experiment_proposal(proposal)

        missing = proposal_request()
        missing["power_analysis"] = None
        proposal_only = compile_experiment_proposal(missing)
        proposal_only["reason_codes"] = ["EXPERIMENT_GUARDRAILS_MISSING"]
        with self.assertRaisesRegex(ExperimentContractError, "blockers contradict"):
            validate_experiment_proposal(resign_proposal(proposal_only))

        invalid_window = compile_experiment_proposal(proposal_request())
        invalid_window["source_analysis"]["source_window"]["end"] = "2026-99-99"
        with self.assertRaisesRegex(ExperimentContractError, "source_window is invalid"):
            validate_experiment_proposal(resign_proposal(invalid_window))

        blocked = proposal_request()
        blocked["source_analysis_result"]["status"] = "blocked"
        with self.assertRaises(ExperimentContractError):
            compile_experiment_proposal(blocked)


class OutcomeHandoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.proposal = compile_experiment_proposal(proposal_request())

    def test_completed_observation_creates_separate_handoff_not_evaluation(self) -> None:
        result = compile_outcome_evaluation_handoff(
            outcome_request(self.proposal)
        )

        self.assertEqual("handoff_ready", result["status"])
        self.assertEqual(OUTCOME_JOURNEY_ID, result["outcome_journey"]["journey_id"])
        self.assertEqual("blocked", result["outcome_journey"]["can_run_status"])
        self.assertEqual(
            ["OPERATOR_UNAVAILABLE"], result["outcome_journey"]["reason_codes"]
        )
        self.assertTrue(result["independence"]["journey_distinct"])
        self.assertTrue(result["independence"]["evidence_window_separate"])
        self.assertFalse(result["independence"]["same_run_evaluation_allowed"])
        self.assertFalse(
            result["independence"]["recommendation_self_validation_allowed"]
        )
        self.assertFalse(result["evaluation_performed"])
        self.assertFalse(result["network_called"])
        self.assertEqual(result, validate_outcome_evaluation_handoff(result))
        rendered = repr(result)
        for private in (
            "private source question",
            "private source finding",
            "user_rows",
            "metric_values",
            "vendor_payload",
        ):
            self.assertNotIn(private, rendered)

    def test_proposal_observation_and_window_blockers_are_machine_distinct(self) -> None:
        proposal_only_request = proposal_request()
        proposal_only_request["power_analysis"] = None
        proposal_only = compile_experiment_proposal(proposal_only_request)
        incomplete = observation(proposal_only, status="incomplete")
        result = compile_outcome_evaluation_handoff(
            outcome_request(
                proposal_only,
                observed=incomplete,
                start="2026-08-01",
                end="2026-08-02",
                timezone="Asia/Shanghai",
            )
        )

        self.assertEqual("blocked", result["status"])
        self.assertEqual(
            {
                "EXPERIMENT_PROPOSAL_NOT_READY",
                "EXPERIMENT_OBSERVATION_INCOMPLETE",
                "OUTCOME_EVIDENCE_WINDOW_MISMATCH",
                "OUTCOME_EVIDENCE_WINDOW_NOT_SEPARATE",
                "OUTCOME_EVIDENCE_TIMEZONE_MISMATCH",
            },
            set(result["reason_codes"]),
        )
        self.assertFalse(result["evaluation_performed"])

    def test_observation_binding_completion_and_order_fail_closed(self) -> None:
        wrong = observation(self.proposal)
        wrong["proposal_digest"] = "0" * 64
        with self.assertRaisesRegex(ExperimentContractError, "not bound"):
            compile_outcome_evaluation_handoff(
                outcome_request(self.proposal, observed=wrong)
            )

        missing = observation(self.proposal)
        missing["evidence_digest"] = None
        with self.assertRaisesRegex(ExperimentContractError, "requires"):
            compile_outcome_evaluation_handoff(
                outcome_request(self.proposal, observed=missing)
            )

        reversed_observation = observation(
            self.proposal,
            started_at="2026-08-20T00:00:00Z",
            ended_at="2026-08-10T00:00:00Z",
        )
        with self.assertRaisesRegex(ExperimentContractError, "window is invalid"):
            compile_outcome_evaluation_handoff(
                outcome_request(self.proposal, observed=reversed_observation)
            )

    def test_service_is_offline_and_handoff_digest_tamper_is_detected(self) -> None:
        service = ExperimentHandoffService()
        result = service.outcome_handoff(outcome_request(self.proposal))
        self.assertFalse(result["network_called"])

        result["evidence_window"]["end"] = "2026-08-21"
        with self.assertRaisesRegex(ExperimentContractError, "identity changed"):
            validate_outcome_evaluation_handoff(result)

        changed = service.outcome_handoff(outcome_request(self.proposal))
        changed["reason_codes"] = ["OUTCOME_EVIDENCE_WINDOW_MISMATCH"]
        changed["status"] = "blocked"
        with self.assertRaisesRegex(ExperimentContractError, "contradicts blockers"):
            validate_outcome_evaluation_handoff(resign_handoff(changed))

        invalid_timezone = service.outcome_handoff(outcome_request(self.proposal))
        invalid_timezone["evidence_window"]["timezone"] = "Mars/Olympus"
        with self.assertRaisesRegex(ExperimentContractError, "evidence_window is invalid"):
            validate_outcome_evaluation_handoff(resign_handoff(invalid_timezone))

        private_metric = service.outcome_handoff(outcome_request(self.proposal))
        private_metric["primary_metric"]["metric_values"] = ["private-user-row"]
        with self.assertRaises(ExperimentContractError):
            validate_outcome_evaluation_handoff(resign_handoff(private_metric))


class ExperimentSurfaceTests(unittest.TestCase):
    def test_sdk_property_is_lazy_cached_and_never_constructs_data_clients(self) -> None:
        def forbidden_client():
            raise AssertionError("Experiment handoff constructed a data client")

        sdk = GravitySDK(
            insight_factory=forbidden_client,
            sql_factory=forbidden_client,
        )
        service = sdk.experiments

        self.assertIsInstance(service, ExperimentHandoffService)
        self.assertIs(service, sdk.experiments)
        result = service.propose(proposal_request())
        self.assertEqual("ready_for_review", result["status"])
        self.assertFalse(result["network_called"])

    def test_cli_commands_are_explicit_offline_and_emit_contracts(self) -> None:
        parser = cli.build_parser()
        proposal_args = parser.parse_args(
            ["experiment", "propose", "--input", json.dumps(proposal_request())]
        )
        outcome_args = parser.parse_args(
            [
                "experiment",
                "outcome-handoff",
                "--input",
                json.dumps(outcome_request(compile_experiment_proposal(proposal_request()))),
            ]
        )
        self.assertFalse(proposal_args.network_required)
        self.assertFalse(outcome_args.network_required)

        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(
                ["experiment", "propose", "--input", json.dumps(proposal_request())]
            )
        self.assertEqual(0, code)
        self.assertEqual("", stderr.getvalue())
        result = json.loads(stdout.getvalue())
        self.assertEqual("gravity.experiment-proposal.v1", result["schema_version"])
        self.assertFalse(result["network_called"])

        invalid = proposal_request()
        invalid["private_unknown"] = "credential=private-cli-value"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(
                ["experiment", "propose", "--input", json.dumps(invalid)]
            )
        self.assertEqual(2, code)
        self.assertEqual("", stdout.getvalue())
        self.assertNotIn("private-cli-value", stderr.getvalue())

    def test_all_machine_schemas_are_packaged_local_and_observation_is_standalone(self) -> None:
        root = (
            Path(__file__).resolve().parents[1]
            / "src/gravity_sdk/contracts/schema"
        )
        expected = {
            "experiment-power-analysis-v1.schema.json": "gravity.experiment-power-analysis.v1",
            "experiment-proposal-request-v1.schema.json": "gravity.experiment-proposal-request.v1",
            "experiment-proposal-v1.schema.json": "gravity.experiment-proposal.v1",
            "experiment-observation-v1.schema.json": "gravity.experiment-observation.v1",
            "outcome-evaluation-handoff-request-v1.schema.json": "gravity.outcome-evaluation-handoff-request.v1",
            "outcome-evaluation-handoff-v1.schema.json": "gravity.outcome-evaluation-handoff.v1",
        }
        for name, schema_id in expected.items():
            with self.subTest(name=name):
                schema = json.loads((root / name).read_text(encoding="utf-8"))
                self.assertEqual(schema_id, schema["$id"])
                self.assertTrue(
                    all(reference.startswith("#/") for reference in references(schema))
                )

        proposal = compile_experiment_proposal(proposal_request())
        observed = observation(proposal)
        validate_schema(
            observed,
            "experiment-observation-v1.schema.json",
            "Experiment observation",
        )


def references(value: object) -> list[str]:
    result = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "$ref":
                result.append(str(item))
            result.extend(references(item))
    elif isinstance(value, list):
        for item in value:
            result.extend(references(item))
    return result


if __name__ == "__main__":
    unittest.main()
