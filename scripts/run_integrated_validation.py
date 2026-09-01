from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFINITION = (
    "Every applicable included gate passes on one clean main commit using this "
    "worktree's independent .venv; optional prerequisite skips remain explicit, "
    "and one JSON receipt binds the result to that exact HEAD."
)
POST_RELEASE_GATES = (
    {
        "name": "release_provenance_live_pypi",
        "classification": "post_release",
        "included": False,
        "reason": (
            "Live PyPI provenance requires external network and publication state; "
            "deterministic integrated validation runs the offline fixture instead."
        ),
    },
)
PACKAGE_REFERENCE_STALE_GUIDANCE = "\n".join(
    (
        "Package-reference checkpoint receipt is stale. It binds the repository scan's file "
        "universe and counts, scanner and generator hashes, every "
        "coordinate-bound disposition and its evidence, and the "
        "actionable/blocker summary. Do not blindly regenerate it.",
        "A rebind is safe only after manual comparison shows that the change is "
        "limited to newly added non-reference files: no existing source_key "
        "disappeared or changed; sites_sha256, tracked-site/disposition counts, "
        "classifications, actionable count, and blocker count are unchanged.",
        "Stop for manual package-boundary review if any disposition count changes, any site "
        "disappears or changes classification, any blocker/actionable count "
        "changes, or scanner/generator logic changed.",
        "After that review approves a rebind: run `python "
        "scripts/generate_agent_module_reference_dispositions.py`; inspect the "
        "candidate receipt diff; do not modify or rebind the immutable baseline "
        "fixture, Canonical Architecture directive, or component index. Run the "
        "generator once more to confirm the fixed point; then run `python "
        "scripts/generate_agent_module_reference_dispositions.py --check` and "
        "require exit 0.",
    )
)


@dataclass(frozen=True)
class GateSpec:
    name: str
    command: tuple[str, ...]
    timeout_seconds: int = 300


def gate_specs(python: Path, run_root: Path) -> tuple[GateSpec, ...]:
    py = str(python)
    usability = run_root / "agent-usability"
    return (
        GateSpec(
            "unittest_collector",
            (py, "scripts/run_unittest_shards.py"),
            1800,
        ),
        GateSpec(
            "pytest_collector",
            (py, "-m", "pytest", "-q", "-n", "auto", "--dist", "load"),
            1800,
        ),
        GateSpec(
            "test_duration_budget",
            (py, "scripts/check_test_duration_budget.py"),
            1800,
        ),
        GateSpec("compiler_check", (py, "-m", "gravity_insight.compiler", "check")),
        GateSpec("quality_check", (py, "-m", "gravity_insight.quality", "check")),
        GateSpec("changelog", (py, "scripts/check_changelog.py")),
        GateSpec(
            "generator_release_compatibility",
            (py, "scripts/generate_release_compatibility.py", "--check"),
        ),
        GateSpec(
            "agent_usability_development",
            (
                py,
                "scripts/agent_usability_eval.py",
                "run",
                "--split",
                "development",
                "--output-dir",
                str(usability),
            ),
            600,
        ),
        GateSpec("cli_help", (py, "-m", "gravity_insight", "--help")),
        GateSpec(
            "cli_sql_offline_smoke",
            (
                py,
                "-m",
                "gravity_insight",
                "--workspace",
                "examples/workspace",
                "sql",
                "--dry-run",
            ),
        ),
        GateSpec(
            "cli_census_offline_smoke",
            (py, "-m", "gravity_insight", "census", "--smoke"),
        ),
        GateSpec(
            "cli_insight_offline_smoke",
            (py, "-m", "gravity_insight", "insight", "--dry-run"),
        ),
        GateSpec("git_diff_check", ("git", "diff", "--check")),
        GateSpec(
            "runtime_component_index",
            (
                py,
                "-m",
                "pytest",
                "-q",
                "tests/test_agent_runtime_requirement_graph.py",
            ),
        ),
        GateSpec(
            "generator_agent_guides",
            (py, "scripts/generate_agent_skills.py", "--check"),
        ),
        GateSpec(
            "generator_skill_packages",
            (py, "scripts/generate_skill_packages.py", "--check"),
        ),
        GateSpec(
            "generator_journey_ledger",
            (py, "scripts/generate_journey_ledger.py", "--check"),
        ),
        GateSpec(
            "generator_skill_library",
            (py, "scripts/generate_skill_library.py", "--check"),
        ),
        GateSpec(
            "generator_execution_variant",
            (
                py,
                "scripts/generate_execution_variant_characterization.py",
                "--check",
            ),
        ),
        GateSpec(
            "r12_three_stage_rollback",
            (py, "scripts/validate_r12_stage_rollbacks.py"),
            600,
        ),
        GateSpec(
            "package_reference_checkpoint",
            (py, "scripts/generate_agent_module_reference_dispositions.py", "--check"),
            600,
        ),
        GateSpec(
            "public_api_export_manifest",
            (py, "scripts/generate_public_api_exports.py"),
        ),
        GateSpec(
            "release_provenance_offline_fixture",
            (
                py,
                "-m",
                "unittest",
                "tests.test_release_channel.ReleaseProvenanceTests",
            ),
        ),
        GateSpec(
            "installed_wheel_surface_matrix",
            (py, "scripts/check_installed_wheel_surface_matrix.py"),
            600,
        ),
        GateSpec(
            "installed_wheel_canonical_consumer",
            (py, "scripts/check_installed_wheel_consumer.py"),
            900,
        ),
        GateSpec(
            "promotion_readiness",
            (py, "scripts/check_promotion_readiness.py"),
        ),
        GateSpec(
            "cumulative_capability",
            (
                py,
                "scripts/check_cumulative_capabilities.py",
                "--base",
                "main",
                "--head",
                "HEAD",
            ),
        ),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(arguments)} failed: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def preconditions() -> dict[str, Any]:
    expected_venv = (ROOT / ".venv").resolve()
    executable = Path(sys.executable).resolve()
    prefix = Path(sys.prefix).resolve()
    head = _git("rev-parse", "HEAD")
    branch = _git("branch", "--show-current")
    dirty_paths = _git("status", "--porcelain", "--untracked-files=all").splitlines()
    return {
        "head": head,
        "branch": branch,
        "branch_is_main": branch == "main",
        "clean": not dirty_paths,
        "dirty_paths": dirty_paths,
        "expected_venv": str(expected_venv),
        "python_executable": str(executable),
        "python_prefix": str(prefix),
        "independent_venv": (
            prefix == expected_venv
            and sys.prefix != sys.base_prefix
            and executable.is_relative_to(expected_venv)
        ),
    }


def _gate_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["GRAVITY_INSIGHT_AUTO_UPGRADE"] = "0"
    # pip's negative boolean option uses "0" to activate --no-build-isolation.
    environment["PIP_NO_BUILD_ISOLATION"] = "0"
    environment["HTTP_PROXY"] = "http://127.0.0.1:9"
    environment["HTTPS_PROXY"] = "http://127.0.0.1:9"
    environment["ALL_PROXY"] = "http://127.0.0.1:9"
    environment["NO_PROXY"] = "127.0.0.1,localhost"
    return environment


def _summary(output: str) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    pytest = re.search(r"(\d+) passed(?:, (\d+) subtests passed)?", output)
    if pytest:
        summary["passed"] = int(pytest.group(1))
        if pytest.group(2):
            summary["subtests_passed"] = int(pytest.group(2))
    unittest_count = re.search(r"Ran (\d+) tests?", output)
    if unittest_count:
        summary["tests_run"] = int(unittest_count.group(1))
        summary["unittest_ok"] = bool(
            re.search(r"(?m)^OK(?: \(skipped=\d+\))?$", output)
        )
    compiler = re.search(r"check: (\d+) operations, (\d+) manifests", output)
    if compiler:
        summary["operations"] = int(compiler.group(1))
        summary["manifests"] = int(compiler.group(2))
    quality = re.search(
        r"debt_files=(\d+).*debt_functions=(\d+).*"
        r"debt_complexity=(\d+).*debt_operation_literals=(\d+)",
        output,
    )
    if quality:
        summary["quality_debt"] = {
            "files": int(quality.group(1)),
            "functions": int(quality.group(2)),
            "complexity": int(quality.group(3)),
            "operation_literals": int(quality.group(4)),
        }
    cases = re.search(r"- Cases: (\d+)", output)
    security = re.search(r"Security compliance hard gate: (\w+)", output)
    requests = re.search(r"Production HTTP requests: (\d+)", output)
    if cases:
        summary["usability_cases"] = int(cases.group(1))
    if security:
        summary["security_gate"] = security.group(1)
    if requests:
        summary["production_http_requests"] = int(requests.group(1))
    lines = [line for line in output.splitlines() if line.strip()]
    if lines:
        try:
            value = json.loads(lines[-1])
        except json.JSONDecodeError:
            value = None
        if isinstance(value, Mapping):
            for key in (
                "passed",
                "status",
                "reason_code",
                "reason",
                "strict_prerequisites",
                "promotion_complete",
                "all_index_requirements_main_integrated",
                "case_count",
                "surface_count",
                "network_calls",
                "consumer_commit",
                "head_commit",
            ):
                if key in value:
                    summary[key] = value[key]
            if isinstance(value.get("summary"), Mapping):
                summary["tool_summary"] = dict(value["summary"])
            check = value.get("check")
            if isinstance(check, Mapping):
                for key in ("consumer_commit", "network_calls"):
                    if key in check:
                        summary[key] = check[key]
                if isinstance(check.get("summary"), Mapping):
                    summary["tool_summary"] = dict(check["summary"])
    return summary


def _gate_status(exit_code: int, summary: Mapping[str, Any]) -> str:
    reported = summary.get("status")
    if reported == "pass":
        return "pass" if exit_code == 0 else "fail"
    if reported == "skipped":
        reason = summary.get("reason")
        if exit_code == 0 and isinstance(reason, str) and reason.strip():
            return "skipped"
        return "fail"
    if reported == "fail":
        return "fail"
    return "pass" if exit_code == 0 else "fail"


def run_gate(
    gate: GateSpec, logs: Path, environment: Mapping[str, str]
) -> dict[str, Any]:
    started_at = _utc_now()
    started = time.monotonic()
    log = logs / f"{gate.name}.log"
    timed_out = False
    with log.open("w", encoding="utf-8", newline="\n") as stream:
        try:
            completed = subprocess.run(
                list(gate.command),
                cwd=ROOT,
                env=dict(environment),
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=gate.timeout_seconds,
                check=False,
            )
            exit_code = completed.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            exit_code = 124
            stream.write(
                f"\nTIMEOUT after {gate.timeout_seconds} seconds; process terminated\n"
            )
    output = log.read_text(encoding="utf-8", errors="replace")
    if gate.name == "package_reference_checkpoint" and "stale checkpoint receipt:" in output:
        output += "\n" + PACKAGE_REFERENCE_STALE_GUIDANCE + "\n"
        log.write_text(output, encoding="utf-8", newline="\n")
    summary = _summary(output)
    status = _gate_status(exit_code, summary)
    reason = summary.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        reason = None
    if status == "fail" and reason is None:
        reason = (
            f"gate timed out after {gate.timeout_seconds} seconds"
            if timed_out
            else f"gate exited with code {exit_code}"
        )
    return {
        "name": gate.name,
        "command": list(gate.command),
        "started_at": started_at,
        "finished_at": _utc_now(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "timeout_seconds": gate.timeout_seconds,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "status": status,
        "passed": status == "pass",
        "reason_code": summary.get("reason_code"),
        "reason": reason,
        "log_path": log.relative_to(ROOT).as_posix(),
        "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
        "summary": summary,
    }


def integrated_green(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    gates: Sequence[Mapping[str, Any]],
    *,
    complete_gate_set: bool,
) -> bool:
    return bool(
        complete_gate_set
        and before.get("branch_is_main") is True
        and before.get("clean") is True
        and before.get("independent_venv") is True
        and after.get("clean") is True
        and after.get("head") == before.get("head")
        and all(
            gate.get("exit_code") == 0
            and gate.get("status", "pass") in {"pass", "skipped"}
            for gate in gates
        )
    )


def summarize_gate_results(gates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    counts = {status: 0 for status in ("pass", "skipped", "fail")}
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for gate in gates:
        status = str(gate.get("status", "fail"))
        if status not in counts:
            status = "fail"
        counts[status] += 1
        if status not in {"skipped", "fail"}:
            continue
        detail = {
            "name": gate.get("name"),
            "reason_code": gate.get("reason_code"),
            "reason": gate.get("reason"),
        }
        (skipped if status == "skipped" else failed).append(detail)
    return {
        "gate_status_counts": counts,
        "skipped_gates": skipped,
        "failed_gates": [item["name"] for item in failed],
        "failed_gate_details": failed,
    }


def _write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run and receipt exact-HEAD integrated validation."
    )
    parser.add_argument(
        "--trial",
        action="store_true",
        help="Run on a non-main branch, but never report integrated green.",
    )
    parser.add_argument(
        "--only",
        help="Comma-separated gate names for a non-green diagnostic trial.",
    )
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        before = preconditions()
    except RuntimeError as exc:
        print(f"integrated validation preflight failed: {exc}", file=sys.stderr)
        return 2
    if not before["clean"]:
        print(
            json.dumps(
                {
                    "refused": True,
                    "reason": "worktree_not_clean",
                    "preconditions": before,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    if not before["independent_venv"]:
        print(
            json.dumps(
                {
                    "refused": True,
                    "reason": "independent_worktree_venv_required",
                    "preconditions": before,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    if not before["branch_is_main"] and not args.trial:
        print(
            json.dumps(
                {
                    "refused": True,
                    "reason": "main_branch_required_use_trial_for_diagnostics",
                    "preconditions": before,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2

    run_root = ROOT / "tmp/integrated-validation" / before["head"]
    logs = run_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    available = gate_specs(Path(sys.executable).resolve(), run_root)
    selected_names = (
        [name.strip() for name in args.only.split(",") if name.strip()]
        if args.only
        else [gate.name for gate in available]
    )
    unknown = sorted(set(selected_names) - {gate.name for gate in available})
    if unknown:
        print(f"unknown integrated validation gates: {', '.join(unknown)}", file=sys.stderr)
        return 2
    selected = [gate for gate in available if gate.name in set(selected_names)]
    complete_gate_set = len(selected) == len(available)
    environment = _gate_environment()
    started_at = _utc_now()
    results: list[dict[str, Any]] = []
    for gate in selected:
        print(f"RUN {gate.name}", flush=True)
        result = run_gate(gate, logs, environment)
        results.append(result)
        print(
            f"DONE {gate.name} status={result['status']} "
            f"exit={result['exit_code']} duration={result['duration_seconds']}s",
            flush=True,
        )
    after = preconditions()
    green = integrated_green(
        before, after, results, complete_gate_set=complete_gate_set
    )
    gate_summary = summarize_gate_results(results)
    has_skips = bool(gate_summary["skipped_gates"])
    receipt = {
        "schema_version": "gravity.integrated-validation-receipt.v2",
        "definition": DEFINITION,
        "commit_sha": before["head"],
        "branch": before["branch"],
        "started_at": started_at,
        "finished_at": _utc_now(),
        "trial": bool(args.trial or args.only),
        "complete_gate_set": complete_gate_set,
        "preconditions_before": before,
        "preconditions_after": after,
        "gates": results,
        **gate_summary,
        "excluded_post_release_gates": list(POST_RELEASE_GATES),
        "integrated_validation_green": green,
        "overall": (
            "passed_with_skips" if green and has_skips else "passed" if green else "failed"
        ),
    }
    receipt_path = args.receipt or run_root / "receipt.json"
    _write_receipt(receipt_path, receipt)
    print(
        json.dumps(
            {
                "receipt": _display_path(receipt_path),
                "commit_sha": before["head"],
                "gate_count": len(results),
                **gate_summary,
                "integrated_validation_green": green,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(main())
