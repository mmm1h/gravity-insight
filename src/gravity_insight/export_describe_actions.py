"""Caller-facing next_action and workflow text for export describe."""

from __future__ import annotations

from typing import Any


def describe_next_action(operation_id: str, effect: str, currently_callable: bool) -> str:
    if currently_callable and effect == "export_job_create":
        return (
            "Run `gravity export run "
            f"{operation_id} --input <request.json> --columns <column-codes> "
            "--idempotency-key <key> --output <file>` after applying the "
            "documented substitutions."
        )
    if currently_callable and operation_id.endswith(".evaluate"):
        return (
            "Run `gravity export evaluate "
            f"{operation_id} --input <request.json>` to estimate rows before create."
        )
    if currently_callable and operation_id.endswith("task_type.list"):
        return "Run `gravity export task-types` to list verified export task types."
    if currently_callable and effect in {"export_status", "export_cancel"}:
        return (
            "Use `gravity export status <job-id>`, `gravity export wait <job-id>`, "
            "`gravity export download <job-id>`, `gravity export cancel <job-id>`, "
            "or `gravity export list` with a job_id from a create operation; this "
            "route is not `gravity run`."
        )
    return (
        "Run `gravity export list-capabilities` "
        "and select an operation with currently_callable=true."
    )


def describe_workflow(operation_id: str, effect: str) -> dict[str, Any]:
    if operation_id.endswith(".evaluate"):
        command = f"gravity export evaluate {operation_id} --input <request.json>"
        return {
            "default_command": command,
            "default_mode": "estimate_rows",
            "order": ["evaluate"],
            "commands": [command],
            "note": (
                "This estimates rows for the same body as the matching create "
                "route. It is not a job creator and is not reachable via "
                "`gravity run`."
            ),
        }
    if operation_id.endswith("task_type.list"):
        return {
            "default_command": "gravity export task-types",
            "default_mode": "list_task_types",
            "order": ["task-types"],
            "commands": ["gravity export task-types"],
            "note": "This lists verified export task types. It is not a job creator.",
        }
    if effect != "export_job_create":
        return {
            "commands": [],
            "note": "This route is a supporting export effect, not a job creator.",
        }
    return {
        "default_command": (
            "gravity export run "
            f"{operation_id} --input <request.json> --columns <column-codes> "
            "--idempotency-key <key> --output <file> --timeout 300"
        ),
        "default_mode": "create_poll_download",
        "order": ["start", "wait", "download"],
        "commands": [
            (
                "gravity export start "
                f"{operation_id} --input <request.json> --columns <column-codes> "
                "--idempotency-key <key>"
            ),
            (
                "gravity export wait <job-id> "
                f"--operation-id {operation_id} --interval 2 --timeout 300"
            ),
            (
                "gravity export download <job-id> "
                f"--operation-id {operation_id} --output <file> --timeout 300"
            ),
        ],
        "recovery": (
            "The staged commands are recovery controls. If creation outcome is "
            "uncertain, run `gravity "
            "export list --page 1 --page-size 100` before creating another job. "
            "A wait timeout does not cancel the job."
        ),
        "staged_commands_are_recovery": True,
        "create_auto_retry": False,
        "timeout_auto_cancel": False,
    }
