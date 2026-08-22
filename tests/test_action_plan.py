"""R12-A authorization, preimage, claim, readback and privacy gates."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from gravity_sdk import ActionPlanService, GravitySDK, host_source
from gravity_sdk.action_plan import REQUEST_SCHEMA_VERSION
from gravity_sdk.action_segment_connector import ACTION_KIND
from gravity_sdk.errors import InputValidationError
from gravity_sdk.find_input import object_input
from gravity_sdk.result_audit import SCHEMA_VERSION as AUDIT_SCHEMA_VERSION
from gravity_sdk.segment_mutation_contracts import DETAIL_OPERATION, SAVE


SCOPE_A = "a" * 32
SCOPE_B = "b" * 32
PRINCIPAL = "91"
NOW = datetime(2026, 8, 22, 8, 0, 0, tzinfo=timezone.utc)
RECEIPT_ID = "c" * 32


class FixtureInsight:
    def __init__(self) -> None:
        self.principal = PRINCIPAL
        self.reads = 0
        self.writes = 0
        self.readback_error = False
        self.contract_revision = 1
        self.state = {
            "segment_id": "7",
            "app_id": "1",
            "segment_name": "Old Name",
            "segment_remark": "GSDK-aabbccddeeff | old-note-private",
            "operation_status": "ready",
            "modify_time": "2026-08-22T07:00:00Z",
            "create_user_id": PRINCIPAL,
            "create_user_name": "private-owner-name",
            "update_user_id": PRINCIPAL,
        }

    def _current_principal_id(self) -> str | None:
        return self.principal

    def describe(self, operation_id: str) -> dict[str, object]:
        if operation_id not in {DETAIL_OPERATION, SAVE}:
            raise AssertionError(operation_id)
        return {
            "operation_id": operation_id,
            "contract_version": self.contract_revision,
            "effect": "mutation" if operation_id == SAVE else "read",
            "stability": "stable",
        }

    def read(self, operation_id: str, inputs: dict[str, object]) -> dict[str, object]:
        if operation_id != DETAIL_OPERATION or str(inputs["segment_id"]) != "7":
            raise AssertionError((operation_id, inputs))
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
            "data": copy.deepcopy(self.state),
        }

    def _preview_mutation(
        self, operation_id: str, inputs: dict[str, object]
    ) -> dict[str, object]:
        if operation_id != SAVE:
            raise AssertionError(operation_id)
        return {
            "schema_version": "gravity-insight.mutation.v1",
            "ok": True,
            "status": "preview",
            "operation_id": operation_id,
            "network_called": False,
            "request": {"method": "POST", "path": "/registered/", "body": dict(inputs)},
        }

    def _execute_mutation(
        self, operation_id: str, inputs: dict[str, object]
    ) -> dict[str, object]:
        if operation_id != SAVE:
            raise AssertionError(operation_id)
        self.writes += 1
        self.state["segment_name"] = str(inputs["segment_name"])
        self.state["segment_remark"] = str(inputs["segment_remark"])
        self.state["modify_time"] = "2026-08-22T08:00:01Z"
        return {
            "operation_id": operation_id,
            "attempts": 1,
            "result_audit": {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "fact_paths": {},
                "http_receipts": [
                    {"receipt_id": RECEIPT_ID, "storage_status": "stored"}
                ],
            },
        }


def _workspace(root: Path, scope: str = SCOPE_A) -> SimpleNamespace:
    return SimpleNamespace(
        root=root,
        state_root=root / "state" / "principals" / scope,
        path=root / "gravity.toml",
    )


def _sdk(root: Path, scope: str = SCOPE_A) -> tuple[GravitySDK, FixtureInsight]:
    insight = FixtureInsight()
    sdk = GravitySDK(
        insight=insight,
        workspace=_workspace(root, scope),
        _runtime_scope_bound=True,
    )
    return sdk, insight


def _request(
    *, name: str = "New Name", remark: str = "new-note-private"
) -> dict[str, object]:
    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "segment_id": "7",
        "name": name,
        "remark": remark,
    }


def _authorization(service: ActionPlanService, request: dict[str, object]) -> dict[str, object]:
    return host_source(
        "user", "authorization", service.authorization_value(request)
    )


def _confirmation(
    service: ActionPlanService, preview: dict[str, object]
) -> dict[str, object]:
    return host_source(
        "user",
        "authorization",
        service.confirmation_value(
            str(preview["plan_id"]), str(preview["preview_fingerprint"])
        ),
    )


def _artifact(workspace: object) -> Path:
    paths = list((workspace.state_root / "action-plans").glob("*.json"))
    if len(paths) != 1:
        raise AssertionError(f"expected one Action Plan, found {len(paths)}")
    return paths[0]


class ActionPlanHappyPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.sdk, self.insight = _sdk(self.root)
        self.service = self.sdk.actions
        self.request = _request()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def preview(self) -> dict[str, object]:
        with mock.patch("gravity_sdk.action_plan._utcnow", return_value=NOW):
            return self.service.preview_segment_update(
                self.request,
                authorization=_authorization(self.service, self.request),
            )

    def test_preview_reads_exact_preimage_without_mutation_and_persists_no_values(self) -> None:
        preview = self.preview()
        self.assertEqual((1, 0), (self.insight.reads, self.insight.writes))
        self.assertEqual(
            ("gravity.action-plan.v1", "previewed", "require_confirmation"),
            (
                preview["schema_version"],
                preview["status"],
                preview["policy"]["decision"],
            ),
        )
        self.assertEqual(
            ["segment_name", "segment_remark"],
            preview["confirmation_summary"]["managed_fields"],
        )
        self.assertIn(
            "upstream_revision_unavailable",
            preview["confirmation_summary"]["limitations"],
        )
        self.assertNotIn("new-note-private", repr(preview))
        rendered = _artifact(self.sdk.workspace).read_text(encoding="utf-8")
        for private in (
            "New Name",
            "new-note-private",
            "Old Name",
            "old-note-private",
            "private-owner-name",
            f'"{PRINCIPAL}"',
            SCOPE_A,
        ):
            self.assertNotIn(private, rendered)

    def test_exact_confirmation_executes_existing_owner_once_and_cannot_replay(self) -> None:
        preview = self.preview()
        with mock.patch("gravity_sdk.action_plan._utcnow", return_value=NOW):
            result = self.service.execute(
                preview["plan_id"],
                self.request,
                confirmation=_confirmation(self.service, preview),
            )
        self.assertEqual(("succeeded", 1), (result["status"], self.insight.writes))
        self.assertEqual("verified", result["readback"]["status"])
        self.assertEqual(RECEIPT_ID, result["receipt_references"][0]["receipt_id"])
        self.assertFalse(result["automatic_retry"])
        self.assertEqual("allow", result["policy"]["decision"])
        with mock.patch("gravity_sdk.action_plan._utcnow", return_value=NOW):
            with self.assertRaises(InputValidationError) as replay:
                self.service.execute(
                    preview["plan_id"],
                    self.request,
                    confirmation=_confirmation(self.service, preview),
                )
        self.assertEqual("ACTION_PLAN_CONSUMED", replay.exception.code)
        self.assertEqual(1, self.insight.writes)

    def test_direct_segment_surface_remains_unchanged_without_action_plan(self) -> None:
        direct, client = _sdk(self.root / "direct", SCOPE_B)
        dry = direct.segment_update("7", name="New Name", remark="new", execute=False)
        self.assertEqual(("preview", 0, 0), (dry["status"], client.reads, client.writes))
        done = direct.segment_update("7", name="New Name", remark="new", execute=True)
        self.assertEqual(("updated", 2, 1), (done["status"], client.reads, client.writes))

    def test_new_plan_from_verified_new_preimage_can_update_again(self) -> None:
        with mock.patch("gravity_sdk.action_plan._utcnow", return_value=NOW):
            first = self.preview()
            self.service.execute(
                first["plan_id"],
                self.request,
                confirmation=_confirmation(self.service, first),
            )
            second_request = _request(name="Next Name", remark="next-note")
            second = self.service.preview_segment_update(
                second_request,
                authorization=_authorization(self.service, second_request),
            )
            result = self.service.execute(
                second["plan_id"],
                second_request,
                confirmation=_confirmation(self.service, second),
            )
        self.assertEqual(("succeeded", 2), (result["status"], self.insight.writes))


class ActionPlanAuthorityAndDriftTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def fixture(self, name: str = "case") -> tuple[GravitySDK, FixtureInsight, dict[str, object], dict[str, object]]:
        sdk, insight = _sdk(self.root / name)
        request = _request()
        service = sdk.actions
        preview = service.preview_segment_update(
            request, authorization=_authorization(service, request)
        )
        return sdk, insight, request, preview

    def test_tool_or_instruction_sources_cannot_authorize_preview_or_execute(self) -> None:
        sdk, insight = _sdk(self.root / "authority")
        request = _request()
        service = sdk.actions
        for origin, role in (("tool_result", "data"), ("user", "instruction")):
            with self.subTest(origin=origin, role=role), self.assertRaises(InputValidationError) as raised:
                service.preview_segment_update(
                    request,
                    authorization=host_source(
                        origin, role, service.authorization_value(request)
                    ),
                )
            self.assertEqual("ACTION_AUTHORIZATION_REQUIRED", raised.exception.code)
        self.assertEqual((0, 0), (insight.reads, insight.writes))

        preview = service.preview_segment_update(
            request, authorization=_authorization(service, request)
        )
        bad = host_source(
            "tool_result",
            "data",
            service.confirmation_value(
                preview["plan_id"], preview["preview_fingerprint"]
            ),
        )
        with self.assertRaises(InputValidationError) as confirmation:
            service.execute(preview["plan_id"], request, confirmation=bad)
        self.assertEqual("ACTION_CONFIRMATION_REQUIRED", confirmation.exception.code)
        self.assertEqual(0, insight.writes)

    def test_foreign_unmarked_owner_and_invalid_ttl_block_before_artifact(self) -> None:
        sdk, insight = _sdk(self.root / "foreign")
        insight.state["segment_remark"] = "manual"
        insight.state["create_user_id"] = "92"
        request = _request()
        with self.assertRaises(InputValidationError) as owner:
            sdk.actions.preview_segment_update(
                request, authorization=_authorization(sdk.actions, request)
            )
        self.assertEqual("OWNERSHIP_REQUIRED", owner.exception.code)
        self.assertEqual((1, 0), (insight.reads, insight.writes))
        self.assertFalse((sdk.workspace.state_root / "action-plans").exists())

        with self.assertRaises(InputValidationError) as ttl:
            sdk.actions.preview_segment_update(
                request,
                authorization=_authorization(sdk.actions, request),
                ttl_seconds=0,
            )
        self.assertEqual("ACTION_TTL_INVALID", ttl.exception.code)
        self.assertEqual(1, insight.reads)

    def test_input_principal_contract_and_reference_drift_fail_before_claim(self) -> None:
        cases = ("input", "principal", "contract")
        for case in cases:
            with self.subTest(case=case):
                sdk, insight, request, preview = self.fixture(case)
                supplied = copy.deepcopy(request)
                if case == "input":
                    supplied["name"] = "Changed"
                elif case == "principal":
                    insight.principal = "92"
                else:
                    insight.contract_revision = 2
                with self.assertRaises(InputValidationError) as raised:
                    sdk.actions.execute(
                        preview["plan_id"],
                        supplied,
                        confirmation=_confirmation(sdk.actions, preview),
                    )
                self.assertEqual(
                    {
                        "input": "ACTION_INPUT_CHANGED",
                        "principal": "ACTION_IDENTITY_CHANGED",
                        "contract": "ACTION_CONTRACT_CHANGED",
                    }[case],
                    raised.exception.code,
                )
                self.assertEqual(0, insight.writes)

    def test_preimage_or_owner_change_is_stale_under_owner_lock_and_consumes_plan(self) -> None:
        for field, value in (
            ("segment_remark", "GSDK-aabbccddeeff | changed"),
            ("create_user_id", "92"),
        ):
            with self.subTest(field=field):
                sdk, insight, request, preview = self.fixture(f"stale-{field}")
                insight.state[field] = value
                result = sdk.actions.execute(
                    preview["plan_id"],
                    request,
                    confirmation=_confirmation(sdk.actions, preview),
                )
                self.assertEqual("stale", result["status"])
                self.assertEqual(["ACTION_TARGET_CHANGED"], result["reason_codes"])
                self.assertEqual(0, insight.writes)
                with self.assertRaises(InputValidationError) as replay:
                    sdk.actions.execute(
                        preview["plan_id"],
                        request,
                        confirmation=_confirmation(sdk.actions, preview),
                    )
                self.assertEqual("ACTION_PLAN_CONSUMED", replay.exception.code)

    def test_unmarked_upstream_owner_change_has_a_distinct_stale_reason(self) -> None:
        sdk, insight = _sdk(self.root / "owner")
        insight.state["segment_remark"] = "manual"
        request = _request(remark="new manual note")
        preview = sdk.actions.preview_segment_update(
            request, authorization=_authorization(sdk.actions, request)
        )
        self.assertEqual(
            "upstream_owner", preview["confirmation_summary"]["ownership_basis"]
        )
        insight.state["create_user_id"] = "92"
        result = sdk.actions.execute(
            preview["plan_id"],
            request,
            confirmation=_confirmation(sdk.actions, preview),
        )
        self.assertEqual(("stale", 0), (result["status"], insight.writes))
        self.assertEqual(["ACTION_OWNER_CHANGED"], result["reason_codes"])

    def test_confirmation_must_bind_the_exact_preview_fingerprint(self) -> None:
        sdk, insight, request, preview = self.fixture("confirmation")
        wrong = host_source(
            "user",
            "authorization",
            sdk.actions.confirmation_value(preview["plan_id"], "0" * 64),
        )
        with self.assertRaises(InputValidationError) as raised:
            sdk.actions.execute(preview["plan_id"], request, confirmation=wrong)
        self.assertEqual("ACTION_CONFIRMATION_REQUIRED", raised.exception.code)
        self.assertEqual(0, insight.writes)
        success = sdk.actions.execute(
            preview["plan_id"],
            request,
            confirmation=_confirmation(sdk.actions, preview),
        )
        self.assertEqual("succeeded", success["status"])

    def test_post_write_readback_failure_is_uncertain_and_not_retryable(self) -> None:
        sdk, insight, request, preview = self.fixture("uncertain")
        insight.readback_error = True
        result = sdk.actions.execute(
            preview["plan_id"],
            request,
            confirmation=_confirmation(sdk.actions, preview),
        )
        self.assertEqual(("uncertain", 1), (result["status"], insight.writes))
        self.assertEqual(["ACTION_EXECUTION_UNCERTAIN"], result["reason_codes"])
        self.assertFalse(result["automatic_retry"])
        with self.assertRaises(InputValidationError) as replay:
            sdk.actions.execute(
                preview["plan_id"],
                request,
                confirmation=_confirmation(sdk.actions, preview),
            )
        self.assertEqual("ACTION_PLAN_CONSUMED", replay.exception.code)

    def test_atomic_claim_allows_only_one_concurrent_execute(self) -> None:
        sdk, insight, request, preview = self.fixture("concurrent")
        confirmation = _confirmation(sdk.actions, preview)

        def execute() -> object:
            try:
                return sdk.actions.execute(
                    preview["plan_id"], request, confirmation=confirmation
                )
            except InputValidationError as error:
                return error

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _index: execute(), range(2)))
        results = [item for item in outcomes if isinstance(item, dict)]
        errors = [item for item in outcomes if isinstance(item, InputValidationError)]
        self.assertEqual((1, 1, 1), (len(results), len(errors), insight.writes))
        self.assertEqual("succeeded", results[0]["status"])
        self.assertEqual("ACTION_PLAN_CONSUMED", errors[0].code)

    def test_field_claim_rejects_two_plans_from_the_same_preimage(self) -> None:
        sdk, insight = _sdk(self.root / "field-claim")
        request = _request()
        first = sdk.actions.preview_segment_update(
            request, authorization=_authorization(sdk.actions, request)
        )
        second = sdk.actions.preview_segment_update(
            request, authorization=_authorization(sdk.actions, request)
        )
        succeeded = sdk.actions.execute(
            first["plan_id"], request, confirmation=_confirmation(sdk.actions, first)
        )
        self.assertEqual("succeeded", succeeded["status"])
        with self.assertRaises(InputValidationError) as conflict:
            sdk.actions.execute(
                second["plan_id"],
                request,
                confirmation=_confirmation(sdk.actions, second),
            )
        self.assertEqual("ACTION_FIELD_OWNERSHIP_CONFLICT", conflict.exception.code)
        self.assertEqual(1, insight.writes)

    def test_expiry_identity_and_artifact_tamper_fail_before_mutation(self) -> None:
        sdk, insight, request, preview = self.fixture("expiry")
        with mock.patch(
            "gravity_sdk.action_plan._utcnow", return_value=NOW + timedelta(days=1)
        ), self.assertRaises(InputValidationError) as expired:
            sdk.actions.execute(
                preview["plan_id"],
                request,
                confirmation=_confirmation(sdk.actions, preview),
            )
        self.assertEqual("ACTION_PLAN_EXPIRED", expired.exception.code)
        self.assertEqual(0, insight.writes)

        other, other_insight = _sdk(self.root / "other", SCOPE_B)
        with self.assertRaises(InputValidationError) as identity:
            other.actions.execute(
                preview["plan_id"],
                request,
                confirmation=_confirmation(other.actions, preview),
            )
        self.assertEqual("ACTION_IDENTITY_CHANGED", identity.exception.code)
        self.assertEqual(0, other_insight.writes)

        path = _artifact(sdk.workspace)
        value = json.loads(path.read_text(encoding="utf-8"))
        value["preimage_digest"] = "0" * 64
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(InputValidationError) as tampered:
            sdk.actions.execute(
                preview["plan_id"],
                request,
                confirmation=_confirmation(sdk.actions, preview),
            )
        self.assertEqual("ACTION_PLAN_TAMPERED", tampered.exception.code)

    def test_hardlink_and_store_count_bound_fail_closed(self) -> None:
        sdk, insight, request, preview = self.fixture("hardlink")
        path = _artifact(sdk.workspace)
        link = path.with_suffix(".link")
        os.link(path, link)
        try:
            with self.assertRaises(InputValidationError) as linked:
                sdk.actions.execute(
                    preview["plan_id"],
                    request,
                    confirmation=_confirmation(sdk.actions, preview),
                )
            self.assertEqual("ACTION_PLAN_TAMPERED", linked.exception.code)
            self.assertEqual(0, insight.writes)
        finally:
            link.unlink(missing_ok=True)

        bounded, bounded_insight = _sdk(self.root / "bounded")
        with mock.patch("gravity_sdk.action_plan_store.MAX_STORED_PLANS", 1):
            bounded.actions.preview_segment_update(
                request, authorization=_authorization(bounded.actions, request)
            )
            with self.assertRaises(InputValidationError) as full:
                bounded.actions.preview_segment_update(
                    request, authorization=_authorization(bounded.actions, request)
                )
        self.assertEqual("ACTION_STORE_BOUND_EXCEEDED", full.exception.code)
        self.assertEqual(0, bounded_insight.writes)


class ActionPlanSurfaceTests(unittest.TestCase):
    def test_unscoped_sdk_cannot_construct_action_service(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            sdk = GravitySDK(
                insight=FixtureInsight(), workspace=_workspace(Path(raw)),
            )
            with self.assertRaises(InputValidationError) as raised:
                _ = sdk.actions
        self.assertEqual("ACTION_SCOPE_UNBOUND", raised.exception.code)

    def test_cli_requires_explicit_matching_confirmation_and_uses_service(self) -> None:
        from gravity_sdk import cli

        with tempfile.TemporaryDirectory() as raw:
            sdk, _insight = _sdk(Path(raw))
            request = _request()
            encoded = json.dumps(request)
            with mock.patch("gravity_sdk.sdk.GravitySDK.from_env", return_value=sdk):
                parsed = cli.build_parser().parse_args(
                    ["action", "segment-update", "preview", "--input", encoded]
                )
                preview = parsed._gravity_handler(parsed, object_input)
                execute = cli.build_parser().parse_args(
                    [
                        "action",
                        "segment-update",
                        "execute",
                        "--plan-id",
                        preview["plan_id"],
                        "--confirm-plan",
                        preview["plan_id"],
                        "--preview-fingerprint",
                        preview["preview_fingerprint"],
                        "--input",
                        encoded,
                    ]
                )
                result = execute._gravity_handler(execute, object_input)
        self.assertEqual("succeeded", result["status"])

    def test_schema_required_fields_match_public_private_and_execution_values(self) -> None:
        root = Path(__file__).resolve().parents[1]
        schema_root = root / "src/gravity_sdk/contracts/schema"
        with tempfile.TemporaryDirectory() as raw:
            sdk, _insight = _sdk(Path(raw))
            request = _request()
            preview = sdk.actions.preview_segment_update(
                request, authorization=_authorization(sdk.actions, request)
            )
            private = json.loads(_artifact(sdk.workspace).read_text(encoding="utf-8"))
            result = sdk.actions.execute(
                preview["plan_id"], request, confirmation=_confirmation(sdk.actions, preview)
            )
        for name, value in (
            ("action-plan-v1.schema.json", preview),
            ("action-plan-private-v1.schema.json", private),
            ("action-execution-v1.schema.json", result),
        ):
            schema = json.loads((schema_root / name).read_text(encoding="utf-8"))
            self.assertEqual(set(schema["required"]), set(value))
        self.assertEqual(ACTION_KIND, preview["action_kind"])


if __name__ == "__main__":
    unittest.main()
