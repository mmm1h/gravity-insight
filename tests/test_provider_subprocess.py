from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from gravity_sdk.external_context_provider import subprocess_context_provider
from gravity_sdk.provider_rpc_transport import SubprocessProviderTransport
from tests.test_external_context_contracts import provider_descriptor


PROVIDER_SCRIPT = r'''
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
mode = sys.argv[1]

def emit(content):
    resource = {
        "uri": "provider://team/docs/fact",
        "title": "Fixture fact",
        "resource_type": "document",
        "source_revision": "fixture-1",
        "item_id": "fixture-fact",
        "fact_id": "fact.fixture",
        "entity_refs": ["entity://gravity/app@1"],
        "valid_time": {"start": None, "end": None, "timezone": "Asia/Shanghai"},
        "effective_range": {"start": None, "end": None},
        "observed_at": "2026-08-22T00:00:00Z",
        "authority": "canonical",
        "freshness": "current",
        "supersedes": [],
        "sensitivity": "internal",
        "citation": {
            "path": "fixture/resource",
            "line_start": 1,
            "line_end": max(1, len(content.splitlines())),
        },
        "content": content,
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
    response = {
        "schema_version": "gravity.provider-rpc-response.v1",
        "request_id": request["request_id"],
        "status": "success",
        "resources": [resource],
        "next_cursor": None,
        "stats": {"internal_requests": 1, "retries": 0, "cache_hits": 0},
    }
    sys.stdout.write(json.dumps(response, sort_keys=True, separators=(",", ":")))
    sys.stdout.flush()

if mode == "success":
    emit("Subprocess fact.")
elif mode == "environment":
    emit(json.dumps({
        "gravity_present": any(key.startswith("GRAVITY_") for key in os.environ),
        "provider_explicit": os.environ.get("PROVIDER_TOKEN") == "provider-secret",
    }, sort_keys=True))
elif mode == "malformed":
    sys.stdout.write("not-json")
    sys.stdout.flush()
elif mode == "output-bomb":
    sys.stdout.buffer.write(b"x" * 131072)
    sys.stdout.buffer.flush()
    time.sleep(2)
elif mode == "failure":
    sys.stderr.write("private-provider-secret")
    sys.stderr.flush()
    raise SystemExit(7)
elif mode == "wait":
    ready, done = Path(sys.argv[2]), Path(sys.argv[3])
    ready.write_text("ready", encoding="utf-8")
    time.sleep(1)
    done.write_text("done", encoding="utf-8")
elif mode == "tree-timeout":
    marker = Path(sys.argv[2])
    child = "import time; from pathlib import Path; time.sleep(0.4); Path(r'" + str(marker) + "').write_text('escaped', encoding='utf-8')"
    subprocess.Popen([sys.executable, "-c", child])
    time.sleep(2)
else:
    raise SystemExit(9)
'''


class ProviderSubprocessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.script = self.root / "provider_fixture.py"
        self.script.write_text(PROVIDER_SCRIPT, encoding="utf-8", newline="\n")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def descriptor(self, mode: str, *arguments: Path) -> dict:
        binding = {
            "executable": str(Path(sys.executable).resolve()),
            "arguments": [str(self.script), mode, *(str(item) for item in arguments)],
            "working_directory": str(self.root),
        }
        return provider_descriptor(
            transport="subprocess", subprocess_binding=binding
        )

    def test_success_loads_one_context_item_through_exact_process_binding(self) -> None:
        provider = subprocess_context_provider(
            self.descriptor("success"), work_root=self.root
        )
        result = provider.read("provider://team/docs/fact")
        description = provider.describe()

        self.assertTrue(result["ok"])
        self.assertEqual("Subprocess fact.", result["context_items"][0]["content"])
        self.assertEqual("data", result["context_items"][0]["role"])
        self.assertEqual(1, result["enforced_rpc"]["transport_attempts"])
        self.assertEqual(1, result["provider_reported"]["internal_requests"])
        self.assertFalse(result["provider_reported"]["enforced"])
        self.assertTrue(
            description["provider"]["deployment"]["subprocess_configured"]
        )
        self.assertEqual(
            2, description["provider"]["deployment"]["subprocess_argument_count"]
        )
        self.assertNotIn(str(self.root), json.dumps(description))
        self.assertNotIn(str(self.script), json.dumps(description))

    def test_environment_is_sanitized_but_explicit_provider_values_are_available(self) -> None:
        with patch.dict(
            os.environ,
            {
                "GRAVITY_AUTH_TOKEN": "must-not-cross",
                "GRAVITY_PASSWORD": "must-not-cross",
            },
        ):
            provider = subprocess_context_provider(
                self.descriptor("environment"),
                work_root=self.root,
                environment={"PROVIDER_TOKEN": "provider-secret"},
            )
            result = provider.read("provider://team/docs/fact")
        observed = json.loads(result["context_items"][0]["content"])
        self.assertFalse(observed["gravity_present"])
        self.assertTrue(observed["provider_explicit"])
        self.assertNotIn("must-not-cross", json.dumps(result))
        self.assertNotIn("provider-secret", json.dumps(result))

        with self.assertRaisesRegex(ValueError, "forbidden entry"):
            SubprocessProviderTransport(
                self.descriptor("success"),
                work_root=self.root,
                environment={"GRAVITY_AUTH_TOKEN": "forbidden"},
            )

    def test_nonzero_exit_malformed_and_output_bomb_are_stable_private_gaps(self) -> None:
        cases = (
            ("failure", "PROVIDER_RPC_UNAVAILABLE"),
            ("malformed", "PROVIDER_RPC_MALFORMED"),
            ("output-bomb", "PROVIDER_RPC_OUTPUT_LIMIT"),
        )
        for mode, reason in cases:
            descriptor = self.descriptor(mode)
            descriptor["rpc"]["max_attempts"] = 1
            if mode == "output-bomb":
                descriptor["rpc"]["max_output_bytes"] = 1024
                descriptor["rpc"]["max_output_tokens"] = 1024
            with self.subTest(mode=mode):
                provider = subprocess_context_provider(
                    descriptor, work_root=self.root
                )
                result = provider.read("provider://team/docs/fact")
                self.assertEqual([reason], result["reason_codes"])
                self.assertNotIn("private-provider-secret", json.dumps(result))

    def test_cancellation_terminates_the_fixture_before_it_can_finish(self) -> None:
        ready = self.root / "ready"
        done = self.root / "done"
        descriptor = self.descriptor("wait", ready, done)
        descriptor["rpc"]["timeout_ms"] = 2000
        descriptor["rpc"]["cancellation_grace_ms"] = 1000
        cancellation = threading.Event()
        provider = subprocess_context_provider(descriptor, work_root=self.root)
        holder: dict[str, dict] = {}
        thread = threading.Thread(
            target=lambda: holder.setdefault(
                "result",
                provider.read(
                    "provider://team/docs/fact", cancellation=cancellation
                ),
            )
        )
        thread.start()
        deadline = time.monotonic() + 1
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(ready.exists())
        cancellation.set()
        thread.join(timeout=2)

        self.assertFalse(thread.is_alive())
        self.assertEqual(
            ["PROVIDER_RPC_CANCELLED"], holder["result"]["reason_codes"]
        )
        time.sleep(1.1)
        self.assertFalse(done.exists())

    def test_timeout_terminates_the_entire_spawned_process_tree(self) -> None:
        escaped = self.root / "child-escaped"
        descriptor = self.descriptor("tree-timeout", escaped)
        descriptor["rpc"]["timeout_ms"] = 50
        descriptor["rpc"]["cancellation_grace_ms"] = 1000
        descriptor["rpc"]["max_attempts"] = 1
        provider = subprocess_context_provider(descriptor, work_root=self.root)
        started = time.monotonic()
        result = provider.read("provider://team/docs/fact")
        elapsed = time.monotonic() - started

        self.assertEqual(["PROVIDER_RPC_TIMEOUT"], result["reason_codes"])
        self.assertLess(elapsed, 1.5)
        time.sleep(0.6)
        self.assertFalse(escaped.exists())

    def test_work_root_and_cwd_reject_escape_and_links(self) -> None:
        outside = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: outside.rmdir() if outside.exists() else None)
        escaped = self.descriptor("success")
        escaped["deployment"]["subprocess"]["working_directory"] = str(outside)
        with self.assertRaisesRegex(ValueError, "escapes"):
            SubprocessProviderTransport(escaped, work_root=self.root)

        linked = self.root / "linked"
        try:
            linked.symlink_to(outside, target_is_directory=True)
        except OSError as exc:
            self.skipTest(f"directory symlinks unavailable: {exc}")
        linked_descriptor = self.descriptor("success")
        linked_descriptor["deployment"]["subprocess"]["working_directory"] = str(
            linked
        )
        with self.assertRaisesRegex(ValueError, "link or reparse"):
            SubprocessProviderTransport(linked_descriptor, work_root=self.root)

        argument_escape = self.descriptor("success")
        argument_escape["deployment"]["subprocess"]["arguments"][0] = str(
            outside / "provider.py"
        )
        with self.assertRaisesRegex(ValueError, "argument path escapes"):
            SubprocessProviderTransport(argument_escape, work_root=self.root)


if __name__ == "__main__":
    unittest.main()
