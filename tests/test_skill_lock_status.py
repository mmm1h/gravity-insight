from __future__ import annotations

from contextlib import chdir, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from gravity_insight import __version__
from gravity_insight.cli import main
from gravity_insight.skill_hub_contract import compile_hub_index
from gravity_insight.skill_hub_locks import build_skills_lock, compile_skills_lock
from gravity_insight.skill_hub_state import build_hub_snapshot, write_hub_snapshot
from gravity_insight.skill_maintenance_state import (
    compile_skill_maintenance_receipt,
    not_bootstrapped_skill_maintenance_receipt,
    write_skill_maintenance_receipt,
)
from tests.locked_skill_fixture import canonical_skill_manifest
from tests.test_skill_hub_contracts import hub_index, skill_entry, source_snapshot
from tests.test_workspace import _workspace_text


class SkillLockStatusTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        # Resolve before use: on Windows a >8-character account name gives the
        # temp root an 8.3 alias (RUNNER~1), and the diagnostic reports the
        # canonical long form. Comparing the two spellings fails only on hosts
        # that have such an alias, which is why it survived local runs.
        self.root = Path(temporary.name).resolve() / "project's $offline workspace"
        self.root.mkdir()
        self.state = self.root / "state"
        self.path = self.root / "gravity.skills.lock.json"
        self.index = compile_hub_index(
            hub_index(skills=[skill_entry(canonical_skill_manifest())], packs=[])
        )
        self.source = source_snapshot(self.index)

    def write_lock(self, version: str = __version__) -> dict:
        lock = build_skills_lock(
            self.index, self.source, list(self.index["skills"]), runtime_version=version
        )
        self.path.write_text(json.dumps(lock), encoding="utf-8")
        return lock

    def invoke(self, *arguments: str, start: Path | None = None) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            chdir(start or self.root),
            patch.dict(os.environ, {"GRAVITY_WORKSPACE": ""}),
            patch("socket.socket", side_effect=AssertionError("network attempted")),
            patch("gravity_insight.runtime.build_client", side_effect=AssertionError("credentials attempted")),
            patch("gravity_insight.skill_maintenance.read_bundled_skill_seed", side_effect=AssertionError("seed opened")),
            redirect_stdout(stdout), redirect_stderr(stderr),
        ):
            code = main(list(arguments))
        return code, stdout.getvalue(), stderr.getvalue()

    def status(self, *arguments: str, start: Path | None = None) -> dict:
        code, stdout, stderr = self.invoke(
            "skills", "status", "--state-root", str(self.state), *arguments, start=start
        )
        self.assertEqual((0, ""), (code, stderr))
        report = json.loads(stdout)
        self.assertEqual(report, compile_skill_maintenance_receipt(report))
        return report

    def test_no_lock_is_explicitly_not_checked_not_a_match(self) -> None:
        report = self.status()
        diagnostic = report["project_lock"]
        self.assertEqual("not_checked", diagnostic["status"])
        self.assertEqual("no_lock", diagnostic["reason"])
        self.assertIsNone(diagnostic["locked_runtime_version"])
        self.assertIsNone(diagnostic["next_action"])
        self.assertEqual(str(self.path), diagnostic["lock_path"])
        self.assertFalse(self.path.exists())

    def test_match_is_checked_independently_of_unbootstrapped_seed(self) -> None:
        self.write_lock()
        report = self.status()
        self.assertEqual("match", report["project_lock"]["status"])
        self.assertEqual(__version__, report["project_lock"]["locked_runtime_version"])
        self.assertIsNone(report["project_lock"]["next_action"])
        self.assertEqual("not_bootstrapped", report["status"])
        self.assertFalse(report["bootstrap_checked"])

    def test_stale_036_project_lock_reports_runtime_and_executable_remedy_offline(self) -> None:
        self.write_lock("0.3.6")
        before = self.path.read_bytes()
        receipt_path = write_skill_maintenance_receipt(
            self.state, not_bootstrapped_skill_maintenance_receipt()
        )
        receipt_before = receipt_path.read_bytes()
        report = self.status("--lock", str(self.path))
        diagnostic = report["project_lock"]
        self.assertEqual("mismatch", diagnostic["status"])
        self.assertEqual("HUB_RUNTIME_INCOMPATIBLE", diagnostic["reason"])
        self.assertEqual("0.3.6", diagnostic["locked_runtime_version"])
        self.assertEqual(__version__, diagnostic["runtime_version"])
        self.assertFalse(report["network_called"])
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(receipt_before, receipt_path.read_bytes())

        # Parse the emitted command with the native shell, including hostile path characters.
        command = diagnostic["next_action"]
        if os.name == "nt":
            parsed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                 "function gravity { ConvertTo-Json -InputObject @($args) -Compress }; " + command],
                capture_output=True, text=True, encoding="utf-8", check=True, timeout=30,
            )
            arguments = json.loads(parsed.stdout)
        else:
            arguments = shlex.split(command)[1:]
        self.assertEqual(["skills", "lock"], arguments[:2])
        self.assertEqual(str(self.path), arguments[arguments.index("--output") + 1])
        self.assertEqual(self.source["source_id"], arguments[arguments.index("--source-id") + 1])
        write_hub_snapshot(
            self.state,
            build_hub_snapshot(self.source, self.source["source_descriptor_digest"], self.index, network_called=False),
        )
        code, _, stderr = self.invoke(*arguments)
        self.assertEqual((0, ""), (code, stderr))
        rebuilt = compile_skills_lock(json.loads(self.path.read_text(encoding="utf-8")))
        self.assertEqual(__version__, rebuilt["runtime_version"])
        self.assertEqual(list(self.index["skills"]), rebuilt["requested"])
        self.assertEqual("match", self.status()["project_lock"]["status"])

    def test_workspace_root_is_used_from_subdirectory_even_with_explicit_state(self) -> None:
        self.write_lock()
        (self.root / "gravity.toml").write_text(_workspace_text(), encoding="utf-8")
        nested = self.root / "nested"
        nested.mkdir()
        report = self.status(start=nested)
        self.assertEqual(str(self.path), report["project_lock"]["lock_path"])
        self.assertEqual("match", report["project_lock"]["status"])

    def test_default_state_and_lock_both_use_discovered_workspace(self) -> None:
        self.write_lock("0.3.6")
        (self.root / "gravity.toml").write_text(_workspace_text(), encoding="utf-8")
        with patch.dict(os.environ, {"GRAVITY_CACHE_HOME": str(self.state)}):
            code, stdout, stderr = self.invoke("skills", "status")
        self.assertEqual((0, ""), (code, stderr))
        report = compile_skill_maintenance_receipt(json.loads(stdout))
        self.assertEqual("mismatch", report["project_lock"]["status"])
        self.assertEqual(str(self.path), report["project_lock"]["lock_path"])
        self.assertIn("workspaces", report["project_lock"]["next_action"])

    def test_explicit_lock_overrides_default_and_missing_is_not_checked(self) -> None:
        self.write_lock()
        other = self.root / "absent.json"
        report = self.status("--lock", str(other))
        self.assertEqual("not_checked", report["project_lock"]["status"])
        self.assertEqual("no_lock", report["project_lock"]["reason"])
        self.assertEqual(str(other), report["project_lock"]["lock_path"])

    def test_bad_lock_is_a_stderr_error_without_partial_stdout(self) -> None:
        lock = self.write_lock()
        corrupted = {**lock, "runtime_version": "0.3.6"}
        for content in ("not-json-private-marker", json.dumps({}), json.dumps(corrupted)):
            with self.subTest(content=content[:8]):
                self.path.write_text(content, encoding="utf-8")
                code, stdout, stderr = self.invoke("skills", "status", "--state-root", str(self.state))
                self.assertNotEqual(0, code)
                self.assertEqual("", stdout)
                self.assertIn("error", json.loads(stderr))
                self.assertNotIn("private-marker", stderr)

    def test_unreadable_lock_does_not_collapse_to_no_lock(self) -> None:
        self.write_lock()
        with patch("gravity_insight.skill_hub_cli.read_json", side_effect=PermissionError("private-path-marker")):
            code, stdout, stderr = self.invoke("skills", "status", "--state-root", str(self.state))
        self.assertNotEqual(0, code)
        self.assertEqual("", stdout)
        self.assertIn("SKILLS_LOCK_INVALID", stderr)
        self.assertNotIn("private-path-marker", stderr)

    def test_linked_lock_is_rejected_before_reading_target(self) -> None:
        self.write_lock()
        os.link(self.path, self.root / "linked.json")
        with patch("gravity_insight.skill_hub_cli.read_json", side_effect=AssertionError("linked file read")):
            code, stdout, stderr = self.invoke("skills", "status", "--state-root", str(self.state))
        self.assertNotEqual(0, code)
        self.assertEqual("", stdout)
        self.assertIn("SKILLS_LOCK_INVALID", stderr)


if __name__ == "__main__":
    unittest.main()
