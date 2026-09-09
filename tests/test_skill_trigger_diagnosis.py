from __future__ import annotations

from contextlib import chdir, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from gravity_insight import __version__
from gravity_insight.cli import main
from gravity_insight.doctor_cli import _public_installation, diagnose_skills
from gravity_insight.skill_hub_client import SkillHubClient
from gravity_insight.skill_hub_locks import build_skills_lock
from gravity_insight.skill_host_install import _host_target_state
from gravity_insight.skill_seed import open_bundled_hub_source, validate_bundled_skill_seed
from scripts.generate_skill_library import render_seed


class SkillTriggerDiagnosisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.seed = render_seed()
        cls.validated = validate_bundled_skill_seed(cls.seed)
        cls.session = open_bundled_hub_source(cls.seed)
        cls.entry = cls.validated["agent_index"]["skills"][0]

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.project = self.root / "private-project"
        self.project.mkdir()
        self.state = self.root / "private-state"
        self.home = self.root / "private-user"
        self.cas = self.state / "skill-hub-cas"
        self.lock_path = self.project / "gravity.skills.lock.json"
        self.enterContext(patch("gravity_insight.doctor_cli.read_bundled_skill_seed", return_value=self.seed))
        self.enterContext(patch("pathlib.Path.home", return_value=self.home))
        network = patch("socket.socket", side_effect=AssertionError("network attempted"))
        network.start()
        self.addCleanup(network.stop)

    def diagnose(self, **kwargs):
        return diagnose_skills(
            state_root=self.state, project_root=self.project, home=self.home,
            environ={}, **kwargs,
        )

    def lock(self, version=__version__):
        lock = build_skills_lock(
            self.session.index, self.session.reference(), [self.entry["skill_uri"]],
            runtime_version=version,
        )
        self.lock_path.write_text(json.dumps(lock), encoding="utf-8")
        return lock

    def install_files(self, root=None):
        target = (root or self.home / ".agents" / "skills") / self.entry["directory"]
        for relative, content in self.validated["agent_packages"][self.entry["skill_uri"]].items():
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        return target

    def snapshot(self):
        return {
            p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None
            for p in self.root.rglob("*")
        }

    def native(self, report):
        return report["native_files"]["hosts"][0]["skills"][0]

    def test_absent_lock_and_files_are_distinct_and_diagnostics_never_create_roots(self):
        before = self.snapshot()
        report = self.diagnose()
        self.assertEqual(before, self.snapshot())
        self.assertEqual("PROJECT_LOCK_MISSING", report["project_lock"]["reason_codes"][0])
        self.assertIn("track", report["project_lock"]["next_action"])
        self.assertEqual("missing", self.native(report)["status"])
        self.assertIn("native installer", self.native(report)["next_action"])
        self.assertEqual("unknown", report["host_discovery"]["status"])
        self.assertEqual("not_measured", report["invocation"]["valid_result"])
        self.assertIsNone(report["routing"]["arm"])

    def test_wrong_directory_is_not_a_native_install_and_partial_files_conflict(self):
        self.lock()
        self.install_files(self.home / "wrong-directory")
        self.assertEqual("missing", self.native(self.diagnose())["status"])
        target = self.install_files()
        (target / "SKILL.md").unlink()
        report = self.native(self.diagnose())
        self.assertEqual("local_override_conflict", report["status"])
        self.assertEqual(["SKILL.md"], report["missing_files"])
        self.assertIn("Restore the listed missing_files", report["next_action"])

    def test_old_native_version_and_disabled_claude_header_are_not_host_observations(self):
        self.lock()
        target = self.install_files(self.home / ".claude" / "skills")
        skill = target / "SKILL.md"
        skill.write_bytes(skill.read_bytes().replace(b"---\nname:", b"---\ndisable-model-invocation: true\nname:", 1))
        schema_path = target / "references/SCHEMA.json"
        schema = json.loads(schema_path.read_bytes())
        schema["skill_uri"] = self.entry["skill_uri"].rsplit("@", 1)[0] + "@0.1.0"
        schema_path.write_text(json.dumps(schema), encoding="utf-8")
        report = self.diagnose()
        native = report["native_files"]["hosts"][2]["skills"][0]
        self.assertEqual("disabled", native["implicit_invocation"])
        self.assertIn("disable-model-invocation", native["policy_next_action"])
        self.assertEqual("mismatch", native["version_match"])
        self.assertIn("another Skill version", native["version_next_action"])
        self.assertEqual("unknown", report["host_discovery"]["status"])

    def test_installed_files_never_prove_discovery_invocation_or_project_resolution(self):
        self.lock()
        self.install_files()
        report = self.diagnose()
        self.assertEqual("installed_consistent", self.native(report)["status"])
        self.assertEqual(self.native(report)["observed_digest"], self.native(report)["expected_digest"])
        self.assertEqual("blocked", report["project_lock"]["resolution"])
        self.assertEqual("unknown", report["host_discovery"]["status"])
        self.assertEqual("not_measured", report["invocation"]["status"])

    def test_local_edits_are_preserved_and_private_content_is_not_emitted(self):
        self.lock()
        target = self.install_files()
        (target / "SKILL.md").write_text("private-body-business-value", encoding="utf-8")
        before = self.snapshot()
        report = self.diagnose()
        self.assertEqual(before, self.snapshot())
        self.assertEqual("local_override_conflict", self.native(report)["status"])
        self.assertIn("preserve local edits", self.native(report)["next_action"])
        rendered = json.dumps(report)
        for forbidden in (str(self.root), "private-user", "private-project", "private-body-business-value"):
            self.assertNotIn(forbidden, rendered)

    def test_disabled_bootstrap_is_not_host_disable_or_missing_files(self):
        self.install_files()
        report = diagnose_skills(state_root=self.state, project_root=self.project, home=self.home, environ={"GRAVITY_INSIGHT_AUTO_SKILLS": "off"})
        self.assertEqual("disabled", report["runtime_library"]["auto_bootstrap"])
        self.assertIn("explicitly run gravity skills bootstrap", report["runtime_library"]["bootstrap_next_action"])
        self.assertEqual("installed_consistent", self.native(report)["status"])
        self.assertEqual("unknown", report["host_discovery"]["enablement"])
        self.assertIn("if disabled, explicitly enable", report["host_discovery"]["next_action"])

    def test_old_runtime_and_invalid_lock_have_different_remedies_without_rewriting(self):
        self.lock("0.3.6")
        before = self.snapshot()
        report = self.diagnose()
        self.assertEqual("mismatch", report["project_lock"]["runtime_match"])
        self.assertIn("matching Runtime", report["project_lock"]["next_action"])
        self.assertEqual(before, self.snapshot())
        self.lock_path.write_text("private-invalid-json", encoding="utf-8")
        report = self.diagnose()
        self.assertEqual("invalid_or_unreadable", report["project_lock"]["parse_status"])
        self.assertNotIn("private-invalid-json", json.dumps(report))

    def test_runtime_cas_and_real_project_resolver_are_checked_independently(self):
        client = SkillHubClient(self.state)
        client.bootstrap_bundled(self.seed)
        self.lock()
        for command in (
            ["git", "init", "-q"], ["git", "add", "gravity.skills.lock.json"],
            ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"],
        ):
            subprocess.run(command, cwd=self.project, check=True, capture_output=True)
        report = self.diagnose()
        self.assertEqual("ready", report["runtime_library"]["status"])
        self.assertEqual("resolved", report["project_lock"]["resolution"])
        package = self.cas / "skills" / "sha256" / self.entry["package_digest"]
        next(p for p in package.rglob("*") if p.is_file()).write_text("changed", encoding="utf-8")
        report = self.diagnose()
        self.assertNotEqual("ready", report["runtime_library"]["status"])
        self.assertEqual("blocked", report["project_lock"]["resolution"])

    def test_cli_default_receipt_and_opt_in_diagnosis_are_read_only(self):
        for extra, schema in (([], "gravity.skill-maintenance-receipt.v1"), (["--diagnose"], "gravity.skill-trigger-diagnosis.v1")):
            output = io.StringIO()
            before = self.snapshot()
            with chdir(self.project), redirect_stdout(output), patch.dict("os.environ", {"GRAVITY_WORKSPACE": ""}):
                code = main(["skills", "status", "--state-root", str(self.state), *extra])
            self.assertEqual(0, code)
            self.assertEqual(schema, json.loads(output.getvalue())["schema_version"])
            self.assertEqual(before, self.snapshot())

    def test_doctor_installation_presentation_masks_paths_but_preserves_mismatch(self):
        private = str(self.root / "private-user")
        report = _public_installation({"status": "fail", "mismatches": ["INSTALL_IMPORT_ROOT_MISMATCH"], "metadata": [{"metadata_path": private}], "source": {"project_root": private}, "import": {"path": private}, "reinstall_commands": [f'python -m pip install -e "{private}"']})
        self.assertNotIn("private-user", json.dumps(report))
        self.assertEqual(["INSTALL_IMPORT_ROOT_MISMATCH"], report["mismatches"])

    def test_unreadable_native_target_is_unknown_not_missing(self):
        with patch.object(Path, "lstat", side_effect=PermissionError("private-path")):
            self.assertEqual(("unknown", None), _host_target_state(self.home / "skill", self.entry))

    def test_unreadable_native_contents_are_unknown_not_local_edits(self):
        self.lock()
        target = self.install_files()
        scandir = os.scandir

        def unreadable_target(path):
            if Path(path) == target:
                raise PermissionError("private-path")
            return scandir(path)

        with patch("gravity_insight.skill_host_install.os.scandir", side_effect=unreadable_target):
            self.assertEqual(("unknown", None), _host_target_state(target, self.entry))
            report = self.native(self.diagnose())
        self.assertEqual("unknown", report["status"])
        self.assertIn("Check access", report["next_action"])
        self.assertNotIn("private-path", json.dumps(report))

    def test_status_expands_user_paths_without_creating_them(self):
        output = io.StringIO()
        with chdir(self.project), redirect_stdout(output), patch.dict("os.environ", {"GRAVITY_WORKSPACE": ""}), patch("gravity_insight.doctor_cli.diagnose_skills", return_value={}) as diagnose:
            code = main(["skills", "status", "--diagnose", "--state-root", "~/state", "--cas-root", "~/cas"])
        self.assertEqual(0, code)
        self.assertEqual(Path("~/state").expanduser().absolute(), diagnose.call_args.kwargs["state_root"])
        self.assertEqual(Path("~/cas").expanduser(), diagnose.call_args.kwargs["cas_root"])
        self.assertFalse((self.project / "~").exists())


if __name__ == "__main__":
    unittest.main()
