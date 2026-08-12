"""Intent-first Agent cards for the compact Analysis Query Spec contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import re
from typing import Any

from .analysis_spec_schema import analysis_query_spec_schema
from .find import query_match


_ANALYSIS_KINDS = ("event", "funnel", "property", "retention", "scatter")
_INTENT_ALIASES: Mapping[str, tuple[str, ...]] = {
    "event": (
        "event analysis",
        "event analytics",
        "analyse events",
        "analyze events",
        "事件分析",
        "事件查询",
        "事件趋势分析",
    ),
    "funnel": (
        "funnel analysis",
        "funnel analytics",
        "funnel query spec",
        "conversion funnel analysis",
        "analyse funnel",
        "analyze funnel",
        "漏斗分析",
        "转化漏斗",
    ),
    "property": (
        "property analysis",
        "attribute analysis",
        "property query spec",
        "analyse properties",
        "analyze properties",
        "属性分析",
        "用户属性分析",
    ),
    "retention": (
        "retention analysis",
        "retention analytics",
        "retention query spec",
        "cohort retention analysis",
        "analyse retention",
        "analyze retention",
        "留存分析",
        "用户留存",
    ),
    "scatter": (
        "scatter analysis",
        "scatter plot analysis",
        "scatter query spec",
        "analyse scatter",
        "analyze scatter",
        "散点分析",
        "散点图",
    ),
}
_GENERIC_ALIASES = (
    "analysis query",
    "analysis query spec",
    "analysis query compiler",
    "analysis query compile",
    "分析查询",
    "分析查询规格",
    "分析查询编译器",
    "查询规格",
    "查询编译",
)
_SPACE = re.compile(r"[^a-z0-9_.]+", re.IGNORECASE)
_REF = re.compile(r"^#/definitions/([^/]+)$")
_SPEC_CONTRACT = analysis_query_spec_schema()


def analysis_query_spec_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    """Return one type-focused Analysis Spec card for an explicit analysis intent."""

    if platform is not None or (domain is not None and domain != "analysis"):
        return []
    selected = _analysis_kind(query)
    if selected is not None:
        return [_analysis_card(query, selected)]
    if (
        _matches_alias(query, _GENERIC_ALIASES)
        or _normalized(query) == "analysis.query.spec"
    ):
        return [_analysis_card(query, None)]
    return []


def _analysis_kind(query: str) -> str | None:
    selector = query.strip().casefold()
    for kind in _ANALYSIS_KINDS:
        if selector == f"analysis.query.spec:{kind}":
            return kind
    matches = [
        kind
        for kind, aliases in _INTENT_ALIASES.items()
        if _matches_alias(query, aliases)
    ]
    return matches[0] if len(matches) == 1 else None


def _matches_alias(query: str, aliases: Sequence[str]) -> bool:
    normalized = _normalized(query)
    compact = query.strip().casefold()
    for alias in aliases:
        selected = alias.casefold()
        if selected.isascii():
            padded = f" {normalized.replace('.', ' ')} "
            if f" {_normalized(selected).replace('.', ' ')} " in padded:
                return True
        elif selected in compact:
            return True
    return False


def _normalized(value: str) -> str:
    return " ".join(_SPACE.sub(" ", value.strip().casefold()).split())


def _analysis_card(query: str, selected_kind: str | None) -> dict[str, Any]:
    contract = _SPEC_CONTRACT
    selector = (
        "analysis.query.spec"
        if selected_kind is None
        else f"analysis.query.spec:{selected_kind}"
    )
    required = ["kind", "app", "spec"] if selected_kind is None else ["app", "spec"]
    card: dict[str, Any] = {
        "kind": "analysis_query_spec",
        "selector": selector,
        "compiler": "analysis_query",
        "analysis_kind": selected_kind,
        "domain": "analysis",
        "description": _description(selected_kind),
        "effect": "read",
        "executable": True,
        "compiler_callable": True,
        "plan_executable": True,
        "natural_language_auto_execute": False,
        "execution_mode": "plan_after_explicit_spec",
        "offline": True,
        "network_called": False,
        "kinds": [selected_kind] if selected_kind is not None else list(_ANALYSIS_KINDS),
        "input_schema": _input_schema(contract, selected_kind),
        "required_inputs": required,
        "missing_inputs": list(required),
        "input_template": _input_template(contract, selected_kind),
        "spec_schema_version": contract["schema_version"],
        "match": _intent_match(query, selector, selected_kind),
        "next": {
            "ready_without_input": False,
            "argv": ["gravity", "plan", "run", "--input", "<plan.json>"],
            "schema_argv": _schema_argv(selected_kind),
            "call_count_after_discovery": 1,
        },
    }
    return card


def _description(selected_kind: str | None) -> str:
    scope = "事件、漏斗、留存、属性或散点" if selected_kind is None else selected_kind
    return (
        f"用现有 Analysis Spec v1 合同描述{scope}分析，再由登记的 analysis_query "
        "composite 编译和执行；自然语言不会填充业务字段。"
    )


def _intent_match(
    query: str, selector: str, selected_kind: str | None
) -> dict[str, Any]:
    aliases = (
        _GENERIC_ALIASES
        if selected_kind is None
        else _INTENT_ALIASES[selected_kind]
    )
    match = query_match(query, selector, *aliases, score=100)
    normalized = _normalized(query)
    exact = normalized in {_normalized(selector), *(_normalized(alias) for alias in aliases)}
    return {
        **match,
        "confidence": "strong",
        "coverage": 1.0,
        "matched_terms": [selected_kind or "analysis query spec"],
        "missing_terms": [],
        "score": 100,
        "intent_only": True,
        "exact_selector": exact,
    }


def _input_schema(
    contract: Mapping[str, Any], selected_kind: str | None
) -> dict[str, Any]:
    kinds = list(_ANALYSIS_KINDS)
    kind_field: dict[str, Any] = {"type": "string", "required": True, "enum": kinds}
    spec_field: dict[str, Any] = {
        "type": "object",
        "required": True,
        "nullable": False,
        "schema_version": contract["schema_version"],
        "discriminator": "kind",
    }
    if selected_kind is None:
        spec_field["variants_by_kind"] = deepcopy(contract["kind_schemas"])
        spec_field["definitions"] = deepcopy(contract["definitions"])
    else:
        kind_field = {
            **kind_field,
            "required": False,
            "enum": [selected_kind],
            "const": selected_kind,
            "default": selected_kind,
        }
        schema = deepcopy(contract["kind_schemas"][selected_kind])
        spec_field["selected_kind"] = selected_kind
        spec_field["variants_by_kind"] = {selected_kind: schema}
        spec_field["definitions"] = _referenced_definitions(
            schema, contract["definitions"]
        )
    return {
        "kind": kind_field,
        "app": {
            "type": "string|integer",
            "required": True,
            "nullable": False,
        },
        "spec": spec_field,
    }


def _referenced_definitions(
    schema: Mapping[str, Any], definitions: Mapping[str, Any]
) -> dict[str, Any]:
    pending = list(_definition_refs(schema))
    selected: dict[str, Any] = {}
    while pending:
        name = pending.pop(0)
        if name in selected or name not in definitions:
            continue
        value = deepcopy(definitions[name])
        selected[name] = value
        pending.extend(ref for ref in _definition_refs(value) if ref not in selected)
    return {name: selected[name] for name in sorted(selected)}


def _definition_refs(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        refs: set[str] = set()
        reference = value.get("$ref")
        match = _REF.fullmatch(reference) if isinstance(reference, str) else None
        if match is not None:
            refs.add(match.group(1))
        for item in value.values():
            refs.update(_definition_refs(item))
        return refs
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return {ref for item in value for ref in _definition_refs(item)}
    return set()


def _input_template(
    contract: Mapping[str, Any], selected_kind: str | None
) -> dict[str, Any]:
    if selected_kind is None:
        return {
            "kind": "<event|funnel|property|retention|scatter>",
            "app": "<workspace-app-alias-or-positive-id>",
            "spec": "<gravity-insight.analysis-query-spec.v1 object>",
        }
    schema = contract["kind_schemas"][selected_kind]
    properties = schema.get("properties", {})
    spec = {
        name: _property_placeholder(name, properties.get(name))
        for name in schema.get("required", [])
    }
    return {
        "kind": selected_kind,
        "app": "<workspace-app-alias-or-positive-id>",
        "spec": spec,
    }


def _property_placeholder(name: str, value: Any) -> str:
    if not isinstance(value, Mapping):
        return f"<{name}:value>"
    selected_type = value.get("type")
    if selected_type is None and "$ref" in value:
        selected_type = str(value["$ref"]).rsplit("/", 1)[-1]
    return f"<{name}:{selected_type or 'value'}>"


def _schema_argv(selected_kind: str | None) -> list[str]:
    kind = selected_kind or "<kind>"
    return ["gravity", "analysis", "query", "--kind", kind, "--spec-schema"]


__all__ = ["analysis_query_spec_cards"]
