from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gravity_sdk import cli, result_output
from gravity_sdk.sql.__main__ import _emit_query_result

class ResultOutputTests(unittest.TestCase):
    def test_partial_is_written_but_terminal_error_preserves_target(self):
        partial = {"schema_version": "test.v1", "ok": False, "status": "partial", "exit_code": 3, "results": [{"ok": True}]}
        terminal = ({"schema_version": "test.v1", "ok": False, "status": "error", "exit_code": 3, "error": {"category": "upstream"}}, {"schema_version": "test.v1", "ok": False, "status": "capability_gap", "exit_code": 4, "error": {"category": "local"}})
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "result.json"
            argv = ["reports", "pulse", "--app", "1", "--start", "2026-08-01", "--end", "2026-08-02", "--output", str(output)]
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch("gravity_sdk.cli.dispatch_command", return_value=terminal[0]), contextlib.redirect_stderr(stderr):
                self.assertEqual(3, cli.main(argv)); self.assertFalse(output.exists())
            with patch("gravity_sdk.cli.dispatch_command", return_value=partial), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                self.assertEqual(3, cli.main(argv))
            self.assertEqual(partial, json.loads(output.read_text(encoding="utf-8")))
            self.assertEqual({"ok": True, "status": "written", "output": str(output), "format": "json", "size_bytes": output.stat().st_size}, json.loads(stdout.getvalue()))
            with patch("gravity_sdk.cli.dispatch_command", return_value=terminal[1]), contextlib.redirect_stderr(stderr):
                self.assertEqual(4, cli.main(argv))
            self.assertEqual(partial, json.loads(output.read_text(encoding="utf-8")))

    def test_half_written_temporary_keeps_old_file_and_is_removed(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "result.json"; output.write_text("old", encoding="utf-8")
            def half_write(handle, value):
                handle.file.write(value[:len(value) // 2]); raise OSError("stop")
            with patch.object(tempfile._TemporaryFileWrapper, "write", half_write, create=True), self.assertRaises(OSError):
                result_output.write_rendered_result(str(output), "new")
            self.assertEqual("old", output.read_text(encoding="utf-8"))
            self.assertFalse(any(path.suffix == ".tmp" for path in Path(folder).iterdir()))

    def test_sql_output_uses_same_receipt_and_keeps_partial_exit(self):
        item = {"ok": False, "status": "partial", "results": [{"ok": True}]}
        envelope = {"schema_version": "gravity-sql.query.v1", "exit_code": 3, "results": [item]}
        with tempfile.TemporaryDirectory() as folder:
            output, stdout = Path(folder) / "sql.json", io.StringIO()
            with contextlib.redirect_stdout(stdout):
                self.assertEqual(3, _emit_query_result(envelope, None, None, str(output)))
            receipt = json.loads(stdout.getvalue())
            self.assertEqual({"ok": True, "status": "written", "output": str(output), "format": "json", "size_bytes": output.stat().st_size}, receipt)
            self.assertEqual("partial", json.loads(output.read_text(encoding="utf-8"))["status"])
