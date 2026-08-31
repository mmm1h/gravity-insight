from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from .coverage import coverage_files
from .diffing import diff_files
from .fetcher import DEFAULT_SITE, StaticFetcher, check_upstream
from .impact import impact_files
from .io import json_bytes, read_json, write_json
from .parser import parse_snapshot

from gravity_insight.paths import CONTRACT_ROOT, MANIFEST_ROOT, PROJECT_ROOT, TMP_ROOT
from gravity_insight.errors import ErrorCategory, exit_code_for_category


REPO_ROOT = PROJECT_ROOT
TOOL_ROOT = Path(__file__).resolve().parent
DATA_DIR = TOOL_ROOT / "data"
DEFAULT_RAW_DIR = TMP_ROOT / "codex" / "gi-census-full" / "final"
DEFAULT_SNAPSHOT = DATA_DIR / "bundle-snapshot.json"
DEFAULT_ROUTES = DATA_DIR / "routes.json"
DEFAULT_ROUTE_PARAMS = DATA_DIR / "route-params.json"
DEFAULT_ROUTE_RESPONSE_FIELDS = DATA_DIR / "route-response-fields.json"
DEFAULT_COVERAGE = DATA_DIR / "coverage.json"
DEFAULT_REPORT = DATA_DIR / "coverage-report.md"
DEFAULT_MANIFESTS = MANIFEST_ROOT
DEFAULT_PROVENANCE = CONTRACT_ROOT / "generated" / "provenance.json"
DEFAULT_CONTRACTS = CONTRACT_ROOT
DEFAULT_DRAFTS = DEFAULT_CONTRACTS / "drafts"
DEFAULT_BATCH_RESULTS = TMP_ROOT / "codex" / "gi-batch-probe" / "final-results.json"
DEFAULT_RESERVATIONS = DEFAULT_CONTRACTS / "reservations"
DEFAULT_ROUTE_REGISTRY = DEFAULT_CONTRACTS / "routes" / "registry.json"
_CALLER_EXIT = exit_code_for_category(ErrorCategory.CALLER)
_UPSTREAM_EXIT = exit_code_for_category(ErrorCategory.UPSTREAM)
_LOCAL_EXIT = exit_code_for_category(ErrorCategory.LOCAL)
_CAPACITY_STATUS_CLASSES = frozenset(
    {"rate_limited", "server_error", "transport_error"}
)


def _path(value: str) -> Path:
    return Path(value).resolve()


def _coverage_summary(result: dict[str, Any]) -> dict[str, Any]:
    source = result.get("source", {})
    return {
        **result["summary"],
        "coverage_scope": source.get("coverage_scope", "unrecorded"),
        "platform_complete": source.get("platform_complete", False),
        "known_excluded_origins": source.get("known_excluded_origins", []),
    }


def _run_coverage(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    result = coverage_files(
        args.routes,
        args.manifests,
        args.output,
        args.report,
        args.baseline_routes,
        args.reservations,
        args.route_registry,
    )
    summary = _coverage_summary(result)
    incomplete = not bool(result.get("source", {}).get("bundle_complete", False))
    unaccounted = int(result.get("summary", {}).get("unaccounted", 0))
    if args.require_accounted and unaccounted:
        return summary, _LOCAL_EXIT
    return summary, _UPSTREAM_EXIT if args.require_complete and incomplete else 0


def _root_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gravity census",
        description="Maintainer-only Gravity frontend static route census"
    )
    parser.add_argument("--smoke", action="store_true", help="run deterministic offline smoke checks")
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = _root_parser()
    subparsers = parser.add_subparsers(dest="command")

    fetch = subparsers.add_parser("fetch", help="discover and GET public frontend bundles")
    fetch.add_argument("--site", default=DEFAULT_SITE)
    fetch.add_argument("--raw-dir", type=_path, default=DEFAULT_RAW_DIR)
    fetch.add_argument("--output", type=_path, default=DEFAULT_SNAPSHOT)
    fetch.add_argument("--max-requests", type=int, default=800)
    fetch.add_argument("--max-attempts", type=int, default=3)
    fetch.add_argument("--concurrency", type=int, default=4)
    fetch.add_argument("--timeout", type=float, default=45.0)
    fetch.add_argument("--no-manifest-probes", action="store_true")
    fetch.add_argument("--require-complete", action="store_true")
    fetch.add_argument("--failure-output", type=_path,
                       help="write a sanitized machine-readable failure classification")

    parse = subparsers.add_parser("parse", help="parse downloaded bundles into routes.json")
    parse.add_argument("--snapshot", type=_path, default=DEFAULT_SNAPSHOT)
    parse.add_argument("--raw-dir", type=_path, default=DEFAULT_RAW_DIR)
    parse.add_argument("--output", type=_path, default=DEFAULT_ROUTES)

    params = subparsers.add_parser("params", help="extract request parameter contracts")
    params.add_argument("--snapshot", type=_path, default=DEFAULT_SNAPSHOT)
    params.add_argument("--routes", type=_path, default=DEFAULT_ROUTES)
    params.add_argument("--raw-dir", type=_path, default=DEFAULT_RAW_DIR)
    params.add_argument("--output", type=_path, default=DEFAULT_ROUTE_PARAMS)
    params.add_argument("--batch-results", type=_path, default=DEFAULT_BATCH_RESULTS)
    params.add_argument("--drafts", type=_path, default=DEFAULT_DRAFTS)

    responses = subparsers.add_parser("responses", help="extract response-field consumers")
    responses.add_argument("--snapshot", type=_path, default=DEFAULT_SNAPSHOT)
    responses.add_argument("--routes", type=_path, default=DEFAULT_ROUTES)
    responses.add_argument("--raw-dir", type=_path, default=DEFAULT_RAW_DIR)
    responses.add_argument("--output", type=_path, default=DEFAULT_ROUTE_RESPONSE_FIELDS)
    responses.add_argument("--drafts", type=_path, default=DEFAULT_DRAFTS)
    responses.add_argument(
        "--apply-drafts",
        action="store_true",
        help="merge static fields into fail-closed draft candidate_fields",
    )

    apply_responses = subparsers.add_parser(
        "apply-responses", help="apply an existing response-field artifact to drafts"
    )
    apply_responses.add_argument(
        "--responses", type=_path, default=DEFAULT_ROUTE_RESPONSE_FIELDS
    )
    apply_responses.add_argument("--drafts", type=_path, default=DEFAULT_DRAFTS)

    coverage = subparsers.add_parser("coverage", help="reconcile routes with SDK manifests")
    coverage.add_argument("--routes", type=_path, default=DEFAULT_ROUTES)
    coverage.add_argument("--manifests", type=_path, default=DEFAULT_MANIFESTS)
    coverage.add_argument("--output", type=_path, default=DEFAULT_COVERAGE)
    coverage.add_argument("--report", type=_path, default=DEFAULT_REPORT)
    coverage.add_argument("--baseline-routes", type=_path)
    coverage.add_argument("--reservations", type=_path, default=DEFAULT_RESERVATIONS)
    coverage.add_argument("--route-registry", type=_path, default=DEFAULT_ROUTE_REGISTRY)
    coverage.add_argument("--require-complete", action="store_true")
    coverage.add_argument(
        "--require-accounted",
        action="store_true",
        help="fail when any route lacks an explicit or semantic accounting state",
    )

    diff = subparsers.add_parser("diff", help="diff two routes documents or bundle snapshots")
    diff.add_argument("old", type=_path)
    diff.add_argument("new", type=_path)
    diff.add_argument("--output", type=_path)
    diff.add_argument("--fail-on-change", action="store_true")

    impact = subparsers.add_parser(
        "impact", help="map a route diff through provenance to affected operations"
    )
    impact.add_argument("diff", type=_path)
    impact.add_argument("--provenance", type=_path, default=DEFAULT_PROVENANCE)
    impact.add_argument("--contracts-root", type=_path, default=DEFAULT_CONTRACTS)
    impact.add_argument("--output", type=_path)
    impact.add_argument("--overlay-output", type=_path)
    impact.add_argument("--census-complete", action="store_true", default=None)
    impact.add_argument("--require-complete", action="store_true")

    upstream = subparsers.add_parser("check-upstream", help="GET HTML only and compare entry hashes")
    upstream.add_argument("--site", default=DEFAULT_SITE)
    upstream.add_argument("--baseline", type=_path, default=DEFAULT_SNAPSHOT)
    upstream.add_argument("--output", type=_path)
    upstream.add_argument("--timeout", type=float, default=30.0)
    return parser


def _smoke() -> dict[str, Any]:
    from .normalize import normalize_path

    sample = normalize_path("/api/v1/app/${app.id}/detail?x=1")
    if sample != "/api/v1/app/{id}/detail":
        raise RuntimeError(f"normalization smoke failed: {sample}")
    operations = sum(
        len(json.loads(path.read_text(encoding="utf-8")).get("operations", []))
        for path in sorted(DEFAULT_MANIFESTS.glob("*.json"))
    )
    if operations <= 0:
        raise RuntimeError("no Gravity Insight manifest operations found")
    return {"status": "pass", "offline": True, "network_called": False, "manifest_operations": operations}


def _run_fetch(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    fetcher = StaticFetcher(
        max_attempts=args.max_attempts,
        max_requests=args.max_requests,
        concurrency=args.concurrency,
        timeout=args.timeout,
    )
    result = fetcher.fetch(
        site_url=args.site,
        raw_dir=args.raw_dir,
        snapshot_path=args.output,
        probe_manifests=not args.no_manifest_probes,
    )
    incomplete = args.require_complete and not result["summary"]["complete"]
    if incomplete and args.failure_output:
        write_json(args.failure_output, _incomplete_fetch_failure(result))
    return result["summary"], _UPSTREAM_EXIT if incomplete else 0


def _safe_fetch_failures(result: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for failure in result.get("discovery", {}).get("failures", []):
        if not isinstance(failure, dict):
            continue
        status = failure.get("status_code")
        exception_type = failure.get("exception_type")
        rows.append(
            {
                "host": str(failure.get("host", "unknown")),
                "status_class": str(failure.get("status_class", "unknown")),
                "http_status": status if type(status) is int else None,
                "exception_type": (
                    str(exception_type) if exception_type is not None else None
                ),
            }
        )
    return rows


def _incomplete_fetch_failure(result: dict[str, Any]) -> dict[str, Any]:
    failures = _safe_fetch_failures(result)
    capacity = bool(failures) and all(
        failure["status_class"] in _CAPACITY_STATUS_CLASSES
        for failure in failures
    )
    failure_class = "upstream_capacity" if capacity else "incomplete_graph"
    next_action = (
        "Wait at least 30000 ms, then retry `gravity census fetch --require-complete` "
        "once. If capacity failures persist, inspect upstream rate-limit and service "
        "health before another crawl."
        if capacity
        else "Inspect the snapshot completeness_reason and discovery failures; do not "
        "promote route or contract changes until a complete graph is proven."
    )
    summary = result.get("summary", {})
    return {
        "status": "error",
        "error": "The public static graph could not be proven complete.",
        "code": (
            "CENSUS_UPSTREAM_CAPACITY"
            if capacity
            else "CENSUS_INCOMPLETE_GRAPH"
        ),
        "category": "upstream",
        "retryable": capacity,
        "failure_class": failure_class,
        "failures": failures,
        "cooldown_remaining_ms": 30_000 if capacity else 0,
        "summary": {
            "complete": bool(summary.get("complete", False)),
            "request_attempts": int(summary.get("request_attempts", 0)),
            "pending_js": int(summary.get("pending_js", 0)),
            "failed_js": int(summary.get("failed_js", 0)),
        },
        "next_action": next_action,
    }


def _exception_failure(error: BaseException) -> dict[str, Any]:
    error_code = str(getattr(error, "code", ""))
    diagnostics = getattr(error, "diagnostics", None)
    if error_code.startswith("GOVERNOR_") and isinstance(diagnostics, dict):
        return {
            "status": "error",
            "error": str(error),
            "code": error_code,
            "category": "upstream",
            "retryable": True,
            **diagnostics,
            "next_action": str(getattr(error, "next_action", "") or ""),
        }
    status_class = str(getattr(error, "status_class", "unknown"))
    capacity = status_class in _CAPACITY_STATUS_CLASSES
    status = getattr(error, "status_code", None)
    exception_type = getattr(error, "exception_type", None)
    return {
        "status": "error",
        "error": str(error),
        "code": (
            "CENSUS_UPSTREAM_CAPACITY" if capacity else "CENSUS_FETCH_FAILED"
        ),
        "category": "upstream" if hasattr(error, "status_class") else "local",
        "retryable": capacity,
        "failure_class": "upstream_capacity" if capacity else "unclassified",
        "failures": (
            [
                {
                    "host": str(getattr(error, "host", "unknown")),
                    "status_class": status_class,
                    "http_status": status if type(status) is int else None,
                    "exception_type": (
                        str(exception_type) if exception_type is not None else None
                    ),
                }
            ]
            if hasattr(error, "status_class")
            else []
        ),
        "cooldown_remaining_ms": 30_000 if capacity else 0,
        "next_action": (
            "Wait at least 30000 ms, then retry the same census fetch once."
            if capacity
            else "Inspect this local failure and retry only after correcting it."
        ),
    }


def _write_failure(args: argparse.Namespace, payload: dict[str, Any]) -> None:
    target = getattr(args, "failure_output", None)
    if target:
        write_json(target, payload)


def _run_parse(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    result = parse_snapshot(args.snapshot, args.raw_dir, args.output)
    return result["summary"], 0


def _run_params(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from .params import extract_route_params

    result = extract_route_params(
        args.snapshot,
        args.routes,
        args.raw_dir,
        args.output,
        repo_root=REPO_ROOT,
        batch_results_path=args.batch_results,
        drafts_root=args.drafts,
    )
    return {**result["summary"], "validation": result["validation"]}, 0


def _run_responses(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from .response import apply_response_fields_to_drafts, extract_route_response_fields

    result = extract_route_response_fields(args.snapshot, args.routes, args.raw_dir, args.output)
    rendered = dict(result["summary"])
    if args.apply_drafts:
        rendered["draft_integration"] = apply_response_fields_to_drafts(result, args.drafts)
    return rendered, 0


def _run_apply_responses(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from .response import apply_response_fields_to_drafts

    return apply_response_fields_to_drafts(read_json(args.responses), args.drafts), 0


def _run_diff(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    result = diff_files(args.old, args.new)
    if args.output:
        write_json(args.output, result)
    changed = any(int(value) for value in result.get("summary", {}).values())
    return result, 5 if args.fail_on_change and changed else 0


def _run_impact(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    try:
        from gravity_insight.drift import HealthOverlay
    except ModuleNotFoundError:  # source checkout before editable installation
        from gravity_insight.drift import HealthOverlay

    overlay = HealthOverlay(args.overlay_output) if args.overlay_output else HealthOverlay()
    result = impact_files(
        args.diff,
        args.provenance,
        args.contracts_root,
        census_complete=args.census_complete,
        overlay=overlay,
    )
    if args.output:
        write_json(args.output, result)
    if args.overlay_output:
        write_json(args.overlay_output, overlay.snapshot())
    incomplete = not bool(result.get("census_complete"))
    return result, _UPSTREAM_EXIT if args.require_complete and incomplete else 0


def _run_check_upstream(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    result = check_upstream(args.site, read_json(args.baseline), timeout=args.timeout)
    if args.output:
        write_json(args.output, result)
    return result, 0


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    if args.smoke:
        if args.command:
            raise ValueError("--smoke cannot be combined with a command")
        return _smoke(), 0
    handlers = {
        "fetch": _run_fetch,
        "parse": _run_parse,
        "params": _run_params,
        "responses": _run_responses,
        "apply-responses": _run_apply_responses,
        "coverage": _run_coverage,
        "diff": _run_diff,
        "impact": _run_impact,
        "check-upstream": _run_check_upstream,
    }
    handler = handlers.get(args.command)
    if handler is None:
        raise ValueError("choose --smoke or a subcommand")
    return handler(args)


def main(argv: Sequence[str] | None = None) -> int:
    from ..cli_stdio import configure_utf8_stdio

    configure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result, exit_code = run(args)
    except (OSError, UnicodeEncodeError, RuntimeError) as exc:
        payload = _exception_failure(exc)
        _write_failure(args, payload)
        sys.stderr.buffer.write(json_bytes(payload))
        return (
            _UPSTREAM_EXIT
            if payload.get("category") == "upstream"
            else _LOCAL_EXIT
        )
    except (ValueError, json.JSONDecodeError) as exc:
        sys.stderr.buffer.write(json_bytes({"status": "error", "error": str(exc)}))
        return _CALLER_EXIT
    sys.stdout.buffer.write(json_bytes(result))
    return exit_code
