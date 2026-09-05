"""Explain and run the governed validation selected for the current Git change."""

from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import subprocess
import sys
import time
from typing import Sequence

if __package__:
    from scripts.check_test_duration_budget import (
        FULL_GATE_NODEIDS,
        LOCAL_FOCUSED_WALL_LIMIT_SECONDS,
    )
    from scripts.repository_map import RepositoryMapError, build_task_context
else:
    from check_test_duration_budget import (
        FULL_GATE_NODEIDS,
        LOCAL_FOCUSED_WALL_LIMIT_SECONDS,
    )
    from repository_map import RepositoryMapError, build_task_context


ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=check,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def changed_files(base_ref: str) -> list[str]:
    """Return committed, staged, unstaged, and untracked paths since base."""

    try:
        merge_base = _git("merge-base", "HEAD", base_ref).stdout.strip()
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip()
        raise RepositoryMapError(
            f"cannot resolve base ref {base_ref!r}: {detail or 'git merge-base failed'}"
        ) from exc
    tracked = _git(
        "diff",
        "--name-only",
        "--no-renames",
        "--diff-filter=ACDMRTUXB",
        merge_base,
        "--",
    ).stdout.splitlines()
    untracked = _git("ls-files", "--others", "--exclude-standard").stdout.splitlines()
    return sorted({path.replace("\\", "/") for path in [*tracked, *untracked] if path})


def command_argv(command: str) -> list[str]:
    """Decode the Task Context Pack's stable PowerShell-shaped command."""

    if command.startswith('& "'):
        executable, separator, remainder = command[3:].partition('" ')
        if not separator or not executable:
            raise RepositoryMapError(f"cannot decode selected command: {command}")
        return [executable, *shlex.split(remainder, posix=True)]
    return shlex.split(command, posix=True)


def _print_plan(paths: Sequence[str], pack: dict) -> None:
    impact = pack["impact_scope"]
    risk = pack["risk_assessment"]
    print(f"Changed files ({len(paths)}) from Git:")
    for path in paths:
        print(f"  - {path}")
    print(
        "Impact selection: "
        f"strategy={impact['selection_strategy']} depth={impact['closure_depth']} "
        f"fanout_limit={impact['reverse_fanout_limit']} "
        f"test_file_limit={impact['test_file_limit']}"
    )
    print(f"  seed modules ({len(impact['seed_modules'])}): {impact['seed_modules']}")
    print(
        "  bounded dependents: "
        f"{impact['bounded_dependents']['count']} "
        f"sha256={impact['bounded_dependents']['sha256']}"
    )
    if impact["fanout_boundaries"]:
        print(f"  fanout boundaries: {impact['fanout_boundaries']}")
    print(f"  impacted test files ({len(impact['impacted_test_files'])}):")
    for path in impact["impacted_test_files"]:
        print(f"    - {path}")
    print(
        f"Focused tier excludes {len(FULL_GATE_NODEIDS)} full_gate items; "
        "raw pytest, unittest Full Gate, and CI include them."
    )
    if impact["overflow_reason"]:
        print(f"  Focused overflow: {impact['overflow_reason']}; promoted to Full")
    print(
        f"Risk: {risk['level']} / {risk['review_mode']} / "
        f"{risk['validation_profile']}"
    )
    for match in risk["matched_rules"]:
        print(f"  - {match['level']}: {match['subject']} ({match['rule']})")
    print(f"Selected commands ({len(risk['selected_commands'])}):")
    for index, command in enumerate(risk["selected_commands"], 1):
        print(f"  [{index}] {command}")


def run_selected(pack: dict) -> int:
    selected = pack["risk_assessment"]["selected_commands"]
    focused = set(pack["focused_gate"])
    focused_elapsed = 0.0
    for index, command in enumerate(selected, 1):
        argv = command_argv(command)
        print(f"RUN [{index}/{len(selected)}]: {command}", flush=True)
        started = time.perf_counter()
        completed = subprocess.run(argv, cwd=ROOT, check=False)
        elapsed = time.perf_counter() - started
        print(f"DONE [{index}/{len(selected)}]: exit={completed.returncode} wall={elapsed:.3f}s")
        if command in focused:
            focused_elapsed += elapsed
        if completed.returncode != 0:
            return completed.returncode
        if (
            command in focused
            and focused_elapsed > LOCAL_FOCUSED_WALL_LIMIT_SECONDS
        ):
            print(
                "FAIL local-focused-wall-budget: "
                f"observed={focused_elapsed:.3f}s "
                f"limit={LOCAL_FOCUSED_WALL_LIMIT_SECONDS:.3f}s",
                file=sys.stderr,
            )
            return 1
    if focused_elapsed:
        print(
            "PASS local-focused-wall-budget: "
            f"observed={focused_elapsed:.3f}s "
            f"limit={LOCAL_FOCUSED_WALL_LIMIT_SECONDS:.3f}s"
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-ref",
        default="main",
        help="local Git ref used to find the branch merge-base (default: main)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the explainable selection without executing it",
    )
    args = parser.parse_args(argv)
    try:
        paths = changed_files(args.base_ref)
        if not paths:
            raise RepositoryMapError(
                f"no changed files found between {args.base_ref!r} and the working tree"
            )
        pack = build_task_context("changed_files", paths, root=ROOT)
        _print_plan(paths, pack)
        return 0 if args.dry_run else run_selected(pack)
    except RepositoryMapError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
