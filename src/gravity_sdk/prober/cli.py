"""Command-line surface for the Gravity Insight contract probe pipeline."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from gravity_sdk import runtime

from .model import (
    create_bulk_drafts,
    create_drafts,
    create_write_registry,
    promote_drafts,
    reevaluate_drafts,
    status_report,
)
from .online import run_online_probes
from .verdict_probe import run_verdict_probes
from .batch import run_batch_probes
from .parameters import assemble_draft_parameters
from .reprobe import run_parameter_reprobes
from .parents import resolve_parent_blockers
from .transport import RecordingSession, RequestDiscipline, build_runtime, sdk_parts


class ProberArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise ValueError(message)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def _interval(value: str) -> int:
    parsed = int(value)
    if parsed < 300:
        raise argparse.ArgumentTypeError("probe interval must be at least 300ms")
    return parsed


def _request_limit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 200:
        raise argparse.ArgumentTypeError("request limit must be between 1 and 200")
    return parsed


def _batch_request_limit(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= 900:
        raise argparse.ArgumentTypeError("batch request limit must be between 1 and 900")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = ProberArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    draft = commands.add_parser("draft", help="Generate non-executable drafts from coverage.json.")
    draft.add_argument("--path", action="append", default=[])
    draft.add_argument("--family", action="append", default=[])
    draft.add_argument("--business-module", action="append", default=[])
    draft.add_argument("--cost", action="append", default=[])
    draft.add_argument("--method-certainty", default="high")
    draft.add_argument("--limit", type=_positive_int, default=12)
    draft.add_argument("--overwrite", action="store_true")
    draft.add_argument(
        "--all-high-certainty",
        action="store_true",
        help="Generate every high-certainty uncovered read and write bulk audit reports.",
    )
    draft.add_argument(
        "--method-evidence", type=Path, default=None,
        help="Value-free OPTIONS evidence used to resolve UNKNOWN census methods.",
    )

    reserve = commands.add_parser(
        "reserve-writes",
        help="Generate static blocked-write reservations and route classifications.",
    )
    reserve.add_argument("--overwrite", action="store_true")

    probe = commands.add_parser("probe", help="Run controlled online probes and persist value-free evidence.")
    probe.add_argument("operation_id", nargs="+")
    probe.add_argument("--stable", action="store_true", help="Probe existing stable operations for upstream drift.")
    probe.add_argument("--interval-ms", type=_interval, default=310)
    probe.add_argument("--request-limit", type=_request_limit, default=200)
    probe.add_argument(
        "--evidence-root", type=Path, default=None,
        help="Override the immutable evidence directory for a scoped discovery run.",
    )

    verdict_probe = commands.add_parser(
        "verdict-probe",
        help="Collect shape-only evidence for open privacy verdicts.",
    )
    verdict_probe.add_argument("operation_id", nargs="+")
    verdict_probe.add_argument("--interval-ms", type=_interval, default=310)
    verdict_probe.add_argument("--request-limit", type=_request_limit, default=10)
    verdict_probe.add_argument("--evidence-root", type=Path, default=None)

    batch = commands.add_parser(
        "probe-batch", help="Probe all drafts by data-availability tier."
    )
    batch.add_argument("--interval-ms", type=_interval, default=310)
    batch.add_argument("--request-limit", type=_batch_request_limit, default=900)
    batch.add_argument("--no-promote", action="store_true")

    commands.add_parser(
        "assemble-params",
        help="Merge frontend-observed route parameter contracts into all matching drafts.",
    )

    reprobe = commands.add_parser(
        "reprobe-params",
        help="Re-probe parameter-blocked drafts with bounded error-learning retries.",
    )
    reprobe.add_argument("--interval-ms", type=_interval, default=310)
    reprobe.add_argument("--request-limit", type=_batch_request_limit, default=850)

    resolve_parents = commands.add_parser(
        "resolve-parents",
        help="Resolve parent-resource blockers and persist value-free evidence.",
    )
    resolve_parents.add_argument("operation_id", nargs="*")
    resolve_parents.add_argument("--interval-ms", type=_interval, default=310)
    resolve_parents.add_argument(
        "--request-limit", type=_batch_request_limit, default=200
    )
    resolve_parents.add_argument("--evidence-root", type=Path, default=None)

    promote = commands.add_parser("promote", help="Promote gate-passing drafts and rebuild manifests.")
    promote.add_argument("operation_id", nargs="+")
    promote.add_argument("--no-compile", action="store_true")

    commands.add_parser(
        "reevaluate",
        help="Re-evaluate legacy privacy-short-circuit evidence offline and promote eligible drafts.",
    )

    status = commands.add_parser("status", help="Show draft gates and aggregate probe request statistics.")
    status.add_argument("operation_id", nargs="*")
    return parser


def _ensure_auth() -> dict[str, Any]:
    status = runtime.credential_status()
    if status.get("auth_state") == "valid_token":
        return status
    if status.get("can_exchange_credentials"):
        # A long-lived parent process can inject an expired token that masks a
        # newer token in the local env file. Reload the file before another
        # guarded account/password exchange.
        for name in (
            "GRAVITY_AUTH_TOKEN",
            "GRAVITY_AUTH_TOKEN_EXPIRES_AT_ASIA_SHANGHAI",
            "GRAVITY_AUTH_UPDATED_AT",
        ):
            os.environ.pop(name, None)
        status = runtime.credential_status()
        if status.get("auth_state") == "valid_token":
            return status
        runtime.refresh_credentials()
        status = runtime.credential_status()
    if status.get("auth_state") != "valid_token":
        sdk = runtime._sdk_module()
        raise sdk.CredentialError(
            "Gravity credentials are unavailable for the requested online probe"
        )
    return status


def run(args: argparse.Namespace) -> Mapping[str, Any]:
    if args.command == "draft":
        if args.all_high_certainty:
            if any((args.path, args.family, args.business_module, args.cost)):
                raise ValueError("--all-high-certainty cannot be combined with route filters")
            summary = create_bulk_drafts(
                method_certainty=args.method_certainty or "high",
                limit=args.limit,
            )
            return {
                "schema_version": "gravity-insight.prober-bulk-draft.v1",
                "ok": True,
                "status": "success",
                **summary,
            }
        created = create_drafts(
            paths=args.path,
            families=args.family,
            business_modules=args.business_module,
            costs=args.cost,
            method_certainty=args.method_certainty or None,
            limit=args.limit,
            overwrite=args.overwrite,
            method_evidence_path=args.method_evidence,
        )
        return {
            "schema_version": "gravity-insight.prober-draft.v1",
            "ok": True,
            "status": "success",
            "count": len(created),
            "drafts": created,
        }
    if args.command == "reserve-writes":
        summary = create_write_registry(overwrite=args.overwrite)
        return {
            "schema_version": "gravity-insight.prober-write-reservation.v1",
            "ok": True,
            "status": "success",
            "summary": summary,
        }
    if args.command == "probe":
        auth = _ensure_auth()
        kwargs: dict[str, Any] = {}
        if args.evidence_root is not None:
            kwargs["evidence_root"] = args.evidence_root.resolve()
        result = run_online_probes(
            args.operation_id,
            stable=args.stable,
            interval_seconds=args.interval_ms / 1000.0,
            request_limit=args.request_limit,
            **kwargs,
        )
        result["auth"] = {
            "auth_state": auth.get("auth_state"),
            "can_exchange_credentials": bool(auth.get("can_exchange_credentials")),
        }
        return result
    if args.command == "verdict-probe":
        auth = _ensure_auth()
        kwargs: dict[str, Any] = {}
        if args.evidence_root is not None:
            kwargs["evidence_root"] = args.evidence_root.resolve()
        result = run_verdict_probes(
            args.operation_id,
            interval_seconds=args.interval_ms / 1000.0,
            request_limit=args.request_limit,
            **kwargs,
        )
        result["auth"] = {
            "auth_state": auth.get("auth_state"),
            "can_exchange_credentials": bool(auth.get("can_exchange_credentials")),
        }
        return result
    if args.command == "probe-batch":
        auth = _ensure_auth()
        result = run_batch_probes(
            interval_seconds=args.interval_ms / 1000.0,
            request_limit=args.request_limit,
            promote=not args.no_promote,
        )
        result["auth"] = {
            "auth_state": auth.get("auth_state"),
            "can_exchange_credentials": bool(auth.get("can_exchange_credentials")),
        }
        return result
    if args.command == "assemble-params":
        return assemble_draft_parameters()
    if args.command == "reprobe-params":
        auth = _ensure_auth()
        result = run_parameter_reprobes(
            interval_seconds=args.interval_ms / 1000.0,
            request_limit=args.request_limit,
        )
        result["auth"] = {
            "auth_state": auth.get("auth_state"),
            "can_exchange_credentials": bool(auth.get("can_exchange_credentials")),
        }
        return result
    if args.command == "resolve-parents":
        auth = _ensure_auth()
        import requests

        recording = RecordingSession(
            requests.Session(),
            RequestDiscipline(
                interval_seconds=args.interval_ms / 1000.0,
                request_limit=args.request_limit,
            ),
        )
        runtime_instance = build_runtime(recording)
        stable_client = sdk_parts()["GravityInsightClient"].from_env(
            runtime=runtime_instance, timeout=120.0, attempts=1
        )
        kwargs: dict[str, Any] = {}
        if args.evidence_root is not None:
            kwargs["evidence_root"] = args.evidence_root.resolve()
        result = resolve_parent_blockers(
            stable_client=stable_client,
            recording=recording,
            operation_ids=args.operation_id,
            **kwargs,
        )
        result["auth"] = {
            "auth_state": auth.get("auth_state"),
            "can_exchange_credentials": bool(auth.get("can_exchange_credentials")),
        }
        return result
    if args.command == "promote":
        promoted = promote_drafts(
            args.operation_id, compile_products=not args.no_compile
        )
        return {
            "schema_version": "gravity-insight.prober-promote.v1",
            "ok": True,
            "status": "success",
            "count": len(promoted),
            "operations": promoted,
        }
    if args.command == "reevaluate":
        return reevaluate_drafts()
    if args.command == "status":
        return status_report(args.operation_id)
    raise ValueError(f"unsupported prober command: {args.command}")


def _write_json(value: Any, *, stream: Any = None) -> None:
    selected = stream or sys.stdout
    selected.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _error_helpers() -> tuple[Any, Any]:
    sdk = runtime._sdk_module()
    errors = importlib.import_module(sdk.__name__ + ".errors")
    return errors.error_envelope, errors.exit_code_for_error


def main(argv: Sequence[str] | None = None) -> int:
    args: argparse.Namespace | None = None
    try:
        args = build_parser().parse_args(argv)
        result = run(args)
        _write_json(result)
        return 0
    except (OSError, RuntimeError, ValueError, TypeError) as exc:
        error_envelope, exit_code_for_error = _error_helpers()
        operation_id = None
        if args is not None and hasattr(args, "operation_id"):
            values = getattr(args, "operation_id")
            if isinstance(values, list) and len(values) == 1:
                operation_id = str(values[0])
        _write_json(error_envelope(exc, operation_id=operation_id), stream=sys.stderr)
        return int(exit_code_for_error(exc))


__all__ = ["build_parser", "main", "run"]
