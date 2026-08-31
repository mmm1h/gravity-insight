"""Shared value-free helpers for repository evidence collectors."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.as_posix()} must contain a JSON object")
    return value


def relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def git_state(root: Path) -> dict[str, Any]:
    def run(*args: str) -> str:
        completed = subprocess.run(
            ("git", *args),
            cwd=root,
            check=True,
            capture_output=True,
        )
        return completed.stdout.decode("utf-8").strip()

    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(run("status", "--porcelain")),
    }


def metric(
    *,
    source: str,
    claim: str,
    measured: bool,
    passed: int | None = None,
    total: int | None = None,
    observed: Any = None,
    proxy_metric: bool = False,
    limitation: str | None = None,
    missing: Sequence[str] = (),
) -> dict[str, Any]:
    if measured:
        if type(passed) is not int or type(total) is not int or total <= 0:
            raise ValueError("measured score metrics require integer passed/total")
        if passed < 0 or passed > total:
            raise ValueError("score metric passed count is outside its denominator")
    else:
        passed = None
        total = None
    return {
        "source": source,
        "claim": claim,
        "measured": measured,
        "passed": passed,
        "total": total,
        "observed": observed,
        "proxy_metric": proxy_metric,
        "limitation": limitation,
        "missing": list(missing),
    }


def dimension(
    *,
    dimension_id: str,
    name: str,
    maximum: int,
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    required = [item for item in evidence if item.get("required", True)]
    measured, passed, total = _dimension_counts(required)
    score = round(maximum * passed / total, 2) if measured else None
    missing = _dimension_missing(required)
    return {
        "id": dimension_id,
        "name": name,
        "score": score,
        "max": maximum,
        "measured": measured,
        "evidence": [dict(item) for item in evidence],
        "missing": missing,
        "calculation": (
            {"passed": passed, "total": total, "formula": "max * passed / total"}
            if measured
            else None
        ),
    }


def _dimension_counts(
    required: Sequence[Mapping[str, Any]],
) -> tuple[bool, int | None, int | None]:
    if not required or any(item.get("measured") is not True for item in required):
        return False, None, None
    passed = sum(int(item["passed"]) for item in required)
    total = sum(int(item["total"]) for item in required)
    return (True, passed, total) if total > 0 else (False, None, None)


def _dimension_missing(required: Sequence[Mapping[str, Any]]) -> list[str]:
    return sorted(
        {
            str(value)
            for item in required
            if item.get("measured") is not True
            for value in item.get("missing", ())
        }
    )


__all__ = ["dimension", "git_state", "load_object", "metric", "relative"]
