from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from gravity_sdk.skill_hub_client import SkillHubClient
from gravity_sdk.skill_hub_contract import SkillHubContractError
from gravity_sdk.skill_hub_state import (
    build_trusted_installation_state,
    compile_skill_installation_state,
    read_json,
)
from gravity_sdk.trusted_pack_hub import (
    TrustedPackHubClient,
    verify_trusted_pack_startup,
)
from tests.test_skill_hub_io import GitHubFixture, bound_entry, skill_archive, trusted_wheel
from tests.test_skill_hub_contracts import hub_index, skill_entry, trusted_entry


class RaisingEntryPoint:
    def __init__(self, group: str) -> None:
        self.group = group
        self.name = "example"

    def load(self):
        raise AssertionError("entry point code loaded")


class SkillHubClientTests(unittest.TestCase):
    def setUp(self) -> None:
        raw_skill = skill_entry()
        self.skill_zip = skill_archive(raw_skill)
        self.skill = bound_entry(raw_skill, self.skill_zip)
        self.wheel = trusted_wheel()
        self.trusted = trusted_entry(self.wheel)
        self.index = hub_index(skills=[self.skill], packs=[self.trusted])
        self.fixture = GitHubFixture()
        self.fixture.publish(
            self.index,
            {
                self.skill["archive"]["path"]: self.skill_zip,
                self.trusted["archive"]["path"]: self.wheel,
            },
        )
        self.mirror = self.fixture.clone("client")
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.cas = self.root / "cas"
        self.client = SkillHubClient(
            self.state, cas_root=self.cas, runtime_version="0.3.0"
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()
        self.fixture.close()

    def test_skill_control_plane_closes_sync_lock_fetch_install_and_audit(self) -> None:
        lock_path = self.root / "project" / "gravity.skills.lock.json"
        lock_path.parent.mkdir()
        lock_path.write_text('{"sentinel":true}\n', encoding="utf-8")

        synced = self.client.sync(git_source(), repository=self.mirror)
        self.assertEqual('{"sentinel":true}\n', lock_path.read_text(encoding="utf-8"))
        self.assertFalse(synced["network_called"])

        searched = self.client.search("team-analysis")
        self.assertEqual([self.skill["skill_uri"]], [item["skill_uri"] for item in searched["results"]])
        shown = self.client.show(self.skill["skill_uri"])
        self.assertEqual(self.skill["package"]["package_digest"], shown["package"]["package_digest"])

        resolved = self.client.resolve([self.skill["skill_uri"]])
        written = self.client.lock([self.skill["skill_uri"]], lock_path)
        lock = resolved["lock"]
        self.assertEqual(lock, read_json(lock_path))
        self.assertEqual(lock["lock_digest"], written["lock_digest"])
        self.assertEqual("unchanged", self.client.update([self.skill["skill_uri"]], lock_path)["status"])

        before = self.client.verify(lock)
        self.assertFalse(before["ok"])
        self.assertIn("HUB_CAS_MISSING", before["reason_codes"])
        fetched = self.client.fetch(lock, git_source(), repository=self.mirror)
        self.assertEqual("verified", fetched["status"])
        self.assertTrue(self.client.verify(lock)["ok"])

        installed = self.client.install(
            lock,
            install_root=self.root / "installed",
            at="2026-08-22T12:00:00Z",
        )
        state = compile_skill_installation_state(read_json(Path(installed["state_path"])))
        self.assertEqual(lock["lock_digest"], state["lock_digest"])
        self.assertEqual("healthy", state["installations"][0]["health"])
        self.assertIn("local_path", state["installations"][0])
        self.assertNotIn("local_path", repr(lock))
        audit = self.client.audit()
        self.assertEqual(1, len(audit["sources"]))
        self.assertEqual(1, audit["sources"][0]["skill_count"])

    def test_fetch_rejects_changed_source_descriptor_and_lock_readback_tamper(self) -> None:
        self.client.sync(git_source(), repository=self.mirror)
        lock = self.client.resolve([self.skill["skill_uri"]])["lock"]
        changed = git_source()
        changed["owner"] = "different-owner"
        with self.assertRaises(SkillHubContractError):
            self.client.fetch(lock, changed, repository=self.mirror)

        path = self.root / "gravity.skills.lock.json"
        self.client.lock([self.skill["skill_uri"]], path)
        value = json.loads(path.read_text(encoding="utf-8"))
        value["skills"][0]["package_digest"] = "0" * 64
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(SkillHubContractError, "SKILLS_LOCK_DIGEST_MISMATCH"):
            self.client.update([self.skill["skill_uri"]], path)

    def test_offline_verify_classifies_a_semantically_invalid_cas_manifest(self) -> None:
        self.client.sync(git_source(), repository=self.mirror)
        lock = self.client.resolve([self.skill["skill_uri"]])["lock"]
        self.client.fetch(lock, git_source(), repository=self.mirror)
        manifest_path = (
            self.cas
            / "skills"
            / "sha256"
            / lock["skills"][0]["package_digest"]
            / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["runtime_requires"] = "latest"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        verified = self.client.verify(lock)

        self.assertFalse(verified["ok"])
        self.assertEqual(["HUB_CAS_TAMPERED"], verified["reason_codes"])

    def test_multiple_sources_require_explicit_source_identity(self) -> None:
        self.client.sync(git_source(), repository=self.mirror)
        other = git_source()
        other["source_id"] = "hub-source://org/other@1"
        other["owner"] = "other-team"
        self.client.sync(other, repository=self.mirror)

        with self.assertRaisesRegex(SkillHubContractError, "HUB_SOURCE_REQUIRED"):
            self.client.resolve([self.skill["skill_uri"]])
        selected = self.client.resolve(
            [self.skill["skill_uri"]], source_id="hub-source://org/example@1"
        )
        self.assertEqual("resolved", selected["status"])

    def test_state_root_rejects_a_linked_parent_before_resolution(self) -> None:
        real = self.root / "real-state-parent"
        real.mkdir()
        linked = self.root / "linked-state-parent"
        try:
            linked.symlink_to(real, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlinks unavailable: {exc}")
        with self.assertRaisesRegex(SkillHubContractError, "HUB_STATE_INVALID"):
            SkillHubClient(linked / "nested")
        self.assertFalse((real / "nested").exists())

    def test_trusted_pack_flow_never_installs_or_scans_environment(self) -> None:
        self.client.sync(git_source(), repository=self.mirror)
        trusted = TrustedPackHubClient(
            self.state, cas_root=self.cas, runtime_version="0.3.0"
        )
        identity = self.trusted["pack_id"]
        lock = trusted.resolve([identity])["lock"]
        self.assertFalse(trusted.verify(lock)["ok"])
        fetched = trusted.fetch(lock, git_source(), repository=self.mirror)
        self.assertEqual("verified", fetched["status"])
        self.assertTrue(trusted.verify(lock)["ok"])

        plan = trusted.install_plan(lock)
        self.assertEqual("external_installer", plan["installation_owner"])
        self.assertNotIn("command", repr(plan))
        self.assertNotIn("pip", repr(plan))

        item = lock["packs"][0]
        state = build_trusted_installation_state(
            lock["lock_digest"],
            [
                {
                    "pack_id": item["pack_id"],
                    "descriptor_digest": item["descriptor_digest"],
                    "distribution": item["distribution"],
                    "version": item["version"],
                    "wheel_sha256": item["wheel_sha256"],
                    "installed_at": "2026-08-22T12:00:00Z",
                    "local_path": "C:/external-installer/site-packages/example.dist-info",
                    "health": "healthy",
                }
            ],
        )
        distribution = SimpleNamespace(
            version=item["version"],
            metadata={
                "Name": item["distribution"],
                "Gravity-Trusted-Pack-ID": item["pack_id"],
            },
            entry_points=[
                RaisingEntryPoint("gravity.models"),
                RaisingEntryPoint("gravity.operators"),
            ],
        )
        with patch(
            "importlib.metadata.entry_points",
            side_effect=AssertionError("global environment scan attempted"),
        ):
            verified = verify_trusted_pack_startup(
                lock,
                state,
                distribution_lookup=lambda name: distribution,
            )
        self.assertTrue(verified["ok"])
        self.assertEqual([identity], [item["pack_id"] for item in verified["packs"]])

        wrong = copy.deepcopy(state)
        wrong["installations"][0]["health"] = "tampered"
        from gravity_sdk.agent_runtime_contracts import canonical_digest

        wrong["state_digest"] = canonical_digest(
            {key: value for key, value in wrong.items() if key != "state_digest"}
        )
        blocked = verify_trusted_pack_startup(
            lock, wrong, distribution_lookup=lambda name: distribution
        )
        self.assertFalse(blocked["ok"])
        self.assertEqual(["TRUSTED_PACK_STATE_MISMATCH"], blocked["reason_codes"])

    def test_two_projects_share_an_exact_trusted_lock_and_plan_only(self) -> None:
        self.client.sync(git_source(), repository=self.mirror)
        first = TrustedPackHubClient(
            self.state, cas_root=self.cas, runtime_version="0.3.0"
        )
        identity = self.trusted["pack_id"]
        first_lock = first.resolve([identity])["lock"]
        first.fetch(first_lock, git_source(), repository=self.mirror)

        second_state = self.root / "second-project-state"
        second_sync = SkillHubClient(
            second_state, cas_root=self.cas, runtime_version="0.3.0"
        )
        second_sync.sync(git_source(), repository=self.mirror)
        second = TrustedPackHubClient(
            second_state, cas_root=self.cas, runtime_version="0.3.0"
        )
        second_lock = second.resolve([identity])["lock"]
        fetched = second.fetch(second_lock, git_source(), repository=self.mirror)

        self.assertEqual(first_lock, second_lock)
        self.assertTrue(fetched["artifacts"][0]["cached"])
        self.assertEqual(first.install_plan(first_lock), second.install_plan(second_lock))
        skill_verification = self.client.verify(first_lock)
        self.assertFalse(skill_verification["ok"])
        self.assertEqual(["SKILLS_LOCK_INVALID"], skill_verification["reason_codes"])


def git_source() -> dict:
    from tests.test_skill_hub_contracts import git_source as fixture

    return fixture()


if __name__ == "__main__":
    unittest.main()
