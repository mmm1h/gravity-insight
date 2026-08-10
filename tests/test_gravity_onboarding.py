from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path

from gravity_sdk.credentials import CredentialConfig, CredentialProvider, session_path
from gravity_sdk.onboarding import ensure_first_run_credentials, should_onboard


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
                [],
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
                    ["insight", "read"], env_path=env_path, stdin=_Pipe()
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
                ensure_first_run_credentials([], env_path=env_path, stdin=_Terminal())
            )
            self.assertNotIn("GRAVITY_AUTH_TOKEN", env_path.read_text(encoding="utf-8"))
            self.assertIn("legacy-token", session_path(env_path).read_text(encoding="utf-8"))

    def test_help_and_dry_run_never_start_onboarding(self) -> None:
        self.assertFalse(should_onboard(["--help"]))
        self.assertFalse(should_onboard(["sql", "--dry-run"]))
        self.assertFalse(should_onboard(["census", "--smoke"]))
        self.assertTrue(should_onboard(["insight", "auth", "status"]))

    def test_failed_login_rolls_back_account_fields(self) -> None:
        class FailingProvider:
            def refresh(self):
                raise RuntimeError("rejected")

        with tempfile.TemporaryDirectory() as directory:
            env_path = Path(directory) / ".env.gravity.local"
            initialized = ensure_first_run_credentials(
                [],
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
