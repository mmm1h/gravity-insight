"""Deterministic Agent discovery for the offline table-lineage catalog."""

from __future__ import annotations

import re
from typing import Any

from .agent_capabilities import agent_query_match, normalize_agent_query
from .agent_intent_text import affirmative_intent_text


_CAPABILITY = {
    "kind": "metadata",
    "selector": "metadata:table_lineage",
    "metadata_kind": "table_lineage",
    "domain": "metadata",
    "description": (
        "离线查询已同步的账号级数据表版本与操作日志；只返回上游实际观察到的 "
        "table_id、version、action 和时间，不推断表名、App 归属或当前版本。"
    ),
    "aliases": (
        "table lineage",
        "table version",
        "table version history",
        "table operation log",
        "table change",
        "data table lineage",
        "表血缘",
        "数据表血缘",
        "表版本",
        "数据表版本",
        "表操作日志",
        "数据表操作日志",
        "表变更",
        "数据表变更",
    ),
}


def table_lineage_capability_cards(
    query: str, *, domain: str | None, platform: str | None
) -> list[dict[str, Any]]:
    """Return one authoritative local handoff for explicit lineage intent."""

    definition = _CAPABILITY
    if platform is not None or domain not in {None, definition["domain"]}:
        return []
    recognized = affirmative_intent_text(query)
    normalized = normalize_agent_query(recognized)
    words = frozenset(re.findall(r"[a-z0-9_]+", normalized))
    english_intent = "table" in words and (
        bool(words & {"lineage", "version", "change"})
        or {"operation", "log"} <= words
    )
    chinese_intent = bool(re.search(
        r"(?:数据表|(?<!报)表).{0,12}(?:血缘|版本|变更|操作日志)", recognized
    )) or ("同步" in recognized and "沿革" in recognized)
    selector = str(definition["selector"])
    exact = normalized in {
        selector.casefold(),
        str(definition["metadata_kind"]).casefold(),
    }
    if not (english_intent or chinese_intent or exact):
        return []
    match = agent_query_match(
        query,
        selector,
        definition["metadata_kind"],
        definition["description"],
        *definition["aliases"],
        score=100,
    )
    match.update({
        "confidence": "strong",
        "coverage": 1.0,
        "matched_terms": [normalized],
        "missing_terms": [],
    })
    if exact:
        match["exact_selector"] = True
    return [{
        "kind": definition["kind"],
        "selector": selector,
        "metadata_kind": definition["metadata_kind"],
        "domain": definition["domain"],
        "description": definition["description"],
        "scope": "account",
        "effect": "local_read",
        "executable": True,
        "plan_executable": True,
        "offline": True,
        "network_called": False,
        "required_inputs": [],
        "missing_inputs": [],
        "input_template": {
            "query": "<optional-table-id-version-or-action>",
        },
        "match": match,
        "next": {
            "ready_without_input": True,
            "argv": ["gravity", "metadata", "tables"],
            "call_count_after_discovery": 1,
        },
        "next_action": (
            "Execute plan_node as-is for all observed tables, or set request.query "
            "to a known table_id, version, or action value before execution."
        ),
    }]


__all__ = ["table_lineage_capability_cards"]
