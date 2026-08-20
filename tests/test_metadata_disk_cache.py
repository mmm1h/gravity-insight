"""Cross-process FieldPolicy metadata snapshots on disk."""

from __future__ import annotations

import dataclasses
import json
import pickle
import tempfile
import unittest
from pathlib import Path

from gravity_sdk import cache_disk, credentials as credentials_module
from gravity_sdk.cache import MetadataCache
from gravity_sdk.client import GravityInsightClient
from gravity_sdk.credentials import DEFAULT_ENV_PATH, CredentialProvider
from gravity_sdk.models import ReadResult
from gravity_sdk.paths import PROJECT_ROOT
from gravity_sdk.runtime_scope import (
    env_isolation_key,
    field_policy_cache_dir,
    operation_catalog_state_path,
)


_EXECUTED: list[str] = []


def _detonate(token: str) -> str:
    """Module-level so pickle stores it by name and really calls it back."""

    _EXECUTED.append(token)
    return token


class _Detonator:
    """Unpickling this runs _detonate; JSON loading cannot run anything."""

    def __reduce__(self):
        return (_detonate, ("unpickled",))


def _write_account(directory: Path, name: str, username: str) -> Path:
    path = directory / name
    path.write_text(
        f"GRAVITY_USERNAME={username}\nGRAVITY_PASSWORD=pw-{username}\n",
        encoding="utf-8",
    )
    return path


def _result(name: str = "purchase") -> ReadResult:
    return ReadResult(
        schema_version="gravity-insight.read.v1",
        status="success",
        source={"system": "gravity_insight"},
        fetched_at="2026-08-19T00:00:00Z",
        schema_fingerprint="a" * 64,
        contract_version="2",
        request={"inputs": {"app_id": "101"}},
        page={"page": 1},
        data={"list": [{"name": name}]},
        operation_id="analysis.event.list",
        items=({"name": name},),
        page_info={"page": 1, "page_size": 2000, "total_page": 1},
    )


class FieldPolicyDiskCacheTests(unittest.TestCase):
    def test_disk_hit_skips_the_network_loader_in_a_new_cache(self) -> None:
        calls: list[str] = []

        def load() -> ReadResult:
            calls.append("network")
            return _result("purchase")

        first = MetadataCache(
            ["analysis.event.list"],
            persist=True,
            persist_scope="disk-hit",
            wall_clock=lambda: 10.0,
        )
        first.get_or_load("analysis.event.list", {"app_id": "101", "page": 1}, load)
        second = MetadataCache(
            ["analysis.event.list"],
            persist=True,
            persist_scope="disk-hit",
            wall_clock=lambda: 20.0,
        )

        def fail() -> ReadResult:
            raise AssertionError("disk hit must not load")

        replay = second.get_or_load(
            "analysis.event.list", {"app_id": "101", "page": 1}, fail
        )
        self.assertEqual(["network"], calls)
        self.assertEqual("purchase", replay.items[0]["name"])

    def test_expired_disk_snapshot_is_not_reused(self) -> None:
        first = MetadataCache(
            ["analysis.event.list"],
            persist=True,
            persist_scope="expired",
            wall_clock=lambda: 0.0,
        )
        first.get_or_load("analysis.event.list", {"page": 1}, _result)
        later = MetadataCache(
            ["analysis.event.list"],
            persist=True,
            persist_scope="expired",
            wall_clock=lambda: 601.0,
        )
        refreshed = later.get_or_load(
            "analysis.event.list", {"page": 1}, lambda: _result("signup")
        )
        self.assertEqual("signup", refreshed.items[0]["name"])

    def test_two_env_snapshots_do_not_mix(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            directory = Path(raw)
            first_env = _write_account(directory, "a.env.gravity.local", "user-a")
            second_env = _write_account(directory, "b.env.gravity.local", "user-b")
            key_a = env_isolation_key(first_env)
            key_b = env_isolation_key(second_env)
        cache_a = MetadataCache(
            ["analysis.event.list"], persist=True, persist_scope=key_a
        )
        cache_b = MetadataCache(
            ["analysis.event.list"], persist=True, persist_scope=key_b
        )
        cache_a.get_or_load("analysis.event.list", {"page": 1}, lambda: _result("from-a"))
        cache_b.get_or_load("analysis.event.list", {"page": 1}, lambda: _result("from-b"))
        def fail_a() -> ReadResult:
            raise AssertionError("account A disk miss")

        def fail_b() -> ReadResult:
            raise AssertionError("account B disk miss")

        replay_a = MetadataCache(
            ["analysis.event.list"], persist=True, persist_scope=key_a
        ).get_or_load("analysis.event.list", {"page": 1}, fail_a)
        replay_b = MetadataCache(
            ["analysis.event.list"], persist=True, persist_scope=key_b
        ).get_or_load("analysis.event.list", {"page": 1}, fail_b)
        path_a = str(field_policy_cache_dir(key_a))
        path_b = str(field_policy_cache_dir(key_b))
        self.assertEqual("from-a", replay_a.items[0]["name"])
        self.assertEqual("from-b", replay_b.items[0]["name"])
        self.assertNotEqual(path_a, path_b)
        self.assertIn(key_a, Path(path_a).parts)
        self.assertNotIn("user-a", path_a)
        self.assertNotIn("pw-user-a", path_a)
        self.assertNotIn("user-b", path_b)

    def test_default_persist_path_is_principal_scoped(self) -> None:
        class _Transport:
            is_test_transport = True

            def request(self, *args: object, **kwargs: object) -> None:
                raise AssertionError("path tests must not send HTTP")

        transport = _Transport()
        with tempfile.TemporaryDirectory() as raw:
            explicit = _write_account(Path(raw), "other.env.gravity.local", "file-user")
            isolated = GravityInsightClient.from_env(transport=transport, env_path=explicit)
            default_client = GravityInsightClient.from_env(transport=transport)
            default_dir = default_client._metadata_cache._persist_dir
            isolated_dir = isolated._metadata_cache._persist_dir
            isolated_scope = isolated._metadata_cache._persist_scope
        self.assertTrue(default_client._metadata_cache._persist)
        self.assertNotEqual("", default_client._metadata_cache._persist_scope)
        self.assertEqual(field_policy_cache_dir(""), default_dir)
        self.assertEqual(
            operation_catalog_state_path("").parent / "field-policy",
            default_dir,
        )
        self.assertNotEqual("", isolated_scope)
        self.assertNotEqual(default_dir, isolated_dir)
        self.assertIn(isolated_scope, isolated_dir.parts)
        self.assertNotIn("file-user", str(isolated_dir))

    def test_clear_drops_the_disk_snapshot(self) -> None:
        cache = MetadataCache(
            ["analysis.event.list"], persist=True, persist_scope="cleared"
        )
        cache.get_or_load("analysis.event.list", {"page": 1}, lambda: _result("old"))
        cache.clear()
        replay = MetadataCache(
            ["analysis.event.list"], persist=True, persist_scope="cleared"
        ).get_or_load("analysis.event.list", {"page": 1}, lambda: _result("new"))
        self.assertEqual("new", replay.items[0]["name"])


class CredentialDefaultPathTests(unittest.TestCase):
    def test_bare_credential_provider_uses_checkout_env_file(self) -> None:
        provider = CredentialProvider()
        checkout = PROJECT_ROOT / ".env.gravity.local"
        leaked = Path(credentials_module.__file__).resolve().parents[3] / ".env.gravity.local"
        self.assertEqual(checkout, DEFAULT_ENV_PATH)
        self.assertEqual(checkout, provider.env_path)
        self.assertNotEqual(leaked, DEFAULT_ENV_PATH)


class DiskSnapshotFormatTests(unittest.TestCase):
    """The cache file is attacker-reachable; the process is not."""

    def test_snapshot_is_json_and_a_pickle_payload_is_never_executed(self) -> None:
        cache = MetadataCache(
            ["analysis.event.list"], persist=True, persist_scope="format"
        )
        cache.get_or_load("analysis.event.list", {"page": 1}, lambda: _result("first"))
        directory = field_policy_cache_dir("format")
        written = sorted(directory.glob("*"))
        self.assertEqual(1, len(written), written)
        self.assertEqual(".json", written[0].suffix)
        decoded = json.loads(written[0].read_text(encoding="utf-8"))
        self.assertEqual("gravity.field-policy-cache.v1", decoded["schema"])

        # A pickle that would run code on load must be inert here.
        marker: list[str] = []
        _EXECUTED.clear()
        written[0].write_bytes(pickle.dumps(_Detonator()))
        replay = MetadataCache(
            ["analysis.event.list"], persist=True, persist_scope="format"
        ).get_or_load(
            "analysis.event.list", {"page": 1}, lambda: _result("reloaded")
        )
        self.assertEqual([], _EXECUTED, "cache file must never be unpickled")
        self.assertEqual("reloaded", replay.items[0]["name"])
        self.assertEqual([], marker)

    def test_read_result_survives_the_json_round_trip_with_field_types(self) -> None:
        original = _result("round-trip")
        restored = cache_disk._decode(cache_disk._encode(original))
        self.assertEqual(original, restored)
        for item in dataclasses.fields(ReadResult):
            self.assertEqual(
                type(getattr(original, item.name)),
                type(getattr(restored, item.name)),
                f"{item.name} changed type across the round trip",
            )
