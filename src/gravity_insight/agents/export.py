"""Fail-closed Agent discovery for governed export job creators."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from .intent_text import affirmative_intent_text


_CREATE_EFFECT = "export_job_create"
_GENERIC_INTENTS = frozenset({
    "export",
    "data export",
    "export data",
    "导出",
    "数据导出",
    "导出数据",
})
_MATERIAL_ALIASES = (
    "material export",
    "export material",
    "material report export",
    "export material report",
    "creative report export",
    "export creative report",
    "素材导出",
    "导出素材",
    "素材报表导出",
    "导出素材报表",
    "素材数据导出",
    "导出素材数据",
)
_USER_EVENT_OPERATION = "export.analysis.user_event.start"
_USER_EVENT_ALIASES = (
    "user event export",
    "export user event",
    "export user events",
    "export user event results",
    "event timeline export",
    "export event timeline",
    "用户事件导出",
    "导出用户事件",
    "导出用户事件结果",
    "事件时间线导出",
    "导出事件时间线",
)
_ANALYSIS_EXPORT_ALIASES = {
    _USER_EVENT_OPERATION: _USER_EVENT_ALIASES,
    "export.analysis.segment.result.start": (
        "segment result export", "export segment result", "分群结果导出", "导出分群结果",
    ),
    "export.analysis.segment_user_detail.start": (
        "segment user detail export", "segment member export", "分群用户明细导出", "分群成员导出",
    ),
    "export.analysis.user_detail.start": (
        "user detail export", "export user details", "用户明细导出", "导出用户明细",
    ),
    "export.analysis.pay_event.start": (
        "pay event export", "payment detail export", "付费事件导出", "订单明细导出",
    ),
    "export.analysis.monetization_detail.start": (
        "monetization detail export",
        "export monetization detail",
        "export monetization details",
        "变现明细导出",
        "导出变现明细",
    ),
    "export.analysis.origin_event.start": (
        "origin event export",
        "export origin event",
        "export origin events",
        "raw event export",
        "export raw events",
        "自然事件导出",
        "原始事件导出",
        "导出自然事件",
        "导出原始事件",
    ),
}
_EXPORT_DESCRIPTIONS = {
    _USER_EVENT_OPERATION: "创建、轮询并原子下载受治理的单用户事件文件。",
    "export.analysis.segment.result.start": "创建、轮询并原子下载受治理的分群结果文件。",
    "export.analysis.segment_user_detail.start": "创建、轮询并原子下载受治理的分群用户明细文件。",
    "export.analysis.user_detail.start": "创建、轮询并原子下载受治理的用户明细文件。",
    "export.analysis.pay_event.start": "创建、轮询并原子下载受治理的付费事件文件。",
    "export.analysis.monetization_detail.start": (
        "创建、轮询并原子下载受治理的变现明细文件；超限时标注 truncated 并给出创建时钉住的总量。"
    ),
    "export.analysis.origin_event.start": (
        "创建、轮询并原子下载受治理的原始事件 gzip CSV；提交前须有正数 evaluate。"
    ),
}
_EXPORT_FAMILY_BOUNDARY = "宽问法不能解析成这一条；七个子类输入不可互换。"
_EXPORT_BOUNDARIES = {
    _USER_EVENT_OPERATION: (
        "只导出单用户事件，不导出分群、用户明细、付费或变现文件。",
        _EXPORT_FAMILY_BOUNDARY,
    ),
    "export.analysis.segment.result.start": (
        "只导出分群结果，不导出分群用户明细或单用户事件。",
        _EXPORT_FAMILY_BOUNDARY,
    ),
    "export.analysis.segment_user_detail.start": (
        "只导出分群用户明细，不导出分群结果或用户明细。",
        _EXPORT_FAMILY_BOUNDARY,
    ),
    "export.analysis.user_detail.start": (
        "只导出用户明细，不导出单用户事件或分群用户明细。",
        _EXPORT_FAMILY_BOUNDARY,
    ),
    "export.analysis.pay_event.start": (
        "只导出付费事件，不导出变现明细或普通用户事件。",
        _EXPORT_FAMILY_BOUNDARY,
    ),
    "export.analysis.monetization_detail.start": (
        "只导出变现明细文件，不是按平台广告位聚合的变现报表。",
        "超限时标注 truncated，不假装完整。",
    ),
    "export.analysis.origin_event.start": (
        "只导出原始事件 gzip CSV；提交前须有正数 evaluate。",
        _EXPORT_FAMILY_BOUNDARY,
    ),
    "export.material.report.start": (
        "只导出素材报表文件，不下载单个素材 URL。",
        "不用于分析导出七个子类。",
    ),
}
MATERIAL_EXPORT_OPERATION = ".".join(("export", "material", "report", "start"))
_MATERIAL_OPERATION = MATERIAL_EXPORT_OPERATION
_SPACE = re.compile(r"[^a-z0-9_.]+", re.IGNORECASE)


def query_requests_export(query: str) -> bool:
    """Recognize explicit export intent without guessing a different product."""

    query = affirmative_intent_text(query)
    selected = query.strip().casefold()
    normalized = _normalize(query)
    return (
        selected.startswith("export.")
        or normalized in _GENERIC_INTENTS
        or any(_contains_alias(query, alias) for alias in _MATERIAL_ALIASES)
        or _analysis_export_match(query)
        or _material_export_workflow(query)
        or _material_file_export(query)
        or "导出" in selected
    )


def load_export_agent_inventory(client: Any) -> tuple[Mapping[str, Any], ...]:
    """Snapshot descriptions for callable create effects once, entirely offline."""

    capabilities = getattr(client, "export_capabilities", None)
    describe = getattr(client, "export_describe", None)
    if not callable(capabilities) or not callable(describe):
        return ()
    result = capabilities()
    operations = result.get("operations", []) if isinstance(result, Mapping) else []
    selected: list[Mapping[str, Any]] = []
    for item in operations if isinstance(operations, list) else ():
        if not _callable_creator(item):
            continue
        operation_id = str(item["operation_id"])
        description = describe(operation_id)
        if (
            isinstance(description, Mapping)
            and str(description.get("operation_id", "")) == operation_id
            and _callable_creator(description)
        ):
            selected.append(dict(description))
    return tuple(sorted(selected, key=lambda item: str(item["operation_id"])))


def export_inventory_for_query(
    query: str,
    *,
    client: Any | None,
    inventory: Sequence[Mapping[str, Any]] | None,
) -> Sequence[Mapping[str, Any]]:
    """Reuse a batch snapshot, or lazily load a single explicit export query."""

    from .discovery_policy import operation_fallback_excluded

    if operation_fallback_excluded(query):
        return ()
    if inventory is not None:
        return inventory
    if client is None or not query_requests_export(query):
        return ()
    return load_export_agent_inventory(client)


def export_capability_cards(
    query: str,
    *,
    domain: str | None,
    platform: str | None,
    inventory: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Build direct ``gravity export run`` cards from the safe snapshot."""

    if platform is not None or domain not in {
        None, "analysis", "export", "material", "report"
    }:
        return []
    cards = [
        card
        for description in inventory
        if (card := _export_card(query, description)) is not None
    ]
    return sorted(
        cards,
        key=lambda card: (
            not bool(card["match"].get("exact_selector")),
            not bool(card["match"].get("specific_intent")),
            card["selector"] != "export.material.report.start",
            str(card["selector"]),
        ),
    )


def export_capability_inventory(client: Any) -> tuple[dict[str, Any], ...]:
    """Materialize every currently callable export card from export contracts."""

    descriptions = load_export_agent_inventory(client)
    cards = [
        _export_card(str(item["operation_id"]), item)
        for item in descriptions
    ]
    if any(card is None for card in cards):
        raise RuntimeError("callable export inventory cannot reproduce its Agent cards")
    return tuple(card for card in cards if card is not None)


def analysis_export_family_choices() -> list[dict[str, Any]]:
    """Project exact Analysis families for a non-executable selection handoff."""

    from ..export_contracts import ExportContractRegistry
    from ..paths import CONTRACT_ROOT

    contracts = ExportContractRegistry.from_file(
        CONTRACT_ROOT / "exports" / "routes-v1.json"
    )
    choices: list[dict[str, Any]] = []
    for selector in _ANALYSIS_EXPORT_ALIASES:
        description = contracts.describe(selector)
        if not _callable_creator(description):
            raise RuntimeError(
                f"Analysis export selection references a non-callable family: {selector}"
            )
        required = _required_request_fields(
            _plain_mapping(description.get("input_schema"))
        )
        choices.append({
            "selector": selector,
            "currently_callable": True,
            "request_required_fields": required,
            "next_action": (
                "Run next.argv to select this exact family, then inspect "
                "next.schema_argv and supply only that contract's inputs."
            ),
            "next": {
                "ready_without_input": True,
                "argv": ["gravity", "agent", selector],
                "schema_argv": ["gravity", "export", "describe", selector],
            },
        })
    return choices


def is_authoritative_export_card(card: Mapping[str, Any]) -> bool:
    return (
        card.get("kind") == "export"
        and card.get("currently_callable") is True
        and card.get("effect") == _CREATE_EFFECT
    )


def _export_card(
    query: str, description: Mapping[str, Any]
) -> dict[str, Any] | None:
    if not _callable_creator(description):
        return None
    operation_id = str(description["operation_id"])
    query = affirmative_intent_text(query)
    selected = query.strip().casefold()
    exact = selected == operation_id.casefold()
    generic = _normalize(query) in _GENERIC_INTENTS
    material = (
        any(_contains_alias(query, alias) for alias in _MATERIAL_ALIASES)
        or _material_export_workflow(query)
        or _material_file_export(query)
    )
    route_match = (
        material
        if operation_id == _MATERIAL_OPERATION
        else _analysis_export_match(query, operation_id)
    )
    if not (exact or generic or route_match):
        return None
    input_schema = _plain_mapping(description.get("input_schema"))
    columns = _plain_mapping(description.get("columns"))
    workflow = _plain_mapping(description.get("workflow"))
    examples = _plain_examples(description.get("examples"))
    request_required = _required_request_fields(input_schema)
    idempotency_template = _idempotency_template(examples)
    return {
        "kind": "export",
        "selector": operation_id,
        "operation_id": operation_id,
        "domain": "export",
        "description": _EXPORT_DESCRIPTIONS.get(
            operation_id, "创建、轮询并原子下载受治理的素材报表文件。"
        ),
        "boundaries": _EXPORT_BOUNDARIES[operation_id],
        "effect": _CREATE_EFFECT,
        "executable": True,
        "currently_callable": True,
        "natural_language_auto_execute": False,
        "plan_executable": False,
        "execution_mode": "direct_export_run_after_explicit_inputs",
        "input_schema": input_schema,
        "request_required_fields": request_required,
        "required_inputs": ["input", "columns", "idempotency_key", "output"],
        "missing_inputs": ["input", "columns", "idempotency_key", "output"],
        "input_template": {
            "input": "<request.json>",
            "columns": "<comma-separated-column-codes>",
            "idempotency_key": idempotency_template or "<unique-key>",
            "output": _output_placeholder(columns.get("format")),
            "timeout_seconds": 300,
        },
        "columns": columns,
        "idempotency": {
            "required": True,
            "template": idempotency_template,
            "create_auto_retry": False,
        },
        "output": {
            "required": True,
            "format": columns.get("format"),
            "atomic_commit": True,
        },
        "timeout": {
            "default_seconds": 300,
            "maximum_seconds": 300,
            "auto_cancel": bool(workflow.get("timeout_auto_cancel", False)),
        },
        "examples": examples,
        "match": _export_match(operation_id, exact, route_match),
        "next": {
            "ready_without_input": False,
            "argv": _run_argv(operation_id, columns.get("format")),
            "schema_argv": ["gravity", "export", "describe", operation_id],
            "call_count_after_discovery": 1,
        },
    }


def _plain_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _plain_examples(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _required_request_fields(input_schema: Mapping[str, Any]) -> list[str]:
    value = input_schema.get("required")
    return [str(item) for item in value] if isinstance(value, list) else []


def _idempotency_template(examples: Sequence[Any]) -> Any:
    first = examples[0] if examples else None
    return first.get("idempotency_key_template") if isinstance(first, Mapping) else None


def _export_match(
    operation_id: str, exact: bool, specific_intent: bool
) -> dict[str, Any]:
    return {
        "confidence": "strong",
        "coverage": 1.0,
        "matched_terms": [operation_id if exact else "export"],
        "missing_terms": [],
        "score": 100,
        "exact_selector": exact,
        "specific_intent": specific_intent,
        "intent_only": not exact,
    }


def _output_placeholder(file_format: Any) -> str:
    if file_format == "csv":
        return "<writable-file.csv>"
    return "<writable-file.xlsx>"


def _run_argv(operation_id: str, file_format: Any = None) -> list[str]:
    return [
        "gravity", "export", "run", operation_id,
        "--input", "<request.json>",
        "--columns", "<comma-separated-column-codes>",
        "--idempotency-key", "<unique-key>",
        "--output", _output_placeholder(file_format),
        "--timeout", "300",
    ]


def _callable_creator(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and bool(value.get("operation_id"))
        and value.get("currently_callable") is True
        and value.get("effect") == _CREATE_EFFECT
    )


def _normalize(value: str) -> str:
    if value.isascii():
        return " ".join(_SPACE.sub(" ", value.strip().casefold()).split())
    return "".join(value.strip().casefold().split())


def _contains_alias(query: str, alias: str) -> bool:
    if alias.isascii():
        return f" {_normalize(alias)} " in f" {_normalize(query)} "
    return alias in "".join(query.strip().casefold().split())


def _material_export_workflow(query: str) -> bool:
    selected = query.strip().casefold()
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    english = (
        (
            bool(words & {"material", "creative"})
            or ("素材" in selected)
        )
        and bool(words & {"report"})
        and bool(words & {"create", "generate"})
        and bool(words & {"download", "save"})
    )
    chinese = (
        "素材" in selected
        and ("报表" in selected or "分析" in selected and "文件" in selected)
        and any(term in selected for term in ("生成", "创建"))
        and any(term in selected for term in ("下载", "保存到本地"))
    )
    return english or chinese


def material_export_capability_cards(
    query: str, *, domain: str | None = None, platform: str | None = None
) -> list[dict[str, Any]]:
    """Index the governed material-report export without a live export client."""

    if platform is not None or domain not in {None, "analysis", "export", "material", "report"}:
        return []
    selected = affirmative_intent_text(query)
    exact = selected.strip().casefold() == _MATERIAL_OPERATION
    if not exact and not (
        any(_contains_alias(selected, alias) for alias in _MATERIAL_ALIASES)
        or _material_export_workflow(selected)
        or _material_file_export(selected)
    ):
        return []
    return [
        {
            "kind": "export",
            "selector": _MATERIAL_OPERATION,
            "operation_id": _MATERIAL_OPERATION,
            "domain": "export",
            "description": "创建、轮询并原子下载受治理的素材报表文件。",
            "boundaries": _EXPORT_BOUNDARIES[_MATERIAL_OPERATION],
            "effect": _CREATE_EFFECT,
            "executable": True,
            "currently_callable": True,
        }
    ]


def _material_file_export(query: str) -> bool:
    selected = affirmative_intent_text(query)
    words = frozenset(re.findall(r"[a-z0-9_]+", selected))
    english = (
        bool(words & {"creative", "material"}) and "export" in words
        and bool(words & {"data", "file", "report"})
    )
    chinese = (
        "素材" in selected and "导出" in selected
        and any(term in selected for term in ("文件", "数据", "报表"))
    )
    return english or chinese


def _user_event_export(query: str) -> bool:
    selected = affirmative_intent_text(query)
    return any(_contains_alias(selected, alias) for alias in _USER_EVENT_ALIASES)


def _analysis_export_match(query: str, operation_id: str | None = None) -> bool:
    normalized = _normalize(query)
    exact_operations = {
        candidate
        for candidate, values in _ANALYSIS_EXPORT_ALIASES.items()
        if any(_normalize(alias) == normalized for alias in values)
    }
    if operation_id is not None and exact_operations:
        return operation_id in exact_operations
    aliases = (
        _ANALYSIS_EXPORT_ALIASES.get(operation_id, ())
        if operation_id is not None
        else tuple(
            alias
            for values in _ANALYSIS_EXPORT_ALIASES.values()
            for alias in values
        )
    )
    return any(_contains_alias(query, alias) for alias in aliases)


def analysis_export_is_specific(query: str) -> bool:
    return _analysis_export_match(query)


__all__ = [
    "MATERIAL_EXPORT_OPERATION",
    "analysis_export_family_choices",
    "analysis_export_is_specific",
    "export_capability_cards",
    "export_capability_inventory",
    "export_inventory_for_query",
    "is_authoritative_export_card",
    "load_export_agent_inventory",
    "material_export_capability_cards",
    "query_requests_export",
]
