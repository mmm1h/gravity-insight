
"""Governed Segment CRUD with marker-or-upstream-owner readback gates."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .analysis_spec import compile_query_spec
from .actionable_error_values import actual_value
from .errors import (
    InputValidationError,
    MutationReadbackError,
)
from .segment_mutation_contracts import (
    DETAIL_OPERATION,
    FROM_ANALYSIS_CREATE as FROM_ANALYSIS,
    FROM_HISTORY_CREATE as FROM_HISTORY,
    FROM_RULE_CREATE,
    FROM_RULE_UPDATE,
    FROM_TMP_CREATE as FROM_TMP,
    LIST_OPERATION,
    MANUAL_UPDATE,
    SAVE,
)
from .segment_spec import compile_segment_spec


from .segment_mutation_support import (
    MARKER_PREFIX,
    SCHEMA_VERSION,
    WRITE_LOCK as _WRITE_LOCK,
    caller_remark as _caller_remark,
    completed as _completed,
    create_preview as _create_preview,
    dependent_preview as _dependent_preview,
    effect_preview as _effect_preview,
    execute_create as _execute_create,
    fixed_date as _fixed_date,
    identifier as _identifier,
    is_sdk_segment_remark,
    marked_remark as _marked_remark,
    marker_from_remark as _marker_from_remark,
    name as _name,
    row_id as _row_id,
    run_analysis as _run_analysis,
    require_segment_authority as _require_segment_authority,
    same_app as _same_app,
    segment_catalog as _segment_catalog,
    segment_detail as _segment_detail,
    segment_marker,
    step as _step,
)

def create_segment_from_analysis(
    client: Any,
    spec: Mapping[str, Any],
    *,
    app: str | int,
    name: str,
    step: int,
    is_loss: bool = True,
    remark: str = "",
    idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Run one explicit ungrouped funnel and persist its selected cell."""

    selected_name = _name(name)
    selected_step = _step(step)
    if type(is_loss) is not bool:
        raise InputValidationError(
            f"actual value: {actual_value(is_loss)}; allowed values: true or false",
            field="is_loss",
        )
    compiled = compile_query_spec("funnel", spec, app=app)
    if compiled.inputs.get("group_by_list") != []:
        raise InputValidationError(
            f"actual value: {actual_value(compiled.inputs.get('group_by_list'))}; allowed value: an ungrouped funnel",
            field="spec.group_by",
            next_action="Remove group_by, choose the funnel step/loss explicitly, then run the dry-run again.",
        )
    if selected_step >= len(compiled.inputs["query_item_list"]):
        raise InputValidationError(
            f"actual value: {actual_value(selected_step)}; allowed range: 0 through {len(compiled.inputs['query_item_list']) - 1}",
            field="step",
        )
    semantic = {
        "app_id": compiled.inputs["app_id"],
        "spec": copy.deepcopy(dict(spec)),
        "name": selected_name,
        "step": selected_step,
        "is_loss": is_loss,
    }
    marker = segment_marker(
        "from_analysis", semantic, idempotency_key=idempotency_key
    )
    marked_remark = _marked_remark(marker, remark)
    inputs = {
        **copy.deepcopy(compiled.inputs),
        "date_list_v2": _fixed_date(compiled.inputs["date_list"]),
        "segment_conf": {
            "segment_subject": "analysis_funnel",
            "segment_name": selected_name,
            "remark": marked_remark,
            "step": selected_step,
            "is_loss": is_loss,
        },
    }
    preview = client._preview_mutation(FROM_ANALYSIS, inputs)
    envelope = _create_preview(
        preview,
        app_id=str(compiled.inputs["app_id"]),
        name=selected_name,
        marker=marker,
        impact="Create one persistent segment from the selected funnel step/loss after the same funnel succeeds.",
        analysis_request={
            "operation_id": compiled.operation_id,
            "inputs": copy.deepcopy(compiled.inputs),
        },
    )
    if not execute:
        return envelope
    return _execute_create(
        client,
        operation_id=FROM_ANALYSIS,
        inputs=inputs,
        app_id=str(compiled.inputs["app_id"]),
        name=selected_name,
        marker=marker,
        before_write=lambda: _run_analysis(client, compiled.operation_id, compiled.inputs),
        preview=envelope,
    )


def create_segment_from_rule(
    client: Any,
    spec: Mapping[str, Any],
    *,
    app: str | int,
    idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Create one persistent segment from an explicit Segment Rule Spec."""

    compiled = compile_segment_spec(spec, app=app)
    semantic = copy.deepcopy(compiled.inputs)
    marker = segment_marker(
        "from_rule", semantic, idempotency_key=idempotency_key
    )
    inputs = {
        **compiled.inputs,
        "remark": _marked_remark(marker, str(compiled.inputs.get("remark", ""))),
    }
    preview = client._preview_mutation(FROM_RULE_CREATE, inputs)
    envelope = _create_preview(
        preview,
        app_id=str(inputs["app_id"]),
        name=str(inputs["name"]),
        marker=marker,
        impact="Create one persistent rule-based segment; no analysis, asset, promotion, or permission object is changed.",
    )
    if not execute:
        return envelope
    return _execute_create(
        client,
        operation_id=FROM_RULE_CREATE,
        inputs=inputs,
        app_id=str(inputs["app_id"]),
        name=str(inputs["name"]),
        marker=marker,
        preview=envelope,
    )


def create_segment_from_history(
    client: Any,
    *,
    app_id: str | int,
    source_segment_id: str | int,
    version_id: str | int,
    name: str,
    remark: str = "",
    idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    selected_app = _identifier(app_id, "app_id")
    selected_source = _identifier(source_segment_id, "source_segment_id")
    selected_version = _identifier(version_id, "version_id")
    selected_name = _name(name)
    semantic = {
        "app_id": selected_app,
        "source_segment_id": selected_source,
        "version_id": selected_version,
        "name": selected_name,
    }
    marker = segment_marker(
        "from_history", semantic, idempotency_key=idempotency_key
    )
    inputs = {
        "app_id": selected_app,
        "segment_id": selected_source,
        "version_id": selected_version,
        "segment_name": selected_name,
        "segment_remark": _marked_remark(marker, remark),
    }
    preview = client._preview_mutation(FROM_HISTORY, inputs)
    envelope = _create_preview(
        preview,
        app_id=selected_app,
        name=selected_name,
        marker=marker,
        impact="Create one persistent segment copied from one exact historical segment version.",
    )
    if not execute:
        return envelope
    return _execute_create(
        client, operation_id=FROM_HISTORY, inputs=inputs, app_id=selected_app,
        name=selected_name, marker=marker, preview=envelope,
    )


def create_segment_from_tmp(
    client: Any,
    *,
    app_id: str | int,
    tmp_segment_id: str | int,
    name: str,
    remark: str = "",
    idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    selected_app = _identifier(app_id, "app_id")
    selected_tmp = _identifier(tmp_segment_id, "tmp_segment_id")
    selected_name = _name(name)
    semantic = {
        "app_id": selected_app,
        "tmp_segment_id": selected_tmp,
        "name": selected_name,
    }
    marker = segment_marker("from_tmp", semantic, idempotency_key=idempotency_key)
    inputs = {
        "from_tmp_segment_id": selected_tmp,
        "app_id": selected_app,
        "segment_name": selected_name,
        "segment_remark": _marked_remark(marker, remark),
    }
    preview = client._preview_mutation(FROM_TMP, inputs)
    envelope = _create_preview(
        preview,
        app_id=selected_app,
        name=selected_name,
        marker=marker,
        impact="Create one persistent segment from one exact temporary segment.",
    )
    if not execute:
        return envelope
    return _execute_create(
        client, operation_id=FROM_TMP, inputs=inputs, app_id=selected_app,
        name=selected_name, marker=marker, preview=envelope,
    )


def update_segment_metadata(
    client: Any,
    segment_id: str | int,
    *,
    name: str,
    remark: str = "",
    execute: bool = False,
) -> dict[str, Any]:
    selected_id, selected_name = _identifier(segment_id, "segment_id"), _name(name)
    note = _caller_remark(remark)
    if not execute:
        return _dependent_preview(
            SAVE,
            selected_id,
            action="UPDATE_NAME",
            target={"segment_id": selected_id, "name": selected_name},
            impact="Update this segment's display name and remark; preserve an SDK marker if the read preimage contains one.",
        )
    with _WRITE_LOCK:
        preimage = _segment_detail(client, selected_id)
        ownership = _require_segment_authority(client, preimage)
        marker = _marker_from_remark(preimage.get("segment_remark"))
        selected_remark = _marked_remark(marker, note) if marker else note
        inputs = {
            "segment_id": selected_id,
            "segment_name": selected_name,
            "segment_remark": selected_remark,
            "action": "UPDATE_NAME",
        }
        preview = client._preview_mutation(SAVE, inputs)
        mutation = client._execute_mutation(SAVE, inputs)
        after = _segment_detail(client, selected_id)
        if after.get("segment_name") != selected_name or after.get("segment_remark", "") != selected_remark:
            raise MutationReadbackError(
                "segment metadata update did not round-trip",
                next_action="Read the segment by exact ID and review its current name/remark before issuing another write.",
            )
        return _completed(
            preview,
            mutation,
            {**after, "ownership": ownership.public()},
            preimage=preimage,
        )


def update_segment_rule(
    client: Any,
    segment_id: str | int,
    spec: Mapping[str, Any],
    *,
    app: str | int,
    execute: bool = False,
) -> dict[str, Any]:
    selected_id = _identifier(segment_id, "segment_id")
    compiled = compile_segment_spec(spec, app=app)
    if not execute:
        return _dependent_preview(
            FROM_RULE_UPDATE,
            selected_id,
            action="UPDATE_RULE",
            target={"segment_id": selected_id, "name": compiled.inputs["name"]},
            impact="Replace this segment's rule definition and preserve an SDK marker if the read preimage contains one.",
        )
    with _WRITE_LOCK:
        preimage = _segment_detail(client, selected_id)
        ownership = _require_segment_authority(client, preimage)
        _same_app(preimage, str(compiled.inputs["app_id"]))
        marker = _marker_from_remark(preimage.get("segment_remark"))
        note = str(compiled.inputs.get("remark", ""))
        inputs = {
            **compiled.inputs,
            "segment_id": selected_id,
            "remark": _marked_remark(marker, note) if marker else _caller_remark(note),
            "to_update_latest_result": True,
        }
        preview = client._preview_mutation(FROM_RULE_UPDATE, inputs)
        mutation = client._execute_mutation(FROM_RULE_UPDATE, inputs)
        after = _segment_detail(client, selected_id)
        if marker and _marker_from_remark(after.get("segment_remark")) != marker:
            raise MutationReadbackError(
                "segment rule update did not preserve the SDK marker",
                next_action="Stop writes and read the segment detail before deciding whether manual repair is needed.",
            )
        return _completed(
            preview,
            mutation,
            {**after, "ownership": ownership.public()},
            preimage=preimage,
        )


def refresh_segment(
    client: Any, segment_id: str | int, *, execute: bool = False
) -> dict[str, Any]:
    selected_id = _identifier(segment_id, "segment_id")
    inputs = {"segment_id": selected_id}
    preview = client._preview_mutation(MANUAL_UPDATE, inputs)
    envelope = _effect_preview(
        preview,
        target={"segment_id": selected_id},
        impact="Trigger one manual recalculation for this segment; current membership may change asynchronously.",
        preconditions=["The exact segment ID must still exist at execution time."],
    )
    if not execute:
        return envelope
    with _WRITE_LOCK:
        preimage = _segment_detail(client, selected_id)
        ownership = _require_segment_authority(client, preimage)
        mutation = client._execute_mutation(MANUAL_UPDATE, inputs)
        after = _segment_detail(client, selected_id)
        return _completed(
            envelope,
            mutation,
            {**after, "ownership": ownership.public()},
            preimage=preimage,
        )


def delete_segment(
    client: Any, segment_id: str | int, *, execute: bool = False
) -> dict[str, Any]:
    selected_id = _identifier(segment_id, "segment_id")
    if not execute:
        return _dependent_preview(
            SAVE,
            selected_id,
            action="DEL",
            target={"segment_id": selected_id},
            impact="Permanently delete this segment only after detail readback proves a Gravity SDK marker is present.",
        )
    with _WRITE_LOCK:
        preimage = _segment_detail(client, selected_id)
        ownership = _require_segment_authority(client, preimage)
        marker = _marker_from_remark(preimage.get("segment_remark"))
        name = _name(preimage.get("segment_name"))
        app_id = _identifier(preimage.get("app_id"), "app_id")
        inputs = {
            "segment_id": selected_id,
            "segment_name": name,
            "segment_remark": str(preimage["segment_remark"]),
            "action": "DEL",
        }
        preview = client._preview_mutation(SAVE, inputs)
        mutation = client._execute_mutation(SAVE, inputs)
        remaining = _segment_catalog(client, app_id)
        if any(_row_id(row) == selected_id for row in remaining):
            raise MutationReadbackError(
                "segment still exists after the delete acknowledgement",
                next_action="Read the segment by exact ID and inspect references before issuing another explicit delete.",
            )
        return _completed(
            preview,
            mutation,
            {
                "segment_id": selected_id,
                "deleted": True,
                "marker": marker,
                "ownership": ownership.public(),
            },
            preimage=preimage,
            status="deleted",
        )


__all__ = [
    "MARKER_PREFIX", "SCHEMA_VERSION", "create_segment_from_analysis",
    "create_segment_from_history", "create_segment_from_rule",
    "create_segment_from_tmp", "delete_segment", "is_sdk_segment_remark",
    "refresh_segment", "segment_marker", "update_segment_metadata",
    "update_segment_rule",
]
