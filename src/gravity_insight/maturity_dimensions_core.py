"""Correctness, Journey, Skill, and Census maturity evidence."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .capability_contract import capability_contracts
from .capability_trust import CapabilityTrustService
from .evidence_common import load_object, metric, relative
from .operator_registry import OperatorRegistry
from .semantic_registry import SemanticRegistry
from .skill_contract import compile_skill_manifest


def correctness_evidence(
    profile: Mapping[str, Any] | None,
    certifications: Mapping[str, Any],
    *,
    profile_failure: str | None = None,
) -> list[dict[str, Any]]:
    return [
        *_operation_evidence(profile, profile_failure=profile_failure),
        _journey_registry_metric(certifications),
        _surface_metric(certifications),
        *_capability_evidence(),
    ]


def _operation_evidence(
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
                source="python -m gravity_insight.compiler check",
                claim="operation contracts and provenance compile deterministically",
                measured=False,
                missing=missing,
            )
        ]
    count = int(profile["operation_count"])
    measured = count > 0
    missing = () if measured else ("a successful compiler catalog",)
    return [
        metric(
            source="python -m gravity_insight.compiler check",
            claim="operation contracts compile deterministically",
            measured=measured,
            passed=count if profile["compiler_check"] == "PASS" else 0,
            total=count if measured else None,
            observed={"operations": count, "status": profile["compiler_check"]},
            missing=missing,
        ),
        metric(
            source="src/gravity_insight/contracts/generated/provenance.json",
            claim="compiled operations have provenance",
            measured=measured,
            passed=int(profile["provenance_covered"]) if measured else None,
            total=count if measured else None,
            observed={
                "covered": int(profile["provenance_covered"]),
                "operations": count,
            },
            missing=() if measured else ("compiled operation provenance",),
        ),
    ]


def _journey_registry_metric(certifications: Mapping[str, Any]) -> dict[str, Any]:
    contracts = certifications.get("journeys", [])
    total = int(certifications.get("counts", {}).get("source_total", 0))
    return metric(
        source="src/gravity_insight/contracts/journeys/*.json + Journey schema",
        claim="Journey source contracts load and bind to the ledger",
        measured=total > 0,
        passed=len(contracts) if total else None,
        total=total if total else None,
        observed={
            "loaded": len(contracts),
            "source_total": total,
            "registry_errors": len(certifications.get("registry_errors", [])),
        },
        missing=() if total else ("Journey Contract sources",),
    )


def _surface_metric(certifications: Mapping[str, Any]) -> dict[str, Any]:
    contracts = certifications.get("journeys", [])
    surfaces = [
        value
        for item in contracts
        for value in item.get("evidence", {}).get("surfaces", {}).values()
    ]
    return metric(
        source="src/gravity_insight/contracts/journeys/*.json",
        claim="Journey surfaces are available or explicitly not applicable",
        measured=bool(surfaces),
        passed=sum(value in {"available", "not_applicable"} for value in surfaces) if surfaces else None,
        total=len(surfaces) if surfaces else None,
        observed={"passing_surfaces": sum(value in {"available", "not_applicable"} for value in surfaces), "declared_surfaces": len(surfaces)},
        missing=() if surfaces else ("Journey surface declarations",),
    )


def _capability_evidence() -> list[dict[str, Any]]:
    trust = CapabilityTrustService()
    results = [
        trust.trust(
            str(item["contract"]["identity_kind"]),
            str(item["contract"]["selector"]),
        )
        for item in capability_contracts()
    ]
    predicates = (
        ("Capability Trust is stable", lambda item: item["trust_status"] == "stable"),
        ("Capability Completeness is complete", lambda item: item["completeness"] == "complete"),
        ("Capability Data Quality passes", lambda item: item["data_quality"]["status"] == "pass"),
        ("Capability provider fingerprint matches", lambda item: item["provider"]["status"] == "matched"),
    )
    return [
        metric(
            source="gravity_insight.capability_trust.CapabilityTrustService",
            claim=claim,
            measured=bool(results),
            passed=sum(predicate(item) for item in results) if results else None,
            total=len(results) if results else None,
            observed={"capabilities": len(results)},
            missing=() if results else ("Capability Contracts",),
        )
        for claim, predicate in predicates
    ]


def journey_evidence(
    root: Path,
    certifications: Mapping[str, Any],
    evaluation: Mapping[str, Any] | None,
    evaluation_observed: Mapping[str, Any],
) -> list[dict[str, Any]]:
    evidence = _target_evidence(root, certifications)
    if evaluation is None:
        evidence.append(
            metric(
                source="scripts/agent_usability_eval.py run --split development",
                claim="current Agent usability layers",
                measured=False,
                observed=dict(evaluation_observed),
                missing=("a successful current development evaluation result",),
            )
        )
        return evidence
    evidence.extend(_evaluation_layer_evidence(evaluation))
    return evidence


def _target_evidence(
    root: Path, certifications: Mapping[str, Any]
) -> list[dict[str, Any]]:
    path = root / "evals/agent_usability/journey-targets.json"
    raw = load_object(path).get("journeys", {})
    targets = list(raw.values()) if isinstance(raw, Mapping) else []
    contracts = {
        str(item["display_name"]): item
        for item in certifications.get("journeys", [])
        if isinstance(item, Mapping)
    }
    titles = [str(item.get("ledger_title")) for item in targets if isinstance(item, Mapping)]
    registered = sum(title in contracts for title in titles)
    certified = sum(contracts.get(title, {}).get("status") == "certified" for title in titles)
    common = {"measured": bool(targets), "total": len(targets) if targets else None}
    return [
        metric(
            source=relative(root, path),
            claim="evaluation targets have machine Journey contracts",
            passed=registered if targets else None,
            observed={"registered": registered, "targets": len(targets)},
            proxy_metric=True,
            limitation="Contract presence does not prove successful execution.",
            missing=() if targets else ("Journey evaluation targets",),
            **common,
        ),
        metric(
            source="gravity journey certifications --json",
            claim="evaluation targets are certified by current offline evidence",
            passed=certified if targets else None,
            observed={"certified": certified, "targets": len(targets)},
            proxy_metric=True,
            limitation="Offline certification does not replace production Journey evidence.",
            missing=() if targets else ("Journey certification targets",),
            **common,
        ),
    ]


def _evaluation_layer_evidence(evaluation: Mapping[str, Any]) -> list[dict[str, Any]]:
    layers = evaluation["layers"]
    cases = int(evaluation["case_count"])
    definitions = (
        ("product_selection", "Agent product selection", False),
        ("parameter_fillability", "Agent parameter fillability", True),
        ("end_to_end", "offline terminal Journey completion", True),
        ("error_recovery", "Agent error recovery", False),
    )
    result = []
    for key, claim, retain_skips in definitions:
        layer = layers[key]
        total = cases if retain_skips else int(layer["total"])
        result.append(
            metric(
                source="evals/agent_usability + scripts/agent_usability_eval.py",
                claim=claim,
                measured=total > 0,
                passed=int(layer["passed"]),
                total=total,
                observed={"evaluator_total": layer["total"], "full_suite_cases": cases, "failure_classes": layer.get("failure_classes", {})},
                proxy_metric=True,
                limitation="Development cases are offline proxies; production-skipped cases stay in applicable denominators.",
            )
        )
    return result


def skill_evidence(root: Path, health: Mapping[str, Any]) -> list[dict[str, Any]]:
    manifests, valid = _skill_manifests(root)
    method_report, method_report_error = _current_method_report(root)
    evidence = [
        metric(
            source="skills/library/*.json + gravity.skill.v1",
            claim="canonical Skill manifests validate",
            measured=bool(manifests),
            passed=valid if manifests else None,
            total=len(manifests) if manifests else None,
            observed={"valid": valid, "manifests": len(manifests)},
            missing=() if manifests else ("canonical Skill manifests",),
        ),
        _method_complete_metric(manifests, method_report, method_report_error),
        *_registry_evidence(health),
    ]
    return evidence


def _skill_manifests(root: Path) -> tuple[list[dict[str, Any]], int]:
    manifests = []
    valid = 0
    for path in sorted((root / "skills/library").glob("*.json")):
        value = load_object(path)
        manifests.append(value)
        try:
            compile_skill_manifest(value, label=relative(root, path))
            valid += 1
        except (RuntimeError, ValueError, TypeError):
            pass
    return manifests, valid


def _current_method_report(
    root: Path,
) -> tuple[Mapping[str, Any] | None, str | None]:
    try:
        from scripts.generate_method_gap_report import library_report

        return library_report(root), None
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        return None, type(exc).__name__


def _method_complete_metric(
    manifests: list[dict[str, Any]],
    report: Mapping[str, Any] | None,
    report_error: str | None,
) -> dict[str, Any]:
    summary = report.get("summary", {}) if report is not None else {}
    source = report.get("source", {}) if report is not None else {}
    report_count = int(summary.get("skill_count", 0))
    measured = bool(manifests) and report is not None and report_count == len(manifests)
    missing = ()
    if not measured:
        missing = ("a current Method Complete report for every canonical Skill",)
    return metric(
        source="scripts/generate_method_gap_report.py::library_report(current manifests)",
        claim="Skill method completeness is computed from current canonical manifests",
        measured=measured,
        passed=int(summary["method_complete_true"]) if measured else None,
        total=report_count if measured else None,
        observed={
            "manifests": len(manifests),
            "report_skills": report_count,
            "method_complete": (
                int(summary["method_complete_true"]) if measured else None
            ),
            "method_incomplete": (
                int(summary["method_complete_false"]) if measured else None
            ),
            "manifest_set_sha256": source.get("manifest_set_sha256"),
            "generation": source.get("generation"),
            "report_error": report_error,
        },
        missing=missing,
    )


def _registry_evidence(health: Mapping[str, Any]) -> list[dict[str, Any]]:
    semantic = SemanticRegistry().list()
    operator = OperatorRegistry().list()
    provider = next(item for item in health["checks"] if item["id"] == "provider_offline_reachability")
    rows = (
        ("gravity semantics list", "Semantic definitions compile", semantic["count"], semantic["count"]),
        ("gravity operators list", "Operator implementations match contracts", operator["count"], operator["count"]),
        ("gravity runtime health", "Context Provider is reachable offline", int(provider["status"] == "pass"), 1),
    )
    return [
        metric(
            source=source,
            claim=claim,
            measured=total > 0,
            passed=passed if total else None,
            total=total if total else None,
            observed={"count": total},
            missing=() if total else (claim,),
        )
        for source, claim, passed, total in rows
    ]


def census_evidence(status: Mapping[str, Any]) -> list[dict[str, Any]]:
    current = status["current"]
    if not current["measured"]:
        return [
            metric(
                source="gravity census status --json",
                claim="current upstream drift and reliability state",
                measured=False,
                observed=current,
                missing=current["missing"],
                measurement_resolution=current["measurement"],
            )
        ]
    baseline = status["baseline"]
    routes = int(baseline["routes"])
    accounted = routes - int(baseline["unaccounted"])
    checks = (
        current["drift_conclusion_available"] is True,
        current["failure_class"] is None,
        current["changed"] is False,
    )
    return [
        metric(
            source="src/gravity_insight/census/data/coverage.json",
            claim="census routes are accounted",
            measured=routes > 0,
            passed=accounted,
            total=routes,
            observed=baseline,
        ),
        metric(
            source="current Census fetch-step and diff receipts",
            claim="current crawl is complete, classified, and unchanged",
            measured=True,
            passed=sum(checks),
            total=len(checks),
            observed=current,
            measurement_resolution=current["measurement"],
        ),
    ]


__all__ = [
    "census_evidence",
    "correctness_evidence",
    "journey_evidence",
    "skill_evidence",
]
