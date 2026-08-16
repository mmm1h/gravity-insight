"""Intent-first Agent cards for the compact Analysis Query Spec contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import re
from typing import Any

from .analysis_spec_schema import analysis_query_spec_schema
from .agent_intent_text import affirmative_intent_text
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
        "事件趋势",
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
        "属性分布",
        "属性的分布",
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
        "留存",
        "用户留存",
    ),
    "scatter": (
        "scatter analysis",
        "scatter plot analysis",
        "scatter query spec",
        "analyse scatter",
        "analyze scatter",
        "散点分析",
        "散点关系",
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
        or _period_compare_intent(query)
        or _normalized(query) == "analysis.query.spec"
    ):
        return [_analysis_card(query, None)]
    return []


def analysis_query_spec_inventory() -> tuple[dict[str, Any], ...]:
    """Materialize every canonical Analysis Spec card from its owner."""

    selectors = ("analysis.query.spec", *(
        f"analysis.query.spec:{kind}" for kind in _ANALYSIS_KINDS
    ))
    return tuple(
        analysis_query_spec_cards(selector, domain=None, platform=None)[0]
        for selector in selectors
    )


def _analysis_kind(query: str) -> str | None:
    query = affirmative_intent_text(query)
    selector = query.strip().casefold()
    for kind in _ANALYSIS_KINDS:
        if selector == f"analysis.query.spec:{kind}":
            return kind
    matches = [
        kind
        for kind, aliases in _INTENT_ALIASES.items()
        if _matches_alias(query, aliases)
    ]
    if len(matches) == 1:
        return matches[0]
    return _natural_analysis_kind(query)


def _natural_analysis_kind(query: str) -> str | None:
    """Recognize analyst-shaped tasks while keeping kind evidence explicit."""

    selected = query.strip().casefold()
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    compact = "".join(selected.split())
    claims = (
        ("event", _natural_event(words, compact)),
        ("funnel", _natural_funnel(words, compact)),
        ("retention", _natural_retention(words, compact)),
        ("property", _natural_property(words, compact)),
        ("scatter", _natural_scatter(words, compact)),
    )
    matched = [kind for kind, claimed in claims if claimed]
    return matched[0] if len(matched) == 1 else None


def _natural_event(words: frozenset[str], compact: str) -> bool:
    english = (
        bool(words & {"activity", "behavior", "event"})
        and bool(words & {"count", "counts", "frequency", "trend", "trends", "volume"})
        and bool(words & {"daily", "day", "week", "time", "channel"})
    )
    chinese = ("事件" in compact or "行为" in compact) and any(
        term in compact for term in ("每天", "每小时", "次数", "频次", "发生量", "趋势")
    )
    return english or chinese


def _natural_funnel(words: frozenset[str], compact: str) -> bool:
    explicit = "funnel" in words and bool(
        words & {"conversion", "convert", "step", "steps"}
    )
    staged_conversion = "conversion" in words and "from" in words and bool(
        words & {"through", "to"}
    )
    chinese = "转化" in compact and (
        "多步" in compact
        or "逐步" in compact
        or "步骤" in compact
        or "依次" in compact
        or compact.count("到") >= 2
    )
    return explicit or staged_conversion or chinese


def _natural_retention(words: frozenset[str], compact: str) -> bool:
    english = "retention" in words and len(words) >= 2 or (
        "return" in words and bool(words & {"rate", "rates"}) and "day" in words
    )
    chinese = any(
        term in compact
        for term in (
            "第1天", "第2天", "第7天", "第一天", "第二天", "第七天",
            "次日", "次周", "次月", "七日",
        )
    ) and any(term in compact for term in ("回来", "回访", "复访", "留存"))
    return english or chinese


def _natural_property(words: frozenset[str], compact: str) -> bool:
    english = (
        {"distribution", "users", "by"} <= words
        or {"property", "distribution"} <= words
    )
    chinese = (
        any(term in compact for term in ("用户", "会员", "访客", "人群"))
        and any(term in compact for term in ("分布", "占比", "比例", "构成", "集中"))
        and any(term in compact for term in ("属性", "城市", "省份", "渠道", "地区", "机型", "性别", "年龄"))
    )
    return english or chinese


def _natural_scatter(words: frozenset[str], compact: str) -> bool:
    explicit = "scatter" in words or "散点" in compact
    english = bool(words & {"relationship", "correlation"}) and (
        "between" in words or "versus" in words
    )
    chinese = (
        "关系" in compact and any(term in compact for term in ("和", "与", "之间"))
    ) or (
        any(term in compact for term in ("相关", "关联"))
        and any(term in compact for term in ("是否", "与", "之间"))
    )
    return explicit or english or chinese


def _period_compare_intent(query: str) -> bool:
    selected = affirmative_intent_text(query)
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    english = (
        bool(words & {"compare", "comparison"})
        and bool(words & {"week", "weeks", "month", "months", "period", "periods"})
        and "same" in words
        and bool(words & {"analysis", "definition", "spec"})
    )
    chinese = (
        any(term in selected for term in ("对比", "比较"))
        and any(term in selected for term in ("本周", "上周", "本月", "上月", "时期"))
        and any(term in selected for term in ("同一个", "同一份", "相同"))
        and "分析" in selected
    )
    return english or chinese or _same_definition_compare(selected)


def _same_definition_compare(selected: str) -> bool:
    return (
        any(term in selected for term in ("同口径", "相同口径"))
        and any(term in selected for term in ("跨期", "不同时期", "两个时期"))
        and any(term in selected for term in ("对照", "对比", "比较"))
    )


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
    if selected_kind in {"event", "funnel", "retention", "property"}:
        card["multi_app_batch"] = _multi_app_batch_template(
            selected_kind, card["input_template"]["spec"]
        )
    return card


def _multi_app_batch_template(kind: str, spec: Any) -> dict[str, Any]:
    return {
        "schema_version": "gravity.analysis-query-batch.v2",
        "queries": [{
            "id": kind,
            "kind": kind,
            "apps": ["<explicit-workspace-app-alias-or-positive-id>"],
            "spec": deepcopy(spec),
            "limits": {"max_items": 200},
        }],
        "max_expanded_components": 32,
        "all_apps_selector": False,
        "cross_app_aggregation": False,
    }


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


__all__ = ["analysis_query_spec_cards", "analysis_query_spec_inventory"]


def _with_period_compare(
    card: dict[str, Any], selected_kind: str | None, compare_requested: bool
) -> dict[str, Any]:
    """Advertise the optional two-window mode without inventing date values."""

    fields = card["input_schema"]
    for name in ("compare_start", "compare_end"):
        fields[name] = {
            "type": "string",
            "format": "date",
            "required": False,
            "paired_with": "compare_end" if name == "compare_start" else "compare_start",
        }
    card["optional_inputs"] = ["compare_start", "compare_end"]
    card["period_compare"] = {
        "schema_version": "gravity-insight.analysis-period-compare.v1",
        "same_spec_required": True,
        "explicit_windows_required": True,
        "supported_kinds": ["event", "funnel", "retention", "scatter"],
        "property_capability_gap": True,
    }
    if compare_requested:
        card["required_inputs"].extend(card["optional_inputs"])
        card["missing_inputs"].extend(card["optional_inputs"])
        card["input_template"].update(
            compare_start="<explicit-baseline-start-date>",
            compare_end="<explicit-baseline-end-date>",
        )
        if selected_kind == "property":
            card.update(
                executable=False,
                plan_executable=False,
                execution_mode="capability_gap",
                capability_gap=(
                    "property Analysis has no governed date-window input"
                ),
            )
    return card


_analysis_card_without_period_compare = _analysis_card


def _analysis_card(query: str, selected_kind: str | None) -> dict[str, Any]:
    return _with_period_compare(
        _analysis_card_without_period_compare(query, selected_kind),
        selected_kind,
        _period_compare_intent(query) or any(term in query.strip().casefold() for term in (
            "period compare", "compare analysis periods", "compare last week",
            "compare last month", "跨期对比", "对比上周", "对比上月",
            "比较本周和上周",
        )),
    )


_GENERIC_ALIASES = _GENERIC_ALIASES + (
    "analysis period compare",
    "compare analysis periods",
    "compare last week",
    "compare last month",
    "跨期对比",
    "对比上周",
    "对比上月",
    "比较本周和上周",
)
