from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

from gravity_insight.sql import __main__ as gravity_cli
from gravity_insight.sql import products
from gravity_insight.sql import verification as verification_module
from gravity_insight.sql.client import GravityClient
from gravity_insight.workspace import Workspace, WorkspaceDefaults


DAY = date(2026, 9, 3)
FIXTURES = Path(__file__).parent / "fixtures"


class _FixtureRuntime:
    def __init__(self, fixture: dict[str, object]) -> None:
        self._responses = list(fixture["responses"])
        self.sql: list[str] = []

    def request(self, _profile, _method, _path, *, json_body, **_kwargs):
        self.sql.append(json_body["sql"])
        response = self._responses.pop(0)
        return mock.Mock(
            status_code=response["status_code"],
            payload=response["payload"],
            retry_after_ms=response.get("retry_after_ms"),
        )


class _PriorSnapshotClient:
    def execute_sql(self, _sql: str):
        return [{"metric": "PRIOR_AGGREGATE_VALUE"}]


class SqlVerificationDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def _workspace(self) -> Workspace:
        products = {}
        for index in (1, 2):
            name = f"p{index}"
            products[name] = {
                "kind": "custom-sql",
                "datasource": "demo",
                "apps": ["demo"],
                "privacy": "aggregate",
                "output_fields": ["metric"],
                "max_rows": 10,
                "measurement": "fixture aggregate",
                "forbidden_claims": ["user-level identity"],
                "sql": (
                    f"SELECT {index} AS metric /* SQL_TEXT_SENTINEL:{name} */ "
                    "WHERE 76543210 IN ({app_ids}) "
                    "AND '{start}' < '{end}' LIMIT {limit}"
                ),
            }
        return Workspace(
            path=None,
            root=self.root,
            state_root=self.root / "state",
            apps={"demo": 76543210},
            defaults=WorkspaceDefaults(
                app="demo",
                timezone="Asia/Shanghai",
                time_window="latest-safe-day",
            ),
            datasources={
                "demo": {
                    "id": "FIXTURE_DATASOURCE_ID",
                    "verification_status": "pending_review",
                    "timezone": "Asia/Shanghai",
                    "privacy": "aggregate output only",
                }
            },
            products=products,
            recipes={},
        )

    def _run_fixture(self, name: str):
        fixture = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
        runtime = _FixtureRuntime(fixture)
        workspace = self._workspace()
        previous_snapshot = self.root / "latest.json"
        prior_evidence = verification_module.verify_all(
            _PriorSnapshotClient(), DAY, workspace=workspace
        )
        products.validate_evidence(prior_evidence, workspace=workspace)
        previous_snapshot.write_text(
            json.dumps(prior_evidence, ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        previous_snapshot_bytes = previous_snapshot.read_bytes()
        output, error = io.StringIO(), io.StringIO()

        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            [
                "gravity_insight.sql",
                "verify",
                "--date",
                DAY.isoformat(),
                "--publish",
            ],
        ), mock.patch(
            "gravity_insight.sql.__main__.product_names",
            return_value=("p1", "p2"),
        ), mock.patch(
            "gravity_insight.sql.__main__.latest_safe_date", return_value=DAY
        ), mock.patch(
            "gravity_insight.sql.__main__.load_workspace", return_value=workspace
        ), mock.patch(
            "gravity_insight.sql.__main__._client",
            return_value=GravityClient(runtime),
        ), mock.patch(
            "gravity_insight.sql.__main__.publish_evidence"
        ) as publish, mock.patch(
            "gravity_insight.sql.__main__.EVIDENCE_PATH", previous_snapshot
        ), mock.patch(
            "gravity_insight.sql.time_window._time.monotonic",
            side_effect=[0.0, 1.0, 1.5],
        ), redirect_stdout(output), redirect_stderr(error):
            exit_code = gravity_cli.main()

        rendered = output.getvalue()
        payload = json.loads(rendered)
        self.assertEqual(previous_snapshot_bytes, previous_snapshot.read_bytes())
        publish.assert_not_called()
        self.assertFalse(payload["readiness_achieved"])
        self.assertNotIn(payload["verification_status"], {"verified", "verified_with_gaps"})
        self.assertEqual(
            {
                "configured_product_count": 2,
                "completed_product_count": 1,
                "pending_product_count": 1,
                "failure_product": "p2",
            },
            payload["progress"],
        )
        self.assertNotIn("completed_products", payload)
        self.assertNotIn("datasource_id", payload)
        for secret in [*fixture["forbidden_output"], *runtime.sql]:
            self.assertNotIn(secret, rendered)
        return exit_code, payload, error.getvalue(), workspace

    def test_public_cli_fixture_engine_rejected(self):
        exit_code, payload, error, _workspace = self._run_fixture(
            "sql-verify-engine-rejected.json"
        )

        failure = payload["failure"]
        self.assertEqual(3, exit_code)
        self.assertEqual("gravity.sql-verification-result.v1", payload["schema_version"])
        self.assertEqual("error", payload["status"])
        self.assertEqual("failed", payload["verification_status"])
        self.assertEqual("SQL_ENGINE_REJECTED", failure["code"])
        self.assertEqual("SQL_ENGINE_REJECTED", failure["sql_code"])
        self.assertEqual("plan", failure["stage"])
        self.assertEqual("engine_rejected", failure["upstream_error"]["category"])
        self.assertFalse(failure["retryable"])
        self.assertEqual("yes", failure["reached_sql_engine"])
        self.assertEqual(1, failure["execution_evidence"]["request_count"])
        self.assertEqual(1, failure["execution_evidence"]["request_count_bound"])
        self.assertFalse(failure["execution_evidence"]["request_count_capped"])
        self.assertEqual(500, failure["execution_evidence"]["elapsed_ms"])
        self.assertEqual(900000, failure["execution_evidence"]["elapsed_ms_bound"])
        self.assertFalse(failure["execution_evidence"]["elapsed_ms_capped"])
        self.assertEqual(
            "Do not retry unchanged. Check SQL syntax and types plus documented "
            "join support; reduce join, CTE, window, or resource demands, or use "
            "governed Analysis reads. Provide only the sanitized protocol_status "
            "to the SDK maintainer.",
            failure["next_action"],
        )
        protocol = failure["upstream_error"]["protocol_status"]
        self.assertEqual("FAILED", protocol["status"]["value"])
        self.assertEqual(200, protocol["code"]["value"])
        self.assertEqual("OK", protocol["msg"]["value"])
        self.assertFalse(protocol["extra_error"]["value_persisted"])
        self.assertEqual("object", protocol["extra_error"]["value_type"])
        self.assertFalse(payload["checkpoint"]["written"])
        self.assertFalse(payload["resume"]["supported"])
        self.assertEqual("", error)

    def test_public_cli_fixture_non_tabular(self):
        exit_code, payload, error, _workspace = self._run_fixture(
            "sql-verify-non-tabular.json"
        )

        failure = payload["failure"]
        self.assertEqual(4, exit_code)
        self.assertEqual("error", payload["status"])
        self.assertEqual("SQL_RESPONSE_SHAPE_INVALID", failure["code"])
        self.assertEqual("SQL_RESPONSE_SHAPE_INVALID", failure["sql_code"])
        self.assertEqual("shape", failure["stage"])
        self.assertEqual(
            "tabular_shape_drift", failure["upstream_error"]["category"]
        )
        self.assertFalse(failure["retryable"])
        self.assertEqual("yes", failure["reached_sql_engine"])
        self.assertEqual(1, failure["execution_evidence"]["request_count"])
        self.assertEqual(
            "Stop automation and ask the SDK maintainer to re-verify the SQL "
            "response shape.",
            failure["next_action"],
        )
        self.assertFalse(payload["checkpoint"]["written"])
        self.assertFalse(payload["resume"]["supported"])
        self.assertEqual("", error)

    def test_public_cli_fixture_rate_limited(self):
        exit_code, payload, error, workspace = self._run_fixture(
            "sql-verify-rate-limited.json"
        )

        failure = payload["failure"]
        self.assertEqual(3, exit_code)
        self.assertEqual("rate_limited", payload["status"])
        self.assertEqual("interrupted", payload["verification_status"])
        self.assertEqual("RATE_LIMITED", failure["code"])
        self.assertEqual("SQL_HTTP_RATE_LIMITED", failure["sql_code"])
        self.assertEqual("execute", failure["stage"])
        self.assertEqual(
            "http_rate_limited", failure["upstream_error"]["category"]
        )
        self.assertTrue(failure["retryable"])
        self.assertEqual("unknown", failure["reached_sql_engine"])
        self.assertEqual(429, failure["upstream_error"]["http_status"])
        self.assertEqual(1, failure["execution_evidence"]["request_count"])
        self.assertEqual(2500, failure["retry_after_ms"])
        self.assertEqual(
            "Wait the bounded retry_after_ms, then run `gravity sql verify --date "
            "2026-09-03 --resume`; keep concurrency at 1 and do not increase it.",
            failure["next_action"],
        )
        self.assertTrue(payload["checkpoint"]["written"])
        self.assertTrue(payload["checkpoint"]["strict_prefix"])
        self.assertTrue(payload["resume"]["supported"])
        self.assertTrue(
            verification_module.verification_checkpoint_path(
                DAY, workspace=workspace
            ).is_file()
        )
        self.assertIn("CHECKPOINTED", error)

    def test_verify_boundary_error_never_renders_original_exception_text(self):
        workspace = self._workspace()
        output, error = io.StringIO(), io.StringIO()
        raw_detail = "RAW_BOUNDARY_EXCEPTION_SENTINEL unreviewed-detail"

        with mock.patch.object(
            gravity_cli.sys,
            "argv",
            ["gravity_insight.sql", "verify", "--date", DAY.isoformat()],
        ), mock.patch(
            "gravity_insight.sql.__main__.product_names", return_value=("p1", "p2")
        ), mock.patch(
            "gravity_insight.sql.__main__.latest_safe_date", return_value=DAY
        ), mock.patch(
            "gravity_insight.sql.__main__.load_workspace", return_value=workspace
        ), mock.patch(
            "gravity_insight.sql.__main__._client", side_effect=RuntimeError(raw_detail)
        ), redirect_stdout(output), redirect_stderr(error):
            exit_code = gravity_cli.main()

        payload = json.loads(error.getvalue())
        self.assertEqual(2, exit_code)
        self.assertEqual("", output.getvalue())
        self.assertNotIn(raw_detail, error.getvalue())
        self.assertEqual("SQL_VERIFY_INPUT_INVALID", payload["failure"]["code"])
        self.assertEqual("bind", payload["failure"]["stage"])
        self.assertEqual(0, payload["failure"]["execution_evidence"]["request_count"])
        self.assertFalse(payload["readiness_achieved"])


if __name__ == "__main__":
    unittest.main()
