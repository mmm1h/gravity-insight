"""Contract-derived cohort horizon rules for governed Multidim requests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, NoReturn

from .errors import (
    ErrorCategory,
    GravityInsightError,
    InputValidationError,
    ManifestError,
)
from ._field_policy_operations import (
    ANALYSIS_RETENTION_QUERY,
    REPORT_MULTIDIM_QUERY,
    REPORT_MULTIDIM_TOTAL,
)
from .models import load_operation_manifest
from .paths import MANIFEST_ROOT


MULTIDIM_COHORT_HORIZON_GAP_CODE = (
    "MULTIDIM_COHORT_HORIZON_CONTRACT_MISSING"
)
STANDARD_RETENTION_DENOMINATOR_GAP_CODE = (
    "STANDARD_RETENTION_DENOMINATOR_COHORT_RULE_UNVERIFIED"
)
STANDARD_RETENTION_DENOMINATOR_SCHEMA_VERSION = (
    "gravity.retention-denominator-reconciliation.v1"
)
MULTI_KEYS_FIELD = "multi_keys"
QUERY_OPERATION = REPORT_MULTIDIM_QUERY
TOTAL_OPERATION = REPORT_MULTIDIM_TOTAL
_MALFORMED = "malformed"
_HORIZON_GAP = "horizon_gap"
_READING_FIELDS = frozenset({"status", "value", "fetched_at"})
_READING_STATUSES = frozenset(
    {
        "success",
        "empty",
        "partial",
        "error",
        "contract_changed",
        "capability_gap",
        "unknown",
    }
)
_MAX_DENOMINATOR = 9_223_372_036_854_775_807
_STANDARD_DENOMINATOR_GAP_REASON = (
    "registered contracts and sanitized probe evidence establish the two aggregate "
    "field paths but do not define standard_activate_cnt cohort inclusion, exclusion, "
    "time-boundary, attribution, or late-event rules, so equality cannot establish "
    f"semantic equivalence with {ANALYSIS_RETENTION_QUERY} init_num"
)
_STANDARD_DENOMINATOR_NEXT_ACTION = (
    "Add one reviewed, sanitized evidence artifact that binds report.multidim.query "
    "standard_activate_cnt to its exact source event, inclusion and exclusion rules, "
    "cohort timezone/day boundary, acquisition attribution or re-attribution, and "
    "late-event/backfill behavior; then register that definition in a Semantic contract "
    "and rerun compiler, projection/privacy, and denominator-reconciliation gates."
)


@dataclass(frozen=True)
class MultidimMultiKeyContract:
    values: tuple[int, ...]
    min_items: int
    max_items: int

    @property
    def minimum(self) -> int:
        return self.values[0]

    @property
    def maximum(self) -> int:
        return self.values[-1]

    @property
    def contiguous(self) -> bool:
        return self.values == tuple(range(self.minimum, self.maximum + 1))

    @property
    def allowed_text(self) -> str:
        if self.contiguous:
            return f"{self.minimum} to {self.maximum}"
        return ", ".join(str(value) for value in self.values)

    @property
    def validation_text(self) -> str:
        if self.contiguous:
            return f"unique ascending integers from {self.allowed_text}"
        return f"unique ascending integers from the registered set {self.allowed_text}"

    @property
    def cli_help(self) -> str:
        return (
            "Comma-separated cohort observation days; must be "
            f"{self.validation_text}. Values come from the compiled "
            f"{QUERY_OPERATION} input_fields.multi_keys.item_enum contract."
        )

    @property
    def reason(self) -> str:
        return (
            "Registered Multidim contracts enumerate cohort observation windows "
            f"from D{self.minimum} through D{self.maximum} only; no governed route "
            f"currently observes after D{self.maximum} while preserving "
            "acquisition-cohort cumulative revenue, payer-retention denominator, "
            "and activation ARPU semantics."
        )

    @property
    def next_action(self) -> str:
        return (
            "Obtain sanitized production or direct-wire evidence that "
            f"{QUERY_OPERATION} and {TOTAL_OPERATION} accept post-D{self.maximum} "
            "multi_keys for the same metrics, then update the source operation "
            "contracts, recompile manifests, and re-run projection/privacy and "
            "semantic regression gates; do not substitute generic event retention."
        )


class MultidimCohortHorizonGapError(GravityInsightError):
    """A coherent request exceeds the horizons in the governed contracts."""

    code = MULTIDIM_COHORT_HORIZON_GAP_CODE
    category = ErrorCategory.LOCAL
    retryable = False


def multidim_multi_key_contract(
    operations: Sequence[Any] | None = None,
) -> MultidimMultiKeyContract:
    """Read and reconcile the query/total rules from the compiled report manifest."""

    loaded = (
        tuple(load_operation_manifest(MANIFEST_ROOT / "report.json"))
        if operations is None
        else tuple(operations)
    )
    selected = {
        operation.operation_id: operation.schema()
        for operation in loaded
        if getattr(operation, "operation_id", None)
        in {QUERY_OPERATION, TOTAL_OPERATION}
    }
    missing = {QUERY_OPERATION, TOTAL_OPERATION} - set(selected)
    if missing:
        raise ManifestError(
            "compiled report manifest is missing a governed Multidim horizon contract"
        )
    query = _multi_key_contract(selected[QUERY_OPERATION])
    total = _multi_key_contract(selected[TOTAL_OPERATION])
    if query != total:
        raise ManifestError(
            "compiled Multidim query and total multi_keys contracts disagree"
        )
    return query


def classify_multi_keys(
    value: Any, contract: MultidimMultiKeyContract
) -> str | None:
    """Separate malformed inputs from coherent post-contract horizon requests."""

    if not isinstance(value, (list, tuple)):
        return _MALFORMED
    selected = list(value)
    if not contract.min_items <= len(selected) <= contract.max_items:
        return _MALFORMED
    if any(not isinstance(item, int) or isinstance(item, bool) for item in selected):
        return _MALFORMED
    if len(set(selected)) != len(selected) or selected != sorted(selected):
        return _MALFORMED
    allowed = frozenset(contract.values)
    if any(
        item < contract.minimum
        or (item <= contract.maximum and item not in allowed)
        for item in selected
    ):
        return _MALFORMED
    if any(item > contract.maximum for item in selected):
        return _HORIZON_GAP
    return None


def multidim_horizon_gap_error(
    *,
    field: str,
    contract: MultidimMultiKeyContract | None = None,
) -> MultidimCohortHorizonGapError:
    selected = contract or multidim_multi_key_contract()
    return MultidimCohortHorizonGapError(
        selected.reason,
        field=field,
        next_action=selected.next_action,
    )


def malformed_multi_keys_message(
    subject: str, contract: MultidimMultiKeyContract
) -> str:
    return f"{subject} must be {contract.validation_text}"


def standard_retention_denominator_gap() -> dict[str, Any]:
    """Return the named gap while the native cohort rule remains unproven."""

    return {
        "kind": "capability_gap",
        "code": STANDARD_RETENTION_DENOMINATOR_GAP_CODE,
        "journey": "standard_retention_denominator_reconciliation",
        "query": "standard_activate_cnt versus init_num ordinary retention denominator",
        "reason": _STANDARD_DENOMINATOR_GAP_REASON,
        "next_action": _STANDARD_DENOMINATOR_NEXT_ACTION,
        "weak_matches": [],
        "network_called": False,
    }


def reconcile_standard_retention_denominators(
    *,
    cohort_date: str,
    offset: int,
    multidim: Mapping[str, Any],
    analysis: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare two already-fetched aggregate denominators without doing I/O."""

    selected_date = _cohort_date(cohort_date)
    selected_offset = _offset(offset)
    sources = {
        "multidim": _denominator_reading(
            multidim,
            "multidim",
            operation_id=QUERY_OPERATION,
            field="standard_activate_cnt",
        ),
        "analysis": _denominator_reading(
            analysis,
            "analysis",
            operation_id=ANALYSIS_RETENTION_QUERY,
            field="init_num",
        ),
    }
    status, cohort_status, drift, reason_codes = _denominator_comparison(sources)
    return {
        "schema_version": STANDARD_RETENTION_DENOMINATOR_SCHEMA_VERSION,
        "kind": "retention_denominator_reconciliation",
        "status": status,
        "cohort_status": cohort_status,
        "cohort_date": selected_date,
        "offset": selected_offset,
        "sources": sources,
        "drift": drift,
        "drift_expression": "standard_activate_cnt - init_num",
        "comparison_basis": "reported_aggregate_values_only",
        "semantic_equivalence": "unknown",
        "reason_codes": reason_codes,
        "capability_gap": standard_retention_denominator_gap(),
        "privacy": {
            "classification": "aggregate_only",
            "contains_user_or_device_rows": False,
        },
        "network_called": False,
    }


def _denominator_reading(
    value: Mapping[str, Any],
    name: str,
    *,
    operation_id: str,
    field: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _denominator_input_error(f"{name} must be an object", name)
    unknown = sorted(set(value) - _READING_FIELDS)
    if unknown:
        _denominator_input_error(
            f"{name} contains fields outside the aggregate reading contract: "
            f"{', '.join(unknown)}",
            name,
        )
    status = value.get("status")
    if status not in _READING_STATUSES:
        _denominator_input_error(
            f"{name}.status must be a registered source status",
            f"{name}.status",
        )
    count = value.get("value")
    if count is not None and (
        type(count) is not int or not 0 <= count <= _MAX_DENOMINATOR
    ):
        _denominator_input_error(
            f"{name}.value must be a non-negative 64-bit integer or null",
            f"{name}.value",
        )
    if status == "empty" and count is not None:
        _denominator_input_error(
            f"{name}.value must be null when status is empty",
            f"{name}.value",
        )
    return {
        "operation_id": operation_id,
        "field": field,
        "status": status,
        "value_present": count is not None,
        "value": count,
        "fetched_at": _fetched_at(value.get("fetched_at"), f"{name}.fetched_at"),
    }


def _denominator_comparison(
    sources: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str, int | None, list[str]]:
    multidim, analysis = sources["multidim"], sources["analysis"]
    if multidim["status"] == analysis["status"] == "empty":
        return "unknown", "empty", None, ["EMPTY_COHORT"]
    if multidim["status"] != "success" or analysis["status"] != "success":
        return "unknown", "unknown", None, ["SOURCE_STATUS_NOT_COMPARABLE"]
    if not multidim["value_present"] or not analysis["value_present"]:
        return "unknown", "unknown", None, ["DENOMINATOR_VALUE_MISSING"]
    drift = multidim["value"] - analysis["value"]
    return (
        "match" if drift == 0 else "drift",
        "observed",
        drift,
        [],
    )


def _cohort_date(value: Any) -> str:
    try:
        parsed = date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        parsed = None
    if parsed is None or parsed.isoformat() != value:
        _denominator_input_error(
            "cohort_date must be an ISO calendar date in YYYY-MM-DD form",
            "cohort_date",
        )
    return value


def _offset(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 3_650:
        _denominator_input_error(
            "offset must be an integer from 0 through 3650",
            "offset",
        )
    return value


def _fetched_at(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        _denominator_input_error(
            f"{field} must be a timezone-aware ISO timestamp",
            field,
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None or parsed.utcoffset() is None:
        _denominator_input_error(
            f"{field} must be a timezone-aware ISO timestamp",
            field,
        )
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _denominator_input_error(message: str, field: str) -> NoReturn:
    raise InputValidationError(
        message,
        field=field,
        next_action=(
            "Pass only status, aggregate value, and fetched_at for each source to "
            "reconcile_standard_retention_denominators; do not pass raw rows."
        ),
    )


def _multi_key_contract(operation: Mapping[str, Any]) -> MultidimMultiKeyContract:
    input_fields = operation.get("input_fields")
    field = input_fields.get(MULTI_KEYS_FIELD) if isinstance(input_fields, Mapping) else None
    if not isinstance(field, Mapping):
        raise ManifestError("compiled Multidim contract is missing input_fields.multi_keys")
    values = field.get("item_enum")
    min_items = field.get("min_items")
    max_items = field.get("max_items")
    if (
        field.get("type") != "array"
        or field.get("item_type") != "integer"
        or not _valid_item_enum(values)
        or not _valid_item_bounds(min_items, max_items)
    ):
        raise ManifestError(
            "compiled Multidim multi_keys contract must declare a bounded integer item_enum"
        )
    return MultidimMultiKeyContract(tuple(values), min_items, max_items)


def _valid_item_enum(values: Any) -> bool:
    return (
        isinstance(values, list)
        and bool(values)
        and all(isinstance(value, int) and not isinstance(value, bool) for value in values)
        and values == sorted(set(values))
    )


def _valid_item_bounds(min_items: Any, max_items: Any) -> bool:
    return (
        isinstance(min_items, int)
        and not isinstance(min_items, bool)
        and isinstance(max_items, int)
        and not isinstance(max_items, bool)
        and 1 <= min_items <= max_items
    )


__all__ = [
    "MULTIDIM_COHORT_HORIZON_GAP_CODE",
    "STANDARD_RETENTION_DENOMINATOR_GAP_CODE",
    "STANDARD_RETENTION_DENOMINATOR_SCHEMA_VERSION",
    "MultidimCohortHorizonGapError",
    "MultidimMultiKeyContract",
    "classify_multi_keys",
    "malformed_multi_keys_message",
    "multidim_horizon_gap_error",
    "multidim_multi_key_contract",
    "reconcile_standard_retention_denominators",
    "standard_retention_denominator_gap",
]
