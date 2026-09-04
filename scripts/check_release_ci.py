from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "gravity.release-ci-evidence.v1"
WORKFLOW_PATH = ".github/workflows/ci.yml"
_SHA_RE = re.compile(r"[0-9a-f]{40}")


class ReleaseCIError(ValueError):
    """The selected CI run is not valid release evidence."""


def _load(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseCIError(f"cannot read {label} JSON at {path}") from exc
    if not isinstance(value, Mapping):
        raise ReleaseCIError(f"{label} JSON must be an object")
    return value


def check_release_ci(
    run: Mapping[str, Any],
    jobs_document: Mapping[str, Any],
    *,
    expected_run_id: int,
    expected_sha: str,
    expected_event: str,
    expected_branch: str,
) -> dict[str, Any]:
    if _SHA_RE.fullmatch(expected_sha) is None:
        raise ReleaseCIError("expected SHA must be a lowercase 40-character commit SHA")
    expected = {
        "id": expected_run_id,
        "head_sha": expected_sha,
        "event": expected_event,
        "head_branch": expected_branch,
        "conclusion": "success",
        "path": WORKFLOW_PATH,
    }
    mismatched = {
        key: {"expected": value, "actual": run.get(key)}
        for key, value in expected.items()
        if run.get(key) != value
    }
    if mismatched:
        raise ReleaseCIError(f"CI run identity mismatch: {mismatched}")

    jobs = jobs_document.get("jobs")
    if not isinstance(jobs, list):
        raise ReleaseCIError("CI jobs response must contain a jobs array")
    required = [job for job in jobs if isinstance(job, Mapping) and job.get("name") == "ci-required"]
    if len(required) != 1 or required[0].get("conclusion") != "success":
        raise ReleaseCIError(
            "CI run must contain exactly one successful ci-required job; "
            f"observed={[(item.get('id'), item.get('conclusion')) for item in required]}"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "run_id": expected_run_id,
        "run_number": run.get("run_number"),
        "commit_sha": expected_sha,
        "event_name": expected_event,
        "branch": expected_branch,
        "workflow_path": WORKFLOW_PATH,
        "conclusion": "success",
        "required_job": {
            "id": required[0].get("id"),
            "name": "ci-required",
            "conclusion": "success",
        },
    }


def _write(path: Path | None, receipt: Mapping[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate exact-SHA release CI evidence and emit a receipt."
    )
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--jobs", type=Path, required=True)
    parser.add_argument("--run-id", type=int, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--expected-event", required=True)
    parser.add_argument("--expected-branch", required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = check_release_ci(
            _load(args.run, "CI run"),
            _load(args.jobs, "CI jobs"),
            expected_run_id=args.run_id,
            expected_sha=args.expected_sha,
            expected_event=args.expected_event,
            expected_branch=args.expected_branch,
        )
        _write(args.receipt, receipt)
    except (OSError, ReleaseCIError) as exc:
        print(f"FAIL release CI evidence: {exc}", file=sys.stderr)
        return 1
    print(
        "PASS release CI evidence: "
        f"run_id={receipt['run_id']} sha={receipt['commit_sha']} "
        f"event={receipt['event_name']} branch={receipt['branch']} required=ci-required"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
