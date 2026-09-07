from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from gravity_insight.skill_hub_client import SkillHubClient
from gravity_insight.skill_hub_contract import SkillHubContractError
from gravity_insight.skill_hub_source import validate_bundled_skill_seed
from gravity_insight.skill_hub_state import (
    build_skill_maintenance_receipt,
    write_skill_maintenance_receipt,
)
from scripts import generate_skill_library as builder


class SkillSeedBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.outputs = builder.render_outputs()
        cls.seed = builder.render_seed(cls.outputs)
        cls.seed_digest = hashlib.sha256(cls.seed).hexdigest()

    def test_seed_is_deterministic_manifest_bound_and_contains_only_93_assets(self) -> None:
        rebuilt = builder.render_seed(builder.render_outputs())
        self.assertEqual(self.seed, rebuilt)
        validated = validate_bundled_skill_seed(self.seed)

        self.assertEqual(self.seed_digest, validated["seed_digest"])
        self.assertEqual(93, len(validated["files"]))
        self.assertEqual(44, validated["skill_count"])
        self.assertEqual(44, validated["agent_skill_count"])
        self.assertFalse(validated["network_called"])
        self.assertNotIn("skills/sources/registry.json", validated["files"])
        self.assertFalse(
            any(name.startswith("skills/library/") for name in validated["files"])
        )

    def test_empty_cache_bootstrap_is_offline_exact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            client = SkillHubClient(root / "state", cas_root=root / "cas")
            project_lock = root / "project" / "gravity.skills.lock.json"
            project_lock.parent.mkdir()
            project_lock.write_text('{"sentinel":true}\n', encoding="utf-8")
            self.assertEqual(0, client.list()["count"])

            with patch.object(
                socket,
                "socket",
                side_effect=AssertionError("network attempted"),
            ):
                first = client.bootstrap_bundled(
                    self.seed, at="2026-09-07T01:00:00Z"
                )

            self.assertEqual("ready", first["status"])
            self.assertTrue(first["changed"])
            self.assertEqual(44, first["skill_count"])
            self.assertEqual(44, first["artifacts_verified"])
            self.assertEqual(44, first["artifacts_written"])
            self.assertFalse(first["network_called"])
            self.assertEqual(44, client.list()["count"])
            self.assertEqual('{"sentinel":true}\n', project_lock.read_text(encoding="utf-8"))

            managed_lock = root / "state" / "skill-maintenance" / "managed-skills.lock.json"
            managed_before = managed_lock.read_bytes()
            cas_files = {
                path: (path.read_bytes(), path.stat().st_mtime_ns)
                for path in (root / "cas" / "skills" / "sha256").rglob("*")
                if path.is_file()
            }
            second = client.bootstrap_bundled(
                self.seed, at="2026-09-07T01:01:00Z"
            )

            self.assertEqual("ready", second["status"])
            self.assertFalse(second["changed"])
            self.assertEqual(44, second["artifacts_verified"])
            self.assertEqual(0, second["artifacts_written"])
            self.assertEqual(first["managed_lock_digest"], second["managed_lock_digest"])
            self.assertEqual(managed_before, managed_lock.read_bytes())
            self.assertEqual(
                cas_files,
                {
                    path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in (root / "cas" / "skills" / "sha256").rglob("*")
                    if path.is_file()
                },
            )

    def test_tampered_seed_fails_closed_and_retains_last_known_good(self) -> None:
        tampered = bytearray(self.seed)
        tampered[len(tampered) // 2] ^= 1
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            client = SkillHubClient(root / "state", cas_root=root / "cas")
            with self.assertRaisesRegex(SkillHubContractError, "HUB_SEED_INVALID"):
                client.bootstrap_bundled(
                    bytes(tampered), at="2026-09-07T01:00:00Z"
                )
            unavailable = client.status()
            self.assertEqual("unavailable", unavailable["status"])
            self.assertTrue(unavailable["bootstrap_checked"])
            self.assertEqual(0, unavailable["skill_count"])

            client.bootstrap_bundled(self.seed, at="2026-09-07T01:01:00Z")
            with self.assertRaisesRegex(SkillHubContractError, "HUB_SEED_INVALID"):
                client.bootstrap_bundled(
                    bytes(tampered), at="2026-09-07T01:02:00Z"
                )
            degraded = client.status()
            self.assertEqual("degraded", degraded["status"])
            self.assertEqual(44, degraded["skill_count"])
            self.assertEqual(44, client.list()["count"])
            self.assertEqual(["HUB_SEED_INVALID"], degraded["reason_codes"])

    def test_concurrent_bootstrap_uses_one_cas_maintenance_writer(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            clients = [
                SkillHubClient(root / "state", cas_root=root / "cas")
                for _index in range(2)
            ]
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(
                        lambda client: client.bootstrap_bundled(
                            self.seed, at="2026-09-07T01:00:00Z"
                        ),
                        clients,
                    )
                )

            self.assertEqual([False, True], sorted(item["changed"] for item in results))
            self.assertEqual(
                [0, 44], sorted(item["artifacts_written"] for item in results)
            )
            self.assertEqual(1, len({item["managed_lock_digest"] for item in results}))

    def test_status_distinguishes_not_checked_from_checked_empty(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            client = SkillHubClient(root / "state", cas_root=root / "cas")
            unchecked = client.status()
            empty = build_skill_maintenance_receipt(
                status="empty",
                bootstrap_checked=True,
                active_source={
                    "source_id": "hub-source://org/empty@1",
                    "transport": "static_https",
                    "source_descriptor_digest": "1" * 64,
                    "source_revision": "empty-v1",
                },
                active_index_digest="2" * 64,
                active_seed_digest="3" * 64,
                managed_lock_digest=None,
                skill_count=0,
                last_attempt_at="2026-09-07T01:00:00Z",
                last_success_at="2026-09-07T01:00:00Z",
                network_called=False,
                reason_codes=[],
                update_available=False,
                host_restart_required=False,
            )
            write_skill_maintenance_receipt(client.state_root, empty)
            checked = client.status()

            self.assertEqual("not_bootstrapped", unchecked["status"])
            self.assertFalse(unchecked["bootstrap_checked"])
            self.assertEqual("empty", checked["status"])
            self.assertTrue(checked["bootstrap_checked"])
            self.assertNotEqual(unchecked["status"], checked["status"])
            self.assertEqual(0, checked["skill_count"])


if __name__ == "__main__":
    unittest.main()
