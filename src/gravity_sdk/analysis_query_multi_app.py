"""Explicit multi-App contract for compact Analysis Query Batch v2."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import InputValidationError
from .plan import DEFAULT_MAX_ITEMS
from .result_source import GOVERNED_PRODUCT, result_source
from .actionable_error_values import actual_value


MULTI_APP_BATCH_SCHEMA_VERSION = "gravity.analysis-query-batch.v2"
MULTI_APP_RESULT_SCHEMA_VERSION = "gravity.analysis-query-batch-result.v2"
MULTI_APP_SCHEMA_VERSION = "gravity.analysis-query-multi-app-schema.v1"
MAX_COMPONENTS = 32
MULTI_APP_KINDS = frozenset({"event", "funnel", "retention", "property"})

_QUERY_FIELDS = frozenset(
    {"id", "kind", "apps", "spec", "start", "end", "output_fields", "limits"}
)
_QUERY_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


@dataclass(frozen=True)
class MultiAppComponent:
    node_id: str
    result_query_id: str
    kind: str
    app: str | int
    spec: Mapping[str, Any]
    start: str | None
    end: str | None
    output_fields: tuple[str, ...]
    max_items: int


def analysis_query_multi_app_schema() -> dict[str, Any]:
    return {
        "schema_version": MULTI_APP_SCHEMA_VERSION,
        "ok": True,
        "status": "success",
        "batch_schema_version": MULTI_APP_BATCH_SCHEMA_VERSION,
        "result_schema_version": MULTI_APP_RESULT_SCHEMA_VERSION,
        "command": "gravity analysis query --kind <kind> --spec <spec> --apps <apps>",
        "input": {
            "required": ["id", "kind", "apps", "spec"],
            "additional_properties": False,
            "properties": {
                "id": {"type": "string", "pattern": _QUERY_ID_RE.pattern},
                "kind": {"type": "string", "enum": sorted(MULTI_APP_KINDS)},
                "apps": {
                    "type": "array",
                    "min_items": 1,
                    "max_items": MAX_COMPONENTS,
                    "unique_items": True,
                    "items": {"type": ["string", "integer"]},
                },
                "spec": {"type": "object"},
                "start": {"type": "string", "format": "date"},
                "end": {"type": "string", "format": "date"},
                "output_fields": {"type": "array", "items": {"type": "string"}},
                "limits": {"type": "object"},
            },
        },
        "execution": {
            "delegate": "gravity.plan.v1",
            "expansion": "same-layer scalar-app analysis_query nodes",
            "adapter_inner_concurrency": 1,
            "max_expanded_components": MAX_COMPONENTS,
        },
        "output": {
            "identity_fields": ["query_id", "app"],
            "cross_app_aggregation": False,
            "all_apps_selector": False,
        },
    }


def parse_multi_app_queries(source: Sequence[Any]) -> tuple[MultiAppComponent, ...]:
    values: list[MultiAppComponent] = []
    identifiers: list[str] = []
    for index, value in enumerate(source):
        query_id, components = _query(value, index)
        identifiers.append(query_id)
        values.extend(components)
    if len(set(identifiers)) != len(identifiers):
        raise _input_error(f"actual value: {actual_value(identifiers)}; " + ("query ids must be unique"), "queries.id")
    if len(values) > MAX_COMPONENTS:
        raise _input_error(
            f"multi-App expansion supports at most {MAX_COMPONENTS} components; must stay at or below that bound; split the request",
            "queries.apps",
        )
    return tuple(values)


def _query(value: Any, index: int) -> tuple[str, tuple[MultiAppComponent, ...]]:
    field = f"queries[{index}]"
    if not isinstance(value, Mapping):
        raise _input_error(f"actual value: {actual_value(value)}; " + ("batch queries must be objects"), field)
    _reject_unknown(value, _QUERY_FIELDS, field)
    query_id = value.get("id")
    if not isinstance(query_id, str) or not _QUERY_ID_RE.fullmatch(query_id):
        raise _input_error("query id is invalid; must be a bounded opaque identifier", f"{field}.id")
    kind = str(value.get("kind", "")).strip().casefold()
    if kind not in MULTI_APP_KINDS:
        raise _input_error(
            f"actual value: {actual_value(kind)}; " + ("multi-App kind must be event, funnel, retention, or property"),
            f"{field}.kind",
        )
    spec = value.get("spec")
    if not isinstance(spec, Mapping):
        raise _input_error(f"actual value: {actual_value(spec)}; " + ("spec must be an object"), f"{field}.spec")
    options = {
        "kind": kind,
        "spec": copy.deepcopy(dict(spec)),
        "start": _optional_text(value.get("start"), f"{field}.start"),
        "end": _optional_text(value.get("end"), f"{field}.end"),
        "output_fields": _output_fields(value.get("output_fields"), field),
        "max_items": _limits(value.get("limits", {}), field),
    }
    components = tuple(
        MultiAppComponent(
            node_id=f"q{index + 1}.app{app_index + 1}",
            result_query_id=query_id,
            app=app,
            **options,
        )
        for app_index, app in enumerate(_apps(value.get("apps"), field))
    )
    return query_id, components


def decorate_multi_app_result(
    selected: dict[str, Any],
    result: Mapping[str, Any],
    queries: Sequence[Any],
    query_count: int,
) -> dict[str, Any]:
    identities = {
        item.node_id: {"query_id": item.result_query_id, "app": item.app}
        for item in queries
    }
    selected["results"] = [
        {**copy.deepcopy(dict(item)), **identities.get(item.get("node_id"), {})}
        for item in result.get("results", ())
        if isinstance(item, Mapping)
    ]
    return {
        "schema_version": MULTI_APP_RESULT_SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "plan_result_schema_version": result.get("schema_version"),
        "query_count": query_count,
        "component_count": len(queries),
        "cross_app_aggregation": False,
        **selected,
    }


def _apps(value: Any, field: str) -> tuple[str | int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _input_error(f"actual value: {actual_value(value)}; " + ("apps must be an array"), f"{field}.apps")
    apps = tuple(item.strip() if isinstance(item, str) else item for item in value)
    if not apps:
        raise _input_error(f"actual value: {actual_value(apps)}; " + ("apps must not be empty"), f"{field}.apps")
    if any(not _is_app(item) or item == "*" for item in apps):
        raise _input_error(
            f"actual value: {actual_value(apps)}; " + ("apps items must be explicit workspace aliases or positive ids"),
            f"{field}.apps",
        )
    if len(set(apps)) != len(apps):
        raise _input_error(f"actual value: {actual_value(apps)}; " + ("apps must be unique"), f"{field}.apps")
    return apps


def _limits(value: Any, field: str) -> int:
    if not isinstance(value, Mapping):
        raise _input_error(f"actual value: {actual_value(value)}; " + ("limits must be an object"), f"{field}.limits")
    _reject_unknown(value, frozenset({"max_items"}), f"{field}.limits")
    maximum = value.get("max_items", DEFAULT_MAX_ITEMS)
    if type(maximum) is not int:
        raise _input_error(f"actual value: {actual_value(maximum)}; " + ("max_items must be an integer"), f"{field}.limits.max_items")
    return maximum


def _output_fields(value: Any, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _input_error(f"actual value: {actual_value(value)}; " + ("output_fields must be an array"), f"{field}.output_fields")
    selected = tuple(item.strip() for item in value if isinstance(item, str))
    if len(selected) != len(value) or not selected:
        raise _input_error(
            f"actual value: {actual_value(selected)}; " + ("output_fields must be a non-empty string array"), f"{field}.output_fields"
        )
    if len(set(selected)) != len(selected):
        raise _input_error(f"actual value: {actual_value(selected)}; " + ("output_fields must be unique"), f"{field}.output_fields")
    return selected


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
    "MAX_COMPONENTS",
    "MULTI_APP_BATCH_SCHEMA_VERSION",
    "MULTI_APP_KINDS",
    "MULTI_APP_RESULT_SCHEMA_VERSION",
    "MULTI_APP_SCHEMA_VERSION",
    "MultiAppComponent",
    "decorate_multi_app_result",
    "analysis_query_multi_app_schema",
    "parse_multi_app_queries",
]
