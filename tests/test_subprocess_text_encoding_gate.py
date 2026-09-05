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
            "import subprocess\nsubprocess.run(['tool'], text=True, encoding='utf-8')\n",
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


if __name__ == "__main__":
    unittest.main()
