"""Contract-derived cohort horizon rules for governed Multidim requests."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import ErrorCategory, GravityInsightError, ManifestError
from ._field_policy_operations import REPORT_MULTIDIM_QUERY, REPORT_MULTIDIM_TOTAL
from .models import load_operation_manifest
from .paths import MANIFEST_ROOT


MULTIDIM_COHORT_HORIZON_GAP_CODE = (
    "MULTIDIM_COHORT_HORIZON_CONTRACT_MISSING"
)
MULTI_KEYS_FIELD = "multi_keys"
QUERY_OPERATION = REPORT_MULTIDIM_QUERY
TOTAL_OPERATION = REPORT_MULTIDIM_TOTAL
_MALFORMED = "malformed"
_HORIZON_GAP = "horizon_gap"


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
    "MultidimCohortHorizonGapError",
    "MultidimMultiKeyContract",
    "classify_multi_keys",
    "malformed_multi_keys_message",
    "multidim_horizon_gap_error",
    "multidim_multi_key_contract",
]
