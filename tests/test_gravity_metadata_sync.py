from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from gravity_sdk import GravitySDK, cli
from gravity_sdk.domains import ANALYSIS_METADATA_OPERATIONS
from gravity_sdk.errors import ContractChangedError, UpstreamError
from gravity_sdk.find_metadata import search_metadata
from gravity_sdk.metadata_lineage import (
    TABLE_LINEAGE_OPERATIONS,
    TABLE_OPERATION_LOG_OPERATION_ID,
    search_table_lineage,
)
from gravity_sdk.metadata_vocabulary import VOCABULARY_SOURCES
from gravity_sdk.metadata_sync import (
    _create_schema,
    _write_apps,
    _write_catalog_metadata,
    _write_rows,
    sync_all_apps,
)
from gravity_sdk.metadata_onboarding import sync_app
from gravity_sdk.metadata_status import metadata_status
from gravity_sdk.agent_catalog_refresh import refresh_complete_catalog


class FakeSyncClient:
    def __init__(
        self, *, failed_app: str | None = None, malformed_media: bool = False
    ) -> None:
        self.failed_app = failed_app
        self.malformed_media = malformed_media
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
            if app_id == "media_enums":
                media = (
                    {"bytedance": {"optimization_goal": {"secret": "hidden"}}}
                    if self.malformed_media
                    else {"bytedance": {"optimization_goal": [
                        {"code": "INSTALL", "name": "Install"}
                    ]}}
                )
                results.append({
                    "operation_id": operation_id,
                    "request_id": app_id,
                    "ok": True,
                    "status": "success",
                    "data": {"status": "success", "data": media},
                })
                continue
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


class FakeLineageClient(FakeSyncClient):
    def __init__(self, *, fail_lineage: bool = False) -> None:
        super().__init__()
        self.fail_lineage = fail_lineage

    def batch(self, requests: list[dict], max_workers: int = 6):
        if requests and all(
            request["operation_id"] in TABLE_LINEAGE_OPERATIONS
            for request in requests
        ):
            self.batch_calls.append((requests, max_workers))
            results = []
            for request in requests:
                operation_id = request["operation_id"]
                if self.fail_lineage and operation_id == TABLE_OPERATION_LOG_OPERATION_ID:
                    results.append(
                        {
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
                row = {
                    "id": f"source-{operation_id}",
                    "table_id": "table-7",
                    "version_id": "version-2",
                    "create_time": "2026-08-12T01:02:03Z",
                }
                if operation_id == TABLE_OPERATION_LOG_OPERATION_ID:
                    row.update(action_type="publish", action_sub_type="version")
                results.append(
                    {
                        "ok": True,
                        "status": "success",
                        "data": {"status": "success", "data": {"list": [row]}},
                    }
                )
            return results
        return super().batch(requests, max_workers=max_workers)


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
            self.assertNotIn("table_lineage_included", result)
            self.assertEqual(3, len(client.batch_calls))
            self.assertEqual([8, 8, 1], [call[1] for call in client.batch_calls])
            self.assertEqual(
                set(ANALYSIS_METADATA_OPERATIONS),
                {
                    request["operation_id"]
                    for request in client.batch_calls[0][0]
                },
            )
            self.assertEqual(8, len(client.batch_calls[0][0]))
            vocabulary_requests = [
                request
                for requests, _ in client.batch_calls[1:]
                for request in requests
            ]
            self.assertEqual(
                [source.operation_id for source in VOCABULARY_SOURCES],
                [request["operation_id"] for request in vocabulary_requests],
            )
            self.assertEqual(
                [source.source for source in VOCABULARY_SOURCES],
                [request["request_id"] for request in vocabulary_requests],
            )
            self.assertEqual(9, result["vocabulary_operation_count"])
            self.assertEqual(9, result["vocabulary_rows_written"])
            metric = search_metadata(
                "name-report_metrics", database=database, kind="metric"
            )
            media = search_metadata("INSTALL", database=database, kind="media_enum")
            self.assertEqual(
                ("workspace", "report_metrics"),
                (metric["results"][0]["scope"], metric["results"][0]["source"]),
            )
            self.assertEqual(
                {"platform": "bytedance", "group": "optimization_goal", "code": "INSTALL", "name": "Install"},
                media["results"][0]["payload"],
            )
            self.assertTrue(all(request["read_all"] for request in client.batch_calls[0][0]))
            self.assertEqual(
                [source.paginated for source in VOCABULARY_SOURCES],
                [request["read_all"] for request in vocabulary_requests],
            )
            stdout = io.StringIO()
            with (
                patch("gravity_sdk.cli.runtime.build_client") as build_client,
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = cli.main([
                    "metadata", "vocabulary", "INSTALL", "--kind", "media_enum",
                    "--database", str(database),
                ])
            self.assertEqual(0, exit_code)
            build_client.assert_not_called()
            self.assertNotIn("database", json.loads(stdout.getvalue()))

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

    def test_single_app_sync_is_bounded_preserves_apps_and_status_is_offline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            self._fixture_catalog(database)
            client = FakeSyncClient()

            result = sync_app(
                client, "202", database=database, max_pages=2, concurrency=4
            )
            status = metadata_status(
                database=database,
                app_id="202",
                now=datetime.now(timezone.utc),
            )
            all_status = metadata_status(database=database)
            stale_status = metadata_status(
                database=database,
                app_id="202",
                now=datetime(2099, 1, 1, tzinfo=timezone.utc),
            )
            sdk = GravitySDK(
                insight_factory=lambda: (_ for _ in ()).throw(
                    AssertionError("dry-run must not construct Insight")
                )
            )
            dry_run_sdk = sdk.sync_metadata_app("202", database=database, dry_run=True)
            status_sdk = sdk.metadata_status(database=database, app_id="202")

        self.assertEqual(("single_app", 7, 4), (
            result["scope"],
            result["request_budget"]["logical_request_upper_bound"],
            result["logical_requests_made"],
        ))
        self.assertEqual(2, result["catalog_app_count"])
        self.assertEqual(4, result["rows_written"])
        self.assertEqual(("ready", 4, False), (
            status["status"], status["results"][0]["row_count"],
            status["network_called"],
        ))
        self.assertEqual({"101", "202"}, {
            item["app_id"] for item in all_status["results"]
        })
        self.assertEqual("stale", stale_status["status"])
        self.assertFalse(dry_run_sdk["network_called"])
        self.assertEqual("ready", status_sdk["status"])

    def test_empty_compatible_catalog_is_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            with closing(sqlite3.connect(database)) as connection:
                _create_schema(connection)
                connection.commit()

            status = metadata_status(database=database)

        self.assertEqual(("not_synced", 0, False), (
            status["status"], status["count"], status["network_called"]
        ))

    def test_single_app_page_bound_persists_prefix_as_explicit_partial(self) -> None:
        class PagedClient(FakeSyncClient):
            def batch(self, requests: list[dict], max_workers: int = 6):
                results = super().batch(requests, max_workers=max_workers)
                for request, result in zip(requests, results, strict=True):
                    if request["operation_id"] == "analysis.event.list":
                        result["data"]["page"] = {
                            "number": request["inputs"]["page"], "total_pages": 3,
                        }
                return results

        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            result = sync_app(PagedClient(), "101", database=database, max_pages=2)
            status = metadata_status(database=database, app_id="101")

        self.assertEqual("partial", result["status"])
        self.assertEqual(2, result["operation_pages"]["analysis.event.list"]["pages_fetched"])
        self.assertEqual("PAGE_BOUND_REACHED", result["failures"][0]["code"])
        self.assertEqual(("partial", 1), (
            status["status"], status["results"][0]["failure_count"]
        ))

    def test_metadata_status_and_sync_estimate_cli_do_not_build_client(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite3"
            for argv, expected in (
                (["metadata", "status", "--database", str(database)], "missing"),
                ([
                    "metadata", "sync", "--app-id", "101", "--max-pages", "2",
                    "--database", str(database), "--dry-run",
                ], "estimate"),
            ):
                stdout = io.StringIO()
                with (
                    patch("gravity_sdk.cli.runtime.build_client") as build_client,
                    contextlib.redirect_stdout(stdout),
                ):
                    exit_code = cli.main(argv)
                self.assertEqual(0, exit_code)
                self.assertEqual(expected, json.loads(stdout.getvalue())["status"])
                build_client.assert_not_called()

            expected = {
                "schema_version": "gravity-insight.metadata-sync.v1",
                "ok": True, "status": "success", "exit_code": 0,
            }
            stdout = io.StringIO()
            with (
                patch("gravity_sdk.cli.runtime.build_client", return_value=object()),
                patch("gravity_sdk.metadata_cli.sync_app", return_value=expected) as app_sync,
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = cli.main([
                    "metadata", "sync", "--app-id", "101", "--max-pages", "2",
                    "--database", str(database),
                ])
            self.assertEqual(0, exit_code)
            self.assertEqual("success", json.loads(stdout.getvalue())["status"])
            self.assertEqual(("101", 2), (
                app_sync.call_args.args[1], app_sync.call_args.kwargs["max_pages"]
            ))

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

            database.write_bytes(b"previous-complete-catalog")
            guarded = refresh_complete_catalog(
                FakeSyncClient(failed_app="202"), database=database,
                include_table_lineage=False,
            )
            self.assertEqual("partial", guarded["status"])
            self.assertEqual(b"previous-complete-catalog", database.read_bytes())

        with tempfile.TemporaryDirectory() as temporary:
            malformed = sync_all_apps(
                FakeSyncClient(malformed_media=True),
                database=Path(temporary) / "metadata.sqlite3",
            )
        self.assertEqual(("partial", 1), (
            malformed["status"], malformed["vocabulary_failure_count"]
        ))

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

    def test_opt_in_lineage_replaces_atomically_and_is_searchable_offline(self) -> None:
        client = FakeLineageClient()
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            database.write_bytes(b"previous")
            result = sync_all_apps(
                client,
                database=database,
                concurrency=8,
                include_table_lineage=True,
            )
            found = search_table_lineage("publish", database=database)

        lineage_requests = client.batch_calls[-1][0]
        self.assertEqual(list(TABLE_LINEAGE_OPERATIONS), [
            item["operation_id"] for item in lineage_requests
        ])
        self.assertTrue(all(item["read_all"] for item in lineage_requests))
        self.assertTrue(result["table_lineage_included"])
        self.assertEqual(1, found["count"])
        self.assertTrue(found["offline"])
        self.assertEqual("account", found["scope"])
        self.assertEqual(
            {"table_id", "observed", "versions", "operations"},
            set(found["results"][0]),
        )
        self.assertNotIn("name", found["results"][0])
        self.assertNotIn("app_id", found["results"][0])
        self.assertNotIn("current_version", found["results"][0])

    def test_lineage_source_failure_preserves_previous_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            database.write_bytes(b"previous")
            with self.assertRaises(UpstreamError):
                sync_all_apps(
                    FakeLineageClient(fail_lineage=True),
                    database=database,
                    include_table_lineage=True,
                )
            self.assertEqual(b"previous", database.read_bytes())

    def test_metadata_tables_cli_does_not_build_a_client(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            sync_all_apps(
                FakeLineageClient(),
                database=database,
                include_table_lineage=True,
            )
            stdout = io.StringIO()
            with (
                patch("gravity_sdk.cli.runtime.build_client") as build_client,
                contextlib.redirect_stdout(stdout),
            ):
                exit_code = cli.main(
                    ["metadata", "tables", "table-7", "--database", str(database)]
                )
        self.assertEqual(0, exit_code)
        build_client.assert_not_called()
        self.assertTrue(json.loads(stdout.getvalue())["observed"])


if __name__ == "__main__":
    unittest.main()
