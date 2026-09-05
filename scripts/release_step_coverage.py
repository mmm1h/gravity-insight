"""Declare release step coverage independently of a job's green conclusion."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from gravity_insight.evidence_common import (
    context_bound_measurement,
    resolve_context_bound_measurement,
)

SCHEMA_VERSION = "gravity.release-step-coverage.v1"
PREREQUISITES = (
    "checkout",
    "setup_python",
    "install_tooling",
    "build_distributions",
    "check_distributions",
    "generate_sboms",
    "audit_dependencies",
    "download_ci",
    "download_secret",
    "prepare_iv",
    "integrated_validation",
    "wheel_surface",
    "canonical_consumer",
    "changelog",
)
TAIL = (
    "coverage_pre",
    "aggregate",
    "upload_distributions",
    "coverage_final",
    "upload_evidence",
)
WORKFLOW = ".github/workflows/release.yml"
JOB = "release_supply_chain"
MAX_AGE = timedelta(hours=24)


def inventory(phase: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if phase == "prepublish":
        return PREREQUISITES, TAIL
    if phase == "final":
        return PREREQUISITES + TAIL[:3], TAIL[3:]
    raise ValueError(f"unknown release coverage phase: {phase!r}")


def _coordinate(step: str) -> dict[str, str]:
    return {"workflow": WORKFLOW, "job": JOB, "step": step}


def _bindings(sha: str, run_id: str, run_attempt: str, event: str) -> dict[str, str]:
    for label, value in (("run_id", run_id), ("run_attempt", run_attempt)):
        if not isinstance(value, str) or not value.isdecimal() or int(value) <= 0:
            raise ValueError(
                f"coverage.{label}: expected positive decimal string; observed {value!r}; next: supply Actions run identity"
            )
    return {
        "commit_sha": sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "event_name": event,
    }


def capture_coverage(
    steps: Mapping[str, Any],
    *,
    sha: str,
    run_id: str,
    run_attempt: str,
    event: str,
    phase: str = "prepublish",
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(steps, Mapping):
        raise ValueError(
            "coverage steps: expected Actions steps object; next: pass toJSON(steps) through RELEASE_STEPS_JSON"
        )
    expected, excluded = inventory(phase)
    now = now or datetime.now(timezone.utc)
    bindings = _bindings(sha, run_id, run_attempt, event)
    observations = {}
    for step in expected:
        raw = steps.get(step)
        outcome = raw.get("outcome") if isinstance(raw, Mapping) else None
        # Record the raw outcome, never the continue-on-error-adjusted conclusion.
        observations[step] = context_bound_measurement(
            {"outcome": outcome, "present": step in steps},
            coordinate=_coordinate(step),
            scope={"phase": phase},
            captured_at=now,
            binds_to=bindings,
        )
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "phase": phase,
        "bindings": bindings,
        "expected_steps": list(expected),
        "excluded_steps": list(excluded),
        "exclusion_reason": "observer/self or subsequent evidence transport; not yet observable at this checkpoint",
        "unexpected_steps": sorted(set(steps) - set(expected) - set(excluded)),
        "observations": observations,
    }
    receipt["coverage"] = resolve_coverage(
        receipt,
        sha=sha,
        run_id=run_id,
        run_attempt=run_attempt,
        event=event,
        phase=phase,
        now=now,
    )
    return receipt


def resolve_coverage(
    document: Mapping[str, Any],
    *,
    sha: str,
    run_id: str,
    run_attempt: str,
    event: str = "push",
    phase: str = "prepublish",
    now: datetime | None = None,
) -> dict[str, Any]:
    expected, excluded = inventory(phase)
    bindings = _bindings(sha, run_id, run_attempt, event)
    errors = []
    for key, value in {
        "schema_version": SCHEMA_VERSION,
        "phase": phase,
        "bindings": bindings,
        "expected_steps": list(expected),
        "excluded_steps": list(excluded),
        "unexpected_steps": [],
    }.items():
        if document.get(key) != value:
            errors.append(f"{key}: expected {value!r}; observed {document.get(key)!r}")
    observations = document.get("observations")
    if not isinstance(observations, Mapping):
        errors.append("observations: expected object")
        observations = {}
    extra = sorted(set(observations) - set(expected))
    if extra:
        errors.append(f"unexpected observations: {extra}")
    entries = {}
    ran, skipped, missing, blocked = [], [], [], []
    for step in expected:
        measurement = observations.get(step)
        resolution = resolve_context_bound_measurement(
            measurement,
            expected_coordinate=_coordinate(step),
            expected_scope={"phase": phase},
            expected_bindings=bindings,
            now=now or datetime.now(timezone.utc),
            max_age=MAX_AGE,
        )
        value = resolution["value"]
        outcome = value.get("outcome") if isinstance(value, Mapping) else None
        status = resolution["status"]
        if status == "measured":
            if value == {"outcome": "skipped", "present": True}:
                status = "not_measured"
                skipped.append(step)
            elif value == {"outcome": None, "present": False}:
                status = "not_measured"
                missing.append(step)
            elif (
                outcome in ("success", "failure", "cancelled")
                and value.get("present") is True
            ):
                ran.append(step)
                if outcome != "success":
                    status = "invalid"
            else:
                status = "invalid"
        elif measurement is None:
            missing.append(step)
        passed = status == "measured" and outcome == "success"
        if not passed:
            blocked.append(f"{step}={status}({outcome or 'missing/unknown'})")
        entries[step] = {
            "status": status,
            "outcome": outcome,
            "passed": passed,
            "measurement": resolution,
        }
    statuses = {entry["status"] for entry in entries.values()}
    status = "measured"
    for candidate in ("invalid", "not_applicable", "expired", "not_measured"):
        if candidate in statuses:
            status = candidate
            break
    if errors:
        status = "invalid"
    return {
        "status": status,
        "release_grade": not blocked and not errors and event == "push",
        "expected_steps": list(expected),
        "ran_steps": ran,
        "skipped_steps": skipped,
        "missing_steps": missing,
        "excluded_steps": list(excluded),
        "steps": entries,
        "blocked": blocked,
        "errors": errors,
    }


def require_release_coverage(
    document: Mapping[str, Any], *, sha: str, run_id: str, run_attempt: str
) -> dict[str, Any]:
    coverage = resolve_coverage(
        document, sha=sha, run_id=run_id, run_attempt=run_attempt
    )
    if not coverage["release_grade"]:
        details = "; ".join(coverage["blocked"] + coverage["errors"])
        raise ValueError(
            "release coverage: expected all prepublish steps measured(success) in the current push run; "
            f"observed {details}; next: run the complete tag-push release workflow; "
            "measure/dispatch evidence cannot authorize publication"
        )
    return coverage


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phase", choices=("prepublish", "final"), default="prepublish"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = capture_coverage(
            json.loads(os.environ["RELEASE_STEPS_JSON"]),
            sha=os.environ["GITHUB_SHA"],
            run_id=os.environ["GITHUB_RUN_ID"],
            run_attempt=os.environ["GITHUB_RUN_ATTEMPT"],
            event=os.environ["GITHUB_EVENT_NAME"],
            phase=args.phase,
        )
    except (KeyError, ValueError, TypeError) as exc:
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "status": "invalid",
            "release_grade": False,
            "error": str(exc),
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    # This collector records observations; the aggregate command enforces release.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
