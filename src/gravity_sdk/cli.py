"""Command-line interface for the read-only Gravity Insight SDK."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from gravity_sdk.domains import (
    ANALYSIS_AUXILIARY_OPERATIONS,
    ANALYSIS_DASHBOARD_OPERATIONS,
    ANALYSIS_DETAIL_OPERATIONS,
    ANALYSIS_DIRECTORY_OPERATIONS,
    ANALYSIS_PAGINATED_OPERATIONS,
    ANALYSIS_REPORT_CONFIG_OPERATIONS,
    ANALYSIS_SEGMENT_OPERATIONS,
    ANALYSIS_TEMPLATE_OPERATIONS,
    ANALYSIS_VALUE_OPERATIONS,
    ATTRIBUTION_STATUS_OPERATIONS,
    DOMAIN_OPERATIONS,
    MULTIDIM_METADATA_OPERATIONS,
    MULTIDIM_TEMPLATE_SCOPES,
    PROMOTION_EQUALS_OPERATOR,
    PROMOTION_PARENT_FILTER_FIELDS,
    PROMOTION_PLATFORMS,
    PROMOTION_PRIMARY_OPERATIONS,
    promotion_operation,
)
from gravity_sdk import nonempty_cli, runtime
from gravity_sdk.cli_limits import (
    agent_limit as _agent_limit,
    operation_limit as _operation_limit,
    concurrency as _concurrency,
    positive_int as _positive_int,
    validate_date_pair,
)
from gravity_sdk.pagination_cli import (
    DEFAULT_STDOUT_MAX_ITEMS,
    DEFAULT_STDOUT_MAX_PAGES,
    add_pagination_arguments as _add_all_pages,
    page_options as _page_options,
)

try:
    from gravity_sdk.errors import (
        ErrorCategory,
        GravityInsightError,
        InputValidationError,
    )
    from gravity_sdk.export_cli import (
        add_export_commands, command_error, dispatch_command,
        output_argument,
    )
    from gravity_sdk.export_batch import (
        add_batch_commands, batch_schema_version, envelope_exit_code, run_batch_command,
    )
    from gravity_sdk.multidim import add_cli_query_arguments, call_cli_read, parse_multi_days
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_sdk.errors import (
        ErrorCategory,
        GravityInsightError,
        InputValidationError,
    )
    from gravity_sdk.export_cli import (
        add_export_commands, command_error, dispatch_command, output_argument,
    )
    from gravity_sdk.export_batch import (
        add_batch_commands, batch_schema_version, envelope_exit_code, run_batch_command,
    )
    from gravity_sdk.multidim import add_cli_query_arguments, call_cli_read, parse_multi_days

from gravity_sdk.parents import add_parent_commands, run_parent_command
from gravity_sdk.attribution import add_snapshot_command
from gravity_sdk.analysis_spec_cli import add_analysis_query_arguments, run_analysis_query_command
from gravity_sdk.business_pulse_cli import add_business_pulse_command
from gravity_sdk.saved_analysis_cli import add_saved_analysis_commands
from gravity_sdk.metadata_sync import (
    add_metadata_commands,
    run_analysis_metadata,
    run_metadata_command,
)
from gravity_sdk.find import (
    add_find_command,
    add_operation_commands,
    filter_operations,
    run_find_command,
    run_operation_command,
)
from gravity_sdk.find_input import (
    add_input as _add_input, date_range_input as _date_range_input,
    load_json_input as _load_json_input,
    normalize_input_arguments as _normalize_input_arguments,
    object_input as _object_input,
    without_filter as _without_filter,
)
from gravity_sdk.recipe import add_recipe_commands
from gravity_sdk.resolver_cli import add_resolver_command
from gravity_sdk.agent import DeferredAgentClient, add_agent_command, ndjson_metadata, run_agent_command
from gravity_sdk.capability_cli import add_deepening_commands
from gravity_sdk.read_cli import add_read_command
from gravity_sdk.plan_cli import add_plan_commands
from gravity_sdk.plan_product_cli import dispatch as dispatch_plan


_LARGE_VALUE_BYTES = 8_192
_MULTIDIM_QUERY_OPERATIONS = frozenset(
    (*DOMAIN_OPERATIONS["multidim.query"], *DOMAIN_OPERATIONS["multidim.calc_total"])
)


class AgentArgumentParser(argparse.ArgumentParser):
    def parse_args(
        self, args: Sequence[str] | None = None, namespace: argparse.Namespace | None = None
    ) -> argparse.Namespace:
        parsed = super().parse_args(args, namespace)
        _normalize_input_arguments(parsed)
        return parsed

    def error(self, message: str) -> None:
        raise InputValidationError(
            message,
            next_action="Run `gravity --help` and retry with valid arguments.",
        )


_SECRET_KEYS = {
    "authorization",
    "cookie",
    "password",
    "secret",
    "access_token",
    "refresh_token",
    "gravity_auth_token",
    "gravity_authorization",
    "token",
    "email",
    "email_address",
    "phone",
    "mobile",
    "user_name",
    "creator",
    "designer_id",
    "designer_name",
    "operator",
    "operator_name",
    "operator_id",
    "dept",
    "dept_name",
    "dept_id",
    "department",
    "callback_url",
    "click_url",
    "postback_url",
}


_SECRET_KEY_SUFFIXES = (
    "_password",
    "_url",
    "_token",
    "_email",
    "_phone",
    "_mobile",
    "_user_id",
    "_user_name",
    "_designer_id",
    "_designer_name",
)
_CONTRACTED_IDENTIFIER_KEYS = {
    "user_id",
    "event_user_id",
    "continuation_token",
}
_SESSION_SECRET_KEYS = {
    "authorization",
    "cookie",
    "password",
    "secret",
    "access_token",
    "refresh_token",
    "gravity_auth_token",
    "gravity_authorization",
    "session_token",
    "token",
}
_SESSION_SECRET_SUFFIXES = (
    "_password",
    "_token",
    "_secret",
    "_authorization",
    "_cookie",
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*")
_JWT_RE = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")


def _redact(value: Any, *, allow_analysis_business_fields: bool = False) -> Any:
    value = runtime.to_jsonable(value)
    if isinstance(value, Mapping):
        allow_analysis_business_fields = allow_analysis_business_fields or str(
            value.get("operation_id", "")
        ).startswith("analysis.")
        result: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            filter_operator = (
                lowered == "operator"
                and "field" in value
                and "values" in value
                and (
                    str(item).upper()
                    in {
                        "EQUALS",
                        "IN",
                        "NOT_EQUALS",
                        "NOT_IN",
                        "CONTAINS",
                        "GT",
                        "GTE",
                        "LT",
                        "LTE",
                    }
                    or isinstance(item, int)
                    and not isinstance(item, bool)
                )
            )
            blocked_keys = (
                _SESSION_SECRET_KEYS if allow_analysis_business_fields else _SECRET_KEYS
            )
            blocked_suffixes = (
                _SESSION_SECRET_SUFFIXES
                if allow_analysis_business_fields
                else _SECRET_KEY_SUFFIXES
            )
            if (
                (lowered in blocked_keys and not filter_operator)
                or (
                    lowered.endswith(blocked_suffixes)
                    and lowered not in _CONTRACTED_IDENTIFIER_KEYS
                )
                or not allow_analysis_business_fields
                and lowered.startswith("operator_")
                or not allow_analysis_business_fields
                and lowered.startswith("dept_")
            ):
                continue
            result[str(key)] = _redact(
                item,
                allow_analysis_business_fields=allow_analysis_business_fields,
            )
        return result
    if isinstance(value, list):
        return [
            _redact(
                item,
                allow_analysis_business_fields=allow_analysis_business_fields,
            )
            for item in value
        ]
    if isinstance(value, str):
        return _JWT_RE.sub("[REDACTED]", _BEARER_RE.sub("Bearer [REDACTED]", value))
    return value


def _write_json(value: Any, *, stream=None) -> None:
    print(
        json.dumps(_redact(value), ensure_ascii=False, indent=2, sort_keys=True),
        file=stream or sys.stdout,
    )


def _add_query_shortcuts(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--app-id")
    parser.add_argument("--media")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--time-dim", action="append")
    parser.add_argument("--dimensions", action="append")
    parser.add_argument("--metrics", action="append")
    parser.add_argument("--multi-days", action="append")
    parser.add_argument("--parent-id")


def _add_discovery_commands(commands: Any) -> None:
    add_agent_command(commands, _agent_limit)
    add_operation_commands(commands, _operation_limit)


def build_parser() -> argparse.ArgumentParser:
    parser = AgentArgumentParser(prog="gravity", description="Governed Gravity Insight read and export operations.")
    parser.set_defaults(network_required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run offline smoke checks; never call Gravity.",
    )
    commands = parser.add_subparsers(dest="command")

    _add_discovery_commands(commands)

    add_plan_commands(
        commands, _concurrency, _add_input, handler=dispatch_plan
    )

    validate = commands.add_parser(
        "validate", help="Validate one operation input without network access."
    )
    validate.set_defaults(network_required=False)
    validate.add_argument("operation_id")
    _add_input(validate, required=True)
    validate.add_argument("--render-wire", action="store_true")

    add_read_command(commands, _add_input, _add_all_pages, _positive_int)

    add_resolver_command(commands, _add_input, _add_all_pages)

    nonempty_cli.register(commands, _add_input)

    batch_input, batch_concurrency, batch_positive = _add_input, _concurrency, _positive_int
    add_batch_commands(commands, batch_input, batch_concurrency, batch_positive)

    auth = commands.add_parser(
        "auth", help="Inspect or refresh local Gravity credentials."
    )
    auth_commands = auth.add_subparsers(dest="auth_command", required=True)
    auth_status = auth_commands.add_parser("status")
    auth_status.set_defaults(network_required=False)
    auth_commands.add_parser("refresh")

    add_parent_commands(commands)

    add_business_pulse_command(commands, _concurrency, _positive_int)

    doctor = add_export_commands(commands, _add_input, _positive_int).add_parser(
        "doctor",
        help="Validate local contracts; --live runs every stable minimum probe.",
    )
    doctor.add_argument("--live", action="store_true")
    doctor.add_argument("--concurrency", type=_concurrency, default=6)
    doctor.set_defaults(network_required=False)

    apps_commands, _ = add_metadata_commands(
        commands, _concurrency, _add_input, _add_all_pages
    )

    analysis_commands = add_saved_analysis_commands(commands, _positive_int)
    analysis_metadata = analysis_commands.add_parser("metadata")
    analysis_metadata.add_argument("--app-id", required=True)
    _add_input(analysis_metadata)
    add_deepening_commands(apps_commands, analysis_commands, _concurrency)
    analysis_segments = analysis_commands.add_parser("segments")
    analysis_segments.add_argument("--app-id", required=True)
    analysis_segments.add_argument(
        "--experimental",
        action="store_true",
        help="allow the operation only when the registry marks it experimental",
    )
    _add_input(analysis_segments)
    _add_all_pages(analysis_segments)
    analysis_query = analysis_commands.add_parser("query")
    add_analysis_query_arguments(analysis_query, _add_input, _add_query_shortcuts)
    analysis_segment = analysis_commands.add_parser(
        "segment", help="Read a segment definition, history, trend, or member rows."
    )
    analysis_segment.add_argument(
        "--kind", required=True, choices=sorted(ANALYSIS_SEGMENT_OPERATIONS)
    )
    _add_input(analysis_segment, required=True)
    _add_all_pages(analysis_segment)
    analysis_report_config = analysis_commands.add_parser(
        "report-config", help="List or read a saved Analysis configuration."
    )
    analysis_report_config.add_argument(
        "--kind", required=True, choices=sorted(ANALYSIS_REPORT_CONFIG_OPERATIONS)
    )
    _add_input(analysis_report_config, required=True)
    _add_all_pages(analysis_report_config)
    analysis_dashboard = analysis_commands.add_parser(
        "dashboard", help="Read Analysis dashboard trees, details, and members."
    )
    analysis_dashboard.add_argument(
        "--kind", required=True, choices=sorted(ANALYSIS_DASHBOARD_OPERATIONS)
    )
    _add_input(analysis_dashboard, required=True)
    _add_all_pages(analysis_dashboard)
    analysis_values = analysis_commands.add_parser(
        "values", help="Read enumerable user or event property values."
    )
    analysis_values.add_argument(
        "--kind", required=True, choices=sorted(ANALYSIS_VALUE_OPERATIONS)
    )
    _add_input(analysis_values, required=True)
    analysis_users = analysis_commands.add_parser(
        "users", help="Read the account member directory."
    )
    _add_input(analysis_users)
    _add_all_pages(analysis_users)
    analysis_templates = analysis_commands.add_parser(
        "templates", help="Read Analysis template subjects or template rows."
    )
    analysis_templates.add_argument(
        "--kind", required=True, choices=sorted(ANALYSIS_TEMPLATE_OPERATIONS)
    )
    _add_input(analysis_templates)
    _add_all_pages(analysis_templates)
    analysis_auxiliary = analysis_commands.add_parser(
        "auxiliary", help="Read hidden properties or task event catalogs."
    )
    analysis_auxiliary.add_argument(
        "--kind", required=True, choices=sorted(ANALYSIS_AUXILIARY_OPERATIONS)
    )
    _add_input(analysis_auxiliary, required=True)
    _add_all_pages(analysis_auxiliary)
    analysis_detail = analysis_commands.add_parser(
        "detail", help="Read order, monetization, user, event, or postback detail."
    )
    analysis_detail.add_argument(
        "--kind", required=True, choices=sorted(ANALYSIS_DETAIL_OPERATIONS)
    )
    analysis_detail.add_argument(
        "--fields",
        action="append",
        help="Comma-separated contracted response fields; may be repeated.",
    )
    _add_input(analysis_detail, required=True)
    _add_all_pages(analysis_detail)

    multidim = commands.add_parser("multidim")
    multidim_commands = multidim.add_subparsers(dest="multidim_command", required=True)
    templates = multidim_commands.add_parser("templates")
    template_commands = templates.add_subparsers(dest="template_command", required=True)
    template_list = template_commands.add_parser("list")
    template_list.add_argument(
        "--scope", choices=sorted(MULTIDIM_TEMPLATE_SCOPES), default="preset"
    )
    _add_input(template_list)
    _add_all_pages(template_list)
    template_get = template_commands.add_parser("get")
    _add_input(template_get)
    multidim_metadata = multidim_commands.add_parser("metadata")
    _add_input(multidim_metadata)
    multidim_query = multidim_commands.add_parser("query")
    add_cli_query_arguments(
        multidim_query, _add_input, _add_all_pages, _add_query_shortcuts
    )
    multidim_total = multidim_commands.add_parser("calc-total")
    _add_input(multidim_total)
    _add_query_shortcuts(multidim_total)

    promotion = commands.add_parser("promotion")
    promotion_commands = promotion.add_subparsers(
        dest="promotion_command", required=True
    )
    promotion_commands.add_parser("platforms")
    promotion_query = promotion_commands.add_parser("query")
    promotion_query.add_argument(
        "--platform", required=True, choices=sorted(PROMOTION_PLATFORMS)
    )
    promotion_query.add_argument("--level")
    _add_input(promotion_query)
    _add_all_pages(promotion_query)
    _add_query_shortcuts(promotion_query)
    promotion_snapshot = promotion_commands.add_parser("snapshot")
    promotion_snapshot.add_argument(
        "--platform", required=True, choices=("all", *sorted(PROMOTION_PLATFORMS))
    )
    promotion_snapshot.add_argument("--level")
    promotion_snapshot.add_argument("--concurrency", type=_concurrency, default=6)
    _add_input(promotion_snapshot)
    _add_query_shortcuts(promotion_snapshot)

    business = commands.add_parser("business-report")
    business_commands = business.add_subparsers(dest="business_command", required=True)
    business_query = business_commands.add_parser("query")
    _add_input(business_query)
    _add_all_pages(business_query)

    objects = commands.add_parser("objects")
    object_commands = objects.add_subparsers(dest="objects_command", required=True)
    objects_list = object_commands.add_parser("list")
    _add_input(objects_list)
    _add_all_pages(objects_list)

    materials = commands.add_parser("materials")
    material_commands = materials.add_subparsers(
        dest="materials_command", required=True
    )
    for name in ("list", "tags", "reviews"):
        item = material_commands.add_parser(name)
        _add_input(item)
        _add_all_pages(item)

    attribution = commands.add_parser("attribution")
    attribution_commands = attribution.add_subparsers(
        dest="attribution_command", required=True
    )
    for name in ("status", "maps"):
        item = attribution_commands.add_parser(name)
        _add_input(item)
        _add_all_pages(item)
    add_snapshot_command(attribution_commands, _concurrency)
    add_find_command(commands, _operation_limit)
    add_recipe_commands(commands)
    return parser


def _client(args: argparse.Namespace):
    if bool(getattr(args, "allow_experimental", False)):
        return runtime.build_client(allow_experimental=True)
    return runtime.build_client()


def _enforce_output_policy(args: argparse.Namespace) -> None:
    if not bool(getattr(args, "all_pages", False)):
        return
    if getattr(args, "output", None) or getattr(args, "format", "json") == "ndjson":
        return
    raise InputValidationError(
        "--all-pages requires --output <path> or --format ndjson",
        field="all_pages",
        next_action=(
            "Retry with `--output <path>` for JSON or `--format ndjson` for a stream."
        ),
    )


def _domain_read(
    args: argparse.Namespace,
    command_key: str,
    *,
    read_all: bool | None = None,
) -> Any:
    client = _client(args)
    operation_id = runtime.resolve_operation_id(client, DOMAIN_OPERATIONS[command_key])
    all_pages = (
        bool(args.all_pages)
        if read_all is None and hasattr(args, "all_pages")
        else bool(read_all)
    )
    return runtime.call_read(
        client,
        operation_id,
        _object_input(args.input),
        read_all=all_pages,
        **_page_options(args, all_pages=all_pages, active=all_pages),
    )


def _split_values(values: Sequence[str] | None) -> list[str] | None:
    if not values:
        return None
    result = [
        part.strip() for value in values for part in value.split(",") if part.strip()
    ]
    return result or None


def _merge_query_shortcuts(
    client: Any,
    operation_id: str,
    args: argparse.Namespace,
    supplied: Mapping[str, Any],
    *,
    strict: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    schema = runtime.to_jsonable(client.schema(operation_id))
    fields = schema.get("input_fields", {}) if isinstance(schema, Mapping) else {}
    allowed = set(fields) if isinstance(fields, Mapping) else set()
    unknown = sorted(set(supplied) - allowed)
    if unknown and strict:
        raise ValueError(
            f"{operation_id} does not accept input fields: " + ", ".join(unknown)
        )
    result = {key: value for key, value in supplied.items() if key in allowed}
    ignored: list[str] = []
    if not strict:
        ignored.extend(f"input:{key}" for key in unknown)

    def assign(flag: str, candidates: Sequence[str], value: Any) -> None:
        if value is None:
            return
        target = next((name for name in candidates if name in allowed), None)
        if target:
            result[target] = value
        elif strict:
            raise ValueError(
                f"{operation_id} does not accept --{flag.replace('_', '-')}"
            )
        else:
            ignored.append(flag)

    app_id = getattr(args, "app_id", None)
    media = getattr(args, "media", None)
    if operation_id in _MULTIDIM_QUERY_OPERATIONS:
        filters = _without_filter(result.get("filters", []), "app_id", app_id is not None)
        if app_id is not None:
            filters.append(
                {"field": "app_id", "operator": "EQUALS", "values": [str(app_id)]}
            )
        if media is not None:
            filters.append(
                {"field": "click_company", "operator": "IN", "values": [media]}
            )
        if app_id is not None or media is not None:
            result["filters"] = filters
    else:
        if app_id is not None and "app_id" in allowed:
            result["app_id"] = str(app_id)
        elif app_id is not None and _accepts_array_field(fields, "filters"):
            filters = _without_filter(result.get("filters", []), "app_id")
            filters.append(
                {
                    "field": "app_id",
                    "operator": PROMOTION_EQUALS_OPERATOR,
                    "values": [str(app_id)],
                }
            )
            result["filters"] = filters
        elif app_id is not None and strict:
            raise ValueError(f"{operation_id} does not accept --app-id")
        elif app_id is not None:
            ignored.append("app_id")
        assign("media", ("media_type", "media"), media)
    start, end = getattr(args, "start", None), getattr(args, "end", None)
    validate_date_pair(start, end)
    assign("start/end", ("date_list",), _date_range_input(operation_id, start if start and end else None, end))
    time_dims = _split_values(getattr(args, "time_dim", None))
    if time_dims and len(time_dims) != 1:
        raise ValueError("--time-dim accepts exactly one value")
    assign("time_dim", ("time_dims",), time_dims[0] if time_dims else None)
    assign(
        "dimensions",
        ("data_dims", "dims_list"),
        _split_values(getattr(args, "dimensions", None)),
    )
    assign(
        "metrics",
        ("metrics_list", "query_fields"),
        _split_values(getattr(args, "metrics", None)),
    )
    assign("multi_days", ("multi_keys",), parse_multi_days(_split_values(getattr(args, "multi_days", None))))
    parent = getattr(args, "parent_id", None)
    if parent is not None:
        direct = next(
            (
                name
                for name in (
                    "parent_id",
                    "advertiser_id",
                    "account_id",
                    "campaign_id",
                    "group_id",
                    "developer_id",
                )
                if name in allowed
            ),
            None,
        )
        filter_field = PROMOTION_PARENT_FILTER_FIELDS.get(operation_id)
        if direct:
            result[direct] = str(parent)
        elif filter_field and _accepts_array_field(fields, "filters"):
            filters = _without_filter(result.get("filters", []), filter_field)
            filters.append(
                {
                    "field": filter_field,
                    "operator": PROMOTION_EQUALS_OPERATOR,
                    "values": [str(parent)],
                }
            )
            result["filters"] = filters
        elif strict:
            raise ValueError(f"{operation_id} does not accept --parent-id")
        else:
            ignored.append("parent_id")
    return result, ignored


def _accepts_array_field(fields: Any, name: str) -> bool:
    if not isinstance(fields, Mapping):
        return False
    spec = fields.get(name)
    return isinstance(spec, Mapping) and spec.get("type") == "array"


def _multidim_metadata(args: argparse.Namespace) -> Any:
    client = _client(args)
    supplied = _object_input(args.input)
    requests: list[dict[str, Any]] = []
    for operation_id in MULTIDIM_METADATA_OPERATIONS:
        per_operation = supplied.get(
            operation_id, supplied.get(operation_id.rsplit(".", 2)[-2], {})
        )
        if not isinstance(per_operation, Mapping):
            raise ValueError(f"metadata input for {operation_id} must be an object")
        requests.append(
            {
                "operation_id": operation_id,
                "inputs": dict(per_operation),
                "read_all": True,
            }
        )
    return runtime.call_batch(client, requests)


def _analysis(args: argparse.Namespace) -> Any:
    if args.analysis_command == "metadata":
        return run_analysis_metadata(args, _client, _object_input)
    if args.analysis_command == "query":
        return run_analysis_query_command(args, runtime.build_client, _object_input, _merge_query_shortcuts, runtime.call_read)

    supplied = _object_input(args.input)
    if args.analysis_command == "segments":
        operation_id = DOMAIN_OPERATIONS["analysis.segments"][0]
    elif args.analysis_command == "segment":
        operation_id = ANALYSIS_SEGMENT_OPERATIONS[args.kind]
    elif args.analysis_command == "report-config":
        operation_id = ANALYSIS_REPORT_CONFIG_OPERATIONS[args.kind]
    elif args.analysis_command == "dashboard":
        operation_id = ANALYSIS_DASHBOARD_OPERATIONS[args.kind]
    elif args.analysis_command == "values":
        operation_id = ANALYSIS_VALUE_OPERATIONS[args.kind]
    elif args.analysis_command == "users":
        operation_id = ANALYSIS_DIRECTORY_OPERATIONS["users"]
    elif args.analysis_command == "templates":
        operation_id = ANALYSIS_TEMPLATE_OPERATIONS[args.kind]
    elif args.analysis_command == "auxiliary":
        operation_id = ANALYSIS_AUXILIARY_OPERATIONS[args.kind]
    else:
        operation_id = ANALYSIS_DETAIL_OPERATIONS[args.kind]
        selected_fields = _split_values(args.fields)
        if selected_fields is not None:
            supplied["fields"] = selected_fields
        if args.kind == "user-event" and bool(getattr(args, "all_pages", False)):
            raise ValueError(
                "analysis user-event has no upstream page_info contract; "
                "read one page at a time with explicit page/page_size until "
                "event_timeline[*].list is empty"
            )

    read_all = bool(getattr(args, "all_pages", False))
    if read_all and operation_id not in ANALYSIS_PAGINATED_OPERATIONS:
        raise ValueError(
            f"--all-pages is not supported for non-paginated operation {operation_id}"
        )

    client = runtime.build_client()
    schema = client.schema(operation_id)
    stability = (
        schema.get("stability", "stable") if isinstance(schema, Mapping) else "stable"
    )
    if stability != "stable":
        if not bool(getattr(args, "experimental", False)):
            raise ValueError(
                "experimental analysis reads require explicit --experimental"
            )
        client = runtime.build_client(allow_experimental=True)

    if args.analysis_command == "segments":
        supplied["app_id"] = str(args.app_id)
    return runtime.call_read(
        client,
        operation_id,
        supplied,
        read_all=read_all,
        **_page_options(args, all_pages=True, active=read_all),
    )


def _apps_or_metadata(args: argparse.Namespace) -> Any:
    if args.command == "apps":
        return _domain_read(args, "apps.list")
    if args.command == "find":
        return run_find_command(args, _client(args))
    return run_metadata_command(args, _client)


def _promotion(args: argparse.Namespace) -> Any:
    if args.promotion_command == "platforms":
        client = _client(args)
        available = runtime.operation_ids(client.operations())
        return {
            "platforms": [
                {
                    "platform": platform,
                    "levels": {
                        level: operation_id
                        for level, operation_id in levels.items()
                        if not available or operation_id in available
                    },
                }
                for platform, levels in PROMOTION_PLATFORMS.items()
            ]
        }
    client = _client(args)
    if args.promotion_command == "snapshot" and args.platform == "all":
        if args.level is not None:
            raise ValueError("--level cannot be combined with --platform all")
        supplied = _object_input(args.input)
        requests: list[dict[str, Any]] = []
        ignored: dict[str, list[str]] = {}
        for platform, operation_id in PROMOTION_PRIMARY_OPERATIONS.items():
            inputs, skipped = _merge_query_shortcuts(
                client, operation_id, args, supplied, strict=False
            )
            requests.append(
                {"operation_id": operation_id, "inputs": inputs, "read_all": True}
            )
            if skipped:
                ignored[platform] = skipped
        results = runtime.call_batch(client, requests, concurrency=args.concurrency)
        return {
            "platform_count": len(requests),
            "concurrency": args.concurrency,
            "ignored_shortcuts": ignored,
            "results": results,
        }
    operation_id = promotion_operation(args.platform, args.level)
    operation_id = runtime.resolve_operation_id(client, operation_id)
    inputs, _ = _merge_query_shortcuts(
        client, operation_id, args, _object_input(args.input)
    )
    read_all = args.promotion_command == "snapshot" or bool(
        getattr(args, "all_pages", False)
    )
    return runtime.call_read(
        client,
        operation_id,
        inputs,
        read_all=read_all,
        **_page_options(
            args,
            all_pages=True,
            active=bool(getattr(args, "all_pages", False)),
        ),
    )


def _attribution(args: argparse.Namespace) -> Any:
    client = _client(args)
    supplied = _object_input(args.input)
    if args.attribution_command == "maps":
        operation_id = runtime.resolve_operation_id(
            client, DOMAIN_OPERATIONS["attribution.maps"]
        )
        return runtime.call_read(
            client,
            operation_id,
            supplied,
            read_all=bool(args.all_pages),
            **_page_options(args, all_pages=True, active=bool(args.all_pages)),
        )
    requests = [
        {"operation_id": operation_id, "inputs": dict(supplied)}
        for operation_id in ATTRIBUTION_STATUS_OPERATIONS
    ]
    return runtime.call_batch(client, requests)


def _doctor(args: argparse.Namespace) -> Any:
    local = runtime.validate_manifest_json()
    client = _client(args)
    operations = client.operations()
    operation_ids = runtime.operation_ids(operations)
    result: dict[str, Any] = {
        "status": "pass",
        "live": False,
        **local,
        "registered_operations": len(operation_ids),
        "auth": runtime.credential_status(),
    }
    if args.live:
        if callable(getattr(client, "probe_all", None)):
            probes = client.probe_all(max_workers=args.concurrency)
            coverage = probes.get("coverage", {}) if isinstance(probes, Mapping) else {}
            probe_status = (
                str(probes.get("status", "error"))
                if isinstance(probes, Mapping)
                else "error"
            )
            result.update(
                {
                    "status": "pass"
                    if probe_status in {"success", "empty"}
                    else "partial",
                    "live": True,
                    "probe_status": probe_status,
                    "probes_run": probes.get("probed", 0)
                    if isinstance(probes, Mapping)
                    else 0,
                    "coverage": coverage,
                }
            )
            return result
        operation_id = runtime.resolve_operation_id(
            client, DOMAIN_OPERATIONS["apps.list"]
        )
        schema = runtime.to_jsonable(client.schema(operation_id))
        live_probe = schema.get("live_probe", {}) if isinstance(schema, Mapping) else {}
        if not isinstance(live_probe, Mapping):
            raise ValueError(f"{operation_id} has an invalid live probe contract")
        probe_inputs = live_probe.get("inputs", live_probe.get("input", {}))
        if not isinstance(probe_inputs, Mapping):
            raise ValueError(f"{operation_id} live probe inputs must be an object")
        runtime.call_read(client, operation_id, dict(probe_inputs), read_all=False)
        result.update(
            {"live": True, "probe_operation_id": operation_id, "probe_succeeded": True}
        )
    return result


def _auth_or_parents(args: argparse.Namespace) -> Any:
    if args.command == "parents":
        return run_parent_command(args, _client)
    return runtime.credential_status() if args.auth_command == "status" else runtime.refresh_credentials()


def _run_discovery(args: argparse.Namespace) -> Any:
    if args.command == "agent":
        return run_agent_command(args, DeferredAgentClient(lambda: _client(args)))
    return run_operation_command(args, _client(args), filter_operations)


def run(args: argparse.Namespace) -> Any:
    _enforce_output_policy(args)
    if args.dry_run:
        if args.command:
            raise ValueError("--dry-run cannot be combined with a command")
        checks = runtime.validate_manifest_json()
        client = _client(args)
        operations = client.operations(stability=None)
        operation_ids = runtime.operation_ids(operations)
        if not operation_ids:
            raise ValueError("core registry returned no operations")
        for operation_id in sorted(operation_ids):
            client.schema(operation_id)
        return {
            "status": "pass",
            "offline": True,
            "network_called": False,
            "core_registry_validated": True,
            "registered_operations": len(operation_ids),
            **checks,
        }
    if args.command in {"operations", "agent"}:
        return _run_discovery(args)
    if args.command == "validate":
        return _client(args).validate(
            args.operation_id,
            _object_input(args.input),
            render_wire=args.render_wire,
        )
    if args.command == "batch":
        result = run_batch_command(
            args, _client, _load_json_input, runtime.call_batch,
            DOMAIN_OPERATIONS["apps.list"][0],
        )
        batch_command = args.batch_command
        expected_schema = batch_schema_version(args)
        if not isinstance(result, Mapping): raise RuntimeError("batch command returned a non-object envelope")
        if result.get("schema_version") != expected_schema: raise RuntimeError("batch command returned the wrong public schema")
        if batch_command in {"read", "run"} and "exit_code" not in result: raise RuntimeError("batch execution omitted its aggregate exit code")
        return result
    if args.command in {"auth", "parents"}:
        return _auth_or_parents(args)
    if args.command == "doctor":
        return _doctor(args)
    if args.command in {"apps", "metadata", "find"}:
        return _apps_or_metadata(args)
    if args.command == "analysis":
        return _analysis(args)
    if args.command == "multidim":
        if args.multidim_command == "metadata":
            return _multidim_metadata(args)
        if args.multidim_command == "templates":
            key = (
                f"multidim.templates.{args.scope}"
                if args.template_command == "list"
                else "multidim.templates.get"
            )
            return _domain_read(args, key)
        key = (
            "multidim.query"
            if args.multidim_command == "query"
            else "multidim.calc_total"
        )
        client = _client(args)
        operation_id = runtime.resolve_operation_id(client, DOMAIN_OPERATIONS[key])
        inputs, _ = _merge_query_shortcuts(
            client, operation_id, args, _object_input(args.input)
        )
        return call_cli_read(
            client,
            operation_id,
            inputs,
            include_total=bool(getattr(args, "include_total", False)), read_all=bool(getattr(args, "all_pages", False)),
            **_page_options(
                args,
                all_pages=True,
                active=bool(getattr(args, "all_pages", False)),
            ),
        )
    if args.command == "promotion":
        return _promotion(args)
    if args.command == "business-report":
        return _domain_read(args, "business_report.query")
    if args.command == "objects":
        return _domain_read(args, "objects.list")
    if args.command == "materials":
        return _domain_read(args, f"materials.{args.materials_command}")
    if args.command == "attribution":
        return _attribution(args)
    raise ValueError("choose --dry-run or a command")


def _summary_reference(operation_id: str | None, path: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bytes):
        encoded = value
        value_type = "binary"
    else:
        encoded = json.dumps(
            runtime.to_jsonable(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        value_type = type(value).__name__
    return {
        "summary": {
            "type": value_type,
            "size_bytes": len(encoded),
            "sha256": hashlib.sha256(encoded).hexdigest(),
        },
        "reference": {
            "kind": "response_field",
            "operation_id": operation_id,
            "json_path": path,
            "retrieve": "rerun the command with `--output <path>`",
        },
    }


def _safe_stdout_value(
    value: Any,
    *,
    operation_id: str | None,
    path: str = "$",
    parent_key: str | None = None,
    summarized: list[str] | None = None,
) -> Any:
    summarized = summarized if summarized is not None else []
    value = runtime.to_jsonable(value)
    if isinstance(value, bytes):
        summarized.append(path)
        return _summary_reference(operation_id, path, value)
    if isinstance(value, str) and len(value.encode("utf-8")) > _LARGE_VALUE_BYTES:
        summarized.append(path)
        return _summary_reference(operation_id, path, value)
    if isinstance(value, Mapping):
        encoded_size = None
        if parent_key and parent_key.casefold() in {
            "config",
            "ui_config",
            "extra_data",
            "opaque_json",
            "binary",
            "blob",
        }:
            try:
                encoded_size = len(
                    json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode(
                        "utf-8"
                    )
                )
            except (TypeError, ValueError):
                encoded_size = _LARGE_VALUE_BYTES + 1
        if encoded_size is not None and encoded_size > _LARGE_VALUE_BYTES:
            summarized.append(path)
            return _summary_reference(operation_id, path, value)
        return {
            str(key): _safe_stdout_value(
                item,
                operation_id=operation_id,
                path=f"{path}.{key}",
                parent_key=str(key),
                summarized=summarized,
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        rows = list(value)
        if len(rows) > DEFAULT_STDOUT_MAX_ITEMS:
            summarized.append(path)
            rows = rows[:DEFAULT_STDOUT_MAX_ITEMS]
        return [
            _safe_stdout_value(
                item,
                operation_id=operation_id,
                path=f"{path}[{index}]",
                parent_key=parent_key,
                summarized=summarized,
            )
            for index, item in enumerate(rows)
        ]
    return value


def _safe_stdout_result(result: Any) -> Any:
    operation_id = (
        str(result.get("operation_id"))
        if isinstance(result, Mapping) and result.get("operation_id")
        else None
    )
    summarized: list[str] = []
    safe = _safe_stdout_value(
        result, operation_id=operation_id, summarized=summarized
    )
    if summarized and isinstance(safe, Mapping):
        safe = dict(safe)
        safe["truncated"] = True
        safe.setdefault("next_page_input", None)
        safe["summarized_fields"] = sorted(set(summarized))
    return safe


def _ndjson_rows(result: Any) -> tuple[list[Any], dict[str, Any]]:
    value = runtime.to_jsonable(result)
    rows: Any = None
    if isinstance(value, list):
        rows = value
    elif isinstance(value, Mapping):
        data = value.get("data")
        if isinstance(data, list):
            rows = data
        elif isinstance(data, Mapping):
            rows = data.get("list", data.get("items"))
        elif value.get("schema_version") == "gravity.agent.v1" and isinstance(
            value.get("candidates"), list
        ):
            rows = value["candidates"]
    if not isinstance(rows, list):
        rows = [value]
    metadata = {
        "schema_version": "gravity-insight.ndjson-meta.v1",
        "operation_id": value.get("operation_id") if isinstance(value, Mapping) else None,
        "status": value.get("status") if isinstance(value, Mapping) else "success",
        "truncated": value.get("truncated", False) if isinstance(value, Mapping) else False,
        "next_page_input": value.get("next_page_input") if isinstance(value, Mapping) else None,
        "total": value.get("total") if isinstance(value, Mapping) else None,
        "rows_written": len(rows),
    }
    metadata.update(ndjson_metadata(value))
    return rows, metadata


def _iter_ndjson_lines(result: Any):
    if isinstance(result, Mapping) and result.get("schema_version") == "gravity.agent-batch.v1":
        from gravity_sdk.agent_batch import iter_ndjson_records
        for record in iter_ndjson_records(result):
            yield json.dumps(_redact(record), ensure_ascii=False, sort_keys=True)
        return
    rows, metadata = _ndjson_rows(result)
    for row in rows:
        yield json.dumps(
            _redact(_safe_stdout_result(row)), ensure_ascii=False, sort_keys=True
        )
    yield json.dumps(
        {"_gravity_insight": metadata}, ensure_ascii=False, sort_keys=True
    )


def _render_ndjson(result: Any) -> str:
    return "\n".join(_iter_ndjson_lines(result)) + "\n"


def _emit_success(args: argparse.Namespace, result: Any) -> None:
    output = output_argument(args)
    output_format = getattr(args, "format", "json")
    if output:
        if output == "-":
            raise InputValidationError(
                "--output must be a file path; use --format ndjson for stdout",
                field="output",
            )
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        if output_format == "ndjson":
            rendered = _render_ndjson(result)
        else:
            rendered = json.dumps(
                _redact(result), ensure_ascii=False, indent=2, sort_keys=True
            ) + "\n"
        path.write_text(rendered, encoding="utf-8")
        _write_json(
            {
                "ok": True,
                "status": "written",
                "output": str(path),
                "format": output_format,
                "size_bytes": len(rendered.encode("utf-8")),
            }
        )
        return
    if output_format == "ndjson":
        for line in _iter_ndjson_lines(result):
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
        return
    _write_json(_safe_stdout_result(result))


def main(argv: Sequence[str] | None = None) -> int:
    args: argparse.Namespace | None = None
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        result = dispatch_command(args, _client, _object_input, nonempty_cli.runner(_object_input, run))
        if isinstance(result, Mapping) and type(result.get("exit_code")) is int:
            _emit_success(args, result)
            return int(result.get("exit_code", 4))
        if isinstance(result, Mapping) and result.get("ok") is False:
            stream = (
                sys.stdout
                if result.get("schema_version") == "gravity-insight.validation.v1"
                else sys.stderr
            )
            _write_json(result, stream=stream)
            return envelope_exit_code(result)
        _emit_success(args, result)
        return 0
    except (GravityInsightError, OSError, RuntimeError, ValueError, TypeError) as exc:
        envelope, exit_code = command_error(args, exc)
        _write_json(envelope, stream=sys.stderr)
        return exit_code
