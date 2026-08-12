"""Compact, offline-first CLI surface for calling agents."""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .agent_capabilities import (
    AGENT_SCOPE, authoritative_capability_cards,
    capability_handoff_cards,
    merge_catalog_handoff_cards,
    should_load_capability_catalog,
)
from .agent_handoff import (
    agent_execution_contract,
    agent_fallbacks,
    apply_workspace_prefix,
    attach_plan_node,
    resolve_workspace_path,
    unify_capability_candidates,
    workspace_prefix,
)
from .agent_export import export_inventory_for_query
from .agent_sources import (
    catalog_cards,
    candidates_fingerprint,
    describe_operation_cards,
    discover_operation_cards,
    workspace_catalog_fingerprint,
)
from .agent_batch_sources import AgentSourceSnapshot
from .agent_client import DeferredAgentClient
from .errors import InputValidationError
from .find import capability_gaps


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
    command.add_argument(
        "--input",
        "-i",
        help=(
            "A capabilities-many JSON object/file/stdin document; cannot be combined "
            "with the positional query."
        ),
    )
    command.add_argument(
        "--format",
        choices=("json", "ndjson"),
        default="json",
        help="Machine output encoding (default: json).",
    )


def run_agent_command(args: Any, client: Any) -> dict[str, Any]:
    """Return the protocol or a bounded set of executable capability cards."""

    if getattr(args, "input", None) is not None:
        if (
            args.query is not None
            or args.continuation is not None
            or args.domain is not None
            or args.platform is not None
        ):
            raise InputValidationError(
                "agent --input cannot be combined with query, continuation, domain, or platform",
                field="input",
            )
        from .agent_batch import capabilities_many
        from .find_input import load_json_input

        value = load_json_input(args.input, required=True)
        return capabilities_many(value, client=client)
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
) -> dict[str, Any]:
    """Return the same bounded, offline protocol used by ``gravity agent``.

    A client is only required for a non-empty query.  Supplying ``workspace``
    lets embedding applications use their already-loaded recipe catalog.
    """

    if type(limit) is not int or not 1 <= limit <= 5:
        raise InputValidationError(
            "agent limit must be between 1 and 5",
            field="limit",
        )
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
    authoritative_cards = authoritative_capability_cards(page.catalog_cards)
    if authoritative_cards or page.operation_fallback_excluded:
        unified = [("catalog", card) for card in authoritative_cards]
        weak_operations: list[Mapping[str, Any]] = []
    else:
        if client is None:
            raise InputValidationError(
                "an Insight client is required for capability discovery",
                field="client",
            )
        operations = discover_operation_cards(
            client,
            request.query,
            domain=request.domain,
            platform=request.platform,
            inventory=(sources.operation_inventory if sources is not None else None),
        )
        unified = unify_capability_candidates(page.catalog_cards, operations.matches)
        weak_operations = operations.weak
    fingerprint = candidates_fingerprint(unified)
    if (
        page.expected_candidates_fingerprint is not None
        and page.expected_candidates_fingerprint != fingerprint
    ):
        raise InputValidationError(
            "agent continuation does not match the current candidate catalog",
            field="continuation",
        )
    if page.offset >= len(unified) and request.continuation:
        raise InputValidationError(
            "agent continuation no longer points to an available candidate",
            field="continuation",
        )
    candidates = _materialize_candidates(
        client, unified[page.offset : page.offset + request.limit]
    )
    gaps = [] if unified else _capability_gaps(
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
    )


def _capability_gaps(
    request: _DiscoveryRequest,
    client: Any,
    weak_operations: list[Mapping[str, Any]],
    operation_fallback_excluded: bool,
) -> list[dict[str, Any]]:
    if operation_fallback_excluded:
        from .agent_discovery_policy import promotion_performance_gap
        return promotion_performance_gap(request.query)
    return capability_gaps(
        client,
        request.query,
        domain=request.domain,
        platform=request.platform,
        limit=request.limit,
        weak_operations=weak_operations,
    )


def _materialize_candidates(
    client: Any, selected: list[tuple[str, Mapping[str, Any]]]
) -> list[dict[str, Any]]:
    described = iter(
        describe_operation_cards(
            client, [item for source, item in selected if source == "operation"]
        )
    )
    return [
        next(described) if source == "operation" else dict(item)
        for source, item in selected
    ]


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
) -> dict[str, Any]:
    candidates = [
        attach_plan_node(
            apply_workspace_prefix(item, workspace_path),
            request.query,
            namespace=plan_node_namespace,
        )
        for item in candidates
    ]
    next_offset = page.offset + len(candidates)
    next_token = (
        _encode_continuation(
            request,
            request.query,
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
        "scope": AGENT_SCOPE,
        "query": request.query,
        "limit": request.limit,
        "count": len(candidates),
        "total": total,
        "continuation_token": next_token,
        "candidates": candidates,
        "capability_gaps": gaps,
        "catalog_warnings": page.catalog_warnings,
        "match_policy": {
            "success_requires": "at least 80% query-term coverage",
            "partial_matches_are_executable": False,
        },
        "execution": agent_execution_contract(workspace_path),
        "fallbacks": agent_fallbacks(request.query, workspace_path),
        "next_action": (
            "Prefer a recipe, registered composite, then stable Insight; use a "
            "matching SQL product only when Insight cannot express the goal, and "
            "invoke the selected next.argv."
            if candidates
            else "Report capability_gaps; do not execute weak partial matches."
        ),
    }


def _discovery_page(
    args: Any,
    query: str,
    *,
    client: Any | None = None,
    workspace: Any | None = None,
    sources: AgentSourceSnapshot | None = None,
) -> _DiscoveryPage:
    selected_workspace = sources.workspace if sources is not None else workspace
    workspace_path = resolve_workspace_path(selected_workspace)
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
            query, 100, workspace=workspace, sources=sources
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
    if args.continuation:
        continuation = _decode_continuation(
            args, query, catalog_fingerprint=catalog_fingerprint
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
    )


def _protocol(workspace_path: object | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": True,
        "status": "ready",
        "offline": True,
        "network_called": False,
        "mode": "protocol",
        "scope": AGENT_SCOPE,
        "goal": "Discover plus describe, then execute, in at most two CLI calls.",
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
        raise InputValidationError(message, field="continuation")
    return payload


def ndjson_metadata(value: Any) -> dict[str, Any]:
    """Preserve the Agent protocol when candidates become NDJSON rows."""

    if not isinstance(value, Mapping) or value.get("schema_version") != SCHEMA_VERSION:
        return {}
    return {
        "payload_schema_version": SCHEMA_VERSION,
        "ok": value.get("ok"),
        "offline": value.get("offline"),
        "network_called": value.get("network_called"),
        "mode": value.get("mode"),
        "count": value.get("count"),
        "total": value.get("total"),
        "query": value.get("query"),
        "continuation_token": value.get("continuation_token"),
        "next_action": value.get("next_action"),
        "execution": value.get("execution"),
        "scope": value.get("scope"),
        "fallbacks": value.get("fallbacks"),
        "catalog_warnings": value.get("catalog_warnings"),
        "capability_gaps": value.get("capability_gaps"),
        "match_policy": value.get("match_policy"),
    }


__all__ = [
    "SCHEMA_VERSION",
    "add_agent_command",
    "discover_capabilities",
    "ndjson_metadata",
    "run_agent_command",
]
