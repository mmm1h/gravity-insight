"""Append-only query accounting and binary safety checks for the evaluator."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


LEDGER_SCHEMA_VERSION = "gravity.agent-usability-query-ledger.v1"
PROTECTED_SPLITS = frozenset({"holdout", "final"})
FOUR_LAYER_NAMES = (
    "product_selection",
    "parameter_fillability",
    "end_to_end",
    "error_recovery",
)
SECURITY_CHECKS = (
    "upstream_mutation_handoff",
    "credential_assignment",
    "arbitrary_transport_handoff",
    "natural_language_auto_execute",
    "operation_allowlist_control",
)
_TEXT_FIELDS = frozenset({"message", "next_action", "warning", "warnings"})
_TRANSPORT_KEYS = frozenset(
    {"url", "uri", "host", "hostname", "endpoint", "http_method", "method"}
)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?ix)(?:\bGRAVITY_)?"
    r"(?:access[_-]?token|refresh[_-]?token|session[_-]?token|api[_-]?key|"
    r"client[_-]?secret|authorization|cookie|password|passwd|private[_-]?key|"
    r"secret|token|密码|口令|令牌|密钥)"
    r"\s*(?:=|:)\s*(?!<|\*{3,}|\[?redacted\]?)([^\s,;`]+)"
)
_LOCAL_WRITE_CATALOG_SYNC = "metadata_catalog_sync"
_LOCAL_WRITE_FILE_OUTPUT = "file_output"
_TABLE_SCHEMA_SYNC_GAP = "CURRENT_TABLE_SCHEMA_PARENT_MISSING"


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def load_query_records(path: Path) -> list[dict[str, Any]]:
    """Read and validate query records without accepting a damaged ledger."""

    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    previous_hash: str | None = None
    for number, raw in enumerate(path.read_bytes().splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise ValueError(f"query ledger line {number} is malformed") from error
        if not isinstance(value, Mapping):
            raise ValueError(f"query ledger line {number} must be an object")
        record = dict(value)
        if record.get("record_type") != "query":
            continue
        _validate_query_record(record, number)
        claimed_hash = str(record["entry_sha256"])
        payload = {key: item for key, item in record.items() if key != "entry_sha256"}
        if hashlib.sha256(_canonical(payload)).hexdigest() != claimed_hash:
            raise ValueError(f"query ledger line {number} failed its integrity check")
        if record.get("previous_entry_sha256") != previous_hash:
            raise ValueError(f"query ledger line {number} broke the append chain")
        previous_hash = claimed_hash
        records.append(record)
    return records


def _validate_query_record(record: Mapping[str, Any], number: int) -> None:
    required = {
        "schema_version", "record_type", "run_at", "split", "suite_version",
        "git_revision", "purpose", "four_layer_scores", "entry_sha256",
        "previous_entry_sha256", "split_query_ordinal", "protected_query_ordinal",
    }
    if required - set(record):
        raise ValueError(f"query ledger line {number} is incomplete")
    if record.get("schema_version") != LEDGER_SCHEMA_VERSION:
        raise ValueError(f"query ledger line {number} has an unknown schema")
    if record.get("split") not in PROTECTED_SPLITS:
        raise ValueError(f"query ledger line {number} has an invalid split")
    scores = record.get("four_layer_scores")
    if not isinstance(scores, Mapping) or set(scores) != set(FOUR_LAYER_NAMES):
        raise ValueError(f"query ledger line {number} has invalid layer scores")


def query_counts(records: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = Counter(str(record.get("split")) for record in records)
    return {
        "holdout": counts["holdout"],
        "final": counts["final"],
        "protected_total": counts["holdout"] + counts["final"],
    }


def ensure_query_allowed(
    split: str,
    purpose: str | None,
    allow_final_rerun: bool,
    ledger_path: Path,
) -> str | None:
    if split not in PROTECTED_SPLITS:
        if allow_final_rerun:
            raise ValueError("--allow-final-rerun is valid only with --split final")
        return None
    selected_purpose = " ".join(str(purpose or "").splitlines()).strip()
    if not selected_purpose:
        raise ValueError("--purpose is required for holdout and final evaluation")
    if len(selected_purpose) > 500:
        raise ValueError("--purpose must not exceed 500 characters")
    records = load_query_records(ledger_path)
    counts = query_counts(records)
    if split != "final" and allow_final_rerun:
        raise ValueError("--allow-final-rerun is valid only with --split final")
    if split == "final" and counts["final"]:
        if not allow_final_rerun:
            raise ValueError(
                "final was already queried; rerun only with --allow-final-rerun"
            )
    elif split == "final" and allow_final_rerun:
        raise ValueError("--allow-final-rerun requires a prior final ledger record")
    return selected_purpose


def append_query_record(
    result: Mapping[str, Any],
    *,
    purpose: str,
    allow_final_rerun: bool,
    ledger_path: Path,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Append exactly one durable record; never rewrite existing ledger bytes."""

    records = load_query_records(ledger_path)
    counts = query_counts(records)
    split = str(result.get("split"))
    if split not in PROTECTED_SPLITS:
        raise ValueError("only holdout and final queries belong in the query ledger")
    if split == "final" and counts["final"] and not allow_final_rerun:
        raise ValueError("final rerun lost its explicit override before ledger append")
    layers = result.get("layers")
    if not isinstance(layers, Mapping):
        raise ValueError("evaluation result has no layer scores")
    scores = {
        name: _score(layers.get(name), name) for name in FOUR_LAYER_NAMES
    }
    subject = result.get("subject")
    if not isinstance(subject, Mapping):
        raise ValueError("evaluation result has no code revision")
    previous_hash = str(records[-1]["entry_sha256"]) if records else None
    record: dict[str, Any] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "record_type": "query",
        "run_at": str(result.get("run_at")),
        "split": split,
        "suite_version": str(result.get("suite_version")),
        "git_revision": str(subject.get("git_commit")),
        "product_source_sha256": str(subject.get("product_source_sha256")),
        "evaluator_source_sha256": str(subject.get("evaluator_source_sha256", "")),
        "git_worktree_dirty": subject.get("git_worktree_dirty") is True,
        "purpose": purpose,
        "case_count": int(result.get("case_count", 0)),
        "trials": int(result.get("trials", 0)),
        "four_layer_scores": scores,
        "security_compliance": _security_receipt(layers.get("security_compliance")),
        "selector_arm": _selector_receipt(result.get("selector_arm"), layers),
        "final_rerun_override": bool(allow_final_rerun),
        "split_query_ordinal": counts[split] + 1,
        "protected_query_ordinal": counts["protected_total"] + 1,
        "previous_entry_sha256": previous_hash,
    }
    record["entry_sha256"] = hashlib.sha256(_canonical(record)).hexdigest()
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical(record) + b"\n"
    with ledger_path.open("ab") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    updated = query_counts([*records, record])
    return record, updated


def _score(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"evaluation result is missing {name}")
    return {
        "passed": int(value["passed"]),
        "total": int(value["total"]),
        "rate": value.get("rate"),
    }


def _security_receipt(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {"passed": False, "violation_count": None}
    return {
        "passed": value.get("passed") is True,
        "violation_count": int(value.get("violation_count", 0)),
    }


def _selector_receipt(value: Any, layers: Mapping[str, Any]) -> dict[str, Any]:
    selected = value if isinstance(value, Mapping) else {}
    trials = selected.get("trial_receipts", [])
    identities = [
        str(item.get("selector"))
        for item in trials
        if isinstance(item, Mapping) and item.get("selector")
    ]
    cost = layers.get("cost")
    return {
        "mode": str(selected.get("mode", "unspecified")),
        "protocol": selected.get("protocol"),
        "plugin_sha256": selected.get("plugin_sha256"),
        "selector_versions": list(dict.fromkeys(identities)),
        "network_trials": (
            int(cost.get("external_selector_network_trials", 0))
            if isinstance(cost, Mapping)
            else 0
        ),
    }


def security_compliance_score(
    observations: Sequence[Mapping[str, Any]],
    *,
    client: Any | None = None,
    blocked_transport: Any | None = None,
) -> dict[str, Any]:
    """Return a binary gate: any observed or control violation fails the layer."""

    failures: Counter[str] = Counter()
    local_writes: Counter[str] = Counter()
    mutation_ids = _upstream_mutation_ids(client)
    for observation in observations:
        result = observation.get("result")
        if not isinstance(result, Mapping):
            continue
        candidates = [
            item for item in result.get("candidates", ()) if isinstance(item, Mapping)
        ]
        if any(_references_mutation(card, mutation_ids) for card in candidates):
            failures["upstream_mutation_handoff"] += 1
        local_writes.update(_local_write_effects(result))
        if _has_credential_assignment(result):
            failures["credential_assignment"] += 1
        if any(_has_arbitrary_transport(card) for card in candidates):
            failures["arbitrary_transport_handoff"] += 1
        if any(card.get("natural_language_auto_execute") is True for card in candidates):
            failures["natural_language_auto_execute"] += 1
    if client is not None:
        failures.update(_control_failures(client, blocked_transport))
    count = sum(failures.values())
    return {
        "passed": count == 0,
        "gate": "pass" if count == 0 else "fail",
        "criterion": "binary_any_violation_fails",
        "violation_count": count,
        "failure_classes": dict(sorted(failures.items())),
        "local_write_information": {
            "handoff_count": sum(local_writes.values()),
            "classes": dict(sorted(local_writes.items())),
        },
        "checks": list(SECURITY_CHECKS),
    }


def _upstream_mutation_ids(client: Any | None) -> frozenset[str]:
    """Read registered mutation classifications; command spelling is not evidence."""

    operation_ids: set[str] = set()
    registry = getattr(client, "_registry", None)
    all_operations = getattr(registry, "all", None)
    if callable(all_operations):
        operation_ids.update(
            str(operation.operation_id)
            for operation in all_operations()
            if getattr(operation, "effect", None) == "mutation"
        )
    from gravity_sdk.census.coverage import load_write_reservations

    root = Path(__file__).resolve().parents[1]
    operation_ids.update(
        str(item["operation_id"])
        for item in load_write_reservations(
            root / "src" / "gravity_sdk" / "contracts" / "reservations"
        )
    )
    return frozenset(operation_ids)


def _references_mutation(
    card: Mapping[str, Any], mutation_ids: frozenset[str]
) -> bool:
    node = card.get("plan_node")
    request = node.get("request") if isinstance(node, Mapping) else None
    identifiers = {
        str(value) for value in (
            card.get("operation_id"), card.get("selector"),
            request.get("selector") if isinstance(request, Mapping) else None,
        ) if isinstance(value, str)
    }
    return bool(identifiers & mutation_ids)


def _local_write_effects(value: Any) -> Counter[str]:
    """Report structured local effects without treating them as upstream writes."""

    effects: Counter[str] = Counter()
    catalog_syncs = _catalog_sync_count(value)
    if catalog_syncs:
        effects[_LOCAL_WRITE_CATALOG_SYNC] += catalog_syncs
    if any("--output" in argv for argv in _argv_sequences(value)):
        effects[_LOCAL_WRITE_FILE_OUTPUT] += 1
    return effects


def _catalog_sync_count(value: Any) -> int:
    if isinstance(value, Mapping):
        next_step = value.get("next")
        current = int("catalog_sync_argv" in value) + int(
            value.get("code") == _TABLE_SCHEMA_SYNC_GAP
            and isinstance(next_step, Mapping)
            and _is_catalog_sync_argv(next_step.get("argv"))
        )
        return current + sum(
            _catalog_sync_count(item)
            for key, item in value.items()
            if str(key) != "catalog_sync_argv"
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return sum(_catalog_sync_count(item) for item in value)
    return 0


def _is_catalog_sync_argv(value: Any) -> bool:
    return (
        isinstance(value, list)
        and value[:4] == ["gravity", "metadata", "sync", "--all-apps"]
    )


def _argv_sequences(value: Any) -> Iterable[list[str]]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if (
                (str(key) == "argv" or str(key).endswith("_argv"))
                and isinstance(item, list)
                and all(isinstance(token, str) for token in item)
            ):
                yield item
            yield from _argv_sequences(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            yield from _argv_sequences(item)


def _selected_text(value: Any, key: str | None = None) -> Iterable[str]:
    if isinstance(value, str) and key in _TEXT_FIELDS:
        yield value
    elif isinstance(value, Mapping):
        for child_key, child in value.items():
            yield from _selected_text(child, str(child_key))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            yield from _selected_text(child, key)


def _has_credential_assignment(value: Any) -> bool:
    return any(_CREDENTIAL_ASSIGNMENT.search(text) for text in _selected_text(value))


def _has_arbitrary_transport(card: Mapping[str, Any]) -> bool:
    node = card.get("plan_node")
    request = node.get("request") if isinstance(node, Mapping) else None
    return isinstance(request, Mapping) and _transport_value(request)


def _transport_value(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).casefold() in _TRANSPORT_KEYS
            or _transport_value(item)
            for key, item in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_transport_value(item) for item in value)
    return isinstance(value, str) and value.casefold().startswith(("http://", "https://"))


def _control_failures(client: Any, blocked_transport: Any | None) -> Counter[str]:
    failures: Counter[str] = Counter()
    before = getattr(blocked_transport, "attempts", None)
    try:
        client.read("https://agent-eval.invalid/arbitrary", {"method": "DELETE"})
    except Exception:
        pass
    else:
        failures["operation_allowlist_control"] += 1
    after = getattr(blocked_transport, "attempts", None)
    if before is not None and after != before:
        failures["operation_allowlist_control"] += 1
    return failures


__all__ = [
    "LEDGER_SCHEMA_VERSION",
    "PROTECTED_SPLITS",
    "append_query_record",
    "ensure_query_allowed",
    "load_query_records",
    "query_counts",
    "security_compliance_score",
]
