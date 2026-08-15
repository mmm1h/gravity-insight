from __future__ import annotations

import unittest

import argparse
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from gravity_sdk.find import run_find_command
from gravity_sdk.metadata_sync import (
    _create_schema,
    _write_apps,
    _write_catalog_metadata,
    _write_rows,
)
from gravity_sdk.workspace import load_workspace


ROOT = Path(__file__).resolve().parents[1]


class FindClient:
    def search_operations(self, query: str, **_kwargs):
        return {
            "operations": [
                {
                    "operation_id": "analysis.retention.query",
                    "description": "Retention analysis",
                    "domain": "analysis",
                    "stability": "stable",
                    "score": 90,
                    "matched_on": ["operation_id"],
                }
            ]
        }


def _fixture_catalog(database: Path) -> None:
    synced_at = "2026-08-10T00:00:00Z"
    with closing(sqlite3.connect(database)) as connection:
        _create_schema(connection)
        _write_apps(connection, [("101", {"id": 101, "name": "Game"})], synced_at)
        _write_rows(
            connection,
            "101",
            "analysis.event.list",
            [{"name": "retention_reward", "cname": "留存奖励"}],
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



class GravityFindTests(unittest.TestCase):
    def test_find_merges_operation_and_fixture_metadata_backends(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            _fixture_catalog(database)
            args = argparse.Namespace(
                query="retention",
                backends=None,
                database=database,
                app_id=None,
                limit=20,
            )
            result = run_find_command(args, FindClient())

        assert result["status"] == "success"
        assert result["backends"] == {"operations": 1, "recipes": 0, "metadata": 1}
        assert {item["backend"] for item in result["results"]} == {
            "operations",
            "metadata",
        }


    def test_find_keeps_operation_results_when_metadata_catalog_is_missing(self):
        args = argparse.Namespace(
            query="retention",
            backends=None,
            database=Path("missing-fixture.sqlite3"),
            app_id=None,
            limit=20,
        )
        result = run_find_command(args, FindClient())

        assert result["status"] == "partial"
        assert result["count"] == 1
        assert result["errors"][0]["backend"] == "metadata"


    def test_find_includes_workspace_recipe_backend(self):
        args = argparse.Namespace(
            query="retention",
            backends=["recipes"],
            database=Path("missing-fixture.sqlite3"),
            app_id=None,
            limit=20,
        )
        workspace = load_workspace(ROOT / "examples" / "workspace" / "gravity.toml")

        result = run_find_command(args, FindClient(), workspace=workspace)

        assert result["status"] == "success"
        assert result["backends"] == {"recipes": 1}
        assert result["results"][0]["name"] == "demo-retention"
