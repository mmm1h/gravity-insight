"""Opaque links from execution envelopes to durable HTTP receipts."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from .response_drift import merge_response_drifts, normalize_response_drift


SCHEMA_VERSION = "gravity.result-audit.v1"
STORED = "stored"
WRITE_FAILED = "write_failed"
_STORAGE_STATUSES = frozenset({STORED, WRITE_FAILED})
_FACT_POINTERS = {
    "operation_id": frozenset({"/operation_id", "/result/operation_id"}),
    "contract_version": frozenset({"/contract_version", "/result/contract_version"}),
    "evidence_reference": frozenset({"/evidence_reference", "/result/evidence_reference"}),
    "call_bound": frozenset({"/call_bound", "/result/call_bound"}),
}
_FACT_FIELDS = {name: sorted(pointers)[0] for name, pointers in _FACT_POINTERS.items()}
_RETENTION_ROOTS = ("total", "y", "date_to_week", "date_to_month")
_RETENTION_OFFSET_FIELDS = ("values", "values_loss", "percent_values", "percent_values_loss")
_RETENTION_ERROR = "RETENTION_TOTAL_INVALID"
_RETENTION_ACTION_VERSION = "gravity-insight.retention-safe-next-action.v1"
_MAX_RETENTION_ISSUES = 20
_MAX_RETENTION_ACTIONS = 100


def receipt_reference(receipt_id: object, storage_status: str) -> dict[str, str]:
    """Build one value-free reference without exposing storage coordinates."""

    normalized_id = str(receipt_id)
    if not _receipt_id(normalized_id):
        raise ValueError("HTTP receipt reference has an invalid receipt_id")
    if storage_status not in _STORAGE_STATUSES:
        raise ValueError("HTTP receipt reference has an invalid storage_status")
    return {"receipt_id": normalized_id, "storage_status": storage_status}


def add_result_audit(
    value: Mapping[str, Any],
    references: Sequence[Mapping[str, Any]],
    *,
    fact_paths: Mapping[str, str] | None = None,
    response_drift: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Add or merge the independent audit sub-contract without copying facts."""

    selected = _audit_retention_result(dict(value))
    normalized = _references(references)
    current = selected.get("result_audit")
    existing_references: list[dict[str, str]] = []
    existing_paths: dict[str, str] = {}
    existing_drift: dict[str, Any] | None = None
    if current is not None:
        if not isinstance(current, Mapping) or current.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("result envelope has an incompatible result_audit")
        existing_references = _references(current.get("http_receipts", ()))
        existing_paths = _paths(current.get("fact_paths", {}))
        if current.get("response_drift") is not None:
            existing_drift = normalize_response_drift(current["response_drift"])
    paths = {
        **existing_paths,
        **(_paths(fact_paths) if fact_paths is not None else infer_fact_paths(selected)),
    }
    receipts = _deduplicate([*existing_references, *normalized])
    drift = merge_response_drifts((existing_drift, response_drift))
    if not paths and not receipts and drift is None:
        return selected
    selected["result_audit"] = {
        "schema_version": SCHEMA_VERSION,
        "fact_paths": paths,
        "http_receipts": receipts,
        **({"response_drift": drift} if drift is not None else {}),
    }
    return selected


def _audit_retention_result(value: dict[str, Any]) -> dict[str, Any]:
    """Make invalid grouped Retention totals partial without losing group rows."""

    source, request = value.get("source"), value.get("request")
    inputs = request.get("inputs") if isinstance(request, Mapping) else None
    if (
        value.get("schema_version") != "gravity-insight.read.v1"
        or value.get("status") not in {"success", "empty"}
        or not isinstance(source, Mapping)
        or (source.get("domain"), source.get("resource")) != ("analysis", "retention")
        or not isinstance(inputs, Mapping)
        or not isinstance(value.get("data"), Mapping)
    ):
        return value
    data, issues, truncated, invalid_count, undefined_count = _validate_retention_data(
        value["data"], inputs
    )
    if not invalid_count and not undefined_count:
        return value
    value["data"] = data
    warnings = list(value.get("warnings", ()))
    if invalid_count:
        warnings.append(
            "grouped Retention user-count totals failed arithmetic invariants; "
            f"invalid total offsets were replaced with null (count={invalid_count})"
        )
        value.update(ok=False, status="partial", error=_retention_error(issues, truncated))
        action = _retention_next_action(data, inputs, str(value.get("operation_id", "")))
        if action is not None:
            value["next_action"] = action
    if undefined_count:
        warnings.append(
            "Retention rates with init_num=0 are undefined; percentage cells "
            f"were replaced with null (count={undefined_count})"
        )
    value["warnings"] = warnings
    return value


def _validate_retention_data(
    value: Mapping[str, Any], inputs: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, str]], bool, int, int]:
    data = copy.deepcopy(dict(value))
    issues: list[dict[str, str]] = []
    invalid_count = undefined_count = 0
    truncated = False
    check_total = _grouped_user_count_retention(inputs)
    for path, row in _retention_rows(data):
        init_num = _number(row.get("init_num"))
        if init_num == 0:
            undefined_count += _null_undefined_rates(row)
        if not check_total or not _is_total(row) or init_num is None:
            continue
        offsets, evidence = _invalid_offsets(row, init_num)
        if not offsets:
            continue
        invalid_count += len(offsets)
        for offset in offsets:
            _null_offset(row, offset)
        if init_num < 0:
            row["init_num"] = None
        for field, reason in evidence:
            if len(issues) < _MAX_RETENTION_ISSUES:
                issues.append({"field": f"{path}.{field}", "type": reason})
            else:
                truncated = True
    return data, issues, truncated, invalid_count, undefined_count


def _retention_error(issues: list[dict[str, str]], truncated: bool) -> dict[str, Any]:
    return {
        "code": _RETENTION_ERROR,
        "category": "local",
        "message": (
            "The SDK cannot safely project a grouped Retention total because its "
            "user-count numerator and denominator fail arithmetic invariants; "
            "invalid total cells are null and valid group rows remain available."
        ),
        "field": "data.total",
        "retryable": False,
        "retry_after_ms": None,
        "next_action": (
            "Execute the top-level next_action batch when present; it issues one "
            "ungrouped Retention request per observed group value with an exact "
            "first-step event-property equality filter. Consume each result "
            "independently and do not aggregate across groups."
        ),
        "unsupported_items": issues,
        "unsupported_items_truncated": truncated,
    }


def _retention_next_action(
    data: Mapping[str, Any], inputs: Mapping[str, Any], operation_id: str
) -> dict[str, Any] | None:
    source = _retention_action_source(data, inputs)
    if source is None:
        return None
    group, values, query_items, conditions = source
    requests = [
        {
            "operation_id": operation_id,
            "input": _group_query_input(inputs, group, value, query_items, conditions, index),
            "request_id": f"retention-group-{index:03d}",
        }
        for index, value in enumerate(values, start=1)
    ]
    return {
        "schema_version": _RETENTION_ACTION_VERSION,
        "status": "ready",
        "reason_code": _RETENTION_ERROR,
        "action": "execute_independent_group_queries",
        "command": "gravity batch read --input <next_action.input> --concurrency 1",
        "input": {"requests": requests},
        "result_policy": {
            "consume": "each filtered Retention result independently",
            "aggregate_across_groups": False,
            "overlap_union_total": "unsupported",
        },
    }


def _retention_action_source(
    data: Mapping[str, Any], inputs: Mapping[str, Any]
) -> tuple[Mapping[str, Any], list[str], Sequence[Any], Sequence[Any]] | None:
    groups, items = inputs.get("group_by_list"), inputs.get("query_item_list")
    group = _single_event_group(groups)
    values = _group_values(data)
    if (
        _contains_redaction(inputs)
        or group is None
        or not values
        or len(values) > _MAX_RETENTION_ACTIONS
        or not _two_query_items(items)
    ):
        return None
    conditions = items[0].get("conditions", ())
    if not isinstance(conditions, Sequence) or isinstance(conditions, (str, bytes)) or len(conditions) >= 100:
        return None
    query_id = inputs.get("query_id")
    if not isinstance(query_id, str) or len(query_id) != 32 or not query_id[:13].isdigit() or not query_id[13:].isalnum():
        return None
    return group, values, items, conditions


def _group_query_input(
    inputs: Mapping[str, Any],
    group: Mapping[str, Any],
    group_value: str,
    query_items: Sequence[Any],
    conditions: Sequence[Any],
    index: int,
) -> dict[str, Any]:
    result = copy.deepcopy(dict(inputs))
    result["query_id"] = str(inputs["query_id"])[:-4] + f"{index:04X}"
    result["group_by_list"] = [
        copy.deepcopy(item) for item in inputs.get("group_by_list", ()) if _time_group(item)
    ]
    items = copy.deepcopy(list(query_items))
    first = dict(items[0])
    condition: dict[str, Any] = {
        "operator": "EQUALS", "field": group["field"],
        "type": group["type"], "value": [group_value],
    }
    table = group.get("dim_using_table_name")
    if isinstance(table, str) and table:
        condition["dim_using_table_name"] = table
    first["conditions"] = [*copy.deepcopy(list(conditions)), condition]
    items[0] = first
    result["query_item_list"] = items
    return result


def _grouped_user_count_retention(inputs: Mapping[str, Any]) -> bool:
    groups, items = inputs.get("group_by_list"), inputs.get("query_item_list")
    return (
        isinstance(groups, Sequence)
        and not isinstance(groups, (str, bytes))
        and any(isinstance(item, Mapping) and not _time_group(item) for item in groups)
        and _two_query_items(items)
        and inputs.get("period_calc_method", "SUM") == "SUM"
        and inputs.get("custom_before_method", "SUM") == "SUM"
        and inputs.get("total_calc_type", "DAY") == "DAY"
        and inputs.get("query_item_before_after") in (None, {})
        and all(_user_count_step(item) for item in items)
    )


def _two_query_items(value: Any) -> bool:
    return (
        isinstance(value, Sequence) and not isinstance(value, (str, bytes))
        and len(value) == 2 and isinstance(value[0], Mapping)
    )


def _user_count_step(value: Any) -> bool:
    target = value.get("target") if isinstance(value, Mapping) else None
    return isinstance(target, Mapping) and (
        target.get("name"), target.get("field")
    ) == ("PresetUserCount", "PresetUserCount")


def _retention_rows(value: Mapping[str, Any]):
    for root in _RETENTION_ROOTS:
        if root in value:
            yield from _walk_retention_rows(value[root], f"data.{root}")


def _walk_retention_rows(value: Any, path: str):
    if isinstance(value, dict):
        if "init_num" in value and "is_total" in value:
            yield path, value
            return
        for key, item in value.items():
            yield from _walk_retention_rows(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_retention_rows(item, f"{path}[{index}]")


def _invalid_offsets(row: Mapping[str, Any], init_num: Decimal) -> tuple[set[int], list[tuple[str, str]]]:
    offsets: set[int] = set()
    evidence: list[tuple[str, str]] = []
    if init_num < 0:
        offsets.update(range(max(1, _offset_count(row))))
        evidence.append(("init_num", "negative_denominator"))
    for index, value in _numbers(row.get("values")):
        if value < 0:
            offsets.add(index); evidence.append((f"values[{index}]", "negative_numerator"))
        elif value > init_num:
            offsets.add(index); evidence.append((f"values[{index}]", "numerator_exceeds_denominator"))
    for index, value in _numbers(row.get("values_loss")):
        if value < 0 or value > init_num:
            offsets.add(index); evidence.append((f"values_loss[{index}]", "loss_count_out_of_range"))
    for field in ("percent_values", "percent_values_loss"):
        for index, value in _percentages(row.get(field)):
            if not 0 <= value <= 100:
                reason = "retention_percent_out_of_range" if field == "percent_values" else "loss_percent_out_of_range"
                offsets.add(index); evidence.append((f"{field}[{index}]", reason))
    return offsets, evidence


def _null_undefined_rates(row: dict[str, Any]) -> int:
    count = 0
    for field in ("percent_values", "percent_values_loss"):
        values = row.get(field)
        if isinstance(values, list):
            for index, value in enumerate(values):
                if value is not None:
                    values[index] = None; count += 1
    return count


def _null_offset(row: dict[str, Any], offset: int) -> None:
    for field in _RETENTION_OFFSET_FIELDS:
        values = row.get(field)
        if isinstance(values, list) and offset < len(values):
            values[offset] = None


def _offset_count(row: Mapping[str, Any]) -> int:
    return max((len(value) for field in _RETENTION_OFFSET_FIELDS if isinstance((value := row.get(field)), list)), default=0)


def _numbers(value: Any):
    if isinstance(value, list):
        for index, item in enumerate(value):
            number = _number(item)
            if number is not None:
                yield index, number


def _percentages(value: Any):
    if isinstance(value, list):
        for index, item in enumerate(value):
            rendered = item.strip()[:-1] if isinstance(item, str) and item.strip().endswith("%") else item
            number = _number(rendered)
            if number is not None:
                yield index, number


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _is_total(row: Mapping[str, Any]) -> bool:
    return row.get("is_total") is True or row.get("is_total") == 1


def _time_group(value: Any) -> bool:
    return (
        isinstance(value, Mapping) and value.get("field") == "create_time"
        and value.get("type") in {"event", "default_event", "default"}
    )


def _single_event_group(value: Any) -> Mapping[str, Any] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    groups = [item for item in value if isinstance(item, Mapping) and not _time_group(item)]
    if len(groups) != 1:
        return None
    group = groups[0]
    if (
        group.get("type") != "event" or not isinstance(group.get("field"), str)
        or not group["field"] or group.get("group_by") != group["field"]
        or group.get("operator") not in (None, "") or group.get("values") not in (None, (), [])
    ):
        return None
    return group


def _group_values(data: Mapping[str, Any]) -> list[str]:
    result: list[str] = []
    for _path, row in _retention_rows(data):
        values = row.get("group_cols")
        if (
            not _is_total(row) and isinstance(values, list) and len(values) == 1
            and isinstance(values[0], str) and values[0] and values[0] != "[REDACTED]"
            and values[0] not in result
        ):
            result.append(values[0])
    return result


def _contains_redaction(value: Any) -> bool:
    if value == "[REDACTED]":
        return True
    if isinstance(value, Mapping):
        return any(_contains_redaction(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_redaction(item) for item in value)
    return False


def infer_fact_paths(value: Mapping[str, Any]) -> dict[str, str]:
    """Point at existing stable facts; their values deliberately stay in place."""

    return {
        name: pointer
        for name, pointer in _FACT_FIELDS.items()
        if name in value
    }


def error_receipt_references(error: BaseException) -> list[dict[str, str]]:
    raw = getattr(error, "http_receipt_references", ())
    try:
        return _references(raw)
    except ValueError:
        return []


def result_receipt_references(value: object) -> list[dict[str, str]]:
    if not isinstance(value, Mapping):
        return []
    audit = value.get("result_audit")
    if not isinstance(audit, Mapping) or audit.get("schema_version") != SCHEMA_VERSION:
        return []
    try:
        return _references(audit.get("http_receipts", ()))
    except ValueError:
        return []


def result_response_drift(value: object) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    audit = value.get("result_audit")
    if not isinstance(audit, Mapping) or audit.get("schema_version") != SCHEMA_VERSION:
        return None
    drift = audit.get("response_drift")
    if drift is None:
        return None
    try:
        return normalize_response_drift(drift)
    except ValueError:
        return None


def project_result_audit(
    target: Mapping[str, Any], source: object
) -> dict[str, Any]:
    """Carry only receipt references through a safe result reconstruction."""

    references = (
        error_receipt_references(source)
        if isinstance(source, BaseException)
        else result_receipt_references(source)
    )
    if isinstance(source, Mapping):
        references.extend(result_receipt_references(source.get("data")))
        references.extend(result_receipt_references(source.get("result")))
    drifts = [result_response_drift(source)]
    if isinstance(source, Mapping):
        drifts.extend(
            (
                result_response_drift(source.get("data")),
                result_response_drift(source.get("result")),
            )
        )
    return add_result_audit(
        target,
        references,
        response_drift=merge_response_drifts(drifts),
    )


def aggregate_result_audit(
    target: Mapping[str, Any], sources: Sequence[object]
) -> dict[str, Any]:
    """Aggregate opaque references while inferring facts only from the target."""

    selected = dict(target)
    for source in sources:
        selected = project_result_audit(selected, source)
    return selected


def bind_error_receipts(
    error: BaseException, references: Sequence[Mapping[str, Any]]
) -> None:
    """Carry completed-response facts across a later local processing error."""

    normalized = _references(references)
    if not normalized:
        return
    current = error_receipt_references(error)
    try:
        setattr(error, "http_receipt_references", tuple(_deduplicate([*current, *normalized])))
    except Exception:
        pass


def _references(value: object) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("http_receipts must be an array")
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"receipt_id", "storage_status"}:
            raise ValueError("HTTP receipt reference has unsupported fields")
        result.append(receipt_reference(item["receipt_id"], str(item["storage_status"])))
    return _deduplicate(result)


def _paths(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("result audit fact_paths must be an object")
    result: dict[str, str] = {}
    for name, pointer in value.items():
        if name not in _FACT_POINTERS or pointer not in _FACT_POINTERS[name]:
            raise ValueError("result audit fact_paths contains an unsupported pointer")
        result[str(name)] = str(pointer)
    return result


def _deduplicate(values: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        receipt_id = value["receipt_id"]
        if receipt_id in seen:
            continue
        seen.add(receipt_id)
        result.append(dict(value))
    return result


def _receipt_id(value: str) -> bool:
    return len(value) == 32 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "SCHEMA_VERSION",
    "STORED",
    "WRITE_FAILED",
    "add_result_audit",
    "bind_error_receipts",
    "error_receipt_references",
    "infer_fact_paths",
    "aggregate_result_audit",
    "project_result_audit",
    "receipt_reference",
    "result_receipt_references",
    "result_response_drift",
]
