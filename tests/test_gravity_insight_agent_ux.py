from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk import cli, runtime

try:
    from gravity_sdk import GravityInsightClient
    from gravity_sdk.credentials import CredentialConfig
    from gravity_sdk.errors import (
        InputValidationError,
        OperationNotImplementedError,
        UpstreamError,
    )
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_sdk import GravityInsightClient
    from gravity_sdk.credentials import CredentialConfig
    from gravity_sdk.errors import (
        InputValidationError,
        OperationNotImplementedError,
        UpstreamError,
    )


NOW = datetime(2026, 8, 9, 3, 0, tzinfo=timezone.utc)


def _jwt(expires_at: datetime) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": int(expires_at.timestamp())}).encode("utf-8")
    ).decode("ascii").rstrip("=")
    return f"header.{payload}.signature"


def _paged_operation() -> dict[str, object]:
    return {
        "operation_id": "example.items.list",
        "domain": "example",
        "resource": "items",
        "action": "list",
        "contract_version": 1,
        "upstream_method": "GET",
        "path_template": "/report/api/v3/example/items/",
        "auth_profile": "gravity_authorization",
        "stability": "stable",
        "input_fields": {
            "page": {"type": "integer", "default": 1},
            "page_size": {"type": "integer", "default": 20},
        },
        "request": {
            "path_fields": [],
            "query_fields": ["page", "page_size"],
            "body_fields": [],
            "defaults": {"page": 1, "page_size": 20},
            "fixed_query": {},
            "fixed_body": {},
        },
        "response_projection": {
            "data_shape": "object",
            "data_keys": ["list", "page_info"],
            "required_data_keys": ["list"],
            "item_keys": ["id"],
            "dynamic_item_fields": [],
        },
        "pagination": {
            "kind": "page_info",
            "page_field": "page",
            "page_size_field": "page_size",
            "list_path": "data.list",
            "page_info_path": "data.page_info",
            "total_page_field": "total_page",
            "default_page_size": 20,
            "max_page_size": 100,
        },
        "semantic_error_rules": [],
        "privacy_policy": {
            "classification": "configuration",
            "redact_keys": ["authorization", "token", "cookie"],
        },
        "required_parent": [],
        "live_probe": {"enabled": True, "input": {}},
    }


class _NeverTransport:
    is_test_transport = True

    def request(self, *_args, **_kwargs):
        raise AssertionError("caller validation must not invoke transport")


class CredentialUxTests(unittest.TestCase):
    def test_newer_managed_file_beats_stale_ambient_process_token(self) -> None:
        stale_token = _jwt(NOW - timedelta(hours=1))
        fresh_token = _jwt(NOW + timedelta(days=7))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.gravity.local"
            path.write_text(
                "\n".join(
                    (
                        "GRAVITY_USERNAME=analyst@example.invalid",
                        "GRAVITY_PASSWORD=secret",
                        f"GRAVITY_AUTH_TOKEN={fresh_token}",
                        "GRAVITY_AUTH_UPDATED_AT=2026-08-09T11:00:00+08:00",
                        "GRAVITY_AUTH_TOKEN_EXPIRES_AT_ASIA_SHANGHAI=2026-08-16T11:00:00+08:00",
                    )
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"GRAVITY_AUTH_TOKEN": stale_token},
                clear=True,
            ):
                config = CredentialConfig.from_env(path)

            self.assertEqual(fresh_token, config.token)
            self.assertEqual("credential_file", config.token_source)
            self.assertGreater(config.expires_at, NOW)

            explicit = CredentialConfig.from_env(
                path, environ={"GRAVITY_AUTH_TOKEN": stale_token}
            )
            self.assertEqual(stale_token, explicit.token)
            self.assertEqual("process_environment", explicit.token_source)

    def test_auth_status_identifies_account_without_disclosing_username(self) -> None:
        config = SimpleNamespace(
            token="secret",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            updated_at=NOW,
            username="analyst@example.invalid",
            password="secret",
            token_source="credential_file",
        )

        class Config:
            @classmethod
            def from_env(cls, _path):
                return config

        with patch.object(
            runtime,
            "_sdk_module",
            return_value=SimpleNamespace(CredentialConfig=Config),
        ):
            status = runtime.credential_status()

        self.assertEqual("a***@example.invalid", status["account_hint"])
        self.assertNotIn("analyst@example.invalid", json.dumps(status))
        self.assertEqual("credential_file", status["token_source"])
        self.assertTrue(status["token_valid"])
        self.assertNotIn("auth refresh", status["next_action"])

    def test_refresh_returns_the_post_refresh_auth_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            refreshed = {
                "auth_state": "valid_token",
                "token_valid": True,
                "account_hint": "a***@example.invalid",
            }

            class Provider:
                def __init__(self, path, *, environ):
                    self.path = path
                    self.environ = environ

                def refresh(self):
                    return SimpleNamespace(token="internal")

            with (
                patch.object(runtime, "REPO_ROOT", root),
                patch.object(
                    runtime,
                    "_sdk_module",
                    return_value=SimpleNamespace(CredentialProvider=Provider),
                ),
                patch.object(runtime, "credential_status", return_value=refreshed),
            ):
                result = runtime.refresh_credentials()

        self.assertEqual("success", result["status"])
        self.assertEqual("refreshed_internal_session", result["refresh"]["action"])
        self.assertEqual(refreshed, result["auth"])


class ErrorAndHealthUxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = GravityInsightClient._from_manifest_for_tests(
            {"manifest_version": 1, "operations": [_paged_operation()]},
            transport=_NeverTransport(),
        )

    def test_input_invalid_has_field_and_does_not_change_health(self) -> None:
        before = self.client.describe("example.items.list")["health"]

        with self.assertRaises(InputValidationError) as raised:
            self.client.read(
                "example.items.list", {"page": "1", "page_size": 1}
            )

        detail = raised.exception.to_error_detail(
            operation_id="example.items.list"
        )
        after = self.client.describe("example.items.list")["health"]
        self.assertEqual("page", detail.field)
        self.assertEqual(before, after)

        validation = self.client.validate(
            "example.items.list", {"page": "1", "page_size": 1}
        )
        self.assertEqual("page", validation["error"]["field"])
        self.assertEqual(before, self.client.describe("example.items.list")["health"])

    def test_cli_exit_codes_match_error_categories(self) -> None:
        cases = (
            (InputValidationError("input 'page' must be integer"), 2, "caller"),
            (UpstreamError("upstream unavailable"), 3, "upstream"),
            (OSError("local disk unavailable"), 4, "local"),
        )
        for error, expected_code, expected_category in cases:
            with self.subTest(category=expected_category):
                stderr = io.StringIO()
                with (
                    patch(
                        "gravity_sdk.cli.dispatch_command",
                        side_effect=error,
                    ),
                    contextlib.redirect_stderr(stderr),
                ):
                    exit_code = cli.main(["operations", "list"])
                envelope = json.loads(stderr.getvalue())
                self.assertEqual(expected_code, exit_code)
                self.assertEqual(expected_category, envelope["error"]["category"])


class DiscoveryUxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = GravityInsightClient.from_env()

    def test_default_search_prioritizes_callable_and_only_previews_draft_noise(self) -> None:
        result = self.client.search_operations(
            "当前账号 App", stability=None, limit=10
        )
        operations = result["operations"]
        non_callable = [item for item in operations if not item["executable"]]

        self.assertTrue(operations)
        self.assertEqual("stable", operations[0]["stability"])
        self.assertTrue(operations[0]["executable"])
        self.assertEqual(1, len(non_callable))
        self.assertEqual(
            "callable_stable_first", result["presentation"]["mode"]
        )
        self.assertGreater(result["total"], result["count"])
        self.assertIsNotNone(result["continuation_token"])

    def test_draft_action_is_written_for_sdk_users(self) -> None:
        operation_id = "app.app_info.get"
        described = self.client.describe(operation_id)
        action = described["next_action"]

        self.assertFalse(described["user_can_unlock"])
        self.assertIn("Contact the Gravity Insight SDK maintainers", action)
        self.assertIn(operation_id, action)
        for internal_term in ("targeted probe", "request binding", "promote contract"):
            self.assertNotIn(internal_term, action)

        with self.assertRaises(OperationNotImplementedError) as raised:
            self.client.read(operation_id, {})
        self.assertEqual(action, raised.exception.next_action)


if __name__ == "__main__":
    unittest.main()
