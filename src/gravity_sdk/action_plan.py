"""R12-A Action Plan service with one fixed Segment update connector."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .action_plan_store import ActionPlanStore, bound_scope_key, timestamp
from .action_segment_connector import (
    ACTION_KIND,
    CONNECTOR_ID,
    CONNECTOR_VERSION,
    MANAGED_FIELDS,
    REQUEST_SCHEMA_VERSION,
    attempted_receipts,
    current_execution_binding,
    execute_segment_update,
    prepare_segment_update,
    verified_readback,
)
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

_SOURCE_FIELDS = frozenset({"schema_version", "origin", "role", "value"})


class ActionPlanService:
    """Prepare and consume one explicit Segment metadata Action Plan."""

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
            "action_kind": ACTION_KIND,
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
        prepared = prepare_segment_update(self._sdk.insight, request)
        now = _utcnow()
        expires = now + timedelta(seconds=ttl_seconds)
        nonce, plan_id = self._store.allocate()
        values = {
            "action_kind": ACTION_KIND,
            "connector_id": CONNECTOR_ID,
            "connector_version": CONNECTOR_VERSION,
            "created_at": timestamp(now),
            "expires_at": timestamp(expires),
            "request_digest": mutation_digest(dict(request)),
            "authorization_digest": mutation_digest(expected_authorization),
            "principal_digest": prepared["principal_digest"],
            "target_digest": prepared["target_digest"],
            "preimage_digest": prepared["preimage_digest"],
            "ownership_digest": prepared["ownership_digest"],
            "contract_fingerprint": prepared["contract_fingerprint"],
            "managed_fields": list(MANAGED_FIELDS),
        }
        values["preview_fingerprint"] = mutation_digest(
            {"nonce": nonce, **values}
        )
        artifact = self._store.create(nonce, values, now=now)
        return _public_plan(
            plan_id,
            artifact,
            prepared["normalized"],
            str(prepared["ownership_basis"]),
        )

    def execute(
        self,
        plan_id: str,
        request: Mapping[str, Any],
        *,
        confirmation: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Claim once, delegate to the Segment owner, and classify readback."""

        now = _utcnow()
        artifact = self._store.load(plan_id, now=now)
        current = current_execution_binding(self._sdk.insight, request)
        _compare_current(artifact, request, current)
        _require_user_source(
            confirmation,
            self.confirmation_value(plan_id, artifact["preview_fingerprint"]),
            code="ACTION_CONFIRMATION_REQUIRED",
            field="confirmation",
        )
        self._store.claim(plan_id, artifact, now=now)
        attempted = execute_segment_update(
            self._sdk.insight,
            current["normalized"],
            expected_preimage_digest=artifact["preimage_digest"],
        )
        return _execution_result(plan_id, attempted, current["normalized"])


def _public_plan(
    plan_id: str,
    artifact: Mapping[str, Any],
    normalized: Mapping[str, Any],
    ownership_basis: str,
) -> dict[str, Any]:
    return {
        "schema_version": PUBLIC_SCHEMA_VERSION,
        "ok": True,
        "status": "previewed",
        "plan_id": plan_id,
        "action_kind": ACTION_KIND,
        "connector": {"id": CONNECTOR_ID, "version": CONNECTOR_VERSION},
        "confirmation_summary": {
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
            "managed_fields": list(MANAGED_FIELDS),
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
        },
        "preview_fingerprint": artifact["preview_fingerprint"],
        "created_at": artifact["created_at"],
        "expires_at": artifact["expires_at"],
        "policy": _policy(
            plan_id, "preview", "require_confirmation", ["USER_CONFIRMATION_REQUIRED"]
        ),
    }


def _execution_result(
    plan_id: str,
    attempted: Mapping[str, Any],
    normalized: Mapping[str, Any],
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
            receipts=attempted_receipts(attempted),
        )
    readback = verified_readback(result, normalized)
    if writes != 1 or readback is None:
        return _failed_execution(
            plan_id,
            writes,
            "uncertain",
            "ACTION_FIELD_OWNERSHIP_CONFLICT",
            receipts=attempted_receipts(attempted),
        )
    return {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "ok": True,
        "status": "succeeded",
        "plan_id": plan_id,
        "action_kind": ACTION_KIND,
        "connector": {"id": CONNECTOR_ID, "version": CONNECTOR_VERSION},
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
        "policy": _policy(plan_id, "execute", "allow", ["USER_CONFIRMATION_BOUND"]),
    }


def _failed_execution(
    plan_id: str,
    writes: int,
    status: str,
    reason: str,
    *,
    receipts: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": EXECUTION_SCHEMA_VERSION,
        "ok": False,
        "status": status,
        "plan_id": plan_id,
        "action_kind": ACTION_KIND,
        "connector": {"id": CONNECTOR_ID, "version": CONNECTOR_VERSION},
        "write_attempted": writes > 0,
        "write_attempts": writes,
        "automatic_retry": False,
        "target": None,
        "readback": {"status": "unverified", "assertions": []},
        "receipt_references": list(receipts or []),
        "reason_codes": [reason],
        "policy": _policy(plan_id, "execute", "deny", [reason]),
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
    plan_id: str, phase: str, decision: str, reasons: list[str]
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
        "masked_paths": ["/request/remark"],
    }


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
    "DEFAULT_TTL_SECONDS",
    "EXECUTION_SCHEMA_VERSION",
    "POLICY_SCHEMA_VERSION",
    "PUBLIC_SCHEMA_VERSION",
    "REQUEST_SCHEMA_VERSION",
]
