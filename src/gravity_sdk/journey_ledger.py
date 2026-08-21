"""Strict read-only projection of the human-owned analysis Journey ledger."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Sequence

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    load_json_object,
    validate_schema,
)


SCHEMA_VERSION = "gravity.journey-ledger-snapshot.v1"
SOURCE_PATH = "docs/analysis-journeys.md"
_SCHEMA_NAME = "journey-ledger-snapshot-v1.schema.json"
_PACKAGE_SNAPSHOT = (
    Path(__file__).resolve().parent
    / "contracts"
    / "journeys"
    / "ledger-snapshot.v1.json"
)
_HEADER = (
    "动线",
    "状态",
    "四面可达（CLI / SDK / Plan / Agent 中英首问）",
    "调用次数（已知 / 未知）",
    "阻塞",
)
_SEPARATOR = re.compile(r"^:?-{3,}:?$")


class JourneyLedgerError(AgentRuntimeContractError):
    """The Markdown Journey ledger cannot be projected without ambiguity."""


def parse_journey_ledger(
    text: str, *, source_path: str = SOURCE_PATH
) -> dict[str, Any]:
    if not isinstance(text, str) or not text:
        raise JourneyLedgerError("Journey ledger must be non-empty UTF-8 text")
    rows = _ledger_rows(text.splitlines())
    display_keys = [row["legacy_display_key"] for row in rows]
    if len(display_keys) != len(set(display_keys)):
        raise JourneyLedgerError("Journey ledger display keys must be unique")
    source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    snapshot_body = {
        "source_path": source_path,
        "source_sha256": source_sha256,
        "rows": rows,
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        **snapshot_body,
        "snapshot_digest": canonical_digest(snapshot_body),
        "row_count": len(rows),
        "network_called": False,
    }
    _validate_snapshot(result)
    return result


def _ledger_rows(lines: Sequence[str]) -> list[dict[str, Any]]:
    header_index = _header_index(lines)
    separator = _table_cells(lines[header_index + 1])
    if len(separator) != len(_HEADER) or any(
        _SEPARATOR.fullmatch(cell) is None for cell in separator
    ):
        raise JourneyLedgerError("Journey ledger table separator is invalid")
    rows: list[dict[str, Any]] = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        cells = _table_cells(line)
        if len(cells) != len(_HEADER):
            raise JourneyLedgerError("Journey ledger row must contain five columns")
        rows.append(_row(cells))
    if not rows:
        raise JourneyLedgerError("Journey ledger table must contain rows")
    return rows


def _header_index(lines: Sequence[str]) -> int:
    headers = [
        index
        for index, line in enumerate(lines)
        if line.startswith("|") and _table_cells(line) == _HEADER
    ]
    if len(headers) != 1:
        raise JourneyLedgerError("Journey ledger must contain one exact table header")
    header_index = headers[0]
    if header_index + 1 >= len(lines):
        raise JourneyLedgerError("Journey ledger table separator is missing")
    return header_index


def render_journey_ledger_snapshot(text: str) -> str:
    return json.dumps(
        parse_journey_ledger(text),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def load_packaged_journey_ledger() -> dict[str, Any]:
    value = load_json_object(_PACKAGE_SNAPSHOT, "packaged Journey ledger")
    _validate_snapshot(value)
    body = {
        "source_path": value["source_path"],
        "source_sha256": value["source_sha256"],
        "rows": value["rows"],
    }
    if value["row_count"] != len(value["rows"]):
        raise JourneyLedgerError("packaged Journey ledger row count drifted")
    if value["snapshot_digest"] != canonical_digest(body):
        raise JourneyLedgerError("packaged Journey ledger digest drifted")
    return copy.deepcopy(value)


def ledger_row(
    snapshot: dict[str, Any], legacy_display_key: str
) -> dict[str, Any] | None:
    matches = [
        row
        for row in snapshot["rows"]
        if row["legacy_display_key"] == legacy_display_key
    ]
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


def _table_cells(line: str) -> tuple[str, ...]:
    if not line.startswith("|") or not line.rstrip().endswith("|"):
        raise JourneyLedgerError("Journey ledger table line must use outer pipes")
    value = line.strip()[1:-1]
    cells: list[str] = []
    current: list[str] = []
    code_delimiter = 0
    index = 0
    while index < len(value):
        character = value[index]
        if character == "`":
            end = index
            while end < len(value) and value[end] == "`":
                end += 1
            count = end - index
            if code_delimiter == 0:
                code_delimiter = count
            elif code_delimiter == count:
                code_delimiter = 0
            current.append(value[index:end])
            index = end
            continue
        if character == "\\" and index + 1 < len(value):
            current.append(value[index : index + 2])
            index += 2
            continue
        if character == "|" and code_delimiter == 0:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
        index += 1
    if code_delimiter:
        raise JourneyLedgerError("Journey ledger row has an unterminated code span")
    cells.append("".join(current).strip())
    return tuple(cells)


def _validate_snapshot(value: dict[str, Any]) -> None:
    try:
        validate_schema(value, _SCHEMA_NAME, "Journey ledger snapshot")
    except AgentRuntimeContractError as exc:
        raise JourneyLedgerError(str(exc)) from exc
    for row in value["rows"]:
        body = {key: item for key, item in row.items() if key != "row_digest"}
        if row["row_digest"] != canonical_digest(body):
            raise JourneyLedgerError("Journey ledger row digest drifted")


__all__ = [
    "JourneyLedgerError",
    "SCHEMA_VERSION",
    "SOURCE_PATH",
    "ledger_row",
    "load_packaged_journey_ledger",
    "parse_journey_ledger",
    "render_journey_ledger_snapshot",
]
