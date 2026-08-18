"""Thin CLI bridge for compact Analysis query specs."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .analysis_spec import (
    analysis_query_spec_schema,
    prepare_query_spec,
    validate_query_spec,
)
from .result_source import GOVERNED_PRODUCT, add_result_source
from .domains import ANALYSIS_QUERY_OPERATIONS, new_analysis_query_id
from .errors import InputValidationError
from .result_output import output_file
from .actionable_error_values import actual_value


def add_analysis_query_arguments(
    parser: Any,
    add_input: Callable[..., Any],
    add_shortcuts: Callable[[Any], None],
    concurrency_type: Callable[[str], int],
) -> None:
    parser.add_argument(
        "--kind",
        choices=sorted(ANALYSIS_QUERY_OPERATIONS),
        help="event, funnel, property, retention, or scatter; required except for batch",
    )
    parser.add_argument(
        "--experimental",
        action="store_true",
        help="allow the operation only when the registry marks it experimental",
    )
    add_input(parser)
    add_shortcuts(parser)
    parser.add_argument(
        "--spec",
        help="compact Analysis spec as inline JSON, file path, or '-' for stdin",
    )
    parser.add_argument(
        "--app",
        help="workspace App alias or positive id; required with --spec",
    )
    parser.add_argument(
        "--apps",
        action="append",
        help=(
            "comma-separated explicit Apps for event/funnel/retention/property; "
            "may be repeated"
        ),
    )
    parser.add_argument(
        "--concurrency",
        dest="analysis_query_concurrency",
        type=concurrency_type,
        default=6,
        help="Plan worker budget for --apps (default: 6, maximum: 24)",
    )
    parser.add_argument("--workspace", help="gravity.toml or its directory for --spec")
    parser.add_argument(
        "--compare-start",
        help="explicit baseline window start date for same-spec period compare",
    )
    parser.add_argument(
        "--compare-end",
        help="explicit baseline window end date for same-spec period compare",
    )
    parser.add_argument(
        "--compare-concurrency",
        type=int,
        default=None,
        help="existing batch worker budget for the two windows (default: 2, maximum: 24)",
    )
    parser.add_argument(
        "--dry-run",
        dest="query_spec_dry_run",
        action="store_true",
        help="compile and validate --spec offline without sending a request",
    )
    parser.add_argument(
        "--spec-schema",
        action="store_true",
        help="print the compact Analysis Spec v1 contract; requires --kind and is offline",
    )
    parser.add_argument(
        "--output", type=output_file,
        help="Atomically write the complete JSON result to a local file.",
    )
    parser.set_defaults(result_output_fail_closed=True)


def run_analysis_query_command(
    args: Any,
    build_client: Callable[[], Any],
    parse_object: Callable[[str], Mapping[str, Any]],
    merge_shortcuts: Callable[..., tuple[dict[str, Any], list[str]]],
    call_read: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    if args.kind is None:
        raise InputValidationError(
            f"actual value: {actual_value(args.kind)}; " + ("analysis query requires --kind unless the batch subcommand is used"),
            field="kind",
            next_action=(
                "Run `gravity analysis query --kind <kind> --help`, or use "
                "`gravity analysis query batch --input <queries.json>`."
            ),
        )
    if getattr(args, "apps", None) and args.spec is None:
        raise InputValidationError(f"actual value: {actual_value(getattr(args, 'apps', None))}; " + ("--apps requires --spec"), field="apps")
    schema = _spec_schema_result(args)
    if schema is not None:
        return schema
    if args.spec is None and bool(getattr(args, "query_spec_dry_run", False)):
        raise InputValidationError(
            f"actual value: {actual_value(args.spec)}; " + ("--dry-run requires --spec; raw --input cannot be executed in dry-run mode"),
            field="dry_run",
        )
    compare_start, compare_end = _compare_dates(args)
    client = build_client()
    operation_id = ANALYSIS_QUERY_OPERATIONS[args.kind]
    stability = client.schema(operation_id).get("stability", "stable")
    if stability != "stable":
        if not bool(getattr(args, "experimental", False)):
            raise InputValidationError(
                f"actual value: {actual_value(getattr(args, 'experimental', False))}; "
                "experimental analysis reads require explicit --experimental",
                field="experimental", next_action="Add --experimental and retry the same request.",
            )
        client = build_client(allow_experimental=True)
    if args.spec is None:
        return _run_raw_query(
            args, client, operation_id, parse_object, merge_shortcuts, call_read
        )
    if args.input is not None:
        raise InputValidationError(
            f"actual value: {actual_value({'spec': args.spec, 'input': args.input})}; "
            "--spec cannot be combined with raw --input",
            field="spec",
            next_action="Omit either --spec or raw --input, then retry.",
        )
    _reject_unrelated_shortcuts(args)
    spec = parse_object(args.spec)
    options = {
        "workspace": getattr(args, "workspace", None),
        "app": getattr(args, "app", None) or getattr(args, "app_id", None),
        "start": getattr(args, "start", None),
        "end": getattr(args, "end", None),
    }
    return _run_compact_query(
        args,
        client,
        spec,
        options,
        compare_start,
        compare_end,
        call_read,
    )


def _spec_schema_result(args: Any) -> dict[str, Any] | None:
    if not bool(getattr(args, "spec_schema", False)):
        return None
    if args.spec is not None or args.input is not None:
        raise InputValidationError(
            f"actual value: {actual_value({'spec': args.spec, 'input': args.input})}; "
            "--spec-schema cannot be combined with --spec or --input",
            field="spec_schema",
            next_action="Omit either --spec-schema or --spec/--input, then retry.",
        )
    result = analysis_query_spec_schema()
    result["requested_kind"] = args.kind
    return result


def _run_raw_query(
    args: Any,
    client: Any,
    operation_id: str,
    parse_object: Callable[[str], Mapping[str, Any]],
    merge_shortcuts: Callable[..., tuple[dict[str, Any], list[str]]],
    call_read: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    if args.input is None:
        raise InputValidationError(
            f"actual value: {actual_value(args.spec)}; "
            "analysis query requires --spec, or expert raw --input",
            field="spec",
            next_action=(
                "Run `gravity analysis query --kind <kind> --spec-schema`, "
                "fill required fields, then retry with `--spec <json-or-file> "
                "--app <alias-or-id>`."
            ),
        )
    inputs, _ = merge_shortcuts(
        client, operation_id, args, parse_object(args.input)
    )
    inputs.setdefault("query_id", new_analysis_query_id())
    return call_read(client, operation_id, inputs)


def _run_compact_query(
    args: Any,
    client: Any,
    spec: Mapping[str, Any],
    options: Mapping[str, Any],
    compare_start: str | None,
    compare_end: str | None,
    call_read: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    if getattr(args, "apps", None):
        return _run_multi_app_query(args, client, spec, options, compare_start, compare_end)
    if bool(getattr(args, "dry_run", False)) or bool(
        getattr(args, "query_spec_dry_run", False)
    ):
        _reject_compare_dry_run(compare_start)
        return prepare_query_spec(client, args.kind, spec, **options)
    if compare_start is not None:
        return _run_period_compare(
            args, client, spec, options, compare_start, compare_end
        )
    compiled, _validation = validate_query_spec(
        client, args.kind, spec, **options
    )
    return add_result_source(
        call_read(client, compiled.operation_id, compiled.inputs),
        GOVERNED_PRODUCT,
        replace=True,
    )


def _run_multi_app_query(
    args: Any,
    client: Any,
    spec: Mapping[str, Any],
    options: Mapping[str, Any],
    compare_start: str | None,
    compare_end: str | None,
) -> dict[str, Any]:
    from .analysis_query_batch import MULTI_APP_BATCH_SCHEMA_VERSION
    from .sdk import GravitySDK

    if options.get("app") is not None:
        raise InputValidationError(
            f"actual value: {actual_value(options.get('app'))}; --apps cannot be "
            "combined with --app",
            field="apps",
            next_action="Omit either --apps or --app, then retry.",
        )
    if compare_start is not None or compare_end is not None:
        raise InputValidationError(
            f"actual value: {actual_value({'compare_start': compare_start, 'compare_end': compare_end})}; "
            "--apps does not support period compare",
            field="compare_start/compare_end",
            next_action="Omit period-compare dates or omit --apps, then retry.",
        )
    apps = [
        selected
        for value in args.apps
        for selected in (item.strip() for item in value.split(","))
        if selected
    ]
    query: dict[str, Any] = {
        "id": str(args.kind),
        "kind": args.kind,
        "apps": apps,
        "spec": dict(spec),
        "limits": {"max_items": 200},
    }
    if options.get("start") is not None:
        query["start"] = options["start"]
        query["end"] = options["end"]
    return GravitySDK(insight=client, workspace=options.get("workspace")).analysis_queries(
        {"schema_version": MULTI_APP_BATCH_SCHEMA_VERSION, "queries": [query]},
        max_workers=args.analysis_query_concurrency,
        dry_run=bool(getattr(args, "query_spec_dry_run", False)),
    )


def _compare_dates(args: Any) -> tuple[str | None, str | None]:
    start = getattr(args, "compare_start", None)
    end = getattr(args, "compare_end", None)
    concurrency = getattr(args, "compare_concurrency", None)
    if (start is None) != (end is None):
        raise InputValidationError(
            f"actual value: {actual_value((start, end))}; " + ("--compare-start and --compare-end must be provided together"),
            field="compare_start/compare_end",
        )
    if start is not None and args.spec is None:
        raise InputValidationError(f"actual value: {actual_value(args.spec)}; " + ("period compare requires --spec"), field="spec")
    if concurrency is not None and start is None:
        raise InputValidationError(
            f"actual value: {actual_value(concurrency)}; " + ("--compare-concurrency requires a compare window"),
            field="compare_concurrency",
        )
    return start, end


def _reject_compare_dry_run(compare_start: str | None) -> None:
    if compare_start is not None:
        raise InputValidationError(
            f"actual value: {actual_value(compare_start)}; period compare does not "
            "support --dry-run",
            field="dry_run",
            next_action="Omit --dry-run or omit the conflicting command, then retry.",
        )


def _run_period_compare(
    args: Any,
    client: Any,
    spec: Mapping[str, Any],
    options: Mapping[str, Any],
    compare_start: str,
    compare_end: str,
) -> dict[str, Any]:
    from .analysis_period_compare import compare_analysis_periods

    return compare_analysis_periods(
        client,
        args.kind,
        spec,
        workspace=options["workspace"],
        app=options["app"],
        current_start=options["start"],
        current_end=options["end"],
        baseline_start=compare_start,
        baseline_end=compare_end,
        max_workers=getattr(args, "compare_concurrency", None) or 2,
    )
def _reject_unrelated_shortcuts(args: Any) -> None:
    unsupported = {
        "media": getattr(args, "media", None),
        "time_dim": getattr(args, "time_dim", None),
        "dimensions": getattr(args, "dimensions", None),
        "metrics": getattr(args, "metrics", None),
        "multi_days": getattr(args, "multi_days", None),
        "parent_id": getattr(args, "parent_id", None),
    }
    selected = sorted(name for name, value in unsupported.items() if value is not None)
    if selected:
        raise InputValidationError(
            f"actual value: {actual_value(selected)}; "
            "--spec does not accept unrelated raw-query shortcuts: "
            + ", ".join(selected)
            + "; put grouping in spec.group_by and metrics in spec.steps[].metric",
            field="spec",
            next_action=(
                "Omit --"
                + ", --".join(name.replace("_", "-") for name in selected)
                + " and put those fields in `--spec`; inspect the contract with "
                "`gravity analysis query --kind <kind> --spec-schema`."
            ),
        )
