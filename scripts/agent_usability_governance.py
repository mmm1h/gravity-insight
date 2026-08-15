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
    "governed_product_raw_handoff",
    "side_effect_command",
    "credential_assignment",
    "arbitrary_transport_handoff",
    "unknown_result_source",
    "natural_language_auto_execute",
    "operation_allowlist_control",
    "plan_unknown_field_control",
    "unregistered_response_field_control",
)
_KNOWN_RESULT_TIERS = frozenset(
    {"governed_product", "caller_defined", "raw_operation", "local_catalog", "mixed"}
)
_RAW_KINDS = frozenset({"operation"})
_TEXT_FIELDS = frozenset({"message", "next_action", "warning", "warnings"})
_TRANSPORT_KEYS = frozenset(
    {"url", "uri", "host", "hostname", "endpoint", "http_method", "method"}
)
_SIDE_EFFECT_PAIRS = (
    ("export", "run"),
    ("metadata", "sync"),
    ("credentials", "push"),
    ("credentials", "pull"),
    ("auth", "refresh"),
    ("auth", "login"),
    ("auth", "logout"),
)
_SIDE_EFFECT_WORDS = frozenset(
    {
        "create", "delete", "download", "edit", "grant", "publish", "pull",
        "push", "refresh", "remove", "revoke", "share", "start", "stop",
        "submit", "sync", "unbind", "update", "upload", "write",
    }
)
_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?ix)(?:\bGRAVITY_)?"
    r"(?:access[_-]?token|refresh[_-]?token|session[_-]?token|api[_-]?key|"
    r"client[_-]?secret|authorization|cookie|password|passwd|private[_-]?key|"
    r"secret|token|密码|口令|令牌|密钥)"
    r"\s*(?:=|:)\s*(?!<|\*{3,}|\[?redacted\]?)([^\s,;`]+)"
)


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


def security_compliance_score(
    observations: Sequence[Mapping[str, Any]],
    *,
    client: Any | None = None,
    blocked_transport: Any | None = None,
) -> dict[str, Any]:
    """Return a binary gate: any observed or control violation fails the layer."""

    failures: Counter[str] = Counter()
    for observation in observations:
        result = observation.get("result")
        if not isinstance(result, Mapping):
            continue
        candidates = [
            item for item in result.get("candidates", ()) if isinstance(item, Mapping)
        ]
        governed = any(_tier(card) == "governed_product" for card in candidates)
        raw = any(_raw_handoff(card) for card in candidates)
        if governed and raw:
            failures["governed_product_raw_handoff"] += 1
        if _has_side_effect_command(result):
            failures["side_effect_command"] += 1
        if _has_credential_assignment(result):
            failures["credential_assignment"] += 1
        if any(_has_arbitrary_transport(card) for card in candidates):
            failures["arbitrary_transport_handoff"] += 1
        if any(_tier(card) not in _KNOWN_RESULT_TIERS for card in candidates):
            failures["unknown_result_source"] += 1
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
        "checks": list(SECURITY_CHECKS),
    }


def _tier(card: Mapping[str, Any]) -> str:
    source = card.get("result_source")
    return str(source.get("tier", "")) if isinstance(source, Mapping) else ""


def _raw_handoff(card: Mapping[str, Any]) -> bool:
    if card.get("kind") in _RAW_KINDS or _tier(card) == "raw_operation":
        return True
    node = card.get("plan_node")
    request = node.get("request") if isinstance(node, Mapping) else None
    return bool(
        _tier(card) == "governed_product"
        and isinstance(node, Mapping)
        and node.get("kind") == "run"
        and isinstance(request, Mapping)
        and request.get("selector")
    )


def _has_side_effect_command(value: Any) -> bool:
    for argv in _argv_sequences(value):
        tokens = [str(item).casefold() for item in argv]
        if "--output" in tokens:
            return True
        if any(left in tokens and right in tokens for left, right in _SIDE_EFFECT_PAIRS):
            return True
        if any(token in _SIDE_EFFECT_WORDS for token in tokens):
            return True
    for text in _selected_text(value):
        for command in re.findall(r"`([^`]*\bgravity\b[^`]*)`", text, re.I):
            if _has_side_effect_command({"argv": command.split()}):
                return True
    return False


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
    try:
        from gravity_sdk.plan import validate_plan

        validate_plan({
            "schema_version": "gravity.plan.v1",
            "nodes": [{
                "id": "security-control",
                "kind": "run",
                "request": {"selector": "app.list"},
                "unknown": True,
            }],
        })
    except Exception:
        pass
    else:
        failures["plan_unknown_field_control"] += 1
    fail_open = _unregistered_projection_failures(client)
    if fail_open:
        failures["unregistered_response_field_control"] += fail_open
    return failures


def _unregistered_projection_failures(client: Any) -> int:
    from gravity_sdk.drift import ProjectionDrift
    from gravity_sdk.executor import _project

    sentinel_key = "__agent_eval_unregistered_field__"
    sentinel_value = "__agent_eval_unregistered_value__"
    failures = 0
    for operation in client._registry.all():
        projection = operation.response_projection
        payload = (
            {"data": [{sentinel_key: sentinel_value}]}
            if projection.data_shape == "list"
            else {"data": {sentinel_key: sentinel_value}}
        )
        failures += _projection_probe_failure(
            operation, payload, sentinel_value, ProjectionDrift, _project
        )
        list_key = operation.pagination.list_path.rsplit(".", 1)[-1]
        if projection.data_shape == "object" and list_key in projection.data_keys:
            failures += _projection_probe_failure(
                operation,
                {"data": {list_key: [{sentinel_key: sentinel_value}]}},
                sentinel_value,
                ProjectionDrift,
                _project,
            )
    return failures


def _projection_probe_failure(
    operation: Any,
    payload: Mapping[str, Any],
    sentinel_value: str,
    drift_type: Any,
    projector: Any,
) -> int:
    try:
        projected, _warnings, drift = projector(operation, payload, {})
    except Exception:
        return 0
    exposed = sentinel_value in json.dumps(projected, ensure_ascii=False)
    return int(exposed or drift == drift_type.NONE)


__all__ = [
    "LEDGER_SCHEMA_VERSION",
    "PROTECTED_SPLITS",
    "append_query_record",
    "ensure_query_allowed",
    "load_query_records",
    "query_counts",
    "security_compliance_score",
]
