import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

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

    def test_public_cli_expands_tilde_output_in_a_subprocess(self):
        script = "import sys\nfrom unittest.mock import patch\nfrom gravity_sdk import __main__ as entry\npatch('gravity_sdk.cli.dispatch_command',return_value={'字段':'值'}).start()\npatch('gravity_sdk.__main__.ensure_first_run_credentials',return_value=True).start()\nraise SystemExit(entry.main(['reports','pulse','--app','1','--start','2026-08-01','--end','2026-08-02','--output',sys.argv[1]]))"
        with tempfile.TemporaryDirectory() as folder:
            home, cwd = Path(folder, "用户 目录"), Path(folder, "调用 目录"); home.mkdir(); cwd.mkdir()
            env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "PYTHONIOENCODING": "gbk", "PYTHONUTF8": "0"}
            run = subprocess.run([sys.executable, "-c", script, "~/结果.json"], cwd=cwd, env=env, capture_output=True)
            self.assertEqual(0, run.returncode, run.stderr.decode("utf-8", "replace")); self.assertTrue((home / "结果.json").is_file()); self.assertFalse((cwd / "~").exists())

    def test_concurrent_output_has_one_explicit_local_failure(self):
        script = "import sys,tempfile,time\nfrom pathlib import Path\nfrom unittest.mock import patch\nfrom gravity_sdk import __main__ as entry\ndef slow(handle,value):time.sleep(.5);return handle.file.write(value)\npatch.object(tempfile._TemporaryFileWrapper,'write',slow,create=True).start()\nwhile not Path(sys.argv[2]).exists():time.sleep(.001)\npatch('gravity_sdk.cli.dispatch_command',return_value={'marker':sys.argv[3]*100}).start()\npatch('gravity_sdk.__main__.ensure_first_run_credentials',return_value=True).start()\nraise SystemExit(entry.main(['reports','pulse','--app','1','--start','2026-08-01','--end','2026-08-02','--output',sys.argv[1]]))"
        with tempfile.TemporaryDirectory() as folder:
            output, gate = Path(folder, "result.json"), Path(folder, "go"); env = dict(os.environ)
            runs = [subprocess.Popen([sys.executable, "-c", script, str(output), str(gate), marker], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for marker in "AB"]
            gate.write_text("go", encoding="ascii"); streams = [run.communicate(timeout=30) for run in runs]
            self.assertEqual([0, 4], sorted(run.returncode for run in runs)); failure = json.loads(next(stderr for run, (_, stderr) in zip(runs, streams) if run.returncode == 4).decode("utf-8")); self.assertEqual(("LOCAL_IO_ERROR", "local"), (failure["error"]["code"], failure["error"]["category"]))

    def test_missing_profile_roots_is_structured_local_error(self):
        env = {**os.environ, "PYTHONIOENCODING": "gbk", "PYTHONUTF8": "0", "LC_ALL": "C"}
        for name in ("HOME", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "XDG_CACHE_HOME", "GRAVITY_CACHE_HOME"): env.pop(name, None)
        commands = ([sys.executable, "-m", "gravity_sdk", "--dry-run"], [sys.executable, "-c", "from gravity_sdk.cli_stdio import insight_main;raise SystemExit(insight_main())"], [sys.executable, "-c", "from gravity_sdk.cli_stdio import sql_main;raise SystemExit(sql_main())"])
        for command in commands:
            run = subprocess.run(command, env=env, capture_output=True); payload = json.loads(run.stderr.decode("utf-8"))
            self.assertEqual((4, "LOCAL_IO_ERROR", "local"), (run.returncode, payload["error"]["code"], payload["error"]["category"])); self.assertIn("GRAVITY_CACHE_HOME", payload["error"]["next_action"])
