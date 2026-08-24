"""One Action Plan owner with an explicit closed connector set."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import action_dashboard_connector as dashboard_connector
from . import action_segment_connector as segment_connector
from .action_connector_support import attempted_receipts
from .action_plan_store import ActionPlanStore, bound_scope_key, timestamp
from .errors import InputValidationError
from .host_effect_sources import SOURCE_SCHEMA_VERSION
from .mutation_lifecycle import mutation_digest


PUBLIC_SCHEMA_VERSION = "gravity.action-plan.v1"
EXECUTION_SCHEMA_VERSION = "gravity.action-execution.v1"
AUTHORIZATION_SCHEMA_VERSION = "gravity.action-authorization.v1"
CONFIRMATION_SCHEMA_VERSION = "gravity.action-confirmation.v1"
POLICY_SCHEMA_VERSION = "gravity.policy-decision.v1"
DEFAULT_TTL_SECONDS = 900
MAX_TTL_SECONDS = 3_600
REQUEST_SCHEMA_VERSION = segment_connector.REQUEST_SCHEMA_VERSION
DASHBOARD_REQUEST_SCHEMA_VERSION = dashboard_connector.REQUEST_SCHEMA_VERSION

_SOURCE_FIELDS = frozenset({"schema_version", "origin", "role", "value"})
_SEGMENT_MASKED_PATHS = ("/request/remark",)


class ActionPlanService:
    """Prepare and consume one exact plan through two closed connectors."""

    def __init__(self, sdk: Any) -> None:
        workspace = sdk.workspace
        self._sdk = sdk
        self._workspace = workspace
        self._scope_key = bound_scope_key(
            workspace, bool(getattr(sdk, "_runtime_scope_bound", False))
        )
        self._store = ActionPlanStore(
            Path(workspace.state_root) / "action-plans", self._scope_key
        )

    def __repr__(self) -> str:
        return "<ActionPlanService private>"

    def authorization_value(self, request: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": AUTHORIZATION_SCHEMA_VERSION,
            "action_kind": _request_action_kind(request),
            "request": copy.deepcopy(dict(request)),
        }

    def confirmation_value(
        self, plan_id: str, preview_fingerprint: str
    ) -> dict[str, Any]:
        return {
            "schema_version": CONFIRMATION_SCHEMA_VERSION,
            "plan_id": plan_id,
            "preview_fingerprint": preview_fingerprint,
            "confirmed": True,
        }

    def preview_segment_update(
        self,
        request: Mapping[str, Any],
        *,
        authorization: Mapping[str, Any],
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> dict[str, Any]:
        """Read current preimage/owner and create an immutable confirmation plan."""

        _bounded_ttl(ttl_seconds)
        expected_authorization = self.authorization_value(request)
        _require_user_source(
            authorization,
            expected_authorization,
            code="ACTION_AUTHORIZATION_REQUIRED",
            field="authorization",
        )
        prepared = segment_connector.prepare_segment_update(self._sdk.insight, request)
        plan_id, artifact = self._create_plan(
            request,
            expected_authorization,
            prepared,
            action_kind=segment_connector.ACTION_KIND,
            connector_id=segment_connector.CONNECTOR_ID,
            connector_version=segment_connector.CONNECTOR_VERSION,
            managed_fields=segment_connector.MANAGED_FIELDS,
            ttl_seconds=ttl_seconds,
        )
        return _public_plan(
            plan_id,
            artifact,
            action_kind=segment_connector.ACTION_KIND,
            connector_id=segment_connector.CONNECTOR_ID,
            connector_version=segment_connector.CONNECTOR_VERSION,
            summary=_segment_summary(
                prepared["normalized"], str(prepared["ownership_basis"])
            ),
            masked_paths=_SEGMENT_MASKED_PATHS,
        )

    def preview_dashboard_delivery(
        self,
        request: Mapping[str, Any],
        *,
        authorization: Mapping[str, Any],
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> dict[str, Any]:
        """Compile one Artifact target and create its immutable plan."""

        _bounded_ttl(ttl_seconds)
        expected_authorization = self.authorization_value(request)
        _require_user_source(
            authorization,
            expected_authorization,
            code="ACTION_AUTHORIZATION_REQUIRED",
            field="authorization",
        )
        prepared = dashboard_connector.prepare_dashboard_delivery(
            self._sdk.insight, self._workspace, request
        )
        plan_id, artifact = self._create_plan(
            request,
            expected_authorization,
            prepared,
            action_kind=dashboard_connector.ACTION_KIND,
            connector_id=dashboard_connector.CONNECTOR_ID,
            connector_version=dashboard_connector.CONNECTOR_VERSION,
            managed_fields=dashboard_connector.MANAGED_FIELDS,
            ttl_seconds=ttl_seconds,
        )
        return _public_plan(
            plan_id,
            artifact,
            action_kind=dashboard_connector.ACTION_KIND,
            connector_id=dashboard_connector.CONNECTOR_ID,
            connector_version=dashboard_connector.CONNECTOR_VERSION,
            summary=dashboard_connector.confirmation_summary(
                prepared["normalized"], str(prepared["ownership_basis"])
            ),
            masked_paths=dashboard_connector.MASKED_PATHS,
        )

    def _create_plan(
        self,
        request: Mapping[str, Any],
        authorization: Mapping[str, Any],
        prepared: Mapping[str, Any],
        *,
        action_kind: str,
        connector_id: str,
        connector_version: int,
        managed_fields: tuple[str, ...],
        ttl_seconds: int,
    ) -> tuple[str, dict[str, Any]]:
        now = _utcnow()
        nonce, plan_id = self._store.allocate()
        values = {
            "action_kind": action_kind,
            "connector_id": connector_id,
            "connector_version": connector_version,
            "created_at": timestamp(now),
            "expires_at": timestamp(now + timedelta(seconds=ttl_seconds)),
            "request_digest": mutation_digest(dict(request)),
            "authorization_digest": mutation_digest(dict(authorization)),
            "principal_digest": prepared["principal_digest"],
            "target_digest": prepared["target_digest"],
            "preimage_digest": prepared["preimage_digest"],
            "ownership_digest": prepared["ownership_digest"],
            "contract_fingerprint": prepared["contract_fingerprint"],
            "managed_fields": list(managed_fields),
        }
        values["preview_fingerprint"] = mutation_digest({"nonce": nonce, **values})
        return plan_id, self._store.create(nonce, values, now=now)

    def execute(
        self,
        plan_id: str,
        request: Mapping[str, Any],
        *,
        confirmation: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Claim once, delegate to the bound owner, and classify readback."""

        now = _utcnow()
        artifact = self._store.load(plan_id, now=now)
        action_kind = artifact["action_kind"]
        if _request_action_kind(request) != action_kind:
            _fail("ACTION_INPUT_CHANGED")
        if action_kind == segment_connector.ACTION_KIND:
            current = segment_connector.current_execution_binding(
                self._sdk.insight, request
            )
            connector_id = segment_connector.CONNECTOR_ID
            connector_version = segment_connector.CONNECTOR_VERSION
            verifier = segment_connector.verified_readback
            masked_paths = _SEGMENT_MASKED_PATHS
        elif action_kind == dashboard_connector.ACTION_KIND:
            current = dashboard_connector.current_execution_binding(
                self._sdk.insight, self._workspace, request
            )
            connector_id = dashboard_connector.CONNECTOR_ID
            connector_version = dashboard_connector.CONNECTOR_VERSION
            verifier = dashboard_connector.verified_readback
            masked_paths = dashboard_connector.MASKED_PATHS
        else:
            _fail("ACTION_PLAN_TAMPERED")
        _compare_current(artifact, request, current)
        _require_user_source(
            confirmation,
            self.confirmation_value(plan_id, artifact["preview_fingerprint"]),
            code="ACTION_CONFIRMATION_REQUIRED",
            field="confirmation",
        )
        self._store.claim(plan_id, artifact, now=now)
        if action_kind == segment_connector.ACTION_KIND:
            attempted = segment_connector.execute_segment_update(
                self._sdk.insight,
                current["normalized"],
                expected_preimage_digest=artifact["preimage_digest"],
            )
        else:
            attempted = dashboard_connector.execute_dashboard_delivery(
                self._sdk.insight,
                current["normalized"],
                expected_preimage_digest=artifact["preimage_digest"],
            )
        return _execution_result(
            plan_id,
            attempted,
            current["normalized"],
            action_kind=action_kind,
            connector_id=connector_id,
            connector_version=connector_version,
            verifier=verifier,
            masked_paths=masked_paths,
        )


def _public_plan(
    plan_id: str,
    artifact: Mapping[str, Any],
    *,
    action_kind: str,
    connector_id: str,
    connector_version: int,
    summary: Mapping[str, Any],
    masked_paths: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "ok": True,
        "status": "previewed",
        "plan_id": plan_id,
        "action_kind": action_kind,
        "connector": {"id": connector_id, "version": connector_version},
        "confirmation_summary": copy.deepcopy(dict(summary)),
        "preview_fingerprint": artifact["preview_fingerprint"],
        "created_at": artifact["created_at"],
        "expires_at": artifact["expires_at"],
        "policy": _policy(
            plan_id,
            "preview",
            "require_confirmation",
            ["USER_CONFIRMATION_REQUIRED"],
            masked_paths=masked_paths,
        ),
    }


def _segment_summary(
    normalized: Mapping[str, Any], ownership_basis: str
) -> dict[str, Any]:
    return {
        "target": {
            "kind": "segment",
            "segment_id": normalized["segment_id"],
        },
        "expected_changes": [
            {"field": "segment_name", "value": normalized["name"]},
            {
                "field": "segment_remark",
                "value_summary": {"length": len(normalized["remark"])},
            },
        ],
        "managed_fields": list(segment_connector.MANAGED_FIELDS),
        "ownership_basis": ownership_basis,
        "readback_assertions": [
            "segment_name",
            "segment_remark",
            "field_ownership",
        ],
        "limitations": [
            "upstream_revision_unavailable",
            "external_change_after_last_preimage_read_is_detectable_only_by_readback",
        ],
    }


def _execution_result(
    plan_id: str,
    attempted: Mapping[str, Any],
    normalized: Mapping[str, Any],
    *,
    action_kind: str,
    connector_id: str,
    connector_version: int,
    verifier: Any,
    masked_paths: tuple[str, ...],
) -> dict[str, Any]:
    writes = int(attempted.get("write_attempts", 0))
    error = attempted.get("error")
    result = attempted.get("result")
    if error is not None:
        code = getattr(error, "code", None)
        stale = writes == 0
        reason = (
            str(code)
            if code == "ACTION_TARGET_CHANGED"
            else "ACTION_OWNER_CHANGED"
            if code == "OWNERSHIP_REQUIRED"
            else "ACTION_PRECONDITION_FAILED"
            if stale
            else "ACTION_EXECUTION_UNCERTAIN"
        )
        return _failed_execution(
            plan_id,
            writes,
            "stale" if stale else "uncertain",
            reason,
            action_kind=action_kind,
            connector_id=connector_id,
            connector_version=connector_version,
            masked_paths=masked_paths,
            receipts=attempted_receipts(attempted),
        )
    readback = verifier(result, normalized)
    if writes != 1 or readback is None:
        return _failed_execution(
            plan_id,
            writes,
            "uncertain",
            "ACTION_FIELD_OWNERSHIP_CONFLICT",
            action_kind=action_kind,
            connector_id=connector_id,
            connector_version=connector_version,
            masked_paths=masked_paths,
            receipts=attempted_receipts(attempted),
        )
    return {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "ok": True,
        "status": "succeeded",
        "plan_id": plan_id,
        "action_kind": action_kind,
        "connector": {"id": connector_id, "version": connector_version},
        "write_attempted": True,
        "write_attempts": 1,
        "automatic_retry": False,
        "target": readback["target"],
        "readback": {
            "status": "verified",
            "assertions": readback["assertions"],
        },
        "receipt_references": readback["receipt_references"],
        "reason_codes": [],
        "policy": _policy(
            plan_id,
            "execute",
            "allow",
            ["USER_CONFIRMATION_BOUND"],
            masked_paths=masked_paths,
        ),
    }


def _failed_execution(
    plan_id: str,
    writes: int,
    status: str,
    reason: str,
    *,
    action_kind: str,
    connector_id: str,
    connector_version: int,
    masked_paths: tuple[str, ...],
    receipts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "ok": False,
        "status": status,
        "plan_id": plan_id,
        "action_kind": action_kind,
        "connector": {"id": connector_id, "version": connector_version},
        "write_attempted": writes > 0,
        "write_attempts": writes,
        "automatic_retry": False,
        "target": None,
        "readback": {"status": "unverified", "assertions": []},
        "receipt_references": list(receipts or []),
        "reason_codes": [reason],
        "policy": _policy(
            plan_id,
            "execute",
            "deny",
            [reason],
            masked_paths=masked_paths,
        ),
    }


def _compare_current(
    artifact: Mapping[str, Any],
    request: Mapping[str, Any],
    current: Mapping[str, Any],
) -> None:
    checks = (
        (mutation_digest(dict(request)), artifact["request_digest"], "ACTION_INPUT_CHANGED"),
        (current["principal_digest"], artifact["principal_digest"], "ACTION_IDENTITY_CHANGED"),
        (current["target_digest"], artifact["target_digest"], "ACTION_TARGET_CHANGED"),
        (
            current["contract_fingerprint"],
            artifact["contract_fingerprint"],
            "ACTION_CONTRACT_CHANGED",
        ),
    )
    for actual, expected, reason in checks:
        if actual != expected:
            _fail(reason)


def _policy(
    plan_id: str,
    phase: str,
    decision: str,
    reasons: list[str],
    *,
    masked_paths: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "schema_version": POLICY_SCHEMA_VERSION,
        "decision_id": mutation_digest(
            {"plan_id": plan_id, "phase": phase, "decision": decision, "reasons": reasons}
        )[:32],
        "policy_revision": "gravity.action-policy.v1",
        "decision": decision,
        "reason_codes": list(reasons),
        "evaluated_effect": "mutation",
        "masked_paths": list(masked_paths),
    }


def _request_action_kind(request: Any) -> str:
    if not isinstance(request, Mapping):
        raise InputValidationError(
            "actual value: Action request is not an object; allowed value: one registered Action request schema",
            field="request",
            code="ACTION_REQUEST_INVALID",
            next_action="Use one exact registered Action request and preview a new Action Plan.",
        )
    schema_version = request.get("schema_version")
    by_schema = {
        segment_connector.REQUEST_SCHEMA_VERSION: segment_connector.ACTION_KIND,
        dashboard_connector.REQUEST_SCHEMA_VERSION: dashboard_connector.ACTION_KIND,
    }
    action_kind = by_schema.get(schema_version)
    if action_kind is None:
        raise InputValidationError(
            "actual value: unregistered Action request schema; allowed value: a Segment update or Analysis Dashboard request",
            field="request.schema_version",
            code="ACTION_REQUEST_INVALID",
            next_action="Use one exact registered Action request and preview a new Action Plan.",
        )
    return action_kind


def _require_user_source(
    source: Any,
    expected: Mapping[str, Any],
    *,
    code: str,
    field: str,
) -> None:
    valid = (
        isinstance(source, Mapping)
        and set(source) == _SOURCE_FIELDS
        and source.get("schema_version") == SOURCE_SCHEMA_VERSION
        and source.get("origin") == "user"
        and source.get("role") == "authorization"
        and source.get("value") == expected
    )
    if not valid:
        raise InputValidationError(
            f"actual value: authorization source is absent, non-user, or not bound to the exact Action value; allowed value: current user/authorization source for {expected.get('schema_version')}",
            field=field,
            code=code,
            next_action="Obtain current explicit user authorization for the exact request or preview fingerprint, then retry once.",
        )


def _bounded_ttl(value: Any) -> None:
    if type(value) is not int or not 1 <= value <= MAX_TTL_SECONDS:
        raise InputValidationError(
            f"actual value: invalid Action Plan ttl; allowed range: 1 through {MAX_TTL_SECONDS} seconds",
            field="ttl_seconds",
            code="ACTION_TTL_INVALID",
            next_action="Choose a bounded expiry and preview a new Action Plan.",
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fail(code: str) -> None:
    raise InputValidationError(
        f"Action Plan stopped before mutation ({code}).",
        field="plan_id",
        code=code,
        next_action="Do not retry this plan; inspect current state and preview a new explicitly authorized Action Plan.",
    )


__all__ = [
    "AUTHORIZATION_SCHEMA_VERSION",
    "ActionPlanService",
    "CONFIRMATION_SCHEMA_VERSION",
    "DASHBOARD_REQUEST_SCHEMA_VERSION",
    "DEFAULT_TTL_SECONDS",
    "EXECUTION_SCHEMA_VERSION",
    "POLICY_SCHEMA_VERSION",
    "PUBLIC_SCHEMA_VERSION",
    "REQUEST_SCHEMA_VERSION",
]
