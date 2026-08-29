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
    "Every included gate exits 0 on one clean dev commit using this worktree's "
    "independent .venv, and one JSON receipt binds the result to that exact HEAD."
)
POST_RELEASE_GATES = (
    {
        "name": "release_provenance_live_pypi",
        "classification": "post_release",
        "included": False,
        "reason": (
            "PyPI provenance exists only after publication and cannot gate a "
            "pre-main merge; integrated validation runs the offline fixture instead."
        ),
    },
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
            (py, "scripts/run_unittest_shards.py", "--expected-total", "2094"),
            1800,
        ),
        GateSpec(
            "pytest_collector",
            (py, "-m", "pytest", "-q", "-n", "auto", "--dist", "load"),
            1800,
        ),
        GateSpec("compiler_check", (py, "-m", "gravity_sdk.compiler", "check")),
        GateSpec("quality_check", (py, "-m", "gravity_sdk.quality", "check")),
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
        GateSpec("cli_help", (py, "-m", "gravity_sdk", "--help")),
        GateSpec(
            "cli_sql_offline_smoke",
            (
                py,
                "-m",
                "gravity_sdk",
                "--workspace",
                "examples/workspace",
                "sql",
                "--dry-run",
            ),
        ),
        GateSpec(
            "cli_census_offline_smoke",
            (py, "-m", "gravity_sdk", "census", "--smoke"),
        ),
        GateSpec(
            "cli_insight_offline_smoke",
            (py, "-m", "gravity_sdk", "insight", "--dry-run"),
        ),
        GateSpec("git_diff_check", ("git", "diff", "--check")),
        GateSpec(
            "r00_requirement_graph",
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
            "generator_ct01",
            (py, "scripts/generate_thinkingai_inventory.py", "--check"),
        ),
        GateSpec(
            "generator_ct02",
            (py, "scripts/generate_thinkingai_representatives.py", "--check"),
        ),
        GateSpec(
            "generator_ct03",
            (py, "scripts/generate_thinkingai_full_specifications.py", "--check"),
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
            "r17_live_checkpoint",
            (py, "scripts/generate_agent_module_reference_dispositions.py", "--check"),
            600,
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
        "branch_is_dev": branch == "dev",
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
    environment["GRAVITY_SDK_AUTO_UPGRADE"] = "0"
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
                "ready",
                "all_index_requirements_fixed_dev",
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
    return summary


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
    return {
        "name": gate.name,
        "command": list(gate.command),
        "started_at": started_at,
        "finished_at": _utc_now(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "timeout_seconds": gate.timeout_seconds,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "passed": exit_code == 0,
        "log_path": log.relative_to(ROOT).as_posix(),
        "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
        "summary": _summary(output),
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
        and before.get("branch_is_dev") is True
        and before.get("clean") is True
        and before.get("independent_venv") is True
        and after.get("clean") is True
        and after.get("head") == before.get("head")
        and all(gate.get("exit_code") == 0 for gate in gates)
    )


def _write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run and receipt exact-HEAD integrated validation."
    )
    parser.add_argument(
        "--trial",
        action="store_true",
        help="Run on a non-dev branch, but never report integrated green.",
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
    if not before["branch_is_dev"] and not args.trial:
        print(
            json.dumps(
                {
                    "refused": True,
                    "reason": "dev_branch_required_use_trial_for_diagnostics",
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
            f"DONE {gate.name} exit={result['exit_code']} "
            f"duration={result['duration_seconds']}s",
            flush=True,
        )
    after = preconditions()
    green = integrated_green(
        before, after, results, complete_gate_set=complete_gate_set
    )
    receipt = {
        "schema_version": "gravity.integrated-validation-receipt.v1",
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
        "excluded_post_release_gates": list(POST_RELEASE_GATES),
        "integrated_validation_green": green,
        "overall": "passed" if green else "failed",
    }
    receipt_path = args.receipt or run_root / "receipt.json"
    _write_receipt(receipt_path, receipt)
    print(
        json.dumps(
            {
                "receipt": receipt_path.relative_to(ROOT).as_posix(),
                "commit_sha": before["head"],
                "gate_count": len(results),
                "failed_gates": [
                    result["name"] for result in results if not result["passed"]
                ],
                "integrated_validation_green": green,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(main())
