"""Requirement 2.1 maturity score derived only from machine evidence."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .census.status import census_status
from .documentation_status import documentation_report
from .evidence_common import (
    context_bound_measurement,
    dimension,
    git_state,
    load_object,
    metric,
    resolve_context_bound_measurement,
)
from .journey_certification import journey_certifications
from .maturity_dimensions_core import (
    census_evidence,
    correctness_evidence,
    journey_evidence,
    skill_evidence,
)
from .maturity_dimensions_ops import (
    architecture_evidence,
    ci_evidence,
    performance_evidence,
)
from .paths import PROJECT_ROOT
from .runtime_health import runtime_health_report


DIMENSIONS = (
    ("correctness_trust_completeness_surface_parity", "正确性、Trust、Completeness、Surface Parity", 20),
    ("journey_agent_value", "真实 Journey 与 Agent 使用价值", 15),
    ("skill_semantic_operator_context", "Skill / Semantic / Operator / Context 成熟度", 15),
    ("upstream_drift_reliability_operations", "上游漂移、可靠性与运行运维", 10),
    ("performance_request_governance_observability", "性能、请求治理与可观测性", 10),
    ("ci_release_security_supply_chain", "CI、Release、安全与供应链", 10),
    ("architecture_maintainability_efficiency_tokens", "架构可维护性、开发效率与 Token 经济", 10),
    ("documentation_information_architecture", "文档与信息架构", 10),
)

_QUALITY_PROFILE_SCRIPT = """
import json
import sys
from pathlib import Path
from gravity_insight.quality import (
    COMPLEXITY_LIMIT,
    FILE_SLOC_LIMIT,
    FUNCTION_SLOC_LIMIT,
    inspect_repository,
)
profile = inspect_repository(Path(sys.argv[1]))
files = profile.file_sloc
functions = profile.functions
literal_files = {item.path for item in profile.operation_literals}
print(json.dumps({
    "operation_count": profile.operation_count,
    "compiler_check": profile.compiler_check,
    "provenance_covered": profile.provenance_covered,
    "files": {
        "passed": sum(value <= FILE_SLOC_LIMIT for value in files.values()),
        "total": len(files),
        "limit": FILE_SLOC_LIMIT,
    },
    "function_sloc": {
        "passed": sum(item.sloc <= FUNCTION_SLOC_LIMIT for item in functions),
        "total": len(functions),
        "limit": FUNCTION_SLOC_LIMIT,
    },
    "function_complexity": {
        "passed": sum(item.complexity <= COMPLEXITY_LIMIT for item in functions),
        "total": len(functions),
        "limit": COMPLEXITY_LIMIT,
    },
    "operation_literals": {
        "passed": len(files) - len(literal_files),
        "total": len(files),
        "limit": 0,
    },
}))
"""


def _evaluation(root: Path) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    temporary_root = root / "tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="maturity-eval-", dir=temporary_root))
    command = (
        sys.executable,
        str(root / "scripts/agent_usability_eval.py"),
        "run",
        "--split",
        "development",
        "--output-dir",
        str(output),
    )
    try:
        return _run_evaluation(root, output, command)
    finally:
        shutil.rmtree(output)


def _run_evaluation(
    root: Path, output: Path, command: Sequence[str]
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    completed = subprocess.run(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        timeout=600,
    )
    candidates = sorted(output.glob("result-development-*.json"))
    if completed.returncode or not candidates:
        return None, {
            "exit_code": completed.returncode,
            "stderr_tail": completed.stderr.decode(
                "utf-8", errors="replace"
            ).splitlines()[-5:],
        }
    result = load_object(candidates[-1])
    return result, {
        "exit_code": completed.returncode,
        "subject": result.get("subject"),
        "run_at": result.get("run_at"),
        "suite_version": result.get("suite_version"),
    }


def _quality_profile(root: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        completed = subprocess.run(
            (sys.executable, "-c", _QUALITY_PROFILE_SCRIPT, str(root)),
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        return None, f"isolated quality-profile collection failed: {type(exc).__name__}"
    if completed.returncode:
        return (
            None,
            f"isolated quality-profile process exited with code {completed.returncode}",
        )
    if not isinstance(completed.stdout, str) or not completed.stdout.strip():
        return None, "isolated quality-profile stdout was missing or empty"
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        return (
            None,
            "isolated quality-profile stdout was not a JSON document "
            f"(line {exc.lineno}, column {exc.colno}: {exc.msg})",
        )
    if not isinstance(value, dict):
        return None, "isolated quality-profile stdout JSON root was not an object"
    return value, None


def _profile_measurement(
    root: Path,
    repository: Mapping[str, Any],
    profile: Mapping[str, Any] | None,
    failure: str | None,
) -> dict[str, Any]:
    context = {
        "coordinate": {"kind": "repository_quality_profile"},
        "scope": {"kind": "git_worktree", "root": root.resolve().as_posix()},
        "binds_to": {
            "commit_sha": repository["commit"],
            "worktree_state": "dirty" if repository["dirty"] else "clean",
        },
    }
    captured = (
        context_bound_measurement(profile, captured_at=datetime.now(timezone.utc), **context)
        if profile is not None else None
    )
    resolution = resolve_context_bound_measurement(
        captured,
        expected_coordinate=context["coordinate"],
        expected_scope=context["scope"],
        expected_bindings=context["binds_to"],
    )
    return {"measurement": captured, "resolution": resolution, "collection_failure": failure}


def _evidence_sets(
    root: Path,
    *,
    profile: Any,
    profile_failure: str | None,
    certifications: Mapping[str, Any],
    census: Mapping[str, Any],
    health: Mapping[str, Any],
    docs: Mapping[str, Any],
    evaluation: Mapping[str, Any] | None,
    evaluation_observed: Mapping[str, Any],
    repository: Mapping[str, Any],
) -> Sequence[list[dict[str, Any]]]:
    docs_metric = metric(
        source="gravity docs check --json",
        claim="documentation governance checks pass",
        measured=docs["summary"]["total"] > 0,
        passed=docs["summary"]["passed"],
        total=docs["summary"]["total"],
        observed=docs["summary"],
    )
    return (
        correctness_evidence(
            profile, certifications, profile_failure=profile_failure
        ),
        journey_evidence(root, certifications, evaluation, evaluation_observed),
        skill_evidence(root, health),
        census_evidence(census),
        performance_evidence(certifications, census, evaluation),
        ci_evidence(root, repository),
        architecture_evidence(
            root, profile, certifications, profile_failure=profile_failure
        ),
        [docs_metric],
    )


def _blocking_gates(
    health: Mapping[str, Any],
    docs: Mapping[str, Any],
    evaluation: Mapping[str, Any] | None,
    all_measured: bool,
) -> list[dict[str, Any]]:
    return [
        {"id": "runtime_health", "satisfied": health["ok"], "source": "gravity runtime health --json"},
        {"id": "docs_check", "satisfied": docs["ok"], "source": "gravity docs check --json"},
        {"id": "agent_security", "satisfied": bool(evaluation and evaluation.get("security_hard_gate_passed") is True), "source": "evals/agent_usability development evaluation"},
        {"id": "all_dimensions_measured", "satisfied": all_measured, "source": "maturity dimension evidence"},
    ]


def _total(dimensions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    all_measured = all(item["measured"] for item in dimensions)
    measured_score = round(
        sum(float(item["score"]) for item in dimensions if item["measured"]), 2
    )
    measured_max = sum(int(item["max"]) for item in dimensions if item["measured"])
    unmeasured_max = sum(int(item["max"]) for item in dimensions if not item["measured"])
    upper = round(measured_score + unmeasured_max, 2)
    return {
        "status": "measured" if all_measured else "partially_measured",
        "score": measured_score if all_measured else None,
        "max": sum(item[2] for item in DIMENSIONS),
        "measured": all_measured,
        "measured_score": measured_score,
        "measured_max": measured_max,
        "unmeasured_max": unmeasured_max,
        "score_upper_bound": upper,
        "minimum_gap_to_90": round(max(0.0, 90 - upper), 2),
        "normalized_estimate": None,
        "unavailable_evidence_statuses": sorted(
            {
                str(item.get("status", "not_measured"))
                for item in dimensions
                if not item["measured"]
            }
        ),
    }


def maturity_score(root: Path = PROJECT_ROOT) -> dict[str, Any]:
    root = root.resolve()
    repository = git_state(root)
    profile, profile_failure = _quality_profile(root)
    certifications = journey_certifications(root)
    census = census_status(root)
    health = runtime_health_report(root, include_compiler=False)
    docs = documentation_report(root)
    evaluation, observed = _evaluation(root)
    sets = _evidence_sets(
        root,
        profile=profile,
        profile_failure=profile_failure,
        certifications=certifications,
        census=census,
        health=health,
        docs=docs,
        evaluation=evaluation,
        evaluation_observed=observed,
        repository=repository,
    )
    dimensions = [
        dimension(dimension_id=item[0], name=item[1], maximum=item[2], evidence=evidence)
        for item, evidence in zip(DIMENSIONS, sets)
    ]
    total = _total(dimensions)
    gates = _blocking_gates(health, docs, evaluation, total["measured"])
    threshold = _threshold(dimensions, total, gates)
    repository["measurement"] = _maturity_measurement(
        root,
        repository,
        status="measured" if total["measured"] else "partially_measured",
        total=total,
        captured_at=datetime.now(timezone.utc),
    )
    return {
        "schema_version": "gravity.maturity-score.v1",
        "status": "measured" if total["measured"] else "partially_measured",
        "dimensions": dimensions,
        "total": total,
        "threshold": threshold,
        "blocking_gates": gates,
        "repository": repository,
        "network_called": False,
        "quality_profile": _profile_measurement(root, repository, profile, profile_failure),
    }


def _maturity_measurement(
    root: Path,
    repository: Mapping[str, Any],
    *,
    status: str,
    total: Mapping[str, Any],
    captured_at: datetime,
) -> dict[str, Any]:
    return context_bound_measurement(
        {"status": status, "total": dict(total)},
        coordinate={
            "kind": "maturity_score",
            "commit_sha": repository["commit"],
            "worktree_state": "dirty" if repository["dirty"] else "clean",
        },
        scope={"kind": "git_worktree", "root": root.resolve().as_posix()},
        captured_at=captured_at,
        binds_to={
            "commit_sha": repository["commit"],
            "branch": repository["branch"],
        },
    )


def _threshold(
    dimensions: Sequence[Mapping[str, Any]],
    total: Mapping[str, Any],
    gates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    dimension_pass = all(
        float(item["score"]) / int(item["max"]) >= 0.7
        for item in dimensions
        if item["measured"]
    )
    satisfied = bool(
        total["measured"]
        and float(total["score"]) >= 90
        and dimension_pass
        and all(item["satisfied"] for item in gates)
    )
    return {
        "total_minimum": 90,
        "dimension_minimum_ratio": 0.7,
        "satisfied": satisfied,
    }


__all__ = ["DIMENSIONS", "maturity_score"]
