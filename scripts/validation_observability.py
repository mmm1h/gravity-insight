"""Measure risk-proportional validation cost and development experience."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

try:
    from .repository_map import ROOT, build_task_context, estimate_tokens
except ImportError:
    from repository_map import ROOT, build_task_context, estimate_tokens  # type: ignore[no-redef]
from gravity_insight.validation_observability import (
    ValidationObservationError,
    append_baseline,
    build_observation,
    read_baselines,
    trend_summary,
)


COMMAND_NAMES = {
    "scripts/generate_repository_map.py --check": "repository_map_check",
    "-m unittest discover -s tests": "unittest_collector",
    "-m pytest -q": "pytest_collector",
    "-m gravity_insight.compiler check": "compiler_check",
    "-m gravity_insight.quality check": "quality_check",
    "-m gravity_insight --help": "cli_help",
    "git diff --check": "git_diff_check",
}
ABLATION_CANDIDATES = {"unittest_collector"}


def _command_name(command: str, gate: str, index: int) -> str:
    if gate == "focused" and " -m pytest -q " in command:
        return "focused_tests"
    for marker, name in COMMAND_NAMES.items():
        if marker in command:
            return name
    return f"{gate}_command_{index + 1}"


def _command_argv(command: str) -> list[str]:
    if command.startswith('& "'):
        executable, separator, remainder = command[3:].partition('"')
        if not separator:
            raise ValidationObservationError(f"cannot parse command: {command}")
        return [executable, *shlex.split(remainder.strip(), posix=True)]
    return shlex.split(command, posix=True)


def run_gate(
    gate: str,
    commands: Sequence[str],
    *,
    log_dir: Path,
    ablate: Sequence[str] = (),
) -> dict[str, Any]:
    unknown = set(ablate) - ABLATION_CANDIDATES
    if unknown:
        raise ValidationObservationError(
            "unknown ablation candidate(s): " + ", ".join(sorted(unknown))
        )
    log_dir.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    ablated: list[str] = []
    started = time.perf_counter()
    for index, command in enumerate(commands):
        name = _command_name(command, gate, index)
        if name in ablate:
            ablated.append(name)
            print(f"ABLATE {gate}:{name}", flush=True)
            continue
        print(f"RUN {gate}:{name}", flush=True)
        command_started = time.perf_counter()
        completed = subprocess.run(
            _command_argv(command),
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        duration = round(time.perf_counter() - command_started, 3)
        payload = completed.stdout or ""
        log_path = log_dir / f"{gate}-{index + 1:02d}-{name}.log"
        log_path.write_text(payload, encoding="utf-8", newline="\n")
        try:
            relative_log = log_path.resolve().relative_to(ROOT.resolve()).as_posix()
        except ValueError:
            relative_log = log_path.resolve().as_posix()
        result = {
            "name": name,
            "command": command,
            "exit_code": completed.returncode,
            "duration_seconds": duration,
            "log": relative_log,
            "log_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        }
        results.append(result)
        print(
            f"DONE {gate}:{name} exit={completed.returncode} duration={duration}s",
            flush=True,
        )
        if completed.returncode != 0:
            break
    return {
        "gate": gate,
        "status": "passed" if results and all(item["exit_code"] == 0 for item in results) else "failed",
        "total_seconds": round(time.perf_counter() - started, 3),
        "commands": results,
        "ablated_commands": ablated,
    }


def _git_revision() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def _read_object(path: Path | None) -> Mapping[str, Any] | None:
    if path is None:
        return None
    parsed = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, Mapping):
        raise ValidationObservationError(f"expected JSON object: {path}")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files", nargs="+")
    parser.add_argument("--gate", action="append", choices=("focused", "full"), default=[])
    parser.add_argument("--ablate", action="append", default=[])
    parser.add_argument("--trace", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--revision")
    parser.add_argument("--trend-only", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.trend_only is not None:
            archive = read_baselines(args.trend_only)
            print(json.dumps(trend_summary(archive["observations"]), ensure_ascii=False, sort_keys=True))
            return 0
        if not args.changed_files:
            parser.error("--changed-files is required unless --trend-only is used")
        context = build_task_context("changed_files", args.changed_files)
        receipts: dict[str, dict[str, Any]] = {}
        log_dir = ROOT / "tmp/validation-observability/logs"
        for gate in args.gate:
            commands = context[f"{gate}_gate"]
            receipts[gate] = run_gate(
                gate,
                commands,
                log_dir=log_dir,
                ablate=args.ablate if gate == "full" else (),
            )
        observation = build_observation(
            context,
            root=ROOT,
            token_estimator=estimate_tokens,
            gate_receipts=receipts,
            trace=_read_object(args.trace),
            revision=args.revision or _git_revision(),
        )
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(
                json.dumps(observation, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
                + b"\n"
            )
        archive = append_baseline(args.archive, observation) if args.archive else None
    except (
        OSError,
        subprocess.SubprocessError,
        ValidationObservationError,
        ValueError,
    ) as exc:
        print(f"validation observation failed: {exc}", file=sys.stderr)
        return 2
    summary = {
        "observation": str(args.output) if args.output else None,
        "receipt_sha256": observation["receipt_sha256"],
        "risk_level": observation["risk_level"],
        "metrics": observation["metrics"],
        "gate_status": {name: receipt["status"] for name, receipt in receipts.items()},
        "archive_records": len(archive["observations"]) if archive else None,
        "trend": trend_summary(archive["observations"]) if archive else None,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0 if all(item["status"] == "passed" for item in receipts.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
