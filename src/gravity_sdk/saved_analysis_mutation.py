"""Governed create, update, and delete lifecycle for saved Analysis assets."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .actionable_error_values import actual_value
from .composite_catalog import stable_operation
from .errors import (
    ContractChangedError,
    GravityInsightError,
    InputValidationError,
    MutationReadbackError,
    ObjectAlreadyExistsError,
    UnsupportedOperationError,
    UpstreamError,
)
from .mutation_lifecycle import WRITE_LOCK, mutation_marker
from .mutation_ownership import (
    create_user_owner,
    require_mutation_authority,
    single_creator_owner,
)
from .report_mutation_support import caller_text, marker, optional_caller_text, positive_id
from .result_source import GOVERNED_PRODUCT, result_source
from .saved_analysis_artifact import preflight_saved_definition
from .saved_analysis_catalog import GET_OPERATION_ID, list_saved_analyses
from .saved_analysis_support import decoded_config, identifier, require_success, supported_subject


UPDATE_OPERATION_ID = stable_operation(
    "analysis", "report_config", action="update"
).operation_id
SCHEMA_VERSION = "gravity-insight.saved-analysis-mutation.v1"
CREATE_UNSUPPORTED_CODE = "SAVED_ANALYSIS_CREATE_UNSUPPORTED"


def create_saved_analysis(
    client: Any,
    *,
    app_id: str | int,
    name: str,
    subject: str,
    config: Mapping[str, Any],
    remark: str = "",
    idempotency_key: str | None = None,
    workspace: Any | None = None,
    start: str | None = None,
    end: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview or create one reusable, marked, replay-validated analysis."""

    selected_app = positive_id(app_id, "app_id")
    selected_name = caller_text(name, "name", 256)
    selected_subject, config_text = _definition(
        subject, config, app_id=selected_app, workspace=workspace, start=start, end=end
    )
    selected_remark = optional_caller_text(remark, "remark", 1_980)
    selected_marker = mutation_marker(
        "saved_analysis",
        {
            "app_id": selected_app,
            "name": selected_name,
            "subject": selected_subject,
            "config": config_text,
        },
        idempotency_key=idempotency_key,
    )
    marked_remark = _marked_remark(selected_marker, selected_remark)
    inputs = {
        "app_id": selected_app,
        "subject": selected_subject,
        "name": selected_name,
        "config": config_text,
        "remark": marked_remark,
    }
    dry_run = _create_preview(
        client._preview_mutation(UPDATE_OPERATION_ID, inputs),
        target={
            "app_id": selected_app,
            "name": selected_name,
            "subject": selected_subject,
            "marker": selected_marker,
        },
    )
    if not execute:
        return dry_run
    with WRITE_LOCK:
        rows = _catalog(client, selected_app, workspace)
        existing = _unique_marker(rows, selected_marker)
        if existing is not None:
            if existing.get("name") != selected_name:
                raise ObjectAlreadyExistsError(
                    f"actual value: {actual_value(existing.get('name'))}; allowed value: {actual_value(selected_name)}",
                    field="name",
                    next_action="Reuse the marked analysis or choose another idempotency key and name.",
                )
            return _idempotent(existing)
        if any(row.get("name") == selected_name for row in rows):
            raise ObjectAlreadyExistsError(
                f"actual value: {actual_value(selected_name)}; allowed value: a unique saved Analysis name",
                field="name",
                next_action="Choose another name and repeat the same dry-run before executing.",
            )
        mutation = _execute_create(client, inputs)
        created = _unique_marker(
            _catalog(client, selected_app, workspace), selected_marker
        )
        if created is None or created.get("name") != selected_name:
            raise MutationReadbackError(
                "created saved Analysis did not round-trip through its complete list",
                next_action="Inspect this exact GSDK marker before deciding whether another create is safe.",
            )
        detail = _detail(client, selected_app, identifier(created.get("id"), "id"))
        _require_definition(detail, inputs, "created")
        return _completed(mutation, _safe_record(detail), "created")


def update_saved_analysis(
    client: Any,
    analysis_id: str | int,
    *,
    app_id: str | int,
    name: str,
    subject: str,
    config: Mapping[str, Any],
    remark: str = "",
    workspace: Any | None = None,
    start: str | None = None,
    end: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview or replace the full definition after marker-or-owner preflight."""

    selected_id = identifier(analysis_id, "analysis_id")
    selected_app = positive_id(app_id, "app_id")
    selected_name = caller_text(name, "name", 256)
    selected_subject, config_text = _definition(
        subject, config, app_id=selected_app, workspace=workspace, start=start, end=end
    )
    selected_remark = optional_caller_text(remark, "remark", 2_000)
    if not execute:
        return _dependent_preview(
            selected_id,
            selected_app,
            "Replace this saved Analysis full definition after marker-or-owner readback.",
        )
    with WRITE_LOCK:
        row = _exact_row(_catalog(client, selected_app, workspace), selected_id)
        preimage = _detail(client, selected_app, selected_id)
        ownership = _authority(client, row, preimage, selected_id)
        selected_marker = marker(row, ("name", "remark")) or marker(
            preimage, ("name", "remark")
        )
        inputs = {
            "app_id": selected_app,
            "id": selected_id,
            "subject": selected_subject,
            "name": selected_name,
            "config": config_text,
            "remark": _marked_remark(selected_marker, selected_remark),
        }
        if _same_definition(preimage, inputs):
            return _idempotent(_safe_record(preimage), status="already_current")
        mutation = client._execute_mutation(UPDATE_OPERATION_ID, inputs)
        listed = _exact_row(_catalog(client, selected_app, workspace), selected_id)
        if listed.get("name") != selected_name:
            raise MutationReadbackError(
                "updated saved Analysis name did not round-trip through its list",
                next_action="Read the exact analysis ID and stop writes if the old name remains.",
            )
        detail = _detail(client, selected_app, selected_id)
        _require_definition(detail, inputs, "updated")
        target = _safe_record(detail)
        target["ownership"] = ownership.public()
        return _completed(mutation, target, "updated", preimage=_safe_record(preimage))


def delete_saved_analysis(
    client: Any,
    analysis_id: str | int,
    *,
    app_id: str | int,
    workspace: Any | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview or soft-delete one exact asset and prove it disappears from list."""

    selected_id = identifier(analysis_id, "analysis_id")
    selected_app = positive_id(app_id, "app_id")
    if not execute:
        return _dependent_preview(
            selected_id,
            selected_app,
            "Delete this exact saved Analysis after marker-or-owner readback.",
        )
    with WRITE_LOCK:
        row = _exact_row(_catalog(client, selected_app, workspace), selected_id)
        preimage = _detail(client, selected_app, selected_id)
        ownership = _authority(client, row, preimage, selected_id)
        inputs = {
            "app_id": selected_app,
            "id": selected_id,
            "subject": _contract_text(preimage.get("subject"), "subject", 64),
            "name": _contract_text(preimage.get("name"), "name", 256),
            "config": _contract_text(preimage.get("config"), "config", 1_000_000),
            "remark": _contract_string(preimage.get("remark"), "remark", 2_000),
            "is_deleted": True,
        }
        mutation = client._execute_mutation(UPDATE_OPERATION_ID, inputs)
        remaining = _catalog(client, selected_app, workspace)
        if any(row.get("id") == selected_id for row in remaining):
            raise ContractChangedError(
                "saved Analysis still exists after the delete acknowledgement",
                next_action="Stop writes and re-verify report_config/update delete semantics before retrying.",
            )
        target = _safe_record(preimage)
        target.update({"deleted": True, "ownership": ownership.public()})
        return _completed(mutation, target, "deleted", preimage=_safe_record(preimage))


def _definition(
    subject: Any,
    config: Any,
    *,
    app_id: str,
    workspace: Any,
    start: str | None,
    end: str | None,
) -> tuple[str, str]:
    supported_subject(subject)
    decoded = decoded_config(config)
    prepared = preflight_saved_definition(
        {"subject": subject, "config": decoded},
        app=app_id,
        workspace=workspace,
        start=start,
        end=end,
    )
    return str(subject), json.dumps(
        prepared, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )


def _execute_create(client: Any, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        return client._execute_mutation(UPDATE_OPERATION_ID, inputs)
    except InputValidationError as error:
        code = getattr(error.code, "value", error.code)
        if code != "INPUT_INVALID" or error.field != "mutation":
            raise
        raise _create_unsupported(error) from None
    except UpstreamError as error:
        if type(error) is not UpstreamError:
            raise
        raise _create_unsupported(error) from None


def _create_unsupported(error: BaseException) -> UnsupportedOperationError:
    classified = UnsupportedOperationError(
        "actual value: upstream rejected a locally replay-validated saved Analysis create; "
        "allowed value: a create definition accepted by the registered upstream write contract",
        field="saved_analysis.create",
        code=CREATE_UNSUPPORTED_CODE,
        next_action=(
            "Treat this exact subject/config definition as unsupported and do not retry it. "
            "Reuse an accessible saved Analysis, or wait until upstream-accepted write evidence "
            "is registered."
        ),
    )
    references = getattr(error, "http_receipt_references", ())
    if references:
        classified.http_receipt_references = references
    return classified


def _catalog(client: Any, app_id: str, workspace: Any) -> list[Mapping[str, Any]]:
    value = list_saved_analyses(client, app_id, workspace=workspace)
    rows = value.get("items") if isinstance(value, Mapping) else None
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise ContractChangedError(
            "saved Analysis list product changed shape",
            next_action="Stop writes until the complete saved Analysis catalog is restored.",
        )
    return [row for row in rows if isinstance(row, Mapping)]


def _detail(client: Any, app_id: str, analysis_id: str) -> Mapping[str, Any]:
    value = client.read(GET_OPERATION_ID, {"app_id": app_id, "id": analysis_id})
    require_success(value, GET_OPERATION_ID, "saved Analysis mutation detail")
    data = value.get("data") if isinstance(value, Mapping) else None
    if not isinstance(data, Mapping):
        raise ContractChangedError(
            "saved Analysis mutation detail changed shape",
            next_action="Stop writes until analysis.report_config.get is re-verified.",
        )
    if _contract_identifier(data.get("id"), "detail.id") != analysis_id:
        raise ContractChangedError(
            "saved Analysis detail identity changed",
            next_action="List the selected App again and resolve the exact ID before another write.",
        )
    if _contract_identifier(data.get("app_id"), "detail.app_id") != app_id:
        raise ContractChangedError(
            "saved Analysis detail crossed the selected App boundary",
            next_action="Stop writes until report_config/info App scoping is re-verified.",
        )
    return data


def _exact_row(rows: Sequence[Mapping[str, Any]], analysis_id: str) -> Mapping[str, Any]:
    matches = [row for row in rows if row.get("id") == analysis_id]
    if len(matches) != 1:
        raise InputValidationError(
            f"actual value: {actual_value({'id': analysis_id, 'matches': len(matches)})}; allowed value: one exact saved Analysis",
            field="analysis_id",
            next_action="List saved analyses for this App and retry with one exact current ID.",
        )
    return matches[0]


def _unique_marker(
    rows: Sequence[Mapping[str, Any]], selected_marker: str
) -> Mapping[str, Any] | None:
    matches = [
        row for row in rows
        if marker(row, ("name", "remark")) == selected_marker
    ]
    if len(matches) > 1:
        raise MutationReadbackError(
            "more than one saved Analysis has the same SDK marker",
            next_action="List the marker matches and remove only confirmed duplicates before retrying.",
        )
    return matches[0] if matches else None


def _authority(
    client: Any,
    row: Mapping[str, Any],
    detail: Mapping[str, Any],
    analysis_id: str,
) -> Any:
    selected_marker = marker(row, ("name", "remark")) or marker(
        detail, ("name", "remark")
    )
    owner = create_user_owner(detail)
    if owner.owner_id is None:
        owner = create_user_owner(row)
    if owner.owner_id is None:
        owner = single_creator_owner(detail.get("creator"))
    return require_mutation_authority(
        client,
        marker=selected_marker,
        owner=owner,
        object_kind="saved Analysis",
        object_id=analysis_id,
        field="analysis_id",
    )


def _require_definition(
    detail: Mapping[str, Any], expected: Mapping[str, Any], action: str
) -> None:
    scalar_fields = ("id", "app_id", "name", "subject", "remark")
    for field in scalar_fields:
        if field in expected and str(detail.get(field)) != str(expected[field]):
            raise MutationReadbackError(
                f"{action} saved Analysis {field} did not round-trip",
                next_action="Read the exact analysis ID and inspect current state before another write.",
            )
    try:
        same_config = decoded_config(detail.get("config")) == decoded_config(
            expected.get("config")
        )
    except GravityInsightError:
        same_config = False
    if not same_config:
        raise MutationReadbackError(
            f"{action} saved Analysis config did not round-trip",
            next_action="Read the exact analysis ID and inspect its definition before another write.",
        )


def _same_definition(current: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    if any(str(current.get(key)) != str(expected.get(key)) for key in ("id", "app_id", "name", "subject", "remark")):
        return False
    try:
        return decoded_config(current.get("config")) == decoded_config(expected.get("config"))
    except GravityInsightError:
        return False


def _marked_remark(selected_marker: str | None, remark: str) -> str:
    if selected_marker is None:
        return remark
    return f"{selected_marker} | {remark}" if remark else selected_marker


def _contract_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ContractChangedError(
            f"saved Analysis {field} changed type or range",
            next_action="Stop writes until the saved Analysis detail contract is re-verified.",
        )
    return value


def _contract_identifier(value: Any, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ContractChangedError(
            f"saved Analysis {field} changed type",
            next_action="Stop writes until the saved Analysis identity contract is re-verified.",
        )
    selected = str(value).strip()
    if not selected or len(selected) > 256:
        raise ContractChangedError(
            f"saved Analysis {field} changed range",
            next_action="Stop writes until the saved Analysis identity contract is re-verified.",
        )
    return selected


def _contract_string(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum:
        raise ContractChangedError(
            f"saved Analysis {field} changed type or range",
            next_action="Stop writes until the saved Analysis detail contract is re-verified.",
        )
    return value


def _safe_record(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value[key])
        for key in (
            "id", "app_id", "name", "subject", "remark", "create_time",
            "modify_time", "create_user_id", "create_user_name", "update_user_id",
            "update_user_name",
        )
        if key in value
    }


def _create_preview(raw: Mapping[str, Any], *, target: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **copy.deepcopy(dict(raw)),
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "dry_run": True,
        "confirmation_required": True,
        "target": copy.deepcopy(dict(target)),
        "impact": "Create one reusable saved Analysis; no sharing or dashboard state changes.",
        "preconditions": [
            "Read the complete saved Analysis list before writing.",
            "Treat one exact marker match as idempotent reuse.",
            "Send one non-retried write and verify list plus detail readback.",
        ],
        "automatic_retry": False,
        "next_action": "Review this zero-network preview, then repeat with execute=true or --execute.",
    }


def _dependent_preview(analysis_id: str, app_id: str, impact: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "preview",
        "operation_id": UPDATE_OPERATION_ID,
        "effect": "mutation",
        "offline": True,
        "network_called": False,
        "dry_run": True,
        "confirmation_required": True,
        "target": {"id": analysis_id, "app_id": app_id},
        "impact": impact,
        "preconditions": [
            "Read the complete list and exact detail at execution time.",
            "Require a GSDK marker or create_user_id/creator.id equal to gravity_id.",
            "Send one non-retried write and verify fresh readback.",
        ],
        "automatic_retry": False,
        "attempts": 0,
        "next_action": "Review the target and full definition, then repeat with execute=true or --execute.",
    }


def _completed(
    mutation: Mapping[str, Any],
    target: Mapping[str, Any],
    status: str,
    *,
    preimage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": status,
        "operation_id": UPDATE_OPERATION_ID,
        "effect": "mutation",
        "offline": False,
        "network_called": True,
        "dry_run": False,
        "confirmation_required": False,
        "automatic_retry": False,
        "attempts": mutation.get("attempts", 1),
        "target": copy.deepcopy(dict(target)),
        "preimage": copy.deepcopy(dict(preimage)) if preimage is not None else None,
        "mutation": copy.deepcopy(dict(mutation)),
        "error": None,
    }


def _idempotent(value: Mapping[str, Any], *, status: str = "already_exists") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": status,
        "operation_id": UPDATE_OPERATION_ID,
        "effect": "mutation",
        "offline": False,
        "network_called": True,
        "write_sent": False,
        "attempts": 0,
        "idempotent_reuse": True,
        "target": _safe_record(value),
        "error": None,
    }


__all__ = [
    "CREATE_UNSUPPORTED_CODE",
    "SCHEMA_VERSION",
    "UPDATE_OPERATION_ID",
    "create_saved_analysis",
    "delete_saved_analysis",
    "update_saved_analysis",
]
