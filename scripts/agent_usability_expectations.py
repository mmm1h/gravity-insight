"""Derive evaluation response shapes from the analysis-journey ledger."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
TARGETS_PATH = ROOT / "evals" / "agent_usability" / "journey-targets.json"
LEDGER_PATH = ROOT / "docs" / "analysis-journeys.md"
TARGETS_SCHEMA = "gravity.agent-usability-journey-targets.v1"
STATUSES = frozenset({"已闭环", "部分闭环", "完全缺失"})
_LEDGER_ROW = re.compile(
    r"^\| (?P<title>.*?) \| (?P<status>已闭环|部分闭环|完全缺失) \|"
)


def _targets(path: Path) -> tuple[dict[str, Mapping[str, Any]], str]:
    payload = path.read_bytes()
    document = json.loads(payload)
    if document.get("schema_version") != TARGETS_SCHEMA:
        raise ValueError(
            "journey-targets.json schema_version is invalid; actual value: "
            f"{document.get('schema_version')!r}; allowed value: {TARGETS_SCHEMA!r}"
        )
    if document.get("partial_status_policy") != "target_gap":
        raise ValueError(
            "journey-targets.json partial_status_policy is invalid; actual value: "
            f"{document.get('partial_status_policy')!r}; allowed value: 'target_gap'"
        )
    journeys = document.get("journeys")
    if not isinstance(journeys, Mapping) or len(journeys) != 48:
        raise ValueError(
            "journey-targets.json journeys is invalid; actual value: "
            f"{type(journeys).__name__} with {len(journeys) if isinstance(journeys, Mapping) else 0} entries; "
            "required value: exactly 48 journey targets"
        )
    return {str(key): value for key, value in journeys.items()}, hashlib.sha256(payload).hexdigest()


def _ledger_statuses(
    targets: Mapping[str, Mapping[str, Any]], path: Path
) -> tuple[dict[str, str], str]:
    payload = path.read_bytes()
    selected: dict[str, str] = {}
    titles = {str(target["ledger_title"]): journey_id for journey_id, target in targets.items()}
    for line in payload.decode("utf-8").splitlines():
        match = _LEDGER_ROW.match(line)
        if match is None or match.group("title") not in titles:
            continue
        journey_id = titles[match.group("title")]
        if journey_id in selected:
            raise ValueError(
                "analysis-journeys.md contains a duplicate counted journey; actual value: "
                f"{match.group('title')!r}; required action: keep exactly one authoritative row"
            )
        selected[journey_id] = match.group("status")
    missing = sorted(set(targets) - set(selected))
    if missing:
        raise ValueError(
            "analysis-journeys.md is missing registered journey rows; actual value: "
            f"{missing!r}; required action: restore the exact ledger_title rows"
        )
    return selected, hashlib.sha256(payload).hexdigest()


def _shape_signature(value: Mapping[str, Any]) -> tuple[Any, Any]:
    return value.get("route_key"), value.get("gap_code")


def derive_cases(
    cases: Sequence[Mapping[str, Any]],
    *,
    targets_path: Path = TARGETS_PATH,
    ledger_path: Path = LEDGER_PATH,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return cases with only their expected response shape replaced."""

    targets, targets_hash = _targets(targets_path)
    statuses, ledger_hash = _ledger_statuses(targets, ledger_path)
    derived: list[dict[str, Any]] = []
    for case in cases:
        journey_id = str(case.get("journey_id", ""))
        target = targets.get(journey_id)
        if target is None:
            raise ValueError(
                "case journey_id is not registered; actual value: "
                f"{journey_id!r}; allowed values: {sorted(targets)!r}"
            )
        original = case.get("expected")
        if original is None:
            expectation: dict[str, Any] = {}
        elif not isinstance(original, Mapping):
            raise ValueError(
                f"case {case.get('case_id')!r} expected is invalid; actual value: "
                f"{type(original).__name__}; required value: an expectation object or omission"
            )
        else:
            alternatives = [
                value for key in ("product", "gap")
                if isinstance((value := target.get(key)), Mapping)
            ]
            if _shape_signature(original) not in map(_shape_signature, alternatives):
                raise ValueError(
                    f"case {case.get('case_id')!r} target identity is not frozen to {journey_id}; "
                    f"actual value: {_shape_signature(original)!r}; allowed values: "
                    f"{[_shape_signature(value) for value in alternatives]!r}"
                )
            expectation = dict(original)
        status = statuses[journey_id]
        shape_name = "product" if status == "已闭环" else "gap"
        shape = target.get(shape_name)
        if not isinstance(shape, Mapping):
            raise ValueError(
                f"journey target {journey_id}.{shape_name} is missing; actual value: {shape!r}; "
                "required action: register the frozen product or target-gap identity before changing ledger status"
            )
        expectation.update(shape)
        expectation["gap_code"] = shape.get("gap_code")
        expectation["terminal_kind"] = (
            "answer_or_empty" if shape_name == "product" else "capability_gap"
        )
        derived.append({**case, "expected": expectation})
    counts = Counter(statuses.values())
    snapshot = {
        "schema_version": TARGETS_SCHEMA,
        "partial_status_policy": "target_gap",
        "journey_count": len(targets),
        "status_counts": {status: counts[status] for status in sorted(STATUSES)},
        "targets_sha256": targets_hash,
        "ledger_sha256": ledger_hash,
    }
    return derived, snapshot


__all__ = ["LEDGER_PATH", "TARGETS_PATH", "derive_cases"]
