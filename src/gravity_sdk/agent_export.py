"""Fail-closed Agent discovery for governed export job creators."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from .agent_intent_text import affirmative_intent_text


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
        or _user_event_export(query)
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

    from .agent_discovery_policy import operation_fallback_excluded

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
    user_event = operation_id == _USER_EVENT_OPERATION and _user_event_export(query)
    route_match = material if operation_id != _USER_EVENT_OPERATION else user_event
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
        "description": (
            "创建、轮询并原子下载受治理的单用户事件文件。"
            if operation_id == _USER_EVENT_OPERATION
            else "创建、轮询并原子下载受治理的素材报表文件。"
        ),
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
            "output": "<writable-file.xlsx>",
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
            "argv": _run_argv(operation_id),
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


def _run_argv(operation_id: str) -> list[str]:
    return [
        "gravity", "export", "run", operation_id,
        "--input", "<request.json>",
        "--columns", "<comma-separated-column-codes>",
        "--idempotency-key", "<unique-key>",
        "--output", "<writable-file.xlsx>",
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
        bool(words & {"material", "creative"})
        and bool(words & {"report"})
        and bool(words & {"create", "generate"})
        and bool(words & {"download", "save"})
    )
    chinese = (
        "素材" in selected
        and "报表" in selected
        and any(term in selected for term in ("生成", "创建"))
        and any(term in selected for term in ("下载", "保存到本地"))
    )
    return english or chinese


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


__all__ = [
    "export_capability_cards",
    "export_capability_inventory",
    "export_inventory_for_query",
    "is_authoritative_export_card",
    "load_export_agent_inventory",
    "query_requests_export",
]
