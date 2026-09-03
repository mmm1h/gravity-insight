"""Performance, CI, and architecture maturity evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .evidence_common import load_object, metric, relative


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
    receipt_path = root / "tmp/integrated-validation" / str(repository["commit"]) / "receipt.json"
    receipt = load_object(receipt_path) if receipt_path.is_file() else None
    gates = receipt.get("gates", []) if receipt else []
    measured = _receipt_is_current(receipt, repository) and bool(gates)
    evidence = [
        metric(
            source=relative(root, receipt_path),
            claim="complete integrated validation is bound to the exact clean HEAD",
            measured=measured,
            passed=sum(item.get("exit_code") == 0 for item in gates) if measured else None,
            total=len(gates) if measured else None,
            observed={"receipt_present": receipt is not None, "commit": repository["commit"], "dirty": repository["dirty"]},
            missing=() if measured else ("a complete integrated-validation receipt for the exact clean HEAD",),
        )
    ]
    evidence.append(_workflow_metric(root))
    return evidence


def _receipt_is_current(
    receipt: Mapping[str, Any] | None, repository: Mapping[str, Any]
) -> bool:
    return bool(
        receipt
        and receipt.get("commit_sha") == repository["commit"]
        and receipt.get("complete_gate_set") is True
        and receipt.get("preconditions_after", {}).get("clean") is True
    )


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
