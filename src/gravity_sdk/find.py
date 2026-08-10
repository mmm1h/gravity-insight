"""Extensible cross-catalog search for agent-facing CLI discovery."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from .errors import InputValidationError
from .find_metadata import search_metadata
from .runtime import to_jsonable
from .workspace import Workspace, load_workspace


SCHEMA_VERSION = "gravity.find.v1"


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
                    "operation_id": recipe.operation,
                    "score": score,
                }
            )
        return sorted(
            results, key=lambda item: (-int(item["score"]), str(item["name"]))
        )[:limit]


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
            "unknown find backend: " + ", ".join(unknown), field="backend"
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
    "run_find_command",
    "add_operation_commands",
    "filter_operations",
    "run_operation_command",
]
