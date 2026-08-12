from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gravity_sdk import __main__ as unified_cli
from gravity_sdk.cli import build_parser
from gravity_sdk.credentials import CredentialConfig, CredentialProvider, session_path
from gravity_sdk.sql import __main__ as sql_cli
from gravity_sdk.onboarding import (
    command_requires_credentials,
    ensure_first_run_credentials,
    should_onboard,
)


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


class _Pipe(io.StringIO):
    def isatty(self) -> bool:
        return False


class GravityOnboardingTests(unittest.TestCase):
    def test_first_interactive_run_saves_only_account_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env.gravity.local"

            def provider_factory(path: Path) -> CredentialProvider:
                return CredentialProvider(
                    path,
                    environ={},
                    login=lambda username, password: {
                        "code": 0,
                        "data": {
                            "day": 7,
                            "user": {"Authorization": f"session-for-{username}"},
                        },
                    },
                )

            output = _Terminal()
            initialized = ensure_first_run_credentials(
                env_path=env_path,
                stdin=_Terminal(),
                stderr=output,
                read_username=lambda: "analyst@example.invalid",
                read_password=lambda: "local-secret",
                provider_factory=provider_factory,
            )

            self.assertTrue(initialized)
            account_text = env_path.read_text(encoding="utf-8")
            self.assertIn("GRAVITY_USERNAME=analyst@example.invalid", account_text)
            self.assertIn("GRAVITY_PASSWORD=local-secret", account_text)
            self.assertNotIn("GRAVITY_AUTH_TOKEN", account_text)
            self.assertNotIn("GRAVITY_SDK_HOME", account_text)
            self.assertIn("GRAVITY_AUTH_TOKEN", session_path(env_path).read_text(encoding="utf-8"))
            config = CredentialConfig.from_env(env_path, environ={})
            self.assertEqual("internal_session", config.token_source)
            self.assertEqual("session-for-analyst@example.invalid", config.token)

    def test_noninteractive_run_does_not_prompt_or_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env.gravity.local"
            self.assertTrue(
                ensure_first_run_credentials(
                    env_path=env_path, stdin=_Pipe(), requires_credentials=True
                )
            )
            self.assertFalse(env_path.exists())

    def test_existing_legacy_token_is_migrated_without_prompting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env.gravity.local"
            env_path.write_text(
                "GRAVITY_USERNAME=analyst\n"
                "GRAVITY_PASSWORD=secret\n"
                "GRAVITY_AUTH_TOKEN=legacy-token\n",
                encoding="utf-8",
            )
            self.assertTrue(
                ensure_first_run_credentials(env_path=env_path, stdin=_Terminal())
            )
            self.assertNotIn("GRAVITY_AUTH_TOKEN", env_path.read_text(encoding="utf-8"))
            self.assertIn("legacy-token", session_path(env_path).read_text(encoding="utf-8"))

    def test_offline_requirement_is_derived_from_command_properties(self) -> None:
        for command in (
            ["agent"],
            ["agent", "retention"],
            ["operations", "search", "retention"],
            ["find", "retention"],
            ["metadata", "search", "retention"],
            ["validate", "analysis.retention.query", "--input", "{}"],
            ["recipe", "validate", "sample"],
            ["auth", "status"],
            ["export", "list-capabilities"],
            ["batch", "schema"],
            ["plan", "run", "--input", '{"nodes":[]}'],
            [
                "analysis", "query", "--kind", "event",
                "--spec", "{}", "--dry-run",
            ],
            [
                "analysis", "query", "batch", "--input", "{}", "--dry-run",
            ],
        ):
            with self.subTest(command=command):
                self.assertFalse(command_requires_credentials(command, build_parser))
        self.assertFalse(should_onboard(requires_credentials=False))
        self.assertTrue(
            command_requires_credentials(
                ["read", "analysis.retention.query"], build_parser
            )
        )
        self.assertTrue(command_requires_credentials(
            ["analysis", "query", "batch", "--input", "{}"], build_parser
        ))
        self.assertTrue(should_onboard(requires_credentials=True))

    def test_unified_cli_passes_parser_derived_requirement_to_onboarding(self) -> None:
        with patch.object(
            unified_cli, "ensure_first_run_credentials", return_value=True
        ) as ensure, patch("gravity_sdk.cli.main", return_value=0):
            self.assertEqual(0, unified_cli.main(["find", "retention"]))

        ensure.assert_called_once_with(requires_credentials=False)

    def test_sql_offline_commands_do_not_require_gravity_credentials(self) -> None:
        for command in (
            ["credentials", "status"],
            ["status"],
            ["evidence-preflight"],
            ["--dry-run"],
        ):
            with self.subTest(command=command):
                self.assertFalse(
                    command_requires_credentials(command, sql_cli.build_parser)
                )
        for command in (["verify"], ["query", "sample", "--start", "a", "--end", "b"]):
            with self.subTest(command=command):
                self.assertTrue(
                    command_requires_credentials(command, sql_cli.build_parser)
                )

    def test_plain_gravity_runs_first_setup_but_help_does_not(self) -> None:
        with patch.object(
            unified_cli, "ensure_first_run_credentials", return_value=True
        ) as ensure:
            self.assertEqual(0, unified_cli.main([]))
        ensure.assert_called_once_with(requires_credentials=True)

        with patch.object(
            unified_cli, "ensure_first_run_credentials", return_value=True
        ) as ensure:
            self.assertEqual(0, unified_cli.main(["--help"]))
        ensure.assert_not_called()

    def test_top_level_help_lists_resolver_and_offline_discovery(self) -> None:
        output = _Terminal()
        with patch("sys.stdout", output):
            self.assertEqual(0, unified_cli.main(["--help"]))

        rendered = output.getvalue()
        self.assertIn("gravity find <query>", rendered)
        self.assertIn("gravity agent [query]", rendered)
        self.assertIn("gravity recipe validate|check <name>", rendered)
        self.assertIn("gravity run @<recipe>", rendered)

    def test_failed_login_rolls_back_account_fields(self) -> None:
        class FailingProvider:
            def refresh(self):
                raise RuntimeError("rejected")

        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env.gravity.local"
            initialized = ensure_first_run_credentials(
                env_path=env_path,
                stdin=_Terminal(),
                stderr=_Terminal(),
                read_username=lambda: "analyst",
                read_password=lambda: "wrong",
                provider_factory=lambda _path: FailingProvider(),
            )
            self.assertFalse(initialized)
            config = CredentialConfig.from_env(env_path, environ={})
            self.assertIsNone(config.username)
            self.assertIsNone(config.password)


if __name__ == "__main__":
    unittest.main()
