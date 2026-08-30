"""Stable attribution configuration and performance products."""

from __future__ import annotations

import copy
from datetime import date
from typing import Any, Callable, Mapping

from . import runtime
from .domains import (
    ATTRIBUTION_PAGINATED_OPERATIONS,
    ATTRIBUTION_SNAPSHOT_OPERATIONS,
)
from .composite_batch import (
    annotate_result,
    composite_envelope,
    enforce_composite_item_budget,
    ordered_results,
    validate_composite_bounds,
)
from .composite_catalog import stable_operation
from .actionable_error_values import actual_value
from .errors import InputValidationError
from .attribution_user_detail import (
    OPERATION_ID as USER_DETAIL_OPERATION_ID,
    SCHEMA_VERSION as USER_DETAIL_SCHEMA_VERSION,
    TESTING_DEVICE_OPERATION_ID,
    read_user_detail as attribution_user_detail,
    result as attribution_user_detail_result,
    validate_request as validate_attribution_user_detail_request,
)
from .workspace import load_workspace
from .workspace_app import resolve_workspace_app


SCHEMA_VERSION = "gravity-insight.attribution-snapshot.v1"
PERFORMANCE_SCHEMA_VERSION = "gravity-insight.attribution-performance.v1"
PERFORMANCE_OPERATION_ID = stable_operation(
    "attribution", "attribution", action="query"
).operation_id
PERFORMANCE_PROFILES = (
    (
        "attributed_registrations",
        ("AppRealRegisterCnt",),
        ("date", "ad_platform"),
        "user_activated_time",
    ),
    (
        "activation_and_pay",
        ("AppActivateStandard", "AppGamePayAmountReportingStandard"),
        ("date", "ad_platform"),
        "behavior_occurred_time",
    ),
    (
        "activation_conversion",
        ("AppActivateStandard", "AppActivateBuried", "AppActivateUploaded"),
        ("date",),
        "user_activated_time",
    ),
    (
        "overview",
        (
            "AdShow",
            "AdClick",
            "AppActivateStandard",
            "AppRegisterStandard",
            "AppGamePayUserCntStandard",
        ),
        ("date",),
        "user_activated_time",
    ),
)


def add_snapshot_command(
    subcommands: Any, concurrency_type: Callable[[str], int]
) -> None:
    snapshot = subcommands.add_parser(
        "snapshot",
        help="Read every stable attribution configuration for one app concurrently.",
    )
    app = snapshot.add_mutually_exclusive_group(required=True)
    app.add_argument("--app", help="Workspace app alias or literal app id.")
    app.add_argument("--app-id", help="Compatibility alias for --app.")
    snapshot.add_argument("--concurrency", type=concurrency_type, default=6)
    snapshot.set_defaults(_gravity_handler=_dispatch_snapshot)
    add_performance_command(subcommands, concurrency_type)
    add_user_detail_command(subcommands)


def add_performance_command(
    subcommands: Any, concurrency_type: Callable[[str], int]
) -> None:
    performance = subcommands.add_parser(
        "performance",
        help="Read the four governed attribution-performance panels.",
    )
    app = performance.add_mutually_exclusive_group(required=True)
    app.add_argument("--app", help="Workspace app alias or literal app id.")
    app.add_argument("--app-id", help="Compatibility alias for --app.")
    performance.add_argument("--start", required=True, help="Inclusive YYYY-MM-DD.")
    performance.add_argument("--end", required=True, help="Inclusive YYYY-MM-DD.")
    performance.add_argument("--concurrency", type=concurrency_type, default=4)
    performance.set_defaults(_gravity_handler=_dispatch_performance)


def add_user_detail_command(subcommands: Any) -> None:
    detail = subcommands.add_parser(
        "user-detail",
        help="Read one registered testing device's governed attribution detail.",
    )
    app = detail.add_mutually_exclusive_group(required=True)
    app.add_argument("--app", help="Workspace app alias or literal app id.")
    app.add_argument("--app-id", help="Compatibility alias for --app.")
    detail.add_argument(
        "--device-id",
        required=True,
        help="Internal row id selected from app.testing_tool.list.",
    )
    detail.set_defaults(_gravity_handler=_dispatch_user_detail)


def _dispatch_snapshot(args: Any, _object_input: Any) -> dict[str, Any]:
    workspace = load_workspace()
    selected = args.app if args.app is not None else args.app_id
    return attribution_snapshot(
        runtime.build_client(),
        resolve_workspace_app(workspace, selected),
        concurrency=args.concurrency,
    )


def _dispatch_performance(args: Any, _object_input: Any) -> dict[str, Any]:
    workspace = load_workspace()
    selected = args.app if args.app is not None else args.app_id
    return attribution_performance(
        runtime.build_client(),
        resolve_workspace_app(workspace, selected),
        args.start,
        args.end,
        max_workers=args.concurrency,
    )


def _dispatch_user_detail(args: Any, _object_input: Any) -> dict[str, Any]:
    workspace = load_workspace()
    selected = args.app if args.app is not None else args.app_id
    return attribution_user_detail(
        runtime.build_client(),
        resolve_workspace_app(workspace, selected),
        args.device_id,
    )


def attribution_snapshot(
    client: Any,
    app_id: str | int,
    *,
    concurrency: int = 6,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    normalized_app_id = _positive_app_id(app_id)
    pages, items = validate_composite_bounds(
        max_pages, max_items, minimum_items=len(ATTRIBUTION_SNAPSHOT_OPERATIONS)
    )
    requests = [
        {
            "operation_id": operation_id,
            "request_id": operation_id,
            "inputs": {"app_id": normalized_app_id},
            "read_all": operation_id in ATTRIBUTION_PAGINATED_OPERATIONS,
        }
        for operation_id in ATTRIBUTION_SNAPSHOT_OPERATIONS
    ]
    ordered = ordered_results(
        runtime.call_batch(
            client,
            requests,
            concurrency=concurrency,
            max_pages=pages,
            max_total_items=items,
        ),
        requests,
        component="attribution snapshot",
    )
    enforce_composite_item_budget(ordered, items)
    results = [
        annotate_result(result, source=operation_id, scope="app")
        for operation_id, result in zip(
            ATTRIBUTION_SNAPSHOT_OPERATIONS, ordered, strict=True
        )
    ]
    envelope = composite_envelope(results, schema_version=SCHEMA_VERSION)
    if envelope["total_count"] != len(requests):
        raise RuntimeError("attribution snapshot result count invariant failed")
    return {
        **envelope,
        "app_id": normalized_app_id,
        "operation_count": len(requests),
        "paginated_operation_count": len(ATTRIBUTION_PAGINATED_OPERATIONS),
    }


def attribution_performance(
    client: Any,
    app_id: str | int,
    start: str,
    end: str,
    *,
    max_workers: int = 4,
    max_pages: int = 1,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Read the four fixed front-end attribution aggregates for one App/window."""

    app, wire_app, date_range, workers, pages, items = validate_attribution_performance_request(
        app_id,
        start,
        end,
        max_workers=max_workers,
        max_pages=max_pages,
        max_items=max_items,
    )
    requests = [
        {
            "operation_id": PERFORMANCE_OPERATION_ID,
            "request_id": name,
            "inputs": {
                "app_id": wire_app,
                "date_list": list(date_range),
                "metrics_list": list(metrics),
                "dims_list": list(dimensions),
                "statistics_caliber": caliber,
            },
            "read_all": False,
        }
        for name, metrics, dimensions, caliber in PERFORMANCE_PROFILES
    ]
    ordered = ordered_results(
        runtime.call_batch(
            client,
            requests,
            concurrency=min(workers, len(requests)),
            max_pages=pages,
            max_total_items=items,
        ),
        requests,
        component="attribution performance",
    )
    ordered = [_normalize_explicit_empty(result) for result in ordered]
    enforce_composite_item_budget(ordered, items)
    results = [
        annotate_result(result, source=profile[0], scope="app")
        for profile, result in zip(PERFORMANCE_PROFILES, ordered, strict=True)
    ]
    envelope = composite_envelope(
        results,
        schema_version=PERFORMANCE_SCHEMA_VERSION,
        extra={
            "app_id": app,
            "date_range": list(date_range),
            "source_count": len(PERFORMANCE_PROFILES),
            "profiles": [
                {
                    "name": name,
                    "metrics": list(metrics),
                    "dimensions": list(dimensions),
                    "statistics_caliber": caliber,
                }
                for name, metrics, dimensions, caliber in PERFORMANCE_PROFILES
            ],
        },
    )
    if all(result.get("status") == "empty" for result in results) and envelope.get("ok") is True:
        envelope["status"] = "empty"
    return envelope


def validate_attribution_performance_request(
    app_id: str | int,
    start: str,
    end: str,
    *,
    max_workers: int = 4,
    max_pages: int = 1,
    max_items: int = 100_000,
) -> tuple[str, int, tuple[str, str], int, int, int]:
    app = _performance_app_id(app_id)
    window = _performance_date_range(start, end)
    if (
        isinstance(max_workers, bool)
        or not isinstance(max_workers, int)
        or not 1 <= max_workers <= 24
    ):
        raise _performance_input_error(
            "attribution performance max_workers has an invalid actual value; it must be between 1 and 24",
            "max_workers",
            "Retry with a max_workers value between 1 and 24.",
        )
    pages, items = validate_composite_bounds(
        max_pages, max_items, minimum_items=len(PERFORMANCE_PROFILES)
    )
    return app, int(app), window, max_workers, pages, items


def _normalize_explicit_empty(result: Mapping[str, Any]) -> dict[str, Any]:
    selected = copy.deepcopy(dict(result))
    envelope = selected.get("data")
    data = envelope.get("data") if isinstance(envelope, Mapping) else None
    if (
        selected.get("ok") is True
        and selected.get("status") in {"success", "empty"}
        and isinstance(data, Mapping)
        and isinstance(data.get("items"), list)
        and isinstance(data.get("total"), list)
        and not data["items"]
        and not data["total"]
    ):
        selected["status"] = "empty"
        if isinstance(envelope, Mapping):
            selected["data"] = {**dict(envelope), "status": "empty"}
    return selected


def _performance_app_id(value: str | int) -> str:
    rendered = (
        str(value).strip()
        if not isinstance(value, bool) and isinstance(value, (str, int))
        else ""
    )
    if not rendered.isascii() or not rendered.isdigit() or int(rendered) <= 0:
        raise _performance_input_error(
            "attribution performance app_id has an invalid actual value; it must be a positive integer",
            "app_id",
            "Resolve a catalog App and retry with `--app <alias-or-positive-id>`.",
        )
    return str(int(rendered))


def _performance_date_range(start: str, end: str) -> tuple[str, str]:
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        valid = first <= last
    except (TypeError, ValueError):
        valid = False
    if not valid:
        raise _performance_input_error(
            "attribution performance date range has an invalid actual value; start and end must be ordered YYYY-MM-DD dates",
            "start/end",
            "Retry with `--start YYYY-MM-DD --end YYYY-MM-DD` and start no later than end.",
        )
    return first.isoformat(), last.isoformat()


def _performance_input_error(
    message: str, field: str, next_action: str
) -> InputValidationError:
    return InputValidationError(message, field=field, next_action=next_action)


def _positive_app_id(value: str | int) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise _app_id_error(
            f"actual value: {actual_value(value)}; attribution snapshot app_id must be a "
            "positive integer",
            field="app_id",
            next_action="Retry with `--app-id <positive-integer>`.",
        )
    rendered = str(value).strip()
    if not rendered.isascii() or not rendered.isdigit() or int(rendered) <= 0:
        raise _app_id_error(
            f"actual value: {actual_value(value)}; attribution snapshot app_id must be a "
            "positive integer",
            field="app_id",
            next_action="Retry with `--app-id <positive-integer>`.",
        )
    return str(int(rendered))


def _app_id_error(message: str, *, field: str, next_action: str) -> InputValidationError:
    return InputValidationError(
        message,
        field=field,
        next_action=next_action,
    )


__all__ = [
    "PERFORMANCE_OPERATION_ID",
    "PERFORMANCE_PROFILES",
    "PERFORMANCE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "TESTING_DEVICE_OPERATION_ID",
    "USER_DETAIL_OPERATION_ID",
    "USER_DETAIL_SCHEMA_VERSION",
    "add_performance_command",
    "add_snapshot_command",
    "attribution_performance",
    "attribution_snapshot",
    "attribution_user_detail",
    "attribution_user_detail_result",
    "validate_attribution_performance_request",
    "validate_attribution_user_detail_request",
]
