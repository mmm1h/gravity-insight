"""Unavailable source-calendar facts shared by Multidim discovery and results."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


SCHEMA_VERSION = "gravity.multidim-source-availability.v1"
GAP_CODE = "MULTIDIM_SOURCE_AVAILABILITY_UNVERIFIED"
_OPERATIONS = frozenset(
    ".".join(("report", "multidim", action)) for action in ("query", "calc_total")
)


def multidim_source_availability() -> dict[str, Any]:
    """Declare only registered facts, independently of rows and fetch/page times."""
    return {
        "schema_version": SCHEMA_VERSION,
        "availability": "unavailable",
        "gap_code": GAP_CODE,
        "source_through": None,
        "native_calendar": None,
        "zero_suppression": "unverified",
        "missing_dates": "unknown_not_zero",
        "source_completeness": "unknown",
        "fetched_at_semantics": "source_fetch_observation_not_source_through",
        "composite_total": {
            "basis": "returned_query_rows",
            "requested_window_completeness": "unverified",
            "empty_query_behavior": "skip_calc_total_and_return_null",
        },
        "allowed_claims": ["returned-scope-observation"],
        "forbidden_claims": [
            "missing-date-as-zero",
            "source-current-through-requested-end",
            "complete-requested-window-spend",
        ],
        "evidence_needed": [
            "verified-source-through-and-native-calendar",
            "verified-zero-suppression-semantics",
        ],
        "remediation": (
            "Keep omitted dates unknown and totals conditional on returned rows. "
            "Register reviewed source-through/native-calendar or zero-suppression "
            "evidence before certifying zero spend or complete requested-window spend."
        ),
    }


def annotate_multidim_availability(value: Mapping[str, Any]) -> dict[str, Any]:
    """Attach the closed declaration without accepting source-provided claims."""
    selected = dict(value)
    operation = selected.get("operation_id")
    if (
        isinstance(operation, str)
        and operation in _OPERATIONS
        and selected.get("schema_version") == "gravity-insight.read.v1"
    ):
        selected["source_availability"] = multidim_source_availability()
    return selected
