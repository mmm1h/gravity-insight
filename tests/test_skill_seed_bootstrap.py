from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from gravity_insight.agent_runtime_contracts import canonical_digest
from gravity_insight import __main__ as entry
from gravity_insight.skill_hub_client import SkillHubClient
from gravity_insight.skill_maintenance_startup import (
    AUTO_SKILLS_ENV,
    maybe_bootstrap_bundled_skills,
    startup_skill_bootstrap_enabled,
)
from gravity_insight.skill_hub_contract import SkillHubContractError
from gravity_insight.skill_hub_locks import build_skills_lock
from gravity_insight.skill_seed import (
    open_bundled_hub_source,
    validate_bundled_skill_seed,
)
from gravity_insight.skill_maintenance_state import (
    build_skill_maintenance_receipt,
    skill_maintenance_generation_path,
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
            self.assertEqual(0, client.list()["count"])

            with patch.object(
                socket,
                "socket",
                side_effect=AssertionError("network attempted"),
            ):
                first = client.bootstrap_bundled(
                    self.seed,
                    at="2026-09-07T01:00:00Z",
                    project_root=project_lock.parent,
                )

            self.assertEqual("ready", first["status"])
            self.assertTrue(first["changed"])
            self.assertEqual(44, first["skill_count"])
            self.assertEqual(44, first["artifacts_verified"])
            self.assertEqual(44, first["artifacts_written"])
            self.assertFalse(first["network_called"])
            self.assertEqual(44, client.list()["count"])
            self.assertFalse(project_lock.exists())

            generation_path = skill_maintenance_generation_path(
                client.state_root, self.seed_digest
            )
            generation_before = generation_path.read_bytes()
            cas_files = {
                path: (path.read_bytes(), path.stat().st_mtime_ns)
                for path in (root / "cas" / "skills" / "sha256").rglob("*")
                if path.is_file()
            }
            second = client.bootstrap_bundled(
                self.seed,
                at="2026-09-07T01:01:00Z",
                project_root=project_lock.parent,
            )

            self.assertEqual("ready", second["status"])
            self.assertFalse(second["changed"])
            self.assertEqual(0, second["artifacts_verified"])
            self.assertEqual(0, second["artifacts_written"])
            self.assertEqual("seed_digest_match", second["shortcut"])
            self.assertEqual(first["managed_lock_digest"], second["managed_lock_digest"])
            self.assertFalse(project_lock.exists())
            self.assertEqual(generation_before, generation_path.read_bytes())
            self.assertEqual(
                cas_files,
                {
                    path: (path.read_bytes(), path.stat().st_mtime_ns)
                    for path in (root / "cas" / "skills" / "sha256").rglob("*")
                    if path.is_file()
                },
            )

    def test_tampered_seed_fails_closed_and_retains_last_known_good(self) -> None:
        with zipfile.ZipFile(io.BytesIO(self.seed)) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        archive_name = next(
            name for name in sorted(files) if name.startswith("runtime-skill-")
        )
        changed = bytearray(files[archive_name])
        changed[len(changed) // 2] ^= 1
        files[archive_name] = bytes(changed)
        tampered = builder._zip(files)
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            client = SkillHubClient(root / "state", cas_root=root / "cas")
            with self.assertRaisesRegex(
                SkillHubContractError, "HUB_SEED_DIGEST_MISMATCH"
            ):
                client.bootstrap_bundled(
                    tampered, at="2026-09-07T01:00:00Z"
                )
            unavailable = client.status()
            self.assertEqual("unavailable", unavailable["status"])
            self.assertTrue(unavailable["bootstrap_checked"])
            self.assertEqual(0, unavailable["skill_count"])

            client.bootstrap_bundled(self.seed, at="2026-09-07T01:01:00Z")
            with self.assertRaisesRegex(
                SkillHubContractError, "HUB_SEED_DIGEST_MISMATCH"
            ):
                client.bootstrap_bundled(
                    tampered, at="2026-09-07T01:02:00Z"
                )
            degraded = client.status()
            self.assertEqual("degraded", degraded["status"])
            self.assertEqual(44, degraded["skill_count"])
            self.assertEqual(44, client.list()["count"])
            self.assertEqual(
                ["HUB_SEED_DIGEST_MISMATCH"], degraded["reason_codes"]
            )

            from gravity_insight.cli import main as insight_main

            stdout, stderr = io.StringIO(), io.StringIO()
            with (
                patch(
                    "gravity_insight.skill_maintenance.read_bundled_skill_seed",
                    return_value=tampered,
                ),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                exit_code = insight_main(
                    ["skills", "bootstrap", "--state-root", str(root / "cli-state")]
                )
            self.assertEqual(2, exit_code)
            self.assertIn("HUB_SEED_DIGEST_MISMATCH", stderr.getvalue())

    def test_same_seed_shortcut_does_not_reopen_or_reverify_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            client = SkillHubClient(root / "state", cas_root=root / "cas")
            client.bootstrap_bundled(self.seed, at="2026-09-07T01:00:00Z")

            with (
                patch(
                    "gravity_insight.skill_maintenance.open_bundled_hub_source",
                    side_effect=AssertionError("seed reopened"),
                ),
                patch.object(
                    client.cas,
                    "fetch_skill",
                    side_effect=AssertionError("archive unpack repeated"),
                ),
                patch.object(
                    client,
                    "verify",
                    side_effect=AssertionError("CAS reverified"),
                ),
            ):
                second = client.bootstrap_bundled(
                    self.seed, at="2026-09-07T01:01:00Z"
                )

            self.assertFalse(second["changed"])
            self.assertEqual("seed_digest_match", second["shortcut"])
            self.assertEqual(0, second["artifacts_verified"])

    def test_generation_is_not_active_until_the_receipt_pointer_commits(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            client = SkillHubClient(root / "state", cas_root=root / "cas")
            original = write_skill_maintenance_receipt

            def fail_ready(state_root, receipt):
                if receipt["status"] == "ready":
                    raise OSError("injected receipt failure")
                return original(state_root, receipt)

            with (
                patch(
                    "gravity_insight.skill_maintenance.write_skill_maintenance_receipt",
                    side_effect=fail_ready,
                ),
                self.assertRaisesRegex(
                    SkillHubContractError, "HUB_BOOTSTRAP_IO_FAILED"
                ),
            ):
                client.bootstrap_bundled(
                    self.seed, at="2026-09-07T01:00:00Z"
                )

            self.assertEqual("unavailable", client.status()["status"])
            self.assertEqual(0, client.list()["count"])

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
            self.assertEqual(
                ["SKILL_BOOTSTRAP_NOT_ATTEMPTED"], unchecked["reason_codes"]
            )
            self.assertEqual([], checked["reason_codes"])
            self.assertEqual(0, checked["skill_count"])

    def test_valid_old_project_lock_is_reported_but_never_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            project = root / "project"
            project.mkdir()
            session = open_bundled_hub_source(self.seed)
            identity = sorted(session.index["skills"])[0]
            old = build_skills_lock(
                session.index,
                session.reference(),
                [identity],
            )
            old["source"]["source_revision"] = "older-release"
            old["lock_digest"] = canonical_digest(
                {key: value for key, value in old.items() if key != "lock_digest"}
            )
            project_lock = project / "gravity.skills.lock.json"
            project_lock.write_text(
                json.dumps(old, sort_keys=True) + "\n", encoding="utf-8"
            )
            before = project_lock.read_bytes()
            client = SkillHubClient(root / "state", cas_root=root / "cas")

            result = client.bootstrap_bundled(
                self.seed,
                at="2026-09-07T01:00:00Z",
                project_root=project,
            )

            self.assertTrue(client.status()["update_available"])
            self.assertTrue(result["changed"])
            self.assertEqual(before, project_lock.read_bytes())

    def test_startup_policy_skips_diagnostic_and_explicit_maintenance_paths(self) -> None:
        skipped = (
            [],
            ["--help"],
            ["agent", "--help"],
            ["--dry-run"],
            ["doctor"],
            ["insight", "doctor"],
            ["skills", "status"],
            ["insight", "skills", "status"],
            ["skills", "bootstrap"],
            ["skills", "repair"],
            ["skills", "host-install-plan"],
            ["skills", "sync"],
        )
        for argv in skipped:
            with self.subTest(argv=argv):
                self.assertFalse(
                    startup_skill_bootstrap_enabled(
                        argv, environ={AUTO_SKILLS_ENV: "1"}
                    )
                )
                self.assertEqual(
                    "disabled",
                    maybe_bootstrap_bundled_skills(
                        argv, environ={AUTO_SKILLS_ENV: "1"}
                    ).status,
                )
        for value in ("0", "false", "no", "off", " FALSE "):
            self.assertFalse(
                startup_skill_bootstrap_enabled(
                    ["agent"], environ={AUTO_SKILLS_ENV: value}
                )
            )
        self.assertTrue(
            startup_skill_bootstrap_enabled(["agent"], environ={})
        )

    def test_host_plan_stages_verified_sources_and_preserves_local_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            client = SkillHubClient(root / "state", cas_root=root / "cas")
            client.bootstrap_bundled(self.seed, at="2026-09-07T01:00:00Z")
            host_root = root / "codex-skills"

            initial = client.host_install_plan("codex", host_root, self.seed)
            self.assertEqual("ready", initial["status"])
            self.assertEqual("next_host_start", initial["activation"])
            self.assertEqual(44, len(initial["actions"]))
            self.assertEqual([], initial["conflicts"])
            self.assertTrue(initial["host_restart_required"])
            self.assertFalse(host_root.exists())
            first = initial["actions"][0]
            target = Path(first["target_directory"])
            shutil.copytree(first["source_directory"], target)

            unchanged = client.host_install_plan("codex", host_root, self.seed)
            self.assertEqual("ready", unchanged["status"])
            self.assertEqual(43, len(unchanged["actions"]))
            self.assertEqual(1, len(unchanged["unchanged"]))
            skill_md = target / "SKILL.md"
            skill_md.write_text("local override\n", encoding="utf-8")
            before = skill_md.read_bytes()

            conflicted = client.host_install_plan("codex", host_root, self.seed)
            self.assertEqual("local_override_conflict", conflicted["status"])
            self.assertEqual(1, len(conflicted["conflicts"]))
            self.assertEqual(
                "local_override_conflict",
                conflicted["conflicts"][0]["reason_code"],
            )
            self.assertEqual(before, skill_md.read_bytes())
            self.assertFalse(conflicted["network_called"])

    def test_normal_root_dispatch_bootstraps_before_the_business_command(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            stdout, stderr = io.StringIO(), io.StringIO()
            environment = {
                "GRAVITY_CACHE_HOME": str(root / "cache"),
                "GRAVITY_INSIGHT_AUTO_UPGRADE": "0",
                AUTO_SKILLS_ENV: "1",
            }
            with (
                patch.dict(os.environ, environment, clear=False),
                patch(
                    "gravity_insight.skill_maintenance.read_bundled_skill_seed",
                    return_value=self.seed,
                ),
                patch.object(
                    socket, "socket", side_effect=AssertionError("network attempted")
                ),
                patch.object(
                    entry, "ensure_first_run_credentials", return_value=True
                ),
                redirect_stdout(stdout),
                redirect_stderr(stderr),
            ):
                code = entry.main(["agent-catalog", "categories"])

            self.assertEqual(0, code, stderr.getvalue())
            state_root = root / "cache" / "default"
            status = SkillHubClient(state_root).status()
            self.assertEqual("ready", status["status"])
            self.assertEqual(44, status["skill_count"])
            self.assertFalse(status["network_called"])

    def test_plain_import_has_no_state_or_network_side_effect(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            script = (
                "import pathlib,socket,sys; "
                "socket.socket=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network')); "
                "sys.dont_write_bytecode=True; sys.path.insert(0,sys.argv[1]); "
                "import gravity_insight; print(gravity_insight.__version__)"
            )
            completed = subprocess.run(
                [sys.executable, "-I", "-X", "utf8", "-c", script, str(Path.cwd() / "src")],
                cwd=root,
                env={
                    **os.environ,
                    "GRAVITY_CACHE_HOME": str(root / "cache"),
                    AUTO_SKILLS_ENV: "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=30,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertFalse((root / "cache").exists())

    def test_startup_maintenance_failure_does_not_change_business_exit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {
                        "GRAVITY_CACHE_HOME": str(root / "cache"),
                        "GRAVITY_INSIGHT_AUTO_UPGRADE": "0",
                        AUTO_SKILLS_ENV: "1",
                    },
                    clear=False,
                ),
                patch(
                    "gravity_insight.skill_maintenance.read_bundled_skill_seed",
                    return_value=b"invalid-seed",
                ),
                patch.object(entry, "command_requires_credentials", return_value=False),
                patch.object(entry, "ensure_first_run_credentials", return_value=True),
                patch("gravity_insight.cli.main", return_value=7),
                redirect_stderr(output),
            ):
                code = entry.main(["agent", "fixture query"])

            self.assertEqual(7, code)
            self.assertIn("HUB_SEED_INVALID", output.getvalue())
            self.assertIn("continuing this command", output.getvalue())


if __name__ == "__main__":
    unittest.main()
