"""Shape-only probes for open Gravity Insight privacy verdicts."""

from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from .core import DRAFT_ROOT, EVIDENCE_ROOT, read_json, write_json
from .probe_support import (
    family_id,
    last_primary,
    relative,
    resolve_inputs,
    semantic_success,
)
from .transport import (
    RecordingSession,
    RequestDiscipline,
    build_draft_client,
    build_runtime,
    sdk_parts,
)


MATERIAL_USER_OPERATION = "material.material_examine_user.list"
SUPPORTED_OPERATIONS = (MATERIAL_USER_OPERATION,)


def _rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = payload.get("data")
    values = data.get("list") if isinstance(data, Mapping) else None
    if not isinstance(values, list):
        return []
    return [item for item in values if isinstance(item, Mapping)]


def _field_values(
    rows: Sequence[Mapping[str, Any]], field: str
) -> tuple[list[Any], int]:
    present = [row[field] for row in rows if field in row]
    return present, len(rows) - len(present)


def _boolean_profile(
    rows: Sequence[Mapping[str, Any]], field: str
) -> dict[str, Any]:
    values, missing = _field_values(rows, field)
    true_count = sum(value is True for value in values)
    false_count = sum(value is False for value in values)
    null_count = sum(value is None for value in values)
    other_count = len(values) - true_count - false_count - null_count
    return {
        "occurrences": len(values),
        "missing_rows": missing,
        "distribution": {
            "false": false_count,
            "true": true_count,
            "null": null_count,
            "other_type": other_count,
        },
        "distinct_boolean_count": int(true_count > 0) + int(false_count > 0),
    }


def profile_verdict_payload(
    operation_id: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """Return only target-field aggregate shapes, never response values or hashes."""

    rows = _rows(payload)
    if not rows:
        return {
            "status": "still_blocked",
            "decision": "no_nonempty_list_sample",
            "row_count": 0,
            "field_profiles": {},
            "remaining_question": None,
        }

    if operation_id == MATERIAL_USER_OPERATION:
        profile = _boolean_profile(rows, "is_superuser")
        distribution = profile["distribution"]
        if profile["distinct_boolean_count"] == 2 and distribution["other_type"] == 0:
            status = "resolved_by_probe"
            decision = "sensitive_personnel_permission"
            question = None
        elif profile["occurrences"] == 0:
            status = "still_blocked"
            decision = "target_field_not_observed"
            question = None
        else:
            status = "narrowed"
            decision = "single_value_or_mixed_type_sample_cannot_distinguish_scope"
            question = (
                f"本次 probe 观测到 {len(rows)} 个用户行，is_superuser 的真假分布为 "
                f"true={distribution['true']}、false={distribution['false']}，不同布尔值数量为 "
                f"{profile['distinct_boolean_count']}。请确认：该字段是否逐行表示对应用户的超级管理员权限，"
                "还是与人员无关、仅被复制到每一行的响应级通用能力开关？"
            )
        return {
            "status": status,
            "decision": decision,
            "row_count": len(rows),
            "field_profiles": {"is_superuser": profile},
            "remaining_question": question,
        }

    raise ValueError(f"unsupported verdict probe operation: {operation_id}")


def _evidence_path(operation_id: str, evidence_root: Path) -> Path:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return evidence_root / f"{stamp}_{operation_id}.verdict.yaml"


def _probe_one(
    operation_id: str,
    *,
    draft_root: Path,
    evidence_root: Path,
    stable_client: Any,
    runtime: Any,
    recording: RecordingSession,
) -> dict[str, Any]:
    if operation_id not in SUPPORTED_OPERATIONS:
        raise ValueError(f"unsupported verdict probe operation: {operation_id}")
    source = read_json(draft_root / f"{operation_id}.json")
    if not isinstance(source, Mapping):
        raise ValueError(f"invalid draft source: {operation_id}")

    request_start = recording.discipline.total
    failed_start = recording.discipline.failed
    observation_start = len(recording.observations)
    error_type: str | None = None
    try:
        inputs = resolve_inputs(
            source["operation"].get("live_probe", {}).get("inputs", {}),
            source=source,
            stable_client=stable_client,
            recording=recording,
            parent_cache={},
        )
        client = build_draft_client(source, runtime)
        with recording.observing(operation_id, family_id(source), "privacy_verdict_shape"):
            client.read(operation_id, inputs)
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        error_type = type(exc).__name__

    observation = last_primary(recording.observations[observation_start:], operation_id)
    if (
        observation is None
        or not isinstance(observation.payload, Mapping)
        or observation.status_code < 200
        or observation.status_code >= 300
        or not semantic_success(observation.payload)
    ):
        profile = {
            "status": "still_blocked",
            "decision": "operation_unavailable_or_semantic_error",
            "row_count": 0,
            "field_profiles": {},
            "remaining_question": None,
        }
    else:
        profile = profile_verdict_payload(operation_id, observation.payload)

    probed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    evidence = {
        "schema_version": "gravity-insight.verdict-probe-evidence.v1",
        "operation_id": operation_id,
        "probed_at": probed_at,
        "route": {
            "method": source["operation"]["upstream_method"],
            "path": source["operation"]["path_template"],
        },
        "conclusion": profile,
        "request_stats": {
            "total": recording.discipline.total - request_start,
            "failed": recording.discipline.failed - failed_start,
        },
        "error_type": error_type,
        "privacy_safeguards": {
            "values_persisted": False,
            "value_hashes_persisted": False,
            "non_target_fields_persisted": False,
        },
    }
    path = _evidence_path(operation_id, evidence_root)
    write_json(path, evidence)
    return {
        "operation_id": operation_id,
        "status": profile["status"],
        "decision": profile["decision"],
        "evidence": relative(path),
        "request_stats": copy.deepcopy(evidence["request_stats"]),
        "conclusion": profile,
    }


def run_verdict_probes(
    operation_ids: Sequence[str],
    *,
    interval_seconds: float = 0.31,
    request_limit: int = 10,
    draft_root: Path = DRAFT_ROOT,
    evidence_root: Path = EVIDENCE_ROOT,
    session: Any | None = None,
) -> dict[str, Any]:
    if not operation_ids:
        raise ValueError("verdict-probe requires at least one operation_id")
    if len(operation_ids) > len(SUPPORTED_OPERATIONS):
        raise ValueError("verdict-probe accepts at most one operation")
    if len(set(operation_ids)) != len(operation_ids):
        raise ValueError("verdict-probe operation_ids must be unique")
    unsupported = sorted(set(operation_ids) - set(SUPPORTED_OPERATIONS))
    if unsupported:
        raise ValueError(f"unsupported verdict probe operation: {unsupported[0]}")

    if session is None:
        import requests

        session = requests.Session()
    discipline = RequestDiscipline(
        interval_seconds=interval_seconds, request_limit=request_limit
    )
    recording = RecordingSession(session, discipline)
    runtime = build_runtime(recording)
    stable_client = sdk_parts()["GravityInsightClient"].from_env(
        runtime=runtime, timeout=120.0, attempts=1
    )
    results = [
        _probe_one(
            operation_id,
            draft_root=draft_root,
            evidence_root=evidence_root,
            stable_client=stable_client,
            runtime=runtime,
            recording=recording,
        )
        for operation_id in operation_ids
    ]
    return {
        "schema_version": "gravity-insight.verdict-prober-run.v1",
        "ok": True,
        "status": (
            "success"
            if all(item["status"] != "still_blocked" for item in results)
            else "partial"
        ),
        "results": results,
        "request_stats": {
            "total": discipline.total,
            "failed": discipline.failed,
            "request_limit": discipline.request_limit,
            "minimum_interval_ms": int(discipline.interval_seconds * 1000),
        },
    }


__all__ = [
    "MATERIAL_USER_OPERATION",
    "SUPPORTED_OPERATIONS",
    "profile_verdict_payload",
    "run_verdict_probes",
]
