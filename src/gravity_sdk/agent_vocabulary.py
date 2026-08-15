"""Agent presentation rules for synchronized Analysis vocabulary rows."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import re
from typing import Any


WORKSPACE_VOCABULARY_KINDS = frozenset({
    "metric",
    "custom_metric",
    "metric_tag",
    "metric_tag_category",
    "media_enum",
    "template",
})

AUTHORITATIVE_LOCAL_METADATA_KINDS = frozenset({
    *WORKSPACE_VOCABULARY_KINDS,
    "table_lineage",
})

_KIND_TERMS: Mapping[str, tuple[str, ...]] = {
    "metric": (
        "metric",
        "metrics",
        "physical metric",
        "base metric",
        "report metric",
        "物理指标",
        "基础指标",
    ),
    "custom_metric": (
        "custom metric",
        "custom metrics",
        "custom_metric",
        "derived metric",
        "自定义指标",
    ),
    "metric_tag": (
        "metric tag",
        "metric tags",
        "metric_tag",
        "指标标签",
    ),
    "metric_tag_category": (
        "metric tag category",
        "metric tag categories",
        "metric_tag_category",
        "指标标签分类",
    ),
    "media_enum": (
        "media enum",
        "media enums",
        "media_enum",
        "媒体枚举",
    ),
    "template": (
        "template",
        "templates",
        "analysis template",
        "report template",
        "分析模板",
        "报表模板",
    ),
}


def is_workspace_vocabulary(item: Mapping[str, Any]) -> bool:
    return str(item.get("kind", "")) in WORKSPACE_VOCABULARY_KINDS


def is_vocabulary_discovery_query(query: str) -> bool:
    """Identify class-level requests that cannot match a row name in SQL."""

    normalized = " ".join(re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", query.casefold()))
    return any(
        term in normalized
        for terms in _KIND_TERMS.values()
        for term in terms
        if len(term) > 2
    )


def is_authoritative_local_metadata_card(card: Mapping[str, Any]) -> bool:
    return (
        card.get("kind") == "metadata"
        and (
            card.get("selector") == "metadata:search"
            or str(card.get("metadata_kind", ""))
            in AUTHORITATIVE_LOCAL_METADATA_KINDS
        )
    )


def vocabulary_match_values(item: Mapping[str, Any]) -> tuple[object, ...]:
    kind = str(item.get("kind", ""))
    return (
        item.get("name"),
        item.get("cname"),
        item.get("source"),
        item.get("operation_id"),
        *_KIND_TERMS.get(kind, (kind,)),
    )


def vocabulary_card_fields(item: Mapping[str, Any], query: str) -> dict[str, Any]:
    """Render safe execution hints without turning vocabulary into a query."""

    del query
    kind = str(item["kind"])
    name = _optional_text(item.get("name"))
    source = _optional_text(item.get("source"))
    operation_id = _optional_text(item.get("operation_id"))
    identity = _vocabulary_identity(item)
    lookup_query = _vocabulary_lookup_query(item)
    origin = source or operation_id or "workspace"
    fields: dict[str, Any] = {
        "selector": f"metadata:{kind}:{origin}:{identity}",
        "lookup_query": lookup_query,
        "scope": "workspace",
        "source": source,
        "effect": "local_read",
        "executable": True,
        "plan_executable": True,
        "offline": True,
        "network_called": False,
        "next": {
            "ready_without_input": True,
            "argv": [
                "gravity",
                "metadata",
                "vocabulary",
                lookup_query,
                "--kind",
                kind,
            ],
        },
    }
    if kind == "metric" and name:
        fields["request_fragment"] = {"metrics_list": [name]}
    elif kind == "custom_metric" and name:
        fields["request_fragment"] = {"custom_metrics_list": [name]}
    elif kind == "template":
        fields.update({
            "catalog_only": True,
            "replay_supported": False,
            "next_action": (
                "Use this card only to inspect the synchronized template identity; "
                "it does not contain or replay template configuration."
            ),
        })
    return fields


def _vocabulary_lookup_query(item: Mapping[str, Any]) -> str:
    """Return a stable scalar that the copied typed lookup can match exactly."""

    payload = item.get("payload")
    safe_payload = payload if isinstance(payload, Mapping) else {}
    kind = str(item.get("kind", ""))
    candidates = (
        (
            safe_payload.get("code"),
            item.get("name"),
            safe_payload.get("id"),
            safe_payload.get("name"),
        )
        if kind == "media_enum"
        else (
            item.get("name"),
            safe_payload.get("name"),
            safe_payload.get("code"),
            safe_payload.get("id"),
            item.get("cname"),
        )
    )
    return next(
        (value for candidate in candidates if (value := _optional_text(candidate))),
        str(item.get("source") or item.get("operation_id") or kind),
    )


def _optional_text(value: Any) -> str | None:
    return str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) else None


def _vocabulary_identity(item: Mapping[str, Any]) -> str:
    """Keep selectors unique when names repeat across media groups or catalogs."""

    payload = item.get("payload")
    safe_payload = payload if isinstance(payload, Mapping) else {}
    readable = next(
        (
            value
            for value in (
                _optional_text(safe_payload.get("id")),
                _optional_text(safe_payload.get("code")),
                _optional_text(item.get("name")),
            )
            if value
        ),
        "catalog",
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            safe_payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()[:8]
    return f"{readable}:{fingerprint}"


__all__ = [
    "AUTHORITATIVE_LOCAL_METADATA_KINDS",
    "WORKSPACE_VOCABULARY_KINDS",
    "is_authoritative_local_metadata_card",
    "is_vocabulary_discovery_query",
    "is_workspace_vocabulary",
    "vocabulary_card_fields",
    "vocabulary_match_values",
]
