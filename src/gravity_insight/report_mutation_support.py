"""Input and payload helpers shared by governed report mutations."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .actionable_error_values import actual_value
from .errors import ContractChangedError, InputValidationError, MutationReadbackError
from .mutation_lifecycle import MARKER_PREFIX
from .mutation_ownership import create_user_owner, require_mutation_authority
from .result_source import GOVERNED_PRODUCT, result_source


SCHEMA_VERSION = "gravity-insight.report-mutation.v1"
_SUCCESS = frozenset({"success", "empty", "contract_changed_additive"})


def positive_id(value: Any, field: str) -> str:
    selected = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    if not selected.isdecimal() or int(selected or 0) < 1 or len(selected) > 64:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: a positive integer identifier",
            field=field,
            next_action=f"Use the exact positive {field} returned by the parent list and run dry-run again.",
        )
    return selected


def response_id(value: Any, field: str) -> str:
    selected = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    if not selected.isdecimal() or int(selected or 0) < 1 or len(selected) > 64:
        raise ContractChangedError(
            f"{field} changed type or range",
            next_action="Stop writes until the parent list/detail identity contract is re-verified.",
        )
    return selected


def optional_nonnegative_id(value: Any, field: str) -> str:
    if value is None:
        return "0"
    selected = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    if not selected.isdecimal() or len(selected) > 64:
        raise ContractChangedError(
            f"{field} changed type",
            next_action="Stop writes until the report detail contract is re-verified.",
        )
    return selected


def caller_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed range: 1 through {maximum} characters",
            field=field,
            next_action=f"Use a non-empty {field} within the documented limit and run dry-run again.",
        )
    return value


def optional_caller_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum or MARKER_PREFIX in value:
        raise InputValidationError(
            f"actual value: {actual_value({'type': type(value).__name__, 'length': len(value) if isinstance(value, str) else None, 'contains_marker': isinstance(value, str) and MARKER_PREFIX in value})}; allowed value: caller text without an SDK marker, at most {maximum} characters",
            field=field,
            next_action="Remove marker-like text; the SDK owns marker generation, then run dry-run again.",
        )
    return value.strip()


def contract_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ContractChangedError(
            f"{field} changed type or range",
            next_action="Stop writes until the report detail contract is re-verified.",
        )
    return value


def two_texts(value: Any, field: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 2:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: exactly two timestamp strings",
            field=field,
            next_action="Provide [start_time, end_time] from the frontend contract and run dry-run again.",
        )
    return [caller_text(item, field, 64) for item in value]


def text_sequence(value: Any, field: str, maximum: int) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; allowed value: one or more text values",
            field=field,
            next_action=f"Provide at least one exact {field} value and run dry-run again.",
        )
    return [caller_text(item, field, maximum) for item in value]


def json_text(value: Any, field: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise InputValidationError(
            f"actual value: {actual_value({'type': type(value).__name__})}; allowed value: JSON-serializable data",
            field=field,
            next_action="Remove non-JSON values and run dry-run again.",
        ) from exc


def subscription_report_config(app_id: str) -> dict[str, Any]:
    """Return the smallest structurally complete adreport config from the UI builder."""

    return {
        "columns": [
            {"label": "产品", "prop": "app_id", "type": "dim", "width": 150},
            {"label": "激活数", "prop": "activation", "type": "metric", "width": 150},
        ],
        "filterForm": {
            "appFormModel": {"app_id": app_id, "project_id": "0"},
            "dateListFormModel": {"resultDate": []},
        },
        "formModel": {
            "multi_days": 7, "minigame_pay_shared_ratio_switch": False,
            "minigame_pay_shared_ratio": 60, "minigame_pay_shared_ratio_ios": 100,
            "decimal_point_switch": False, "roi_version": 1,
            "accumulate": False, "asa_time_zone": "UTC",
        },
        "extra_data": {
            "summaryTypeObj": {}, "sortTypeObj": {}, "sortList": [],
            "tableDetail": {
                "dimsResult": {"view": "table", "dims": ["app_id"], "relateDims": []},
                "metricsResult": [{"name": "activation", "cname": "激活数"}],
            },
            "dayRadioValue": "", "hideChart": True, "dateSum": "day",
        },
        "dateList": [],
        "conditionFilterData": {
            "conditions": [{"relation": {"value": "or"}, "field": "", "field_type": "", "operator": "", "value": []}],
            "outRelation": "and",
        },
    }


def marker_in_report(value: Any) -> bool:
    return marker(value if isinstance(value, Mapping) else {}, ("remark",)) is not None


def marker_in_subscription(value: Any) -> bool:
    return marker(
        value if isinstance(value, Mapping) else {}, ("name", "wildcard_name")
    ) is not None


def catalog(client: Any, operation_id: str) -> list[Mapping[str, Any]]:
    value = client.read_all(
        operation_id,
        {"filters": [], "page": 1, "page_size": 20},
        max_pages=1_000,
        max_items=100_000,
        max_workers=1,
    )
    if (
        not isinstance(value, Mapping)
        or value.get("error") is not None
        or value.get("status") not in _SUCCESS
    ):
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


def detail(client: Any, operation_id: str, report_id: str, *, nested: bool = False) -> Mapping[str, Any]:
    inputs = {"id": report_id, **({"subscribe": 1} if nested else {})}
    value = client.read(operation_id, inputs)
    data = value.get("data") if isinstance(value, Mapping) else None
    selected = data.get("detail") if nested and isinstance(data, Mapping) else data
    if (
        not isinstance(value, Mapping)
        or value.get("error") is not None
        or value.get("status") not in _SUCCESS
        or not isinstance(selected, Mapping)
    ):
        raise MutationReadbackError(
            "report detail could not be read for mutation preimage/readback",
            next_action="Read the exact report ID and resolve the upstream error before another write.",
        )
    if response_id(selected.get("id"), "id") != report_id:
        raise ContractChangedError(
            "report detail identity changed",
            next_action="Stop writes until the report detail contract is re-verified.",
        )
    return selected


def unique_marker(
    rows: Sequence[Mapping[str, Any]],
    selected_marker: str,
    *,
    fields: Sequence[str],
) -> Mapping[str, Any] | None:
    matches = [row for row in rows if marker(row, fields) == selected_marker]
    if len(matches) > 1:
        raise MutationReadbackError(
            "more than one object has the same SDK marker",
            next_action="List the marker matches and remove only confirmed duplicates before retrying.",
        )
    return matches[0] if matches else None


def require_created(
    client: Any,
    operation_id: str,
    selected_marker: str,
    *,
    fields: Sequence[str],
    name: str,
) -> Mapping[str, Any]:
    match = unique_marker(
        catalog(client, operation_id), selected_marker, fields=fields
    )
    if match is None or match.get("name") != name:
        raise MutationReadbackError(
            "created object did not round-trip through its list",
            next_action="Inspect this SDK marker before deciding whether another create is safe.",
        )
    return match


def marker(row: Mapping[str, Any], fields: Sequence[str]) -> str | None:
    for field in fields:
        value = row.get(field)
        if not isinstance(value, str):
            continue
        start = value.find(MARKER_PREFIX)
        if start < 0:
            continue
        candidate = value[start : start + 17]
        if len(candidate) == 17 and all(
            char in "0123456789abcdef" for char in candidate[5:]
        ):
            return candidate
    return None


def require_report_authority(
    client: Any,
    row: Mapping[str, Any],
    *,
    object_kind: str,
    object_id: str,
    marker_fields: Sequence[str],
    field: str,
) -> Any:
    return require_mutation_authority(
        client,
        marker=marker(row, marker_fields),
        owner=create_user_owner(row),
        object_kind=object_kind,
        object_id=object_id,
        field=field,
    )


def preview(
    raw: Mapping[str, Any], *, target: Mapping[str, Any], impact: str
) -> dict[str, Any]:
    return {
        **copy.deepcopy(dict(raw)),
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


def dependent_preview(
    operation_id: str, target: Mapping[str, Any], impact: str
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "preview",
        "operation_id": operation_id,
        "effect": "mutation",
        "offline": True,
        "network_called": False,
        "dry_run": True,
        "confirmation_required": True,
        "target": copy.deepcopy(dict(target)),
        "impact": impact,
        "preconditions": [
            "Read the exact upstream preimage at execution time.",
            "Refuse unless a GSDK marker is present or create_user_id matches the authenticated gravity_id.",
            "Read the complete list after deletion and prove the ID is absent.",
        ],
        "automatic_retry": False,
        "attempts": 0,
        "next_action": "Review the target, then repeat with execute=true or --execute.",
    }


def completed(
    raw_preview: Mapping[str, Any],
    mutation: Mapping[str, Any],
    target: Mapping[str, Any],
    status: str,
    preimage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": status,
        "operation_id": mutation.get("operation_id"),
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


def idempotent(existing: Mapping[str, Any], operation_id: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "already_exists",
        "operation_id": operation_id,
        "effect": "mutation",
        "offline": False,
        "network_called": True,
        "write_sent": False,
        "attempts": 0,
        "idempotent_reuse": True,
        "target": copy.deepcopy(dict(existing)),
        "error": None,
    }


__all__ = [
    "SCHEMA_VERSION", "caller_text", "catalog", "completed", "contract_text",
    "dependent_preview", "detail", "idempotent", "json_text", "marker",
    "marker_in_report", "marker_in_subscription", "optional_caller_text",
    "optional_nonnegative_id", "positive_id", "preview", "require_created",
    "require_report_authority", "response_id", "subscription_report_config",
    "text_sequence", "two_texts", "unique_marker",
]
