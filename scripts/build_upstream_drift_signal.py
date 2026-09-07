"""Build a value-free, offline signal from reviewed upstream drift evidence."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

from gravity_insight.capability_contract import _operations


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "gravity.upstream-drift-signal.v1"
ISSUE_MARKER = "gravity-upstream-drift-signal:v1"
_PROBE_COMMAND = re.compile(
    r"^python -m gravity_insight\.prober probe ([a-z][a-z0-9_.-]+)$"
)
_ACTIONABLE_STATUSES = frozenset({None, "ready", "required"})


class SignalInputError(ValueError):
    """Raised when reviewed evidence cannot produce a trustworthy signal."""


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SignalInputError(f"{label} is not readable JSON: {path.name}") from exc
    if not isinstance(value, Mapping):
        raise SignalInputError(f"{label} must be a JSON object: {path.name}")
    return dict(value)


def _string_list(value: object, label: str) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise SignalInputError(f"{label} must be an array")
    if any(not isinstance(item, str) for item in value):
        raise SignalInputError(f"{label} must contain strings")
    result = list(value)
    if any(not item for item in result) or len(result) != len(set(result)):
        raise SignalInputError(f"{label} must contain unique non-empty strings")
    return result


def _pointer_segments(value: object) -> tuple[str, ...]:
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 4_096:
        raise SignalInputError("additive response path is not a bounded JSON Pointer")
    segments: list[str] = []
    for segment in value[1:].split("/"):
        if re.search(r"~(?![01])", segment):
            raise SignalInputError("additive response path has invalid JSON Pointer escaping")
        segments.append(segment.replace("~1", "/").replace("~0", "~"))
    return tuple(segments)


def _top_level_data_key(value: object) -> str:
    segments = _pointer_segments(value)
    if len(segments) != 2 or segments[0] != "data" or not segments[1]:
        raise SignalInputError(
            "additive_unregistered_paths currently supports only /data/<key>; "
            "a wider projection reconciliation must be reviewed before accepting nested paths"
        )
    return segments[1]


def _evidence_findings(
    evidence_root: Path,
    operations: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if not evidence_root.is_dir():
        raise SignalInputError("checked-in probe evidence root is missing")
    paths = sorted(evidence_root.glob("*.json"))
    if not paths:
        raise SignalInputError("checked-in probe evidence root contains no JSON evidence")

    unresolved: dict[tuple[str, str], set[str]] = {}
    matched_files = 0
    for path in paths:
        document = _read_object(path, "checked-in probe evidence")
        observation = document.get("response_observation")
        if not isinstance(observation, Mapping) or (
            "additive_unregistered_paths" not in observation
        ):
            continue
        matched_files += 1
        additive_paths = _string_list(
            observation["additive_unregistered_paths"],
            f"{path.name} response_observation.additive_unregistered_paths",
        )
        operation_id = document.get("operation_id")
        if additive_paths and (
            not isinstance(operation_id, str) or operation_id not in operations
        ):
            raise SignalInputError(
                f"{path.name} additive paths do not bind a current operation"
            )
        if not isinstance(operation_id, str):
            continue
        operation = operations.get(operation_id)
        if operation is None:
            continue
        projection = operation.response_projection
        accounted = set(projection.data_keys) | set(
            projection.known_omitted_data_keys
        )
        for pointer in additive_paths:
            key = _top_level_data_key(pointer)
            if key not in accounted:
                unresolved.setdefault((operation_id, pointer), set()).add(
                    path.relative_to(ROOT).as_posix()
                    if path.is_relative_to(ROOT)
                    else path.name
                )

    findings = [
        {
            "kind": "unresolved_response_drift",
            "operation_id": operation_id,
            "path": pointer,
            "evidence_references": sorted(references),
        }
        for (operation_id, pointer), references in sorted(unresolved.items())
    ]
    return findings, {
        "checked_in_evidence_files": len(paths),
        "additive_evidence_files": matched_files,
    }


def _probe_plan_finding(
    path: Path,
    operations: Mapping[str, Any],
) -> dict[str, Any] | None:
    plan = _read_object(path, "targeted probe plan")
    direct = _string_list(
        plan.get("direct_operation_ids", ()), "probe_plan.direct_operation_ids"
    )
    family = _string_list(
        plan.get("family_sample_operation_ids", ()),
        "probe_plan.family_sample_operation_ids",
    )
    operation_ids = [*direct, *family]
    if len(operation_ids) != len(set(operation_ids)):
        raise SignalInputError("probe plan operation IDs overlap")
    commands = _string_list(plan.get("commands", ()), "probe_plan.commands")
    status = plan.get("status")
    if plan.get("business_api_called") is not False:
        raise SignalInputError("probe plan does not prove business_api_called=false")
    if not commands:
        if operation_ids:
            raise SignalInputError("probe plan has operation IDs without commands")
        if (
            status not in _ACTIONABLE_STATUSES | {"withheld"}
            or plan.get("mode") not in {"none", "schedule_only"}
        ):
            raise SignalInputError("empty probe plan has an unknown status")
        return None
    if (
        status not in _ACTIONABLE_STATUSES
        or plan.get("mode") != "schedule_only"
    ):
        raise SignalInputError("actionable probe plan lost its schedule-only safety contract")
    unknown = sorted(set(operation_ids) - set(operations))
    if unknown:
        raise SignalInputError("probe plan references an unknown current operation")
    expected_commands = [
        f"python -m gravity_insight.prober probe {operation_id}"
        for operation_id in operation_ids
    ]
    if commands != expected_commands or any(
        _PROBE_COMMAND.fullmatch(command) is None for command in commands
    ):
        raise SignalInputError("probe plan commands do not match its operation IDs")
    return {
        "kind": "targeted_probe_plan",
        "direct_operation_ids": direct,
        "family_sample_operation_ids": family,
        "commands": commands,
    }


def _fingerprint(findings: Sequence[Mapping[str, Any]]) -> str:
    actionable = []
    for finding in findings:
        selected = {
            key: value
            for key, value in finding.items()
            if key != "evidence_references"
        }
        actionable.append(selected)
    payload = json.dumps(
        actionable, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_signal(
    evidence_root: Path,
    *,
    probe_plan: Path | None = None,
    require_probe_plan: bool = False,
    operations: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current_operations = _operations() if operations is None else operations
    findings, scanned = _evidence_findings(evidence_root, current_operations)
    if require_probe_plan and (probe_plan is None or not probe_plan.is_file()):
        raise SignalInputError("required targeted probe plan is missing")
    if probe_plan is not None and probe_plan.is_file():
        plan_finding = _probe_plan_finding(probe_plan, current_operations)
        if plan_finding is not None:
            findings.append(plan_finding)
    findings.sort(key=lambda item: json.dumps(item, sort_keys=True))
    if findings:
        status = "action_required"
    elif scanned["additive_evidence_files"] > 0:
        status = "clear"
    else:
        status = "inconclusive"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "actionable": bool(findings),
        "fingerprint": _fingerprint(findings),
        "finding_count": len(findings),
        "findings": findings,
        "scanned": {
            **scanned,
            "targeted_probe_plan": probe_plan is not None and probe_plan.is_file(),
        },
        "network_called": False,
    }


def invalid_signal(error: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "invalid",
        "actionable": False,
        "fingerprint": None,
        "finding_count": 0,
        "findings": [],
        "errors": [error],
        "network_called": False,
    }


def render_summary(signal: Mapping[str, Any]) -> str:
    lines = [
        "### Gravity upstream drift signal",
        "",
        f"Status: `{signal['status']}`.",
        "",
    ]
    if signal["status"] == "invalid":
        lines.append(
            "The signal pipeline could not confirm upstream state. This is not a drift conclusion."
        )
        lines.extend(f"- {error}" for error in signal.get("errors", ()))
        return "\n".join(lines) + "\n"
    if signal["status"] == "inconclusive":
        lines.append(
            "Checked-in JSON evidence was readable, but none exposed "
            "`response_observation.additive_unregistered_paths`. No upstream "
            "drift conclusion is available."
        )
        return "\n".join(lines) + "\n"
    if not signal["actionable"]:
        lines.append(
            "No actionable targeted probe or unresolved checked-in response "
            "drift remains."
        )
        return "\n".join(lines) + "\n"
    lines.append(f"Actionable fingerprint: `{signal['fingerprint']}`")
    lines.append("")
    lines.extend(_finding_lines(signal["findings"]))
    lines.extend(("", "No production business API was called while building this signal."))
    return "\n".join(lines) + "\n"


def render_issue_body(signal: Mapping[str, Any], run_url: str) -> str:
    if signal.get("status") != "action_required":
        raise ValueError("an Issue body requires an actionable signal")
    lines = [
        f"<!-- {ISSUE_MARKER} fingerprint={signal['fingerprint']} -->",
        "The scheduled upstream census found reviewed, value-free evidence that "
        "requires maintainer action.",
        "",
        f"Workflow run: {run_url}",
        "",
        "## Actionable evidence",
        "",
        *_finding_lines(signal["findings"]),
        "",
        "Probe commands are a handoff only. They were not executed by GitHub "
        "Actions and require a separately authorized runner.",
        "",
        "This Issue is updated only when the actionable fingerprint changes and "
        "is closed only after a complete successful census clears every finding.",
    ]
    return "\n".join(lines) + "\n"


def _finding_lines(findings: Sequence[Mapping[str, Any]]) -> list[str]:
    lines: list[str] = []
    for finding in findings:
        if finding["kind"] == "unresolved_response_drift":
            references = ", ".join(
                f"`{value}`" for value in finding["evidence_references"]
            )
            lines.append(
                f"- `{finding['operation_id']}` still does not account for "
                f"`{finding['path']}` ({references})."
            )
            continue
        direct = ", ".join(
            f"`{value}`" for value in finding["direct_operation_ids"]
        ) or "none"
        family = ", ".join(
            f"`{value}`" for value in finding["family_sample_operation_ids"]
        ) or "none"
        lines.extend(
            (
                f"- Targeted probe plan: direct operations {direct}; family samples {family}.",
                "",
                "```powershell",
                *finding["commands"],
                "```",
            )
        )
    return lines


def _write(path: Path | None, content: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=ROOT / "evidence" / "probe")
    parser.add_argument("--probe-plan", type=Path)
    parser.add_argument("--require-probe-plan", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path)
    parser.add_argument("--issue-body-output", type=Path)
    parser.add_argument("--run-url", default="")
    args = parser.parse_args(argv)

    try:
        signal = build_signal(
            args.evidence_root.resolve(),
            probe_plan=args.probe_plan.resolve() if args.probe_plan else None,
            require_probe_plan=args.require_probe_plan,
        )
        code = 0
    except SignalInputError as exc:
        signal = invalid_signal(str(exc))
        code = 2

    rendered = json.dumps(signal, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _write(args.output, rendered)
    _write(args.summary_output, render_summary(signal))
    if args.issue_body_output is not None:
        body = (
            render_issue_body(signal, args.run_url)
            if signal["status"] == "action_required"
            else ""
        )
        _write(args.issue_body_output, body)
    sys.stdout.write(rendered)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
