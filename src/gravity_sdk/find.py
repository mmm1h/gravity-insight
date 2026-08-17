"""Extensible cross-catalog search for agent-facing CLI discovery."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .agent_vocabulary import (
    is_vocabulary_discovery_query,
    is_workspace_vocabulary,
    vocabulary_card_fields,
    vocabulary_match_values,
)
from .errors import InputValidationError
from .find_metadata import search_metadata
from .runtime import to_jsonable
from .workspace import Workspace, load_workspace


SCHEMA_VERSION = "gravity.find.v1"

_MATCH_ALIASES: Mapping[str, tuple[str, ...]] = {
    "app": ("应用", "application"),
    "campaign": ("活动", "推广", "广告"),
    "cohort": ("分群", "segment"),
    "event": ("事件",),
    "funnel": ("漏斗",),
    "material": ("素材", "creative"),
    "metadata": ("元数据",),
    "report": ("报表", "metric", "指标"),
    "retention": ("留存",),
    "segment": ("分群", "cohort"),
    "user": ("用户", "account"),
    "事件": ("event",),
    "分群": ("segment", "cohort"),
    "应用": ("app", "application"),
    "报表": ("report", "metric"),
    "推广": ("promotion", "campaign"),
    "活动": ("campaign",),
    "用户": ("user", "account"),
    "留存": ("retention",),
    "素材": ("material", "creative"),
}


class FindBackend(Protocol):
    name: str

    def search(self, query: str, *, limit: int) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class OperationFindBackend:
    client: Any
    name: str = "operations"

    def search(self, query: str, *, limit: int) -> Sequence[Mapping[str, Any]]:
        result = self.client.search_operations(
            query, stability=None, limit=min(limit, 20)
        )
        values = result.get("operations", [])
        return [
            {
                "backend": self.name,
                "kind": "operation",
                "id": item.get("operation_id"),
                "name": item.get("operation_id"),
                "description": item.get("description", ""),
                "description_origin": "sdk_contract",
                "domain": item.get("domain"),
                "platform": item.get("platform"),
                "stability": item.get("stability"),
                "executable": item.get("executable", True),
                "matched_on": item.get("matched_on", []),
                "score": min(100, int(item.get("score", 0))),
            }
            for item in values
            if isinstance(item, Mapping)
        ]


@dataclass(frozen=True)
class MetadataFindBackend:
    database: Path | None = None
    app_id: str | None = None
    name: str = "metadata"

    def search(self, query: str, *, limit: int) -> Sequence[Mapping[str, Any]]:
        result = search_metadata(
            query,
            database=self.database,
            app_id=self.app_id,
            limit=min(limit, 100),
        )
        return result["results"]


@dataclass(frozen=True)
class RecipeFindBackend:
    workspace: Workspace
    name: str = "recipes"

    def search(self, query: str, *, limit: int) -> Sequence[Mapping[str, Any]]:
        normalized = query.strip().casefold()
        results: list[dict[str, Any]] = []
        for recipe in self.workspace.recipes.values():
            values = (recipe.name, recipe.operation, recipe.description)
            score = max((_recipe_score(normalized, value) for value in values), default=0)
            if score <= 0:
                continue
            results.append(
                {
                    "backend": self.name,
                    "kind": "recipe",
                    "id": recipe.name,
                    "name": recipe.name,
                    "description": recipe.description,
                    "description_origin": "caller_workspace",
                    "operation_id": recipe.operation,
                    "score": score,
                }
            )
        return sorted(
            results, key=lambda item: (-int(item["score"]), str(item["name"]))
        )[:limit]


def query_match(
    query: str, *values: object, score: int = 0
) -> dict[str, Any]:
    """Measure whether every meaningful query concept is represented."""

    concepts = _query_concepts(query)
    haystack = " ".join(str(value).casefold() for value in values if value is not None)
    matched = [
        label
        for label, alternatives in concepts
        if any(term in haystack for term in alternatives)
    ]
    coverage = len(matched) / len(concepts) if concepts else 0.0
    return {
        "confidence": "strong" if coverage >= 0.8 else "partial" if coverage else "none",
        "coverage": round(coverage, 3),
        "matched_terms": matched,
        "missing_terms": [label for label, _ in concepts if label not in matched],
        "score": int(score),
    }


def metadata_capability_cards(
    query: str, *, limit: int | None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Search only the safely resolved default local metadata catalog."""

    try:
        catalog_query = "" if is_vocabulary_discovery_query(query) else query
        result = search_metadata(catalog_query, limit=None, offset=0)
        results = [
            item
            for item in result.get("results", [])
            if isinstance(item, Mapping)
        ]
    except (InputValidationError, OSError):
        return [], [
            "The default local metadata catalog is unavailable; run `gravity metadata "
            "sync --all-apps` before metadata discovery."
        ]
    cards = [_metadata_card(query, item) for item in results]
    strong = [card for card in cards if card["match"]["confidence"] == "strong"]
    return (strong if limit is None else strong[:limit]), []


def capability_gaps(
    client: Any,
    query: str,
    *,
    domain: str | None,
    platform: str | None,
    limit: int,
    weak_operations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Return bounded non-executable blockers or an explicit absence summary."""

    result = client.search_operations(
        query,
        domain=domain,
        platform=platform,
        stability=None,
        limit=limit,
    )
    gaps = [
        _draft_gap(client, query, item)
        for item in result.get("operations", [])
        if isinstance(item, Mapping) and not bool(item.get("executable", True))
    ]
    strong = [gap for gap in gaps if gap["match"]["confidence"] == "strong"]
    if strong:
        return strong[:limit]
    weak = [
        {
            "operation_id": str(item.get("operation_id")),
            "match": query_match(
                query,
                item.get("operation_id"),
                item.get("domain"),
                item.get("resource"),
                item.get("platform"),
                item.get("description"),
                score=int(item.get("score", 0)),
            ),
        }
        for item in weak_operations[:limit]
    ]
    return [{
        "kind": "capability_gap",
        "query": query,
        "reason": "no strongly matching executable or draft capability is registered",
        "weak_matches": weak,
    }]


def _query_concepts(query: str) -> list[tuple[str, frozenset[str]]]:
    fragments = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", query.casefold())
    labels: list[str] = []
    for fragment in fragments:
        if fragment.isascii():
            if len(fragment) >= 3:
                labels.append(fragment)
            continue
        aliases = [key for key in _MATCH_ALIASES if not key.isascii() and key in fragment]
        labels.extend(aliases or [fragment])
    return [
        (label, frozenset((label, *_MATCH_ALIASES.get(label, ()))))
        for label in dict.fromkeys(labels)
    ]


def _metadata_card(query: str, item: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(item.get("kind", "all"))
    if is_workspace_vocabulary(item):
        return _vocabulary_card(query, item)
    command = "events" if kind == "event" else "properties" if "property" in kind else "search"
    app_id = str(item.get("app_id", ""))
    payload = item.get("payload")
    match = query_match(
        query,
        item.get("name"),
        item.get("cname"),
        json.dumps(payload, ensure_ascii=False, sort_keys=True) if isinstance(payload, Mapping) else None,
        score=int(item.get("score", 0)),
    )
    argv = ["gravity", "metadata", command, query]
    if app_id:
        argv.extend(["--app-id", app_id])
    return {
        "kind": "metadata",
        "selector": f"metadata:{kind}:{app_id}:{item.get('name') or ''}",
        "metadata_kind": kind,
        "app_id": app_id or None,
        "name": item.get("name"),
        "display_name": item.get("cname"),
        "operation_id": item.get("operation_id"),
        "match": match,
        "next": {"ready_without_input": True, "argv": argv},
    }


def _vocabulary_card(query: str, item: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(item["kind"])
    payload = item.get("payload")
    match = query_match(
        query,
        *vocabulary_match_values(item),
        json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if isinstance(payload, Mapping)
        else None,
        score=int(item.get("score", 0)),
    )
    return {
        "kind": "metadata",
        "metadata_kind": kind,
        "name": item.get("name"),
        "display_name": item.get("cname"),
        "operation_id": item.get("operation_id"),
        "match": match,
        **vocabulary_card_fields(item, query),
    }


def _draft_gap(client: Any, query: str, item: Mapping[str, Any]) -> dict[str, Any]:
    operation_id = str(item.get("operation_id"))
    described = client.describe(operation_id)
    return {
        "kind": "draft_capability_gap",
        "operation_id": operation_id,
        "description": item.get("description"),
        "description_origin": "sdk_contract",
        "domain": item.get("domain"),
        "platform": item.get("platform"),
        "stability": item.get("stability"),
        "block_reason": item.get("block_reason"),
        "blockers": described.get("blockers"),
        "promotion_gate": described.get("promotion_gate"),
        "match": query_match(
            query,
            operation_id,
            item.get("domain"),
            item.get("resource"),
            item.get("platform"),
            item.get("description"),
            score=int(item.get("score", 0)),
        ),
    }


def add_find_command(commands: Any, limit_parser: Any) -> None:
    find = commands.add_parser(
        "find", help="Search operation and local metadata catalogs together."
    )
    find.set_defaults(network_required=False)
    find.add_argument("query")
    find.add_argument(
        "--backend",
        action="append",
        dest="backends",
        help="Backend name; repeat to select more than one.",
    )
    find.add_argument("--database", type=Path, default=None)
    find.add_argument("--app-id")
    find.add_argument("--limit", type=limit_parser, default=20)


def add_operation_commands(commands: Any, limit_parser: Any) -> None:
    operations = commands.add_parser(
        "operations", help="Inspect registered read operations."
    )
    operations.set_defaults(network_required=False)
    operation_commands = operations.add_subparsers(
        dest="operation_command", required=True
    )
    listing = operation_commands.add_parser("list")
    for name in ("domain", "platform", "stability"):
        listing.add_argument(f"--{name}")
    schema = operation_commands.add_parser("schema")
    schema.add_argument("operation_id")
    search = operation_commands.add_parser("search")
    search.add_argument("query")
    for name in ("domain", "platform", "stability"):
        search.add_argument(f"--{name}")
    search.add_argument("--limit", type=limit_parser, default=20)
    search.add_argument("--continuation")
    describe = operation_commands.add_parser("describe")
    describe.add_argument("operation_id")


def run_operation_command(args: Any, client: Any, filter_operations: Any) -> Any:
    command = args.operation_command
    if command == "list":
        return filter_operations(
            args,
            client.operations(
                domain=args.domain,
                platform=args.platform,
                stability=args.stability if args.stability else None,
            ),
        )
    if command == "search":
        return client.search_operations(
            args.query,
            domain=args.domain,
            platform=args.platform,
            stability=args.stability,
            limit=args.limit,
            continuation=args.continuation,
        )
    return client.describe(args.operation_id) if command == "describe" else client.schema(args.operation_id)


def filter_operations(args: Any, value: Any) -> Any:
    rendered = to_jsonable(value)
    items = rendered
    if isinstance(rendered, Mapping):
        items = rendered.get("operations", rendered.get("data"))
    if not isinstance(items, list):
        return rendered
    filtered = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        operation_id = str(item.get("operation_id", ""))
        if args.domain and item.get("domain") != args.domain:
            continue
        if args.platform and not operation_id.startswith(f"promotion.{args.platform}."):
            continue
        if args.stability and item.get("stability") != args.stability:
            continue
        filtered.append(item)
    return {
        "operations": filtered,
        "count": len(filtered),
    }


def run_find_command(
    args: Any, client: Any, *, workspace: Workspace | None = None
) -> dict[str, Any]:
    selected_workspace = load_workspace() if workspace is None else workspace
    providers: tuple[FindBackend, ...] = (
        OperationFindBackend(client),
        RecipeFindBackend(selected_workspace),
        MetadataFindBackend(args.database, args.app_id),
    )
    selected = set(args.backends or (provider.name for provider in providers))
    available = {provider.name for provider in providers}
    unknown = sorted(selected - available)
    if unknown:
        raise InputValidationError(
            "unknown find backend: " + ", ".join(unknown), field="backend", next_action="Use a documented find backend and retry."
        )

    results: list[dict[str, Any]] = []
    backend_counts: dict[str, int] = {}
    errors: list[dict[str, str]] = []
    for provider in providers:
        if provider.name not in selected:
            continue
        try:
            found = [dict(item) for item in provider.search(args.query, limit=args.limit)]
        except (InputValidationError, OSError) as exc:
            error = {"backend": provider.name, "error": str(exc)}
            if provider.name == "metadata":
                error["next_action"] = "Run `gravity metadata sync --all-apps`."
            errors.append(error)
            backend_counts[provider.name] = 0
            continue
        backend_counts[provider.name] = len(found)
        results.extend(found)
    ordered = sorted(
        results,
        key=lambda item: (
            -int(item.get("score", 0)),
            {"operations": 0, "recipes": 1}.get(str(item.get("backend")), 2),
            str(item.get("name", "")).casefold(),
            str(item.get("app_id", "")),
        ),
    )[: args.limit]
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": bool(ordered) or not errors,
        "status": "partial" if errors and ordered else "error" if errors else "success",
        "query": args.query,
        "count": len(ordered),
        "backends": backend_counts,
        "errors": errors,
        "results": ordered,
    }


def _recipe_score(query: str, value: str) -> int:
    selected = value.casefold()
    if not query:
        return 1
    if query == selected:
        return 100
    if selected.startswith(query):
        return 80
    return 60 if query in selected else 0


__all__ = [
    "FindBackend",
    "MetadataFindBackend",
    "OperationFindBackend",
    "RecipeFindBackend",
    "capability_gaps",
    "metadata_capability_cards",
    "query_match",
    "run_find_command",
    "add_operation_commands",
    "filter_operations",
    "run_operation_command",
]
