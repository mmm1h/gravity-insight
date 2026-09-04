"""Refresh or check order-dependent repository validation harnesses."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]


def ordered_steps(python: str, *, check: bool) -> tuple[tuple[str, ...], ...]:
    suffix = ("--check",) if check else ()
    module_graph_action = "check" if check else "refresh"
    domain_boundary_action = (
        ("domain-boundary", "check")
        if check
        else ("domain-boundary", "baseline", "--write")
    )
    return (
        (
            python,
            "-m",
            "tests.agent_migration_characterization",
            module_graph_action,
        ),
        (
            python,
            "scripts/audit_agent_module_references.py",
            *domain_boundary_action,
        ),
        (python, "scripts/generate_repository_map.py", *suffix),
        (
            python,
            "scripts/generate_agent_module_reference_dispositions.py",
            *suffix,
        ),
    )


def run_steps(steps: Sequence[Sequence[str]]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for index, command in enumerate(steps, start=1):
        print(f"RUN {index}/{len(steps)} {' '.join(command[1:])}", flush=True)
        completed = subprocess.run(command, cwd=ROOT, check=False)
        results.append(
            {
                "step": index,
                "command": list(command),
                "exit_code": completed.returncode,
            }
        )
        if completed.returncode != 0:
            break
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    steps = ordered_steps(sys.executable, check=args.check)
    results = run_steps(steps)
    passed = len(results) == len(steps) and all(item["exit_code"] == 0 for item in results)
    print(
        json.dumps(
            {
                "schema_version": "gravity.validation-harness-refresh.v1",
                "order": [
                    "module_graph_baseline",
                    "domain_boundary_baseline",
                    "repository_map",
                    "agent_module_reference_checkpoint",
                ],
                "mode": "check" if args.check else "write",
                "passed": passed,
                "results": results,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
