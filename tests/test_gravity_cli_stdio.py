import json, os, subprocess, sys, unittest

from gravity_sdk.errors import error_detail_from_exception, exit_code_for_error


class CliStdioTests(unittest.TestCase):
    def test_gbk_process_emits_utf8_and_classifies_codec_failures_as_local(self):
        script = "from unittest.mock import patch\nfrom gravity_sdk import __main__ as entry\np=patch('gravity_sdk.cli.dispatch_command',return_value={'data':{'list':['Łódź']}});p.start()\nraise SystemExit(entry.main(['--dry-run']))"
        env = {**os.environ, "PYTHONIOENCODING": "gbk"}
        env.pop("PYTHONUTF8", None)
        run = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True)
        self.assertEqual((0, "Łódź"), (run.returncode, json.loads(run.stdout.decode("utf-8"))["data"]["list"][0]))
        error = UnicodeEncodeError("gbk", "Ł", 0, 1, "illegal multibyte sequence")
        detail = error_detail_from_exception(error)
        self.assertEqual(("LOCAL_IO_ERROR", "local", 4), (detail.code, detail.category, exit_code_for_error(error)))
