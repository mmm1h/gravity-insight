"""Isolation of credentials, shared runtime, and metadata cache across env files."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from gravity_sdk.cache import MetadataCache
from gravity_sdk.client import GravityInsightClient
from gravity_sdk.credentials import CredentialProvider
from gravity_sdk.find_metadata import _default_catalog_path
from gravity_sdk.shared_runtime import get_shared_runtime
from gravity_sdk import shared_runtime as runtime_module
from gravity_sdk.metadata_sync import default_catalog_path
from gravity_sdk.runtime_scope import (
    env_isolation_key,
    metadata_catalog_path,
    operation_catalog_state_path,
    resolve_env_path,
)
from gravity_sdk.paths import PROJECT_ROOT


def _reset_shared_runtimes() -> None:
    runtime_module.reset_shared_runtimes()


def _write_account(directory: Path, name: str, username: str) -> Path:
    path = directory / name
    path.write_text(
        f"GRAVITY_USERNAME={username}\nGRAVITY_PASSWORD=pw-{username}\n",
        encoding="utf-8",
    )
    return path


class SharedRuntimeIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_shared_runtimes()

    def tearDown(self) -> None:
        _reset_shared_runtimes()

    def test_two_env_files_get_distinct_shared_runtimes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            first = _write_account(directory, "a.env.gravity.local", "user-a")
            second = _write_account(directory, "b.env.gravity.local", "user-b")
            runtime_a = get_shared_runtime(env_path=first, timeout=5.0, attempts=1)
            runtime_b = get_shared_runtime(env_path=second, timeout=5.0, attempts=1)
            again = get_shared_runtime(env_path=first, timeout=5.0, attempts=1)
        self.assertIsNot(runtime_a, runtime_b)
        self.assertIs(runtime_a, again)

    def test_default_env_path_stays_the_checkout_local_file(self) -> None:
        selected, isolated = resolve_env_path(None)
        self.assertEqual(PROJECT_ROOT / ".env.gravity.local", selected)
        self.assertFalse(isolated)

    def test_gravity_env_file_selects_an_explicit_account_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = _write_account(Path(raw), "named.env.gravity.local", "named-user")
            with mock.patch.dict(os.environ, {"GRAVITY_ENV_FILE": str(path)}):
                selected, isolated = resolve_env_path(None)
        self.assertEqual(path, selected)
        self.assertTrue(isolated)


class MetadataCacheIsolationTests(unittest.TestCase):
    def test_shared_cache_does_not_return_another_accounts_snapshot(self) -> None:
        cache = MetadataCache(["app.list"])
        first = cache.get_or_load(
            "app.list",
            {"page": 1},
            lambda: {"account": "A"},
            isolation_key="scope-a",
        )
        second = cache.get_or_load(
            "app.list",
            {"page": 1},
            lambda: {"account": "B"},
            isolation_key="scope-b",
        )
        self.assertEqual({"account": "A"}, first)
        self.assertEqual({"account": "B"}, second)

    def test_stats_do_not_include_the_isolation_key(self) -> None:
        cache = MetadataCache(["app.list"])
        cache.get_or_load("app.list", {}, lambda: {"ok": True}, isolation_key="secret-scope")
        stats = cache.stats()
        serialized = repr(stats)
        self.assertNotIn("secret-scope", serialized)
        self.assertNotIn("isolation", serialized)


class DiskPathIsolationTests(unittest.TestCase):
    def test_catalog_paths_include_env_fingerprint_not_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            first = _write_account(directory, "a.env.gravity.local", "user-a")
            second = _write_account(directory, "b.env.gravity.local", "user-b")
            key_a = env_isolation_key(first)
            key_b = env_isolation_key(second)
            path_a = operation_catalog_state_path(key_a)
            path_b = operation_catalog_state_path(key_b)
            sqlite_a = metadata_catalog_path(key_a)
            sqlite_b = metadata_catalog_path(key_b)
        self.assertNotEqual(key_a, key_b)
        self.assertTrue(key_a.isalnum())
        self.assertNotEqual(path_a, path_b)
        self.assertNotEqual(sqlite_a, sqlite_b)
        joined = os.path.join(str(path_a), str(path_b), str(sqlite_a), str(sqlite_b))
        self.assertNotIn("user-a", joined)
        self.assertNotIn("pw-user-a", joined)
        self.assertNotIn("user-b", joined)
        self.assertIn(key_a, path_a.parts)
        self.assertIn(key_b, sqlite_b.parts)
        self.assertEqual(sqlite_a, default_catalog_path(isolation_key=key_a))
        self.assertEqual(sqlite_a, _default_catalog_path(isolation_key=key_a))


class ExplicitEnvIgnoresProcessTokenTests(unittest.TestCase):
    def test_explicit_env_file_does_not_reuse_process_token(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = _write_account(Path(raw), "other.env.gravity.local", "file-user")
            isolated = CredentialProvider(path, persist=False, isolated=True)
            ambient = CredentialProvider(path, persist=False, isolated=False)
            with mock.patch.dict(os.environ, {"GRAVITY_AUTH_TOKEN": "process-token"}):
                self.assertIsNone(isolated._load())
                self.assertEqual("process-token", ambient._load().token)

    def test_explicit_from_env_files_keep_separate_catalog_paths(self) -> None:
        class _Transport:
            is_test_transport = True

            def request(self, *args: object, **kwargs: object) -> None:
                raise AssertionError("isolation tests must not send HTTP")

        transport = _Transport()
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            first = _write_account(directory, "a.env.gravity.local", "user-a")
            second = _write_account(directory, "b.env.gravity.local", "user-b")
            client_a = GravityInsightClient.from_env(transport=transport, env_path=first)
            client_b = GravityInsightClient.from_env(transport=transport, env_path=second)
            default_client = GravityInsightClient.from_env(transport=transport)
        path_a = client_a._operation_catalog._state_path
        path_b = client_b._operation_catalog._state_path
        default_path = default_client._operation_catalog._state_path
        self.assertNotEqual(path_a, path_b)
        self.assertNotEqual(path_a, default_path)
        self.assertEqual(default_path, operation_catalog_state_path(""))


class MaxConcurrencySourceTests(unittest.TestCase):
    def test_process_concurrency_ceiling_is_defined_once(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src" / "gravity_sdk"
        assignments = []
        for path in root.rglob("*.py"):
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.replace(" ", "") == "MAX_CONCURRENCY=24":
                    assignments.append(f"{path.relative_to(root.parent.parent)}:{line_number}")
        self.assertEqual(
            ["src/gravity_sdk/process_limits.py"],
            [item.split(":")[0].replace("\\", "/") for item in assignments],
        )
