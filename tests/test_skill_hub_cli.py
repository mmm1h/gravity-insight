from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gravity_insight import SkillHubClient, TrustedPackHubClient
from gravity_insight.cli import build_parser, main
from tests.test_skill_hub_contracts import (
    _render_without_wheel_paths,
    git_source,
    hub_index,
    skill_entry,
    trusted_entry,
)
from tests.test_skill_hub_io import GitHubFixture, bound_entry, skill_archive, trusted_wheel


class SkillHubCliTests(unittest.TestCase):
    def setUp(self) -> None:
        raw_skill = skill_entry()
        self.skill_zip = skill_archive(raw_skill)
        self.skill = bound_entry(raw_skill, self.skill_zip)
        self.wheel = trusted_wheel()
        self.trusted = trusted_entry(self.wheel)
        self.fixture = GitHubFixture()
        self.fixture.publish(
            hub_index(skills=[self.skill], packs=[self.trusted]),
            {
                self.skill["archive"]["path"]: self.skill_zip,
                self.trusted["archive"]["path"]: self.wheel,
            },
        )
        self.mirror = self.fixture.clone("cli")
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state = self.root / "state"
        self.cas = self.root / "cas"
        self.source = self.root / "source.json"
        self.source.write_text(json.dumps(git_source()), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()
        self.fixture.close()

    def invoke(self, *arguments: str) -> tuple[int, dict, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch(
                "gravity_insight.runtime.build_client",
                side_effect=AssertionError("Gravity client constructed"),
            ),
            patch("socket.socket", side_effect=AssertionError("network attempted")),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = main(list(arguments))
        rendered = stdout.getvalue() or stderr.getvalue()
        return code, json.loads(rendered), stderr.getvalue()

    def local(self) -> list[str]:
        return ["--state-root", str(self.state), "--cas-root", str(self.cas)]

    def test_root_exports_and_all_control_commands_are_gravity_offline(self) -> None:
        self.assertIsInstance(SkillHubClient(self.state), SkillHubClient)
        self.assertIsInstance(TrustedPackHubClient(self.state), TrustedPackHubClient)
        parser = build_parser()
        commands = {
            "sync": ["--source", str(self.source), "--repository", str(self.mirror)],
            "search": ["example"],
            "resolve": ["--skill", self.skill["skill_uri"]],
            "lock": ["--skill", self.skill["skill_uri"], "--output", "lock.json"],
            "fetch": ["--source", str(self.source), "--repository", str(self.mirror), "--lock", "lock.json"],
            "install": ["--lock", "lock.json"],
            "update": ["--skill", self.skill["skill_uri"], "--output", "lock.json"],
            "verify": ["--lock", "lock.json"],
            "audit": [],
        }
        for command, arguments in commands.items():
            with self.subTest(command=command):
                parsed = parser.parse_args(
                    ["skills", command, *arguments, *self.local()]
                )
                self.assertFalse(parsed.network_required)
                self.assertEqual(
                    command in {"lock", "update"},
                    bool(getattr(parsed, "product_file_output", False)),
                )

        trusted = {
            "resolve": ["--pack", self.trusted["pack_id"]],
            "lock": ["--pack", self.trusted["pack_id"], "--output", "lock.json"],
            "fetch": ["--source", str(self.source), "--repository", str(self.mirror), "--lock", "lock.json"],
            "verify": ["--lock", "lock.json"],
            "install-plan": ["--lock", "lock.json", "--output", "plan.json"],
        }
        for command, arguments in trusted.items():
            with self.subTest(command=f"trusted:{command}"):
                parsed = parser.parse_args(
                    ["trusted-packs", command, *arguments, *self.local()]
                )
                self.assertFalse(parsed.network_required)
                self.assertEqual(
                    command in {"lock", "install-plan"},
                    bool(getattr(parsed, "product_file_output", False)),
                )

    def test_skill_cli_runs_sync_exact_lock_fetch_install_verify_and_audit(self) -> None:
        common = self.local()
        code, synced, stderr = self.invoke(
            "skills",
            "sync",
            "--source",
            str(self.source),
            "--repository",
            str(self.mirror),
            *common,
        )
        self.assertEqual(0, code, stderr)
        self.assertEqual("synced", synced["status"])

        code, listed, _ = self.invoke("skills", "list", *common)
        self.assertEqual(0, code)
        self.assertEqual("gravity.skill-hub-list.v1", listed["schema_version"])
        self.assertEqual(self.skill["skill_uri"], listed["results"][0]["skill_uri"])

        code, searched, _ = self.invoke(
            "skills", "search", "team-analysis", *common
        )
        self.assertEqual(0, code)
        self.assertEqual(self.skill["skill_uri"], searched["results"][0]["skill_uri"])
        code, shown, _ = self.invoke(
            "skills", "show", self.skill["skill_uri"], *common
        )
        self.assertEqual(0, code)
        self.assertEqual("available", shown["status"])

        lock_path = self.root / "gravity.skills.lock.json"
        code, locked, _ = self.invoke(
            "skills",
            "lock",
            "--skill",
            self.skill["skill_uri"],
            "--output",
            str(lock_path),
            *common,
        )
        self.assertEqual(0, code)
        self.assertEqual("written", locked["status"])
        code, fetched, _ = self.invoke(
            "skills",
            "fetch",
            "--lock",
            str(lock_path),
            "--source",
            str(self.source),
            "--repository",
            str(self.mirror),
            *common,
        )
        self.assertEqual(0, code)
        self.assertEqual("verified", fetched["status"])
        code, verified, _ = self.invoke(
            "skills", "verify", "--lock", str(lock_path), *common
        )
        self.assertEqual(0, code)
        self.assertTrue(verified["ok"])
        code, installed, _ = self.invoke(
            "skills",
            "install",
            "--lock",
            str(lock_path),
            "--install-root",
            str(self.root / "installed"),
            *common,
        )
        self.assertEqual(0, code)
        self.assertEqual("installed", installed["status"])
        code, updated, _ = self.invoke(
            "skills",
            "update",
            "--skill",
            self.skill["skill_uri"],
            "--output",
            str(lock_path),
            *common,
        )
        self.assertEqual(0, code)
        self.assertEqual("unchanged", updated["status"])
        code, audit, _ = self.invoke("skills", "audit", *common)
        self.assertEqual(0, code)
        self.assertEqual(1, len(audit["sources"]))

    def test_trusted_cli_stops_at_exact_external_installer_plan(self) -> None:
        common = self.local()
        self.invoke(
            "skills",
            "sync",
            "--source",
            str(self.source),
            "--repository",
            str(self.mirror),
            *common,
        )
        lock_path = self.root / "gravity.trusted-packs.lock.json"
        code, locked, _ = self.invoke(
            "trusted-packs",
            "lock",
            "--pack",
            self.trusted["pack_id"],
            "--output",
            str(lock_path),
            *common,
        )
        self.assertEqual(0, code)
        self.assertEqual("written", locked["status"])
        code, fetched, _ = self.invoke(
            "trusted-packs",
            "fetch",
            "--lock",
            str(lock_path),
            "--source",
            str(self.source),
            "--repository",
            str(self.mirror),
            *common,
        )
        self.assertEqual(0, code)
        self.assertEqual("verified", fetched["status"])
        code, verified, _ = self.invoke(
            "trusted-packs", "verify", "--lock", str(lock_path), *common
        )
        self.assertEqual(0, code)
        self.assertTrue(verified["ok"])

        plan_path = self.root / "install-plan.json"
        code, plan_result, _ = self.invoke(
            "trusted-packs",
            "install-plan",
            "--lock",
            str(lock_path),
            "--output",
            str(plan_path),
            *common,
        )
        self.assertEqual(0, code)
        self.assertEqual("written", plan_result["status"])
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual("external_installer", plan["installation_owner"])
        rendered = _render_without_wheel_paths(plan)
        self.assertNotIn("command", rendered)
        self.assertNotIn("pip", rendered)

        code, error, stderr = self.invoke("trusted-packs", "install", *common)
        self.assertNotEqual(0, code)
        self.assertEqual("INPUT_INVALID", error["error"]["code"])
        self.assertNotEqual("", stderr)


if __name__ == "__main__":
    unittest.main()
