"""Immutable Plan contract constants for Analysis query composites."""

ANALYSIS_QUERY_NAME = "analysis_query"
ANALYSIS_QUERY_REQUEST_FIELDS = frozenset(
    {
        "name", "kind", "app", "spec", "start", "end", "compare_start",
        "compare_end", "metadata_snapshot",
    }
)
ANALYSIS_QUERY_BINDING_TARGETS = frozenset({"/app"})


__all__ = [
    "ANALYSIS_QUERY_BINDING_TARGETS",
    "ANALYSIS_QUERY_NAME",
    "ANALYSIS_QUERY_REQUEST_FIELDS",
]
