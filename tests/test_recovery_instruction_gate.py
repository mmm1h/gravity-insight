from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts.check_recovery_instructions import (
    check_repository,
    recovery_commands,
    resolve_cli_command,
)


ROOT = Path(__file__).resolve().parents[1]


class RecoveryInstructionGateTests(unittest.TestCase):
    def test_repository_recovery_instructions_are_resolvable(self) -> None:
        code, receipt = check_repository(ROOT)
        self.assertEqual(0, code, json.dumps(receipt, indent=2))
        self.assertEqual([], receipt["findings"])

    def test_help_target_must_be_a_registered_command_not_a_positional(self) -> None:
        misleading = resolve_cli_command("gravity agent catalog --help")
        self.assertEqual(("agent",), misleading.command_path)
        self.assertIn("non-command token", str(misleading.error))

        exact = resolve_cli_command("gravity agent-catalog --help")
        self.assertEqual(("agent-catalog",), exact.command_path)
        self.assertIsNone(exact.error)

    def test_nested_namespaces_use_their_real_parser_trees(self) -> None:
        cases = {
            "gravity insight operations describe <operation-id>": (
                "insight",
                "operations",
                "describe",
            ),
            "gravity census fetch --output <snapshot.json>": ("census", "fetch"),
            "gravity sql products": ("sql", "products"),
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                result = resolve_cli_command(command)
                self.assertIsNone(result.error)
                self.assertEqual(expected, result.command_path)

    def test_options_and_structured_input_placeholders_match_the_parser(self) -> None:
        valid = (
            "gravity agent-catalog describe <selector>",
            "gravity agent --input <questions.json>",
        )
        for command in valid:
            with self.subTest(command=command):
                self.assertIsNone(resolve_cli_command(command).error)

        unknown = resolve_cli_command("gravity agent --not-a-real-option value")
        self.assertIn("not a registered option", str(unknown.error))

        missing = resolve_cli_command(
            "gravity agent --routing host_catalog --host-selection"
        )
        self.assertIn("requires one value", str(missing.error))

        wrong_shape = resolve_cli_command("gravity agent --input <selector>")
        self.assertIn("structured input", str(wrong_shape.error))
        self.assertIn("placeholder '<selector>'", str(wrong_shape.error))

        literal_selector = resolve_cli_command(
            "gravity agent --input metadata:search"
        )
        self.assertIn("selector-like value 'metadata:search'", str(literal_selector.error))

    def test_unknown_top_level_command_is_not_accepted_by_optional_root(self) -> None:
        result = resolve_cli_command("gravity definitely-not-a-command")
        self.assertEqual((), result.command_path)
        self.assertIn("not a registered subcommand", str(result.error))

    def test_ast_scan_includes_fields_and_imperative_error_text(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as raw:
            path = Path(raw) / "fixture.py"
            path.write_text(
                """\
example = "Run `gravity agent catalog --help`."
next_action = "Run `gravity agent catalog --help`."
payload = {"remediation": "Run `gravity skills list --state-root <state-root>`."}
structured = {"next": {"argv": ["gravity", "agent-catalog", "categories"]}}
""",
                encoding="utf-8",
                newline="\n",
            )
            commands = recovery_commands(path)
        self.assertEqual(
            [
                (1, "gravity agent catalog --help"),
                (2, "gravity agent catalog --help"),
                (3, "gravity skills list --state-root <state-root>"),
                (4, "gravity agent-catalog categories"),
            ],
            commands,
        )

    def test_ast_scan_includes_unquoted_next_action_and_fallback_argv(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as raw:
            path = Path(raw) / "fixture.py"
            path.write_text(
                """\
next_action = "Call gravity agent --input <selector> independently; then stop."
fallbacks = [{"argv": ["gravity", "agent-catalog", "describe", "<selector>"]}]
""",
                encoding="utf-8",
                newline="\n",
            )
            commands = recovery_commands(path)
        self.assertEqual(
            [
                (1, "gravity agent --input <selector> independently"),
                (2, "gravity agent-catalog describe <selector>"),
            ],
            commands,
        )

    def test_repository_gate_rejects_selector_as_agent_input(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as raw:
            root = Path(raw)
            source = root / "src" / "gravity_insight" / "fixture.py"
            source.parent.mkdir(parents=True)
            source.write_text(
                'next_action = "Call gravity agent --input <selector>; then stop."\n',
                encoding="utf-8",
                newline="\n",
            )
            code, receipt = check_repository(root)
        self.assertEqual(1, code)
        self.assertEqual(1, receipt["scanned"]["command_suggestions"])
        self.assertEqual(1, receipt["finding_count"])
        self.assertIn(
            "placeholder '<selector>' does not describe that input",
            receipt["findings"][0]["detail"],
        )

    def test_imperative_error_message_is_an_equivalent_recovery_field(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as raw:
            path = Path(raw) / "fixture.py"
            path.write_text(
                "raise ValueError(\"Invalid input; run `gravity agent catalog --help`.\")\n",
                encoding="utf-8",
                newline="\n",
            )
            commands = recovery_commands(path)
        self.assertEqual([(1, "gravity agent catalog --help")], commands)

    def test_workflow_artifact_must_be_exact_precreated_and_always_uploaded(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as raw:
            root = Path(raw)
            workflow = root / ".github" / "workflows" / "fixture.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """\
jobs:
  inspect:
    steps:
      - name: Fetch
        run: |
          $snapshot = Join-Path $env:RUNNER_TEMP "current-snapshot.json"
          gravity census fetch --output $snapshot
      - name: Upload
        if: always()
        uses: actions/upload-artifact@v4
        with:
          path: ${{ runner.temp }}/current-snapshot.json
      - name: Reject
        run: throw "Inspect the uploaded snapshot."
""",
                encoding="utf-8",
                newline="\n",
            )
            code, receipt = check_repository(root)
        self.assertEqual(1, code)
        detectors = {item["detector"] for item in receipt["findings"]}
        self.assertIn("recovery-artifact-not-exact", detectors)

    def test_exact_uploaded_artifact_must_precede_the_fallible_fetch(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as raw:
            root = Path(raw)
            workflow = root / ".github" / "workflows" / "fixture.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """\
jobs:
  inspect:
    steps:
      - name: Fetch
        run: |
          $snapshot = Join-Path $env:RUNNER_TEMP "current-snapshot.json"
          gravity census fetch --output $snapshot
      - name: Upload
        if: always()
        uses: actions/upload-artifact@v4
        with:
          path: ${{ runner.temp }}/current-snapshot.json
      - name: Reject
        run: throw "Inspect the uploaded current-snapshot.json."
""",
                encoding="utf-8",
                newline="\n",
            )
            code, receipt = check_repository(root)
        self.assertEqual(1, code)
        self.assertEqual(
            ["recovery-artifact-unavailable"],
            [item["detector"] for item in receipt["findings"]],
        )

    def test_recovery_artifact_upload_must_run_after_failure(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as raw:
            root = Path(raw)
            workflow = root / ".github" / "workflows" / "fixture.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                """\
jobs:
  inspect:
    steps:
      - name: Fetch
        run: |
          $snapshot = Join-Path $env:RUNNER_TEMP "current-snapshot.json"
          @{} | ConvertTo-Json | Set-Content -LiteralPath $snapshot
          gravity census fetch --output $snapshot
      - name: Upload
        uses: actions/upload-artifact@v4
        with:
          path: ${{ runner.temp }}/current-snapshot.json
      - name: Reject
        run: throw "Inspect the uploaded current-snapshot.json."
""",
                encoding="utf-8",
                newline="\n",
            )
            code, receipt = check_repository(root)
        self.assertEqual(1, code)
        self.assertEqual(
            ["recovery-artifact-unavailable"],
            [item["detector"] for item in receipt["findings"]],
        )


if __name__ == "__main__":
    unittest.main()
