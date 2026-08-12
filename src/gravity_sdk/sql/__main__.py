from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import date

from gravity_sdk.http_runtime import MAX_SQL_CONCURRENCY
from gravity_sdk.sql import credentials
from gravity_sdk.sql.client import (
    GravityAuthError,
    GravityClient,
    _extract_rows,
    build_sql_client,
)
from gravity_sdk.sql.cli_input import query_requests
from gravity_sdk.sql.credentials import CredentialSyncError
from gravity_sdk.sql.dry_run import dry_run_override
from gravity_sdk.sql.export import build_paged_sql
from gravity_sdk.sql.products import (
    EVIDENCE_PATH,
    EvidenceFormatError,
    dry_run_checks,
    describe_products,
    evidence_preflight,
    latest_safe_date,
    normalize_window,
    publish_evidence,
    product_names,
    readiness_status,
    resolve_current_evidence,
    run_product_queries,
    verify_all,
)
from gravity_sdk.workspace import WorkspaceError, load_workspace


class _DirectQueryInputError(ValueError):
    def __init__(self, code: str, field: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field


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
        prog="gravity sql",
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
    commands.add_parser(
        "products",
        help="Describe every callable SQL product and the query input contract.",
    )
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
    query_parser.add_argument("product", nargs="?")
    query_parser.add_argument("--start", help="Inclusive ISO timestamp.")
    query_parser.add_argument("--end", help="Exclusive ISO timestamp.")
    query_parser.add_argument("--app-id", type=int, action="extend", nargs="+", help="Positive Gravity app id.")
    query_parser.add_argument(
        "-i",
        "--input",
        help="Inline JSON, JSON file, or '-' for stdin; accepts one request, an array, or a requests wrapper.",
    )
    query_parser.add_argument(
        "--concurrency",
        type=int,
        default=MAX_SQL_CONCURRENCY,
        help=f"Concurrent product reads (1..{MAX_SQL_CONCURRENCY}; default: {MAX_SQL_CONCURRENCY}).",
    )
    return parser


def _query_requests(args: argparse.Namespace) -> list[Mapping[str, object]]:
    """Compatibility seam retained for callers and focused CLI tests."""

    return query_requests(args)


def _evidence_context(
    workspace: object,
) -> tuple[dict[str, object] | None, str | None]:
    try:
        binding = resolve_current_evidence(workspace=workspace)
        status = readiness_status(binding, workspace=workspace)
    except (EvidenceFormatError, OSError, RuntimeError, ValueError):
        return None, (
            "No current valid SQL Evidence is available; the registered aggregate "
            "product query was executed without an Evidence reference."
        )
    reference = binding.reference()
    if not isinstance(reference, dict):
        return None, (
            "Current SQL Evidence has an invalid reference; the registered aggregate "
            "product query was executed without an Evidence reference."
        )
    if status.get("query_ready"):
        return reference, None
    return reference, (
        f"SQL Evidence is {status.get('status', 'not_ready')}: "
        f"{status.get('reason', 'not query-ready')}; the registered aggregate "
        "product query was executed without using Evidence as an authorization gate."
    )


def _emit_query_result(
    envelope: dict[str, object],
    evidence_reference: dict[str, object] | None,
    evidence_warning: str | None,
) -> int:
    results = envelope["results"]
    if not isinstance(results, list):  # Internal invariant; keep machine output stable.
        raise RuntimeError("invalid SQL query result envelope")
    if len(results) == 1:
        payload = dict(results[0])
        payload["schema_version"] = envelope["schema_version"]
        payload["exit_code"] = envelope["exit_code"]
        payload["evidence_reference"] = evidence_reference
        if evidence_warning:
            payload["evidence_warning"] = evidence_warning
    else:
        payload = dict(envelope)
        payload["evidence_reference"] = evidence_reference
        if evidence_warning:
            payload["evidence_warning"] = evidence_warning
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return int(envelope["exit_code"])


def _emit_query_error(
    message: str,
    *,
    category: str,
    code: str,
    exit_code: int,
    field: str | None = None,
) -> int:
    print(
        json.dumps(
            {
                "schema_version": "gravity-sql.query.v1",
                "ok": False,
                "status": "error",
                "exit_code": exit_code,
                "error": {
                    "category": category,
                    "code": code,
                    "field": field,
                    "message": message,
                    "next_action": (
                        "Run `gravity auth status`; refresh or configure credentials, then retry."
                        if category == "authentication"
                        else
                        "Run `gravity sql products`, correct this request, and retry."
                        if exit_code == 2
                        else "Inspect the governed SQL product contract and local state."
                        if exit_code == 4
                        else "Retry after checking Gravity authentication and availability."
                    ),
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        file=sys.stderr,
    )
    return exit_code


def _validate_direct_query_before_client(
    requests: list[Mapping[str, object]],
    configured_products: tuple[str, ...],
) -> None:
    """Reject malformed direct timestamps before credentials/client construction.

    Batch items remain isolated by ``run_product_queries``; this fast path keeps
    the traditional one-product CLI behavior fail-fast and network-free.
    """

    if len(requests) != 1:
        return
    value = requests[0]
    product = value.get("product")
    if not isinstance(product, str) or product not in configured_products:
        raise _DirectQueryInputError(
            "SQL_PRODUCT_UNKNOWN",
            "product",
            "SQL product is not configured in the selected workspace",
        )
    start = value.get("start")
    end = value.get("end")
    if not isinstance(start, str) or not isinstance(end, str):
        raise _DirectQueryInputError(
            "SQL_PRODUCT_WINDOW_REQUIRED",
            "start/end",
            "SQL product request requires string start and end timestamps",
        )
    try:
        normalize_window(start, end)
    except ValueError as exc:
        raise _DirectQueryInputError(
            "SQL_PRODUCT_WINDOW_INVALID",
            "start/end",
            "SQL product request has an invalid time window",
        ) from exc


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


def _run_products_command() -> int:
    products = describe_products()
    payload = {
        "schema_version": "gravity-sql.products.v1",
        "ok": True,
        "status": "success",
        "count": len(products),
        "query_input": {
            "accepted_forms": ["object", "array", "requests_wrapper"],
            "fields": {
                "product": "required string",
                "start": "required inclusive ISO timestamp",
                "end": "required exclusive ISO timestamp",
                "app_ids": "optional positive integer array",
                "request_id": "optional string",
            },
            "stdin": "use query --input -",
            "max_concurrency": MAX_SQL_CONCURRENCY,
        },
        "products": products,
        "next_action": (
            "Run `gravity sql query <product> --start <iso> --end <iso>` "
            "or pass the query_input JSON form with `--input`."
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _run_status_command(args: argparse.Namespace) -> int:
    try:
        workspace = load_workspace()
        result = readiness_status(
            resolve_current_evidence(workspace=workspace),
            workspace=workspace,
        )
    except (EvidenceFormatError, WorkspaceError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    readiness = "READY" if result["query_ready"] else "NOT_READY"
    print(f"{readiness} {result['status']}: {result['reason']}")
    if result.get("verified_for_date"):
        print(f"verified_for_date={result['verified_for_date']}")
    print(f"evidence={result['evidence_path']}")
    return 0


def _run_preflight_command(args: argparse.Namespace) -> int:
    try:
        result = evidence_preflight(
            date.fromisoformat(args.date) if args.date else None,
            workspace=load_workspace(),
        )
    except (EvidenceFormatError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    state = "PASS" if result["offline_checks_passed"] else "BLOCKED"
    print(f"{state} Evidence offline preflight for {result['target_date']}")
    for blocker in result["offline_blockers"]:
        print(f"blocker={blocker}")
    print(f"snapshot_id={result['current_evidence']['snapshot_id']}")
    print(f"result_sha256={result['current_evidence']['result_sha256']}")
    return 0


def _run_verify_command(args: argparse.Namespace) -> int:
    try:
        safe_day = latest_safe_date()
        target_day = date.fromisoformat(args.date) if args.date else safe_day
        if target_day > safe_day:
            raise ValueError(f"date {target_day} is newer than latest safe date {safe_day}")
        if args.publish and target_day != safe_day:
            raise ValueError("--publish only accepts the latest safe date")
        workspace = load_workspace()
        evidence = verify_all(_client(), target_day, workspace=workspace)
        if args.publish:
            publish_evidence(evidence, workspace=workspace)
            print(f"PUBLISHED {EVIDENCE_PATH}", file=sys.stderr)
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (GravityAuthError, EvidenceFormatError, OSError, RuntimeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


def _run_query_command(
    args: argparse.Namespace, configured_products: tuple[str, ...]
) -> int:
    try:
        requests = _query_requests(args)
        _validate_direct_query_before_client(requests, configured_products)
        workspace = load_workspace()
        evidence_reference, evidence_warning = _evidence_context(workspace)
        result = run_product_queries(
            _client(),
            requests,
            max_workers=args.concurrency,
            workspace=workspace,
        )
        return _emit_query_result(result, evidence_reference, evidence_warning)
    except _DirectQueryInputError as exc:
        return _emit_query_error(
            str(exc),
            category="input",
            code=exc.code,
            field=exc.field,
            exit_code=2,
        )
    except GravityAuthError:
        return _emit_query_error(
            "Gravity SQL credentials are unavailable",
            category="authentication",
            code="SQL_PRODUCT_CREDENTIALS_UNAVAILABLE",
            exit_code=2,
        )
    except OSError:
        return _emit_query_error(
            "SQL query input or local state could not be read",
            category="local_io",
            code="SQL_PRODUCT_LOCAL_IO",
            exit_code=4,
            field="input",
        )
    except EvidenceFormatError:
        return _emit_query_error(
            "SQL product or Evidence violated its local contract",
            category="contract",
            code="SQL_PRODUCT_CONTRACT_VIOLATION",
            exit_code=4,
        )
    except ValueError:
        return _emit_query_error(
            "SQL query input is invalid; run `gravity sql products` for the input contract",
            category="input",
            code="SQL_PRODUCT_INPUT_INVALID",
            exit_code=2,
        )
    except TypeError:
        return _emit_query_error(
            "SQL query result violated its machine-output contract",
            category="contract",
            code="SQL_PRODUCT_OUTPUT_CONTRACT_INVALID",
            exit_code=4,
        )
    except RuntimeError:
        return _emit_query_error(
            "Gravity SQL query failed",
            category="runtime",
            code="SQL_PRODUCT_RUNTIME_FAILED",
            exit_code=3,
        )


def main(argv: Sequence[str] | None = None) -> int:
    configured_products, workspace_error = _configured_products()
    parser = build_parser(configured_products)
    args = parser.parse_args(argv)

    if args.dry_run:
        dry_result = dry_run_override(args, configured_products)
        if dry_result is not None:
            return dry_result

    if args.command == "credentials":
        return _run_credentials(args)
    missing_products = _missing_products_error(configured_products, workspace_error)
    if missing_products is not None:
        return missing_products
    if args.command == "products":
        return _run_products_command()
    if args.command == "status":
        return _run_status_command(args)
    if args.command == "evidence-preflight":
        return _run_preflight_command(args)
    if args.command == "verify":
        return _run_verify_command(args)
    if args.command == "query":
        return _run_query_command(args, configured_products)
    if args.dry_run:
        return _run_dry_checks()
    parser.error(
        "Choose --dry-run, products, status, evidence-preflight, verify, query, or credentials."
    )
    return 2


def _client() -> GravityClient:
    return build_sql_client()


if __name__ == "__main__":
    raise SystemExit(main())
