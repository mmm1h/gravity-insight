"""Marker-governed report and subscription mutations."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from typing import Any

from .actionable_error_values import actual_value
from .errors import (
    ContractChangedError,
    InputValidationError,
    MutationReadbackError,
    ObjectAlreadyExistsError,
    OwnershipMarkerRequiredError,
)
from .report_contracts import (
    REPORT_DETAIL,
    REPORT_LIST,
    REPORT_UPDATE,
    SUBSCRIBE_CREATE,
    SUBSCRIBE_DELETE,
    SUBSCRIBE_LIST,
    TEMPLATE_CREATE,
    TEMPLATE_DETAIL,
    TEMPLATE_LIST,
    TEMPLATE_UPDATE,
)
from .result_source import GOVERNED_PRODUCT, result_source
from .report_mutation_support import (
    caller_text as _text,
    contract_text as _contract_text,
    json_text as _json,
    optional_caller_text as _caller_text,
    optional_nonnegative_id as _optional_nonnegative_id,
    positive_id as _positive_id,
    response_id as _response_id,
    subscription_report_config as _subscription_report_config,
    text_sequence as _text_sequence,
    two_texts as _two_texts,
)
from .segment_mutation_support import MARKER_PREFIX, WRITE_LOCK, segment_marker


SCHEMA_VERSION = "gravity-insight.report-mutation.v1"
_SUCCESS = frozenset({"success", "empty", "contract_changed_additive"})


def create_report(
    client: Any,
    *,
    app_id: int,
    name: str,
    config: Mapping[str, Any],
    subject: str = "measurement_report",
    remark: str = "SDK production-contract test",
    idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview or create one visibly marked report and verify list/detail readback."""

    selected_app = _positive_id(app_id, "app_id")
    selected_name = _text(name, "name", 128)
    selected_subject = _text(subject, "subject", 64)
    selected_remark = _caller_text(remark, "remark", 1_980)
    if not isinstance(config, Mapping):
        raise InputValidationError(
            f"actual value: {actual_value({'type': type(config).__name__})}; allowed value: a JSON object",
            field="config",
            next_action="Provide the exact frontend report config object and run dry-run again.",
        )
    config_text = _json(config, "config")
    semantic = {
        "app_id": selected_app, "name": selected_name,
        "subject": selected_subject, "config": config_text,
    }
    marker = segment_marker("report", semantic, idempotency_key=idempotency_key)
    marked_remark = f"{marker} | {selected_remark}" if selected_remark else marker
    inputs = {
        "name": selected_name,
        "remark": marked_remark,
        "subject": selected_subject,
        "app_id": selected_app,
        "config": config_text,
    }
    preview = _preview(
        client._preview_mutation(REPORT_UPDATE, inputs),
        target={"name": selected_name, "app_id": selected_app, "marker": marker},
        impact="Create one reusable test report without changing material, promotion, permission, or subscription state.",
    )
    if not execute:
        return preview
    with WRITE_LOCK:
        rows = _catalog(client, REPORT_LIST)
        existing = _unique_marker(rows, marker, fields=("remark",))
        if existing is not None:
            if existing.get("name") != selected_name:
                raise ObjectAlreadyExistsError(
                    f"actual value: {actual_value(existing.get('name'))}; allowed value: {actual_value(selected_name)}",
                    field="name",
                    next_action="Reuse the marked report or choose a new idempotency key and test name.",
                )
            return _idempotent(existing, REPORT_UPDATE)
        if any(row.get("name") == selected_name for row in rows):
            raise ObjectAlreadyExistsError(
                f"actual value: {actual_value(selected_name)}; allowed value: a unique report name",
                field="name",
                next_action="Choose another obvious test name and run dry-run again.",
            )
        mutation = client._execute_mutation(REPORT_UPDATE, inputs)
        created = _require_created(client, REPORT_LIST, marker, fields=("remark",), name=selected_name)
        detail = _detail(client, _response_id(created.get("id"), "id"))
        if _marker(detail, ("remark",)) != marker:
            raise MutationReadbackError(
                "created report marker did not round-trip through detail",
                next_action="Stop writes and inspect the exact marked report before cleanup.",
            )
        return _completed(preview, mutation, detail, "created")


def delete_report(client: Any, report_id: int | str, *, execute: bool = False) -> dict[str, Any]:
    """Preview or delete only a report whose detail readback proves SDK ownership."""

    selected_id = _positive_id(report_id, "report_id")
    if not execute:
        return _dependent_preview(
            REPORT_UPDATE, {"id": selected_id},
            "Delete this exact report only after list/detail readback proves a Gravity SDK marker.",
        )
    with WRITE_LOCK:
        preimage = _detail(client, selected_id)
        marker = _marker(preimage, ("remark",))
        if marker is None:
            raise OwnershipMarkerRequiredError(
                f"actual value: {actual_value({'report_id': selected_id, 'marker': None})}; allowed value: a report detail carrying GSDK-<12 hex>",
                field="report_id",
                next_action="Do not retry through the SDK; manage this unmarked report with its owner.",
            )
        inputs = {
            "id": selected_id,
            "name": _contract_text(preimage.get("name"), "name", 128),
            "subject": _contract_text(preimage.get("subject"), "subject", 64),
            "report_group_id": _optional_nonnegative_id(preimage.get("report_group_id"), "report_group_id"),
            "config": _contract_text(preimage.get("config"), "config", 100_000),
            "remark": _contract_text(preimage.get("remark"), "remark", 2_000),
            "is_delete": 1,
        }
        preview = client._preview_mutation(REPORT_UPDATE, inputs)
        mutation = client._execute_mutation(REPORT_UPDATE, inputs)
        if any(_response_id(row.get("id"), "id") == selected_id for row in _catalog(client, REPORT_LIST)):
            raise MutationReadbackError(
                "report still exists after the delete acknowledgement",
                next_action="Read the exact report and inspect references before another explicit delete.",
            )
        return _completed(preview, mutation, {"id": selected_id, "marker": marker, "deleted": True}, "deleted", preimage)


def create_subscription(
    client: Any,
    *,
    report_id: int,
    report_name: str,
    subscribe_time: Sequence[str],
    selected_columns: Sequence[str],
    idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Create one disabled subscription with no recipients, or fail closed."""

    selected_id = _positive_id(report_id, "report_id")
    selected_report_name = _text(report_name, "report_name", 110)
    dates = _two_texts(subscribe_time, "subscribe_time")
    columns = _text_sequence(selected_columns, "selected_columns", 256)
    marker = segment_marker(
        "report_subscription",
        {"report_id": selected_id, "subscribe_time": dates, "selected_columns": columns},
        idempotency_key=idempotency_key,
    )
    wildcard_name = f"<报表名称>_{marker}"
    name = f"{selected_report_name}_{marker}"
    inputs = {
        "id": selected_id,
        "wildcard_name": wildcard_name,
        "name": name,
        "report_type": 2,
        "subscribe_status": 0,
        "subscribe_time": dates,
        "send_way": "[]",
        "report_conf_template_id": selected_id,
        "subscribe_content": ["excel"],
        "subscribe_selected_columns": _json(columns, "selected_columns"),
    }
    preview = _preview(
        client._preview_mutation(SUBSCRIBE_CREATE, inputs),
        target={"report_id": selected_id, "name": name, "marker": marker},
        impact="Create one disabled report subscription with an empty recipient list; no test notification is sent.",
    )
    if not execute:
        return preview
    with WRITE_LOCK:
        rows = _catalog(client, SUBSCRIBE_LIST)
        existing = _unique_marker(rows, marker, fields=("name", "wildcard_name"))
        if existing is not None:
            return _idempotent(existing, SUBSCRIBE_CREATE)
        if any(row.get("name") == name for row in rows):
            raise ObjectAlreadyExistsError(
                f"actual value: {actual_value(name)}; allowed value: a unique subscription name",
                field="name",
                next_action="Choose a new idempotency key and run dry-run again.",
            )
        mutation = client._execute_mutation(SUBSCRIBE_CREATE, inputs)
        created = _require_created(client, SUBSCRIBE_LIST, marker, fields=("name", "wildcard_name"), name=name)
        if created.get("subscribe_status") not in (0, "0"):
            raise MutationReadbackError(
                "created subscription did not round-trip as disabled",
                next_action="Immediately inspect and disable the marked subscription in Gravity Web; do not call the test route.",
            )
        if created.get("send_way") not in (None, "", "[]", []):
            raise MutationReadbackError(
                "created subscription unexpectedly contains a recipient",
                next_action="Immediately inspect and remove the marked subscription in Gravity Web; do not call the test route.",
            )
        return _completed(preview, mutation, created, "created")


def create_subscription_report(
    client: Any,
    *,
    app_id: int | str,
    name: str = "GSDK订阅父报表",
    idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Create the v3 report-template parent required by subscriptions."""

    selected_app = _positive_id(app_id, "app_id")
    selected_name = _text(name, "name", 20)
    marker = segment_marker(
        "subscription_report", {"app_id": selected_app, "name": selected_name},
        idempotency_key=idempotency_key,
    )
    inputs = {
        "name": selected_name,
        "remark": f"{marker} | SDK subscription contract test",
        "category": "adreport",
        "config": _subscription_report_config(selected_app),
        "app_id": selected_app,
        "project_id": "0",
    }
    preview = _preview(
        client._preview_mutation(TEMPLATE_CREATE, inputs),
        target={"name": selected_name, "app_id": selected_app, "marker": marker},
        impact="Create one v3 test report used only as the parent of a disabled recipient-free subscription.",
    )
    if not execute:
        return preview
    with WRITE_LOCK:
        rows = _catalog(client, TEMPLATE_LIST)
        existing = _unique_marker(rows, marker, fields=("remark",))
        if existing is not None:
            return _idempotent(existing, TEMPLATE_CREATE)
        if any(row.get("name") == selected_name for row in rows):
            raise ObjectAlreadyExistsError(
                f"actual value: {actual_value(selected_name)}; allowed value: a unique v3 report name",
                field="name",
                next_action="Choose a unique obvious test name and run dry-run again.",
            )
        mutation = client._execute_mutation(TEMPLATE_CREATE, inputs)
        created = _require_created(
            client, TEMPLATE_LIST, marker, fields=("remark",), name=selected_name
        )
        detail = _template_detail(client, _response_id(created.get("id"), "id"))
        if _marker(detail, ("remark",)) != marker:
            raise MutationReadbackError(
                "created v3 report marker did not round-trip through detail",
                next_action="Stop writes and inspect the exact marked report before cleanup.",
            )
        return _completed(preview, mutation, detail, "created")


def delete_subscription_report(
    client: Any, report_id: int | str, *, execute: bool = False,
) -> dict[str, Any]:
    """Delete one marked v3 report after subscription cleanup."""

    selected_id = _positive_id(report_id, "report_id")
    if not execute:
        return _dependent_preview(
            TEMPLATE_UPDATE, {"id": selected_id},
            "Delete this v3 report only after complete-list readback proves a Gravity SDK marker.",
        )
    with WRITE_LOCK:
        matches = [
            row for row in _catalog(client, TEMPLATE_LIST)
            if _response_id(row.get("id"), "id") == selected_id
        ]
        if len(matches) != 1:
            raise MutationReadbackError(
                "v3 report delete preimage is missing or ambiguous",
                next_action="Read the complete v3 report list and resolve the exact ID before another write.",
            )
        preimage = matches[0]
        marker = _marker(preimage, ("remark",))
        if marker is None:
            raise OwnershipMarkerRequiredError(
                f"actual value: {actual_value({'report_id': selected_id, 'marker': None})}; allowed value: a v3 report row carrying GSDK-<12 hex>",
                field="report_id",
                next_action="Do not retry through the SDK; manage this unmarked report with its owner.",
            )
        preview = client._preview_mutation(TEMPLATE_UPDATE, {"id": selected_id, "is_deleted": 1})
        mutation = client._execute_mutation(TEMPLATE_UPDATE, {"id": selected_id, "is_deleted": 1})
        if any(_response_id(row.get("id"), "id") == selected_id for row in _catalog(client, TEMPLATE_LIST)):
            raise MutationReadbackError(
                "v3 report still exists after the delete acknowledgement",
                next_action="Inspect the exact marked report before another explicit delete.",
            )
        return _completed(preview, mutation, {"id": selected_id, "marker": marker, "deleted": True}, "deleted", preimage)


def delete_subscription(client: Any, subscription_id: int | str, *, execute: bool = False) -> dict[str, Any]:
    """Preview or delete one list-readback-verified marked subscription."""

    selected_id = _positive_id(subscription_id, "subscription_id")
    if not execute:
        return _dependent_preview(
            SUBSCRIBE_DELETE, {"id": selected_id},
            "Delete this subscription only after a complete list read proves a Gravity SDK marker.",
        )
    with WRITE_LOCK:
        rows = _catalog(client, SUBSCRIBE_LIST)
        matches = [row for row in rows if _response_id(row.get("id"), "id") == selected_id]
        if len(matches) != 1:
            raise MutationReadbackError(
                "subscription delete preimage is missing or ambiguous",
                next_action="Read the complete subscription list and resolve the exact ID before another write.",
            )
        preimage = matches[0]
        marker = _marker(preimage, ("name", "wildcard_name"))
        if marker is None:
            raise OwnershipMarkerRequiredError(
                f"actual value: {actual_value({'subscription_id': selected_id, 'marker': None})}; allowed value: a subscription name carrying GSDK-<12 hex>",
                field="subscription_id",
                next_action="Do not retry through the SDK; manage this unmarked subscription with its owner.",
            )
        preview = client._preview_mutation(SUBSCRIBE_DELETE, {"ids": [selected_id]})
        mutation = client._execute_mutation(SUBSCRIBE_DELETE, {"ids": [selected_id]})
        remaining = _catalog(client, SUBSCRIBE_LIST)
        if any(_response_id(row.get("id"), "id") == selected_id for row in remaining):
            raise MutationReadbackError(
                "subscription still exists after the delete acknowledgement",
                next_action="Inspect the exact marked subscription before another explicit delete.",
            )
        return _completed(preview, mutation, {"id": selected_id, "marker": marker, "deleted": True}, "deleted", preimage)


def marker_in_report(value: Any) -> bool:
    return _marker(value if isinstance(value, Mapping) else {}, ("remark",)) is not None


def marker_in_subscription(value: Any) -> bool:
    return _marker(value if isinstance(value, Mapping) else {}, ("name", "wildcard_name")) is not None


def _catalog(client: Any, operation_id: str) -> list[Mapping[str, Any]]:
    value = client.read_all(
        operation_id, {"filters": [], "page": 1, "page_size": 20},
        max_pages=1_000, max_items=100_000, max_workers=1,
    )
    if not isinstance(value, Mapping) or value.get("error") is not None or value.get("status") not in _SUCCESS:
        raise MutationReadbackError(
            "report catalog could not be read before or after the mutation",
            next_action="Restore the exact list read and inspect current state before another write.",
        )
    if value.get("truncated") is True or value.get("next_page_input") not in (None, {}):
        raise ContractChangedError(
            "report catalog is incomplete; mutation preflight failed closed",
            next_action="Raise the bounded catalog limit before retrying; do not bypass preflight.",
        )
    data = value.get("data")
    rows = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise ContractChangedError(
            "report catalog no longer returns data.list",
            next_action="Stop writes until the list contract is re-verified.",
        )
    return rows


def _detail(client: Any, report_id: str) -> Mapping[str, Any]:
    value = client.read(REPORT_DETAIL, {"id": report_id})
    data = value.get("data") if isinstance(value, Mapping) else None
    if not isinstance(value, Mapping) or value.get("error") is not None or value.get("status") not in _SUCCESS or not isinstance(data, Mapping):
        raise MutationReadbackError(
            "report detail could not be read for mutation preimage/readback",
            next_action="Read the exact report ID and resolve the upstream error before another write.",
        )
    if _response_id(data.get("id"), "id") != report_id:
        raise ContractChangedError(
            "report detail identity changed",
            next_action="Stop writes until report detail identity is re-verified.",
        )
    return data


def _template_detail(client: Any, report_id: str) -> Mapping[str, Any]:
    value = client.read(TEMPLATE_DETAIL, {"id": report_id, "subscribe": 1})
    data = value.get("data") if isinstance(value, Mapping) else None
    detail = data.get("detail") if isinstance(data, Mapping) else None
    if not isinstance(value, Mapping) or value.get("error") is not None or value.get("status") not in _SUCCESS or not isinstance(detail, Mapping):
        raise MutationReadbackError(
            "v3 report detail could not be read for mutation preimage/readback",
            next_action="Read the exact v3 report ID and resolve the upstream error before another write.",
        )
    if _response_id(detail.get("id"), "id") != report_id:
        raise ContractChangedError(
            "v3 report detail identity changed",
            next_action="Stop writes until the v3 report detail contract is re-verified.",
        )
    return detail


def _unique_marker(rows: Sequence[Mapping[str, Any]], marker: str, *, fields: Sequence[str]) -> Mapping[str, Any] | None:
    matches = [row for row in rows if _marker(row, fields) == marker]
    if len(matches) > 1:
        raise MutationReadbackError(
            "more than one object has the same SDK marker",
            next_action="List the marker matches and remove only confirmed duplicates before retrying.",
        )
    return matches[0] if matches else None


def _require_created(client: Any, operation_id: str, marker: str, *, fields: Sequence[str], name: str) -> Mapping[str, Any]:
    match = _unique_marker(_catalog(client, operation_id), marker, fields=fields)
    if match is None or match.get("name") != name:
        raise MutationReadbackError(
            "created object did not round-trip through its list",
            next_action="Inspect this SDK marker before deciding whether another create is safe.",
        )
    return match


def _marker(row: Mapping[str, Any], fields: Sequence[str]) -> str | None:
    for field in fields:
        value = row.get(field)
        if not isinstance(value, str):
            continue
        start = value.find(MARKER_PREFIX)
        if start < 0:
            continue
        candidate = value[start:start + 17]
        if len(candidate) == 17 and all(char in "0123456789abcdef" for char in candidate[5:]):
            return candidate
    return None


def _preview(preview: Mapping[str, Any], *, target: Mapping[str, Any], impact: str) -> dict[str, Any]:
    return {
        **copy.deepcopy(dict(preview)),
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "dry_run": True,
        "confirmation_required": True,
        "target": copy.deepcopy(dict(target)),
        "impact": impact,
        "preconditions": [
            "Read the complete target list before writing.",
            "Treat an exact marker match as idempotent reuse.",
            "Send at most one non-retried write.",
            "Read the object back and verify its marker after acknowledgement.",
        ],
        "automatic_retry": False,
        "next_action": "Review this zero-network preview, then repeat with execute=true or --execute.",
    }


def _dependent_preview(operation_id: str, target: Mapping[str, Any], impact: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True, "status": "preview", "operation_id": operation_id,
        "effect": "mutation", "offline": True, "network_called": False,
        "dry_run": True, "confirmation_required": True,
        "target": copy.deepcopy(dict(target)), "impact": impact,
        "preconditions": [
            "Read the exact upstream preimage at execution time.",
            "Refuse deletion unless the preimage contains GSDK-<12 hex>.",
            "Read the complete list after deletion and prove the ID is absent.",
        ],
        "automatic_retry": False, "attempts": 0,
        "next_action": "Review the target, then repeat with execute=true or --execute.",
    }


def _completed(preview: Mapping[str, Any], mutation: Mapping[str, Any], target: Mapping[str, Any], status: str, preimage: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True, "status": status, "operation_id": mutation.get("operation_id"),
        "effect": "mutation", "offline": False, "network_called": True,
        "dry_run": False, "confirmation_required": False, "automatic_retry": False,
        "attempts": mutation.get("attempts", 1), "target": copy.deepcopy(dict(target)),
        "preimage": copy.deepcopy(dict(preimage)) if preimage is not None else None,
        "mutation": copy.deepcopy(dict(mutation)), "error": None,
    }


def _idempotent(existing: Mapping[str, Any], operation_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True, "status": "already_exists", "operation_id": operation_id,
        "effect": "mutation", "offline": False, "network_called": True,
        "write_sent": False, "attempts": 0, "idempotent_reuse": True,
        "target": copy.deepcopy(dict(existing)), "error": None,
    }


__all__ = [
    "MARKER_PREFIX", "SCHEMA_VERSION", "create_report", "create_subscription",
    "create_subscription_report", "delete_report", "delete_subscription",
    "delete_subscription_report", "marker_in_report",
    "marker_in_subscription",
]
