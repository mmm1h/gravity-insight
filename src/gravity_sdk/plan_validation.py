"""Offline structural and worst-case budget validation for Plan v1."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .plan import (
    DEFAULT_FOREACH_ITEMS,
    DEFAULT_MAX_ITEMS,
    DEFAULT_MAX_PAGES,
    DEFAULT_MAX_WORKERS,
    MAX_AGGREGATE_ITEMS,
    MAX_DECLARED_NODES,
    MAX_EXPANDED_NODES,
    MAX_FOREACH_ITEMS,
    MAX_WORKERS,
    NODE_KINDS,
    PLAN_SCHEMA_VERSION,
    Binding,
    Foreach,
    NodeLimits,
    PlanNode,
    PlanValidationError,
    ValidatedPlan,
)
from .plan_binding import validate_json, validate_pointer


_PLAN_FIELDS = frozenset({"schema_version", "nodes", "budget"})
_NODE_FIELDS = frozenset(
    {
        "id", "kind", "request", "depends_on", "bindings", "foreach", "limits",
        "output_fields", "call_bound",
    }
)
_BUDGET_FIELDS = frozenset({"max_workers", "max_total_items"})
_LIMIT_FIELDS = frozenset({"max_pages", "max_items"})
_BINDING_FIELDS = frozenset({"from", "source", "target"})
_FOREACH_FIELDS = frozenset({"from", "source", "target", "max_items"})
_CALL_BOUND_FIELDS = frozenset(
    {
        "schema_version", "unit", "known_inputs", "unknown_capability",
        "unknown_capability_assumes", "scenarios",
    }
)
_CALL_BOUND_SCENARIO_FIELDS = frozenset(
    {
        "id", "minimum_calls", "discovery_calls", "unknown_inputs",
        "input_sources", "selection", "catalog_status",
    }
)
_CALL_BOUND_SOURCE_FIELDS = frozenset(
    {
        "inputs", "kind", "selector", "cli_argv", "sdk_method",
        "depends_on_inputs", "depends_on_sources", "selectors",
    }
)
_NODE_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
_CALL_BOUND_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_CALL_BOUND_SOURCE_KINDS = frozenset(
    {"catalog_sync", "local_catalog", "upstream_catalog"}
)


def validate_plan(plan: Mapping[str, Any]) -> ValidatedPlan:
    if not isinstance(plan, Mapping):
        raise invalid("plan must be an object", "plan")
    reject_unknown(plan, _PLAN_FIELDS, "plan")
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise invalid("plan schema_version must be gravity.plan.v1", "schema_version")
    raw_nodes = _node_array(plan.get("nodes"))
    nodes = tuple(validate_node(value, index) for index, value in enumerate(raw_nodes))
    by_id = {node.node_id: node for node in nodes}
    if len(by_id) != len(nodes):
        raise invalid("plan node ids must be unique", "nodes")
    validate_graph(nodes, by_id)
    max_workers, max_total_items = validate_budget(plan.get("budget", {}))
    expanded, aggregate = worst_case(nodes)
    if expanded > MAX_EXPANDED_NODES:
        raise invalid(
            f"plan can expand to more than {MAX_EXPANDED_NODES} executions", "nodes"
        )
    aggregate_limit = min(max_total_items, MAX_AGGREGATE_ITEMS)
    if aggregate > aggregate_limit:
        raise invalid(
            f"plan aggregate max_items exceeds {aggregate_limit}",
            "budget.max_total_items",
        )
    return ValidatedPlan(
        nodes=nodes,
        max_workers=max_workers,
        max_total_items=max_total_items,
        max_expanded_nodes=expanded,
        max_aggregate_items=aggregate,
    )


def _node_array(value: Any) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise invalid("plan nodes must be an array", "nodes")
    if not value:
        raise invalid("plan requires at least one node", "nodes")
    if len(value) > MAX_DECLARED_NODES:
        raise invalid(f"plan declares more than {MAX_DECLARED_NODES} nodes", "nodes")
    return value


def validate_node(value: Any, index: int) -> PlanNode:
    field = f"nodes[{index}]"
    if not isinstance(value, Mapping):
        raise invalid("plan nodes must be objects", field)
    reject_unknown(value, _NODE_FIELDS, field)
    node_id = value.get("id")
    if not isinstance(node_id, str) or not _NODE_ID_RE.fullmatch(node_id):
        raise invalid("plan node id is invalid", f"{field}.id")
    kind = value.get("kind")
    if kind not in NODE_KINDS:
        raise invalid("plan node kind is unsupported", f"{field}.kind")
    request = value.get("request")
    if not isinstance(request, Mapping):
        raise invalid("plan node request must be an object", f"{field}.request")
    if "workspace" in request:
        raise invalid(
            "plan requests cannot override the bound workspace",
            f"{field}.request.workspace",
        )
    try:
        validate_json(request)
    except TypeError as exc:
        raise invalid("plan node request must contain only JSON values", f"{field}.request") from exc
    depends_on = string_array(value.get("depends_on", []), f"{field}.depends_on")
    bindings = validate_bindings(value.get("bindings", []), f"{field}.bindings")
    foreach = validate_foreach(value.get("foreach"), f"{field}.foreach")
    if foreach is not None and foreach.target in {item.target for item in bindings}:
        raise invalid("foreach and binding targets must be distinct", f"{field}.foreach.target")
    limits = validate_limits(value.get("limits", {}), f"{field}.limits")
    output_fields = string_array(
        value.get("output_fields", []), f"{field}.output_fields"
    )
    if any(not item.strip() for item in output_fields):
        raise invalid("output_fields must be non-empty strings", f"{field}.output_fields")
    if len(set(output_fields)) != len(output_fields):
        raise invalid("output_fields must be unique", f"{field}.output_fields")
    validate_call_bound(value.get("call_bound"), f"{field}.call_bound")
    return PlanNode(
        node_id=node_id,
        kind=str(kind),
        request=copy.deepcopy(dict(request)),
        depends_on=depends_on,
        bindings=bindings,
        foreach=foreach,
        limits=limits,
        output_fields=output_fields,
    )


def validate_call_bound(value: Any, field: str) -> None:
    """Validate the optional advisory contract without changing execution state."""

    if value is None:
        return
    if not isinstance(value, Mapping):
        raise invalid("call_bound must be an object", field)
    reject_unknown(value, _CALL_BOUND_FIELDS, field)
    if value.get("schema_version") != "gravity.agent-call-bound.v1":
        raise invalid("call_bound schema_version is invalid", f"{field}.schema_version")
    if value.get("unit") != "cli_or_sdk_invocation":
        raise invalid("call_bound unit is invalid", f"{field}.unit")
    for name in ("known_inputs", "unknown_capability"):
        bounded_int(value.get(name), 1, 16, f"{field}.{name}")
    if value.get("unknown_capability_assumes") != "required_inputs_known":
        raise invalid(
            "call_bound unknown_capability_assumes is invalid",
            f"{field}.unknown_capability_assumes",
        )
    scenarios = value.get("scenarios")
    if not _is_array(scenarios) or len(scenarios) > 16:
        raise invalid("call_bound scenarios must be a bounded array", f"{field}.scenarios")
    scenario_ids: set[str] = set()
    for index, scenario in enumerate(scenarios):
        scenario_id = validate_call_bound_scenario(
            scenario, f"{field}.scenarios[{index}]"
        )
        if scenario_id in scenario_ids:
            raise invalid("call_bound scenario ids must be unique", f"{field}.scenarios")
        scenario_ids.add(scenario_id)
    try:
        validate_json(value)
    except TypeError as exc:
        raise invalid("call_bound must contain only JSON values", field) from exc


def validate_call_bound_scenario(value: Any, field: str) -> str:
    if not isinstance(value, Mapping):
        raise invalid("call_bound scenarios must be objects", field)
    reject_unknown(value, _CALL_BOUND_SCENARIO_FIELDS, field)
    scenario_id = value.get("id")
    if not isinstance(scenario_id, str) or not _CALL_BOUND_ID_RE.fullmatch(scenario_id):
        raise invalid("call_bound scenario id is invalid", f"{field}.id")
    minimum = bounded_int(value.get("minimum_calls"), 2, 16, f"{field}.minimum_calls")
    discovery = bounded_int(
        value.get("discovery_calls"), 0, 15, f"{field}.discovery_calls"
    )
    if minimum != discovery + 2:
        raise invalid(
            "call_bound minimum_calls must equal discovery_calls plus two",
            f"{field}.minimum_calls",
        )
    unknown_inputs = call_bound_string_array(
        value.get("unknown_inputs"), f"{field}.unknown_inputs"
    )
    if value.get("selection") != "caller_exact":
        raise invalid("call_bound selection is invalid", f"{field}.selection")
    if value.get("catalog_status") not in {"any", "available", "missing"}:
        raise invalid(
            "call_bound catalog_status is invalid", f"{field}.catalog_status"
        )
    sources = value.get("input_sources")
    if not _is_array(sources) or not sources or len(sources) > 16:
        raise invalid(
            "call_bound input_sources must be a bounded non-empty array",
            f"{field}.input_sources",
        )
    covered: set[str] = set()
    selectors: set[str] = set()
    for index, source in enumerate(sources):
        source_inputs, selector, dependencies = validate_call_bound_source(
            source, f"{field}.input_sources[{index}]"
        )
        if selector in selectors:
            raise invalid(
                "call_bound input source selectors must be unique",
                f"{field}.input_sources[{index}].selector",
            )
        if not set(dependencies) <= selectors:
            raise invalid(
                "call_bound source dependency must precede the source",
                f"{field}.input_sources[{index}].depends_on_sources",
            )
        selectors.add(selector)
        covered.update(source_inputs)
    if not set(unknown_inputs) <= covered:
        raise invalid(
            "call_bound input sources must cover every unknown input",
            f"{field}.input_sources",
        )
    return scenario_id


def validate_call_bound_source(
    value: Any, field: str
) -> tuple[tuple[str, ...], str, tuple[str, ...]]:
    if not isinstance(value, Mapping):
        raise invalid("call_bound input sources must be objects", field)
    reject_unknown(value, _CALL_BOUND_SOURCE_FIELDS, field)
    inputs = call_bound_string_array(value.get("inputs"), f"{field}.inputs")
    if value.get("kind") not in _CALL_BOUND_SOURCE_KINDS:
        raise invalid("call_bound input source kind is invalid", f"{field}.kind")
    selector = value.get("selector")
    if not isinstance(selector, str) or not selector.strip() or len(selector) > 256:
        raise invalid("call_bound input source selector is invalid", f"{field}.selector")
    cli_argv = call_bound_string_array(
        value.get("cli_argv"), f"{field}.cli_argv", unique=False
    )
    if cli_argv[0] != "gravity":
        raise invalid("call_bound cli_argv must invoke gravity", f"{field}.cli_argv")
    sdk_method = value.get("sdk_method")
    if not isinstance(sdk_method, str) or not sdk_method.strip() or len(sdk_method) > 256:
        raise invalid("call_bound sdk_method is invalid", f"{field}.sdk_method")
    selectors = value.get("selectors")
    if selectors is not None:
        call_bound_string_array(selectors, f"{field}.selectors")
        if value.get("selector") != "gravity.batch.v1":
            raise invalid(
                "call_bound selectors require the batch selector",
                f"{field}.selectors",
            )
    call_bound_string_array(
        value.get("depends_on_inputs", []), f"{field}.depends_on_inputs", empty=True
    )
    dependencies = call_bound_string_array(
        value.get("depends_on_sources", []), f"{field}.depends_on_sources", empty=True
    )
    return inputs, selector, dependencies


def call_bound_string_array(
    value: Any, field: str, *, empty: bool = False, unique: bool = True
) -> tuple[str, ...]:
    selected = string_array(value, field)
    if (not empty and not selected) or len(selected) > 32:
        raise invalid("call_bound string array has invalid length", field)
    if (
        any(not item.strip() or len(item) > 256 for item in selected)
        or unique and len(set(selected)) != len(selected)
    ):
        raise invalid("call_bound string array contains invalid values", field)
    return selected


def validate_bindings(value: Any, field: str) -> tuple[Binding, ...]:
    if not _is_array(value):
        raise invalid("bindings must be an array", field)
    result: list[Binding] = []
    targets: set[str] = set()
    for index, item in enumerate(value):
        item_field = f"{field}[{index}]"
        if not isinstance(item, Mapping):
            raise invalid("bindings must be objects", item_field)
        reject_unknown(item, _BINDING_FIELDS, item_field)
        source_node = item.get("from")
        if not isinstance(source_node, str) or not source_node:
            raise invalid("binding from must be a node id", f"{item_field}.from")
        source = validate_pointer(item.get("source"), f"{item_field}.source", allow_root=True)
        target = validate_pointer(item.get("target"), f"{item_field}.target", allow_root=False)
        if target in targets:
            raise invalid("binding targets must be unique", f"{item_field}.target")
        targets.add(target)
        result.append(Binding(source_node, source, target))
    return tuple(result)


def validate_foreach(value: Any, field: str) -> Foreach | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise invalid("foreach must be an object", field)
    reject_unknown(value, _FOREACH_FIELDS, field)
    source_node = value.get("from")
    if not isinstance(source_node, str) or not source_node:
        raise invalid("foreach from must be a node id", f"{field}.from")
    source = validate_pointer(value.get("source"), f"{field}.source", allow_root=True)
    target = validate_pointer(value.get("target"), f"{field}.target", allow_root=False)
    maximum = bounded_int(
        value.get("max_items", DEFAULT_FOREACH_ITEMS),
        1,
        MAX_FOREACH_ITEMS,
        f"{field}.max_items",
    )
    return Foreach(source_node, source, target, maximum)


def validate_limits(value: Any, field: str) -> NodeLimits:
    if not isinstance(value, Mapping):
        raise invalid("node limits must be an object", field)
    reject_unknown(value, _LIMIT_FIELDS, field)
    return NodeLimits(
        max_pages=bounded_int(
            value.get("max_pages", DEFAULT_MAX_PAGES), 1, 1_000, f"{field}.max_pages"
        ),
        max_items=bounded_int(
            value.get("max_items", DEFAULT_MAX_ITEMS),
            1,
            MAX_AGGREGATE_ITEMS,
            f"{field}.max_items",
        ),
    )


def validate_budget(value: Any) -> tuple[int, int]:
    if not isinstance(value, Mapping):
        raise invalid("plan budget must be an object", "budget")
    reject_unknown(value, _BUDGET_FIELDS, "budget")
    return (
        bounded_int(
            value.get("max_workers", DEFAULT_MAX_WORKERS),
            1,
            MAX_WORKERS,
            "budget.max_workers",
        ),
        bounded_int(
            value.get("max_total_items", MAX_AGGREGATE_ITEMS),
            1,
            MAX_AGGREGATE_ITEMS,
            "budget.max_total_items",
        ),
    )


def validate_graph(nodes: tuple[PlanNode, ...], by_id: Mapping[str, PlanNode]) -> None:
    for node in nodes:
        validate_dependencies(node, by_id)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise invalid("plan dependency graph contains a cycle", "nodes")
        if node_id in visited:
            return
        visiting.add(node_id)
        for dependency in by_id[node_id].depends_on:
            visit(dependency)
        visiting.remove(node_id)
        visited.add(node_id)

    for node in nodes:
        visit(node.node_id)


def validate_dependencies(node: PlanNode, by_id: Mapping[str, PlanNode]) -> None:
    for dependency in node.depends_on:
        if dependency not in by_id:
            raise invalid("plan dependency is unknown", f"nodes.{node.node_id}.depends_on")
        if dependency == node.node_id:
            raise invalid("plan node cannot depend on itself", f"nodes.{node.node_id}.depends_on")
    if len(set(node.depends_on)) != len(node.depends_on):
        raise invalid("plan dependencies must be unique", f"nodes.{node.node_id}.depends_on")
    sources = [binding.source_node for binding in node.bindings]
    if node.foreach is not None:
        sources.append(node.foreach.source_node)
    if any(source not in node.depends_on for source in sources):
        raise invalid(
            "binding and foreach sources must be declared dependencies",
            f"nodes.{node.node_id}.depends_on",
        )


def worst_case(nodes: tuple[PlanNode, ...]) -> tuple[int, int]:
    multipliers = [
        node.foreach.max_items if node.foreach is not None else 1 for node in nodes
    ]
    return (
        sum(multipliers),
        sum(node.limits.max_items * multiplier for node, multiplier in zip(nodes, multipliers)),
    )


def string_array(value: Any, field: str) -> tuple[str, ...]:
    if not _is_array(value) or any(not isinstance(item, str) for item in value):
        raise invalid("field must be an array of strings", field)
    return tuple(value)


def bounded_int(value: Any, minimum: int, maximum: int, field: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise invalid(f"{field} must be between {minimum} and {maximum}", field)
    return value


def reject_unknown(value: Mapping[str, Any], allowed: frozenset[str], field: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise invalid(f"{field} contains an unknown field", f"{field}.{unknown[0]}")


def _is_array(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def invalid(message: str, field: str) -> PlanValidationError:
    return PlanValidationError(message, field=field)


__all__ = ["bounded_int", "validate_plan"]
