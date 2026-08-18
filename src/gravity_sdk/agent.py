"""Compact, offline-first CLI surface for calling agents."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .agent_capabilities import (
    AGENT_SCOPE,
    capability_handoff_cards,
    merge_catalog_handoff_cards,
    should_load_capability_catalog,
)
from .agent_handoff import (
    agent_execution_contract, agent_fallbacks,
    apply_workspace_prefix,
    attach_plan_node,
    resolve_workspace_path,
    unify_capability_candidates,
    workspace_prefix,
)
from .agent_discovery_policy import safe_discovery_query
from .agent_export import export_inventory_for_query
from .agent_sources import (
    catalog_cards,
    candidates_fingerprint,
    discover_operation_cards,
    workspace_catalog_fingerprint,
)
from .agent_batch_sources import AgentSourceSnapshot
from .agent_client import DeferredAgentClient
from .agent_discovery_support import (
    assert_discovery_page,
    finish_discovery_candidates,
    capability_gaps_for_page,
    discovery_next_fields,
    materialize_candidates,
    select_authoritative_cards,
)
from .agent_lexical_retrieval import response_match_policy
from .errors import InputValidationError
from .agent_output import ndjson_metadata
from .actionable_error_values import actual_value


SCHEMA_VERSION = "gravity.agent.v1"
DEFAULT_LIMIT = 3

@dataclass(frozen=True)
class _DiscoveryPage:
    catalog_cards: list[dict[str, Any]]
    catalog_warnings: list[str]
    catalog_fingerprint: str
    expected_candidates_fingerprint: str | None
    offset: int
    workspace_path: object | None
    operation_fallback_excluded: bool
    semantic_gaps: list[dict[str, Any]]
    semantic_context: dict[str, Any] | None


@dataclass(frozen=True)
class _DiscoveryRequest:
    query: str
    domain: str | None
    platform: str | None
    limit: int
    continuation: str | None


def add_agent_command(commands: Any, limit_parser: Any) -> None:
    """Register one bounded discover-and-describe command for agents."""

    command = commands.add_parser(
        "agent",
        help=(
            "Discover and describe a few workspace recipes or callable operations "
            "in one offline command."
        ),
    )
    command.set_defaults(network_required=False)
    command.add_argument(
        "query",
        nargs="?",
        help="Business, technical, or operation-id keyword; omit for the protocol.",
    )
    command.add_argument("--domain")
    command.add_argument("--platform")
    command.add_argument(
        "--limit",
        type=limit_parser,
        default=DEFAULT_LIMIT,
        help="Maximum fully described recipes and operations (default: 3, maximum: 5).",
    )
    command.add_argument("--continuation")
    from .agent_host_selection import add_host_routing_arguments
    add_host_routing_arguments(command)
    command.add_argument(
        "--input",
        "-i",
        help=(
            "A capabilities-many JSON object/file/stdin document whose legal shape "
            "is {\"questions\":[{\"id\":\"q1\",\"query\":\"...\"}]} or a questions "
            "array; cannot be combined with the positional query."
        ),
    )
    from .agent_input_resolution import add_resolution_argument
    add_resolution_argument(command)
    command.add_argument(
        "--format",
        choices=("json", "ndjson"),
        default="json",
        help="Machine output encoding (default: json).",
    )


def run_agent_command(args: Any, client: Any) -> dict[str, Any]:
    """Return the protocol or a bounded set of executable capability cards."""

    from .agent_host_selection import host_routing_command
    if (host_result := host_routing_command(args, client)) is not None:
        return host_result
    from .agent_input_resolution import optional_agent_input_command
    selected = optional_agent_input_command(args, client)
    if selected is not None:
        return selected
    return discover_capabilities(
        args.query,
        client=client,
        domain=args.domain,
        platform=args.platform,
        limit=args.limit,
        continuation=args.continuation,
    )


def discover_capabilities(
    query: str | None = None,
    *,
    client: Any | None = None,
    workspace: Any | None = None,
    domain: str | None = None,
    platform: str | None = None,
    limit: int = DEFAULT_LIMIT,
    continuation: str | None = None,
    sources: AgentSourceSnapshot | None = None,
    plan_node_namespace: str | None = None,
    routing: str = "recognizer",
    host_selection: Any | None = None,
) -> dict[str, Any]:
    """Return the same bounded, offline protocol used by ``gravity agent``.

    A client is only required for a non-empty query.  Supplying ``workspace``
    lets embedding applications use their already-loaded recipe catalog.
    """

    if type(limit) is not int or not 1 <= limit <= 5:
        raise InputValidationError(
            f"actual value: {actual_value(limit)}; " + ("agent limit must be between 1 and 5"),
            field="limit",
        )
    from .agent_host_selection import host_routing_discovery
    host_result = host_routing_discovery(
        query, client, routing=routing, host_selection=host_selection,
        workspace=workspace, plan_node_namespace=plan_node_namespace,
    )
    if host_result is not None:
        return host_result
    normalized_query = str(query or "").strip()
    request = _DiscoveryRequest(
        query=normalized_query,
        domain=domain,
        platform=platform,
        limit=limit,
        continuation=continuation,
    )
    query = request.query
    if not query:
        return _protocol(resolve_workspace_path(workspace))
    return _discover(
        request,
        client,
        workspace=workspace,
        sources=sources,
        plan_node_namespace=plan_node_namespace,
    )


def _discover(
    request: _DiscoveryRequest,
    client: Any,
    *,
    workspace: Any | None,
    sources: AgentSourceSnapshot | None = None,
    plan_node_namespace: str | None = None,
) -> dict[str, Any]:
    page = _discovery_page(
        request, request.query, client=client, workspace=workspace, sources=sources
    )
    authoritative_cards = select_authoritative_cards(page.catalog_cards)
    if authoritative_cards or page.operation_fallback_excluded:
        unified = [("catalog", card) for card in authoritative_cards]
        weak_operations: list[Mapping[str, Any]] = []
    else:
        if client is None:
            raise InputValidationError(
                "an Insight client is required for capability discovery",
                field="client", next_action="Construct GravityClient.from_env() or pass an Insight client.",
            )
        from .agent_monetization_guard import (
            MONETIZATION_DETAIL_RAW_SELECTOR,
            monetization_open_dimension_query,
        )
        from .agent_app_catalog import app_catalog_operation_query

        operation_query = (
            MONETIZATION_DETAIL_RAW_SELECTOR
            if monetization_open_dimension_query(request.query)
            else app_catalog_operation_query(request.query)
        )
        operations = discover_operation_cards(
            client,
            operation_query,
            domain=request.domain,
            platform=request.platform,
            inventory=(sources.operation_inventory if sources is not None else None),
        )
        unified = unify_capability_candidates(page.catalog_cards, operations.matches)
        weak_operations = operations.weak
    from .agent_lexical_retrieval import apply_lexical_fallback

    lexical = apply_lexical_fallback(
        request.query, existing_candidates=unified,
        existing_semantic_gaps=page.semantic_gaps,
        fallback_blocked=page.operation_fallback_excluded,
        workspace=workspace, sources=sources,
        domain=request.domain, platform=request.platform,
    )
    unified, lexical_gaps = finish_discovery_candidates(request.query, lexical)
    fingerprint = candidates_fingerprint(unified)
    assert_discovery_page(page, request, unified, fingerprint)
    candidates = materialize_candidates(
        client, unified[page.offset : page.offset + request.limit]
    )
    gaps = [] if unified else list(lexical_gaps) or page.semantic_gaps or capability_gaps_for_page(
        request, client, weak_operations, page.operation_fallback_excluded)
    return _discovery_response(
        request,
        page,
        candidates,
        gaps,
        total=len(unified),
        candidates_fingerprint=fingerprint,
        plan_node_namespace=plan_node_namespace,
        workspace_path=page.workspace_path,
        semantic_context=page.semantic_context,
        lexical_receipt=lexical.receipt,
    )


def _discovery_response(
    request: _DiscoveryRequest,
    page: _DiscoveryPage,
    candidates: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    *,
    total: int,
    candidates_fingerprint: str,
    plan_node_namespace: str | None,
    workspace_path: object | None,
    semantic_context: dict[str, Any] | None,
    lexical_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    from .agent_discovery_support import recognizer_routing_declaration

    candidates = [
        attach_plan_node(
            apply_workspace_prefix(item, workspace_path),
            safe_discovery_query(request.query),
            namespace=plan_node_namespace,
        )
        for item in candidates
    ]
    next_offset = page.offset + len(candidates)
    next_token = (
        _encode_continuation(
            request,
            safe_discovery_query(request.query),
            offset=next_offset,
            catalog_fingerprint=page.catalog_fingerprint,
            candidates_fingerprint=candidates_fingerprint,
        )
        if next_offset < total
        else None
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "status": "success" if candidates else "capability_gap",
        "offline": True,
        "network_called": False,
        "mode": "discover_and_describe",
        "routing_mode": "recognizer",
        "routing": recognizer_routing_declaration(request.query),
        "scope": AGENT_SCOPE,
        "query": safe_discovery_query(request.query),
        "limit": request.limit,
        "count": len(candidates),
        "total": total,
        "continuation_token": next_token,
        "candidates": candidates,
        "capability_gaps": gaps,
        "catalog_warnings": page.catalog_warnings,
        "match_policy": response_match_policy(lexical_receipt),
        "execution": agent_execution_contract(workspace_path),
        "fallbacks": agent_fallbacks(safe_discovery_query(request.query), workspace_path),
        **discovery_next_fields(bool(candidates), gaps),
        **({"semantic_context": semantic_context} if semantic_context is not None else {}),
    }


def _discovery_page(
    args: Any,
    query: str,
    *,
    client: Any | None = None,
    workspace: Any | None = None,
    sources: AgentSourceSnapshot | None = None,
) -> _DiscoveryPage:
    workspace_path = resolve_workspace_path(sources.workspace if sources is not None else workspace)
    from .agent_semantic_context import load_agent_workspace
    selected_workspace = load_agent_workspace(workspace, sources)
    composite_inventory = (
        sources.composite_inventory if sources is not None else None
    )
    export_inventory = export_inventory_for_query(
        query,
        client=client,
        inventory=sources.export_inventory if sources is not None else None,
    )
    selected_cards, catalog_excluded = capability_handoff_cards(
        query,
        domain=args.domain,
        platform=args.platform,
        export_inventory=export_inventory,
        composite_inventory=composite_inventory,
    )
    warnings: list[str] = []
    catalog_fingerprint = workspace_catalog_fingerprint(None)
    if should_load_capability_catalog(
        query,
        domain=args.domain,
        platform=args.platform,
        direct_cards=selected_cards,
        catalog_excluded=catalog_excluded,
    ):
        catalog, _catalog_total, warnings, catalog_fingerprint = catalog_cards(
            query, 100, workspace=selected_workspace, sources=sources
        )
        selected_cards = merge_catalog_handoff_cards(
            query,
            domain=args.domain,
            platform=args.platform,
            direct_cards=selected_cards,
            catalog=catalog,
            warnings=warnings,
            sources=sources,
        )
    from .agent_semantic_context import resolve_semantic_context

    semantic = resolve_semantic_context(
        query, selected_workspace, selected_cards, client, args.domain, args.platform, sources
    )
    selected_cards = semantic.cards
    catalog_excluded = catalog_excluded or semantic.block_fallback
    if getattr(selected_workspace, "semantic_context", None) is not None:
        catalog_fingerprint = workspace_catalog_fingerprint(selected_workspace)
    if args.continuation:
        continuation = _decode_continuation(
            args, safe_discovery_query(query), catalog_fingerprint=catalog_fingerprint
        )
        offset = int(continuation["offset"])
        expected_candidates_fingerprint = str(
            continuation["candidates_fingerprint"]
        )
    else:
        offset = 0
        expected_candidates_fingerprint = None
    return _DiscoveryPage(
        catalog_cards=selected_cards,
        catalog_warnings=warnings,
        catalog_fingerprint=catalog_fingerprint,
        expected_candidates_fingerprint=expected_candidates_fingerprint,
        offset=offset,
        workspace_path=workspace_path,
        operation_fallback_excluded=catalog_excluded,
        semantic_gaps=semantic.gaps,
        semantic_context=semantic.public_context,
    )


def _protocol(workspace_path: object | None = None) -> dict[str, Any]:
    from .agent_discovery_support import recognizer_routing_declaration

    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "status": "ready",
        "offline": True,
        "network_called": False,
        "mode": "protocol",
        "routing_mode": "recognizer",
        "routing": recognizer_routing_declaration(""),
        "scope": AGENT_SCOPE,
        "goal": "Known inputs take one call; candidate.call_bound declares unknown-input lower bounds.",
        "workflow": [
            {
                "step": "discover_and_describe",
                "argv": [*workspace_prefix(workspace_path), "agent", "<query>"],
                "network_required": False,
            },
            {
                "step": "execute",
                "argv": [
                    *workspace_prefix(workspace_path),
                    "run",
                    "<operation_id-or-@recipe>",
                    "--input",
                    "<json-object-or-file>",
                ],
                "network_required": True,
            },
        ],
        "selection_policy": [
            "If the caller can emit gravity.host-product-selection.v1, read "
            "`agent-catalog host` and pass `--routing host_catalog --host-selection`.",
            "Omit --routing to keep the recognizer floor when the caller cannot "
            "produce a host selection.",
            "Prefer a matching workspace recipe because it owns project semantics.",
            "Prefer a registered composite when it already covers the requested context.",
            "Otherwise select a callable stable Insight operation.",
            "Use governed SQL only when Insight cannot express equivalent semantics.",
        ],
        "input_precedence": ["flag", "--set", "--input", "contract_default"],
        "output": {
            "default": "json",
            "large_results": "Use --output <path> --format ndjson.",
            "empty_is_success": True,
        },
        "exit_codes": {
            "0": "success, including an allowed empty result",
            "2": "caller input or authentication setup",
            "3": "upstream, permission, or rate limit",
            "4": "local contract, privacy, policy, or I/O",
        },
        "execution": agent_execution_contract(workspace_path),
        "fallbacks": agent_fallbacks(workspace_path=workspace_path),
        "next_action": "Run `gravity agent <query>` to get bounded executable capability cards.",
    }


def _encode_continuation(
    args: Any,
    query: str,
    *,
    offset: int,
    catalog_fingerprint: str,
    candidates_fingerprint: str,
) -> str:
    payload = {
        "v": 3,
        "query": query.casefold(),
        "domain": args.domain,
        "platform": args.platform,
        "limit": args.limit,
        "offset": offset,
        "catalog_fingerprint": catalog_fingerprint,
        "candidates_fingerprint": candidates_fingerprint,
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return base64.urlsafe_b64encode(encoded.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_continuation(
    args: Any, query: str, *, catalog_fingerprint: str
) -> Mapping[str, Any]:
    message = "agent continuation does not match this discovery context"
    try:
        token = str(args.continuation)
        padding = "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(token + padding).decode("utf-8"))
        valid = (
            isinstance(payload, Mapping)
            and payload.get("v") == 3
            and payload.get("query") == query.casefold()
            and payload.get("domain") == args.domain
            and payload.get("platform") == args.platform
            and payload.get("limit") == args.limit
            and isinstance(payload.get("offset"), int)
            and 0 < int(payload["offset"])
            and payload.get("catalog_fingerprint") == catalog_fingerprint
            and isinstance(payload.get("candidates_fingerprint"), str)
            and len(payload["candidates_fingerprint"]) == 64
            and all(
                character in "0123456789abcdef"
                for character in payload["candidates_fingerprint"]
            )
        )
    except (binascii.Error, UnicodeError, ValueError, TypeError, json.JSONDecodeError):
        valid = False
        payload = {}
    if not valid:
        raise InputValidationError(message, field="continuation", next_action="Drop continuation and run the search again.")
    return payload


__all__ = [
    "SCHEMA_VERSION",
    "add_agent_command",
    "discover_capabilities",
    "ndjson_metadata",
    "run_agent_command",
]
