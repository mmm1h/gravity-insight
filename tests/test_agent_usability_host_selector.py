from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "scripts" / "agent_usability_host_selector.py"
if str(PLUGIN.parent) not in sys.path:
    sys.path.insert(0, str(PLUGIN.parent))


def _request() -> dict:
    return {
        "schema_version": "gravity.agent-external-selector-request.v1",
        "catalog": {
            "capabilities": [{
                "selector": "composite:business_pulse",
                "source": "composite",
                "name": "business pulse",
            }],
            "categories": [],
        },
        "questions": [{"id": "q-0001", "query": "业务脉搏 — café"}],
    }


class HostSelectorPluginTests(unittest.TestCase):
    def test_recanonicalize_matches_parent_utf8_hash_and_covers_gbk_crash(self) -> None:
        from agent_usability_host_selector import _request_sha256

        request = _request()
        text = json.dumps(
            request, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        self.assertEqual(
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
            _request_sha256(request),
        )
        garbled = text.encode("utf-8").decode("gbk", errors="surrogateescape")
        with self.assertRaises(UnicodeEncodeError):
            json.dumps(
                json.loads(garbled),
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")

    def test_missing_credentials_fail_after_canonicalize(self) -> None:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        env.pop("ANTHROPIC_BASE_URL", None)
        payload = json.dumps(
            _request(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        completed = subprocess.run(
            [sys.executable, str(PLUGIN)],
            input=payload,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            check=False,
        )
        self.assertNotEqual(0, completed.returncode)
        self.assertIn("ANTHROPIC_AUTH_TOKEN", completed.stderr)

    def test_live_path_rejects_unknown_selector_instead_of_abstaining(self) -> None:
        from agent_usability_host_selector import _normalize_results

        with self.assertRaisesRegex(SystemExit, "unknown selectors"):
            _normalize_results(
                [{"id": "q-0001", "selectors": ["not-in-catalog"], "reason": ""}],
                ["q-0001"],
                frozenset({"composite:business_pulse"}),
            )
