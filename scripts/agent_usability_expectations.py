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
TARGETS_SCHEMA = "gravity.agent-usability-journey-targets.v2"
STATUSES = frozenset({"已闭环", "部分闭环", "完全缺失"})
MULTIPLE_INTENTS = "MULTIPLE_INTENTS"
_LEDGER_ROW = re.compile(
    r"^\| (?P<title>.*?) \| (?P<status>已闭环|部分闭环|完全缺失) \|"
)


def _targets(
    path: Path,
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str], str]:
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
    targets = {str(key): value for key, value in journeys.items()}
    candidate_selectors = document.get("candidate_selectors")
    if not isinstance(candidate_selectors, Mapping):
        raise ValueError(
            "journey-targets.json candidate_selectors is invalid; actual value: "
            f"{type(candidate_selectors).__name__}; required value: a journey-to-selector object"
        )
    selectors = {
        str(key): value for key, value in candidate_selectors.items()
        if isinstance(value, str)
    }
    invalid = sorted(
        str(journey_id) for journey_id, selector in candidate_selectors.items()
        if journey_id not in targets or not isinstance(selector, str) or not selector
    )
    if invalid or len(selectors) != len(candidate_selectors) or len(
        set(selectors.values())
    ) != len(selectors):
        raise ValueError(
            "journey-targets.json candidate_selectors is inconsistent; actual invalid journeys: "
            f"{invalid!r}; required value: unique non-empty selectors for registered journeys"
        )
    return targets, selectors, hashlib.sha256(payload).hexdigest()


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


def _multiple_intent_expectation(
    case: Mapping[str, Any],
    original: Mapping[str, Any],
    targets: Mapping[str, Mapping[str, Any]],
    candidate_selectors: Mapping[str, str],
) -> dict[str, Any] | None:
    if original.get("terminal_kind") != "multiple_intents":
        return None
    if set(original) != {"terminal_kind", "journey_ids"}:
        raise ValueError(
            f"case {case.get('case_id')!r} multiple-intent expectation is invalid; "
            "required fields: terminal_kind and journey_ids"
        )
    journey_ids = original.get("journey_ids")
    if (
        not isinstance(journey_ids, Sequence)
        or isinstance(journey_ids, (str, bytes))
        or len(journey_ids) < 2
        or len(set(map(str, journey_ids))) != len(journey_ids)
    ):
        raise ValueError(
            f"case {case.get('case_id')!r} journey_ids is invalid; actual value: "
            f"{journey_ids!r}; required value: at least two unique journey IDs"
        )
    selected = list(map(str, journey_ids))
    primary = str(case.get("journey_id", ""))
    invalid = sorted(set(selected) - set(targets))
    if primary not in selected or invalid:
        raise ValueError(
            f"case {case.get('case_id')!r} journey_ids do not preserve its target identity; "
            f"actual value: {selected!r}; primary: {primary!r}; unregistered: {invalid!r}"
        )
    selectors: list[str | None] = []
    for journey_id in selected:
        selector = candidate_selectors.get(journey_id)
        gap = targets[journey_id].get("gap")
        if selector is None and isinstance(gap, Mapping):
            gap_code = gap.get("gap_code")
            if isinstance(gap_code, str) and gap_code:
                selector = f"gap:{gap_code}"
        selectors.append(selector)
    missing = [
        journey_id for journey_id, selector in zip(selected, selectors)
        if selector is None
    ]
    if missing:
        raise ValueError(
            f"case {case.get('case_id')!r} journeys lack candidate identities; "
            f"actual value: {missing!r}; required action: register exact public "
            "product selectors or frozen target gaps"
        )
    return {
        "route_key": "multiple_intents",
        "gap_code": MULTIPLE_INTENTS,
        "terminal_kind": "capability_gap",
        "journey_ids": selected,
        "candidate_selectors": {
            journey_id: selector for journey_id, selector in zip(selected, selectors)
            if selector is not None
        },
    }


def derive_cases(
    cases: Sequence[Mapping[str, Any]],
    *,
    targets_path: Path = TARGETS_PATH,
    ledger_path: Path = LEDGER_PATH,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return cases with only their expected response shape replaced."""

    targets, candidate_selectors, targets_hash = _targets(targets_path)
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
            multiple = _multiple_intent_expectation(
                case, original, targets, candidate_selectors
            )
            if multiple is not None:
                derived.append({**case, "expected": multiple})
                continue
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
