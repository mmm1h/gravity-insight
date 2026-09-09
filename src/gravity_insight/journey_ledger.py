"""Structured Journey facts and separately identified legacy annotations."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Sequence

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    load_json_object,
    validate_schema,
)


SCHEMA_VERSION = "gravity.journey-ledger-snapshot.v2"
SOURCE_PATH = "src/gravity_insight/governance/journey-ledger-facts.v1.json"
ANNOTATIONS_PATH = "src/gravity_insight/governance/journey-ledger-annotations.v1.json"
_PACKAGE_ROOT = Path(__file__).resolve().parent
FACTS_PATH = _PACKAGE_ROOT / "governance" / "journey-ledger-facts.v1.json"
NOTES_PATH = _PACKAGE_ROOT / "governance" / "journey-ledger-annotations.v1.json"
_PACKAGE_SNAPSHOT = _PACKAGE_ROOT / "contracts" / "journeys" / "ledger-snapshot.v2.json"
_SCHEMA_NAME = "journey-ledger-snapshot-v2.schema.json"


class JourneyLedgerError(AgentRuntimeContractError):
    """Journey facts or annotations cannot be projected without ambiguity."""


def load_journey_facts(path: Path = FACTS_PATH) -> dict[str, Any]:
    facts = load_json_object(path, "Journey ledger facts")
    try:
        validate_schema(facts, "journey-ledger-facts-v1.schema.json", "Journey facts")
    except AgentRuntimeContractError as exc:
        raise JourneyLedgerError(str(exc)) from exc
    keys = [row["display_name"] for row in facts["rows"]]
    if len(keys) != len(set(keys)):
        raise JourneyLedgerError("Journey ledger display keys must be unique")
    return facts


def load_journey_ledger(
    facts_path: Path = FACTS_PATH, *, annotations_path: Path = NOTES_PATH,
) -> dict[str, Any]:
    facts = load_journey_facts(facts_path)
    annotations = load_json_object(annotations_path, "Journey legacy annotations")
    try:
        validate_schema(
            annotations, "journey-ledger-annotations-v1.schema.json", "Journey annotations",
        )
    except AgentRuntimeContractError as exc:
        raise JourneyLedgerError(str(exc)) from exc
    notes = annotations["notes"]
    if set(notes) != {row["display_name"] for row in facts["rows"]}:
        raise JourneyLedgerError("Journey annotation keys must exactly match facts")
    rows = [
        _row((row["display_name"], row["ledger_status"], row["surfaces"],
              row["request_budget"], notes[row["display_name"]]))
        for row in facts["rows"]
    ]
    body = {
        "source_path": SOURCE_PATH,
        "source_sha256": canonical_digest(facts),
        "annotations_path": ANNOTATIONS_PATH,
        "annotations_sha256": canonical_digest(annotations),
        "rows": rows,
    }
    result = {
        "schema_version": SCHEMA_VERSION, **body,
        "snapshot_digest": canonical_digest(body),
        "row_count": len(rows), "network_called": False,
    }
    _validate_snapshot(result)
    return result


def render_journey_ledger_snapshot(facts_path: Path = FACTS_PATH) -> str:
    return json.dumps(
        load_journey_ledger(facts_path), ensure_ascii=False,
        indent=2, sort_keys=True, allow_nan=False,
    ) + "\n"


def render_journey_ledger_markdown(facts_path: Path = FACTS_PATH) -> str:
    facts = load_journey_facts(facts_path)
    lines = [
        "# 分析动线台账",
        "",
        "本页由[结构化当前事实](../src/gravity_insight/governance/journey-ledger-facts.v1.json)生成，不是机器输入；修改 Owner 后运行 python scripts/generate_journey_ledger.py。",
        "",
        "每行对应一个独立问题；不计独立动线的兼容行仍保留。闭环要求已知输入一次、未知输入最多两次，四面可达并区分成功、空、部分失败与缺口；台账状态不替代当次 Journey readiness、权限或完整性。",
        "",
        "旧阻塞与验收文字逐字保留在[历史注释](../src/gravity_insight/governance/journey-ledger-annotations.v1.json)，仅供追溯，不作为最新认证。历史生产基线见[2026-09-01 认证](production-certification.md)；执行合同见[Agent 工作流](agent-workflow.md)。",
        "",
        "漏斗分组边界见[替代路径](guides/funnel-grouping-alternatives.md)。",
        "",
        "## 当前事实投影",
        "",
        "| 动线 | 状态 | 四面可达（CLI / SDK / Plan / Agent 中英首问） | 调用次数（已知 / 未知） |",
        "| --- | --- | --- | --- |",
    ]
    for row in facts["rows"]:
        cells = [row[key].replace("|", "\\|") for key in
                 ("display_name", "ledger_status", "surfaces", "request_budget")]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def load_packaged_journey_ledger() -> dict[str, Any]:
    value = load_json_object(_PACKAGE_SNAPSHOT, "packaged Journey ledger")
    _validate_snapshot(value)
    return copy.deepcopy(value)


def ledger_row(snapshot: dict[str, Any], legacy_display_key: str) -> dict[str, Any] | None:
    matches = [row for row in snapshot["rows"] if row["legacy_display_key"] == legacy_display_key]
    if len(matches) > 1:
        raise JourneyLedgerError("Journey ledger display binding is ambiguous")
    return copy.deepcopy(matches[0]) if matches else None


def _row(cells: Sequence[str]) -> dict[str, Any]:
    display_name, status, surface_text, request_text, blocker = cells
    if not display_name or not status or not surface_text or not request_text:
        raise JourneyLedgerError("Journey ledger required cells must not be empty")
    surface_values = [item.strip() for item in surface_text.split(" / ")]
    if len(surface_values) != 4 or any(not item for item in surface_values):
        raise JourneyLedgerError("Journey ledger surface cell must contain four values")
    body = {
        "legacy_display_key": display_name,
        "display_name": display_name,
        "ledger_status": status,
        "surfaces": {
            "raw": surface_text,
            "cli": surface_values[0],
            "sdk": surface_values[1],
            "plan": surface_values[2],
            "agent": surface_values[3],
        },
        "request_budget": {"raw": request_text},
        "blocker_note": blocker,
        "counted": not status.startswith("不计独立动线"),
        "can_return_business_content": status == "已闭环",
    }
    return {**body, "row_digest": canonical_digest(body)}


def _validate_snapshot(value: dict[str, Any]) -> None:
    try:
        validate_schema(value, _SCHEMA_NAME, "Journey ledger snapshot")
    except AgentRuntimeContractError as exc:
        raise JourneyLedgerError(str(exc)) from exc
    body = {key: value[key] for key in (
        "source_path", "source_sha256", "annotations_path", "annotations_sha256", "rows",
    )}
    if value["row_count"] != len(value["rows"]) or value["snapshot_digest"] != canonical_digest(body):
        raise JourneyLedgerError("Journey ledger snapshot count or digest drifted")
    keys = [row["legacy_display_key"] for row in value["rows"]]
    if len(keys) != len(set(keys)):
        raise JourneyLedgerError("Journey ledger display keys must be unique")
    for row in value["rows"]:
        body = {key: item for key, item in row.items() if key != "row_digest"}
        if row["row_digest"] != canonical_digest(body):
            raise JourneyLedgerError("Journey ledger row digest drifted")


__all__ = [
    "JourneyLedgerError", "SCHEMA_VERSION", "SOURCE_PATH", "ledger_row",
    "load_journey_facts", "load_journey_ledger", "load_packaged_journey_ledger",
    "render_journey_ledger_snapshot", "render_journey_ledger_markdown",
]
