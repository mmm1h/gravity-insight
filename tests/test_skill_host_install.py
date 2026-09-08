from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gravity_insight.agent_runtime_contracts import canonical_digest, validate_schema
from gravity_insight.cli import main
from gravity_insight.skill_hub_client import SkillHubClient
from gravity_insight.skill_hub_contract import SkillHubContractError
from gravity_insight.skill_hub_locks import build_skills_lock
from gravity_insight.skill_seed import open_bundled_hub_source, validate_bundled_skill_seed
from scripts.generate_skill_library import render_seed


class LockDrivenHostInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.seed = render_seed()
        cls.session = open_bundled_hub_source(cls.seed)
        cls.identities = sorted(cls.session.index["skills"])

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.host = self.root / "host"
        self.client = SkillHubClient(self.root / "state", cas_root=self.root / "cas")
        self.network = patch("socket.socket", side_effect=AssertionError("network attempted"))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.client.bootstrap_bundled(self.seed, at="2026-09-08T00:00:00Z")

    def lock(self, identities: list[str] | None = None) -> dict:
        return build_skills_lock(
            self.session.index, self.session.reference(),
            identities if identities is not None else self.identities[:1],
        )

    def plan(self, lock: dict | None = None, host: str = "codex") -> dict:
        return self.client.host_install_plan(host, self.host, self.seed, selection=lock)

    def assert_no_stage(self, lock: dict, reason: str, message: str) -> None:
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        with patch.object(self.client.cas, "stage_agent_skill") as stage:
            with self.assertRaises(SkillHubContractError) as caught:
                self.plan(lock)
        self.assertEqual(reason, caught.exception.reason_code)
        self.assertIn(message, str(caught.exception))
        stage.assert_not_called()
        self.assertEqual(before, sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*")))

    def invoke(self, *arguments: str) -> tuple[int, dict]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            redirect_stdout(stdout), redirect_stderr(stderr),
            patch("gravity_insight.runtime.build_client", side_effect=AssertionError("Gravity client constructed")),
            patch("gravity_insight.skill_host_install.read_bundled_skill_seed", return_value=self.seed),
        ):
            code = main([
                "skills", "host-install-plan", "--host", "codex", "--host-root", str(self.host),
                "--state-root", str(self.client.state_root), "--cas-root", str(self.client.cas.root),
                *arguments,
            ])
        return code, json.loads(stdout.getvalue() or stderr.getvalue())

    def test_no_lock_cli_preserves_full_44_skill_bundle(self) -> None:
        code, plan = self.invoke()
        self.assertEqual(0, code)
        self.assertEqual(44, len(plan["actions"]))
        files = [path for path in (self.root / "cas" / "agent-skills").rglob("*") if path.is_file()]
        self.assertEqual(264, len(files))
        self.assertFalse(self.host.exists())

    def test_exact_lock_cli_stages_only_selected_six_files(self) -> None:
        lock = self.lock()
        path = self.root / "project.lock.json"
        path.write_text(json.dumps(lock), encoding="utf-8")
        before = path.read_bytes()
        code, plan = self.invoke("--lock", str(path))
        self.assertEqual(0, code)
        self.assertEqual(lock["requested"], [item["skill_uri"] for item in plan["actions"]])
        files = [path for path in (self.root / "cas" / "agent-skills").rglob("*") if path.is_file()]
        self.assertEqual(6, len(files))
        self.assertEqual(before, path.read_bytes())
        self.assertFalse(self.host.exists())
        validate_schema(plan, "agent-skill-host-install-plan-v1.schema.json", "Host plan")

    def test_existing_uri_digest_mismatches_are_rejected_before_stage(self) -> None:
        for field in ("manifest_digest", "package_digest", "archive_sha256"):
            with self.subTest(field=field):
                lock = self.lock()
                lock["skills"][0][field] = "0" * 64
                self.assert_no_stage(_redigest(lock), "HOST_SKILL_LOCK_MISMATCH", field)

    def test_missing_seed_uri_is_unavailable_with_offline_remedy(self) -> None:
        lock = self.lock()
        identity = "skill://example/not-in-seed@1.0.0"
        lock["requested"] = [identity]
        lock["skills"][0]["skill_uri"] = identity
        self.assert_no_stage(_redigest(lock), "HOST_SKILL_UNAVAILABLE", "gravity skills")
        with self.assertRaises(SkillHubContractError) as caught:
            self.plan(lock)
        for text in ("unavailable", "old lock", "CAS", "bootstrap", "list", "lock", "--source-id", "--output", str(self.client.state_root)):
            self.assertIn(text, str(caught.exception))

    def test_runtime_version_mismatch_reuses_hub_incompatible(self) -> None:
        lock = self.lock()
        lock["runtime_version"] = "0.3.6"
        self.assert_no_stage(_redigest(lock), "HUB_RUNTIME_INCOMPATIBLE", "runtime_version")

    def test_late_selection_failure_leaves_no_partial_stage(self) -> None:
        lock = self.lock(self.identities[:2])
        lock["skills"][1]["package_digest"] = "0" * 64
        self.assert_no_stage(_redigest(lock), "HOST_SKILL_LOCK_MISMATCH", "digest")

    def test_agent_projection_digests_match_selected_runtime_package(self) -> None:
        lock = self.lock(self.identities[:2])
        for field in ("manifest_digest", "package_digest"):
            with self.subTest(field=field):
                validated = validate_bundled_skill_seed(self.seed)
                validated["agent_index"]["skills"][1][field] = "0" * 64
                with patch(
                    "gravity_insight.skill_host_install.validate_bundled_skill_seed",
                    return_value=validated,
                ):
                    self.assert_no_stage(lock, "HOST_SKILL_LOCK_MISMATCH", "Agent projection")

    def test_selection_preserves_full_maintenance_and_no_network(self) -> None:
        before = self.client.status()
        plan = self.plan(self.lock())
        after = self.client.status()
        self.assertEqual(before, after)
        self.assertEqual(44, after["skill_count"])
        self.assertFalse(after["network_called"])
        self.assertFalse(plan["network_called"])

    def test_plan_digest_changes_with_selection_and_remains_canonical(self) -> None:
        lock = self.lock()
        original = copy.deepcopy(lock)
        single = self.plan(lock)
        multiple = self.plan(self.lock(self.identities[:2]))
        self.assertNotEqual(single["plan_digest"], multiple["plan_digest"])
        for plan in (single, multiple):
            self.assertEqual(plan["plan_digest"], canonical_digest({key: value for key, value in plan.items() if key != "plan_digest"}))
        self.assertEqual(single, self.plan(lock))
        self.assertEqual(original, lock)

    def test_source_and_index_references_must_match_exactly(self) -> None:
        for field in ("source_id", "transport", "source_descriptor_digest", "source_revision", "index_digest"):
            with self.subTest(field=field):
                lock = self.lock()
                lock["source"][field] = "0" * 64 if "digest" in field else ("git" if field == "transport" else "old-source")
                self.assert_no_stage(_redigest(lock), "HUB_SOURCE_SNAPSHOT_CHANGED", "source/index")

    def test_lock_metadata_and_self_digest_are_not_ignored(self) -> None:
        for field, value in (("artifact_size", 1), ("artifact_path", "other.zip"), ("runtime_requires", ">=0.3.0")):
            with self.subTest(field=field):
                lock = self.lock()
                lock["skills"][0][field] = value
                self.assert_no_stage(_redigest(lock), "HOST_SKILL_LOCK_MISMATCH", field)
        lock = self.lock()
        lock["lock_digest"] = "0" * 64
        self.assert_no_stage(lock, "SKILLS_LOCK_DIGEST_MISMATCH", "digest")

    def test_explicit_invalid_lock_never_falls_back_to_bundle(self) -> None:
        for lock in ({}, {**self.lock(), "selection": []}):
            self.assert_no_stage(lock, "SKILLS_LOCK_INVALID", "")
        missing = self.root / "missing.json"
        code, result = self.invoke("--lock", str(missing))
        self.assertNotEqual(0, code)
        self.assertFalse((self.client.cas.root / "agent-skills").exists())
        self.assertNotIn("actions", result)

    def test_selected_install_readback_conflict_and_shared_host_preservation(self) -> None:
        for host in ("codex", "claude"):
            with self.subTest(host=host):
                self.host = self.root / host
                unrelated = self.host / "another-project" / "SKILL.md"
                unrelated.parent.mkdir(parents=True)
                unrelated.write_bytes(b"other project\n")
                lock = self.lock()
                plan = self.plan(lock, host)
                self.assertEqual("next_host_start", plan["activation"])
                action = plan["actions"][0]
                self.assertIsNone(action["target_preimage_digest"])
                target = Path(action["target_directory"])
                shutil.copytree(action["source_directory"], target)
                unchanged = self.plan(lock, host)
                self.assertEqual([], unchanged["actions"])
                self.assertEqual(1, len(unchanged["unchanged"]))
                self.assertFalse(unchanged["host_restart_required"])
                rows = [{"path": path.relative_to(target).as_posix(), "size_bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in sorted(target.rglob("*")) if path.is_file()]
                self.assertEqual(canonical_digest(rows), unchanged["unchanged"][0]["target_preimage_digest"])
                (target / "SKILL.md").write_bytes(b"local edit\n")
                conflict = self.plan(lock, host)
                self.assertEqual("local_override_conflict", conflict["status"])
                self.assertEqual(1, len(conflict["conflicts"]))
                self.assertEqual(b"local edit\n", (target / "SKILL.md").read_bytes())
                self.assertEqual(b"other project\n", unrelated.read_bytes())


def _redigest(lock: dict) -> dict:
    lock["lock_digest"] = canonical_digest({key: value for key, value in lock.items() if key != "lock_digest"})
    return lock
