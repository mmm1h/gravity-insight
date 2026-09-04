import copy
import io
import json
import os
import subprocess
import tempfile
import threading
from threading import Barrier
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from gravity_insight.sql import __main__ as gravity_cli
from gravity_insight.sql import credentials, products, provenance
from gravity_insight.sql.client import GravityClient
try:
    from gravity_insight.errors import AuthenticationError, CredentialError, TransportError
except ModuleNotFoundError:  # pragma: no cover - source-tree test execution.
    from gravity_insight.errors import AuthenticationError, CredentialError, TransportError
from gravity_insight.sql.products import (
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
from gravity_insight.sql.time_window import summarize_custom_result


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_WORKSPACE = ROOT / "examples" / "workspace" / "gravity.toml"
JOIN_FAILURE_WORKSPACE = ROOT / "tests" / "fixtures" / "sql-user-event-join-failure.toml"


def _single_run_verification(*product_names: str) -> dict[str, object]:
    observed_at = datetime(2026, 7, 23, 12, tzinfo=BEIJING).isoformat()
    return {
        "mode": "single_run",
        "segment_count": 1,
        "segments": [
            {
                "sequence": 1,
                "started_at": observed_at,
                "completed_at": observed_at,
                "products": list(product_names),
                "status": "complete",
                "failure_product": None,
            }
        ],
    }


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

    def test_credential_self_test_runs_directly(self):
        self.assertIsNone(credentials.self_test())

    def test_credential_release_asset_uses_current_distribution_identity(self):
        self.assertEqual("gravity-insight-credentials.json", credentials.ASSET_NAME)

    def test_latest_safe_day_changes_at_0200_beijing(self):
        self.assertEqual(
            date(2026, 7, 21),
            latest_safe_date(datetime(2026, 7, 23, 1, 59, 59, tzinfo=BEIJING)),
        )
        self.assertEqual(
            date(2026, 7, 22),
            latest_safe_date(datetime(2026, 7, 23, 2, 0, 0, tzinfo=BEIJING)),
        )

    def test_registered_product_below_cap_is_complete_without_row_cap_warning(self):
        start_at, end_at = day_window(date(2026, 7, 22))
        client = _AggregateClient()
        result = run_product(
            client, "daily-event-summary", start_at, end_at
        )

        self.assertEqual("complete", result["status"])
        self.assertEqual("complete", result["completeness"])
        self.assertEqual("below_row_cap", result["completeness_reason"])
        self.assertFalse(result["row_cap_reached"])
        self.assertEqual([], result["warnings"])
        self.assertTrue(result["forbidden_claims"])
        self.assertEqual(
            [{"app_id": 1001, "event_name": "DemoEvent", "event_count": 2}],
            result["summary"]["rows"],
        )
        self.assertEqual(100, result["summary"]["max_rows"])
        self.assertIsNone(result["summary"]["total_row_count"])
        self.assertEqual("observed event name", result["summary"]["output_semantics"]["event_name"])
        self.assertIn("LIMIT 101", client.sql)
        self.assertEqual(
            "complete", result["obligations"]["execution_status"]["state"]
        )
        self.assertEqual(
            "complete", result["obligations"]["data_completeness"]["state"]
        )

    def test_registered_product_at_cap_without_total_is_unknown(self):
        class CapClient:
            def execute_sql(self, _sql):
                return [
                    {"app_id": 1001, "event_name": f"event-{index}", "event_count": 1}
                    for index in range(100)
                ]

        day = date(2026, 7, 22)
        start_at, end_at = day_window(day)
        result = run_product(
            CapClient(), "daily-event-summary", start_at, end_at
        )

        self.assertEqual("complete", result["status"])
        self.assertEqual("unknown", result["completeness"])
        self.assertEqual("possible_truncation", result["completeness_reason"])
        self.assertTrue(result["row_cap_reached"])
        self.assertEqual(100, result["summary"]["row_count"])
        self.assertEqual(100, result["summary"]["max_rows"])
        self.assertIsNone(result["summary"]["total_row_count"])
        self.assertEqual(1, len(result["warnings"]))
        self.assertTrue(result["warnings"][0].startswith("POSSIBLE_TRUNCATION:"))
        evidence = build_evidence(
            day,
            [result],
            verification=_single_run_verification("daily-event-summary"),
        )
        self.assertEqual("verified_with_gaps", evidence["verification_status"])
        with mock.patch(
            "gravity_insight.sql.products.datasource_verification_status",
            return_value="verified_with_gaps",
        ):
            readiness = readiness_status(
                evidence, datetime(2026, 7, 23, 12, tzinfo=BEIJING)
            )
        self.assertTrue(readiness["query_ready"])
        self.assertEqual(
            "unknown",
            evidence["products"]["daily-event-summary"]["completeness"],
        )

    def test_registered_product_at_cap_with_matching_total_is_proven_complete(self):
        start_at, end_at = day_window(date(2026, 7, 22))
        summary, status, warnings, notes, completeness = (
            summarize_custom_result(
                [{"app_id": 1001}, {"app_id": 1002}],
                (1001,),
                start_at,
                end_at,
                output_fields=["app_id"],
                max_rows=2,
                measurement="aggregate",
                total_row_count=2,
            )
        )

        self.assertEqual("complete", status.state.value)
        self.assertEqual([], warnings)
        self.assertEqual([], notes)
        self.assertEqual(2, summary["total_row_count"])
        self.assertEqual("complete", completeness.state.value)
        self.assertEqual("TOTAL_ROW_COUNT_MATCH", completeness.evidence_code)
        self.assertEqual(True, completeness.facts["row_cap_reached"])

    def test_registered_product_source_above_cap_fails_closed(self):
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
        evidence = build_evidence(
            day,
            results,
            verification=_single_run_verification("daily-event-summary"),
        )
        legacy = copy.deepcopy(evidence)
        legacy["schema_version"] = 1
        legacy.pop("verification")
        legacy_product = legacy["products"]["daily-event-summary"]
        for field in ("row_cap_reached", "completeness", "completeness_reason"):
            legacy_product.pop(field)
        legacy_product["summary"].pop("max_rows")
        legacy_product["summary"].pop("total_row_count")
        legacy["hashes"]["result_sha256"] = products._sha256_json(
            legacy["products"]
        )
        products.validate_evidence(legacy)
        incomplete = copy.deepcopy(evidence)
        incomplete["products"]["daily-event-summary"].pop("completeness")
        with self.assertRaisesRegex(
            EvidenceFormatError, "incomplete product completeness signal"
        ):
            products.validate_evidence(incomplete)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "gravity-latest.json"
            publish_evidence(evidence, path)
            self.assertEqual(evidence, read_evidence(path))
            self.assertEqual([], list(path.parent.glob("*.tmp")))

            original = path.read_text(encoding="utf-8")
            with mock.patch("gravity_insight.sql.products.os.replace", side_effect=OSError("disk")):
                with self.assertRaises(OSError):
                    publish_evidence(evidence, path)
            self.assertEqual(original, path.read_text(encoding="utf-8"))
            self.assertEqual([], list(path.parent.glob("*.tmp")))

            path.write_bytes(b"\xff")
            with self.assertRaises(EvidenceFormatError):
                read_evidence(path)

        now = datetime(2026, 7, 23, 12, tzinfo=BEIJING)
        with mock.patch(
            "gravity_insight.sql.products.datasource_verification_status",
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
            with mock.patch("gravity_insight.sql.products.contract_hash", return_value="0" * 64):
                status = readiness_status(evidence, now)
        self.assertEqual("stale", status["status"])
        self.assertFalse(status["query_ready"])

        with mock.patch(
            "gravity_insight.sql.products.datasource_verification_status",
            return_value="verified_with_gaps",
        ), mock.patch("gravity_insight.sql.products.build_sql", return_value="SELECT 'drift'"):
            self.assertEqual("stale", readiness_status(evidence, now)["status"])

        with self.assertRaises(EvidenceFormatError):
            build_evidence(
                day,
                results + [results[0]],
                verification=_single_run_verification("daily-event-summary"),
            )

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
            verification=_single_run_verification("daily-event-summary"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            rolling = Path(temporary) / "gravity-latest.json"
            product_root = Path(temporary) / "gravity-daily-verification"
            with mock.patch("gravity_insight.sql.products.EVIDENCE_PATH", rolling), mock.patch(
                "gravity_insight.sql.products.EVIDENCE_PRODUCT_ROOT", product_root
            ), mock.patch(
                "gravity_insight.sql.products.git_state", return_value=("a" * 40, True)
            ), mock.patch(
                "gravity_insight.sql.products.load_workspace",
                side_effect=AssertionError("publish reloaded its bound workspace"),
            ):
                from gravity_insight.workspace import load_workspace

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
            verification=_single_run_verification("daily-event-summary"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            rolling = Path(temporary) / "gravity-latest.json"
            rolling.write_text('{"previous": true}\n', encoding="utf-8")
            before = rolling.read_bytes()
            with mock.patch("gravity_insight.sql.products.EVIDENCE_PATH", rolling), mock.patch(
                "gravity_insight.sql.products.EVIDENCE_PRODUCT_ROOT",
                Path(temporary) / "gravity-daily-verification",
            ), mock.patch(
                "gravity_insight.sql.products.git_state", return_value=("a" * 40, True)
            ), mock.patch(
                "gravity_insight.sql.products.publish_json_snapshot",
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
                "gravity_insight.sql",
                "query",
                "daily-event-summary",
                "--start",
                "2026-07-22T00:00:00",
                "--end",
                "2026-07-23T00:00:00",
            ],
        ), mock.patch("gravity_insight.sql.__main__.resolve_current_evidence", return_value=binding), mock.patch(
            "gravity_insight.sql.__main__.readiness_status",
            return_value={"query_ready": False, "status": "pending_review", "reason": "missing"},
        ), mock.patch(
            "gravity_insight.sql.__main__._client", return_value=_AggregateClient()
        ), redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(0, gravity_cli.main())

        payload = json.loads(output.getvalue())
        self.assertEqual("complete", payload["status"])
        self.assertEqual("daily-event-summary", payload["product"])
        self.assertEqual("older-snapshot", payload["evidence_reference"]["snapshot_id"])
        self.assertIn("pending_review", payload["evidence_warning"])

    def test_bad_evidence_credentials_and_injection_have_stable_failures(self):

        with mock.patch.object(
            gravity_cli.sys, "argv", ["gravity_insight.sql", "status", "--json"]
        ), mock.patch(
            "gravity_insight.sql.__main__.resolve_current_evidence",
            side_effect=EvidenceFormatError("bad evidence"),
        ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(2, gravity_cli.main())

        credential_error = io.StringIO()
        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            [
                "gravity_insight.sql",
                "query",
                "daily-event-summary",
                "--start",
                "2026-07-22T00:00:00",
                "--end",
                "2026-07-23T00:00:00",
            ],
        ), mock.patch("gravity_insight.sql.__main__.resolve_current_evidence", return_value=mock.Mock()), mock.patch(
            "gravity_insight.sql.__main__.readiness_status",
            return_value={"query_ready": True},
        ), mock.patch(
            "gravity_insight.sql.__main__._client",
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
                "gravity_insight.sql",
                "query",
                "daily-event-summary",
                "--start",
                "2026-07-22T00:00:00' OR 1=1",
                "--end",
                "2026-07-23T00:00:00",
            ],
        ), mock.patch("gravity_insight.sql.__main__.resolve_current_evidence", return_value=mock.Mock()), mock.patch(
            "gravity_insight.sql.__main__.readiness_status",
            return_value={"query_ready": True},
        ), mock.patch("gravity_insight.sql.__main__._client") as client, redirect_stdout(
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
                "gravity_insight.sql",
                "query",
                "missing token=abc123",
                "--start",
                "2026-07-22T00:00:00",
                "--end",
                "2026-07-23T00:00:00",
            ],
        ), mock.patch("gravity_insight.sql.__main__._client") as client, redirect_stdout(
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
            ["gravity_insight.sql", "query", "--input", secret_path],
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
                "gravity_insight.sql",
                "query",
                "daily-event-summary",
                "--start",
                "2026-07-22T00:00:00",
                "--end",
                "2026-07-23T00:00:00",
            ],
        ), mock.patch(
            "gravity_insight.sql.__main__.resolve_current_evidence", return_value=binding
        ) as resolver, mock.patch(
            "gravity_insight.sql.__main__.readiness_status", return_value={"query_ready": True}
        ), mock.patch(
            "gravity_insight.sql.__main__._client", return_value=_AggregateClient()
        ), redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(0, gravity_cli.main())

        resolver.assert_called_once()
        self.assertIsNotNone(resolver.call_args.kwargs["workspace"])
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual("complete", payload["status"])
        self.assertEqual("synthetic-snapshot", payload["evidence_reference"]["snapshot_id"])
        self.assertEqual(
            "/evidence_reference",
            payload["result_audit"]["fact_paths"]["evidence_reference"],
        )
        self.assertNotIn("evidence_reference", payload["result_audit"])

    def test_products_command_is_one_safe_discovery_call(self):
        output = io.StringIO()
        with mock.patch.object(
            gravity_cli.sys, "argv", ["gravity_insight.sql", "products"]
        ), redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(0, gravity_cli.main())

        payload = json.loads(output.getvalue())
        self.assertEqual("gravity-sql.products.v1", payload["schema_version"])
        self.assertEqual(1, payload["count"])
        product = payload["products"][0]
        self.assertEqual("daily-event-summary", product["name"])
        self.assertNotIn("sql", product)
        self.assertEqual("observed event name", product["output_semantics"]["event_name"])
        self.assertEqual(2, payload["query_input"]["max_concurrency"])

    def test_dry_run_query_emits_offline_safe_plan_without_runtime_or_evidence(self):
        output = io.StringIO()
        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            [
                "gravity_insight.sql",
                "--dry-run",
                "query",
                "daily-event-summary",
                "--start",
                "2026-07-22T00:00:00+08:00",
                "--end",
                "2026-07-23T00:00:00+08:00",
            ],
        ), mock.patch("gravity_insight.sql.__main__._client") as client, mock.patch(
            "gravity_insight.sql.__main__.resolve_current_evidence"
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
                "gravity_insight.sql",
                "--dry-run",
                "query",
                "--input",
                json.dumps({"requests": requests}),
            ],
        ), mock.patch("gravity_insight.sql.__main__._client") as client, redirect_stdout(
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
                "gravity_insight.sql",
                "--dry-run",
                "query",
                "daily-event-summary",
                "--start",
                "not-a-time",
                "--end",
                "2026-07-23T00:00:00+08:00",
            ],
        ), mock.patch("gravity_insight.sql.__main__._client") as client, redirect_stdout(
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
            (["gravity_insight.sql", "--dry-run", "verify"], "verify_all"),
            (
                ["gravity_insight.sql", "--dry-run", "credentials", "pull"],
                "credentials.pull",
            ),
        ):
            with self.subTest(argv=argv):
                error = io.StringIO()
                with mock.patch.object(gravity_cli.sys, "argv", argv), mock.patch(
                    f"gravity_insight.sql.__main__.{patch_target}"
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
            gravity_cli.sys, "argv", ["gravity_insight.sql", "--dry-run"]
        ), mock.patch("gravity_insight.sql.__main__._client") as client, redirect_stdout(
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
            ["gravity_insight.sql", "query", "--input", json.dumps(requests)],
        ), mock.patch(
            "gravity_insight.sql.__main__.resolve_current_evidence",
            side_effect=EvidenceFormatError("missing"),
        ), mock.patch(
            "gravity_insight.sql.__main__._client", return_value=_AggregateClient()
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

    def test_query_cli_classifies_user_event_aggregate_join_failure(self):
        class JoinRejectingRuntime:
            def __init__(self):
                self.sql: list[str] = []

            def request(self, _profile, _method, _path, *, json_body, **_kwargs):
                sql = json_body["sql"]
                self.sql.append(sql)
                return mock.Mock(
                    status_code=200,
                    payload={
                        "status": "REJECTED",
                        "code": "JOIN_REJECTED_FIXTURE",
                        "msg": f"unreviewed planner detail: {sql}",
                        "extra": {"error": {"app_id": 76543210, "sql": sql}},
                    },
                )

        runtime = JoinRejectingRuntime()
        output = io.StringIO()
        with mock.patch.dict(
            os.environ, {"GRAVITY_WORKSPACE": str(JOIN_FAILURE_WORKSPACE)}
        ), mock.patch.object(
            gravity_cli.sys,
            "argv",
            [
                "gravity_insight.sql",
                "query",
                "user-event-aggregate",
                "--start",
                "2026-07-22T00:00:00",
                "--end",
                "2026-07-23T00:00:00",
            ],
        ), mock.patch(
            "gravity_insight.sql.__main__.resolve_current_evidence",
            side_effect=EvidenceFormatError("missing"),
        ), mock.patch(
            "gravity_insight.sql.__main__._client",
            return_value=GravityClient(runtime),
        ), redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(3, gravity_cli.main())

        rendered = output.getvalue()
        payload = json.loads(rendered)
        error = payload["error"]
        self.assertEqual("gravity-sql.query.v1", payload["schema_version"])
        self.assertEqual("SQL_ENGINE_REJECTED", error["code"])
        self.assertEqual("plan", error["stage"])
        self.assertEqual("engine_rejected", error["upstream_error"]["category"])
        self.assertFalse(error["retryable"])
        self.assertEqual("yes", error["reached_sql_engine"])
        self.assertEqual(1, error["execution_evidence"]["request_count"])
        protocol = error["upstream_error"]["protocol_status"]
        self.assertEqual("JOIN_REJECTED_FIXTURE", protocol["code"]["value"])
        self.assertFalse(protocol["msg"]["value_persisted"])
        self.assertEqual("object", protocol["extra_error"]["value_type"])
        self.assertEqual(1, len(runtime.sql))
        self.assertIn("`default`.`user`", runtime.sql[0])
        self.assertIn("`default`.`event`", runtime.sql[0])
        for secret in (
            runtime.sql[0],
            "`default`.`user`",
            "`default`.`event`",
            "PRIVATE_CHANNEL_SENTINEL",
            "PRIVATE_EVENT_SENTINEL",
            "76543210",
            "unreviewed planner detail",
        ):
            self.assertNotIn(secret, rendered)

    def test_product_batch_defaults_to_concurrent_ordered_isolated_execution(self):
        lock, rendezvous = threading.Lock(), Barrier(2, timeout=20)
        active = 0
        max_active = 0

        class ConcurrentAggregateClient:
            def execute_sql(self, _sql):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                try:
                    rendezvous.wait()
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
        self.assertEqual(4, result["execution_evidence"]["request_count"])
        self.assertEqual(
            0,
            result["results"][2]["error"]["execution_evidence"]["request_count"],
        )
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
            _AggregateClient(),
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
        from gravity_insight.workspace import load_workspace

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

    def test_verify_all_runs_products_sequentially(self):
        active = 0
        max_active = 0
        order = []

        def fake_run(_client, product, start_at, end_at, *, workspace=None):
            self.assertIsNotNone(workspace)
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            order.append(product)
            try:
                return {"product": product, "window": [start_at, end_at]}
            finally:
                active -= 1

        with mock.patch(
            "gravity_insight.sql.products.product_names", return_value=("one", "two")
        ), mock.patch(
            "gravity_insight.sql.products.run_product", side_effect=fake_run
        ), mock.patch(
            "gravity_insight.sql.products.build_evidence",
            side_effect=lambda _day, results, **_options: {"results": results},
        ):
            result = verify_all(mock.Mock(), date(2026, 7, 22))

        self.assertEqual(
            ["one", "two"], [item["product"] for item in result["results"]]
        )
        self.assertEqual(["one", "two"], order)
        self.assertEqual(1, max_active)
        with self.assertRaisesRegex(ValueError, "exactly 1"):
            verify_all(mock.Mock(), date(2026, 7, 22), max_workers=2)

    def test_query_and_verify_bind_ambient_workspace_once(self):
        from gravity_insight.workspace import load_workspace

        workspace = load_workspace(EXAMPLE_WORKSPACE)
        request = {
            "product": "daily-event-summary",
            "start": "2026-07-22T00:00:00",
            "end": "2026-07-23T00:00:00",
        }
        no_reload = mock.patch(
            "gravity_insight.sql.products.load_workspace",
            side_effect=AssertionError("workspace was reloaded inside one operation"),
        )
        with mock.patch(
            "gravity_insight.sql.query.load_workspace", return_value=workspace
        ) as query_load, no_reload:
            queried = run_product_queries(
                _AggregateClient(), [request, request], max_workers=1
            )
        self.assertTrue(queried["ok"])
        query_load.assert_called_once_with()

        with mock.patch(
            "gravity_insight.sql.verification.load_workspace", return_value=workspace
        ) as verify_load, mock.patch(
            "gravity_insight.sql.products.load_workspace",
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
            if args[1:3] == ["rev-parse", "--show-toplevel"]:
                return mock.Mock(returncode=0, stdout="/consumer/repo\n")
            if args[1:3] == ["rev-parse", "HEAD"]:
                return mock.Mock(returncode=0, stdout="b" * 40 + "\n")
            if args[1:3] == ["branch", "--show-current"]:
                return mock.Mock(returncode=0, stdout="codex/test\n")
            return mock.Mock(returncode=0, stdout=b"")

        with mock.patch("gravity_insight.sql.products.subprocess.run", side_effect=fake_git), mock.patch(
            "gravity_insight.sql.products._credential_source", return_value="ignored_local_file"
        ), mock.patch(
            "gravity_insight.sql.products.resolve_current_evidence", return_value=binding
        ), mock.patch(
            "gravity_insight.sql.products.readiness_status",
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
                "git_state",
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

    def test_provenance_root_prefers_the_consumer_checkout_over_the_state_root(self):
        with tempfile.TemporaryDirectory() as tempdir:
            consumer = Path(tempdir) / "consumer"
            state = Path(tempdir) / "state"
            consumer.mkdir()
            state.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=consumer, check=True)
            workspace = mock.Mock(root=consumer, state_root=state)

            resolved = provenance.provenance_root(workspace)

            self.assertIsNotNone(resolved)
            self.assertEqual(consumer.resolve(), resolved.resolve())

            # The state root is never a checkout; probing it is what made every
            # normal consumer fail preflight before this fix.
            detached = mock.Mock(root=state, state_root=state)
            with mock.patch.object(provenance, "ROOT", state):
                self.assertIsNone(provenance.provenance_root(detached))

    def test_preflight_git_report_covers_clean_dirty_detached_and_non_git(self):
        with tempfile.TemporaryDirectory() as tempdir:
            repo = Path(tempdir) / "consumer"
            repo.mkdir()
            run = lambda *args: subprocess.run(list(args), cwd=repo, check=True, capture_output=True)
            run("git", "init", "-q", "-b", "work")
            (repo / "gravity.toml").write_text("[apps]\n", encoding="utf-8")
            run("git", "add", "-A")
            run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")

            clean = provenance.preflight_git_report(repo)
            self.assertEqual(("resolved", "work", False), (clean["git_state"], clean["current_branch"], clean["git_dirty"]))
            self.assertRegex(clean["git_sha"], r"^[0-9a-f]{40}$")

            (repo / "untracked.sql").write_text("select 1\n", encoding="utf-8")
            self.assertTrue(provenance.preflight_git_report(repo)["git_dirty"])
            (repo / "untracked.sql").unlink()

            run("git", "checkout", "-q", "--detach", clean["git_sha"])
            detached = provenance.preflight_git_report(repo)
            self.assertEqual(("resolved", "DETACHED", clean["git_sha"]), (detached["git_state"], detached["current_branch"], detached["git_sha"]))

            outside = Path(tempdir) / "plain"
            outside.mkdir()
            self.assertIsNone(provenance.git_toplevel(outside))

        report = provenance.preflight_git_report(None)
        self.assertEqual("not_git_backed", report["git_state"])
        self.assertEqual((None, None, None), (report["git_sha"], report["current_branch"], report["git_dirty"]))

        # Publish must still fail closed: a report is not provenance.
        with mock.patch.object(provenance, "provenance_root", return_value=None):
            with self.assertRaises(EvidenceFormatError):
                provenance.git_state(mock.Mock())

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
            gravity_cli.sys, "argv", ["gravity_insight.sql", "evidence-preflight", "--json"]
        ), mock.patch(
            "gravity_insight.sql.__main__.evidence_preflight", return_value=payload
        ) as preflight, mock.patch(
            "gravity_insight.sql.__main__._client"
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


class GravitySqlFastLaneTests(unittest.TestCase):
    Adapter = verify_all.GravitySqlExplorerAdapter

    @staticmethod
    def request(sql="SELECT 1 AS probe_value LIMIT 1"):
        return {
            "schema_version": "gravity.sql-fast-lane-request.v1",
            "sql": sql,
            "policy": {
                "allowed_relations": [],
                "allowed_functions": [],
                "output_columns": ["probe_value"],
                "budgets": {
                    "statement_timeout_ms": 5000,
                    "max_rows": 1,
                    "max_output_bytes": 1024,
                    "max_cell_bytes": 128,
                    "max_columns": 1,
                },
            },
        }

    @staticmethod
    def response(status="SUCCESS", result=None):
        response = mock.Mock()
        response.status_code = 200
        response.payload = {
            "code": 200,
            "data": {
                "status": status,
                "result": result
                if result is not None
                else {"columns": [{"name": "probe_value"}], "rows": [[1]]},
            },
        }
        return response

    def test_registered_sql_fast_lane_route_has_exact_static_evidence(self):
        route_root = ROOT / "src/gravity_insight/contracts/routes"
        registry = json.loads((route_root / "registry.json").read_text(encoding="utf-8"))
        confirmations = json.loads(
            (route_root / "probe-read-confirmations.json").read_text(encoding="utf-8")
        )["confirmations"]
        routes = [
            item
            for item in registry["routes"]
            if (item["method"], item["path"])
            == ("POST", "/custom_sql/api/sql/execute")
        ]
        reviewed = [
            item
            for item in confirmations
            if (item["method"], item["path"])
            == ("POST", "/custom_sql/api/sql/execute")
        ]
        self.assertEqual(1, len(routes))
        self.assertEqual(1, len(reviewed))
        self.assertEqual(("mmm1h", "2026-08-31"), (
            reviewed[0]["reviewer"], reviewed[0]["reviewed_at"]
        ))
        self.assertEqual(3, len(routes[0]["static_control_flow"]))
        self.assertTrue(routes[0]["static_source"]["complete_same_origin_js_graph"])

    def test_fast_lane_inspect_is_offline_and_reports_control_gaps(self):
        factory = mock.Mock(side_effect=AssertionError("inspection constructed runtime"))
        result = self.Adapter(runtime_factory=factory).inspect(self.request())
        self.assertTrue(result["ok"])
        self.assertFalse(result["network_called"])
        factory.assert_not_called()
        self.assertEqual(("exploratory", "unknown", []), (
            result["trust"], result["completeness"], result["allowed_claims"]
        ))
        self.assertEqual("unknown", result["dialect"])
        self.assertEqual(
            "unavailable_shared_web_session",
            result["safety"]["independent_read_only_identity"],
        )
        self.assertEqual(
            "unavailable_upstream_contract", result["safety"]["scan_budget"]
        )

    def test_fast_lane_ast_allowlists_and_literal_limit_are_enforced(self):
        allowed = self.request(
            "WITH bounded AS (SELECT 1 AS value) "
            "SELECT value AS probe_value FROM bounded LIMIT 1"
        )
        self.assertTrue(self.Adapter().inspect(allowed)["ok"])
        for sql in (
            "SELECT 1 AS probe_value",
            "SELECT 1 AS probe_value LIMIT 1; SELECT 2 AS probe_value LIMIT 1",
            "DELETE FROM safe_table",
            "INSERT INTO safe_table VALUES (1)",
            "UPDATE safe_table SET value = 1",
            "CREATE TABLE safe_table(value INTEGER)",
            "SET x = 1",
        ):
            with self.subTest(sql_kind=sql.split()[0]):
                result = self.Adapter().inspect(self.request(sql))
                self.assertEqual("compile", result["error"]["stage"])
                self.assertFalse(result["network_called"])

    def test_fast_lane_success_is_bounded_exploratory_and_single_request(self):
        runtime = mock.Mock()
        runtime.request.return_value = self.response()
        result = self.Adapter(runtime).execute(self.request())
        self.assertTrue(result["ok"])
        self.assertEqual((1, 1), (
            result["row_count"], result["execution"]["request_count"]
        ))
        self.assertEqual("unknown", result["promotion_source"]["dialect"])
        self.assertFalse(result["stable_dependency_allowed"])
        runtime.request.assert_called_once()
        self.assertEqual(1, runtime.request.call_args.kwargs["attempts"])

    def test_fast_lane_output_budgets_fail_closed_without_partial_rows(self):
        cases = (
            {"columns": [{"name": "probe_value"}], "rows": [[1], [2]]},
            {"columns": [{"name": "probe_value"}, {"name": "extra"}], "rows": [[1, 2]]},
            {"columns": [{"name": "probe_value"}], "rows": [["x" * 256]]},
        )
        for response_result in cases:
            runtime = mock.Mock()
            runtime.request.return_value = self.response(result=response_result)
            with self.subTest(shape=len(response_result["columns"])):
                result = self.Adapter(runtime).execute(self.request())
                self.assertEqual("shape", result["error"]["stage"])
                self.assertEqual([], result["rows"])

    def test_bind_failure_is_classified_before_network(self):
        invalid = self.request()
        del invalid["policy"]["budgets"]
        result = self.Adapter(mock.Mock()).execute(invalid)
        self.assertEqual("bind", result["error"]["stage"])
        self.assertEqual((0, False), (
            result["execution"]["request_count"], result["network_called"]
        ))

    def test_compile_failure_is_classified_before_network(self):
        result = self.Adapter(mock.Mock()).execute(self.request("DELETE FROM safe_table"))
        self.assertEqual("compile", result["error"]["stage"])
        self.assertEqual("SQL_FAST_LANE_STATEMENT_FORBIDDEN", result["error"]["code"])
        self.assertFalse(result["network_called"])

    def test_plan_failure_is_classified_from_engine_rejection(self):
        runtime = mock.Mock()
        runtime.request.return_value = self.response(status="FAILED")
        result = self.Adapter(runtime).execute(self.request())
        self.assertEqual(("plan", "yes"), (
            result["error"]["stage"], result["error"]["reached_sql_engine"]
        ))

    def test_execute_failure_is_classified_from_transport(self):
        runtime = mock.Mock()
        runtime.request.side_effect = RuntimeError("transport fixture")
        result = self.Adapter(runtime).execute(self.request())
        self.assertEqual("execute", result["error"]["stage"])
        self.assertEqual(1, result["execution"]["request_count"])
        self.assertNotIn("transport fixture", str(result))

    def test_shape_failure_is_classified_from_projection_drift(self):
        runtime = mock.Mock()
        runtime.request.return_value = self.response(result={"columns": [], "rows": []})
        result = self.Adapter(runtime).execute(self.request())
        self.assertEqual(("shape", "contract"), (
            result["error"]["stage"], result["error"]["category"]
        ))
        self.assertEqual([], result["rows"])


if __name__ == "__main__":
    unittest.main()
