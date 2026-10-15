"""Registered unavailable monetary/calendar facts for native behavior ads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


SCHEMA_VERSION = "gravity.behavior-ad-semantics.v1"
GAP_CODE = "BEHAVIOR_AD_MONETARY_CALENDAR_SEMANTICS_UNVERIFIED"
_MULTIDIM = frozenset({"reporting_ad_amount", "reporting_ad_cnt", "reporting_ad_uv", "reporting_ad_ecpm"})
_MONETIZATION = frozenset({"reporting_ad_revenue", "reporting_ad_cnt", "reporting_ad_uv", "reporting_ad_ecpm"})
_FAMILIES = {
    ".".join(("report", "multidim", "query")): ("adreport", _MULTIDIM),
    ".".join(("report", "multidim", "calc_total")): ("adreport", _MULTIDIM),
    ".".join(("report", "get", "query")): ("monetization_report", _MONETIZATION),
}
_FORBIDDEN = (
    "verified-currency-or-monetary-unit", "settled-advertising-cash",
    "verified-ecpm-formula-or-backend-conversion", "exact-financial-calendar-join",
    "cross-family-unrounded-equivalence", "silent-iap-iaa-ledger-combination",
    "sum-grouped-ad-uv-as-overall-unique-users", "missing-date-as-zero",
    "verified-dataset-as-of-or-completed-day",
)


@dataclass(frozen=True)
class BehaviorAdSemantics:
    source_family: str
    metrics: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION, "availability": "unavailable", "gap_code": GAP_CODE,
            "source_family": self.source_family, "metrics": list(self.metrics),
            "monetary_unit": None, "currency": None, "income_formula": None,
            "ecpm_generation_source": None, "backend_conversion": None,
            "underlying_precision": None, "display_precision_role": "formatting_only",
            "settlement_status": "unverified", "native_bucket_timezone": None,
            "native_bucket_calendar": None, "completed_through": None, "dataset_as_of": None,
            "fetched_at_semantics": "source_fetch_observation_not_dataset_as_of",
            "grouped_ad_uv": "non_additive", "missing_dates": "unknown_not_zero",
            "allowed_claims": ["separate-native-estimate-observation-within-returned-scope"],
            "forbidden_claims": list(_FORBIDDEN),
            "source_completeness": "unknown",
            "cross_family_amount_equivalence": "unverified",
        }


def behavior_ad_semantics_catalog() -> dict[str, Any]:
    """The finite declaration contains no invented monetary Semantic Metric."""
    return {
        "schema_version": SCHEMA_VERSION, "gap_code": GAP_CODE,
        "families": [BehaviorAdSemantics(family, tuple(sorted(metrics))).to_dict() for family, metrics in (("adreport", _MULTIDIM), ("monetization_report", _MONETIZATION))],
        "evidence_needed": ["native_currency_unit_and_precision", "formula_and_backend_conversion", "settlement_provenance", "native_bucket_timezone_calendar", "snapshot_as_of_and_completed_day"],
    }


def _scope_from_inputs(operation_id: str, inputs: Mapping[str, Any]) -> BehaviorAdSemantics | None:
    family, allowed = _FAMILIES[operation_id]
    if inputs.get("data_topic", family) != family:
        return None
    metrics = inputs.get("metrics_list")
    if not isinstance(metrics, (list, tuple)) or len(metrics) > 500:
        return None
    selected = tuple(sorted({name for name in metrics if isinstance(name, str) and name in allowed}))
    return BehaviorAdSemantics(family, selected) if selected else None


def project_behavior_ad_semantics(source: Any) -> dict[str, Any] | None:
    """Accept only the exact closed declaration; forged units/claims are dropped."""
    if not isinstance(source, Mapping):
        return None
    operation = source.get("operation_id")
    if not isinstance(operation, str) or operation not in _FAMILIES:
        return None
    value = source.get("behavior_ad_semantics")
    if not isinstance(value, Mapping):
        return None
    family, allowed = _FAMILIES[operation]
    selected = value.get("metrics")
    if not isinstance(selected, (list, tuple)) or not 1 <= len(selected) <= len(allowed):
        return None
    if any(not isinstance(name, str) or name not in allowed for name in selected):
        return None
    expected = BehaviorAdSemantics(family, tuple(sorted(set(selected)))).to_dict()
    return expected if value == expected else None


def annotate_behavior_ad_semantics(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = dict(value)
    operation = selected.get("operation_id")
    if not isinstance(operation, str) or operation not in _FAMILIES or selected.get("schema_version") != "gravity-insight.read.v1":
        return selected
    request = selected.get("request")
    inputs = request.get("inputs") if isinstance(request, Mapping) else None
    if isinstance(inputs, Mapping):
        scope = _scope_from_inputs(operation, inputs)
        boundary = scope.to_dict() if scope is not None else None
    else:
        boundary = project_behavior_ad_semantics(selected)
    selected.pop("behavior_ad_semantics", None)
    if boundary is not None:
        selected["behavior_ad_semantics"] = boundary
    return selected
