"""Machine-readable contract for the unchanged single-App batch v1 surface."""

from __future__ import annotations

from typing import Any

from .analysis_spec_schema import ANALYSIS_SPEC_KINDS


def build_analysis_query_batch_schema() -> dict[str, Any]:
    from .analysis_query_batch import (
        BATCH_SCHEMA_VERSION,
        DEFAULT_MAX_WORKERS,
        MAX_QUERIES,
        QUERY_ID_PATTERN,
        RESULT_SCHEMA_VERSION,
        SCHEMA_SCHEMA_VERSION,
    )

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
                        "properties": _query_fields(QUERY_ID_PATTERN),
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
        "example": _example(BATCH_SCHEMA_VERSION),
    }


def _query_fields(pattern: str) -> dict[str, Any]:
    return {
        "id": {"type": "string", "pattern": pattern},
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


def _example(version: str) -> dict[str, Any]:
    return {
        "schema_version": version,
        "queries": [{
            "id": "daily_opens",
            "kind": "event",
            "app": "main",
            "spec": {
                "start": "2026-08-01",
                "end": "2026-08-07",
                "steps": [{
                    "event": "app_open",
                    "metric": {
                        "field": "PresetAllCount",
                        "aggregation": "PresetAllCount",
                    },
                }],
            },
            "limits": {"max_items": 200},
        }],
    }


__all__ = ["build_analysis_query_batch_schema"]
