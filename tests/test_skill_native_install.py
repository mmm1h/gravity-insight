from __future__ import annotations

from contextlib import chdir, redirect_stdout
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from gravity_insight import skill_host_install as native
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
        self.assertEqual("consistent", invoke("host-readback")["status"])

    def test_plan_defaults_to_project_lock_and_never_full_bundle_implicitly(self):
        self.plan()
        lock = build_skills_lock(self.session.index, self.session.reference(), sorted(self.session.index["skills"])[:1])
        (self.project / "gravity.skills.lock.json").write_text(json.dumps(lock), encoding="utf-8")
        with chdir(self.project), redirect_stdout(io.StringIO()) as out:
            code = main(["skills", "host-install-plan", "--host", "codex", "--host-root", str(self.host), "--state-root", str(self.client.state_root)])
        self.assertEqual(0, code)
        self.assertEqual(1, len(json.loads(out.getvalue())["actions"]))
        self.assertFalse(self.host.exists())
