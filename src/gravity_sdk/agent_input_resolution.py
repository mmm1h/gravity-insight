"""Explicit online input resolution for two-call Agent journeys."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .agents.input_catalogs import live_catalog_for_card, resolvable_scenario
from .errors import InputValidationError, UpstreamError
from .actionable_error_values import actual_value


SCHEMA_VERSION = "gravity.agent-input-resolution.v1"
_CONTEXT_FIELDS = frozenset({"app", "platforms", "catalog_policy"})
_REFRESH_POLICIES = frozenset({"none", "refresh"})
_TABLE_LINEAGE_SELECTOR = "metadata:table_lineage"
_INTEGRATED_SELECTOR = "agent.resolve_inputs"


def add_resolution_argument(command: Any) -> None:
    from .result_output import output_file

    command.add_argument(
        "--resolve-inputs",
        metavar="JSON|FILE|-",
        help=(
            "Explicitly read complete live input catalogs in this Agent call. "
            "Pass known App/platforms and optional catalog_policy=refresh."
        ),
    )
    command.add_argument(
        "--output",
        type=output_file,
        help="Atomically write the complete Agent JSON result to this local file.",
    )


def optional_agent_input_command(args: Any, client: Any) -> dict[str, Any] | None:
    """Handle batch input or explicit online resolution before normal discovery."""

    batch_input = getattr(args, "input", None)
    resolution_input = getattr(args, "resolve_inputs", None)
    if batch_input is not None and resolution_input is not None:
        raise InputValidationError(
            "agent --input cannot be combined with --resolve-inputs",
            field="resolve_inputs", next_action="Omit either --input or --resolve-inputs, then retry.",
        )
    if batch_input is not None:
        return _batch_command(args, client, batch_input)
    if resolution_input is None:
        return None
    if not getattr(args, "output", None):
        raise InputValidationError(
            f"actual value: {actual_value(getattr(args, 'output', None))}; " + ("agent --resolve-inputs requires --output so catalogs are not truncated"),
            field="output",
        )
    if getattr(args, "format", "json") != "json":
        raise InputValidationError(
            f"actual value: {actual_value(getattr(args, 'format', 'json'))}; " + ("agent --resolve-inputs requires JSON file output"),
            field="format",
        )
    if args.query is None or args.continuation is not None:
        raise InputValidationError(
            f"actual value: {actual_value(args.query)}; " + ("agent --resolve-inputs requires one query and cannot use continuation"),
            field="resolve_inputs",
        )
    from .find_input import load_json_input

    known_inputs = load_json_input(resolution_input, required=True)
    args.network_required = True
    args.result_output_fail_closed = True
    return resolve_capabilities(
        args.query,
        known_inputs=known_inputs,
        client=client,
        workspace=getattr(args, "workspace", None),
        domain=args.domain,
        platform=args.platform,
        limit=args.limit,
    )


def resolve_capabilities(
    query: str,
    *,
    known_inputs: Mapping[str, Any],
    client: Any,
    workspace: Any | None = None,
    domain: str | None = None,
    platform: str | None = None,
    limit: int = 3,
) -> dict[str, Any]:
    """Discover capability and complete input catalogs in one explicit call."""

    context = _validate_context(known_inputs)
    _clear_metadata_cache(client)
    try:
        return _resolve_online(
            query,
            client=client,
            workspace=workspace,
            domain=domain,
            platform=platform,
            limit=limit,
            context=context,
        )
    finally:
        _clear_metadata_cache(client)


def _resolve_online(
    query: str,
    *,
    client: Any,
    workspace: Any | None,
    domain: str | None,
    platform: str | None,
    limit: int,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    options = {
        "client": client, "workspace": workspace, "domain": domain,
        "platform": platform, "limit": limit,
    }
    result = _discover(query, **options)
    refresh = _refresh_target(result)
    refresh_receipt = None
    if context["catalog_policy"] == "refresh" and refresh["needed"]:
        refresh_receipt = _refresh_catalog(
            client, include_table_lineage=refresh["table_lineage"]
        )
        _clear_metadata_cache(client)
        result = _discover(query, **options)
    cards, resolved = _resolve_cards(
        result.get("candidates"),
        client=client,
        workspace=workspace,
        known_inputs=context,
    )
    refreshed = _mark_refreshed_cards(cards, refresh) if refresh_receipt else 0
    if resolved + refreshed == 0:
        raise InputValidationError(
            "selected Agent capability has no online input catalog to resolve",
            field="query", next_action="Pick a capability that exposes an online input catalog.",
        )
    response = copy.deepcopy(dict(result))
    response.update(
        offline=False,
        network_called=True,
        mode="discover_describe_and_resolve_inputs",
        candidates=cards,
        input_resolution={
            "schema_version": SCHEMA_VERSION,
            "status": "success",
            "selection": "caller_exact",
            "candidate_catalogs_resolved": resolved,
            "candidate_catalogs_refreshed": refreshed,
            "catalog_refresh": refresh_receipt,
            "process_metadata_cache": "cleared_before_and_after",
            "caller_call_unit": "cli_or_sdk_invocation",
            "internal_http_calls_reduced": False,
            "complete_delivery": "sdk_object_or_atomic_json_file",
        },
    )
    return response


def _batch_command(args: Any, client: Any, input_value: Any) -> dict[str, Any]:
    if (
        args.query is not None
        or args.continuation is not None
        or args.domain is not None
        or args.platform is not None
    ):
        raise InputValidationError(
            "agent --input cannot be combined with query, continuation, domain, or platform",
            field="input", next_action="Omit --input or omit query/continuation/domain/platform, then retry.",
        )
    from .agent_batch import capabilities_many
    from .find_input import load_json_input

    return capabilities_many(load_json_input(input_value, required=True), client=client)


def _discover(query: str, **options: Any) -> dict[str, Any]:
    from .agent import discover_capabilities

    return discover_capabilities(query, **options)


def _validate_context(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; " + ("agent resolve inputs must be an object"), field="resolve_inputs"
        )
    unknown = sorted(set(value) - _CONTEXT_FIELDS)
    if unknown:
        raise InputValidationError(
            "agent resolve inputs contains unknown fields", field="resolve_inputs", next_action="Omit either --input or --resolve-inputs, then retry."
        )
    policy = value.get("catalog_policy", "none")
    if policy not in _REFRESH_POLICIES:
        raise InputValidationError(
            f"actual value: {actual_value(policy)}; " + ("catalog_policy must be none or refresh"),
            field="resolve_inputs.catalog_policy",
        )
    return {**copy.deepcopy(dict(value)), "catalog_policy": policy}


def _refresh_target(result: Mapping[str, Any]) -> dict[str, bool]:
    candidates = result.get("candidates")
    cards = candidates if isinstance(candidates, list) else []
    table_lineage = any(
        isinstance(card, Mapping) and card.get("selector") == _TABLE_LINEAGE_SELECTOR
        for card in cards
    )
    metadata = any(
        isinstance(card, Mapping)
        and (
            card.get("kind") in {"metadata", "analysis_task"}
            or card.get("catalog_missing") is True
        )
        for card in cards
    )
    return {"needed": table_lineage or metadata, "table_lineage": table_lineage}


def _refresh_catalog(client: Any, *, include_table_lineage: bool) -> dict[str, Any]:
    from .agents.catalog_refresh import refresh_complete_catalog

    result = refresh_complete_catalog(
        client, include_table_lineage=include_table_lineage
    )
    if result.get("ok") is not True or result.get("status") != "success":
        raise UpstreamError(
            "metadata catalog refresh was incomplete; input resolution stopped"
        )
    fields = (
        "schema_version",
        "status",
        "synced_at",
        "app_count",
        "operation_count",
        "rows_written",
        "vocabulary_rows_written",
        "table_lineage_included",
        "table_lineage_rows",
    )
    return {field: copy.deepcopy(result[field]) for field in fields if field in result}


def _resolve_cards(
    value: Any,
    *,
    client: Any,
    workspace: Any | None,
    known_inputs: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(value, list):
        raise UpstreamError("Agent discovery returned an invalid candidate collection")
    cards, resolved = [], 0
    for raw in value:
        if not isinstance(raw, Mapping):
            raise UpstreamError("Agent discovery returned an invalid candidate")
        card = copy.deepcopy(dict(raw))
        catalog = live_catalog_for_card(
            card,
            client=client,
            workspace=workspace,
            known_inputs=known_inputs,
        )
        if catalog is not None:
            card["input_catalog"] = catalog
            scenario = resolvable_scenario(card)
            if scenario is None:
                raise RuntimeError("input catalog omitted its call-bound scenario")
            card = _lower_call_bound(card, scenario)
            resolved += 1
        cards.append(card)
    return cards, resolved


def _lower_call_bound(card: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    bound = card.get("call_bound")
    if not isinstance(bound, Mapping):
        raise RuntimeError("resolved Agent card omitted call_bound")
    selected = copy.deepcopy(dict(bound))
    scenarios = selected.get("scenarios")
    if not isinstance(scenarios, list):
        raise RuntimeError("resolved Agent card has invalid call_bound scenarios")
    found = False
    for scenario in scenarios:
        if isinstance(scenario, dict) and scenario.get("id") == scenario_id:
            _resolve_scenario(scenario)
            found = True
    if not found:
        raise RuntimeError("resolved Agent card omitted its input scenario")
    card["call_bound"] = selected
    node = card.get("plan_node")
    if isinstance(node, Mapping):
        card["plan_node"] = {**copy.deepcopy(dict(node)), "call_bound": copy.deepcopy(selected)}
    return card


def _mark_refreshed_cards(cards: list[dict[str, Any]], target: Mapping[str, bool]) -> int:
    count = 0
    for card in cards:
        table_card = target["table_lineage"] and card.get("selector") == _TABLE_LINEAGE_SELECTOR
        metadata_card = not target["table_lineage"] and (
            card.get("kind") == "metadata"
            or card.get("kind") == "analysis_task"
            and card.get("catalog_missing") is False
        )
        if table_card or metadata_card:
            _append_refresh_scenario(card)
            count += 1
    return count


def _append_refresh_scenario(card: dict[str, Any]) -> None:
    bound = copy.deepcopy(card.get("call_bound"))
    scenarios = bound.get("scenarios") if isinstance(bound, Mapping) else None
    if not isinstance(scenarios, list):
        raise RuntimeError("refreshed Agent card omitted call_bound scenarios")
    scenario = {
        "id": "catalog_refreshed",
        "minimum_calls": 2,
        "discovery_calls": 0,
        "unknown_inputs": ["catalog_status"],
        "input_sources": [_integrated_source(["catalog_status"], [])],
        "selection": "caller_exact",
        "catalog_status": "available",
    }
    scenarios.append(scenario)
    card["call_bound"] = bound
    node = card.get("plan_node")
    if isinstance(node, Mapping):
        card["plan_node"] = {**copy.deepcopy(dict(node)), "call_bound": copy.deepcopy(bound)}


def _resolve_scenario(scenario: dict[str, Any]) -> None:
    old_sources = scenario.get("input_sources")
    sources = old_sources if isinstance(old_sources, list) else []
    dependencies = sorted({
        str(item)
        for source in sources
        if isinstance(source, Mapping)
        for item in source.get("depends_on_inputs", [])
    })
    scenario.update(
        minimum_calls=2,
        discovery_calls=0,
        catalog_status="available",
        input_sources=[_integrated_source(scenario["unknown_inputs"], dependencies)],
    )


def _integrated_source(inputs: Any, dependencies: list[str]) -> dict[str, Any]:
    return {
        "inputs": copy.deepcopy(list(inputs)),
        "kind": "upstream_catalog",
        "selector": _INTEGRATED_SELECTOR,
        "cli_argv": [
            "gravity", "agent", "<query>", "--resolve-inputs",
            "<known-inputs.json>", "--output", "<catalog.json>",
        ],
        "sdk_method": "GravitySDK.resolve_capabilities",
        "depends_on_inputs": dependencies,
        "depends_on_sources": [],
    }


def _clear_metadata_cache(client: Any) -> None:
    target = getattr(client, "_client", None) or client
    cache = getattr(target, "_metadata_cache", None)
    clear = getattr(cache, "clear", None)
    if callable(clear):
        clear()


__all__ = [
    "SCHEMA_VERSION",
    "add_resolution_argument",
    "optional_agent_input_command",
    "resolve_capabilities",
]
