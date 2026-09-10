"""Aggregate-only result and bounded scan receipts for material game performance."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from typing import Any

from .contracts.envelope_obligations import (
    CompletenessState,
    DataCompleteness,
    DiagnosticEvidence,
    DiagnosticState,
    EnvelopeObligations,
    ExecutionState,
    ExecutionStatus,
    MutationCertainty,
    MutationState,
    SemanticState,
    SemanticValidity,
    serialize_envelope,
)
from .errors import ContractChangedError, GravityInsightError, exit_code_for_category
from .material_game_contract import METHOD, SCHEMA_VERSION
from .result_audit import add_result_audit
from .result_source import GOVERNED_PRODUCT, result_source


def gap(code: str, action: str) -> dict[str, Any]:
    return {"status": "unavailable", "value": None, "reason": code, "next_action": action}


def safe_failure(exc: GravityInsightError) -> dict[str, Any]:
    detail = exc.to_error_detail()
    return {
        **gap(
            detail.code, "Inspect the source contract and retry only when its classified cause is resolved."
        ),
        "error": {
            "code": detail.code,
            "category": detail.category,
            "retryable": detail.retryable,
            "message": "The bounded source read failed.",
        },
    }


def scan_receipt(native: Mapping[str, Any], *, max_pages: int, max_items: int) -> dict[str, Any]:
    page = native.get("page")
    if not isinstance(page, Mapping):
        raise ContractChangedError("bounded source pagination receipt is missing")
    pages, items = page.get("pages_fetched"), page.get("item_count")
    if (
        type(pages) is not int
        or not 1 <= pages <= max_pages
        or type(items) is not int
        or not 0 <= items <= max_items
    ):
        raise ContractChangedError("bounded source pagination usage is invalid")
    total, has_more, completeness, next_page = _scan_position(native, page, pages)
    return {
        "pages_scanned": pages,
        "items_scanned": items,
        "last_page": pages,
        "next_page": next_page,
        "total_pages": total,
        "remaining_pages": max(0, total - pages) if total is not None else None,
        "has_more": has_more,
        "completeness": completeness,
        "pagination_finished": has_more is False,
    }


def envelope(
    request: Mapping[str, Any],
    materials: list[dict[str, Any]],
    report_scan: Any,
    days: list[dict[str, Any]],
    budget: Mapping[str, Any],
    receipts: list[dict[str, Any]],
) -> dict[str, Any]:
    prefix = (report_scan is not None and not report_scan["pagination_finished"]) or budget[
        "remaining_days"
    ] > 0
    prefix = prefix or any(day.get("scan") and not day["scan"]["pagination_finished"] for day in days)
    codes = tuple(
        sorted(
            {
                "DISTINCT_USER_POPULATION_UNPROVEN",
                "SOURCE_COMPLETENESS_UNPROVEN",
                "RETENTION_UNAVAILABLE",
                "USER_PLATFORM_SCOPE_UNPROVEN",
            }
        )
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": "partial" if days or report_scan else "unavailable",
        "exit_code": exit_code_for_category("upstream"),
        "scope": {"app_id": request["app_id"], "report_window": dict(request["window"])},
        "metric_binding_digests": {
            name: hashlib.sha256(
                json.dumps(measure, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
            ).hexdigest()
            for name, measure in request["metrics"].items()
        },
        "platform": request["platform"],
        "object_type": request["object_type"],
        "method": dict(METHOD),
        "materials": materials,
        "report_scan": report_scan,
        "days": [{key: value for key, value in day.items() if key != "cells"} for day in days],
        "budget": dict(budget),
        "error": None,
        "claims": {
            "allowed": ["diagnostic_same_id_acquisition_row_counts", "per_metric_availability"],
            "forbidden": [
                "complete_distinct_new_user_total",
                "platform_scoped_user_counts_or_game_metrics",
                "ad_registration_reconciliation",
                "proven_delivery_window",
                "mature_retention",
                "causal_ad_quality",
            ],
        },
    }
    obligations = EnvelopeObligations(
        ExecutionStatus(
            ExecutionState.PARTIAL if days or report_scan else ExecutionState.NOT_STARTED,
            "MATERIAL_GAME_COMPONENT_GAPS",
        ),
        DataCompleteness(
            CompletenessState.PREFIX if prefix else CompletenessState.UNKNOWN, "SOURCE_COMPLETENESS_UNPROVEN"
        ),
        SemanticValidity(SemanticState.UNKNOWN, codes),
        DiagnosticEvidence(DiagnosticState.INCOMPLETE, codes),
        MutationCertainty(MutationState.NOT_APPLICABLE, "READ_ONLY"),
    )
    return add_result_audit(serialize_envelope(payload, obligations), receipts)


def _scan_total(page: Mapping[str, Any], pages: int) -> int | None:
    total = page.get("total_pages")
    empty = pages == 1 and total == 0 and page.get("item_count") == 0 and page.get("has_more") is False
    if total is not None and (type(total) is not int or (total < pages and not empty)):
        raise ContractChangedError("bounded source total page count is invalid")
    return total


def _scan_position(native: Mapping[str, Any], page: Mapping[str, Any], pages: int) -> tuple[Any, ...]:
    total = _scan_total(page, pages)
    has_more = page.get("has_more")
    if has_more is not None and type(has_more) is not bool:
        raise ContractChangedError("bounded source has_more is invalid")
    completeness = native.get("completeness")
    if completeness not in {"complete", "prefix", "unknown"}:
        raise ContractChangedError("bounded source completeness is invalid")
    next_input = native.get("next_page_input")
    next_page = next_input.get("page") if isinstance(next_input, Mapping) else None
    if next_page is not None and (type(next_page) is not int or next_page != pages + 1):
        raise ContractChangedError("bounded source continuation is invalid")
    if (has_more is True and next_page is None) or (next_page is not None and has_more is not True):
        raise ContractChangedError("bounded source continuation contradicts has_more")
    return total, has_more, completeness, next_page
