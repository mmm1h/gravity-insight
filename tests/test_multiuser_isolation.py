"""Isolation of credentials, shared runtime, and metadata cache across env files."""

from __future__ import annotations

import os
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

from gravity_insight import connect
from gravity_insight.cache import MetadataCache
from gravity_insight.client import GravityInsightClient
from gravity_insight.credential_storage import session_path
from gravity_insight.credentials import CredentialProvider
from gravity_insight.errors import CredentialError, InputValidationError
from gravity_insight.find_metadata import _default_catalog_path, search_metadata
from gravity_insight.shared_runtime import get_shared_runtime
from gravity_insight import shared_runtime as runtime_module
from gravity_insight.metadata_sync import default_catalog_path
from gravity_insight.metadata_status import metadata_status
from gravity_insight.receipt_cli import dispatch as receipt_dispatch
from gravity_insight.receipt import record_completed_http_response, request_receipt_context
from gravity_insight.runtime_scope import (
    env_isolation_key,
    field_policy_cache_dir,
    metadata_catalog_path,
    operation_catalog_state_path,
    resolve_env_path,
    runtime_scope_key,
)
from gravity_insight.paths import PROJECT_ROOT


def _reset_shared_runtimes() -> None:
    runtime_module.reset_shared_runtimes()


def _write_account(directory: Path, name: str, username: str) -> Path:
    path = directory / name
    path.write_text(
        f"GRAVITY_USERNAME={username}\nGRAVITY_PASSWORD=pw-{username}\n",
        encoding="utf-8",
    )
    return path


def _write_session(path: Path, label: str) -> None:
    session_path(path).write_text(
        f"GRAVITY_AUTH_TOKEN=fixture-token-{label}\nGRAVITY_SESSION_USERNAME=fixture-{label}\n",
        encoding="utf-8",
    )


class SharedRuntimeIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        _reset_shared_runtimes()

    def tearDown(self) -> None:
        _reset_shared_runtimes()

    def test_same_path_account_change_replaces_all_identity_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            path = _write_account(directory, "account.env.gravity.local", "fixture-a")
            _write_session(path, "a")
            sdk_a = connect(env_path=path)
            runtime_a, client_a = sdk_a.sql._runtime, sdk_a.insight
            runtime_a.__dict__["_GravityHttpRuntime__credentials"].get()
            operation_id = next(iter(client_a._metadata_cache._operation_ids))
            client_a._metadata_cache.get_or_load(operation_id, {}, lambda: {"fixture": "a"})
            _write_account(directory, path.name, "fixture-b")
            _write_session(path, "b")
            sdk_b = connect(env_path=path)
            runtime_b, client_b = sdk_b.sql._runtime, sdk_b.insight
            runtime_b.__dict__["_GravityHttpRuntime__credentials"].get()
            cached_b = client_b._metadata_cache.get_or_load(operation_id, {}, lambda: {"fixture": "b"})
        self.assertIsNot(runtime_a, runtime_b)
        for name in ("session", "credentials"):
            self.assertIsNot(runtime_a.__dict__[f"_GravityHttpRuntime__{name}"], runtime_b.__dict__[f"_GravityHttpRuntime__{name}"])
        for name in ("_metadata_cache", "_operation_catalog", "_field_policy"):
            self.assertIsNot(getattr(client_a, name), getattr(client_b, name))
        self.assertNotEqual(client_a._operation_catalog._state_path, client_b._operation_catalog._state_path)
        self.assertNotEqual(client_a._metadata_cache._persist_dir, client_b._metadata_cache._persist_dir)
        self.assertNotEqual(sdk_a.workspace.state_root, sdk_b.workspace.state_root)
        self.assertEqual({"fixture": "b"}, cached_b)
        with self.assertRaises(CredentialError):
            runtime_a.__dict__["_GravityHttpRuntime__credentials"].get()

    def test_principal_runtimes_keep_process_governance_singletons(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            first = get_shared_runtime(env_path=_write_account(directory, "a.env", "fixture-a"))
            second = get_shared_runtime(env_path=_write_account(directory, "b.env", "fixture-b"))
        for name in ("limiter", "governor"):
            self.assertIs(first.__dict__[f"_GravityHttpRuntime__{name}"], second.__dict__[f"_GravityHttpRuntime__{name}"])

    def test_default_env_path_stays_the_checkout_local_file(self) -> None:
        selected, isolated = resolve_env_path(None)
        self.assertEqual(PROJECT_ROOT / ".env.gravity.local", selected)
        self.assertFalse(isolated)

    def test_default_env_account_change_scopes_runtime_and_disk_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw, mock.patch(
            "gravity_insight.runtime_scope.PROJECT_ROOT", Path(raw)
        ):
            path = _write_account(Path(raw), ".env.gravity.local", "fixture-a")
            first = get_shared_runtime()
            first_paths = (operation_catalog_state_path(), metadata_catalog_path(), field_policy_cache_dir())
            _write_account(Path(raw), path.name, "fixture-b")
            second = get_shared_runtime()
            second_paths = (operation_catalog_state_path(), metadata_catalog_path(), field_policy_cache_dir())
        self.assertIsNot(first, second)
        self.assertTrue(all(first_path != second_path for first_path, second_path in zip(first_paths, second_paths)))

    def test_credential_generation_change_replaces_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = _write_account(Path(raw), "account.env", "fixture-account")
            path.write_text(path.read_text(encoding="utf-8") + "GRAVITY_AUTH_UPDATED_AT=fixture-generation-a\n", encoding="utf-8")
            first_scope, first = runtime_scope_key(path), get_shared_runtime(env_path=path)
            path.write_text(path.read_text(encoding="utf-8").replace("generation-a", "generation-b"), encoding="utf-8")
            second_scope, second = runtime_scope_key(path), get_shared_runtime(env_path=path)
        self.assertNotEqual(first_scope.credential_generation, second_scope.credential_generation)
        self.assertIsNot(first, second)

    def test_first_login_does_not_move_persistent_account_storage(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = _write_account(Path(raw), "account.env", "fixture-account")
            before_scope = runtime_scope_key(path)
            before_key = env_isolation_key(path)
            session_path(path).write_text(
                "GRAVITY_AUTH_TOKEN=fixture-token\n"
                "GRAVITY_AUTH_UPDATED_AT=fixture-generation\n"
                "GRAVITY_PRINCIPAL_ID=fixture-principal\n"
                "GRAVITY_SESSION_USERNAME=fixture-account\n",
                encoding="utf-8",
            )
            after_scope = runtime_scope_key(path)
            after_key = env_isolation_key(path)

        self.assertNotEqual(before_scope.fingerprint, after_scope.fingerprint)
        self.assertEqual(before_key, after_key)
        self.assertEqual(
            metadata_catalog_path(before_key), metadata_catalog_path(after_key)
        )

    def test_scope_material_and_fingerprint_stay_out_of_public_output(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            path = _write_account(root, "account.env", "fixture-private")
            session_path(path).write_text(
                "GRAVITY_AUTH_TOKEN=fixture-token\nGRAVITY_AUTH_UPDATED_AT=fixture-generation\nGRAVITY_PRINCIPAL_ID=fixture-principal\nGRAVITY_SESSION_USERNAME=fixture-private\n",
                encoding="utf-8",
            )
            scope = runtime_scope_key(path, workspace_root=root)
            receipt_root = root / "principals" / scope.fingerprint
            record_completed_http_response(type("Response", (), {"status_code": 200})(), request_receipt_context(operation_id="app.list", method="GET", path="/fixture/read"), receipt_root)
            with mock.patch.dict(os.environ, {"GRAVITY_ENV_FILE": str(path)}), mock.patch("gravity_insight.paths.STATE_ROOT", root):
                public = [metadata_status(), receipt_dispatch(Namespace(receipt_command="list", limit=1, cursor=None, operation_id=None), lambda _: {})]
                with self.assertRaises(InputValidationError) as raised:
                    search_metadata()
            rendered = json.dumps(public) + repr(scope) + str(raised.exception)
        for private in (str(path), "fixture-private", "pw-fixture-private", "fixture-token", "fixture-generation", "fixture-principal", scope.fingerprint):
            self.assertNotIn(private, rendered)

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
        root = Path(__file__).resolve().parents[1] / "src" / "gravity_insight"
        assignments = []
        for path in root.rglob("*.py"):
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if line.replace(" ", "") == "MAX_CONCURRENCY=24":
                    assignments.append(f"{path.relative_to(root.parent.parent)}:{line_number}")
        self.assertEqual(
            ["src/gravity_insight/process_limits.py"],
            [item.split(":")[0].replace("\\", "/") for item in assignments],
        )
