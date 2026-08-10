import copy
import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime
from pathlib import Path
from unittest import mock

from gravity_sdk.sql import __main__ as gravity_cli
from gravity_sdk.sql.client import GravityClient
try:
    from gravity_sdk.errors import TransportError
except ModuleNotFoundError:  # pragma: no cover - source-tree test execution.
    from gravity_sdk.errors import TransportError
from gravity_sdk.sql.products import (
    BEIJING,
    EvidenceFormatError,
    build_evidence,
    build_sql,
    day_window,
    declared_events,
    evidence_preflight,
    _credential_source,
    latest_safe_date,
    publish_evidence,
    read_evidence,
    readiness_status,
    resolve_current_evidence,
    run_product,
    summarize_events,
    summarize_first_scene,
    summarize_payment,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_WORKSPACE = ROOT / "examples" / "workspace" / "gravity.toml"


class _AggregateClient:
    def execute_sql(self, sql):
        if "WITH raw_pay AS" in sql:
            return [
                {
                    "app_id": 29034827,
                    "pay_event_rows": 2,
                    "order_count": 2,
                    "buyer_count": 1,
                    "revenue_cent": 300,
                    "duplicate_rows": 0,
                    "missing_amount_rows": 0,
                    "invalid_amount_rows": 0,
                    "missing_reason_rows": 0,
                    "fallback_order_key_rows": 0,
                    "missing_pay_type_rows": 0,
                    "missing_pay_method_rows": 0,
                    "non_cny_rows": 0,
                    "pay_method_value_count": 1,
                    "pay_method_min": "method",
                    "pay_method_max": "method",
                    "pay_type_value_count": 1,
                    "pay_type_min": "CNY",
                    "pay_type_max": "CNY",
                }
            ]
        if "WITH user_scene AS" in sql:
            return [
                {"app_id": 29034827, "scene_status": "reported", "host_prefix": "26", "registrations": 2}
            ]
        if "complete_profile_users" in sql:
            return [
                {
                    "app_id": 29034827,
                    "active_users": 2,
                    "profile_row_users": 2,
                    "getpower_users": 1,
                    "usepower_users": 1,
                    "current_power_users": 1,
                    "complete_profile_users": 1,
                    "assetlist_events": 0,
                    "assetlist_users": 0,
                }
            ]
        return [
            {
                "app_id": 29034827,
                "event_name": "__all__",
                "event_rows": 10,
                "active_users": 2,
                "first_event_at": "2026-07-22 00:00:00.011",
                "last_event_at": "2026-07-22 23:59:59.999",
            }
        ]


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

    def test_partial_products_keep_warnings_and_forbidden_claims(self):
        start_at, end_at = day_window(date(2026, 7, 22))
        result = run_product(_AggregateClient(), "energy-profile-coverage", start_at, end_at)

        self.assertEqual("partial", result["status"])
        self.assertTrue(result["warnings"])
        self.assertTrue(result["forbidden_claims"])
        self.assertEqual(0.5, result["summary"]["apps"][0]["complete_profile_coverage_rate"])

        payment_rows = _AggregateClient().execute_sql("WITH raw_pay AS")
        payment_rows[0]["invalid_amount_rows"] = 1
        payment_rows[0]["missing_reason_rows"] = 1
        _summary, status, warnings, _notes = summarize_payment(
            payment_rows, (29034827,), start_at, end_at
        )
        self.assertEqual("partial", status)
        self.assertTrue(any("invalid_amount_rows=1" in warning for warning in warnings))
        self.assertTrue(any("missing_reason_rows=1" in warning for warning in warnings))

    def test_declared_event_absence_is_informational_but_late_data_is_partial(self):
        start_at, end_at = day_window(date(2026, 7, 22))
        fresh_rows = _AggregateClient().execute_sql("event")
        summary, status, warnings, notes = summarize_events(
            fresh_rows, (29034827,), start_at, end_at, declared_events()
        )
        self.assertEqual("complete", status)
        self.assertEqual([], warnings)
        self.assertTrue(summary["apps"][0]["missing_events"])
        self.assertIn("informational", notes[0])

        fresh_rows[0]["last_event_at"] = "2026-07-22 23:00:00"
        _summary, status, warnings, _notes = summarize_events(
            fresh_rows, (29034827,), start_at, end_at, declared_events()
        )
        self.assertEqual("partial", status)
        self.assertIn("15 minutes", warnings[0])

    def test_first_scene_coverage_counts_nonempty_invalid_values_as_present(self):
        start_at, end_at = day_window(date(2026, 7, 22))
        summary, status, warnings, _notes = summarize_first_scene(
            [
                {"app_id": 29034827, "scene_status": "reported", "host_prefix": "26", "registrations": 8},
                {"app_id": 29034827, "scene_status": "invalid_format", "host_prefix": "", "registrations": 1},
                {"app_id": 29034827, "scene_status": "missing", "host_prefix": "", "registrations": 1},
            ],
            (29034827,),
            start_at,
            end_at,
        )
        app = summary["apps"][0]
        self.assertEqual(9, app["with_scene"])
        self.assertEqual(8, app["six_digit_scene"])
        self.assertEqual(0.9, app["coverage_rate"])
        self.assertEqual("partial", status)
        self.assertTrue(warnings)

    def test_evidence_atomic_round_trip_and_contract_drift_rejects_query(self):
        day = date(2026, 7, 22)
        start_at, end_at = day_window(day)
        client = _AggregateClient()
        results = [
            run_product(client, product, start_at, end_at)
            for product in (
                "payment-summary",
                "first-scene-coverage",
                "energy-profile-coverage",
                "event-coverage",
            )
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
            tampered["products"]["payment-summary"]["summary"]["apps"][0]["revenue_cent"] = 999999
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
                for product in (
                    "payment-summary",
                    "first-scene-coverage",
                    "energy-profile-coverage",
                    "event-coverage",
                )
            ],
        )
        with tempfile.TemporaryDirectory() as temporary:
            rolling = Path(temporary) / "gravity-latest.json"
            product_root = Path(temporary) / "gravity-daily-verification"
            with mock.patch("gravity_sdk.sql.products.EVIDENCE_PATH", rolling), mock.patch(
                "gravity_sdk.sql.products.EVIDENCE_PRODUCT_ROOT", product_root
            ), mock.patch(
                "gravity_sdk.sql.products._git_state", return_value=("a" * 40, True)
            ):
                publish_evidence(evidence, rolling)

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
                for product in (
                    "payment-summary",
                    "first-scene-coverage",
                    "energy-profile-coverage",
                    "event-coverage",
                )
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

    def test_query_readiness_rejection_is_exit_1_and_bad_evidence_is_exit_2(self):
        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            [
                "gravity_sdk.sql",
                "query",
                "payment-summary",
                "--start",
                "2026-07-22T00:00:00",
                "--end",
                "2026-07-23T00:00:00",
            ],
        ), mock.patch("gravity_sdk.sql.__main__.resolve_current_evidence", return_value=mock.Mock()), mock.patch(
            "gravity_sdk.sql.__main__.readiness_status",
            return_value={"query_ready": False, "status": "pending_review", "reason": "missing"},
        ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(1, gravity_cli.main())

        with mock.patch.object(
            gravity_cli.sys, "argv", ["gravity_sdk.sql", "status", "--json"]
        ), mock.patch(
            "gravity_sdk.sql.__main__.resolve_current_evidence",
            side_effect=EvidenceFormatError("bad evidence"),
        ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(2, gravity_cli.main())

        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            [
                "gravity_sdk.sql",
                "query",
                "payment-summary",
                "--start",
                "2026-07-22T00:00:00",
                "--end",
                "2026-07-23T00:00:00",
            ],
        ), mock.patch("gravity_sdk.sql.__main__.resolve_current_evidence", return_value=mock.Mock()), mock.patch(
            "gravity_sdk.sql.__main__.readiness_status",
            return_value={"query_ready": True},
        ), mock.patch(
            "gravity_sdk.sql.__main__._client", side_effect=OSError("unreadable credentials")
        ), redirect_stdout(
            io.StringIO()
        ), redirect_stderr(
            io.StringIO()
        ):
            self.assertEqual(2, gravity_cli.main())

        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            [
                "gravity_sdk.sql",
                "query",
                "payment-summary",
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
        ), redirect_stderr(
            io.StringIO()
        ):
            self.assertEqual(2, gravity_cli.main())
            client.assert_not_called()

        start_at, end_at = day_window(date(2026, 7, 22))
        with self.assertRaises(ValueError):
            build_sql("payment-summary", start_at, end_at, ("29034827 OR 1=1",))

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
                "payment-summary",
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
            "gravity_sdk.sql.__main__._client", return_value=mock.Mock()
        ), mock.patch(
            "gravity_sdk.sql.__main__.run_product", return_value={"product": "payment-summary"}
        ), redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(0, gravity_cli.main())

        resolver.assert_called_once_with()
        payload = __import__("json").loads(output.getvalue())
        self.assertEqual("synthetic-snapshot", payload["evidence_reference"]["snapshot_id"])

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

        preflight.assert_called_once_with(None)
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
