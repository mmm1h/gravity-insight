from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date

from gravity_sdk.sql import credentials
from gravity_sdk.sql.client import (
    GravityAuthError,
    GravityClient,
    _extract_rows,
    build_sql_client,
)
from gravity_sdk.sql.credentials import CredentialSyncError
from gravity_sdk.sql.export import build_paged_sql
from gravity_sdk.sql.products import (
    EVIDENCE_PATH,
    EvidenceFormatError,
    dry_run_checks,
    evidence_preflight,
    latest_safe_date,
    normalize_window,
    publish_evidence,
    product_names,
    readiness_status,
    resolve_current_evidence,
    run_product,
    verify_all,
)
from gravity_sdk.workspace import WorkspaceError


def _run_credentials(args: argparse.Namespace) -> int:
    try:
        if args.credential_command == "status":
            result = credentials.status()
        elif args.credential_command == "push":
            result = (
                {"status": "uploaded" if credentials.push_if_enabled() else "disabled-or-unchanged"}
                if args.if_enabled
                else credentials.push()
            )
        else:
            result = credentials.pull()
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except CredentialSyncError as exc:
        print(f"ERROR: {exc}")
        return 1


def _missing_products_error(
    configured_products: tuple[str, ...], workspace_error: str | None
) -> int | None:
    if configured_products:
        return None
    detail = workspace_error or (
        "no SQL products are configured; add [products.<name>] to gravity.toml"
    )
    print(f"ERROR: {detail}", file=sys.stderr)
    return 2


def _configured_products() -> tuple[tuple[str, ...], str | None]:
    workspace_error: str | None = None
    try:
        configured_products = product_names()
    except WorkspaceError as exc:
        configured_products = ()
        workspace_error = str(exc)
    if len(configured_products) != len(set(configured_products)):
        raise RuntimeError("workspace SQL product names must be unique")
    if "" in configured_products:
        raise RuntimeError("workspace SQL product names must be non-empty")
    return configured_products, workspace_error


def build_parser(
    configured_products: tuple[str, ...] | None = None,
) -> argparse.ArgumentParser:
    if configured_products is None:
        configured_products, _workspace_error = _configured_products()
    parser = argparse.ArgumentParser(
        description="Governed SQL fallback when stable Insight cannot express equivalent semantics; otherwise prefer Insight."
    )
    parser.set_defaults(network_required=False)
    parser.add_argument("--dry-run", action="store_true", help="Run offline contract checks without calling Gravity.")
    commands = parser.add_subparsers(dest="command")
    credential_parser = commands.add_parser("credentials", help="Sync GM/Gravity credentials via GitHub.")
    credential_commands = credential_parser.add_subparsers(dest="credential_command", required=True)
    credential_commands.add_parser("status")
    push = credential_commands.add_parser("push")
    push.add_argument("--if-enabled", action="store_true")
    credential_commands.add_parser("pull")
    status_parser = commands.add_parser("status", help="Show data-product readiness.")
    status_parser.add_argument("--json", action="store_true", help="Print machine-readable status.")
    preflight_parser = commands.add_parser(
        "evidence-preflight", help="Run offline checks before an authorized Evidence refresh."
    )
    preflight_parser.add_argument("--date", help="Proposed Beijing calendar day (YYYY-MM-DD).")
    preflight_parser.add_argument("--json", action="store_true", help="Print machine-readable preflight.")
    verify_parser = commands.add_parser("verify", help="Verify the latest safe Beijing calendar day.")
    verify_parser.set_defaults(network_required=True)
    verify_parser.add_argument("--date", help="Beijing calendar day (YYYY-MM-DD).")
    verify_parser.add_argument("--publish", action="store_true", help="Atomically update rolling aggregate evidence.")
    query_parser = commands.add_parser("query", help="Run an aggregate product only when Insight cannot express equivalent semantics.")
    query_parser.set_defaults(network_required=True)
    query_parser.add_argument("product", choices=configured_products or None)
    query_parser.add_argument("--start", required=True, help="Inclusive ISO timestamp.")
    query_parser.add_argument("--end", required=True, help="Exclusive ISO timestamp.")
    query_parser.add_argument("--app-id", type=int, action="extend", nargs="+", help="Positive Gravity app id.")
    return parser


def _run_dry_checks() -> int:
    payload = {"data": {"status": "success", "result": {"columns": [{"name": "user_id"}], "rows": [["u1"]]}}}
    rows = _extract_rows(payload)
    paged = build_paged_sql("SELECT user_id FROM source", page_size=10, offset=0)
    if rows != [{"user_id": "u1"}] or "LIMIT 10 OFFSET 0" not in paged:
        print("FAIL gravity dry-run")
        return 1
    credentials.self_test()
    dry_run_checks()
    print("PASS gravity dry-run")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    configured_products, workspace_error = _configured_products()
    parser = build_parser(configured_products)
    args = parser.parse_args(argv)

    if args.command == "credentials":
        return _run_credentials(args)

    missing_products = _missing_products_error(configured_products, workspace_error)
    if missing_products is not None:
        return missing_products

    if args.command == "status":
        try:
            result = readiness_status(resolve_current_evidence())
        except (EvidenceFormatError, WorkspaceError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            readiness = "READY" if result["query_ready"] else "NOT_READY"
            print(f"{readiness} {result['status']}: {result['reason']}")
            if result.get("verified_for_date"):
                print(f"verified_for_date={result['verified_for_date']}")
            print(f"evidence={result['evidence_path']}")
        return 0

    if args.command == "evidence-preflight":
        try:
            result = evidence_preflight(date.fromisoformat(args.date) if args.date else None)
        except (EvidenceFormatError, OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            state = "PASS" if result["offline_checks_passed"] else "BLOCKED"
            print(f"{state} Evidence offline preflight for {result['target_date']}")
            for blocker in result["offline_blockers"]:
                print(f"blocker={blocker}")
            print(f"snapshot_id={result['current_evidence']['snapshot_id']}")
            print(f"result_sha256={result['current_evidence']['result_sha256']}")
        return 0

    if args.command == "verify":
        try:
            safe_day = latest_safe_date()
            target_day = date.fromisoformat(args.date) if args.date else safe_day
            if target_day > safe_day:
                raise ValueError(f"date {target_day} is newer than latest safe date {safe_day}")
            if args.publish and target_day != safe_day:
                raise ValueError("--publish only accepts the latest safe date")
            evidence = verify_all(_client(), target_day)
            if args.publish:
                publish_evidence(evidence)
                print(f"PUBLISHED {EVIDENCE_PATH}", file=sys.stderr)
            print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        except (GravityAuthError, EvidenceFormatError, OSError, RuntimeError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    if args.command == "query":
        try:
            evidence_binding = resolve_current_evidence()
            status = readiness_status(evidence_binding)
            if not status["query_ready"]:
                print(f"ERROR: query rejected: {status['status']}: {status['reason']}", file=sys.stderr)
                return 1
            start_at, end_at = normalize_window(args.start, args.end)
            result = run_product(_client(), args.product, start_at, end_at, args.app_id)
            result["evidence_reference"] = evidence_binding.reference()
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        except (GravityAuthError, EvidenceFormatError, OSError, RuntimeError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    if not args.dry_run:
        parser.error("Choose --dry-run, status, evidence-preflight, verify, query, or credentials.")

    return _run_dry_checks()


def _client() -> GravityClient:
    return build_sql_client()


if __name__ == "__main__":
    raise SystemExit(main())
