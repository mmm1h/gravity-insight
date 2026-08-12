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
from .errors import InputValidationError
from .plan import DEFAULT_MAX_ITEMS, PLAN_SCHEMA_VERSION


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
_QUERY_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
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
    query_id: str
    kind: str
    app: str | int
    spec: Mapping[str, Any]
    start: str | None
    end: str | None
    output_fields: tuple[str, ...]
    max_items: int


def analysis_query_batch_schema() -> dict[str, Any]:
    """Return the complete, compact machine contract for this thin product."""

    return {
        "schema_version": SCHEMA_SCHEMA_VERSION,
        "ok": True,
        "status": "success",
        "batch_schema_version": BATCH_SCHEMA_VERSION,
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "command": "gravity analysis query batch --input <queries.json> --concurrency 6",
        "input": {
            "type": "object",
            "additional_properties": False,
            "required": ["schema_version", "queries"],
            "properties": {
                "schema_version": {"const": BATCH_SCHEMA_VERSION},
                "queries": {
                    "type": "array",
                    "min_items": 1,
                    "max_items": MAX_QUERIES,
                    "items": {
                        "type": "object",
                        "additional_properties": False,
                        "required": ["id", "kind", "app", "spec"],
                        "properties": _query_schema_fields(),
                    },
                },
            },
        },
        "execution": {
            "delegate": "gravity.plan.v1",
            "shape": "independent same-layer analysis_query composite nodes",
            "outer_concurrency_default": DEFAULT_MAX_WORKERS,
            "outer_concurrency_max": 24,
            "adapter_inner_concurrency": 1,
            "preflight": "every literal spec is compiled before Plan execution",
            "natural_language_auto_execute": False,
        },
        "boundaries": {
            "query_count": MAX_QUERIES,
            "kinds": list(ANALYSIS_SPEC_KINDS),
            "dependencies": False,
            "bindings": False,
            "foreach": False,
            "expressions": False,
            "raw_http_or_sql": False,
        },
        "output": {
            "preserves_input_order": True,
            "echoes_spec": False,
            "echoes_compiled_input": False,
            "failure_isolation": "Plan v1 sibling isolation",
            "exit_precedence": "local 4 > upstream 3 > caller 2 > success 0",
        },
        "example": {
            "schema_version": BATCH_SCHEMA_VERSION,
            "queries": [
                {
                    "id": "daily_opens",
                    "kind": "event",
                    "app": "main",
                    "spec": {
                        "start": "2026-08-01",
                        "end": "2026-08-07",
                        "steps": [
                            {
                                "event": "app_open",
                                "metric": {
                                    "field": "PresetAllCount",
                                    "aggregation": "PresetAllCount",
                                },
                            }
                        ],
                    },
                    "limits": {"max_items": 200},
                }
            ],
        },
    }


def validate_analysis_query_batch(
    sdk: Any,
    payload: Mapping[str, Any],
    *,
    workspace: Any | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> dict[str, Any]:
    """Compile every item and delegate the zero-execution preflight to the SDK."""

    plan, count, selected_workspace = _batch_plan(
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
    return _safe_result(result, count)


def execute_analysis_query_batch(
    sdk: Any,
    payload: Mapping[str, Any],
    *,
    workspace: Any | None = None,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> dict[str, Any]:
    """Compile every item, then delegate execution to the SDK's Plan engine."""

    plan, count, selected_workspace = _batch_plan(
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
    return _safe_result(result, count)


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
        raise _input_error("dry_run must be a boolean", "dry_run")
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
) -> tuple[dict[str, Any], int, Any]:
    selected_workspace = _selected_workspace(sdk, workspace)
    queries = _queries(payload)
    _preflight_specs(queries, selected_workspace)
    nodes = [_plan_node(query) for query in queries]
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "budget": {
            "max_workers": max_workers,
            "max_total_items": sum(query.max_items for query in queries),
        },
        "nodes": nodes,
    }
    return plan, len(queries), selected_workspace


def _queries(payload: Mapping[str, Any]) -> tuple[_BatchQuery, ...]:
    if not isinstance(payload, Mapping):
        raise _input_error("analysis query batch input must be an object", "input")
    _reject_unknown(payload, _WRAPPER_FIELDS, "input")
    if payload.get("schema_version") != BATCH_SCHEMA_VERSION:
        raise _input_error(
            f"schema_version must be {BATCH_SCHEMA_VERSION}", "schema_version"
        )
    source = payload.get("queries")
    if not isinstance(source, Sequence) or isinstance(
        source, (str, bytes, bytearray)
    ):
        raise _input_error("queries must be an array", "queries")
    if not source:
        raise _input_error("queries must not be empty", "queries")
    if len(source) > MAX_QUERIES:
        raise _input_error(f"queries supports at most {MAX_QUERIES} items", "queries")
    values = tuple(_query(item, index) for index, item in enumerate(source))
    identifiers = [item.query_id for item in values]
    if len(set(identifiers)) != len(identifiers):
        raise _input_error("query ids must be unique", "queries.id")
    return values


def _query(value: Any, index: int) -> _BatchQuery:
    field = f"queries[{index}]"
    if not isinstance(value, Mapping):
        raise _input_error("batch queries must be objects", field)
    _reject_unknown(value, _QUERY_FIELDS, field)
    query_id = value.get("id")
    if not isinstance(query_id, str) or not _QUERY_ID_RE.fullmatch(query_id):
        raise _input_error("query id is invalid", f"{field}.id")
    kind = value.get("kind")
    if not isinstance(kind, str) or kind.strip().casefold() not in ANALYSIS_SPEC_KINDS:
        raise _input_error(
            "kind must be event, funnel, retention, property, or scatter",
            f"{field}.kind",
        )
    app = value.get("app")
    if not _is_app(app):
        raise _input_error(
            "app must be a workspace alias or positive id", f"{field}.app"
        )
    spec = value.get("spec")
    if not isinstance(spec, Mapping):
        raise _input_error("spec must be an object", f"{field}.spec")
    limits = _limits(value.get("limits", {}), field)
    return _BatchQuery(
        query_id=query_id,
        kind=kind.strip().casefold(),
        app=app,
        spec=copy.deepcopy(dict(spec)),
        start=_optional_text(value.get("start"), f"{field}.start"),
        end=_optional_text(value.get("end"), f"{field}.end"),
        output_fields=_output_fields(value.get("output_fields"), field),
        max_items=limits,
    )


def _preflight_specs(queries: tuple[_BatchQuery, ...], workspace: Any) -> None:
    for item in queries:
        compile_query_spec(
            item.kind,
            item.spec,
            workspace=workspace,
            app=item.app,
            start=item.start,
            end=item.end,
        )


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
        "id": item.query_id,
        "kind": "composite",
        "request": request,
        "limits": {"max_pages": 1, "max_items": item.max_items},
    }
    if item.output_fields:
        node["output_fields"] = list(item.output_fields)
    return node


def _limits(value: Any, field: str) -> int:
    if not isinstance(value, Mapping):
        raise _input_error("limits must be an object", f"{field}.limits")
    _reject_unknown(value, _LIMIT_FIELDS, f"{field}.limits")
    maximum = value.get("max_items", DEFAULT_MAX_ITEMS)
    if type(maximum) is not int:
        raise _input_error("max_items must be an integer", f"{field}.limits.max_items")
    return maximum


def _output_fields(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        raise _input_error("output_fields must be an array", f"{field}.output_fields")
    selected = tuple(item.strip() for item in value if isinstance(item, str))
    if len(selected) != len(value) or not selected:
        raise _input_error(
            "output_fields must be a non-empty string array",
            f"{field}.output_fields",
        )
    if len(set(selected)) != len(selected):
        raise _input_error("output_fields must be unique", f"{field}.output_fields")
    return selected


def _selected_workspace(sdk: Any, workspace: Any | None) -> Any:
    if workspace is not None:
        return workspace
    try:
        return sdk.workspace
    except AttributeError as exc:
        raise _input_error("workspace is required", "workspace") from exc


def _safe_result(result: Any, query_count: int) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        raise RuntimeError("Plan returned an invalid Analysis query batch result")
    selected = {
        key: copy.deepcopy(value)
        for key, value in result.items()
        if key in _PLAN_RESULT_FIELDS
    }
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "plan_result_schema_version": result.get("schema_version"),
        "query_count": query_count,
        **selected,
    }


def _query_schema_fields() -> dict[str, Any]:
    return {
        "id": {"type": "string", "pattern": _QUERY_ID_RE.pattern},
        "kind": {"type": "string", "enum": list(ANALYSIS_SPEC_KINDS)},
        "app": {"type": ["string", "integer"]},
        "spec": {
            "type": "object",
            "description": "One literal Analysis Query Spec v1 object for kind.",
        },
        "start": {"type": "string", "format": "date"},
        "end": {"type": "string", "format": "date"},
        "output_fields": {
            "type": "array",
            "min_items": 1,
            "unique_items": True,
            "items": {"type": "string"},
        },
        "limits": {
            "type": "object",
            "additional_properties": False,
            "properties": {"max_items": {"type": "integer", "minimum": 1}},
        },
    }


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _input_error(f"{field} must be a non-empty string", field)
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
            f"{field} contains unsupported fields: {', '.join(unknown)}", field
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
    "MAX_QUERIES",
    "RESULT_SCHEMA_VERSION",
    "SCHEMA_SCHEMA_VERSION",
    "analysis_query_batch_schema",
    "execute_analysis_query_batch",
    "run_analysis_query_batch",
    "validate_analysis_query_batch",
]
