import copy
import io
import json
import os
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from gravity_sdk.sql import __main__ as gravity_cli
from gravity_sdk.sql.client import GravityClient
try:
    from gravity_sdk.errors import AuthenticationError, CredentialError, TransportError
except ModuleNotFoundError:  # pragma: no cover - source-tree test execution.
    from gravity_sdk.errors import AuthenticationError, CredentialError, TransportError
from gravity_sdk.sql.products import (
    BEIJING,
    EvidenceFormatError,
    build_evidence,
    build_sql,
    day_window,
    evidence_preflight,
    _credential_source,
    latest_safe_date,
    publish_evidence,
    read_evidence,
    readiness_status,
    resolve_current_evidence,
    run_product,
    run_product_queries,
    summarize_custom,
    verify_all,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_WORKSPACE = ROOT / "examples" / "workspace" / "gravity.toml"


class _AggregateClient:
    def execute_sql(self, sql):
        self.sql = sql
        return [{"app_id": 1001, "event_name": "DemoEvent", "event_count": 2}]


class GravityProductTests(unittest.TestCase):
    def setUp(self):
        self.workspace_environment = mock.patch.dict(
            os.environ, {"GRAVITY_WORKSPACE": str(EXAMPLE_WORKSPACE)}
        )
        self.workspace_environment.start()
        self.addCleanup(self.workspace_environment.stop)

    def test_latest_safe_day_changes_at_0200_beijing(self):
        self.assertEqual(
            date(2026, 7, 21),
            latest_safe_date(datetime(2026, 7, 23, 1, 59, 59, tzinfo=BEIJING)),
        )
        self.assertEqual(
            date(2026, 7, 22),
            latest_safe_date(datetime(2026, 7, 23, 2, 0, 0, tzinfo=BEIJING)),
        )

    def test_workspace_product_projects_only_declared_aggregate_fields(self):
        start_at, end_at = day_window(date(2026, 7, 22))
        result = run_product(
            _AggregateClient(), "daily-event-summary", start_at, end_at
        )

        self.assertEqual("complete", result["status"])
        self.assertEqual([], result["warnings"])
        self.assertTrue(result["forbidden_claims"])
        self.assertEqual(
            [{"app_id": 1001, "event_name": "DemoEvent", "event_count": 2}],
            result["summary"]["rows"],
        )

    def test_generic_summary_rejects_rows_above_workspace_limit(self):
        start_at, end_at = day_window(date(2026, 7, 22))
        with self.assertRaisesRegex(EvidenceFormatError, "max_rows=1"):
            summarize_custom(
                [{"app_id": 1001}, {"app_id": 1001}],
                (1001,),
                start_at,
                end_at,
                output_fields=["app_id"],
                max_rows=1,
                measurement="aggregate",
            )

    def test_evidence_atomic_round_trip_and_contract_drift_rejects_query(self):
        day = date(2026, 7, 22)
        start_at, end_at = day_window(day)
        client = _AggregateClient()
        results = [
            run_product(client, product, start_at, end_at)
            for product in ("daily-event-summary",)
        ]
        evidence = build_evidence(day, results)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "gravity-latest.json"
            publish_evidence(evidence, path)
            self.assertEqual(evidence, read_evidence(path))
            self.assertEqual([], list(path.parent.glob("*.tmp")))

            original = path.read_text(encoding="utf-8")
            with mock.patch("gravity_sdk.sql.products.os.replace", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    publish_evidence(evidence, path)
            self.assertEqual(original, path.read_text(encoding="utf-8"))
            self.assertEqual([], list(path.parent.glob("*.tmp")))

            path.write_bytes(b"\xff")
            with self.assertRaises(EvidenceFormatError):
                read_evidence(path)

        now = datetime(2026, 7, 23, 12, tzinfo=BEIJING)
        with mock.patch(
            "gravity_sdk.sql.products.datasource_verification_status",
            return_value="verified_with_gaps",
        ):
            self.assertTrue(readiness_status(evidence, now)["query_ready"])
            tampered = copy.deepcopy(evidence)
            tampered["products"]["daily-event-summary"]["summary"]["rows"][0]["event_count"] = 999999
            with self.assertRaises(EvidenceFormatError):
                readiness_status(tampered, now)
            stripped = copy.deepcopy(evidence)
            stripped["warnings"] = stripped["warnings"][:1]
            stripped["forbidden_claims"] = ["allowed"]
            with self.assertRaises(EvidenceFormatError):
                readiness_status(stripped, now)
            for invalid_version in ("1", True):
                invalid_schema = copy.deepcopy(evidence)
                invalid_schema["schema_version"] = invalid_version
                with self.assertRaises(EvidenceFormatError):
                    readiness_status(invalid_schema, now)
            with mock.patch("gravity_sdk.sql.products.contract_hash", return_value="0" * 64):
                status = readiness_status(evidence, now)
        self.assertEqual("stale", status["status"])
        self.assertFalse(status["query_ready"])

        with mock.patch(
            "gravity_sdk.sql.products.datasource_verification_status",
            return_value="verified_with_gaps",
        ), mock.patch("gravity_sdk.sql.products.build_sql", return_value="SELECT 'drift'"):
            self.assertEqual("stale", readiness_status(evidence, now)["status"])

        with self.assertRaises(EvidenceFormatError):
            build_evidence(day, results + [results[0]])

    def test_canonical_publish_keeps_rolling_compatibility_and_creates_snapshot(self):
        day = date(2026, 7, 22)
        start_at, end_at = day_window(day)
        client = _AggregateClient()
        evidence = build_evidence(
            day,
            [
                run_product(client, product, start_at, end_at)
                for product in ("daily-event-summary",)
            ],
        )
        with tempfile.TemporaryDirectory() as temporary:
            rolling = Path(temporary) / "gravity-latest.json"
            product_root = Path(temporary) / "gravity-daily-verification"
            with mock.patch("gravity_sdk.sql.products.EVIDENCE_PATH", rolling), mock.patch(
                "gravity_sdk.sql.products.EVIDENCE_PRODUCT_ROOT", product_root
            ), mock.patch(
                "gravity_sdk.sql.products._git_state", return_value=("a" * 40, True)
            ), mock.patch(
                "gravity_sdk.sql.products.load_workspace",
                side_effect=AssertionError("publish reloaded its bound workspace"),
            ):
                from gravity_sdk.workspace import load_workspace

                publish_evidence(
                    evidence,
                    rolling,
                    workspace=load_workspace(EXAMPLE_WORKSPACE),
                )

            self.assertEqual(evidence, read_evidence(rolling))
            self.assertTrue((product_root / "latest.yaml").is_file())
            snapshots = list((product_root / "snapshots").glob("*/result.json"))
            self.assertEqual(1, len(snapshots))
            self.assertEqual(rolling.read_bytes(), snapshots[0].read_bytes())
            binding = resolve_current_evidence(product_root)
            self.assertEqual(evidence, binding.result)
            self.assertEqual(snapshots[0].parent.name, binding.reference()["snapshot_id"])
            self.assertEqual(binding.snapshot.manifest["result_sha256"], binding.reference()["result_sha256"])

    def test_canonical_publish_does_not_advance_rolling_file_when_snapshot_fails(self):
        day = date(2026, 7, 22)
        start_at, end_at = day_window(day)
        client = _AggregateClient()
        evidence = build_evidence(
            day,
            [
                run_product(client, product, start_at, end_at)
                for product in ("daily-event-summary",)
            ],
        )
        with tempfile.TemporaryDirectory() as temporary:
            rolling = Path(temporary) / "gravity-latest.json"
            rolling.write_text('{"previous": true}\n', encoding="utf-8")
            before = rolling.read_bytes()
            with mock.patch("gravity_sdk.sql.products.EVIDENCE_PATH", rolling), mock.patch(
                "gravity_sdk.sql.products.EVIDENCE_PRODUCT_ROOT",
                Path(temporary) / "gravity-daily-verification",
            ), mock.patch(
                "gravity_sdk.sql.products._git_state", return_value=("a" * 40, True)
            ), mock.patch(
                "gravity_sdk.sql.products.publish_json_snapshot",
                side_effect=OSError("snapshot failed"),
            ):
                with self.assertRaisesRegex(OSError, "snapshot failed"):
                    publish_evidence(evidence, rolling)

            self.assertEqual(before, rolling.read_bytes())
            self.assertEqual([], list(rolling.parent.glob("*.tmp")))

    def test_query_evidence_not_ready_warns_without_blocking_product(self):
        binding = mock.Mock()
        binding.reference.return_value = {
            "snapshot_id": "older-snapshot",
            "result_sha256": "a" * 64,
        }
        output = io.StringIO()
        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            [
                "gravity_sdk.sql",
                "query",
                "daily-event-summary",
                "--start",
                "2026-07-22T00:00:00",
                "--end",
                "2026-07-23T00:00:00",
            ],
        ), mock.patch("gravity_sdk.sql.__main__.resolve_current_evidence", return_value=binding), mock.patch(
            "gravity_sdk.sql.__main__.readiness_status",
            return_value={"query_ready": False, "status": "pending_review", "reason": "missing"},
        ), mock.patch(
            "gravity_sdk.sql.__main__._client", return_value=_AggregateClient()
        ), redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(0, gravity_cli.main())

        payload = json.loads(output.getvalue())
        self.assertEqual("complete", payload["status"])
        self.assertEqual("daily-event-summary", payload["product"])
        self.assertEqual("older-snapshot", payload["evidence_reference"]["snapshot_id"])
        self.assertIn("pending_review", payload["evidence_warning"])

    def test_bad_evidence_credentials_and_injection_have_stable_failures(self):

        with mock.patch.object(
            gravity_cli.sys, "argv", ["gravity_sdk.sql", "status", "--json"]
        ), mock.patch(
            "gravity_sdk.sql.__main__.resolve_current_evidence",
            side_effect=EvidenceFormatError("bad evidence"),
        ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(2, gravity_cli.main())

        credential_error = io.StringIO()
        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            [
                "gravity_sdk.sql",
                "query",
                "daily-event-summary",
                "--start",
                "2026-07-22T00:00:00",
                "--end",
                "2026-07-23T00:00:00",
            ],
        ), mock.patch("gravity_sdk.sql.__main__.resolve_current_evidence", return_value=mock.Mock()), mock.patch(
            "gravity_sdk.sql.__main__.readiness_status",
            return_value={"query_ready": True},
        ), mock.patch(
            "gravity_sdk.sql.__main__._client",
            side_effect=CredentialError("secret credential path token=abc123"),
        ), redirect_stdout(
            io.StringIO()
        ), redirect_stderr(credential_error):
            self.assertEqual(2, gravity_cli.main())
        credential_payload = json.loads(credential_error.getvalue())
        self.assertEqual("authentication", credential_payload["error"]["category"])
        self.assertEqual(
            "SQL_PRODUCT_CREDENTIALS_UNAVAILABLE",
            credential_payload["error"]["code"],
        )
        self.assertEqual(2, credential_payload["exit_code"])
        self.assertIn("gravity auth status", credential_payload["error"]["next_action"])
        self.assertNotIn("abc123", credential_error.getvalue())

        injection_error = io.StringIO()
        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            [
                "gravity_sdk.sql",
                "query",
                "daily-event-summary",
                "--start",
                "2026-07-22T00:00:00' OR 1=1",
                "--end",
                "2026-07-23T00:00:00",
            ],
        ), mock.patch("gravity_sdk.sql.__main__.resolve_current_evidence", return_value=mock.Mock()), mock.patch(
            "gravity_sdk.sql.__main__.readiness_status",
            return_value={"query_ready": True},
        ), mock.patch("gravity_sdk.sql.__main__._client") as client, redirect_stdout(
            io.StringIO()
        ), redirect_stderr(injection_error):
            self.assertEqual(2, gravity_cli.main())
            client.assert_not_called()
        injection_payload = json.loads(injection_error.getvalue())
        self.assertEqual("SQL_PRODUCT_WINDOW_INVALID", injection_payload["error"]["code"])
        self.assertEqual("start/end", injection_payload["error"]["field"])
        self.assertNotIn("OR 1=1", injection_error.getvalue())

        unknown_error = io.StringIO()
        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            [
                "gravity_sdk.sql",
                "query",
                "missing token=abc123",
                "--start",
                "2026-07-22T00:00:00",
                "--end",
                "2026-07-23T00:00:00",
            ],
        ), mock.patch("gravity_sdk.sql.__main__._client") as client, redirect_stdout(
            io.StringIO()
        ), redirect_stderr(unknown_error):
            self.assertEqual(2, gravity_cli.main())
            client.assert_not_called()
        unknown_payload = json.loads(unknown_error.getvalue())
        self.assertEqual("SQL_PRODUCT_UNKNOWN", unknown_payload["error"]["code"])
        self.assertEqual("product", unknown_payload["error"]["field"])
        self.assertNotIn("abc123", unknown_error.getvalue())

        local_error = io.StringIO()
        secret_path = r"C:\Users\alice\.secret token=abc123.json"
        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            ["gravity_sdk.sql", "query", "--input", secret_path],
        ), redirect_stdout(io.StringIO()), redirect_stderr(local_error):
            self.assertEqual(4, gravity_cli.main())
        local_payload = json.loads(local_error.getvalue())
        self.assertEqual("local_io", local_payload["error"]["category"])
        self.assertEqual("SQL_PRODUCT_LOCAL_IO", local_payload["error"]["code"])
        self.assertEqual(4, local_payload["exit_code"])
        self.assertNotIn("alice", local_error.getvalue())
        self.assertNotIn("abc123", local_error.getvalue())

        start_at, end_at = day_window(date(2026, 7, 22))
        with self.assertRaises(ValueError):
            build_sql("daily-event-summary", start_at, end_at, ("1001 OR 1=1",))

    def test_query_output_carries_one_immutable_evidence_reference(self):
        binding = mock.Mock()
        binding.reference.return_value = {"snapshot_id": "synthetic-snapshot", "result_sha256": "a" * 64}
        output = io.StringIO()
        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            [
                "gravity_sdk.sql",
                "query",
                "daily-event-summary",
                "--start",
                "2026-07-22T00:00:00",
                "--end",
                "2026-07-23T00:00:00",
            ],
        ), mock.patch(
            "gravity_sdk.sql.__main__.resolve_current_evidence", return_value=binding
        ) as resolver, mock.patch(
            "gravity_sdk.sql.__main__.readiness_status", return_value={"query_ready": True}
        ), mock.patch(
            "gravity_sdk.sql.__main__._client", return_value=_AggregateClient()
        ), redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(0, gravity_cli.main())

        resolver.assert_called_once()
        self.assertIsNotNone(resolver.call_args.kwargs["workspace"])
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual("complete", payload["status"])
        self.assertEqual("synthetic-snapshot", payload["evidence_reference"]["snapshot_id"])

    def test_products_command_is_one_safe_discovery_call(self):
        output = io.StringIO()
        with mock.patch.object(
            gravity_cli.sys, "argv", ["gravity_sdk.sql", "products"]
        ), redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(0, gravity_cli.main())

        payload = json.loads(output.getvalue())
        self.assertEqual("gravity-sql.products.v1", payload["schema_version"])
        self.assertEqual(1, payload["count"])
        product = payload["products"][0]
        self.assertEqual("daily-event-summary", product["name"])
        self.assertNotIn("sql", product)
        self.assertEqual(2, payload["query_input"]["max_concurrency"])

    def test_dry_run_query_emits_offline_safe_plan_without_runtime_or_evidence(self):
        output = io.StringIO()
        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            [
                "gravity_sdk.sql",
                "--dry-run",
                "query",
                "daily-event-summary",
                "--start",
                "2026-07-22T00:00:00+08:00",
                "--end",
                "2026-07-23T00:00:00+08:00",
            ],
        ), mock.patch("gravity_sdk.sql.__main__._client") as client, mock.patch(
            "gravity_sdk.sql.__main__.resolve_current_evidence"
        ) as evidence, redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(0, gravity_cli.main())

        client.assert_not_called()
        evidence.assert_not_called()
        payload = json.loads(output.getvalue())
        self.assertEqual("gravity-sql.query-plan.v1", payload["schema_version"])
        self.assertEqual("validated", payload["status"])
        self.assertTrue(payload["offline"])
        self.assertFalse(payload["network_called"])
        self.assertEqual(1, payload["requested_count"])
        self.assertEqual("daily-event-summary", payload["requests"][0]["product"])
        self.assertEqual([1001], payload["requests"][0]["app_ids"])
        self.assertNotIn("SELECT", output.getvalue())
        self.assertNotIn("credential", output.getvalue().casefold())

    def test_dry_run_query_validates_batch_and_preserves_request_order(self):
        requests = [
            {
                "product": "daily-event-summary",
                "start": "2026-07-22T00:00:00+08:00",
                "end": "2026-07-23T00:00:00+08:00",
                "request_id": str(index),
            }
            for index in range(2)
        ]
        output = io.StringIO()
        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            [
                "gravity_sdk.sql",
                "--dry-run",
                "query",
                "--input",
                json.dumps({"requests": requests}),
            ],
        ), mock.patch("gravity_sdk.sql.__main__._client") as client, redirect_stdout(
            output
        ), redirect_stderr(io.StringIO()):
            self.assertEqual(0, gravity_cli.main())

        client.assert_not_called()
        payload = json.loads(output.getvalue())
        self.assertEqual(["0", "1"], [item["request_id"] for item in payload["requests"]])
        self.assertEqual(2, payload["concurrency"])

    def test_dry_run_query_invalid_input_is_stable_and_never_builds_client(self):
        error = io.StringIO()
        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            [
                "gravity_sdk.sql",
                "--dry-run",
                "query",
                "daily-event-summary",
                "--start",
                "not-a-time",
                "--end",
                "2026-07-23T00:00:00+08:00",
            ],
        ), mock.patch("gravity_sdk.sql.__main__._client") as client, redirect_stdout(
            io.StringIO()
        ), redirect_stderr(error):
            self.assertEqual(2, gravity_cli.main())

        client.assert_not_called()
        payload = json.loads(error.getvalue())
        self.assertEqual("gravity-sql.query-plan.v1", payload["schema_version"])
        self.assertTrue(payload["offline"])
        self.assertFalse(payload["network_called"])
        self.assertEqual("SQL_DRY_RUN_INPUT_INVALID", payload["error"]["code"])
        self.assertNotIn("not-a-time", error.getvalue())

    def test_dry_run_rejects_commands_that_may_access_external_state(self):
        for argv, patch_target in (
            (["gravity_sdk.sql", "--dry-run", "verify"], "verify_all"),
            (
                ["gravity_sdk.sql", "--dry-run", "credentials", "pull"],
                "credentials.pull",
            ),
        ):
            with self.subTest(argv=argv):
                error = io.StringIO()
                with mock.patch.object(gravity_cli.sys, "argv", argv), mock.patch(
                    f"gravity_sdk.sql.__main__.{patch_target}"
                ) as external, redirect_stdout(io.StringIO()), redirect_stderr(error):
                    self.assertEqual(2, gravity_cli.main())
                external.assert_not_called()
                payload = json.loads(error.getvalue())
                self.assertFalse(payload["network_called"])
                self.assertEqual(
                    "SQL_DRY_RUN_COMMAND_NOT_OFFLINE", payload["error"]["code"]
                )

    def test_standalone_dry_run_self_check_is_preserved(self):
        output = io.StringIO()
        with mock.patch.object(
            gravity_cli.sys, "argv", ["gravity_sdk.sql", "--dry-run"]
        ), mock.patch("gravity_sdk.sql.__main__._client") as client, redirect_stdout(
            output
        ), redirect_stderr(io.StringIO()):
            self.assertEqual(0, gravity_cli.main())

        client.assert_not_called()
        self.assertEqual("PASS gravity dry-run\n", output.getvalue())

    def test_query_input_accepts_inline_file_and_stdin_forms(self):
        parser = gravity_cli.build_parser(("daily-event-summary",))
        inline = parser.parse_args(
            [
                "query",
                "--input",
                '{"product":"daily-event-summary","start":"2026-07-22T00:00:00","end":"2026-07-23T00:00:00"}',
            ]
        )
        self.assertEqual(1, len(gravity_cli._query_requests(inline)))

        requests = [
            {
                "product": "daily-event-summary",
                "start": "2026-07-22T00:00:00",
                "end": "2026-07-23T00:00:00",
                "request_id": str(index),
            }
            for index in range(2)
        ]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "queries.json"
            path.write_text(json.dumps(requests), encoding="utf-8")
            from_file = parser.parse_args(["query", "--input", str(path)])
            self.assertEqual(requests, gravity_cli._query_requests(from_file))

        from_stdin = parser.parse_args(["query", "--input", "-"])
        with mock.patch.object(
            gravity_cli.sys,
            "stdin",
            io.StringIO(json.dumps({"requests": requests})),
        ):
            self.assertEqual(requests, gravity_cli._query_requests(from_stdin))

    def test_batch_query_cli_emits_one_ordered_machine_envelope(self):
        requests = [
            {
                "product": "daily-event-summary",
                "start": "2026-07-22T00:00:00",
                "end": "2026-07-23T00:00:00",
                "request_id": str(index),
            }
            for index in range(3)
        ]
        output = io.StringIO()
        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            ["gravity_sdk.sql", "query", "--input", json.dumps(requests)],
        ), mock.patch(
            "gravity_sdk.sql.__main__.resolve_current_evidence",
            side_effect=EvidenceFormatError("missing"),
        ), mock.patch(
            "gravity_sdk.sql.__main__._client", return_value=_AggregateClient()
        ), redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(0, gravity_cli.main())

        payload = json.loads(output.getvalue())
        self.assertEqual("gravity-sql.query.v1", payload["schema_version"])
        self.assertEqual(3, payload["succeeded_count"])
        self.assertEqual(
            ["0", "1", "2"],
            [item["request_id"] for item in payload["results"]],
        )
        self.assertIsNone(payload["evidence_reference"])
        self.assertIn("without an Evidence reference", payload["evidence_warning"])

    def test_product_batch_defaults_to_concurrent_ordered_isolated_execution(self):
        lock = threading.Lock()
        active = 0
        max_active = 0

        class ConcurrentAggregateClient:
            def execute_sql(self, _sql):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                try:
                    time.sleep(0.02)
                    return [
                        {
                            "app_id": 1001,
                            "event_name": "DemoEvent",
                            "event_count": 2,
                        }
                    ]
                finally:
                    with lock:
                        active -= 1

        requests = [
            {
                "product": "daily-event-summary",
                "start": "2026-07-22T00:00:00",
                "end": "2026-07-23T00:00:00",
                "request_id": str(index),
            }
            for index in range(4)
        ]
        requests.insert(
            2,
            {
                "product": "missing-product token=abc123",
                "start": "2026-07-22T00:00:00",
                "end": "2026-07-23T00:00:00",
                "request_id": "invalid",
            },
        )

        result = run_product_queries(ConcurrentAggregateClient(), requests)

        self.assertEqual("partial", result["status"])
        self.assertEqual(4, result["succeeded_count"])
        self.assertEqual(1, result["failed_count"])
        self.assertEqual(2, max_active)
        self.assertEqual(
            ["0", "1", "invalid", "2", "3"],
            [item["request_id"] for item in result["results"]],
        )
        self.assertEqual("input", result["results"][2]["error"]["category"])
        self.assertEqual("SQL_PRODUCT_UNKNOWN", result["results"][2]["error"]["code"])
        self.assertEqual("product", result["results"][2]["error"]["field"])
        self.assertEqual(2, result["results"][2]["exit_code"])
        self.assertIn("gravity sql products", result["results"][2]["error"]["next_action"])
        self.assertNotIn("token=abc123", json.dumps(result))
        for invalid in (0, 3, True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                run_product_queries(
                    ConcurrentAggregateClient(), requests, max_workers=invalid
                )

        missing_credentials = mock.Mock()
        missing_credentials.execute_sql.side_effect = CredentialError(
            "secret credential path"
        )
        auth_result = run_product_queries(missing_credentials, [requests[0]])
        self.assertEqual(2, auth_result["exit_code"])
        self.assertEqual(
            "authentication", auth_result["results"][0]["error"]["category"]
        )
        self.assertNotIn("secret", str(auth_result))

        expired = mock.Mock()
        expired.execute_sql.side_effect = AuthenticationError("expired secret")
        expired_result = run_product_queries(expired, [requests[0]])
        self.assertEqual(2, expired_result["exit_code"])
        self.assertEqual(
            "authentication", expired_result["results"][0]["error"]["category"]
        )
        self.assertIn(
            "gravity auth status",
            expired_result["results"][0]["error"]["next_action"],
        )

        class ContractThenRuntime:
            calls = 0

            def execute_sql(self, _sql):
                self.calls += 1
                if self.calls == 1:
                    return ["not-an-object"]
                raise RuntimeError("upstream failed")

        mixed = run_product_queries(
            ContractThenRuntime(),
            [requests[0], requests[1]],
            max_workers=1,
        )
        self.assertEqual(4, mixed["exit_code"])
        self.assertEqual([4, 3], [item["exit_code"] for item in mixed["results"]])

        invalid_window = run_product_queries(
            ConcurrentAggregateClient(),
            [
                {
                    "product": "daily-event-summary",
                    "start": "2026-07-23T00:00:00",
                    "end": "2026-07-22T00:00:00",
                }
            ],
        )
        window_error = invalid_window["results"][0]["error"]
        self.assertEqual("SQL_PRODUCT_WINDOW_INVALID", window_error["code"])
        self.assertEqual("start/end", window_error["field"])

    def test_product_batch_uses_explicit_workspace_after_environment_changes(self):
        from gravity_sdk.workspace import load_workspace

        workspace = load_workspace(EXAMPLE_WORKSPACE)
        request = {
            "product": "daily-event-summary",
            "start": "2026-07-22T00:00:00",
            "end": "2026-07-23T00:00:00",
        }
        missing = ROOT / "examples" / "missing-gravity.toml"
        with mock.patch.dict(os.environ, {"GRAVITY_WORKSPACE": str(missing)}):
            result = run_product_queries(
                _AggregateClient(),
                [request],
                workspace=workspace,
            )

        self.assertTrue(result["ok"])
        self.assertEqual([1001], result["results"][0]["app_ids"])

    def test_verify_all_runs_independent_products_concurrently(self):
        lock = threading.Lock()
        active = 0
        max_active = 0

        def fake_run(_client, product, start_at, end_at, *, workspace=None):
            self.assertIsNotNone(workspace)
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.02)
                return {"product": product, "window": [start_at, end_at]}
            finally:
                with lock:
                    active -= 1

        with mock.patch(
            "gravity_sdk.sql.products.product_names", return_value=("one", "two")
        ), mock.patch(
            "gravity_sdk.sql.products.run_product", side_effect=fake_run
        ), mock.patch(
            "gravity_sdk.sql.products.build_evidence",
            side_effect=lambda _day, results, **_options: {"results": results},
        ):
            result = verify_all(mock.Mock(), date(2026, 7, 22))

        self.assertEqual(
            ["one", "two"], [item["product"] for item in result["results"]]
        )
        self.assertEqual(2, max_active)

    def test_query_and_verify_bind_ambient_workspace_once(self):
        from gravity_sdk.workspace import load_workspace

        workspace = load_workspace(EXAMPLE_WORKSPACE)
        request = {
            "product": "daily-event-summary",
            "start": "2026-07-22T00:00:00",
            "end": "2026-07-23T00:00:00",
        }
        no_reload = mock.patch(
            "gravity_sdk.sql.products.load_workspace",
            side_effect=AssertionError("workspace was reloaded inside one operation"),
        )
        with mock.patch(
            "gravity_sdk.sql.query.load_workspace", return_value=workspace
        ) as query_load, no_reload:
            queried = run_product_queries(
                _AggregateClient(), [request, request], max_workers=1
            )
        self.assertTrue(queried["ok"])
        query_load.assert_called_once_with()

        with mock.patch(
            "gravity_sdk.sql.verification.load_workspace", return_value=workspace
        ) as verify_load, mock.patch(
            "gravity_sdk.sql.products.load_workspace",
            side_effect=AssertionError("workspace was reloaded during verification"),
        ):
            evidence = verify_all(
                _AggregateClient(), date(2026, 7, 22), max_workers=1
            )
        self.assertEqual([1001], evidence["products"]["daily-event-summary"]["app_ids"])
        verify_load.assert_called_once_with()

    def test_evidence_preflight_is_offline_and_redacts_credentials(self):
        binding = mock.Mock()
        binding.reference.return_value = {"snapshot_id": "snapshot", "result_sha256": "a" * 64}

        def fake_git(args, **_kwargs):
            if args[1:3] == ["rev-parse", "HEAD"]:
                return mock.Mock(returncode=0, stdout="b" * 40 + "\n")
            if args[1:3] == ["branch", "--show-current"]:
                return mock.Mock(returncode=0, stdout="codex/test\n")
            return mock.Mock(returncode=0, stdout=b"")

        with mock.patch("gravity_sdk.sql.products.subprocess.run", side_effect=fake_git), mock.patch(
            "gravity_sdk.sql.products._credential_source", return_value="ignored_local_file"
        ), mock.patch(
            "gravity_sdk.sql.products.resolve_current_evidence", return_value=binding
        ), mock.patch(
            "gravity_sdk.sql.products.readiness_status",
            return_value={"status": "stale", "query_ready": False, "reason": "test"},
        ):
            result = evidence_preflight(date(2026, 7, 22), now=datetime(2026, 7, 23, 12, tzinfo=BEIJING))

        self.assertTrue(result["offline_checks_passed"])
        self.assertFalse(result["network_called"])
        self.assertEqual(
            {
                "schema_version",
                "mode",
                "network_called",
                "target_date",
                "latest_safe_date",
                "data_window",
                "gravity_profile",
                "gravity_credential_present",
                "gravity_credential_source",
                "current_branch",
                "git_sha",
                "git_dirty",
                "python_version",
                "working_tree_clean_or_scoped",
                "current_evidence",
                "current_readiness",
                "offline_checks_passed",
                "offline_blockers",
                "requires_explicit_live_read_authorization",
                "requires_separate_publish_authorization",
            },
            set(result),
        )
        self.assertNotIn("token", str(result).lower())

    def test_credential_source_accepts_account_password_login(self):
        with tempfile.TemporaryDirectory() as tempdir, mock.patch.dict(
            "os.environ",
            {"GRAVITY_USERNAME": "account", "GRAVITY_PASSWORD": "password"},
            clear=True,
        ):
            self.assertEqual("environment", _credential_source(Path(tempdir)))

        with tempfile.TemporaryDirectory() as tempdir, mock.patch.dict(
            "os.environ", {}, clear=True
        ):
            Path(tempdir, ".env.gravity.local").write_text(
                "GRAVITY_USERNAME=account\nGRAVITY_PASSWORD=password\n",
                encoding="utf-8",
            )
            self.assertEqual("local_account_file", _credential_source(Path(tempdir)))

    def test_credential_subprocess_falls_back_when_state_root_is_absent(self):
        completed = __import__("subprocess").CompletedProcess(["tool"], 0, b"", b"")
        with tempfile.TemporaryDirectory() as temporary:
            missing_root = Path(temporary) / "not-created"
            with mock.patch.object(gravity_cli.credentials, "ROOT", missing_root), mock.patch.object(
                gravity_cli.credentials.subprocess, "run", return_value=completed
            ) as run:
                gravity_cli.credentials._run(["tool"], check=False)

        self.assertEqual(Path.cwd(), run.call_args.kwargs["cwd"])

    def test_evidence_preflight_cli_is_offline_json(self):
        output = io.StringIO()
        payload = {"mode": "offline_preflight_only", "network_called": False}
        with mock.patch.object(
            gravity_cli.sys, "argv", ["gravity_sdk.sql", "evidence-preflight", "--json"]
        ), mock.patch(
            "gravity_sdk.sql.__main__.evidence_preflight", return_value=payload
        ) as preflight, mock.patch(
            "gravity_sdk.sql.__main__._client"
        ) as client, redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(0, gravity_cli.main())

        preflight.assert_called_once()
        self.assertIsNone(preflight.call_args.args[0])
        self.assertIsNotNone(preflight.call_args.kwargs["workspace"])
        client.assert_not_called()
        self.assertEqual(payload, __import__("json").loads(output.getvalue()))

    def test_network_failure_is_wrapped_for_exit_2_handling(self):
        runtime = mock.Mock()
        runtime.request.side_effect = TransportError("Gravity SQL request failed")
        client = GravityClient(runtime)
        with self.assertRaisesRegex(RuntimeError, "Gravity SQL request failed"):
            client.execute_sql("SELECT 1")


if __name__ == "__main__":
    unittest.main()
