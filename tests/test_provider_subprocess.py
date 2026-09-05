from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from gravity_insight.external_context_provider import subprocess_context_provider
from gravity_insight import provider_rpc_transport as transport_module
from gravity_insight.provider_rpc_transport import SubprocessProviderTransport
from tests.test_external_context_contracts import provider_descriptor

# Win32 CREATE_SUSPENDED. Named here because subprocess does not define the
# Windows creation flags on POSIX, so tests cannot read it off the module.
CREATE_SUSPENDED = 0x00000004


PROVIDER_SCRIPT = r'''
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import socket

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
    with socket.create_connection(("127.0.0.1", int(sys.argv[2]))) as ready:
        ready.sendall(b"ready")
        ready.recv(1)
elif mode == "tree-timeout":
    marker = Path(sys.argv[2])
    parent_ready = Path(sys.argv[3])
    child_ready = Path(sys.argv[4])
    child = (
        "import socket; from pathlib import Path; "
        "listener=socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(); "
        "Path(r'" + str(child_ready) + "').write_text(str(listener.getsockname()[1]), encoding='ascii'); "
        "listener.accept(); Path(r'" + str(marker) + "').write_text('escaped', encoding='utf-8')"
    )
    subprocess.Popen([sys.executable, "-c", child])
    while not child_ready.exists():
        time.sleep(0.005)
    parent_ready.write_text("ready", encoding="ascii")
    time.sleep(2)
else:
    raise SystemExit(9)
'''


class FakeStream:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, content: bytes) -> None:
        self.writes.append(content)

    def close(self) -> None:
        self.closed = True


class FakeWindowsProcess:
    def __init__(self) -> None:
        self.pid = 4242
        self.returncode: int | None = None
        self.stdin = FakeStream()
        self.stdout = FakeStream()
        self.stderr = FakeStream()

    def poll(self) -> int | None:
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        if self.returncode is None:
            raise AssertionError("fake process was not terminated")
        return self.returncode


class ReadyTransportTimeoutClock:
    def __init__(self, ready: Path) -> None:
        self._ready = ready
        self._worker_calls = 0
        self._harness_deadline = time.monotonic() + 30

    def __call__(self) -> float:
        if not threading.current_thread().name.startswith("gravity-provider-"):
            if time.monotonic() >= self._harness_deadline:
                raise AssertionError("provider worker did not complete timeout path")
            return 0.0
        self._worker_calls += 1
        if self._worker_calls == 1:
            return 0.0
        deadline = time.monotonic() + 30
        while not self._ready.exists():
            if time.monotonic() >= deadline:
                raise AssertionError("subprocess tree did not publish readiness")
            time.sleep(0.005)
        return 1.0

class ProviderSubprocessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.script = self.root / "provider_fixture.py"
        self.script.write_text(PROVIDER_SCRIPT, encoding="utf-8", newline="\n")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def descriptor(self, mode: str, *arguments: str | Path) -> dict:
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
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(30)
        port = str(listener.getsockname()[1])
        descriptor = self.descriptor("wait", port)
        descriptor["rpc"]["timeout_ms"] = 30_000
        descriptor["rpc"]["cancellation_grace_ms"] = 1000
        cancellation = threading.Event()
        provider = subprocess_context_provider(descriptor, work_root=self.root)
        holder: dict[str, dict] = {}
        completed = threading.Event()
        streams_closed = threading.Event()
        processes = []
        launch = SubprocessProviderTransport._launch
        close_streams = transport_module._close_process_streams

        def record_launch(transport, cancellation_grace_ms):
            process = launch(transport, cancellation_grace_ms)
            processes.append(process)
            return process

        def record_stream_close(process):
            try:
                close_streams(process)
            finally:
                streams_closed.set()

        def read() -> None:
            try:
                holder["result"] = provider.read(
                    "provider://team/docs/fact", cancellation=cancellation
                )
            finally:
                completed.set()

        connection = None
        with patch.object(
            SubprocessProviderTransport,
            "_launch",
            autospec=True,
            side_effect=record_launch,
        ), patch.object(
            transport_module,
            "_close_process_streams",
            side_effect=record_stream_close,
        ):
            thread = threading.Thread(target=read)
            thread.start()
            try:
                connection, _address = listener.accept()
                self.assertEqual(b"ready", connection.recv(5))
                cancellation.set()
                self.assertTrue(completed.wait(30))
                thread.join()
                self.assertEqual(
                    ["PROVIDER_RPC_CANCELLED"], holder["result"]["reason_codes"]
                )
                self.assertEqual(1, len(processes))
                self.assertTrue(streams_closed.wait(30))
                for process in processes:
                    self.assertIsNotNone(process.poll())
            finally:
                cancellation.set()
                if connection is not None:
                    try:
                        connection.sendall(b"x")
                    except OSError:
                        pass
                    connection.close()
                listener.close()
                if thread.is_alive():
                    self.assertTrue(completed.wait(30))
                    thread.join()
                if processes:
                    streams_closed.wait(30)

    def test_concurrent_windows_termination_serializes_job_cleanup(self) -> None:
        class BlockingWaitProcess(FakeWindowsProcess):
            def __init__(self) -> None:
                super().__init__()
                self.wait_started = threading.Event()
                self.release_wait = threading.Event()

            def wait(self, timeout: float | None = None) -> int:
                del timeout
                self.wait_started.set()
                if not self.release_wait.wait(30):
                    raise AssertionError("fake process wait was not released")
                self.returncode = -1
                return self.returncode

        class ObservedLock:
            def __init__(self) -> None:
                self._lock = threading.Lock()
                self._attempt_guard = threading.Lock()
                self._attempts = 0
                self.second_attempt = threading.Event()

            def __enter__(self):
                with self._attempt_guard:
                    self._attempts += 1
                    if self._attempts == 2:
                        self.second_attempt.set()
                self._lock.acquire()
                return self

            def __exit__(self, *_args) -> None:
                self._lock.release()

        process = BlockingWaitProcess()
        termination_lock = ObservedLock()
        setattr(
            process,
            transport_module._TERMINATION_LOCK_ATTRIBUTE,
            termination_lock,
        )
        job_available = True
        job_guard = threading.Lock()

        def close_job(_process) -> bool:
            nonlocal job_available
            with job_guard:
                if not job_available:
                    return False
                job_available = False
                return True

        errors = []

        def terminate() -> None:
            try:
                transport_module._terminate_process_tree(process, 1000)
            except BaseException as exc:
                errors.append(exc)

        with (
            patch.object(transport_module.os, "name", "nt"),
            patch.object(
                transport_module,
                "close_windows_job",
                side_effect=close_job,
            ) as close_job_mock,
            patch.object(transport_module.subprocess, "run") as taskkill,
        ):
            first = threading.Thread(target=terminate)
            second = threading.Thread(target=terminate)
            first.start()
            self.assertTrue(process.wait_started.wait(30))
            second.start()
            try:
                self.assertTrue(termination_lock.second_attempt.wait(30))
                self.assertTrue(second.is_alive())
            finally:
                process.release_wait.set()
            first.join(30)
            second.join(30)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual([], errors)
        self.assertEqual(-1, process.poll())
        self.assertEqual(2, close_job_mock.call_count)
        taskkill.assert_not_called()

    def test_timeout_terminates_the_entire_spawned_process_tree(self) -> None:
        escaped = self.root / "child-escaped"
        parent_ready = self.root / "parent-ready"
        child_ready = self.root / "child-ready"
        descriptor = self.descriptor(
            "tree-timeout", escaped, parent_ready, child_ready
        )
        descriptor["rpc"]["timeout_ms"] = 50
        descriptor["rpc"]["cancellation_grace_ms"] = 1000
        descriptor["rpc"]["max_attempts"] = 1
        provider = subprocess_context_provider(
            descriptor,
            work_root=self.root,
            clock=ReadyTransportTimeoutClock(parent_ready),
        )
        result = provider.read("provider://team/docs/fact")

        self.assertEqual(["PROVIDER_RPC_TIMEOUT"], result["reason_codes"])
        port = int(child_ready.read_text(encoding="ascii"))
        # The property under test is that no descendant outlived the kill, not
        # that the kernel has already reclaimed the port. Asserting the port is
        # closed asserts on a race: the listening socket is torn down after the
        # process dies, and in between the backlog still completes a handshake
        # with nobody behind it. Measured on the CI Windows runner, that window
        # is wide enough to fail reproducibly while the descendant is provably
        # gone (escaped_marker=False).
        #
        # Connecting is instead how a survivor is made to reveal itself: the
        # grandchild blocks in accept() and writes `escaped` the moment it
        # returns from one. A connection served from a dead process's backlog
        # leaves no marker, so this distinguishes the two.
        #
        # Do not turn this into a poll that retries create_connection until it
        # raises. The grandchild calls accept() once, so repeated probes fill
        # the backlog; every later connect then hangs to its timeout and raises
        # TimeoutError, which is an OSError. Such a loop reports success whether
        # or not the tree died.
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            reached = True
        except OSError:
            reached = False
        if reached:
            # Only a connection that was actually established can make a
            # survivor reveal itself, so there is nothing to wait for when the
            # port refused us -- refusal already means nothing is in accept().
            deadline = time.monotonic() + 5
            while not escaped.exists() and time.monotonic() < deadline:
                time.sleep(0.05)
        self.assertFalse(
            escaped.exists(),
            f"a descendant survived the kill and accepted on port {port} "
            f"(connect_succeeded={reached})",
        )

    def test_windows_job_binding_failure_is_local_and_reaps_before_rpc(self) -> None:
        process = FakeWindowsProcess()
        descriptor = self.descriptor("success")
        descriptor["rpc"]["max_attempts"] = 2

        def terminate(*_args: object, **_kwargs: object) -> object:
            process.returncode = -1
            return object()

        with (
            patch(
                "gravity_insight.provider_rpc_transport.os",
                type("WindowsOs", (), {"name": "nt", "environ": os.environ})(),
            ),
            patch(
                "gravity_insight.provider_rpc_transport.subprocess.Popen",
                return_value=process,
            ) as launch,
            patch(
                "gravity_insight.provider_rpc_transport.subprocess.run",
                side_effect=terminate,
            ),
            # windows_job_creation_flags() reads provider_windows_job's own os.name,
            # which the WindowsOs proxy above does not reach, so on POSIX it would
            # return 0 and the creationflags assertion below would be vacuous.
            patch(
                "gravity_insight.provider_rpc_transport.windows_job_creation_flags",
                return_value=CREATE_SUSPENDED,
            ),
            patch(
                "gravity_insight.provider_rpc_transport.attach_windows_job",
                return_value=False,
            ),
            patch(
                "gravity_insight.provider_rpc_transport.resume_windows_job_process"
            ) as resume,
            patch(
                "gravity_insight.provider_rpc_transport.close_windows_job",
                return_value=False,
            ),
        ):
            provider = subprocess_context_provider(descriptor, work_root=self.root)
            result = provider.read("provider://team/docs/fact")

        self.assertEqual(
            ["PROVIDER_RPC_ISOLATION_FAILED"], result["reason_codes"]
        )
        self.assertEqual(1, result["enforced_rpc"]["transport_attempts"])
        self.assertEqual(-1, process.poll())
        self.assertEqual([], process.stdin.writes)
        self.assertTrue(
            all(
                stream.closed
                for stream in (process.stdin, process.stdout, process.stderr)
            )
        )
        self.assertEqual(1, launch.call_count)
        self.assertTrue(launch.call_args.kwargs["creationflags"] & 0x00000004)
        resume.assert_not_called()

    def test_windows_binding_precedes_resume_and_non_windows_skips_job(self) -> None:
        transport = SubprocessProviderTransport(
            self.descriptor("success"), work_root=self.root
        )
        process = FakeWindowsProcess()
        events: list[str] = []

        with (
            patch("gravity_insight.provider_rpc_transport.os.name", "nt"),
            patch(
                "gravity_insight.provider_rpc_transport.subprocess.Popen",
                return_value=process,
            ) as windows_launch,
            patch(
                "gravity_insight.provider_rpc_transport.attach_windows_job",
                side_effect=lambda _process: events.append("attach") or True,
            ),
            patch(
                "gravity_insight.provider_rpc_transport.resume_windows_job_process",
                side_effect=lambda _process: events.append("resume") or True,
            ),
        ):
            self.assertIs(process, transport._launch(1000))
        self.assertEqual(["attach", "resume"], events)
        self.assertTrue(
            windows_launch.call_args.kwargs["creationflags"] & 0x00000004
        )

        with (
            patch("gravity_insight.provider_rpc_transport.os.name", "posix"),
            patch(
                "gravity_insight.provider_rpc_transport.subprocess.Popen",
                return_value=process,
            ) as posix_launch,
            patch(
                "gravity_insight.provider_rpc_transport.attach_windows_job"
            ) as attach,
            patch(
                "gravity_insight.provider_rpc_transport.resume_windows_job_process"
            ) as resume,
        ):
            self.assertIs(process, transport._launch(1000))
        self.assertTrue(posix_launch.call_args.kwargs["start_new_session"])
        self.assertNotIn("creationflags", posix_launch.call_args.kwargs)
        attach.assert_not_called()
        resume.assert_not_called()

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
