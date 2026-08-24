"""R13C Artifact binding, Action claims and Kanban readback gates."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from gravity_sdk import GravitySDK, host_source
from gravity_sdk.action_dashboard_connector import (
    ACTION_KIND,
    CONNECTOR_ID,
    REQUEST_SCHEMA_VERSION,
)
from gravity_sdk.agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)
from gravity_sdk.analysis_artifact import compile_analysis_artifact
from gravity_sdk.errors import InputValidationError
from gravity_sdk.find_input import object_input
from gravity_sdk.kanban_mutation_contracts import DASHBOARD_UPDATE, DETAIL
from gravity_sdk.result_audit import SCHEMA_VERSION as AUDIT_SCHEMA_VERSION
from tests.test_analysis_artifact import blocked_result, result_with_semantics


SCOPE = "d" * 32
SOURCE_RECEIPT = "a" * 32
WRITE_RECEIPT = "b" * 32


class DashboardInsight:
    def __init__(self) -> None:
        self.principal = "91"
        self.contract_revision = 1
        self.reads = 0
        self.writes = 0
        self.readback_error = False
        self.detail = {
            "id": 30,
            "name": "Analysis Delivery | GSDK-0123456789ab",
            "app_id": 101,
            "space_id": 10,
            "ui_config": "[]",
            "even_report": [],
            "create_user_id": "91",
            "create_user_name": "private-owner",
        }

    def _current_principal_id(self) -> str:
        return self.principal

    def describe(self, operation_id: str) -> dict[str, object]:
        if operation_id not in {DETAIL, DASHBOARD_UPDATE}:
            raise AssertionError(operation_id)
        return {
            "operation_id": operation_id,
            "contract_version": self.contract_revision,
            "effect": "mutation" if operation_id == DASHBOARD_UPDATE else "read",
            "stability": "stable",
        }

    def read(
        self, operation_id: str, inputs: dict[str, object]
    ) -> dict[str, object]:
        if operation_id != DETAIL:
            raise AssertionError(operation_id)
        self.reads += 1
        if self.readback_error and self.writes:
            return {
                "ok": False,
                "status": "error",
                "error": {"code": "UPSTREAM_UNAVAILABLE"},
            }
        return {
            "ok": True,
            "status": "success",
            "data": copy.deepcopy(self.detail),
        }

    def _preview_mutation(
        self, operation_id: str, inputs: dict[str, object]
    ) -> dict[str, object]:
        if operation_id != DASHBOARD_UPDATE:
            raise AssertionError(operation_id)
        return {
            "ok": True,
            "status": "preview",
            "operation_id": operation_id,
            "network_called": False,
        }

    def _execute_mutation(
        self, operation_id: str, inputs: dict[str, object]
    ) -> dict[str, object]:
        if operation_id != DASHBOARD_UPDATE:
            raise AssertionError(operation_id)
        self.writes += 1
        self.detail["ui_config"] = str(inputs["ui_config"])
        self.detail["even_report"] = copy.deepcopy(inputs["report_list"])
        return {
            "ok": True,
            "status": "success",
            "operation_id": operation_id,
            "attempts": 1,
            "result_audit": {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "fact_paths": {},
                "http_receipts": [
                    {"receipt_id": WRITE_RECEIPT, "storage_status": "stored"}
                ],
            },
        }


def _workspace(root: Path) -> SimpleNamespace:
    return SimpleNamespace(
        root=root,
        state_root=root / "state" / "principals" / SCOPE,
        path=root / "gravity.toml",
        apps={"demo": 101},
    )


def _sdk(root: Path) -> tuple[GravitySDK, DashboardInsight]:
    insight = DashboardInsight()
    return (
        GravitySDK(
            insight=insight,
            workspace=_workspace(root),
            _runtime_scope_bound=True,
        ),
        insight,
    )


def _request(artifact: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "artifact": artifact or compile_analysis_artifact(result_with_semantics()),
        "target": {"app_id": 101, "space_id": 10, "dashboard_id": 30},
        "presentation": {
            "visualization": "markdown_notes",
            "filter_mode": "artifact_scope",
            "layout": "single_column",
        },
    }


def _authorization(service: object, request: dict[str, object]) -> dict[str, object]:
    return host_source(
        "user", "authorization", service.authorization_value(request)
    )


def _confirmation(service: object, preview: dict[str, object]) -> dict[str, object]:
    return host_source(
        "user",
        "authorization",
        service.confirmation_value(
            preview["plan_id"], preview["preview_fingerprint"]
        ),
    )


def _preview(service: object, request: dict[str, object]) -> dict[str, object]:
    return service.preview_dashboard_delivery(
        request, authorization=_authorization(service, request)
    )


def _plan_path(sdk: GravitySDK) -> Path:
    plans = list((sdk.workspace.state_root / "action-plans").glob("*.json"))
    if len(plans) != 1:
        raise AssertionError(plans)
    return plans[0]


def _redigest(value: dict[str, object]) -> dict[str, object]:
    selected = copy.deepcopy(value)
    selected.pop("artifact_id", None)
    selected.pop("artifact_digest", None)
    digest = canonical_digest(selected)
    selected["artifact_id"] = f"sha256:{digest}"
    selected["artifact_digest"] = digest
    return selected


class DashboardActionHappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sdk, self.insight = _sdk(self.root)
        self.service = self.sdk.actions
        self.request = _request()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_preview_execute_readback_and_evidence_are_exact(self) -> None:
        preview = _preview(self.service, self.request)
        summary = preview["confirmation_summary"]
        self.assertEqual((ACTION_KIND, CONNECTOR_ID, 0), (
            preview["action_kind"], preview["connector"]["id"], self.insight.writes
        ))
        self.assertEqual(["dashboard_notes"], summary["managed_fields"])
        self.assertEqual(
            self.request["artifact"]["artifact_digest"],
            summary["expected_changes"][1]["value_summary"]["artifact_digest"],
        )
        self.assertEqual(["/request/artifact"], preview["policy"]["masked_paths"])
        self.assertNotIn("ui_config", repr(preview))
        self.assertNotIn("Returned rows changed.", repr(preview))

        private_text = _plan_path(self.sdk).read_text(encoding="utf-8")
        for value in (
            "What changed?",
            "Returned rows changed.",
            "private-owner",
            SOURCE_RECEIPT,
            SCOPE,
        ):
            self.assertNotIn(value, private_text)

        result = self.service.execute(
            preview["plan_id"],
            self.request,
            confirmation=_confirmation(self.service, preview),
        )
        self.assertEqual(("succeeded", 1, "verified"), (
            result["status"], self.insight.writes, result["readback"]["status"]
        ))
        self.assertEqual(
            self.request["artifact"]["artifact_digest"],
            result["target"]["source_binding"]["artifact_digest"],
        )
        self.assertEqual(
            {SOURCE_RECEIPT, WRITE_RECEIPT},
            {item["receipt_id"] for item in result["receipt_references"]},
        )
        self.assertEqual(
            result["target"]["note_count"],
            len(json.loads(self.insight.detail["ui_config"])),
        )
        self.assertNotIn("ui_config", self.request)
        self.assertNotIn("Returned rows changed.", repr(result))
        with self.assertRaises(InputValidationError) as replay:
            self.service.execute(
                preview["plan_id"],
                self.request,
                confirmation=_confirmation(self.service, preview),
            )
        self.assertEqual("ACTION_PLAN_CONSUMED", replay.exception.code)

    def test_public_private_and_execution_schemas_bind_the_dashboard_profile(self) -> None:
        preview = _preview(self.service, self.request)
        private = json.loads(_plan_path(self.sdk).read_text(encoding="utf-8"))
        result = self.service.execute(
            preview["plan_id"], self.request,
            confirmation=_confirmation(self.service, preview),
        )
        for schema_name, value in (
            ("analysis-dashboard-request-v1.schema.json", self.request),
            ("action-plan-v1.schema.json", preview),
            ("action-plan-private-v1.schema.json", private),
            ("action-execution-v1.schema.json", result),
        ):
            validate_schema(value, schema_name, schema_name)

        crossed = copy.deepcopy(private)
        crossed["connector_id"] = "gravity.segment-metadata-update"
        with self.assertRaises(AgentRuntimeContractError):
            validate_schema(
                crossed, "action-plan-private-v1.schema.json", "crossed plan"
            )

    def test_cli_requires_the_same_explicit_confirmation(self) -> None:
        from gravity_sdk import cli

        encoded = json.dumps(self.request)
        with mock.patch("gravity_sdk.sdk.GravitySDK.from_env", return_value=self.sdk):
            parsed = cli.build_parser().parse_args(
                ["action", "dashboard-delivery", "preview", "--input", encoded]
            )
            preview = parsed._gravity_handler(parsed, object_input)
            execute = cli.build_parser().parse_args(
                [
                    "action", "dashboard-delivery", "execute",
                    "--plan-id", preview["plan_id"],
                    "--confirm-plan", preview["plan_id"],
                    "--preview-fingerprint", preview["preview_fingerprint"],
                    "--input", encoded,
                ]
            )
            result = execute._gravity_handler(execute, object_input)
        self.assertEqual("succeeded", result["status"])


class DashboardActionGapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def assert_gap(self, request: dict[str, object], code: str) -> None:
        sdk, insight = _sdk(self.root / code)
        with self.assertRaises(InputValidationError) as raised:
            _preview(sdk.actions, request)
        self.assertEqual(code, raised.exception.code)
        self.assertEqual((0, 0), (insight.reads, insight.writes))
        self.assertFalse((sdk.workspace.state_root / "action-plans").exists())

    def test_closed_presentation_tuple_has_distinct_stable_gaps(self) -> None:
        cases = (
            ("visualization", "chart", "DASHBOARD_VISUALIZATION_UNSUPPORTED"),
            ("filter_mode", "target_filter", "DASHBOARD_FILTER_MODE_UNSUPPORTED"),
            ("layout", "grid", "DASHBOARD_LAYOUT_UNSUPPORTED"),
        )
        for field, value, code in cases:
            with self.subTest(field=field):
                request = _request()
                request["presentation"][field] = value
                self.assert_gap(request, code)

    def test_status_semantic_source_date_and_content_gaps_are_fail_closed(self) -> None:
        tampered = _request()
        tampered["artifact"]["title"] = "changed without digest"
        self.assert_gap(tampered, "DASHBOARD_ARTIFACT_INVALID")

        blocked = compile_analysis_artifact(blocked_result())
        self.assert_gap(_request(blocked), "DASHBOARD_ARTIFACT_UNDELIVERABLE")

        unresolved = copy.deepcopy(_request()["artifact"])
        unresolved["semantic_references"][0]["status"] = "missing"
        self.assert_gap(
            _request(_redigest(unresolved)),
            "DASHBOARD_SEMANTIC_BINDING_UNRESOLVED",
        )

        source = _request()
        source["artifact"]["scope"]["app"] = "unknown"
        source["artifact"]["filters"]["values"]["app"] = "unknown"
        self.assert_gap(
            _request(_redigest(source["artifact"])),
            "DASHBOARD_SOURCE_BINDING_UNRESOLVED",
        )

        dates = _request()
        dates["artifact"]["scope"]["start"] = "2026-09-02"
        dates["artifact"]["scope"]["end"] = "2026-09-01"
        dates["artifact"]["filters"]["values"] = copy.deepcopy(
            dates["artifact"]["scope"]
        )
        self.assert_gap(
            _request(_redigest(dates["artifact"])),
            "DASHBOARD_DATE_FILTER_INVALID",
        )

        large = _request()
        large["artifact"]["findings"][0]["statement"] = "x" * 5_000
        self.assert_gap(
            _request(_redigest(large["artifact"])),
            "DASHBOARD_CONTENT_UNREPRESENTABLE",
        )

    def test_raw_target_config_is_rejected_by_the_request_schema(self) -> None:
        request = _request()
        request["target"]["ui_config"] = []
        self.assert_gap(request, "ACTION_REQUEST_INVALID")

    def test_report_dashboard_and_foreign_owner_stop_before_plan_allocation(self) -> None:
        sdk, insight = _sdk(self.root / "reports")
        insight.detail["even_report"] = [{"report_id": "7"}]
        with self.assertRaises(InputValidationError) as reports:
            _preview(sdk.actions, _request())
        self.assertEqual("DASHBOARD_TARGET_UNSUPPORTED", reports.exception.code)
        self.assertEqual(0, insight.writes)
        self.assertFalse((sdk.workspace.state_root / "action-plans").exists())

        foreign, foreign_insight = _sdk(self.root / "foreign")
        foreign_insight.detail["name"] = "Manual Dashboard"
        foreign_insight.detail["create_user_id"] = "92"
        with self.assertRaises(InputValidationError) as owner:
            _preview(foreign.actions, _request())
        self.assertEqual("OWNERSHIP_REQUIRED", owner.exception.code)
        self.assertEqual(0, foreign_insight.writes)
        self.assertFalse((foreign.workspace.state_root / "action-plans").exists())


class DashboardActionDriftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def fixture(self, name: str) -> tuple[GravitySDK, DashboardInsight, dict, dict]:
        sdk, insight = _sdk(self.root / name)
        request = _request()
        preview = _preview(sdk.actions, request)
        return sdk, insight, request, preview

    def test_preimage_change_is_stale_zero_write_and_consumes_the_plan(self) -> None:
        sdk, insight, request, preview = self.fixture("stale")
        insight.detail["ui_config"] = '[{"subject":"notes","i":"external"}]'
        result = sdk.actions.execute(
            preview["plan_id"], request,
            confirmation=_confirmation(sdk.actions, preview),
        )
        self.assertEqual(("stale", 0, ["ACTION_TARGET_CHANGED"]), (
            result["status"], insight.writes, result["reason_codes"]
        ))
        with self.assertRaises(InputValidationError) as replay:
            sdk.actions.execute(
                preview["plan_id"], request,
                confirmation=_confirmation(sdk.actions, preview),
            )
        self.assertEqual("ACTION_PLAN_CONSUMED", replay.exception.code)

    def test_post_write_readback_failure_is_uncertain_and_never_retried(self) -> None:
        sdk, insight, request, preview = self.fixture("uncertain")
        insight.readback_error = True
        result = sdk.actions.execute(
            preview["plan_id"], request,
            confirmation=_confirmation(sdk.actions, preview),
        )
        self.assertEqual(("uncertain", 1, False), (
            result["status"], insight.writes, result["automatic_retry"]
        ))
        self.assertEqual(["ACTION_EXECUTION_UNCERTAIN"], result["reason_codes"])

    def test_same_preimage_field_claim_allows_only_one_plan(self) -> None:
        sdk, insight = _sdk(self.root / "field-claim")
        request = _request()
        first = _preview(sdk.actions, request)
        second = _preview(sdk.actions, request)
        result = sdk.actions.execute(
            first["plan_id"], request,
            confirmation=_confirmation(sdk.actions, first),
        )
        self.assertEqual("succeeded", result["status"])
        with self.assertRaises(InputValidationError) as conflict:
            sdk.actions.execute(
                second["plan_id"], request,
                confirmation=_confirmation(sdk.actions, second),
            )
        self.assertEqual("ACTION_FIELD_OWNERSHIP_CONFLICT", conflict.exception.code)
        self.assertEqual(1, insight.writes)

    def test_private_connector_tamper_fails_before_mutation(self) -> None:
        sdk, insight, request, preview = self.fixture("tamper")
        path = _plan_path(sdk)
        value = json.loads(path.read_text(encoding="utf-8"))
        value["managed_fields"] = ["segment_name", "segment_remark"]
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(InputValidationError) as tampered:
            sdk.actions.execute(
                preview["plan_id"], request,
                confirmation=_confirmation(sdk.actions, preview),
            )
        self.assertEqual("ACTION_PLAN_TAMPERED", tampered.exception.code)
        self.assertEqual(0, insight.writes)


if __name__ == "__main__":
    unittest.main()
