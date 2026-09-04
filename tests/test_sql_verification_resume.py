from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from gravity_insight import Credential
from gravity_insight.adaptive_governor import AdaptiveRequestGovernor
from gravity_insight.errors import SqlResponseError, TransportError
from gravity_insight.host_rate_limiter import HostRateLimiter
from gravity_insight.http_runtime import GravityHttpRuntime
from gravity_insight.sql import products
from gravity_insight.sql import verification as verification_module
from gravity_insight.sql import __main__ as gravity_cli
from gravity_insight.sql.client import GravityClient
from gravity_insight.sql.evidence_validation import EvidenceFormatError
from gravity_insight.sql.failures import annotate_sql_failure
from gravity_insight.sql.verification import (
    VERIFICATION_MAX_BACKOFF_MS,
    read_verification_checkpoint,
    verify_all,
    write_verification_checkpoint,
)
from gravity_insight.workspace import Workspace, WorkspaceDefaults


DAY = date(2026, 9, 3)
STARTED = datetime(2026, 9, 4, 10, 0, tzinfo=products.BEIJING)


class _SequenceClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[str] = []

    def execute_sql(self, sql: str):
        self.calls.append(sql)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _FakeResponse:
    def __init__(self, status_code: int, headers=None):
        self.status_code = status_code
        self.headers = dict(headers or {})

    def json(self):
        return {}


class _QueueSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


class _Credentials:
    def get(self):
        return Credential("fixture-token")


def _rate_limit(retry_after_ms: int = 2_500) -> TransportError:
    return annotate_sql_failure(
        TransportError("fixture HTTP 429"),
        kind="http_status",
        http_status=429,
        retry_after_ms=retry_after_ms,
    )


def _engine_rejection() -> SqlResponseError:
    return annotate_sql_failure(
        SqlResponseError("fixture engine rejection"),
        kind="engine_rejected",
    )


class SqlVerificationResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def _workspace(self, count: int) -> Workspace:
        definitions = {}
        for index in range(1, count + 1):
            name = f"p{index}"
            definitions[name] = {
                "kind": "custom-sql",
                "datasource": "demo",
                "apps": ["demo"],
                "privacy": "aggregate",
                "output_fields": ["metric"],
                "max_rows": 10,
                "measurement": "fixture aggregate",
                "forbidden_claims": ["user-level identity"],
                "sql": (
                    f"SELECT {index} AS metric /* product:{name} */ "
                    "WHERE 1001 IN ({app_ids}) "
                    "AND '{start}' < '{end}' LIMIT {limit}"
                ),
            }
        return Workspace(
            path=None,
            root=self.root,
            state_root=self.root / "state",
            apps={"demo": 1001},
            defaults=WorkspaceDefaults(
                app="demo",
                timezone="Asia/Shanghai",
                time_window="latest-safe-day",
            ),
            datasources={
                "demo": {
                    "id": "fixture_warehouse",
                    "verification_status": "verified",
                    "timezone": "Asia/Shanghai",
                    "privacy": "aggregate output only",
                }
            },
            products=definitions,
            recipes={},
        )

    @staticmethod
    def _successes(count: int):
        return [[{"metric": index}] for index in range(1, count + 1)]

    def test_kth_product_rate_limit_preserves_prefix_and_is_not_verified(self):
        workspace = self._workspace(6)
        client = _SequenceClient([*self._successes(4), _rate_limit(3_000)])

        result = verify_all(client, DAY, workspace=workspace, clock=lambda: STARTED)

        self.assertFalse(result["ok"])
        self.assertFalse(result["readiness_achieved"])
        self.assertEqual("interrupted", result["verification_status"])
        self.assertEqual(["p1", "p2", "p3", "p4"], list(result["completed_products"]))
        self.assertEqual(["p5", "p6"], result["pending_products"])
        self.assertEqual(("RATE_LIMITED", True, 3_000), (
            result["failure"]["code"],
            result["failure"]["retryable"],
            result["failure"]["retry_after_ms"],
        ))
        self.assertEqual(5, len(client.calls))
        self.assertFalse(any("product:p6" in sql for sql in client.calls))

    def test_resume_completes_remaining_products_and_records_segments(self):
        workspace = self._workspace(4)
        now = [STARTED]

        first = verify_all(
            _SequenceClient([*self._successes(2), _rate_limit(2_500)]),
            DAY,
            workspace=workspace,
            clock=lambda: now[0],
        )
        path = write_verification_checkpoint(first, DAY, workspace=workspace)
        checkpoint = read_verification_checkpoint(DAY, workspace=workspace)
        sleeps = []

        def sleep(delay: float) -> None:
            sleeps.append(delay)
            now[0] += timedelta(seconds=delay)

        resumed_client = _SequenceClient(self._successes(2))
        evidence = verify_all(
            resumed_client,
            DAY,
            workspace=workspace,
            resume=checkpoint,
            sleeper=sleep,
            clock=lambda: now[0],
        )

        self.assertTrue(path.is_file())
        self.assertEqual([2.5], sleeps)
        self.assertEqual(2, len(resumed_client.calls))
        self.assertTrue("product:p3" in resumed_client.calls[0])
        self.assertTrue("product:p4" in resumed_client.calls[1])
        self.assertEqual("verified", evidence["verification_status"])
        self.assertEqual("resumed_after_rate_limit", evidence["verification"]["mode"])
        self.assertEqual(
            [
                (["p1", "p2"], "rate_limited", "p3"),
                (["p3", "p4"], "complete", None),
            ],
            [
                (
                    segment["products"],
                    segment["status"],
                    segment["failure_product"],
                )
                for segment in evidence["verification"]["segments"]
            ],
        )
        products.validate_evidence(evidence, workspace=workspace)

    def test_persistent_rate_limit_stops_at_bounded_retry_limit(self):
        workspace = self._workspace(1)
        responses = [
            _FakeResponse(429, {"Retry-After": "999"}) for _ in range(3)
        ]
        session = _QueueSession(responses)
        elapsed = [0.0]
        sleeps = []

        def sleep(delay: float) -> None:
            sleeps.append(delay)
            elapsed[0] += delay

        runtime = GravityHttpRuntime(
            session=session,
            credentials=_Credentials(),
            limiter=HostRateLimiter(
                clock=lambda: elapsed[0],
                random_source=lambda: 0.0,
                interval_jitter_ratio=0.0,
            ),
            requests_per_second=100,
            sleeper=sleep,
            rate_clock=lambda: elapsed[0],
            random_source=lambda: 1.0,
            interval_jitter_ratio=0.0,
            wall_clock=lambda: STARTED,
            governor=AdaptiveRequestGovernor(clock=lambda: elapsed[0]),
            receipt_root=self.root / "receipts",
        )

        result = verify_all(
            GravityClient(runtime), workspace=workspace, day=DAY, clock=lambda: STARTED
        )

        self.assertEqual(3, len(session.calls))
        self.assertTrue(sleeps)
        self.assertLessEqual(max(sleeps), 30.0)
        self.assertEqual(VERIFICATION_MAX_BACKOFF_MS, result["failure"]["retry_after_ms"])
        self.assertEqual("interrupted", result["verification_status"])
        self.assertIn("--resume", result["failure"]["next_action"])
        self.assertIn("do not increase", result["failure"]["next_action"])

    def test_engine_rejection_is_terminal_and_not_resumable(self):
        workspace = self._workspace(3)
        client = _SequenceClient([self._successes(1)[0], _engine_rejection()])

        result = verify_all(client, DAY, workspace=workspace, clock=lambda: STARTED)

        self.assertEqual("error", result["status"])
        self.assertEqual("failed", result["verification_status"])
        self.assertEqual("SQL_ENGINE_REJECTED", result["failure"]["code"])
        self.assertFalse(result["failure"]["retryable"])
        self.assertFalse(result["resume"]["supported"])
        self.assertIsNone(result["resume"]["command"])
        self.assertEqual(2, len(client.calls))
        with self.assertRaises(EvidenceFormatError):
            write_verification_checkpoint(result, DAY, workspace=workspace)

    def test_single_product_verification_remains_complete(self):
        workspace = self._workspace(1)

        evidence = verify_all(
            _SequenceClient(self._successes(1)),
            DAY,
            workspace=workspace,
            clock=lambda: STARTED,
        )

        self.assertEqual(2, evidence["schema_version"])
        self.assertEqual("verified", evidence["verification_status"])
        self.assertEqual("single_run", evidence["verification"]["mode"])
        self.assertEqual(["p1"], evidence["verification"]["segments"][0]["products"])
        products.validate_evidence(evidence, workspace=workspace)

    def test_partial_checkpoint_cannot_publish_or_claim_readiness(self):
        workspace = self._workspace(4)
        partial = verify_all(
            _SequenceClient([*self._successes(2), _rate_limit()]),
            DAY,
            workspace=workspace,
            clock=lambda: STARTED,
        )
        output = self.root / "must-not-publish.json"

        self.assertFalse(partial["readiness_achieved"])
        self.assertNotIn(
            partial["verification_status"], {"verified", "verified_with_gaps"}
        )
        with self.assertRaises(EvidenceFormatError):
            products.publish_evidence(partial, output, workspace=workspace)
        self.assertFalse(output.exists())

        skipped = copy.deepcopy(partial)
        skipped["pending_products"] = ["p4"]
        skipped["failure"]["product"] = "p4"
        skipped["checkpoint_sha256"] = products.verification_checkpoint_digest(skipped)
        with self.assertRaisesRegex(EvidenceFormatError, "pending suffix"):
            write_verification_checkpoint(skipped, DAY, workspace=workspace)

    def test_verify_cli_checkpoints_partial_and_never_calls_publish(self):
        workspace = self._workspace(2)
        args = gravity_cli.build_parser(("p1", "p2")).parse_args(
            ["verify", "--date", DAY.isoformat(), "--publish"]
        )
        output, error = io.StringIO(), io.StringIO()

        with mock.patch(
            "gravity_insight.sql.__main__.latest_safe_date", return_value=DAY
        ), mock.patch(
            "gravity_insight.sql.__main__.load_workspace", return_value=workspace
        ), mock.patch(
            "gravity_insight.sql.__main__._client",
            return_value=_SequenceClient([self._successes(1)[0], _rate_limit()]),
        ), mock.patch(
            "gravity_insight.sql.__main__.publish_evidence"
        ) as publish, redirect_stdout(output), redirect_stderr(error):
            exit_code = gravity_cli._run_verify_command(args)

        self.assertEqual(3, exit_code)
        self.assertFalse(json.loads(output.getvalue())["readiness_achieved"])
        publish.assert_not_called()
        self.assertTrue(
            verification_module.verification_checkpoint_path(
                DAY, workspace=workspace
            ).is_file()
        )
        self.assertIn("CHECKPOINTED", error.getvalue())


if __name__ == "__main__":
    unittest.main()
