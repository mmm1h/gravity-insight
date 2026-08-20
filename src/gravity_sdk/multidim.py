"""Controlled multidimensional request and dynamic-column helpers."""

from __future__ import annotations

from typing import Any, Mapping, MutableSet, Sequence

from . import runtime
from .composite import CompositeService
from .errors import InputValidationError, PolicyViolation
from .multidim_contract import (
    MultidimMultiKeyContract,
    classify_multi_keys,
    malformed_multi_keys_message,
    multidim_horizon_gap_error,
    multidim_multi_key_contract,
)
from .multidim_service import (
    MULTIDIM_QUERY_OPERATION as QUERY_OPERATION,
    MULTIDIM_TOTAL_OPERATION as TOTAL_OPERATION,
)


OPERATIONS = frozenset({QUERY_OPERATION, TOTAL_OPERATION})


def add_cli_query_arguments(
    parser: Any, input_adder: Any, pagination_adder: Any, shortcut_adder: Any
) -> None:
    input_adder(parser)
    pagination_adder(parser)
    parser.add_argument(
        "--include-total",
        action="store_true",
        help="Validate live metric metadata and calculate totals in the same command.",
    )
    shortcut_adder(parser)


def call_cli_read(
    client: Any,
    operation_id: str,
    inputs: Mapping[str, Any],
    *,
    include_total: bool = False,
    read_all: bool = False,
    max_pages: int | None = None,
    max_items: int | None = None,
    max_workers: int | None = None,
) -> Any:
    options = {
        "max_pages": max_pages,
        "max_items": max_items,
        "max_workers": max_workers,
    }
    if include_total:
        return CompositeService(client).multidim_query(
            inputs,
            include_total=True,
            read_all=read_all,
            **{key: value for key, value in options.items() if value is not None},
        )
    return runtime.call_read(
        client,
        operation_id,
        inputs,
        read_all=read_all,
        **options,
    )


def requested_strings(values: Mapping[str, Any], input_names: Sequence[str]) -> set[str]:
    result: set[str] = set()
    for input_name in input_names:
        value = values.get(input_name)
        if isinstance(value, str) and value:
            result.add(value)
        elif isinstance(value, (list, tuple, set)):
            result.update(item for item in value if isinstance(item, str) and item)
    return result


def extend_numeric_suffix_keys(
    allowed: MutableSet[str],
    value: Any,
    values: Mapping[str, Any],
    input_names: Sequence[str],
) -> None:
    bases = requested_strings(values, input_names)
    rows = (value,) if isinstance(value, Mapping) else value
    if not bases or not isinstance(rows, (list, tuple)):
        return
    allowed.update(
        str(key)
        for row in rows
        if isinstance(row, Mapping)
        for key in row
        if _matches_numeric_suffix(str(key), bases)
    )


def projected_keys(
    static_keys: Sequence[str],
    dynamic_inputs: Sequence[str],
    numeric_inputs: Sequence[str],
    values: Mapping[str, Any],
    response_value: Any,
) -> set[str]:
    allowed = set(static_keys) | requested_strings(values, dynamic_inputs)
    extend_numeric_suffix_keys(allowed, response_value, values, numeric_inputs)
    return allowed


def build_request_body(operation_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
    data_conf_value = values.get("data_conf", {})
    if not isinstance(data_conf_value, Mapping):
        raise PolicyViolation("multidimensional data_conf is invalid")
    data_conf = dict(data_conf_value)
    multi_keys = values.get("multi_keys")
    if multi_keys is not None:
        _validate_multi_keys(multi_keys)
        data_conf["multi_keys"] = list(multi_keys)
    body = {
        "time_dims": values.get("time_dims"),
        "date_list": values.get("date_list"),
        "data_dims": values.get("data_dims", []),
        "relate_dims": values.get("relate_dims", []),
        "metrics_list": values.get("metrics_list"),
        "custom_metrics_list": values.get("custom_metrics_list", []),
        "data_conf": data_conf,
        "data_topic": values.get("data_topic", "adreport"),
        "filters": values.get("filters", []),
    }
    if operation_id == QUERY_OPERATION:
        body.update(page=values.get("page", 1), page_size=values.get("page_size", 100))
    elif "data_list" in values:
        body["data_list"] = values["data_list"]
    return body


def parse_multi_days(
    values: Sequence[str] | None,
    contract: MultidimMultiKeyContract | None = None,
) -> list[int] | None:
    if not values:
        return None
    selected_contract = contract or multidim_multi_key_contract()
    try:
        days = [int(item) for item in values]
    except (TypeError, ValueError) as exc:
        raise InputValidationError(
            malformed_multi_keys_message("--multi-days", selected_contract),
            field="multi_days",
            next_action=(
                f"Use {selected_contract.validation_text} and retry."
            ),
        ) from exc
    failure = classify_multi_keys(days, selected_contract)
    if failure == "horizon_gap":
        raise multidim_horizon_gap_error(
            field="multi_days", contract=selected_contract
        )
    if failure is not None:
        raise InputValidationError(
            malformed_multi_keys_message("--multi-days", selected_contract),
            field="multi_days",
            next_action=(
                f"Use {selected_contract.validation_text} and retry."
            ),
        )
    return days


def _matches_numeric_suffix(name: str, bases: set[str]) -> bool:
    for base in bases:
        prefix = f"{base}_"
        suffix = name[len(prefix) :] if name.startswith(prefix) else ""
        if suffix.isdecimal() and not suffix.startswith("0") and int(suffix) <= 365:
            return True
    return False


def _validate_multi_keys(
    value: Any, contract: MultidimMultiKeyContract | None = None
) -> None:
    selected_contract = contract or multidim_multi_key_contract()
    failure = classify_multi_keys(value, selected_contract)
    if failure == "horizon_gap":
        raise multidim_horizon_gap_error(
            field="multi_keys", contract=selected_contract
        )
    if failure is not None:
        raise PolicyViolation(
            malformed_multi_keys_message(
                "multidimensional multi_keys", selected_contract
            )
        )
