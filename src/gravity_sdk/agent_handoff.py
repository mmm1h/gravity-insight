"""Copyable Agent command and Plan handoff construction."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any


def workspace_prefix(workspace_path: object | None) -> list[str]:
    if workspace_path is None:
        return ["gravity"]
    return ["gravity", "--workspace", str(workspace_path)]


def resolve_workspace_path(workspace: Any | None) -> object | None:
    selected = workspace
    if selected is None:
        try:
            from .workspace import load_workspace

            selected = load_workspace()
        except (OSError, ValueError):
            return None
    return getattr(selected, "path", None)


def apply_workspace_prefix(
    card: Mapping[str, Any], workspace_path: object | None
) -> dict[str, Any]:
    selected = dict(card)
    if workspace_path is None or not _card_depends_on_workspace(selected):
        return selected
    next_step = selected.get("next")
    if not isinstance(next_step, Mapping):
        return selected
    rendered = dict(next_step)
    for field in ("argv", "then_argv", "schema_argv"):
        argv = rendered.get(field)
        already_bound = (
            isinstance(argv, list)
            and len(argv) >= 3
            and argv[0] == "gravity"
            and argv[1] == "--workspace"
        )
        if (
            isinstance(argv, list)
            and argv
            and argv[0] == "gravity"
            and not already_bound
        ):
            rendered[field] = [*workspace_prefix(workspace_path), *argv[1:]]
    selected["next"] = rendered
    return selected


def _card_depends_on_workspace(card: Mapping[str, Any]) -> bool:
    return str(card.get("kind", "")) in {
        "recipe",
        "sql_product",
        "metadata",
        "composite",
        "analysis_query_spec",
    }


def agent_execution_contract(workspace_path: object | None = None) -> dict[str, Any]:
    return {
        "argv": [
            *workspace_prefix(workspace_path),
            "run",
            "<operation_id-or-@recipe>",
            "--input",
            "<json-object-or-file>",
        ],
        "input_forms": {
            "--input": "inline JSON, JSON file, or '-' for stdin",
            "--set": "repeatable path=value override",
            "--app": "workspace alias or positive App id",
            "--start/--end": "paired date shortcuts",
            "--concurrency": "known-total page workers (default 6, maximum 24)",
        },
        "bounded_stdout": {"max_pages": 5, "max_items": 200},
        "large_result_argv_suffix": [
            "--all-pages", "--concurrency", "6", "--output", "<path>",
            "--format", "ndjson",
        ],
    }


def agent_fallbacks(
    query: str | None = None, workspace_path: object | None = None
) -> list[dict[str, Any]]:
    selected_query = query or "<query>"
    prefix = workspace_prefix(workspace_path)
    return [
        {
            "when": "workspace recipe or local metadata may already encode the goal",
            "argv": [*prefix, "find", selected_query],
        },
        {
            "when": "no stable Insight operation can express equivalent semantics",
            "argv": [*prefix, "sql", "products"],
        },
    ]


def attach_plan_node(
    card: Mapping[str, Any],
    query: str,
    *,
    namespace: str | None = None,
) -> dict[str, Any]:
    selector = str(card.get("selector", "candidate"))
    seed = selector if namespace is None else f"{namespace}\0{selector}"
    kind = str(card.get("kind", ""))
    if kind == "analysis_query_spec":
        missing, template = _handoff_requirements(card, kind)
        return {
            **dict(card),
            "missing_inputs": missing,
            "input_template": template,
            "plan_node": None,
        }
    request, plan_kind = _plan_request(card, query, kind, selector)
    node: dict[str, Any] = {
        "id": "n_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12],
        "kind": plan_kind,
        "request": request,
    }
    output_fields = card.get("output_fields")
    if isinstance(output_fields, list) and output_fields:
        node["output_fields"] = list(output_fields)
    missing, template = _handoff_requirements(card, kind)
    return {
        **dict(card),
        "missing_inputs": missing,
        "input_template": template,
        "plan_node": node,
    }


def unify_capability_candidates(
    catalog: list[dict[str, Any]], operations: list[Mapping[str, Any]]
) -> list[tuple[str, Mapping[str, Any]]]:
    exact = [
        item
        for item in operations
        if bool(item.get("agent_match", {}).get("exact_selector"))
    ]
    if exact:
        return [("operation", item) for item in exact]
    recipes = [card for card in catalog if card.get("kind") == "recipe"]
    compilers = [
        card for card in catalog if card.get("kind") == "analysis_query_spec"
    ]
    auxiliary = [card for card in catalog if card not in recipes + compilers]
    return [
        *(("catalog", card) for card in recipes),
        *(("catalog", card) for card in compilers),
        *(("operation", item) for item in operations),
        *(("catalog", card) for card in auxiliary),
    ]


def _plan_request(
    card: Mapping[str, Any], query: str, kind: str, selector: str
) -> tuple[dict[str, Any], str]:
    if kind in {"recipe", "operation"}:
        return {"selector": selector}, "run"
    if kind == "sql_product":
        return {"product": card.get("product")}, "sql_product"
    if kind == "composite":
        return {"name": card.get("composite")}, "composite"
    if card.get("metadata_kind") == "table_lineage":
        return {"query": "", "kind": "table_lineage"}, "metadata_search"
    lookup_query = card.get("lookup_query")
    selected_query = lookup_query if isinstance(lookup_query, str) else query
    request: dict[str, Any] = {
        "query": selected_query,
        "kind": card.get("metadata_kind", "all"),
    }
    if card.get("app_id") is not None:
        request["app_id"] = card["app_id"]
    return request, "metadata_search"


def _handoff_requirements(
    card: Mapping[str, Any], kind: str
) -> tuple[list[str], dict[str, Any]]:
    existing_missing = card.get("missing_inputs")
    existing_template = card.get("input_template")
    if isinstance(existing_missing, list) and isinstance(existing_template, Mapping):
        return list(existing_missing), dict(existing_template)
    if kind in {"operation", "composite"}:
        missing = [str(value) for value in card.get("required_inputs", [])]
        raw_fields = card.get("input_schema", {})
        fields = raw_fields if isinstance(raw_fields, Mapping) else {}
        template = {
            name: _field_placeholder(name, fields.get(name, {})) for name in missing
        }
        return missing, {"inputs": template} if kind == "operation" else template
    if kind == "recipe":
        missing = [str(value) for value in card.get("required_parameters", [])]
        return missing, {
            "parameters": {name: f"<{name}:value>" for name in missing}
        }
    if kind == "sql_product":
        return ["start", "end"], {
            "start": "<start:inclusive-iso>",
            "end": "<end:exclusive-iso>",
        }
    return [], {}


def _field_placeholder(name: str, specification: Any) -> str:
    if not isinstance(specification, Mapping):
        return f"<{name}:value>"
    selected_type = str(specification.get("type", "value"))
    if selected_type == "array" and specification.get("item_type"):
        selected_type += f"[{specification['item_type']}]"
    if specification.get("enum"):
        selected_type += ":enum"
    return f"<{name}:{selected_type}>"


__all__ = [
    "agent_execution_contract",
    "agent_fallbacks",
    "apply_workspace_prefix",
    "attach_plan_node",
    "resolve_workspace_path",
    "unify_capability_candidates",
    "workspace_prefix",
]
