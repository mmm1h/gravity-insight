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
