from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from scripts.check_subprocess_text_encoding import check_repository


class SubprocessTextEncodingGateTests(unittest.TestCase):
    def _fixture(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for relative in ("scripts", "src", "tests"):
            (root / relative).mkdir()
        return root

    def test_explicit_encoding_and_locale_exemption_pass(self) -> None:
        root = self._fixture()
        (root / "scripts" / "good.py").write_text(
            "import subprocess\nsubprocess.run(['git'], text=True, encoding='utf-8')\n",
            encoding="utf-8",
        )
        (root / "tests" / "test_gravity_cli_stdio.py").write_text(
            "import subprocess\nsubprocess.run(['python'], capture_output=True).stdout.decode('utf-8')\n",
            encoding="utf-8",
        )

        code, receipt = check_repository(root)

        self.assertEqual(0, code)
        self.assertEqual("pass", receipt["status"])
        self.assertEqual(
            ["tests/test_gravity_cli_stdio.py"],
            [item["path"] for item in receipt["exemptions"]],
        )

    def test_call_exemption_survives_a_line_shift(self) -> None:
        """The call exemption keys on the enclosing function, not on where it sits.

        A line number describes the file's current layout rather than the call.
        Pinning one means an unrelated edit above shifts it, the exemption stops
        matching, and this fail-closed gate goes red for a change that had
        nothing to do with it -- and shifts differently per branch, so it can go
        red only at merge time.
        """
        exempted = (
            "import subprocess\n"
            "\n"
            "def _launch_subprocess(command, flags):\n"
            "    return subprocess.Popen(command, **flags)\n"
        )
        for padding in (0, 40):
            with self.subTest(padding=padding):
                root = self._fixture()
                target = (
                    root / "src" / "gravity_insight" / "provider_rpc_transport.py"
                )
                target.parent.mkdir(parents=True)
                target.write_text("\n" * padding + exempted, encoding="utf-8")

                code, receipt = check_repository(root)

                self.assertEqual(0, code)
                self.assertEqual("pass", receipt["status"])
                self.assertEqual(
                    ["_launch_subprocess"],
                    [item["function"] for item in receipt["exemptions"]],
                )

    def test_call_exemption_does_not_cover_a_renamed_function(self) -> None:
        """Renaming the enclosing function is a change worth re-reading."""
        root = self._fixture()
        target = root / "src" / "gravity_insight" / "provider_rpc_transport.py"
        target.parent.mkdir(parents=True)
        target.write_text(
            "import subprocess\n"
            "\n"
            "def _spawn(command, flags):\n"
            "    return subprocess.Popen(command, **flags)\n",
            encoding="utf-8",
        )

        code, receipt = check_repository(root)

        self.assertEqual(1, code)
        self.assertEqual("fail", receipt["status"])
        self.assertEqual(
            "subprocess-keywords-unresolved", receipt["findings"][0]["detector"]
        )

    def test_missing_encoding_fails_with_file_and_line(self) -> None:
        root = self._fixture()
        source = root / "scripts" / "bad.py"
        source.write_text(
            "import subprocess\n\nsubprocess.run(['tool'], text=True)\n",
            encoding="utf-8",
        )

        code, receipt = check_repository(root)

        self.assertEqual(1, code)
        self.assertEqual("fail", receipt["status"])
        self.assertEqual("scripts/bad.py", receipt["findings"][0]["path"])
        self.assertEqual(3, receipt["findings"][0]["line"])

    def _check_source(self, source: str, path: str = "scripts/probe.py"):
        root = self._fixture()
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
        return check_repository(root)

    def test_python_both_ends_pinned_pass(self) -> None:
        for executable in ("sys.executable", "'python'", "'python3.12'", "'C:/venv/Scripts/python.exe'"):
            with self.subTest(executable=executable):
                code, receipt = self._check_source(
                    "import subprocess, sys, os\n"
                    f"subprocess.run([{executable}, '-m', 'probe'], text=True, encoding='utf-8', "
                    "env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'})\n"
                )
                self.assertEqual((0, []), (code, receipt["findings"]))

    def test_python_decoder_only_fails_at_exact_function_and_line(self) -> None:
        code, receipt = self._check_source(
            "import subprocess, sys\ndef collect():\n"
            "    return subprocess.run([sys.executable, '-c', 'print(1)'], text=True, encoding='utf-8')\n"
        )
        self.assertEqual(1, code)
        finding = receipt["findings"][0]
        self.assertEqual(("scripts/probe.py", 3), (finding["path"], finding["line"]))
        self.assertEqual("subprocess-python-encoder-unpinned", finding["detector"])
        self.assertIn("collect: Python child encoder is unpinned", finding["detail"])

    def test_encoding_alone_enables_text_mode_and_needs_encoder(self) -> None:
        code, receipt = self._check_source(
            "from subprocess import run as spawn\nspawn(['python', '-m', 'probe'], encoding='utf-8')\n"
        )
        self.assertEqual(1, code)
        self.assertEqual("subprocess-python-encoder-unpinned", receipt["findings"][0]["detector"])

    def test_isolated_python_requires_effective_command_flag(self) -> None:
        for flags, expected in (("'-I'", 1), ("'-E'", 1), ("'-I', '-X', 'utf8'", 0), ("'-I', '-Xutf8'", 0), ("'-I', '-Xutf8', '-Xutf8=0'", 1)):
            with self.subTest(flags=flags):
                code, receipt = self._check_source(
                    "import subprocess\n"
                    f"subprocess.run(['python', {flags}, '-m', 'probe'], encoding='utf-8', "
                    "env={'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'})\n"
                )
                self.assertEqual(expected, code, receipt)

    def test_inherited_or_overridden_stdio_is_not_proof(self) -> None:
        for environment in ("os.environ", "{'PYTHONUTF8': '1'}", "{'PYTHONIOENCODING': 'gbk'}", "{'PYTHONIOENCODING': 'utf-8', **os.environ}"):
            with self.subTest(environment=environment):
                code, _ = self._check_source(
                    "import subprocess, os\n"
                    f"subprocess.run(['python', '-m', 'probe'], encoding='utf-8', env={environment})\n"
                )
                self.assertEqual(1, code)

    def test_unknown_command_fails_closed_even_with_pins(self) -> None:
        for command in ("command", "[executable, '-m', 'probe']", "['unknown-console-script']"):
            with self.subTest(command=command):
                code, receipt = self._check_source(
                    "import subprocess\n"
                    f"subprocess.run({command}, encoding='utf-8', env={{'PYTHONIOENCODING': 'utf-8'}})\n"
                )
                self.assertEqual(1, code)
                self.assertEqual("subprocess-command-unresolved", receipt["findings"][0]["detector"])

    def test_dynamic_command_exemption_does_not_waive_encoder(self) -> None:
        for padding in (0, 30):
            for name, pinned, expected in (("_run", True, 0), ("_run", False, 1), ("_renamed", True, 1)):
                with self.subTest(padding=padding, name=name, pinned=pinned):
                    env = ", env={'PYTHONIOENCODING': 'utf-8'}" if pinned else ""
                    code, receipt = self._check_source(
                        "\n" * padding + "import subprocess\n"
                        f"def {name}(command):\n"
                        f"    return subprocess.run(command, encoding='utf-8'{env})\n",
                        "scripts/check_installed_wheel_consumer.py",
                    )
                    self.assertEqual(expected, code, receipt)

    def test_injected_subprocess_runner_requires_encoder(self) -> None:
        code, receipt = self._check_source(
            "import subprocess, sys\ndef audit(*, runner=subprocess.run):\n"
            "    return runner([sys.executable, '-m', 'probe'], text=True, encoding='utf-8')\n"
        )
        self.assertEqual(1, code)
        self.assertEqual("subprocess-python-encoder-unpinned", receipt["findings"][0]["detector"])


if __name__ == "__main__":
    unittest.main()
