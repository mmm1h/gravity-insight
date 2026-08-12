from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from gravity_sdk import cli
from gravity_sdk.domains import ANALYSIS_METADATA_OPERATIONS
from gravity_sdk.errors import ContractChangedError
from gravity_sdk.find_metadata import search_metadata
from gravity_sdk.metadata_sync import (
    _create_schema,
    _write_apps,
    _write_catalog_metadata,
    _write_rows,
    sync_all_apps,
)


class FakeSyncClient:
    def __init__(self, *, failed_app: str | None = None) -> None:
        self.failed_app = failed_app
        self.batch_calls: list[tuple[list[dict], int]] = []

    def read_all(self, operation_id: str, inputs: dict):
        assert operation_id == "app.list"
        assert inputs == {}
        return {
            "status": "success",
            "data": {
                "list": [
                    {"id": 101, "name": "Alpha"},
                    {"id": "202", "name": "Beta"},
                ]
            },
        }

    def batch(self, requests: list[dict], max_workers: int = 6):
        self.batch_calls.append((requests, max_workers))
        results = []
        for request in requests:
            app_id = request["request_id"]
            operation_id = request["operation_id"]
            if app_id == self.failed_app:
                results.append(
                    {
                        "operation_id": operation_id,
                        "request_id": app_id,
                        "ok": False,
                        "status": "error",
                        "data": None,
                        "error": {
                            "category": "upstream",
                            "code": "UPSTREAM_UNAVAILABLE",
                        },
                    }
                )
                continue
            results.append(
                {
                    "operation_id": operation_id,
                    "request_id": app_id,
                    "ok": True,
                    "status": "success",
                    "data": {
                        "status": "success",
                        "data": {
                            "list": [
                                {
                                    "id": f"{app_id}-{operation_id}",
                                    "name": f"name-{app_id}",
                                    "cname": f"名称-{app_id}",
                                }
                            ]
                        },
                    },
                }
            )
        return results


class MetadataSyncTests(unittest.TestCase):
    def _fixture_catalog(self, database: Path) -> None:
        synced_at = "2026-08-10T00:00:00Z"
        with closing(sqlite3.connect(database)) as connection:
            _create_schema(connection)
            _write_apps(
                connection,
                [("101", {"id": 101, "name": "Alpha Game"})],
                synced_at,
            )
            _write_rows(
                connection,
                "101",
                "analysis.event.list",
                [{"name": "purchase", "cname": "支付成功"}],
                synced_at,
            )
            _write_rows(
                connection,
                "101",
                "analysis.user_property.list",
                [{"name": "demo_scene", "cname": "示例场景"}],
                synced_at,
            )
            _write_rows(
                connection,
                "101",
                "analysis.event_property.list",
                [{"name": "order_amount", "cname": "订单金额"}],
                synced_at,
            )
            _write_catalog_metadata(
                connection,
                synced_at=synced_at,
                status="success",
                app_count=1,
                rows_written=3,
                failure_count=0,
            )
            connection.commit()

    def test_fixture_catalog_searches_events_and_properties_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            self._fixture_catalog(database)

            search = search_metadata("支付", database=database)
            events = search_metadata(database=database, kind="event")
            properties = search_metadata("金额", database=database, kind="property")

        self.assertTrue(search["offline"])
        self.assertEqual(["purchase"], [item["name"] for item in search["results"]])
        self.assertEqual(["event"], [item["kind"] for item in events["results"]])
        self.assertEqual(
            ["order_amount"], [item["name"] for item in properties["results"]]
        )

    def test_fixture_search_treats_sql_wildcards_as_literals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            self._fixture_catalog(database)
            result = search_metadata("%", database=database)
        self.assertEqual(0, result["count"])

    def test_metadata_search_cli_uses_fixture_without_building_a_client(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            self._fixture_catalog(database)
            stdout = io.StringIO()
            with (
                patch("gravity_sdk.cli.runtime.build_client") as build_client,
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = cli.main(
                    [
                        "metadata",
                        "search",
                        "purchase",
                        "--database",
                        str(database),
                        "--limit",
                        "1",
                        "--offset",
                        "0",
                    ]
                )
        self.assertEqual(0, exit_code)
        build_client.assert_not_called()
        result = json.loads(stdout.getvalue())
        self.assertTrue(result["offline"])
        self.assertEqual(1, result["limit"])
        self.assertEqual(0, result["offset"])
        self.assertEqual("purchase", result["results"][0]["name"])

    def test_sync_all_apps_persists_every_catalog_atomically(self) -> None:
        client = FakeSyncClient()
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            result = sync_all_apps(client, database=database, concurrency=8)

            self.assertTrue(result["ok"])
            self.assertEqual("success", result["status"])
            self.assertEqual(0, result["exit_code"])
            self.assertEqual(2, result["app_count"])
            self.assertEqual(8, result["operation_count"])
            self.assertEqual(8, result["rows_written"])
            self.assertEqual(1, len(client.batch_calls))
            self.assertTrue(all(call[1] == 8 for call in client.batch_calls))
            self.assertEqual(
                set(ANALYSIS_METADATA_OPERATIONS),
                {
                    request["operation_id"]
                    for request in client.batch_calls[0][0]
                },
            )
            self.assertEqual(8, len(client.batch_calls[0][0]))
            self.assertTrue(
                all(
                    request["read_all"]
                    for requests, _ in client.batch_calls
                    for request in requests
                )
            )

            with closing(sqlite3.connect(database)) as connection:
                app_count = connection.execute("SELECT COUNT(*) FROM apps").fetchone()[0]
                row_count = connection.execute(
                    "SELECT COUNT(*) FROM metadata_rows"
                ).fetchone()[0]
                status = connection.execute(
                    "SELECT value FROM catalog_metadata WHERE key = 'status'"
                ).fetchone()[0]
                failure_count = connection.execute(
                    "SELECT COUNT(*) FROM sync_failures"
                ).fetchone()[0]
            self.assertEqual(2, app_count)
            self.assertEqual(8, row_count)
            self.assertEqual("success", status)
            self.assertEqual(0, failure_count)

    def test_partial_sync_records_failures_and_returns_upstream_exit(self) -> None:
        client = FakeSyncClient(failed_app="202")
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            result = sync_all_apps(client, database=database, concurrency=4)

            self.assertFalse(result["ok"])
            self.assertEqual("partial", result["status"])
            self.assertEqual(3, result["exit_code"])
            self.assertEqual(4, result["failure_count"])
            self.assertEqual(4, result["rows_written"])
            with closing(sqlite3.connect(database)) as connection:
                failures = connection.execute(
                    "SELECT app_id, operation_id, code FROM sync_failures ORDER BY operation_id"
                ).fetchall()
            self.assertEqual(4, len(failures))
            self.assertTrue(all(row[0] == "202" for row in failures))

    def test_invalid_app_catalog_keeps_previous_database(self) -> None:
        class InvalidAppClient(FakeSyncClient):
            def read_all(self, operation_id: str, inputs: dict):
                return {"status": "success", "data": {"list": [{"name": "missing"}]}}

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            database.write_bytes(b"previous")
            with self.assertRaises(ContractChangedError):
                sync_all_apps(InvalidAppClient(), database=database)
            self.assertEqual(b"previous", database.read_bytes())


if __name__ == "__main__":
    unittest.main()
