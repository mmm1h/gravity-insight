from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest import mock

from gravity_insight.sql import __main__ as sql_cli
from gravity_insight.sql.credentials import CredentialSyncError, CredentialSyncNotReady
from gravity_insight.sql.products import EvidenceFormatError
from gravity_insight.workspace import WorkspaceError


class SqlCliBoundaryTests(unittest.TestCase):
    def assert_failure(
        self,
        output: io.StringIO,
        *,
        command: str,
        code: str,
        stage: str,
        exit_code: int,
        reached_upstream: str = "no",
    ) -> dict[str, object]:
        payload = json.loads(output.getvalue())
        self.assertEqual("gravity-sql.command-error.v1", payload["schema_version"])
        self.assertEqual(command, payload["command"])
        self.assertEqual(exit_code, payload["exit_code"])
        self.assertFalse(payload["ok"])
        error = payload["error"]
        self.assertEqual(code, error["code"])
        self.assertEqual(stage, error["stage"])
        self.assertFalse(error["retryable"])
        self.assertEqual(reached_upstream, error["reached_upstream"])
        self.assertEqual("no", error["reached_sql_engine"])
        self.assertTrue(error["next_action"])
        self.assertEqual(0, error["execution_evidence"]["request_count"])
        self.assertEqual(
            "gravity_sql_engine", error["execution_evidence"]["request_scope"]
        )
        return payload

    def test_credentials_preserve_not_ready_and_unknown_reachability(self) -> None:
        cases = (
            (
                CredentialSyncNotReady("secret credential path token=abc123"),
                "SQL_CREDENTIAL_SYNC_NOT_READY",
                "bind",
                "no",
            ),
            (
                CredentialSyncError("secret GitHub response token=abc123"),
                "SQL_CREDENTIAL_SYNC_FAILED",
                "execute",
                "unknown",
            ),
        )
        for error, code, stage, reached in cases:
            with self.subTest(code=code), mock.patch.object(
                sql_cli.credentials, "pull", side_effect=error
            ), redirect_stderr(io.StringIO()) as output:
                exit_code = sql_cli._run_credentials(
                    SimpleNamespace(credential_command="pull", if_enabled=False)
                )
            self.assertEqual(1, exit_code)
            self.assert_failure(
                output,
                command="credentials.pull",
                code=code,
                stage=stage,
                exit_code=1,
                reached_upstream=reached,
            )
            self.assertNotIn("abc123", output.getvalue())

    def test_product_discovery_distinguishes_invalid_and_empty_workspace(self) -> None:
        cases = (
            (True, "SQL_WORKSPACE_INVALID"),
            (False, "SQL_PRODUCTS_NOT_CONFIGURED"),
        )
        for invalid, code in cases:
            with self.subTest(code=code), redirect_stderr(io.StringIO()) as output:
                exit_code = sql_cli._missing_products_error((), invalid, "products")
            self.assertEqual(2, exit_code)
            self.assert_failure(
                output,
                command="products",
                code=code,
                stage="bind",
                exit_code=2,
            )

    def test_configured_product_discovery_retains_typed_failure_state(self) -> None:
        with mock.patch.object(
            sql_cli, "product_names", side_effect=WorkspaceError("secret token=abc123")
        ):
            products, invalid = sql_cli._configured_products()
        self.assertEqual((), products)
        self.assertTrue(invalid)

    def test_status_classifies_evidence_and_workspace_failures(self) -> None:
        cases = (
            (
                "resolve_current_evidence",
                EvidenceFormatError("secret evidence token=abc123"),
                "SQL_STATUS_EVIDENCE_INVALID",
                "shape",
            ),
            (
                "load_workspace",
                WorkspaceError("secret workspace token=abc123"),
                "SQL_WORKSPACE_INVALID",
                "bind",
            ),
        )
        for target, error, code, stage in cases:
            with self.subTest(code=code), mock.patch.object(
                sql_cli,
                "load_workspace",
                side_effect=error if target == "load_workspace" else None,
                return_value=object(),
            ), mock.patch.object(
                sql_cli,
                "resolve_current_evidence",
                side_effect=error if target == "resolve_current_evidence" else None,
                return_value=object(),
            ), redirect_stderr(io.StringIO()) as output:
                exit_code = sql_cli._run_status_command(SimpleNamespace(json=True))
            self.assertEqual(2, exit_code)
            self.assert_failure(
                output,
                command="status",
                code=code,
                stage=stage,
                exit_code=2,
            )
            self.assertNotIn("abc123", output.getvalue())

    def test_evidence_preflight_classifies_each_boundary_stage(self) -> None:
        cases = (
            (
                OSError("secret local path token=abc123"),
                "SQL_EVIDENCE_PREFLIGHT_LOCAL_IO",
                "bind",
                4,
            ),
            (
                EvidenceFormatError("secret evidence token=abc123"),
                "SQL_EVIDENCE_PREFLIGHT_CONTRACT_INVALID",
                "shape",
                2,
            ),
            (
                ValueError("secret date token=abc123"),
                "SQL_EVIDENCE_PREFLIGHT_INPUT_INVALID",
                "bind",
                2,
            ),
        )
        for error, code, stage, expected_exit in cases:
            with self.subTest(code=code), mock.patch.object(
                sql_cli, "load_workspace", return_value=object()
            ), mock.patch.object(
                sql_cli, "evidence_preflight", side_effect=error
            ), redirect_stderr(io.StringIO()) as output:
                exit_code = sql_cli._run_preflight_command(
                    SimpleNamespace(date=None, json=True)
                )
            self.assertEqual(expected_exit, exit_code)
            self.assert_failure(
                output,
                command="evidence-preflight",
                code=code,
                stage=stage,
                exit_code=expected_exit,
            )
            self.assertNotIn("abc123", output.getvalue())
