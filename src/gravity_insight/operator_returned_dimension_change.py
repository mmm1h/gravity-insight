"""Deterministic returned-row comparison built into the Operator Registry."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from .operator_ids import RETURNED_DIMENSION_CHANGE_RESULT_SCHEMA


SCHEMA_VERSION = RETURNED_DIMENSION_CHANGE_RESULT_SCHEMA


class OperatorMethodError(ValueError):
    """Governed input facts violate one stable Operator failure boundary."""

    def __init__(
        self,
        reason_code: str,
        message: str,
        *,
        field: str | None = None,
        next_action: str | None = None,
    ) -> None:
        self.reason_code = reason_code
        self.field = field
        self.next_action = next_action
        super().__init__(message)


@dataclass(frozen=True)
class _Comparison:
    current: Mapping[str, Decimal]
    reference: Mapping[str, Decimal]
    current_slice: Decimal
    reference_slice: Decimal
    current_sum: Decimal
    reference_sum: Decimal
    total_delta: Decimal
    slice_delta: Decimal


def returned_dimension_change(
    *,
    current_rows: Sequence[Mapping[str, Any]],
    reference_rows: Sequence[Mapping[str, Any]],
    selected_key: str,
    selected_current: Any,
    selected_reference: Any,
    current_rows_path: str,
    reference_rows_path: str,
    selected_current_path: str,
    selected_reference_path: str,
    current_step_id: str = "compare_current",
    reference_step_id: str = "compare_reference",
    selected_current_step_id: str = "validate_current",
    selected_reference_step_id: str = "validate_reference",
    metric: str = "ap_cost",
    dimension: str = "click_company",
) -> dict[str, Any]:
    """Compare only explicit returned rows and one cross-checked slice."""

    comparison = _comparison(
        current_rows=current_rows,
        reference_rows=reference_rows,
        selected_key=selected_key,
        selected_current=selected_current,
        selected_reference=selected_reference,
        metric=metric,
        dimension=dimension,
    )
    return {
        **_summary(comparison, selected_key, metric=metric, dimension=dimension),
        "returned_dimension_changes": _dimension_changes(
            comparison.current,
            comparison.reference,
            current_rows=current_rows,
            reference_rows=reference_rows,
            current_rows_path=current_rows_path,
            reference_rows_path=reference_rows_path,
            current_step_id=current_step_id,
            reference_step_id=reference_step_id,
            metric=metric,
            dimension=dimension,
        ),
        "fact_references": _fact_references(
            current_rows=current_rows,
            reference_rows=reference_rows,
            current_rows_path=current_rows_path,
            reference_rows_path=reference_rows_path,
            selected_current_path=selected_current_path,
            selected_reference_path=selected_reference_path,
            current_step_id=current_step_id,
            reference_step_id=reference_step_id,
            selected_current_step_id=selected_current_step_id,
            selected_reference_step_id=selected_reference_step_id,
            metric=metric,
        ),
    }


def _comparison(
    *,
    current_rows: Sequence[Mapping[str, Any]],
    reference_rows: Sequence[Mapping[str, Any]],
    selected_key: str,
    selected_current: Any,
    selected_reference: Any,
    metric: str,
    dimension: str,
) -> _Comparison:
    if not isinstance(selected_key, str) or not selected_key:
        raise OperatorMethodError(
            "OPERATOR_DIMENSION_INVALID", "selected dimension key is missing"
        )
    current = _groups(current_rows, metric=metric, dimension=dimension)
    reference = _groups(reference_rows, metric=metric, dimension=dimension)
    current_slice = _decimal(selected_current)
    reference_slice = _decimal(selected_reference)
    if current.get(selected_key) != current_slice:
        raise OperatorMethodError(
            "OPERATOR_CROSSCHECK_FAILED",
            "selected current value does not match the returned breakdown",
        )
    if reference.get(selected_key) != reference_slice:
        raise OperatorMethodError(
            "OPERATOR_CROSSCHECK_FAILED",
            "selected reference value does not match the returned breakdown",
        )
    current_sum = sum(current.values(), Decimal(0))
    reference_sum = sum(reference.values(), Decimal(0))
    return _Comparison(
        current=current,
        reference=reference,
        current_slice=current_slice,
        reference_slice=reference_slice,
        current_sum=current_sum,
        reference_sum=reference_sum,
        total_delta=current_sum - reference_sum,
        slice_delta=current_slice - reference_slice,
    )


def _summary(
    value: _Comparison, selected_key: str, *, metric: str, dimension: str
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "verdict": _verdict(value),
        "metric": metric,
        "dimension": dimension,
        "current_returned_dimension_sum": _render_decimal(value.current_sum),
        "reference_returned_dimension_sum": _render_decimal(value.reference_sum),
        "returned_sum_absolute_change": _render_decimal(value.total_delta),
        "relative_change_percent": _percentage(value.total_delta, value.reference_sum),
        "selected_slice": selected_key,
        "selected_current": _render_decimal(value.current_slice),
        "selected_reference": _render_decimal(value.reference_slice),
        "selected_absolute_change": _render_decimal(value.slice_delta),
        "selected_share_of_returned_sum_change_percent": _percentage(
            value.slice_delta, value.total_delta
        ),
        "statement": (
            f"The sum of returned {dimension} {metric} rows changed from "
            f"{_render_decimal(value.reference_sum)} to "
            f"{_render_decimal(value.current_sum)} "
            f"({_render_decimal(value.total_delta)}); returned "
            f"{dimension}={selected_key} changed from "
            f"{_render_decimal(value.reference_slice)} to "
            f"{_render_decimal(value.current_slice)} "
            f"({_render_decimal(value.slice_delta)}). This is an observed "
            "association within the cited facts, not a causal attribution."
        ),
    }


def _verdict(value: _Comparison) -> str:
    if value.total_delta >= 0:
        return "no_observed_returned_sum_decrease"
    if value.slice_delta < 0:
        return "selected_slice_moved_with_observed_decrease"
    return "selected_slice_did_not_move_with_observed_decrease"


def _percentage(numerator: Decimal, denominator: Decimal) -> str | None:
    if denominator == 0:
        return None
    return _render_decimal(
        (numerator / denominator * Decimal(100)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    )


def _fact_references(
    *,
    current_rows: Sequence[Mapping[str, Any]],
    reference_rows: Sequence[Mapping[str, Any]],
    current_rows_path: str,
    reference_rows_path: str,
    selected_current_path: str,
    selected_reference_path: str,
    current_step_id: str,
    reference_step_id: str,
    selected_current_step_id: str,
    selected_reference_step_id: str,
    metric: str,
) -> list[dict[str, str]]:
    return [
        *[
            _fact(reference_step_id, reference_rows_path, index, metric)
            for index in range(len(reference_rows))
        ],
        *[
            _fact(current_step_id, current_rows_path, index, metric)
            for index in range(len(current_rows))
        ],
        {"step_id": selected_reference_step_id, "path": selected_reference_path},
        {"step_id": selected_current_step_id, "path": selected_current_path},
    ]


def _groups(
    rows: Sequence[Mapping[str, Any]], *, metric: str, dimension: str
) -> dict[str, Decimal]:
    if not rows:
        raise OperatorMethodError(
            "OPERATOR_SAMPLE_INSUFFICIENT", "returned rows are empty"
        )
    result: dict[str, Decimal] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise OperatorMethodError(
                "OPERATOR_INPUT_INVALID", "returned row is not an object"
            )
        key = row.get(dimension)
        if not isinstance(key, str) or not key or key in result:
            raise OperatorMethodError(
                "OPERATOR_DIMENSION_INVALID",
                "dimension keys are missing or duplicated",
            )
        result[key] = _decimal(row.get(metric))
    return result


def _dimension_changes(
    current: Mapping[str, Decimal],
    reference: Mapping[str, Decimal],
    *,
    current_rows: Sequence[Mapping[str, Any]],
    reference_rows: Sequence[Mapping[str, Any]],
    current_rows_path: str,
    reference_rows_path: str,
    current_step_id: str,
    reference_step_id: str,
    metric: str,
    dimension: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for key in sorted(set(current) & set(reference)):
        current_index = next(
            index
            for index, row in enumerate(current_rows)
            if row[dimension] == key
        )
        reference_index = next(
            index
            for index, row in enumerate(reference_rows)
            if row[dimension] == key
        )
        result.append(
            {
                "key": key,
                "current": _render_decimal(current[key]),
                "reference": _render_decimal(reference[key]),
                "absolute_change": _render_decimal(current[key] - reference[key]),
                "fact_references": [
                    _fact(
                        reference_step_id,
                        reference_rows_path,
                        reference_index,
                        metric,
                    ),
                    _fact(current_step_id, current_rows_path, current_index, metric),
                ],
            }
        )
    return sorted(
        result,
        key=lambda item: abs(Decimal(item["absolute_change"])),
        reverse=True,
    )


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise OperatorMethodError(
            "OPERATOR_NUMERIC_INVALID", "metric value is missing or non-numeric"
        )
    try:
        selected = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise OperatorMethodError(
            "OPERATOR_NUMERIC_INVALID",
            "metric value is missing or non-numeric",
        ) from None
    if not selected.is_finite():
        raise OperatorMethodError(
            "OPERATOR_NUMERIC_INVALID", "metric value is not finite"
        )
    return selected


def _render_decimal(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def _fact(step_id: str, rows_path: str, row: int, field: str) -> dict[str, str]:
    return {"step_id": step_id, "path": f"{rows_path}/{row}/{field}"}


__all__ = [
    "OperatorMethodError",
    "SCHEMA_VERSION",
    "returned_dimension_change",
]
