"""Performance, CI, and architecture maturity evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .evidence_common import (
    load_object,
    metric,
    relative,
    resolve_context_bound_measurement,
)


def performance_evidence(
    certifications: Mapping[str, Any],
    census: Mapping[str, Any],
    evaluation: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    evidence = [_budget_metric(certifications), _census_observation_metric(census)]
    if evaluation is None:
        evidence.append(
            metric(
                source="scripts/agent_usability_eval.py",
                claim="repeat reliability and request observations",
                measured=False,
                missing=("a successful current development evaluation result",),
            )
        )
        return evidence
    evidence.extend(_repeat_metrics(evaluation))
    evidence.append(_cost_metric(evaluation))
    return evidence


def _budget_metric(certifications: Mapping[str, Any]) -> dict[str, Any]:
    rows = certifications.get("journeys", [])
    budgets = [item.get("evidence", {}).get("request_budget") for item in rows]
    total = int(certifications.get("counts", {}).get("source_total", 0))
    passed = sum(_valid_budget(item) for item in budgets)
    return metric(
        source="src/gravity_insight/contracts/journeys/*.json#/request_budget",
        claim="Journey request budgets are schema-valid and bounded",
        measured=total > 0,
        passed=passed if total else None,
        total=total if total else None,
        observed={"valid_budgets": passed, "journey_sources": total},
        proxy_metric=True,
        limitation="Declared budgets do not prove production latency or throughput.",
        missing=() if total else ("Journey request budgets",),
    )


def _valid_budget(value: Any) -> bool:
    return bool(
        isinstance(value, Mapping)
        and type(value.get("known_requests_min")) is int
        and type(value.get("known_requests_max")) is int
        and value["known_requests_min"] <= value["known_requests_max"]
    )


def _census_observation_metric(census: Mapping[str, Any]) -> dict[str, Any]:
    request = census["request_governance"]
    fields = ("attempts", "limit", "concurrency", "elapsed_seconds", "pending_js", "failed_js")
    return metric(
        source="src/gravity_insight/census/data/bundle-snapshot.json#/summary",
        claim="Census request usage and observability are recorded",
        measured=True,
        passed=sum(request.get(name) is not None for name in fields),
        total=len(fields),
        observed=request,
        proxy_metric=True,
        limitation="A historical static crawl does not measure Runtime production latency.",
    )


def _repeat_metrics(evaluation: Mapping[str, Any]) -> list[dict[str, Any]]:
    repeatability = evaluation["layers"]["repeat_reliability"]
    result = []
    for name in ("product_selection", "end_to_end"):
        repeat = repeatability[name]["pass^4"]
        result.append(
            metric(
                source="evals/agent_usability repeat_reliability.pass^4",
                claim=f"{name} repeat reliability",
                measured=int(repeat["total"]) > 0,
                passed=int(repeat["passed"]),
                total=int(repeat["total"]),
                observed=repeat,
                proxy_metric=True,
                limitation="Offline repeatability is not a production performance benchmark.",
            )
        )
    return result


def _cost_metric(evaluation: Mapping[str, Any]) -> dict[str, Any]:
    cost = evaluation["layers"]["cost"]
    fields = (
        "elapsed_seconds",
        "logical_question_invocations",
        "production_http_requests",
        "socket_network_attempts",
    )
    return metric(
        source="evals/agent_usability#/layers/cost",
        claim="evaluation cost observations are emitted",
        measured=True,
        passed=sum(cost.get(name) is not None for name in fields),
        total=len(fields),
        observed={name: cost.get(name) for name in fields},
        proxy_metric=True,
        limitation="Invocation counts do not include model-token telemetry.",
    )


def ci_evidence(root: Path, repository: Mapping[str, Any]) -> list[dict[str, Any]]:
    receipt_path, receipt, resolution = _integrated_validation_measurement(
        root, repository
    )
    gates = receipt.get("gates", []) if receipt else []
    measured = resolution["status"] == "measured" and bool(gates)
    missing = (
        ()
        if measured
        else (
            "an integrated-validation receipt applicable to the expected clean exact-HEAD context",
        )
    )
    evidence = [
        metric(
            source=relative(root, receipt_path),
            claim="complete integrated validation is bound to the exact clean HEAD",
            measured=measured,
            passed=sum(item.get("exit_code") == 0 for item in gates) if measured else None,
            total=len(gates) if measured else None,
            observed={
                "receipt_present": receipt is not None,
                "commit": repository["commit"],
                "dirty": repository["dirty"],
                "measurement_status": resolution["status"],
                "reason_code": resolution["reason_code"],
                "mismatches": resolution["mismatches"],
            },
            missing=missing,
            measurement_resolution=resolution,
        )
    ]
    evidence.append(_workflow_metric(root))
    return evidence


def _integrated_validation_measurement(
    root: Path, repository: Mapping[str, Any]
) -> tuple[Path, Mapping[str, Any] | None, dict[str, Any]]:
    expected_path = (
        root / "tmp/integrated-validation" / str(repository["commit"]) / "receipt.json"
    )
    candidates = []
    for path in sorted((root / "tmp/integrated-validation").glob("*/receipt.json")):
        try:
            receipt = load_object(path)
        except (OSError, UnicodeError, ValueError):
            resolution = resolve_context_bound_measurement(
                {}, **_receipt_expectation(root, repository)
            )
            candidates.append((path, None, resolution))
            continue
        measurement = _receipt_measurement(receipt)
        resolution = resolve_context_bound_measurement(
            measurement, **_receipt_expectation(root, repository, receipt)
        )
        candidates.append((path, receipt, resolution))
    exact = [item for item in candidates if item[0] == expected_path]
    if exact:
        return exact[0]
    measured = [item for item in candidates if item[2]["status"] == "measured"]
    if measured:
        return max(measured, key=_receipt_candidate_time)
    if candidates:
        return max(candidates, key=_receipt_candidate_time)
    return (
        expected_path,
        None,
        resolve_context_bound_measurement(
            None, **_receipt_expectation(root, repository)
        ),
    )


def _receipt_expectation(
    root: Path,
    repository: Mapping[str, Any],
    receipt: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    bindings: dict[str, Any] = {"commit_sha": repository["commit"]}
    gates = receipt.get("gates") if receipt is not None else None
    if isinstance(gates, list) and all(isinstance(gate, Mapping) for gate in gates):
        bindings["gate_names"] = [gate.get("name") for gate in gates]
    return {
        "expected_coordinate": {
            "kind": "integrated_validation",
            "commit_sha": repository["commit"],
            "worktree_state": "dirty" if repository["dirty"] else "clean",
            "complete_gate_set": True,
            "trial": False,
        },
        "expected_scope": {
            "kind": "git_worktree",
            "root": root.resolve().as_posix(),
        },
        "expected_bindings": bindings,
    }


def _receipt_measurement(receipt: Mapping[str, Any]) -> Mapping[str, Any]:
    gates = receipt.get("gates")
    if (
        not isinstance(gates, list)
        or not gates
        or any(not isinstance(gate, Mapping) for gate in gates)
    ):
        return {}
    measurement = receipt.get("measurement")
    return (
        measurement
        if isinstance(measurement, Mapping)
        and _receipt_measurement_matches(receipt, measurement)
        else {}
    )


def _receipt_measurement_matches(
    receipt: Mapping[str, Any], measurement: Mapping[str, Any]
) -> bool:
    coordinate = measurement.get("coordinate")
    binds_to = measurement.get("binds_to")
    value = measurement.get("value")
    gates = receipt.get("gates", [])
    after = receipt.get("preconditions_after")
    clean = isinstance(after, Mapping) and after.get("clean") is True
    expected_coordinate = {
        "commit_sha": receipt.get("commit_sha"),
        "worktree_state": "clean" if clean else "dirty",
        "complete_gate_set": receipt.get("complete_gate_set"),
        "trial": bool(receipt.get("trial")),
    }
    expected_bindings = {
        "commit_sha": receipt.get("commit_sha"),
        "gate_names": [gate.get("name") for gate in gates],
    }
    expected_value = {
        "gate_count": len(gates),
        "integrated_validation_green": receipt.get("integrated_validation_green"),
        "overall": receipt.get("overall"),
    }
    return bool(
        _contains_expected(coordinate, expected_coordinate)
        and _contains_expected(binds_to, expected_bindings)
        and _contains_expected(value, expected_value)
        and isinstance(gates, list)
        and _same_timestamp(measurement.get("captured_at"), receipt.get("finished_at"))
    )


def _contains_expected(value: Any, expected: Mapping[str, Any]) -> bool:
    return isinstance(value, Mapping) and all(
        value.get(key) == expected_value for key, expected_value in expected.items()
    )


def _same_timestamp(left: Any, right: Any) -> bool:
    try:
        first = datetime.fromisoformat(str(left).replace("Z", "+00:00"))
        second = datetime.fromisoformat(str(right).replace("Z", "+00:00"))
    except ValueError:
        return False
    if first.tzinfo is None or second.tzinfo is None:
        return False
    return first.astimezone(timezone.utc) == second.astimezone(timezone.utc)


def _receipt_candidate_time(
    candidate: tuple[Path, Mapping[str, Any] | None, Mapping[str, Any]],
) -> str:
    context = candidate[2].get("context")
    return str(context.get("captured_at", "")) if isinstance(context, Mapping) else ""


def _workflow_metric(root: Path) -> dict[str, Any]:
    paths = sorted((root / ".github/workflows").glob("*.yml"))
    result = metric(
        source=".github/workflows/*.yml",
        claim="CI/release/census workflow definitions exist",
        measured=bool(paths),
        passed=len(paths) if paths else None,
        total=len(paths) if paths else None,
        observed=[relative(root, path) for path in paths],
        proxy_metric=True,
        limitation="Workflow presence does not prove an exact-HEAD run passed.",
        missing=() if paths else ("workflow definitions",),
    )
    result["required"] = False
    return result


def architecture_evidence(
    root: Path,
    profile: Mapping[str, Any] | None,
    certifications: Mapping[str, Any],
    *,
    profile_failure: str | None = None,
) -> list[dict[str, Any]]:
    return [
        *_quality_metrics(profile, profile_failure=profile_failure),
        _component_pointer_metric(root),
        _token_proxy_metric(certifications),
    ]


def _quality_metrics(
    profile: Mapping[str, Any] | None,
    *,
    profile_failure: str | None = None,
) -> list[dict[str, Any]]:
    if profile is None:
        missing = ["a successful isolated quality-profile collection"]
        if profile_failure:
            missing.append(profile_failure)
        return [
            metric(
                source="gravity_insight.quality.inspect_repository",
                claim="repository quality profile is available",
                measured=False,
                missing=missing,
            )
        ]
    definitions = (
        ("Runtime files are within the new-file SLOC limit", "files", "The quality ratchet allows explicitly recorded legacy debt."),
        ("functions are within the SLOC limit", "function_sloc", "Function size does not directly measure developer cycle time."),
        ("functions are within the cyclomatic complexity limit", "function_complexity", "Cyclomatic complexity is not a full maintainability measure."),
        ("Runtime files avoid operation-ID literals", "operation_literals", "Literal absence does not prove the architecture has no duplication."),
    )
    return [
        metric(
            source="gravity_insight.quality.inspect_repository",
            claim=claim,
            measured=int(profile[key]["total"]) > 0,
            passed=int(profile[key]["passed"]),
            total=int(profile[key]["total"]),
            observed={
                "items": int(profile[key]["total"]),
                "limit": int(profile[key]["limit"]),
            },
            proxy_metric=True,
            limitation=limitation,
            missing=() if int(profile[key]["total"]) > 0 else (claim,),
        )
        for claim, key, limitation in definitions
    ]


def _component_pointer_metric(root: Path) -> dict[str, Any]:
    path = root / "specs/agent-runtime/index.json"
    pointers = []
    for component in load_object(path).get("components", []):
        if not isinstance(component, Mapping):
            continue
        pointers.extend(path.parent / str(item) for item in component.get("machine_sources", []))
        if component.get("reference"):
            pointers.append(path.parent / str(component["reference"]))
    return metric(
        source=relative(root, path),
        claim="Runtime component owners point to existing machine sources and references",
        measured=bool(pointers),
        passed=sum(item.resolve().exists() for item in pointers) if pointers else None,
        total=len(pointers) if pointers else None,
        observed={"pointers": len(pointers)},
        proxy_metric=True,
        limitation="Path existence does not measure change lead time or ownership quality.",
        missing=() if pointers else ("Runtime component source pointers",),
    )


def _token_proxy_metric(certifications: Mapping[str, Any]) -> dict[str, Any]:
    rows = certifications.get("journeys", [])
    total = int(certifications.get("counts", {}).get("source_total", 0))
    bounded = sum(isinstance(item.get("evidence", {}).get("request_budget"), Mapping) for item in rows)
    return metric(
        source="src/gravity_insight/contracts/journeys/*.json#/request_budget",
        claim="bounded request budgets proxy Runtime token economy",
        measured=total > 0,
        passed=bounded if total else None,
        total=total if total else None,
        observed={"bounded": bounded, "journey_sources": total},
        proxy_metric=True,
        limitation="Request bounds constrain tool calls but do not measure model input, output, cache, or reasoning tokens.",
        missing=() if total else ("Journey request-budget contracts",),
    )


__all__ = ["architecture_evidence", "ci_evidence", "performance_evidence"]
