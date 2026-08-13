"""Copyable Agent command and Plan handoff construction."""

from __future__ import annotations

from collections.abc import Mapping
import copy
import hashlib
import re
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


def is_analysis_task_handoff_query(query: str) -> bool:
    """Keep broad task recognition away from one-word capability lookups."""

    from .agent_analysis_task import is_analysis_task_query

    if not is_analysis_task_query(query):
        return False
    selected = query.strip().casefold()
    if selected.isascii() and " " not in selected and "." in selected:
        return False
    ascii_terms = re.findall(r"[a-z0-9_]+", selected)
    if selected.isascii():
        return len(ascii_terms) >= 2
    chinese = [
        character for character in selected if "\u3400" <= character <= "\u9fff"
    ]
    return len(chinese) >= 4


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
    for field in ("argv", "then_argv", "schema_argv", "cli_argv"):
        rendered[field] = _bound_argv(rendered.get(field), workspace_path)
    selected["next"] = rendered
    return _prefix_catalog_sync(selected, workspace_path)


def _prefix_catalog_sync(
    selected: dict[str, Any], workspace_path: object
) -> dict[str, Any]:
    sync = selected.get("catalog_sync_argv")
    if isinstance(sync, list) and sync and sync[0] == "gravity":
        bound = _bound_argv(sync, workspace_path)
        selected["catalog_sync_argv"] = bound
        catalog = selected.get("catalog")
        if isinstance(catalog, Mapping):
            catalog_value = dict(catalog)
            catalog_next = catalog_value.get("next")
            if isinstance(catalog_next, Mapping):
                catalog_value["next"] = {**catalog_next, "argv": bound}
            selected["catalog"] = catalog_value
    return selected


def _bound_argv(argv: Any, workspace_path: object) -> Any:
    if not isinstance(argv, list) or not argv or argv[0] != "gravity":
        return argv
    if len(argv) >= 3 and argv[1] == "--workspace":
        return argv
    return [*workspace_prefix(workspace_path), *argv[1:]]


def _card_depends_on_workspace(card: Mapping[str, Any]) -> bool:
    return str(card.get("kind", "")) in {
        "recipe",
        "sql_product",
        "metadata",
        "composite",
        "analysis_query_spec",
        "analysis_task",
        "segment_rule_spec",
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
    if card.get("plan_executable") is False:
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
    limits = card.get("plan_node_limits")
    if isinstance(limits, Mapping):
        node["limits"] = copy.deepcopy(dict(limits))
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
    if kind == "analysis_query_spec":
        request: dict[str, Any] = {"name": "analysis_query"}
        analysis_kind = card.get("analysis_kind")
        if isinstance(analysis_kind, str) and analysis_kind:
            request["kind"] = analysis_kind
        for field in ("app", "spec", "start", "end"):
            if card.get(field) is not None:
                request[field] = card[field]
        return request, "composite"
    if kind == "segment_rule_spec":
        from .agent_segment import segment_rule_plan_request

        return segment_rule_plan_request(card), "composite"
    if kind in {"recipe", "operation"}:
        return {"selector": selector}, "run"
    if kind == "sql_product":
        return {"product": card.get("product")}, "sql_product"
    if kind == "composite":
        return _composite_plan_request(card), "composite"
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


def _composite_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    """Delegate value-sensitive composite request templates to their owners."""

    composite = card.get("composite")
    if composite == "dashboard_snapshot":
        from .agent_dashboard import dashboard_plan_request

        return dashboard_plan_request(card)
    if composite == "dashboard_analysis":
        from .agent_dashboard import dashboard_analysis_plan_request

        return dashboard_analysis_plan_request(card)
    if composite == "segment_snapshot":
        from .agent_segment_snapshot import segment_snapshot_plan_request

        return segment_snapshot_plan_request(card)
    if composite == "saved_analysis":
        from .agent_saved_analysis import saved_analysis_plan_request

        return saved_analysis_plan_request(card)
    if composite == "analysis_template":
        from .template_replay_surface import analysis_template_plan_request

        return analysis_template_plan_request(card)
    if composite == "multidim":
        from .agent_multidim import multidim_plan_request

        return multidim_plan_request(card)
    if composite == "business_pulse":
        from .agent_business_pulse import business_pulse_plan_request

        return business_pulse_plan_request(card)
    if composite == "material_performance":
        from .agent_material_performance import material_performance_plan_request

        return material_performance_plan_request(card)
    if composite == "monetization_detail":
        from .agent_monetization_guard import monetization_detail_plan_request

        return monetization_detail_plan_request(card)
    if composite == "order_directory":
        from .agent_order_directory import order_directory_plan_request

        return order_directory_plan_request(card)
    if composite == "order_split_trace":
        from .agent_order_trace import order_split_trace_plan_request

        return order_split_trace_plan_request(card)
    if composite == "promotion_performance":
        from .agent_promotion_performance import promotion_performance_plan_request

        return promotion_performance_plan_request(card)
    return {"name": composite}


def _handoff_requirements(
    card: Mapping[str, Any], kind: str
) -> tuple[list[str], dict[str, Any]]:
    product = _composite_product_requirements(card, kind)
    if product is not None:
        return product
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


def _composite_product_requirements(
    card: Mapping[str, Any], kind: str
) -> tuple[list[str], dict[str, Any]] | None:
    if kind != "composite":
        return None
    if card.get("composite") == "multidim":
        from .agent_multidim import multidim_input_template

        return ["app", "inputs"], multidim_input_template()
    if card.get("composite") == "business_pulse":
        from .agent_business_pulse import (
            BUSINESS_PULSE_REQUIRED_INPUTS,
            business_pulse_input_template,
        )

        return list(BUSINESS_PULSE_REQUIRED_INPUTS), business_pulse_input_template()
    if card.get("composite") == "material_performance":
        from .agent_material_performance import material_performance_input_template

        return ["apps", "start", "end"], material_performance_input_template()
    if card.get("composite") == "monetization_detail":
        from .agent_monetization_guard import (
            MONETIZATION_DETAIL_REQUIRED_INPUTS,
            monetization_detail_input_template,
        )

        return (
            list(MONETIZATION_DETAIL_REQUIRED_INPUTS),
            monetization_detail_input_template(),
        )
    if card.get("composite") == "order_directory":
        from .agent_order_directory import (
            ORDER_DIRECTORY_REQUIRED_INPUTS,
            order_directory_input_template,
        )

        return (
            list(ORDER_DIRECTORY_REQUIRED_INPUTS),
            order_directory_input_template(),
        )
    if card.get("composite") == "order_split_trace":
        from .agent_order_trace import (
            ORDER_SPLIT_TRACE_REQUIRED_INPUTS,
            order_split_trace_input_template,
        )

        return (
            list(ORDER_SPLIT_TRACE_REQUIRED_INPUTS),
            order_split_trace_input_template(),
        )
    if card.get("composite") == "promotion_performance":
        from .agent_promotion_performance import (
            PROMOTION_PERFORMANCE_REQUIRED_INPUTS,
            promotion_performance_input_template,
        )

        return (
            list(PROMOTION_PERFORMANCE_REQUIRED_INPUTS),
            promotion_performance_input_template(),
        )
    return None


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
    "is_analysis_task_handoff_query",
    "resolve_workspace_path",
    "unify_capability_candidates",
    "workspace_prefix",
]


_plan_request_without_period_compare = _plan_request


def _plan_request(
    card: Mapping[str, Any], query: str, kind: str, selector: str
) -> tuple[dict[str, Any], str]:
    request, plan_kind = _plan_request_without_period_compare(
        card, query, kind, selector
    )
    if kind == "analysis_query_spec":
        for field in ("compare_start", "compare_end"):
            if card.get(field) is not None:
                request[field] = card[field]
    return request, plan_kind
