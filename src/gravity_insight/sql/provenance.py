"""Repository provenance for SQL Evidence.

Repository root and state root are distinct inputs. The consumer workspace
directory holds ``gravity.toml`` and is version controlled; the private state
root only holds generated Evidence and is never a checkout. Resolving one from
the other is what made every normal consumer fail the Git step before any
cleanliness, credential, or product check could run.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from gravity_insight.paths import PROJECT_ROOT
from gravity_insight.sql.evidence_validation import EvidenceFormatError
from gravity_insight.sql.failures import (
    SqlFailure,
    classify_sql_failure,
    diagnostic_fields,
)
from gravity_insight.workspace import Workspace, load_workspace


ROOT = PROJECT_ROOT
VERIFICATION_RUN_VERSION = "gravity.sql-verification-run.v1"
VERIFICATION_RESUME_POLICY = "gravity.sql-verification-strict-prefix.v1"
VERIFICATION_CLI_RESULT_VERSION = "gravity.sql-verification-result.v1"


def git_toplevel(candidate: Path) -> Path | None:
    """Return the checkout containing ``candidate``, or None when it has none.

    Asking Git rather than looking for a ``.git`` directory keeps linked
    worktrees working, where ``.git`` is a file.
    """

    probe = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=candidate,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    resolved = probe.stdout.strip()
    if probe.returncode or not resolved:
        return None
    return Path(resolved)


def provenance_root(workspace: Workspace | None = None) -> Path | None:
    """Resolve the Git checkout that Evidence provenance describes.

    Maintainers running from the SDK checkout keep their existing provenance
    through the ``ROOT`` fallback; the state root is never probed.
    """

    selected = load_workspace() if workspace is None else workspace
    for candidate in (selected.root, ROOT):
        if candidate == selected.state_root or not candidate.is_dir():
            continue
        toplevel = git_toplevel(candidate)
        if toplevel is not None:
            return toplevel
    return None


def git_state(workspace: Workspace | None = None) -> tuple[str, bool]:
    """Return the SHA and dirty flag publish records, or fail closed."""

    root = provenance_root(workspace)
    if root is None:
        raise EvidenceFormatError("cannot publish evidence without a Git-backed workspace")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if head.returncode or re.fullmatch(r"[0-9a-f]{40}", head.stdout.strip()) is None:
        raise EvidenceFormatError("cannot publish evidence without a valid repository Git SHA")
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if status.returncode:
        raise EvidenceFormatError("cannot determine repository state for evidence provenance")
    return head.stdout.strip(), bool(status.stdout.strip())


def preflight_git_report(repository_root: Path | None) -> dict[str, Any]:
    """Describe the consumer checkout without turning a missing one into a failure.

    Preflight reports; publish enforces. A workspace outside version control is
    a determinate state that belongs in ``offline_blockers``, not an error that
    looks like the tool itself broke.
    """

    absent = {"git_state": "not_git_backed", "git_sha": None, "current_branch": None, "git_dirty": None}
    if repository_root is None:
        return absent
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repository_root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repository_root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=repository_root, capture_output=True, check=False
    )
    git_sha = head.stdout.strip()
    if head.returncode or re.fullmatch(r"[0-9a-f]{40}", git_sha) is None or branch.returncode or status.returncode:
        return {**absent, "git_state": "unreadable"}
    return {
        "git_state": "resolved",
        "git_sha": git_sha,
        "current_branch": branch.stdout.strip() or "DETACHED",
        "git_dirty": bool(status.stdout.strip()),
    }


def verification_failure(
    error: BaseException,
    *,
    elapsed_seconds: float = 0,
    request_count: int = 0,
    request_count_bound: int = 1,
) -> dict[str, Any]:
    """Project one verification failure through the shared SQL taxonomy."""

    failure = classify_sql_failure(error, request_count=request_count)
    diagnostic = diagnostic_fields(
        failure,
        elapsed_seconds=elapsed_seconds,
        request_count=request_count,
        request_count_bound=request_count_bound,
    )
    return {
        "stage": failure.stage,
        "upstream_category": failure.upstream_category,
        "code": failure.code,
        "message": failure.message,
        "retryable": failure.retryable,
        "reached_sql_engine": failure.reached_sql_engine,
        "next_action": failure.next_action,
        "http_status": failure.http_status,
        "retry_after_ms": failure.retry_after_ms,
        "upstream_error": diagnostic["upstream_error"],
        "execution_evidence": diagnostic["execution_evidence"],
    }


def verification_failure_is_rate_limited(failure: Mapping[str, Any]) -> bool:
    return bool(
        failure.get("code") == "SQL_HTTP_RATE_LIMITED"
        and failure.get("http_status") == 429
        and failure.get("retryable") is True
    )


def verification_failure_run(
    owner: Any,
    day: date,
    names: tuple[str, ...],
    completed: Mapping[str, dict[str, Any]],
    segments: list[dict[str, Any]],
    product: str,
    failure: Mapping[str, Any],
    workspace: Any,
    *,
    rate_limited: bool,
) -> dict[str, Any]:
    retry_after_ms = _verification_retry_after(owner, failure, rate_limited)
    error = _verification_error(day, product, failure, rate_limited, retry_after_ms)
    category = "runtime" if rate_limited else _verification_failure_category(failure)
    result: dict[str, Any] = {
        "schema_version": owner.VERIFICATION_RUN_VERSION,
        "ok": False,
        "status": "rate_limited" if rate_limited else "error",
        "exit_code": owner.sql_error_exit_code(category),
        "readiness_achieved": False,
        "verification_status": "interrupted" if rate_limited else "failed",
        "datasource_id": owner._datasource_id(workspace=workspace),
        "verified_for_date": day.isoformat(),
        "window": owner._window_dict(*owner.day_window(day)),
        "configured_products": list(names),
        "completed_products": dict(completed),
        "pending_products": list(names[len(completed) :]),
        "verification": {
            "mode": "interrupted" if rate_limited else "terminal_failure",
            "segment_count": len(segments),
            "segments": segments,
        },
        "failure": error,
        "resume": verification_resume_contract(owner, day, rate_limited),
    }
    result["checkpoint_sha256"] = verification_checkpoint_digest(result)
    return result


def _verification_retry_after(
    owner: Any, failure: Mapping[str, Any], rate_limited: bool
) -> int | None:
    if not rate_limited:
        return None
    received = failure.get("retry_after_ms")
    selected = received if type(received) is int and received >= 0 else 0
    return min(
        owner.VERIFICATION_MAX_BACKOFF_MS,
        max(owner.VERIFICATION_MIN_BACKOFF_MS, selected),
    )


def _verification_error(
    day: date,
    product: str,
    failure: Mapping[str, Any],
    rate_limited: bool,
    retry_after_ms: int | None,
) -> dict[str, Any]:
    return {
        "product": product,
        "code": "RATE_LIMITED" if rate_limited else failure["code"],
        "sql_code": failure["code"],
        "category": "upstream" if rate_limited else _verification_failure_category(failure),
        "message": failure["message"],
        "stage": failure["stage"],
        "retryable": failure["retryable"],
        "reached_sql_engine": failure["reached_sql_engine"],
        "retry_after_ms": retry_after_ms,
        "upstream_error": dict(failure["upstream_error"]),
        "execution_evidence": dict(failure["execution_evidence"]),
        "next_action": (
            f"Wait the bounded retry_after_ms, then run `gravity sql verify --date "
            f"{day.isoformat()} --resume`; keep concurrency at 1 and do not increase it."
            if rate_limited
            else failure["next_action"]
        ),
    }


def verification_cli_failure_result(
    value: Mapping[str, Any], *, checkpoint_written: bool
) -> dict[str, Any]:
    """Return the public failure receipt without private checkpoint payloads."""

    configured = value["configured_products"]
    completed = value["completed_products"]
    pending = value["pending_products"]
    failure = value["failure"]
    return {
        "schema_version": VERIFICATION_CLI_RESULT_VERSION,
        "ok": False,
        "status": value["status"],
        "exit_code": value["exit_code"],
        "readiness_achieved": False,
        "verification_status": value["verification_status"],
        "verified_for_date": value["verified_for_date"],
        "progress": {
            "configured_product_count": len(configured),
            "completed_product_count": len(completed),
            "pending_product_count": len(pending),
            "failure_product": failure["product"],
        },
        "failure": dict(failure),
        "resume": dict(value["resume"]),
        "checkpoint": {
            "written": checkpoint_written,
            "strict_prefix": value["status"] == "rate_limited",
            "completed_product_count": len(completed),
        },
    }


def run_verification_boundary_error_cli(
    owner: Any, error: BaseException, *, serializer: Any
) -> int:
    """Emit a safe public receipt for failures outside the product loop."""

    if isinstance(error, (OSError, UnicodeError)):
        category = "local_io"
    else:
        classified = classify_sql_failure(error, request_count=0)
        category = (
            "authentication"
            if classified.kind in {"authentication", "credentials"}
            else "input"
        )
    if category == "local_io":
        failure = SqlFailure(
            "local_io", "bind", "local_io", "SQL_VERIFY_LOCAL_IO",
            "SQL verification could not read or write local state", False, "no",
            "Inspect the workspace state path and permissions, then rerun verification.",
        )
    elif category == "input":
        failure = SqlFailure(
            "local_validation", "bind", "local_validation",
            "SQL_VERIFY_INPUT_INVALID",
            "SQL verification input or local contract is invalid", False, "no",
            "Correct the verify date, workspace, or Evidence contract before retrying.",
        )
    else:
        failure = classified
    evidence = diagnostic_fields(
        failure, elapsed_seconds=0, request_count=0, request_count_bound=1
    )
    exit_code = owner.sql_error_exit_code(category)
    result = {
        "schema_version": VERIFICATION_CLI_RESULT_VERSION,
        "ok": False,
        "status": "error",
        "exit_code": exit_code,
        "readiness_achieved": False,
        "verification_status": "failed",
        "verified_for_date": None,
        "progress": {
            "configured_product_count": None,
            "completed_product_count": 0,
            "pending_product_count": None,
            "failure_product": None,
        },
        "failure": {
            "product": None,
            "code": failure.code,
            "sql_code": failure.code,
            "category": category,
            "message": failure.message,
            "stage": failure.stage,
            "retryable": failure.retryable,
            "reached_sql_engine": failure.reached_sql_engine,
            "retry_after_ms": None,
            "upstream_error": evidence["upstream_error"],
            "execution_evidence": evidence["execution_evidence"],
            "next_action": failure.next_action,
        },
        "resume": {
            "supported": False,
            "policy": VERIFICATION_RESUME_POLICY,
            "strict_prefix": True,
            "max_backoff_ms": owner.VERIFICATION_MAX_BACKOFF_MS,
            "command": None,
        },
        "checkpoint": {
            "written": False,
            "strict_prefix": False,
            "completed_product_count": 0,
        },
    }
    print(
        serializer(result, ensure_ascii=False, indent=2, sort_keys=True),
        file=sys.stderr,
    )
    return exit_code


def _verification_failure_category(failure: Mapping[str, Any]) -> str:
    if failure["upstream_category"] in {"authentication", "credentials"}:
        return "authentication"
    if failure["upstream_category"] == "local_validation":
        return "input"
    if failure["stage"] in {"compile", "shape"}:
        return "contract"
    return "runtime"


def verification_resume_contract(owner: Any, day: date, supported: bool) -> dict[str, Any]:
    return {
        "supported": supported,
        "policy": VERIFICATION_RESUME_POLICY,
        "strict_prefix": True,
        "max_backoff_ms": owner.VERIFICATION_MAX_BACKOFF_MS,
        "command": (
            f"gravity sql verify --date {day.isoformat()} --resume" if supported else None
        ),
    }


def verification_checkpoint_path(owner: Any, day: date, workspace: Workspace) -> Path:
    identity = hashlib.sha256(
        f"{owner._datasource_id(workspace=workspace)}\0{day.isoformat()}".encode("utf-8")
    ).hexdigest()[:16]
    return (
        workspace.state_root
        / "evidence"
        / "sql-verification-resume"
        / f"{day.isoformat()}-{identity}.json"
    )


def verification_checkpoint_digest(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "checkpoint_sha256"}
    return hashlib.sha256(
        json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def write_verification_checkpoint(
    owner: Any, value: Mapping[str, Any], day: date, workspace: Workspace
) -> Path:
    owner.validate_resume_checkpoint(owner, value, day, owner.product_names(workspace), workspace)
    path = verification_checkpoint_path(owner, day, workspace)
    owner.write_document_atomic(path, dict(value))
    return path


def read_verification_checkpoint(
    owner: Any, day: date, workspace: Workspace
) -> dict[str, Any]:
    path = verification_checkpoint_path(owner, day, workspace)
    if not path.is_file():
        raise EvidenceFormatError(
            "no rate-limited SQL verification checkpoint exists for the requested date"
        )
    try:
        value = owner.load_document(path)
    except (owner.DocumentError, OSError) as exc:
        raise EvidenceFormatError(
            "the SQL verification checkpoint could not be read"
        ) from exc
    owner.validate_resume_checkpoint(owner, value, day, owner.product_names(workspace), workspace)
    return dict(value)


def clear_verification_checkpoint(owner: Any, day: date, workspace: Workspace) -> None:
    verification_checkpoint_path(owner, day, workspace).unlink(missing_ok=True)


def is_incomplete_verification(value: Any) -> bool:
    return bool(
        isinstance(value, Mapping)
        and value.get("schema_version") == VERIFICATION_RUN_VERSION
        and value.get("readiness_achieved") is False
    )


def run_verification_cli(
    owner: Any,
    client: Any,
    day: date,
    workspace: Workspace,
    *,
    resume: bool,
    publish: bool,
    publisher: Any,
    evidence_path: Path,
    serializer: Any,
) -> int:
    checkpoint = read_verification_checkpoint(owner, day, workspace) if resume else None
    evidence = owner.execute_sql_verification(
        owner, client, day, workspace=workspace, resume=checkpoint
    )
    if is_incomplete_verification(evidence):
        checkpoint_written = False
        if evidence["status"] == "rate_limited":
            write_verification_checkpoint(owner, evidence, day, workspace)
            checkpoint_written = True
            print("CHECKPOINTED rate-limited SQL verification prefix", file=sys.stderr)
        print(serializer(
            verification_cli_failure_result(
                evidence, checkpoint_written=checkpoint_written
            ),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ))
        return int(evidence["exit_code"])
    if publish:
        publisher(evidence, workspace=workspace)
        _clear_obsolete_checkpoint(owner, day, workspace)
        print(f"PUBLISHED {evidence_path}", file=sys.stderr)
    print(serializer(evidence, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _clear_obsolete_checkpoint(owner: Any, day: date, workspace: Workspace) -> None:
    try:
        clear_verification_checkpoint(owner, day, workspace)
    except OSError:
        print(
            "WARNING: published Evidence is durable, but its obsolete SQL "
            "verification checkpoint could not be removed",
            file=sys.stderr,
        )


run_verification_cli.boundary_error = run_verification_boundary_error_cli


__all__ = [
    "ROOT",
    "VERIFICATION_CLI_RESULT_VERSION",
    "VERIFICATION_RESUME_POLICY",
    "VERIFICATION_RUN_VERSION",
    "clear_verification_checkpoint",
    "git_state",
    "git_toplevel",
    "is_incomplete_verification",
    "preflight_git_report",
    "provenance_root",
    "read_verification_checkpoint",
    "run_verification_boundary_error_cli",
    "run_verification_cli",
    "verification_checkpoint_digest",
    "verification_checkpoint_path",
    "verification_failure",
    "verification_failure_is_rate_limited",
    "verification_failure_run",
    "verification_cli_failure_result",
    "verification_resume_contract",
    "write_verification_checkpoint",
]
