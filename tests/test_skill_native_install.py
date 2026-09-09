from __future__ import annotations

from contextlib import chdir, redirect_stderr, redirect_stdout
import copy
import io
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gravity_insight.control_plane import native_skill_install as native
from gravity_insight.agent_runtime_contracts import canonical_digest
from gravity_insight.cli import main
from gravity_insight.doctor_cli import diagnose_skills
from gravity_insight.skill_hub_client import SkillHubClient
from gravity_insight.skill_hub_contract import SkillHubContractError
from gravity_insight.skill_hub_locks import build_skills_lock
from gravity_insight.skill_seed import open_bundled_hub_source
from scripts.generate_skill_library import render_seed


class NativeInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = render_seed()
        cls.session = open_bundled_hub_source(cls.seed)

    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.project = self.root / "project"
        self.project.mkdir()
        self.host = self.project / ".agents/skills"
        self.client = SkillHubClient(self.root / "state")
        self.client.bootstrap_bundled(self.seed)
        self.enterContext(patch.object(native, "read_bundled_skill_seed", return_value=self.seed))
        self.enterContext(patch("socket.socket", side_effect=AssertionError("network attempted")))

    def plan(self, count=1, host="codex"):
        lock = build_skills_lock(self.session.index, self.session.reference(), sorted(self.session.index["skills"])[:count])
        self.host = self.project / (".agents" if host == "codex" else ".claude") / "skills"
        return self.client.host_install_plan(host, self.host, self.seed, selection=lock)

    def run_plan(self, plan, operation="install"):
        preview = native.preview_native_install(plan, self.project, operation=operation)
        return native.execute_native_install(plan, self.project, approve=preview["preview_digest"], operation=operation)

    def snapshot(self):
        return {str(p.relative_to(self.project)): p.read_bytes() if p.is_file() else None for p in self.project.rglob("*")}

    def test_install_readback_diagnosis_idempotence_and_undo_both_hosts(self):
        for host in ("codex", "claude"):
            with self.subTest(host=host):
                plan = self.plan(host=host)
                unrelated = self.host / "lark-other/SKILL.md"
                unrelated.parent.mkdir(parents=True)
                unrelated.write_bytes(b"preserve")
                before = self.snapshot()
                self.assertEqual("absent", native.readback_native_install(plan, self.project)["targets"][0]["status"])
                native.preview_native_install(plan, self.project)
                self.assertEqual(before, self.snapshot())
                result = self.run_plan(plan)
                self.assertEqual("installed", result["status"])
                self.assertEqual(6, len(result["readback"]["targets"][0]["files"]))
                self.assertEqual("not_measured", result["readback"]["host_discovery"])
                installed = self.snapshot()
                self.assertEqual("unchanged", self.run_plan(plan)["status"])
                self.assertEqual(installed, self.snapshot())
                fresh_plan = self.plan(host=host)
                self.assertEqual(1, len(fresh_plan["unchanged"]))
                with patch("gravity_insight.doctor_cli.read_bundled_skill_seed", return_value=self.seed):
                    report = diagnose_skills(state_root=self.client.state_root, project_root=self.project, home=self.root / "home", environ={})
                scopes = [row for row in report["native_files"]["hosts"] if row["host"] == host and row["scope"] == "project"]
                skill = next(row for row in scopes[0]["skills"] if row["skill_uri"] == plan["actions"][0]["skill_uri"])
                self.assertEqual("installed_consistent", skill["status"])
                self.assertEqual("uninstalled", self.run_plan(plan, "uninstall")["status"])
                self.assertEqual(before, self.snapshot())

    def test_unknown_equal_directory_is_not_adopted_or_removed(self):
        plan = self.plan()
        row = plan["actions"][0]
        shutil.copytree(row["source_directory"], row["target_directory"])
        before = self.snapshot()
        for operation in ("install", "uninstall"):
            preview = native.preview_native_install(plan, self.project, operation=operation)
            self.assertEqual("unknown_ownership", preview["targets"][0]["conflict"])
            with self.assertRaises(SkillHubContractError):
                self.run_plan(plan, operation)
        self.assertEqual(before, self.snapshot())

    def test_local_edits_and_empty_directories_block_entire_batch(self):
        plan = self.plan(2)
        self.run_plan(plan)
        target = Path(plan["actions"][0]["target_directory"])
        (target / "local-empty").mkdir()
        (target / "SKILL.md").write_bytes(b"local edits")
        before = self.snapshot()
        for operation in ("install", "uninstall"):
            with self.assertRaises(SkillHubContractError):
                self.run_plan(plan, operation)
        self.assertEqual(before, self.snapshot())

    def test_source_and_target_approval_drift_fail_before_writes(self):
        plan = self.plan()
        preview = native.preview_native_install(plan, self.project)
        source = Path(plan["actions"][0]["source_directory"]) / "SKILL.md"
        original = source.read_bytes()
        source.write_bytes(b"changed")
        with self.assertRaises(SkillHubContractError) as error:
            native.execute_native_install(plan, self.project, approve=preview["preview_digest"])
        self.assertEqual("HOST_SKILL_SOURCE_CHANGED", error.exception.reason_code)
        source.write_bytes(original)
        Path(plan["actions"][0]["target_directory"]).mkdir(parents=True)
        before = self.snapshot()
        with self.assertRaises(SkillHubContractError) as error:
            native.execute_native_install(plan, self.project, approve=preview["preview_digest"])
        self.assertEqual("HOST_SKILL_APPROVAL_STALE", error.exception.reason_code)
        self.assertEqual(before, self.snapshot())

    def test_seed_reuse_does_not_cache_mutable_previews_or_ignore_changed_bytes(self):
        plan = self.plan()
        first = native.preview_native_install(plan, self.project)
        first["targets"][0]["expected"]["files"][0]["sha256"] = "0" * 64
        fresh = native.preview_native_install(plan, self.project)
        self.assertNotEqual("0" * 64, fresh["targets"][0]["expected"]["files"][0]["sha256"])
        with patch.object(native, "read_bundled_skill_seed", return_value=self.seed + b"changed"):
            with self.assertRaises(SkillHubContractError):
                native.preview_native_install(plan, self.project)
        self.assertFalse(self.host.exists())

    def test_mid_batch_install_and_uninstall_failures_restore_exact_preimage(self):
        plan = self.plan(2)
        rename = native._native_rename
        for operation in ("install", "uninstall"):
            with self.subTest(operation=operation):
                if operation == "uninstall":
                    self.run_plan(plan)
                before = self.snapshot()
                calls = 0

                def fail_once(source, target):
                    nonlocal calls
                    calls += 1
                    if calls == 4:
                        raise OSError("injected second ownership promotion failure")
                    return rename(source, target)

                with patch.object(native, "_native_rename", side_effect=fail_once):
                    with self.assertRaisesRegex(OSError, "injected"):
                        self.run_plan(plan, operation)
                self.assertEqual(before, self.snapshot())

    def test_global_escape_and_plan_tampering_are_rejected(self):
        plan = self.plan()
        tampered = copy.deepcopy(plan)
        tampered["actions"][0]["target_directory"] = str(self.root / "outside")
        tampered["plan_digest"] = canonical_digest({k: v for k, v in tampered.items() if k != "plan_digest"})
        with self.assertRaises(SkillHubContractError):
            native.preview_native_install(tampered, self.project)
        with patch("pathlib.Path.home", return_value=self.project):
            with self.assertRaises(SkillHubContractError):
                native.preview_native_install(plan, self.project)
        self.assertEqual({}, self.snapshot())

    def test_cli_preview_approval_and_readback_do_not_construct_hub_client(self):
        plan = self.plan()
        path = self.root / "plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")

        def invoke(command, *extra):
            out = io.StringIO()
            with redirect_stdout(out), patch("gravity_insight.skill_hub_cli.SkillHubClient", side_effect=AssertionError("CAS initialization")):
                code = main(["skills", command, "--plan", str(path), "--project-root", str(self.project), *extra])
            self.assertEqual(0, code)
            return json.loads(out.getvalue())

        preview = invoke("host-install")
        self.assertFalse(self.host.exists())
        self.assertEqual("installed", invoke("host-install", "--approve", preview["preview_digest"])["status"])
        self.assertEqual("unchanged", invoke("host-install", "--approve", preview["preview_digest"])["status"])
        self.assertEqual("consistent", invoke("host-readback")["status"])

    def test_project_cannot_be_nested_inside_either_global_skill_tree(self):
        plan = self.plan()
        for global_tree in (".agents/skills", ".claude/skills"):
            with self.subTest(global_tree=global_tree):
                nested = self.project / global_tree / "pretend-project"
                nested.mkdir(parents=True)
                changed = copy.deepcopy(plan)
                name = Path(plan["actions"][0]["target_directory"]).name
                changed["actions"][0]["target_directory"] = str(nested / ".agents/skills" / name)
                changed["plan_digest"] = canonical_digest({k: v for k, v in changed.items() if k != "plan_digest"})
                before = self.snapshot()
                with patch("pathlib.Path.home", return_value=self.project):
                    with self.assertRaisesRegex(SkillHubContractError, "User-global"):
                        native.preview_native_install(changed, nested)
                self.assertEqual(before, self.snapshot())
        for path in (PureWindowsPath("//example.invalid/share/project"), PureWindowsPath("//?/C:/Users/PC/.agents/skills")):
            with self.assertRaisesRegex(SkillHubContractError, "network/device"):
                native._native_path(path)

    def test_plan_defaults_to_project_lock_and_never_full_bundle_implicitly(self):
        self.plan()
        lock = build_skills_lock(self.session.index, self.session.reference(), sorted(self.session.index["skills"])[:1])
        (self.project / "gravity.skills.lock.json").write_text(json.dumps(lock), encoding="utf-8")
        with chdir(self.project), redirect_stdout(io.StringIO()) as out, patch(
            "gravity_insight.skill_host_install.read_bundled_skill_seed", return_value=self.seed
        ), patch(
            "gravity_insight.skill_maintenance.read_bundled_skill_seed", return_value=self.seed
        ):
            code = main(["skills", "host-install-plan", "--host", "codex", "--host-root", str(self.host), "--state-root", str(self.client.state_root)])
        self.assertEqual(0, code)
        self.assertEqual(1, len(json.loads(out.getvalue())["actions"]))
        self.assertFalse(self.host.exists())

    def test_non_targets_never_write_project_or_user_host_directories(self):
        from gravity_insight import __main__ as entry

        home = self.root / "home"
        for prefix in (home / ".agents/skills", home / ".claude/skills", self.host):
            path = prefix / "lark-existing/SKILL.md"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"existing shared host")
        before = {str(p): p.read_bytes() for p in self.root.rglob("SKILL.md")}
        environment = {
            "GRAVITY_CACHE_HOME": str(self.root / "isolated-cache"),
            "GRAVITY_INSIGHT_AUTO_UPGRADE": "0", "GRAVITY_INSIGHT_AUTO_SKILLS": "1",
        }
        with (
            chdir(self.project), patch.dict(os.environ, environment),
            patch("pathlib.Path.home", return_value=home),
            patch("gravity_insight.skill_maintenance.read_bundled_skill_seed", return_value=self.seed),
            patch.object(native, "execute_native_install", side_effect=AssertionError("implicit host installer")),
            redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()),
        ):
            for arguments in (["agent"], ["skills", "status"], ["skills", "bootstrap"]):
                with self.subTest(arguments=arguments):
                    self.assertEqual(0, entry.main(arguments))
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob("SKILL.md") if "isolated-cache" not in p.parts})
        self.assertEqual(["lark-existing"], sorted(p.name for p in self.host.iterdir()))

    def test_missing_lock_does_not_stage_and_root_readback_skips_bootstrap(self):
        from gravity_insight import __main__ as entry

        with chdir(self.project), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), patch.object(SkillHubClient, "host_install_plan") as build:
            code = main(["skills", "host-install-plan", "--host", "codex", "--host-root", str(self.host), "--state-root", str(self.client.state_root)])
        self.assertNotEqual(0, code)
        build.assert_not_called()
        with patch("gravity_insight.skill_maintenance_startup.maybe_bootstrap_bundled_skills") as bootstrap:
            for prefix in ([], ["insight"]):
                entry._startup_skill_maintenance([*prefix, "skills", "host-readback"])
        bootstrap.assert_not_called()

    def test_ownership_drift_and_hardlinked_target_block_undo(self):
        plan = self.plan()
        self.run_plan(plan)
        preview = native.preview_native_install(plan, self.project, operation="uninstall")
        owner = Path(preview["targets"][0]["ownership_path"])
        owner.write_bytes(b"unrecognized owner")
        before = self.snapshot()
        with self.assertRaises(SkillHubContractError):
            native.execute_native_install(plan, self.project, approve=preview["preview_digest"], operation="uninstall")
        self.assertEqual(before, self.snapshot())
        target = Path(plan["actions"][0]["target_directory"]) / "SKILL.md"
        os.link(target, self.project / "linked-skill")
        with self.assertRaises(SkillHubContractError):
            native.preview_native_install(plan, self.project, operation="uninstall")

    def test_readback_failure_rolls_back_and_busy_guard_fails_closed(self):
        plan = self.plan()
        before = self.snapshot()
        with patch.object(native, "readback_native_install", side_effect=OSError("injected readback")):
            with self.assertRaisesRegex(OSError, "injected readback"):
                self.run_plan(plan)
        self.assertEqual(before, self.snapshot())
        (self.project / ".gravity-native-install.lock").mkdir()
        with self.assertRaises(SkillHubContractError) as error:
            self.run_plan(plan)
        self.assertEqual("HOST_SKILL_INSTALL_BUSY", error.exception.reason_code)

    def test_rollback_conflict_preserves_removed_originals_for_manual_recovery(self):
        plan = self.plan(2)
        self.run_plan(plan)
        target = Path(plan["actions"][0]["target_directory"])
        rename = native._native_rename
        calls = 0

        def concurrent_conflict(source, destination):
            nonlocal calls
            calls += 1
            if calls == 3:
                target.mkdir()
                (target / "local.txt").write_bytes(b"concurrent local edit")
                raise OSError("injected concurrent writer")
            return rename(source, destination)

        with patch.object(native, "_native_rename", side_effect=concurrent_conflict):
            with self.assertRaises(SkillHubContractError) as error:
                self.run_plan(plan, "uninstall")
        self.assertEqual("HOST_SKILL_ROLLBACK_CONFLICT", error.exception.reason_code)
        self.assertEqual(b"concurrent local edit", (target / "local.txt").read_bytes())
        backups = list(self.project.glob(".gravity-native-*/0/SKILL.md"))
        self.assertEqual(1, len(backups))
        self.assertEqual((Path(plan["actions"][0]["source_directory"]) / "SKILL.md").read_bytes(), backups[0].read_bytes())
