"""Dependency, compatibility, and effective-range gates for Semantic Registry."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from .semantic_contract import (
    SemanticContractError,
    effective_range,
    ranges_overlap,
)


def validate_semantic_graph(
    definitions: Sequence[Mapping[str, Any]],
    bindings: Sequence[Mapping[str, Any]],
) -> None:
    by_uri = _definitions_by_uri(definitions)
    graph: dict[str, set[str]] = defaultdict(set)
    for item in definitions:
        _validate_definition(item, by_uri, graph)
    _reject_cycles(graph)
    for item in bindings:
        _validate_binding(item["contract"], by_uri)


def semantic_conflicts(
    definitions: Sequence[Mapping[str, Any]],
    bindings: Sequence[Mapping[str, Any]],
) -> dict[str, list[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    _collect_definition_conflicts(definitions, result)
    _collect_binding_conflicts(bindings, result)
    return {uri: sorted(reasons) for uri, reasons in result.items()}


def _definitions_by_uri(
    definitions: Sequence[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    result: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in definitions:
        result[item["contract"]["uri"]].append(item)
    return result


def _validate_definition(
    item: Mapping[str, Any],
    by_uri: Mapping[str, Sequence[Mapping[str, Any]]],
    graph: dict[str, set[str]],
) -> None:
    definition = item["contract"]
    entity_uri = definition["entity_uri"]
    if entity_uri is not None:
        _covered_candidates(
            definition,
            entity_uri,
            by_uri,
            expected_kind="entity",
            kind_reason="SEMANTIC_ENTITY_CONFLICT",
            missing_message="Semantic entity dependency does not cover the Definition range",
        )
    formula = definition["formula"]
    if formula is None:
        return
    dependencies = _formula_dependencies(item, by_uri, graph)
    _validate_formula_contract(definition, dependencies)


def _formula_dependencies(
    item: Mapping[str, Any],
    by_uri: Mapping[str, Sequence[Mapping[str, Any]]],
    graph: dict[str, set[str]],
) -> list[Mapping[str, Any]]:
    definition = item["contract"]
    dependencies: list[Mapping[str, Any]] = []
    for uri in definition["formula"]["dependencies"]:
        candidates = _covered_candidates(
            definition,
            uri,
            by_uri,
            expected_kind="metric",
            kind_reason="SEMANTIC_FORMULA_INVALID",
            missing_message="Formula dependency does not cover the Definition range",
        )
        dependencies.extend(candidate["contract"] for candidate in candidates)
        graph[item["digest"]].update(candidate["digest"] for candidate in candidates)
    return dependencies


def _covered_candidates(
    definition: Mapping[str, Any],
    uri: str,
    by_uri: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    expected_kind: str,
    kind_reason: str,
    missing_message: str,
) -> list[Mapping[str, Any]]:
    candidates = _active_dependencies(definition, uri, by_uri)
    ranges = [candidate["contract"]["effective_range"] for candidate in candidates]
    if not candidates or not _ranges_cover(definition["effective_range"], ranges):
        raise SemanticContractError("SEMANTIC_DEPENDENCY_MISSING", missing_message)
    if any(candidate["contract"]["kind"] != expected_kind for candidate in candidates):
        raise SemanticContractError(
            kind_reason,
            f"Semantic dependency must reference {expected_kind.title()} Definitions",
        )
    return candidates


def _validate_binding(
    binding: Mapping[str, Any],
    by_uri: Mapping[str, Sequence[Mapping[str, Any]]],
) -> None:
    candidates = [
        candidate
        for candidate in by_uri.get(binding["semantic_uri"], ())
        if ranges_overlap(
            candidate["contract"]["effective_range"], binding["effective_range"]
        )
    ]
    ranges = [candidate["contract"]["effective_range"] for candidate in candidates]
    if not candidates or not _ranges_cover(binding["effective_range"], ranges):
        raise SemanticContractError(
            "SEMANTIC_DEPENDENCY_MISSING",
            "Binding Definition does not cover the Binding range",
        )
    if any(not candidate["contract"]["binding_required"] for candidate in candidates):
        raise SemanticContractError(
            "SEMANTIC_BINDING_INVALID",
            "Binding targets a Definition that does not require a Binding",
        )
    _validate_binding_parameters(binding, candidates)


def _validate_binding_parameters(
    binding: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]
) -> None:
    parameter_sets = {
        tuple(formula["parameters"] if formula is not None else ())
        for formula in (candidate["contract"]["formula"] for candidate in candidates)
    }
    expected = next(iter(parameter_sets), ())
    if len(parameter_sets) != 1 or set(binding["parameters"]) != set(expected):
        raise SemanticContractError(
            "SEMANTIC_PARAMETER_BINDING_INVALID",
            "Binding parameters disagree with Definition formula",
        )


def _validate_formula_contract(
    definition: Mapping[str, Any], dependencies: Sequence[Mapping[str, Any]]
) -> None:
    operator = definition["formula"]["operator"]
    if operator == "source":
        return
    _validate_formula_units(definition, dependencies, operator)
    _validate_formula_additivity(definition, dependencies, operator)
    _validate_formula_scope(definition, dependencies)


def _validate_formula_units(
    definition: Mapping[str, Any],
    dependencies: Sequence[Mapping[str, Any]],
    operator: str,
) -> None:
    comparison = dependencies[0]["unit"] if operator == "ratio" else definition["unit"]
    if any(
        _unit_without_currency(item["unit"]) != _unit_without_currency(comparison)
        for item in dependencies
    ):
        raise SemanticContractError("SEMANTIC_UNIT_CONFLICT", "formula units disagree")
    if any(item["unit"]["currency"] != comparison["currency"] for item in dependencies):
        raise SemanticContractError(
            "SEMANTIC_CURRENCY_CONFLICT", "formula currencies disagree"
        )


def _validate_formula_additivity(
    definition: Mapping[str, Any],
    dependencies: Sequence[Mapping[str, Any]],
    operator: str,
) -> None:
    if operator not in {"sum", "difference"}:
        return
    additive_output = definition["aggregation"]["additivity"] == "additive"
    if additive_output and any(
        item["aggregation"]["additivity"] != "additive" for item in dependencies
    ):
        raise SemanticContractError(
            "SEMANTIC_ADDITIVITY_CONFLICT",
            "additive output depends on non-additive input",
        )


def _validate_formula_scope(
    definition: Mapping[str, Any], dependencies: Sequence[Mapping[str, Any]]
) -> None:
    if any(item["entity_uri"] != definition["entity_uri"] for item in dependencies):
        raise SemanticContractError(
            "SEMANTIC_ENTITY_CONFLICT", "formula entity dependencies disagree"
        )
    output_grains = set(definition["time"]["grains"])
    if any(not output_grains.issubset(item["time"]["grains"]) for item in dependencies):
        raise SemanticContractError(
            "SEMANTIC_TIME_GRAIN_CONFLICT", "formula time grains are incompatible"
        )
    if any(item["time"]["timezone"] != definition["time"]["timezone"] for item in dependencies):
        raise SemanticContractError(
            "SEMANTIC_TIMEZONE_CONFLICT", "formula timezones disagree"
        )
    if any(
        item["time"]["attribution_window"] != definition["time"]["attribution_window"]
        for item in dependencies
    ):
        raise SemanticContractError(
            "SEMANTIC_ATTRIBUTION_WINDOW_CONFLICT",
            "formula attribution windows disagree",
        )


def _reject_cycles(graph: Mapping[str, set[str]]) -> None:
    visiting: set[str] = set()
    complete: set[str] = set()

    def visit(uri: str) -> None:
        if uri in complete:
            return
        if uri in visiting:
            raise SemanticContractError(
                "SEMANTIC_FORMULA_CYCLE", "Semantic formula graph contains a cycle"
            )
        visiting.add(uri)
        for dependency in graph.get(uri, set()):
            visit(dependency)
        visiting.remove(uri)
        complete.add(uri)

    for uri in graph:
        visit(uri)


def _active_dependencies(
    definition: Mapping[str, Any],
    uri: str,
    by_uri: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[Mapping[str, Any]]:
    return [
        candidate
        for candidate in by_uri.get(uri, ())
        if ranges_overlap(
            definition["effective_range"], candidate["contract"]["effective_range"]
        )
    ]


def _ranges_cover(
    required: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]
) -> bool:
    required_start, required_end = effective_range(required)
    target_start = required_start or date.min
    target_end = required_end or date.max
    intervals = sorted(
        (
            (start or date.min, end or date.max)
            for start, end in (effective_range(item) for item in candidates)
        ),
        key=lambda item: (item[0], item[1]),
    )
    cursor = target_start
    for start, end in intervals:
        if end < cursor:
            continue
        if start > cursor:
            return False
        if end >= target_end:
            return True
        cursor = end + timedelta(days=1)
    return False


def _unit_without_currency(unit: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in unit.items() if key != "currency"}


def _collect_definition_conflicts(
    definitions: Sequence[Mapping[str, Any]], result: dict[str, set[str]]
) -> None:
    for uri, values in _definitions_by_uri(definitions).items():
        for index, left in enumerate(values):
            for right in values[index + 1 :]:
                if ranges_overlap(
                    left["contract"]["effective_range"],
                    right["contract"]["effective_range"],
                ):
                    result[uri].add("SEMANTIC_DEFINITION_CONFLICT")


def _collect_binding_conflicts(
    bindings: Sequence[Mapping[str, Any]], result: dict[str, set[str]]
) -> None:
    groups: dict[tuple[str, str, str | None], list[Mapping[str, Any]]] = defaultdict(list)
    for item in bindings:
        contract = item["contract"]
        groups[(contract["semantic_uri"], contract["project_id"], contract["app_alias"])].append(item)
    for (uri, _project, _app), values in groups.items():
        for index, left in enumerate(values):
            for right in values[index + 1 :]:
                if ranges_overlap(
                    left["contract"]["effective_range"],
                    right["contract"]["effective_range"],
                ):
                    result[uri].add("SEMANTIC_BINDING_CONFLICT")


__all__ = ["semantic_conflicts", "validate_semantic_graph"]
