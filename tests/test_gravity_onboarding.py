from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gravity_insight import __main__ as unified_cli
from gravity_insight import runtime
from gravity_insight.cli import build_parser
from gravity_insight.credentials import CredentialConfig, CredentialProvider, session_path
from gravity_insight.errors import InputValidationError
from gravity_insight.runtime_scope import credential_location_diagnosis
from gravity_insight.sql import __main__ as sql_cli
from gravity_insight.onboarding import (
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
                            "user": {
                                "Authorization": f"session-for-{username}",
                                "id": "17",
                            },
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
            self.assertEqual("17", config.gravity_id)
            cached = CredentialProvider(env_path, environ={}, persist=False)
            self.assertEqual("17", cached.current_principal_id())

    def test_noninteractive_run_does_not_prompt_or_write(self) -> None:
        from gravity_insight.errors import InputValidationError

        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env.gravity.local"
            with self.assertRaises(InputValidationError) as caught:
                ensure_first_run_credentials(
                    env_path=env_path, stdin=_Pipe(), requires_credentials=True
                )
            self.assertEqual("auth", caught.exception.field)
            self.assertIn("auth refresh", str(caught.exception.next_action))
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
        ) as ensure, patch("gravity_insight.cli.main", return_value=0):
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
        self.assertIn("gravity recipe validate|check|accept-contract <name>", rendered)
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


class CredentialLocationSelectionTests(unittest.TestCase):
    """Regressions for #226: workspace-scoped credential selection diagnostics.

    A business workspace resolves its own credential location, so a previous
    default-location login is not visible there. That isolation is intended;
    these tests pin the diagnostics that explain it instead of a fallback.
    """

    def _layout(self, root: Path) -> tuple[dict[str, str], Path, Path]:
        cache = root / "cache"
        default_path = cache / "default" / ".env.gravity.local"
        default_path.parent.mkdir(parents=True)
        default_path.write_text(
            "GRAVITY_USERNAME=analyst@example.invalid\nGRAVITY_PASSWORD=local-secret\n",
            encoding="utf-8",
        )
        workspace_path = cache / "workspaces" / "biz-0123456789ab" / ".env.gravity.local"
        workspace_path.parent.mkdir(parents=True)
        home = root / "home"
        home.mkdir()
        # cache_roots() also consults LOCALAPPDATA, XDG_CACHE_HOME and Path.home().
        # Redirect every one of them into the temporary tree so no test ever reads
        # the developer's real credential directory.
        return (
            {
                "GRAVITY_CACHE_HOME": str(cache),
                "LOCALAPPDATA": str(home),
                "XDG_CACHE_HOME": str(home),
                "USERPROFILE": str(home),
                "HOME": str(home),
                "HOMEDRIVE": home.drive,
                "HOMEPATH": str(home)[len(home.drive):],
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
                "PATH": os.environ.get("PATH", ""),
            },
            default_path,
            workspace_path,
        )

    def test_workspace_location_reports_the_configured_default_without_selecting_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environ, default_path, workspace_path = self._layout(Path(directory))

            with patch.dict(os.environ, environ, clear=True):
                diagnosis = credential_location_diagnosis(workspace_path, environ=environ)

            self.assertFalse(diagnosis["selected_configured"])
            self.assertTrue(diagnosis["mismatch"])
            self.assertEqual(str(workspace_path), diagnosis["selected_path"])
            self.assertIn(str(default_path), diagnosis["configured_elsewhere"])
            self.assertEqual("GRAVITY_ENV_FILE", diagnosis["env_file_variable"])
            # The mismatch is reported, never resolved by adopting the account.
            self.assertNotIn("analyst@example.invalid", json.dumps(diagnosis))
            self.assertNotIn("local-secret", json.dumps(diagnosis))

    def test_explicitly_selected_configured_file_reports_no_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environ, default_path, _workspace_path = self._layout(Path(directory))

            with patch.dict(os.environ, environ, clear=True):
                diagnosis = credential_location_diagnosis(default_path, environ=environ)

            self.assertTrue(diagnosis["selected_configured"])
            self.assertFalse(diagnosis["mismatch"])
            self.assertEqual([], diagnosis["configured_elsewhere"])

    def test_unconfigured_location_without_alternatives_reports_no_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environ, default_path, workspace_path = self._layout(Path(directory))
            default_path.unlink()

            with patch.dict(os.environ, environ, clear=True):
                diagnosis = credential_location_diagnosis(workspace_path, environ=environ)

            self.assertFalse(diagnosis["selected_configured"])
            self.assertFalse(diagnosis["mismatch"])
            self.assertEqual([], diagnosis["configured_elsewhere"])

    def test_non_interactive_onboarding_does_not_advertise_auth_refresh(self) -> None:
        """#226 step 3: refresh cannot fix a location mismatch, so never suggest it."""

        with tempfile.TemporaryDirectory() as directory:
            environ, default_path, workspace_path = self._layout(Path(directory))
            with patch.dict(os.environ, environ, clear=True):
                with self.assertRaises(InputValidationError) as raised:
                    ensure_first_run_credentials(
                        env_path=workspace_path,
                        stdin=_Pipe(),
                        stderr=_Pipe(),
                    )

            next_action = raised.exception.next_action
            self.assertIn(str(default_path), next_action)
            self.assertIn("GRAVITY_ENV_FILE", next_action)
            self.assertIn("ignores process-environment credentials", next_action)
            # auth refresh may be named, but only to rule it out, never as the action.
            self.assertIn("`auth refresh` cannot resolve this", next_action)
            self.assertNotIn("run `gravity insight auth refresh`", next_action)
            self.assertNotIn("Run `gravity auth refresh`", next_action)

    def test_auth_status_reports_the_location_mismatch_instead_of_bare_missing(self) -> None:
        """#226 steps 1-2: a previous default login must be explained, not hidden."""

        with tempfile.TemporaryDirectory() as directory:
            environ, default_path, workspace_path = self._layout(Path(directory))
            selected = {**environ, "GRAVITY_ENV_FILE": str(workspace_path)}

            with patch.dict(os.environ, selected, clear=True):
                status = runtime.credential_status()

            self.assertEqual("missing", status["auth_state"])
            self.assertEqual("CREDENTIAL_LOCATION_MISMATCH", status["remediation_code"])
            self.assertFalse(status["onboarding_satisfied"])
            self.assertIn(str(default_path), status["next_action"])
            self.assertIn(
                str(default_path), status["credential_location"]["configured_elsewhere"]
            )
            self.assertNotIn("analyst@example.invalid", json.dumps(status))

    def test_auth_status_does_not_advertise_refresh_for_ambient_only_credentials(self) -> None:
        """#226 step 3: status and onboarding must not disagree about readiness."""

        with tempfile.TemporaryDirectory() as directory:
            environ, _default_path, workspace_path = self._layout(Path(directory))
            exported = {
                **environ,
                "GRAVITY_ENV_FILE": str(workspace_path),
                "GRAVITY_USERNAME": "analyst@example.invalid",
                "GRAVITY_PASSWORD": "local-secret",
            }

            with patch.dict(os.environ, exported, clear=True):
                status = runtime.credential_status()

            self.assertEqual("credentials_available", status["auth_state"])
            self.assertTrue(status["can_exchange_credentials"])
            # Readiness is still reported, but the dead-end remediation is not.
            self.assertFalse(status["onboarding_satisfied"])
            self.assertEqual("CREDENTIAL_AMBIENT_ONLY", status["remediation_code"])
            self.assertIn("will reject them", status["next_action"])
            self.assertNotIn(
                "Run `gravity auth refresh` to exchange", status["next_action"]
            )
            self.assertNotIn("local-secret", json.dumps(status))

    def test_auth_status_keeps_the_plain_refresh_action_when_onboarding_agrees(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environ, default_path, _workspace_path = self._layout(Path(directory))
            selected = {**environ, "GRAVITY_ENV_FILE": str(default_path)}

            with patch.dict(os.environ, selected, clear=True):
                status = runtime.credential_status()

            self.assertEqual("credentials_available", status["auth_state"])
            self.assertTrue(status["onboarding_satisfied"])
            self.assertIsNone(status["remediation_code"])
            self.assertIn("Run `gravity auth refresh`", status["next_action"])

    def test_process_environment_credentials_are_rejected_by_onboarding(self) -> None:
        """#226 step 3: exporting credentials satisfies auth status but not onboarding."""

        with tempfile.TemporaryDirectory() as directory:
            environ, _default_path, workspace_path = self._layout(Path(directory))
            exported = {
                **environ,
                "GRAVITY_USERNAME": "analyst@example.invalid",
                "GRAVITY_PASSWORD": "local-secret",
            }

            ambient = CredentialConfig.from_env(workspace_path)
            persisted = CredentialConfig.from_env(workspace_path, environ={})

            self.assertIsNone(persisted.username)
            self.assertIsNone(persisted.password)
            with patch.dict(os.environ, exported, clear=True):
                ambient = CredentialConfig.from_env(workspace_path)
            self.assertEqual("analyst@example.invalid", ambient.username)


if __name__ == "__main__":
    unittest.main()
