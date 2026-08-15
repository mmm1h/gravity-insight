"""Command-line interface for the read-only Gravity Insight SDK."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from typing import Any, Mapping, Sequence

from gravity_sdk.domains import (
    ANALYSIS_AUXILIARY_OPERATIONS,
    ANALYSIS_DETAIL_OPERATIONS,
    ANALYSIS_DIRECTORY_OPERATIONS,
    ANALYSIS_PAGINATED_OPERATIONS,
    ANALYSIS_REPORT_CONFIG_OPERATIONS,
    ANALYSIS_TEMPLATE_OPERATIONS,
    ANALYSIS_VALUE_OPERATIONS,
    ATTRIBUTION_STATUS_OPERATIONS,
    DOMAIN_OPERATIONS,
)
from gravity_sdk import json_output, nonempty_cli, runtime
from gravity_sdk.cli_limits import (
    agent_limit as _agent_limit,
    operation_limit as _operation_limit,
    concurrency as _concurrency,
    positive_int as _positive_int,
)
from gravity_sdk.pagination_cli import (
    DEFAULT_STDOUT_MAX_ITEMS,
    DEFAULT_STDOUT_MAX_PAGES,
    add_pagination_arguments as _add_all_pages,
    page_options as _page_options,
)
from gravity_sdk import result_output
from gravity_sdk.credential_sanitization import sanitize_credentials as _sanitize_credentials

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

from gravity_sdk.parents import add_parent_commands, run_parent_command
from gravity_sdk.attribution import add_snapshot_command
from gravity_sdk.analysis_spec_cli import run_analysis_query_command
from gravity_sdk.analysis_query_batch_cli import add_analysis_query_commands
from gravity_sdk.segment_spec_cli import add_segment_commands, run_segment_command
from gravity_sdk.business_pulse_cli import add_business_pulse_command
from gravity_sdk.material_cli import add_material_commands, dispatch_material_command
from gravity_sdk.promotion_cli import (
    add_promotion_commands,
    add_query_shortcuts as _add_query_shortcuts,
    dispatch_promotion_command,
    merge_query_shortcuts as _merge_query_shortcuts,
    split_values as _split_values,
)
from gravity_sdk.dashboard_snapshot_cli import add_dashboard_commands
from gravity_sdk.saved_analysis_cli import add_saved_analysis_commands
from gravity_sdk.multidim_cli import add_multidim_commands, multidim_ndjson_view
from gravity_sdk.user_journey_cli import add_user_journey_command
from gravity_sdk.metadata_sync import (
    add_metadata_commands,
    run_analysis_metadata,
    run_metadata_command,
)
from gravity_sdk.find import (
    add_find_command,
    filter_operations,
    run_find_command,
    run_operation_command,
)
from gravity_sdk.find_input import (
    add_input as _add_input,
    load_json_input as _load_json_input,
    normalize_input_arguments as _normalize_input_arguments,
    object_input as _object_input,
)
from gravity_sdk.recipe import add_recipe_commands
from gravity_sdk.resolver_cli import add_resolver_command
from gravity_sdk.agent import DeferredAgentClient, ndjson_metadata, run_agent_command
from gravity_sdk.capability_cli import add_deepening_commands
from gravity_sdk.read_cli import add_read_command
from gravity_sdk.cli_root_commands import add_root_commands
from gravity_sdk.plan_cli import add_plan_commands
from gravity_sdk.plan_product_cli import dispatch as dispatch_plan


_LARGE_VALUE_BYTES = 8_192
_ANALYSIS_QUERY_COMMAND = "query"


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


def _write_json(value: Any, *, stream=None) -> None:
    print(
        json_output.dumps(
            _sanitize_credentials(value), ensure_ascii=False, indent=2, sort_keys=True
        ),
        file=stream or sys.stdout,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = AgentArgumentParser(prog="gravity", description="Governed Gravity Insight read and export operations.")
    parser.set_defaults(network_required=True)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run offline smoke checks; never call Gravity.",
    )
    commands = parser.add_subparsers(dest="command")

    add_root_commands(commands, _agent_limit, _operation_limit, _positive_int, _client)

    add_plan_commands(commands, _concurrency, _add_input, handler=dispatch_plan)

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

    add_material_commands(
        commands, _add_input, _add_all_pages, _concurrency, _positive_int
    )

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
    add_analysis_query_commands(
        analysis_commands, _add_input, _add_query_shortcuts, _concurrency
    )
    add_user_journey_command(analysis_commands, _concurrency, _positive_int)
    add_segment_commands(analysis_commands, _add_input, _add_all_pages)
    analysis_report_config = analysis_commands.add_parser(
        "report-config", help="List or read a saved Analysis configuration."
    )
    analysis_report_config.add_argument(
        "--kind", required=True, choices=sorted(ANALYSIS_REPORT_CONFIG_OPERATIONS)
    )
    _add_input(analysis_report_config, required=True)
    _add_all_pages(analysis_report_config)
    add_dashboard_commands(
        analysis_commands, _add_input, _add_all_pages, _concurrency, _positive_int
    )
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

    add_multidim_commands(
        commands,
        _add_input,
        _add_all_pages,
    )

    add_promotion_commands(
        commands, _add_input, _add_all_pages, _concurrency, _positive_int
    )

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
    if bool(getattr(args, "multidim_dry_run", False)) or bool(
        getattr(args, "multidim_input_schema", False)
    ):
        return
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


def _analysis(args: argparse.Namespace) -> Any:
    if args.analysis_command == "metadata":
        return run_analysis_metadata(args, _client, _object_input)
    if args.analysis_command == _ANALYSIS_QUERY_COMMAND:
        return run_analysis_query_command(args, runtime.build_client, _object_input, _merge_query_shortcuts, runtime.call_read)
    if args.analysis_command == "segment":
        return run_segment_command(
            args, runtime.build_client, _object_input, runtime.call_read
        )

    supplied = _object_input(args.input)
    if args.analysis_command == "segments":
        operation_id = DOMAIN_OPERATIONS["analysis.segments"][0]
    elif args.analysis_command == "report-config":
        operation_id = ANALYSIS_REPORT_CONFIG_OPERATIONS[args.kind]
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
    if args.command == "promotion":
        return dispatch_promotion_command(args, _object_input)
    if args.command == "business-report":
        return _domain_read(args, "business_report.query")
    if args.command == "objects":
        return _domain_read(args, "objects.list")
    if args.command == "materials":
        return dispatch_material_command(args, _object_input)
    if args.command == "attribution":
        return _attribution(args)
    raise ValueError("choose --dry-run or a command")


def _summary_reference(operation_id: str | None, path: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bytes):
        encoded = value
        value_type = "binary"
    else:
        encoded = json_output.dumps(
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
                    json_output.dumps(
                        value, ensure_ascii=False, separators=(",", ":")
                    ).encode("utf-8")
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
        data, multidim_metadata = multidim_ndjson_view(value)
        if isinstance(data, list):
            rows = data
        elif isinstance(data, Mapping):
            rows = data.get("list", data.get("items", data.get("candidates")))
    if not isinstance(rows, list):
        rows = [value]
    metadata = {
        "schema_version": "gravity-insight.ndjson-meta.v1", "result_source": value.get("result_source") if isinstance(value, Mapping) else None,
        "operation_id": value.get("operation_id") if isinstance(value, Mapping) else None, "status": value.get("status") if isinstance(value, Mapping) else "success",
        "truncated": value.get("truncated", False) if isinstance(value, Mapping) else False,
        "next_page_input": value.get("next_page_input") if isinstance(value, Mapping) else None,
        "total": value.get("total", value.get("count")) if isinstance(value, Mapping) else None,
        "rows_written": len(rows),
    }
    metadata.update({**ndjson_metadata(value), **(multidim_metadata if isinstance(value, Mapping) else {})})
    return rows, metadata


def _iter_ndjson_lines(result: Any):
    if isinstance(result, Mapping) and result.get("schema_version") == "gravity.agent-batch.v1":
        from gravity_sdk.agent_batch import iter_ndjson_records
        for record in iter_ndjson_records(result):
            yield json_output.dumps(
                _sanitize_credentials(record), ensure_ascii=False, sort_keys=True
            )
        return
    rows, metadata = _ndjson_rows(result)
    for row in rows:
        yield json_output.dumps(
            _sanitize_credentials(_safe_stdout_result(row)),
            ensure_ascii=False,
            sort_keys=True,
        )
    yield json_output.dumps(
        _sanitize_credentials({"_gravity_insight": metadata}),
        ensure_ascii=False,
        sort_keys=True,
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
        if output_format == "ndjson":
            rendered = _render_ndjson(result)
        else:
            rendered = json_output.dumps(
                _sanitize_credentials(result),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ) + "\n"
        _write_json(result_output.write_rendered_result(
            output, rendered, output_format=output_format
        ))
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
        if (
            output_argument(args)
            and bool(getattr(args, "result_output_fail_closed", False))
            and not result_output.result_is_persistable(result)
        ):
            _write_json(result, stream=sys.stderr)
            return result_output.terminal_result_exit_code(result)
        if isinstance(result, Mapping) and type(result.get("exit_code")) is int:
            _emit_success(args, result)
            return int(result["exit_code"])
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
