from __future__ import annotations

import unittest
import tempfile

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest


from gravity_sdk.fingerprints import shape_fingerprint
from gravity_sdk.metadata_sync import (
    _create_schema,
    _write_apps,
    _write_catalog_metadata,
    _write_rows,
)
from gravity_sdk.receipt import record_http_request
from gravity_sdk.recipe import check_recipe
from gravity_sdk.resolver import resolve_and_run
from gravity_sdk.workspace import Recipe, RecipeBindings, load_workspace


def _recipe() -> Recipe:
    return Recipe(
        name="weekly",
        operation="analysis.example.query",
        description="Example",
        bindings=RecipeBindings("main", "app_id", "saved-report", "query_id"),
        parameters={"start": "date_list.0.start_date", "end": "date_list.0.end_date"},
        required_parameters=("start", "end"),
        input={"query_item_list": []},
        output_fields=("total",),
        contract_fingerprint="a" * 64,
    )


def _description() -> dict:
    return {
        "operation_id": "analysis.example.query",
        "stability": "stable",
        "executable": True,
        "block_reason": None,
        "input_schema": {
            "app_id": {"type": "string", "required": True},
            "query_id": {"type": "string", "required": True},
            "date_list": {"type": "array", "item_type": "object", "required": True},
            "query_item_list": {"type": "array", "required": True},
        },
        "response_projection": {"data_keys": ["total"]},
        "required_parent": [],
        "health": {"contract_fingerprint": "a" * 64},
    }


class _DescriptionClient:
    def __init__(self, description: dict):
        self.description_value = description

    def describe(self, _operation_id: str) -> dict:
        return self.description_value





def _workspace(tmp_path: Path) -> object:
    path = tmp_path / "gravity.toml"
    path.write_text(
        """schema_version = 1

[apps]
main = 1001

[defaults]
app = "main"
timezone = "Asia/Shanghai"
time_window = "latest-safe-day"

[datasources]
[products]
""",
        encoding="utf-8",
    )
    return load_workspace(path, environ={}, cache_root=tmp_path / "cache")


class _ResolverClient:
    def __init__(self, description: dict, validation: dict | None = None):
        self.description_value = description
        self.validation = validation
        self.validated_inputs: list[dict] = []

    def describe(self, _operation_id: str) -> dict:
        return self.description_value

    def validate(self, operation_id: str, inputs: dict) -> dict:
        self.validated_inputs.append(dict(inputs))
        if self.validation is not None:
            return dict(self.validation)
        return {
            "schema_version": "gravity-insight.validation.v1",
            "ok": True,
            "status": "valid_offline",
            "operation_id": operation_id,
            "network_called": False,
            "live_metadata_dependencies": [],
            "error": None,
        }

    def probe(self, _operation_id: str) -> dict:
        return {"status": "success", "data": {"list": [{"id": "parent-1"}]}}








def _metadata_catalog(path: Path) -> None:
    synced_at = "2026-08-10T00:00:00Z"
    with closing(sqlite3.connect(path)) as connection:
        _create_schema(connection)
        _write_apps(connection, [("1001", {"id": 1001, "name": "Demo"})], synced_at)
        _write_rows(
            connection,
            "1001",
            "analysis.event.list",
            [{"name": "retention_reward", "cname": "Retention reward"}],
            synced_at,
        )
        _write_catalog_metadata(
            connection,
            synced_at=synced_at,
            status="success",
            app_count=1,
            rows_written=1,
            failure_count=0,
        )
        connection.commit()


class ResolverTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.tmp_path = Path(self._temporary_directory.name)

    def test_recipe_check_reports_each_required_stale_condition(self):
        for (mutate, reason) in [
        (lambda value: value.update(stability="deprecated"), "operation_deprecated"),
        (
            lambda value: value["input_schema"].pop("date_list"),
            "input_fields_changed",
        ),
        (
            lambda value: value["health"].update(contract_fingerprint="b" * 64),
            "contract_fingerprint_changed",
        ),
    ]:
            with self.subTest(mutate=mutate, reason=reason):
                description = _description()
                mutate(description)

                result = check_recipe(_recipe(), _DescriptionClient(description))

                assert result["ok"] is False
                assert result["status"] == "stale"
                assert reason in {item["code"] for item in result["reasons"]}


    def test_input_shape_fingerprint_ignores_values_but_not_structure(self):
        first = {
            "app_id": "101",
            "filters": [{"field": "event", "operator": "EQUALS", "values": ["A"]}],
        }
        same_shape = {
            "app_id": "999",
            "filters": [{"field": "other", "operator": "IN", "values": ["B"]}],
        }
        changed_shape = {**same_shape, "timezone": "Asia/Shanghai"}

        assert shape_fingerprint(first) == shape_fingerprint(same_shape)
        assert shape_fingerprint(first) != shape_fingerprint(changed_shape)

    def test_resolver_binds_app_alias_and_writes_value_free_receipt(self) -> None:
        tmp_path = self.tmp_path
        description = {
            "operation_id": "analysis.example.query",
            "input_schema": {
                "app_id": {"type": "string", "required": True},
                "date_list": {"type": "array", "item_type": "object", "required": True},
            },
            "required_parent": [],
            "health": {"contract_fingerprint": "c" * 64},
        }
        client = _ResolverClient(description)
        executed: list[dict] = []

        def read(_client, _operation_id, inputs, **_kwargs):
            record_http_request()
            executed.append(dict(inputs))
            return {"ok": True, "status": "empty", "data": []}

        result = resolve_and_run(
            "analysis.example.query",
            client=client,
            workspace=_workspace(tmp_path),
            app="main",
            start="2026-08-01",
            end="2026-08-07",
            read=read,
        )

        assert executed[0]["app_id"] == "1001"
        assert executed[0]["date_list"] == [
            {"start_date": "2026-08-01", "end_date": "2026-08-07"}
        ]
        assert result["receipt"]["request_count"] == 1
        assert (result["ok"], result["status"], result["exit_code"]) == (True, "empty", 0)
        assert result["receipt_storage"]["persisted"] is True
        receipt_text = json.dumps(result["receipt"], ensure_ascii=False)
        assert "1001" not in receipt_text
        assert "2026-08-01" not in receipt_text

    def test_resolver_pagination_audit_requires_both_completeness_facts(self) -> None:
        description = {
            "operation_id": "app.list", "input_schema": {}, "required_parent": [],
            "health": {"contract_fingerprint": "a" * 64},
        }

        def read(*_args, **_kwargs):
            record_http_request()
            return {
                "ok": True, "status": "success",
                "request": {"inputs": {"page_size": 2000}},
                "page": {"number": 1, "total_pages": 2, "item_count": 2000,
                         "total_items": 4000},
                "data": {"list": []},
            }

        result = resolve_and_run(
            "app.list", client=_ResolverClient(description), workspace=_workspace(self.tmp_path),
            supplied_input={"page_size": 2000}, read=read,
        )

        audit = result["pagination_audit"]
        assert (audit["mode"], audit["operation_requests_made"], audit["http_requests_made"]) == (
            "single_page", 1, 1
        )
        assert audit["page_size_clamped"] is False
        assert audit["completeness"]["status"] == "partial"

    def test_exact_multidim_operations_remain_resolvable(self) -> None:
        for operation_id in ('report.multidim.query', 'report.multidim.calc_total'):
            with self.subTest(operation_id=operation_id):
                with tempfile.TemporaryDirectory() as directory:
                    tmp_path = Path(directory)
                    description = {
                        "operation_id": operation_id,
                        "stability": "stable",
                        "executable": True,
                        "input_schema": {},
                        "required_parent": [],
                        "health": {"contract_fingerprint": "f" * 64},
                    }
                    executed: list[str] = []

                    result = resolve_and_run(
                        operation_id,
                        client=_ResolverClient(description),
                        workspace=_workspace(tmp_path),
                        read=lambda _client, selected, _inputs, **_kwargs: (
                            executed.append(selected)
                            or {"ok": True, "status": "empty", "data": {"list": []}}
                        ),
                    )

                    assert executed == [operation_id]
                    assert result["operation_id"] == operation_id
                    assert result["ok"] is True

    def test_resolver_statuses_mechanically_control_ok_exit_and_diagnostics(self) -> None:
        description = {"operation_id": "app.list", "input_schema": {},
                       "required_parent": [], "health": {"contract_fingerprint": "f" * 64}}
        result = resolve_and_run("app.list", client=_ResolverClient(description), workspace=_workspace(
            self.tmp_path), read=lambda *_a, **_k: {"status": "contract_changed", "data": {}, "error": None})
        diagnostic = next(item for item in result["diagnostics"] if item["code"] == "execution_failed")
        self.assertEqual((False, 3, "CONTRACT_CHANGED"),
                         (result["ok"], result["exit_code"], diagnostic["error"]["code"]))

    def test_resolver_returns_parent_candidates_without_guessing_selection(self) -> None:
        tmp_path = self.tmp_path
        description = {
            "operation_id": "report.child.list",
            "input_schema": {"parent_id": {"type": "string", "required": True}},
            "required_parent": [
                {
                    "operation_id": "report.parent.list",
                    "output_path": "data.list[].id",
                    "selection": "caller_select",
                    "target_input": "parent_id",
                }
            ],
            "health": {"contract_fingerprint": "d" * 64},
        }
        client = _ResolverClient(
            description,
            validation={
                "ok": False,
                "status": "invalid",
                "network_called": False,
                "error": {"category": "caller", "code": "INPUT_INVALID"},
            },
        )

        result = resolve_and_run(
            "report.child.list",
            client=client,
            workspace=_workspace(tmp_path),
            read=lambda *_args, **_kwargs: pytest.fail("execution must be skipped"),
        )

        assert result["status"] == "needs_parent"
        assert result["parents"]["bindings"][0]["candidates"] == ["parent-1"]
        diagnostic = next(item for item in result["diagnostics"] if item["code"] == "parent_required")
        assert diagnostic["candidates"] == ["parent-1"]

    def test_empty_result_diagnoses_closest_local_event_name(self) -> None:
        tmp_path = self.tmp_path
        database = tmp_path / "metadata.sqlite3"
        _metadata_catalog(database)
        description = {
            "operation_id": "analysis.example.query",
            "input_schema": {
                "app_id": {"type": "string", "required": True},
                "query_item_list": {"type": "array", "required": True},
            },
            "required_parent": [],
            "health": {"contract_fingerprint": "e" * 64},
        }

        result = resolve_and_run(
            "analysis.example.query",
            client=_ResolverClient(description),
            workspace=_workspace(tmp_path),
            supplied_input={"query_item_list": [{"event_name": "retention_rewad"}]},
            app="main",
            read=lambda *_args, **_kwargs: {"ok": True, "status": "empty", "data": []},
            metadata_database=database,
        )

        diagnostic = next(
            item for item in result["diagnostics"] if item["code"] == "closest_event_names"
        )
        assert diagnostic["suggestions"][0]["candidates"][0]["name"] == "retention_reward"
