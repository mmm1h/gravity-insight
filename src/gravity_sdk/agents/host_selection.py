"""Strict host product-selection contract and repository-owned resolution."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .host_catalog import (
    MAX_CANDIDATES,
    SELECTION_SCHEMA_VERSION,
    host_catalog_sources,
    host_product_catalog,
)
from .discovery_support import catalog_browse_next
from ..errors import InputValidationError
from ..host_effect_sources import (
    SOURCE_SCHEMA_VERSION,
    add_violation,
    expect_sdk_source,
    source_for_plan,
    source_value,
)


RECOGNIZER_ROUTING_MODE = "recognizer"
HOST_ROUTING_MODE = "host_catalog"
ROUTING_MODES = (RECOGNIZER_ROUTING_MODE, HOST_ROUTING_MODE)
DEFAULT_ROUTING_MODE = RECOGNIZER_ROUTING_MODE
EMPTY_SELECTION_GAP = "HOST_PRODUCT_SELECTION_EMPTY"

_RESPONSE_FIELDS = frozenset(
    {"schema_version", "catalog_sha256", "query", "decision", "reason", "candidates"}
)
_REASON_FIELDS = frozenset({"summary", "needs_clarification"})
_CANDIDATE_FIELDS = frozenset({"catalog_ref", "reason"})
_CANDIDATE_REASON_FIELDS = frozenset({"goal_match", "boundary_check"})


def add_host_routing_arguments(command: Any) -> None:
    """Register the explicit host arm while leaving recognizer as the default."""

    command.add_argument(
        "--routing",
        choices=ROUTING_MODES,
        default=DEFAULT_ROUTING_MODE,
        help=(
            "Discovery router (default: recognizer floor). Prefer host_catalog "
            "when the caller can emit gravity.host-product-selection.v1; "
            "host_catalog consumes that selection without invoking a model."
        ),
    )
    command.add_argument(
        "--host-selection",
        help=(
            "Inline JSON, file, or '-' containing gravity.host-product-selection.v1; "
            "valid only with --routing host_catalog."
        ),
    )


def host_routing_command(args: Any, client: Any) -> dict[str, Any] | None:
    """Resolve the explicit CLI host arm, or return None for the recognizer."""

    routing = str(getattr(args, "routing", DEFAULT_ROUTING_MODE))
    selection = getattr(args, "host_selection", None)
    if routing == HOST_ROUTING_MODE:
        from ..find_input import load_json_input

        return resolve_host_product_selection(
            str(args.query or ""), load_json_input(selection, required=True), client
        )
    _validate_routing_inputs(routing, selection)
    return None


def host_routing_discovery(
    query: str | None,
    client: Any,
    *,
    routing: str,
    host_selection: Any,
    workspace: Any | None,
    plan_node_namespace: str | None,
) -> dict[str, Any] | None:
    """Resolve the explicit SDK host arm, or return None for the recognizer."""

    if routing == HOST_ROUTING_MODE:
        return resolve_host_product_selection(
            str(query or ""), host_selection, client, workspace=workspace,
            plan_node_namespace=plan_node_namespace,
        )
    _validate_routing_inputs(routing, host_selection)
    return None


def _validate_routing_inputs(routing: str, selection: Any) -> None:
    if routing != RECOGNIZER_ROUTING_MODE or selection is not None:
        raise InputValidationError(
            "actual value: invalid Agent routing inputs; allowed value: recognizer "
            "without host_selection, or host_catalog with one complete selection",
            field="routing",
            next_action=(
                "Use recognizer as the offline floor when the caller cannot emit "
                "a selection, or fetch the host catalog and pass its exact "
                "selection with host_catalog routing."
            ),
        )


def assess_host_product_selection(
    query: str,
    response: Any,
    client: Any,
) -> dict[str, Any]:
    """Validate one complete host response without guessing or partially parsing."""

    catalog = host_product_catalog(client)
    sources = host_catalog_sources(catalog)
    entries = {str(item["catalog_ref"]): item for item in catalog["entries"]}
    violations: list[dict[str, str]] = []
    selected = _response_mapping(response, violations)
    _validate_response_binding(query, selected, catalog, violations)
    candidates = _candidate_rows(selected.get("candidates"), violations)
    refs = _resolve_catalog_refs(candidates, sources, entries, violations)
    _validate_decision(selected.get("decision"), len(candidates), violations)
    _validate_summary_reason(selected.get("reason"), violations)
    return {
        "schema_version": "gravity.host-product-selection-assessment.v1",
        "allowed": not violations,
        "catalog_sha256": catalog["catalog_sha256"],
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "selected_catalog_refs": sorted(refs),
        "violations": violations,
    }


def compile_host_product_selection(
    query: str,
    response: Any,
    client: Any,
) -> dict[str, Any]:
    """Fail closed and return catalog identities controlled by sdk_contract sources."""

    report = assess_host_product_selection(query, response, client)
    if not report["allowed"]:
        first = report["violations"][0]
        field = str(first["field"])
        codes = ", ".join(item["code"] for item in report["violations"][:8])
        raise InputValidationError(
            "actual value: malformed, stale, or non-catalog host product selection "
            f"({codes}); allowed value: one complete gravity.host-product-selection.v1 "
            "object whose catalog_ref values come from the current SDK catalog",
            field=field,
            next_action=(
                f"Fix field={field} ({first['code']}). Fetch gravity "
                "agent-catalog host again, copy selection_template, and submit "
                "the complete response without adding operation, path, tool, or "
                "Plan control fields."
            ),
            code="HOST_SELECTION_REJECTED",
        )
    return {
        "schema_version": "gravity.host-product-selection-compiled.v1",
        "catalog_sha256": report["catalog_sha256"],
        "selected_catalog_refs": report["selected_catalog_refs"],
        "source_boundary": "gravity.host-source.v1 sdk_contract/instruction",
        "source_schema_version": report["source_schema_version"],
        "host_reason": copy.deepcopy(dict(response["reason"])),
        "candidate_reasons": {
            str(item["catalog_ref"]): copy.deepcopy(dict(item["reason"]))
            for item in response["candidates"]
        },
    }


def resolve_host_product_selection(
    query: str,
    response: Any,
    client: Any,
    *,
    workspace: Any | None = None,
    plan_node_namespace: str | None = None,
) -> dict[str, Any]:
    """Describe validated products without executing them or accepting host controls."""

    compiled = compile_host_product_selection(query, response, client)
    refs = list(compiled["selected_catalog_refs"])
    candidates: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    if not refs:
        gaps = [_empty_selection_gap(query)]
    elif len(refs) > 1:
        from .intent_routing import product_selection_gap

        gaps = [product_selection_gap(
            query,
            refs,
            reason=(
                "the host referenced multiple independently registered catalog "
                "products; the SDK does not guess a top-1 product"
            ),
        )]
    else:
        candidate, gap = _describe_reference(
            refs[0], query, client, workspace, plan_node_namespace
        )
        candidates = [candidate] if candidate is not None else []
        gaps = [gap] if gap is not None else []
    return _selection_envelope(query, candidates, gaps, compiled, workspace)


def _response_mapping(
    response: Any, violations: list[dict[str, str]]
) -> Mapping[str, Any]:
    if not isinstance(response, Mapping):
        add_violation(violations, "HOST_SELECTION_SCHEMA_INVALID", "host_selection")
        return {}
    if set(response) != _RESPONSE_FIELDS:
        add_violation(violations, "HOST_SELECTION_SCHEMA_INVALID", "host_selection")
    if response.get("schema_version") != SELECTION_SCHEMA_VERSION:
        add_violation(
            violations, "HOST_SELECTION_SCHEMA_UNKNOWN", "host_selection.schema_version"
        )
    return response


def _validate_response_binding(
    query: str,
    response: Mapping[str, Any],
    catalog: Mapping[str, Any],
    violations: list[dict[str, str]],
) -> None:
    if not isinstance(query, str) or not query.strip() or response.get("query") != query:
        add_violation(violations, "HOST_SELECTION_QUERY_MISMATCH", "host_selection.query")
    if response.get("catalog_sha256") != catalog["catalog_sha256"]:
        add_violation(
            violations, "HOST_SELECTION_CATALOG_MISMATCH",
            "host_selection.catalog_sha256",
        )


def _candidate_rows(
    value: Any, violations: list[dict[str, str]]
) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or len(value) > MAX_CANDIDATES:
        add_violation(violations, "HOST_SELECTION_CANDIDATES_INVALID", "host_selection.candidates")
        return []
    rows: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        field = f"host_selection.candidates[{index}]"
        if not isinstance(item, Mapping) or set(item) != _CANDIDATE_FIELDS:
            add_violation(violations, "HOST_SELECTION_CANDIDATE_INVALID", field)
            continue
        _validate_candidate_reason(item.get("reason"), f"{field}.reason", violations)
        rows.append(item)
    return rows


def _resolve_catalog_refs(
    candidates: list[Mapping[str, Any]],
    sources: Mapping[str, Any],
    entries: Mapping[str, Mapping[str, Any]],
    violations: list[dict[str, str]],
) -> list[str]:
    refs: list[str] = []
    for index, item in enumerate(candidates):
        reference = item.get("catalog_ref")
        field = f"host_selection.candidates[{index}].catalog_ref"
        source = source_for_plan(reference, sources, field, violations)
        expect_sdk_source(
            source,
            code="HOST_PRODUCT_NOT_SDK_ORIGIN",
            field=field,
            violations=violations,
        )
        expected = entries.get(str(reference))
        value = source_value(source)
        if expected is None or not _source_matches(value, expected, sources):
            add_violation(violations, "HOST_PRODUCT_IDENTITY_MISMATCH", field)
            continue
        refs.append(str(reference))
    if len(set(refs)) != len(refs):
        add_violation(
            violations, "HOST_SELECTION_CANDIDATE_DUPLICATE", "host_selection.candidates"
        )
    return refs


def _source_matches(
    value: Any,
    entry: Mapping[str, Any],
    sources: Mapping[str, Any],
) -> bool:
    reference = str(entry["catalog_ref"])
    expected = {
        "catalog_sha256": sources[reference]["value"]["catalog_sha256"],
        "identity": reference,
        "identity_kind": str(entry["identity_kind"]),
    }
    return value == expected


def _validate_decision(
    decision: Any, count: int, violations: list[dict[str, str]]
) -> None:
    expected = "abstained" if count == 0 else "selected" if count == 1 else "multiple_intents"
    if decision != expected:
        add_violation(
            violations, "HOST_SELECTION_DECISION_MISMATCH", "host_selection.decision"
        )


def _validate_summary_reason(value: Any, violations: list[dict[str, str]]) -> None:
    field = "host_selection.reason"
    if not isinstance(value, Mapping) or set(value) != _REASON_FIELDS:
        add_violation(violations, "HOST_SELECTION_REASON_INVALID", field)
        return
    if not isinstance(value.get("summary"), str) or not value["summary"].strip():
        add_violation(violations, "HOST_SELECTION_REASON_INVALID", f"{field}.summary")
    if not isinstance(value.get("needs_clarification"), bool):
        add_violation(
            violations, "HOST_SELECTION_REASON_INVALID", f"{field}.needs_clarification"
        )


def _validate_candidate_reason(
    value: Any, field: str, violations: list[dict[str, str]]
) -> None:
    if not isinstance(value, Mapping) or set(value) != _CANDIDATE_REASON_FIELDS:
        add_violation(violations, "HOST_SELECTION_REASON_INVALID", field)
        return
    if any(not isinstance(value.get(key), str) or not value[key].strip() for key in _CANDIDATE_REASON_FIELDS):
        add_violation(violations, "HOST_SELECTION_REASON_INVALID", field)


def _describe_reference(
    reference: str,
    query: str,
    client: Any,
    workspace: Any | None,
    namespace: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    from .catalog import _capability_for_item, _inventory
    from .handoff import apply_workspace_prefix, attach_plan_node, resolve_workspace_path
    from .discovery_policy import safe_discovery_query

    item = next(entry for entry in _inventory(client) if entry["selector"] == reference)
    if item["identity_kind"] == "capability_gap":
        gap = copy.deepcopy(dict(item["card"]))
        gap["query"] = safe_discovery_query(query)
        return None, gap
    card = _capability_for_item(item, client)
    card["match"] = {
        "confidence": "host_catalog",
        "coverage": None,
        "matched_terms": [],
        "missing_terms": [],
        "exact_selector": False,
    }
    selected = apply_workspace_prefix(card, resolve_workspace_path(workspace))
    return attach_plan_node(selected, safe_discovery_query(query), namespace=namespace), None


def _empty_selection_gap(query: str) -> dict[str, Any]:
    from .discovery_policy import safe_discovery_query

    return {
        "kind": "capability_gap",
        "code": EMPTY_SELECTION_GAP,
        "query": safe_discovery_query(query),
        "reason": "the host selected no identity from the current canonical product catalog",
        "next_action": (
            "Browse `gravity agent-catalog categories` to confirm no registered "
            "product matches, or inspect `gravity agent-catalog host`; do not "
            "invent an operation, path, product, or Plan control identity."
        ),
        "next": catalog_browse_next(),
        "weak_matches": [],
        "network_called": False,
    }


def _selection_envelope(
    query: str,
    candidates: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    compiled: Mapping[str, Any],
    workspace: Any | None,
) -> dict[str, Any]:
    from ..agent import SCHEMA_VERSION
    from .discovery_policy import safe_discovery_query
    from .handoff import agent_execution_contract, agent_fallbacks, resolve_workspace_path

    workspace_path = resolve_workspace_path(workspace)
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "status": "success" if candidates else "capability_gap",
        "offline": True,
        "network_called": False,
        "mode": "host_catalog_select_and_describe",
        "routing_mode": HOST_ROUTING_MODE,
        "routing": {
            "mode": HOST_ROUTING_MODE,
            "floor": False,
        },
        "query": safe_discovery_query(query),
        "count": len(candidates),
        "total": len(candidates),
        "candidates": candidates,
        "capability_gaps": gaps,
        "selection_receipt": copy.deepcopy(dict(compiled)),
        "execution": agent_execution_contract(workspace_path),
        "fallbacks": agent_fallbacks(safe_discovery_query(query), workspace_path),
        "next_action": (
            "Fill the selected repository-owned card inputs and validate its Plan."
            if candidates
            else (
                "Follow the canonical gap; browse `gravity agent-catalog "
                "categories` only to confirm the capability is absent, and do "
                "not guess a control identity."
            )
        ),
        **({} if candidates else {"next": catalog_browse_next()}),
    }


__all__ = [
    "DEFAULT_ROUTING_MODE",
    "EMPTY_SELECTION_GAP",
    "HOST_ROUTING_MODE",
    "RECOGNIZER_ROUTING_MODE",
    "ROUTING_MODES",
    "add_host_routing_arguments",
    "assess_host_product_selection",
    "compile_host_product_selection",
    "host_routing_command",
    "host_routing_discovery",
    "resolve_host_product_selection",
]
