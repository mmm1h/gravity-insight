"""Compact multi-query product backed entirely by the public Plan v1 engine.

This module owns only the small input contract that turns independent Analysis
Query Spec v1 documents into sibling ``analysis_query`` composite nodes.  Plan
v1 remains the sole owner of adapter preflight, concurrency, budgets, failure
isolation, ordering, and caller-safe result envelopes.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .analysis_spec import compile_query_spec
from .analysis_spec_schema import ANALYSIS_SPEC_KINDS
from .analysis_query_multi_app import (
    MAX_COMPONENTS,
    MULTI_APP_BATCH_SCHEMA_VERSION,
    MULTI_APP_KINDS,
    MULTI_APP_RESULT_SCHEMA_VERSION,
)
from .errors import InputValidationError
from .plan import DEFAULT_MAX_ITEMS, PLAN_SCHEMA_VERSION
from .result_source import GOVERNED_PRODUCT, result_source
from .actionable_error_values import actual_value


BATCH_SCHEMA_VERSION = "gravity.analysis-query-batch.v1"
RESULT_SCHEMA_VERSION = "gravity.analysis-query-batch-result.v1"
SCHEMA_SCHEMA_VERSION = "gravity.analysis-query-batch-schema.v1"
MAX_QUERIES = 32
DEFAULT_MAX_WORKERS = 6

_WRAPPER_FIELDS = frozenset({"schema_version", "queries"})
_QUERY_FIELDS = frozenset(
    {"id", "kind", "app", "spec", "start", "end", "output_fields", "limits"}
)
_LIMIT_FIELDS = frozenset({"max_items"})
QUERY_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$"
_QUERY_ID_RE = re.compile(QUERY_ID_PATTERN)
_PLAN_RESULT_FIELDS = frozenset(
    {
        "ok",
        "status",
        "dry_run",
        "declared_count",
        "expanded_count",
        "max_expanded_count",
        "max_aggregate_items",
        "success_count",
        "empty_count",
        "failure_count",
        "skipped_count",
        "exit_code",
        "max_workers",
        "results",
    }
)


@dataclass(frozen=True)
class _BatchQuery:
    node_id: str
    result_query_id: str
    kind: str
    app: str | int
    spec: Mapping[str, Any]
    start: str | None
    end: str | None
    output_fields: tuple[str, ...]
    max_items: int


def analysis_query_batch_schema() -> dict[str, Any]:
    """Return the complete, compact machine contract for this thin product."""

    from .analysis_query_batch_schema import build_analysis_query_batch_schema

    return build_analysis_query_batch_schema()


def validate_analysis_query_batch(
    sdk: Any,
    payload: Mapping[str, Any],
    *,
    workspace: Any | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> dict[str, Any]:
    """Compile every item and delegate the zero-execution preflight to the SDK."""

    plan, shape, selected_workspace = _batch_plan(
        sdk,
        payload,
        workspace=workspace,
        max_workers=max_workers,
    )
    result = sdk.validate_plan(
        plan,
        workspace=selected_workspace,
        max_workers=max_workers,
    )
    return _safe_result(result, shape)


def execute_analysis_query_batch(
    sdk: Any,
    payload: Mapping[str, Any],
    *,
    workspace: Any | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> dict[str, Any]:
    """Compile every item, then delegate execution to the SDK's Plan engine."""

    plan, shape, selected_workspace = _batch_plan(
        sdk,
        payload,
        workspace=workspace,
        max_workers=max_workers,
    )
    result = sdk.execute_plan(
        plan,
        workspace=selected_workspace,
        max_workers=max_workers,
    )
    return _safe_result(result, shape)


def run_analysis_query_batch(
    sdk: Any,
    payload: Mapping[str, Any],
    *,
    workspace: Any | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Select the SDK validation or execution path without changing its semantics."""

    if not isinstance(dry_run, bool):
        raise _input_error(f"actual value: {actual_value(dry_run)}; " + ("dry_run must be a boolean"), "dry_run")
    function = validate_analysis_query_batch if dry_run else execute_analysis_query_batch
    return function(
        sdk,
        payload,
        workspace=workspace,
        max_workers=max_workers,
    )


def _batch_plan(
    sdk: Any,
    payload: Mapping[str, Any],
    *,
    workspace: Any | None,
    max_workers: int,
) -> tuple[dict[str, Any], tuple[str, int, tuple[_BatchQuery, ...]], Any]:
    selected_workspace = _selected_workspace(sdk, workspace)
    version, query_count, queries = _queries(payload)
    _preflight_specs(
        queries,
        selected_workspace,
        reject_duplicate_apps=version == MULTI_APP_BATCH_SCHEMA_VERSION,
    )
    nodes = [_plan_node(query) for query in queries]
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "budget": {
            "max_workers": max_workers,
            "max_total_items": sum(query.max_items for query in queries),
        },
        "nodes": nodes,
    }
    return plan, (version, query_count, queries), selected_workspace


def _queries(
    payload: Mapping[str, Any],
) -> tuple[str, int, tuple[_BatchQuery, ...]]:
    if not isinstance(payload, Mapping):
        raise _input_error(f"actual value: {actual_value(payload)}; " + ("analysis query batch input must be an object"), "input")
    _reject_unknown(payload, _WRAPPER_FIELDS, "input")
    version = payload.get("schema_version")
    if version not in {BATCH_SCHEMA_VERSION, MULTI_APP_BATCH_SCHEMA_VERSION}:
        raise _input_error(
            f"actual value: {actual_value(version)}; " + ("schema_version must be gravity.analysis-query-batch.v1 or "
            "gravity.analysis-query-batch.v2"),
            "schema_version",
        )
    source = payload.get("queries")
    if not isinstance(source, Sequence) or isinstance(
        source, (str, bytes, bytearray)
    ):
        raise _input_error(f"actual value: {actual_value(source)}; " + ("queries must be an array"), "queries")
    if not source:
        raise _input_error(f"actual value: {actual_value(source)}; " + ("queries must not be empty"), "queries")
    if len(source) > MAX_QUERIES:
        raise _input_error(f"queries supports at most {MAX_QUERIES} items; must stay at or below that bound; split the request", "queries")
    if version == MULTI_APP_BATCH_SCHEMA_VERSION:
        values = _parse_multi_app_queries(source)
    else:
        values = _single_app_queries(source)
    return version, len(source), values


def _single_app_queries(source: Sequence[Any]) -> tuple[_BatchQuery, ...]:
    values = tuple(_query(item, index) for index, item in enumerate(source))
    if len({item.result_query_id for item in values}) != len(values):
        raise _input_error(f"actual value: {actual_value([item.result_query_id for item in values])}; " + ("query ids must be unique"), "queries.id")
    return values


def _parse_multi_app_queries(source: Sequence[Any]) -> tuple[_BatchQuery, ...]:
    from .analysis_query_multi_app import parse_multi_app_queries

    return tuple(
        _BatchQuery(
            node_id=item.node_id,
            result_query_id=item.result_query_id,
            kind=item.kind,
            app=item.app,
            spec=item.spec,
            start=item.start,
            end=item.end,
            output_fields=item.output_fields,
            max_items=item.max_items,
        )
        for item in parse_multi_app_queries(source)
    )


def _query(value: Any, index: int) -> _BatchQuery:
    field = f"queries[{index}]"
    if not isinstance(value, Mapping):
        raise _input_error(f"actual value: {actual_value(value)}; " + ("batch queries must be objects"), field)
    _reject_unknown(value, _QUERY_FIELDS, field)
    query_id, kind = _identity(value, field)
    app = value.get("app")
    if not _is_app(app):
        raise _input_error(
            f"actual value: {actual_value(app)}; " + ("app must be a workspace alias or positive id"), f"{field}.app"
        )
    spec = value.get("spec")
    if not isinstance(spec, Mapping):
        raise _input_error(f"actual value: {actual_value(spec)}; " + ("spec must be an object"), f"{field}.spec")
    limits = _limits(value.get("limits", {}), field)
    return _BatchQuery(
        node_id=query_id,
        result_query_id=query_id,
        kind=kind,
        app=app,
        spec=copy.deepcopy(dict(spec)),
        start=_optional_text(value.get("start"), f"{field}.start"),
        end=_optional_text(value.get("end"), f"{field}.end"),
        output_fields=_output_fields(value.get("output_fields"), field),
        max_items=limits,
    )


def _identity(value: Mapping[str, Any], field: str) -> tuple[str, str]:
    query_id = value.get("id")
    if not isinstance(query_id, str) or not _QUERY_ID_RE.fullmatch(query_id):
        raise _input_error("query id is invalid; must be a bounded opaque identifier", f"{field}.id")
    kind = value.get("kind")
    if not isinstance(kind, str) or kind.strip().casefold() not in ANALYSIS_SPEC_KINDS:
        raise _input_error(
            f"actual value: {actual_value(kind)}; " + ("kind must be event, funnel, retention, property, or scatter"),
            f"{field}.kind",
        )
    return query_id, kind.strip().casefold()


def _preflight_specs(
    queries: tuple[_BatchQuery, ...],
    workspace: Any,
    *,
    reject_duplicate_apps: bool,
) -> None:
    resolved: set[tuple[str, str]] = set()
    for item in queries:
        compiled = compile_query_spec(
            item.kind,
            item.spec,
            workspace=workspace,
            app=item.app,
            start=item.start,
            end=item.end,
        )
        identity = (item.result_query_id, str(compiled.inputs["app_id"]))
        if reject_duplicate_apps and identity in resolved:
            raise _input_error(
                f"actual value: {actual_value(identity)}; " + ("apps must resolve to unique Apps within each query"), "queries.apps"
            )
        resolved.add(identity)


def _plan_node(item: _BatchQuery) -> dict[str, Any]:
    request: dict[str, Any] = {
        "name": "analysis_query",
        "kind": item.kind,
        "app": item.app,
        "spec": copy.deepcopy(dict(item.spec)),
    }
    if item.start is not None:
        request["start"] = item.start
        request["end"] = item.end
    node: dict[str, Any] = {
        "id": item.node_id,
        "kind": "composite",
        "request": request,
        "limits": {"max_pages": 1, "max_items": item.max_items},
    }
    if item.output_fields:
        node["output_fields"] = list(item.output_fields)
    return node


def _limits(value: Any, field: str) -> int:
    if not isinstance(value, Mapping):
        raise _input_error(f"actual value: {actual_value(value)}; " + ("limits must be an object"), f"{field}.limits")
    _reject_unknown(value, _LIMIT_FIELDS, f"{field}.limits")
    maximum = value.get("max_items", DEFAULT_MAX_ITEMS)
    if type(maximum) is not int:
        raise _input_error(f"actual value: {actual_value(maximum)}; " + ("max_items must be an integer"), f"{field}.limits.max_items")
    return maximum


def _output_fields(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise _input_error(f"actual value: {actual_value(value)}; " + ("output_fields must be an array"), f"{field}.output_fields")
    selected = tuple(item.strip() for item in value if isinstance(item, str))
    if len(selected) != len(value) or not selected:
        raise _input_error(
            f"actual value: {actual_value(selected)}; " + ("output_fields must be a non-empty string array"),
            f"{field}.output_fields",
        )
    if len(set(selected)) != len(selected):
        raise _input_error(f"actual value: {actual_value(selected)}; " + ("output_fields must be unique"), f"{field}.output_fields")
    return selected


def _selected_workspace(sdk: Any, workspace: Any | None) -> Any:
    if workspace is not None:
        return workspace
    try:
        return sdk.workspace
    except AttributeError as exc:
        raise _input_error("workspace is required; must bind GravityClient.workspace first", "workspace") from exc


def _safe_result(
    result: Any, shape: tuple[str, int, tuple[_BatchQuery, ...]]
) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise RuntimeError("Plan returned an invalid Analysis query batch result")
    selected = {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if key in _PLAN_RESULT_FIELDS
    }
    version, query_count, queries = shape
    if version == BATCH_SCHEMA_VERSION:
        return {
            "schema_version": RESULT_SCHEMA_VERSION,
            "result_source": result_source(GOVERNED_PRODUCT),
            "plan_result_schema_version": result.get("schema_version"),
            "query_count": query_count,
            **selected,
        }
    from .analysis_query_multi_app import decorate_multi_app_result

    return decorate_multi_app_result(selected, result, queries, query_count)


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _input_error(f"actual value: {actual_value(value)}; " + (f"{field} must be a non-empty string"), field)
    return value.strip()


def _is_app(value: Any) -> bool:
    return (
        isinstance(value, str) and bool(value.strip())
    ) or (type(value) is int and value > 0)


def _reject_unknown(
    value: Mapping[str, Any], allowed: frozenset[str], field: str
) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise _input_error(
            f"{field} contains unsupported fields: {', '.join(unknown)}; must use only declared fields; remove extras", field
        )


def _input_error(message: str, field: str) -> InputValidationError:
    return InputValidationError(
        message,
        field=field,
        next_action=(
            "Run `gravity analysis query batch --help`, correct the compact batch "
            "document, and retry."
        ),
    )


__all__ = [
    "BATCH_SCHEMA_VERSION",
    "DEFAULT_MAX_WORKERS",
    "MAX_COMPONENTS",
    "MAX_QUERIES",
    "MULTI_APP_BATCH_SCHEMA_VERSION",
    "MULTI_APP_KINDS",
    "MULTI_APP_RESULT_SCHEMA_VERSION",
    "QUERY_ID_PATTERN",
    "RESULT_SCHEMA_VERSION",
    "SCHEMA_SCHEMA_VERSION",
    "analysis_query_batch_schema",
    "execute_analysis_query_batch",
    "run_analysis_query_batch",
    "validate_analysis_query_batch",
]
