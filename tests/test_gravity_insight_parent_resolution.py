from __future__ import annotations

from gravity_sdk.parent_resolution import (
    extract_parent_items,
    extract_parent_values,
    resolve_declared_parents,
)
from gravity_sdk.prober.parents import _offline_resolution


def _description(selection: str = "caller_select", field_type: str = "string"):
    return {
        "operation_id": "example.child.list",
        "input_schema": {"parent_id": {"type": field_type}},
        "required_parent": [
            {
                "operation_id": "example.parent.list",
                "output_path": "data.list[].id",
                "selection": selection,
                "target_input": "parent_id",
            }
        ],
    }


def test_extract_parent_values_supports_lists_and_deduplicates() -> None:
    payload = {"data": {"list": [{"id": 7}, {"id": 7}, {"id": 9}]}}

    assert extract_parent_values(payload, "data.list[].id") == [7, 9]


def test_extract_parent_items_preserves_aligned_rows() -> None:
    rows = [
        {"advertiser_id": 101, "promotion_id": 201},
        {"advertiser_id": 102, "promotion_id": 202},
    ]

    assert extract_parent_items({"data": {"list": rows}}, "data.list[]") == rows


def test_extract_parent_values_supports_recursive_tree_fields() -> None:
    payload = {
        "data": {
            "tree": [
                {"id": 1, "children": [{"id": 2, "children": []}]},
            ]
        }
    }

    assert extract_parent_values(payload, "data.tree..id") == [1, 2]


def test_resolve_declared_parents_keeps_caller_selection_explicit() -> None:
    result = resolve_declared_parents(
        _description(),
        lambda _operation_id: {
            "status": "success",
            "data": {"list": [{"id": 7}, {"id": 9}]},
        },
    )

    assert result["status"] == "resolved"
    assert result["bindings"][0]["candidate_count"] == 2
    assert result["bindings"][0]["candidates"] == [7, 9]
    assert result["bindings"][0]["selected"] is None
    assert result["values_persisted"] is False


def test_resolve_declared_parents_reports_empty_and_array_cardinality() -> None:
    result = resolve_declared_parents(
        _description(selection="all", field_type="array"),
        lambda _operation_id: {"status": "empty", "data": {"list": []}},
    )

    assert result["status"] == "empty"
    assert result["bindings"][0]["target_cardinality"] == "many"
    assert result["bindings"][0]["candidate_count"] == 0


def test_resolve_declared_parents_handles_operations_without_parent() -> None:
    result = resolve_declared_parents(
        {"operation_id": "example.root.list", "required_parent": []},
        lambda _operation_id: (_ for _ in ()).throw(AssertionError("must not probe")),
    )

    assert result["status"] == "not_required"
    assert result["bindings"] == []


def test_resolve_declared_parents_caches_shared_parent_and_fails_closed() -> None:
    description = _description()
    description["input_schema"]["other_parent_id"] = {"type": "string"}
    description["required_parent"].append(
        {
            **description["required_parent"][0],
            "output_path": "data.list[].missing_id",
            "target_input": "other_parent_id",
        }
    )
    calls = 0

    def probe(_operation_id: str):
        nonlocal calls
        calls += 1
        return {"status": "success", "data": {"list": [{"id": 7}]}}

    result = resolve_declared_parents(description, probe)

    assert calls == 1
    assert result["status"] == "undetermined"


def test_offline_resolution_does_not_ignore_unbound_id_fields() -> None:
    source = {
        "operation": {
            "path_template": "/api/material/labels",
            "input_fields": {"advertiser_id": {"type": "integer"}},
            "required_parent": [],
            "live_probe": {"inputs": {"advertiser_id": 0}},
        },
        "draft": {
            "probe_evidence": [
                {"conclusion": "success", "path": "evidence/example.yaml"}
            ]
        },
    }

    result = _offline_resolution(source)

    assert result["conclusion"] == "undetermined"
    assert result["basis"] == "unbound_parent_fields"
    assert result["missing_evidence"]
