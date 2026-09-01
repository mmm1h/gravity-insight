"""Injected callable and bounded local subprocess Provider transports."""

from __future__ import annotations

import copy
import json
import os
import re
import signal
import stat
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol

from .external_context_contract import compile_external_provider
from .provider_windows_job import (
    attach_windows_job,
    close_windows_job,
    resume_windows_job_process,
    windows_job_creation_flags,
)


ProviderHandler = Callable[[Mapping[str, Any], threading.Event], Mapping[str, Any] | bytes]
ProviderCancel = Callable[[str], None]
_ENVIRONMENT_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SAFE_AMBIENT_KEYS = (
    "SystemRoot",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TEMP",
    "TMP",
    "LANG",
    "LC_ALL",
)
_STDERR_LIMIT = 64 * 1024
_TERMINATION_LOCK_ATTRIBUTE = "_gravity_provider_termination_lock"
_TERMINATION_LOCK_CREATION_GUARD = threading.Lock()


class ProviderTransportError(RuntimeError):
    """A Provider failed at the guarded transport boundary."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _json_pointer(value: Any, pointer: str) -> Any:
    selected = value
    for encoded in pointer.split("/")[1:]:
        part = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(selected, Mapping):
            selected = selected[part]
        elif isinstance(selected, list) and part.isdigit():
            selected = selected[int(part)]
        else:
            raise TypeError("JSON Pointer does not match command output")
    return selected


class ProviderTransport(Protocol):
    kind: str

    def invoke(
        self,
        request: Mapping[str, Any],
        request_bytes: bytes,
        *,
        timeout_ms: int,
        max_output_bytes: int,
        cancellation_grace_ms: int,
        cancel_event: threading.Event,
    ) -> bytes: ...

    def cancel(self, request_id: str, *, grace_ms: int) -> None: ...


class CallableProviderTransport:
    """Explicit Host/MCP client seam; no discovery or network client is created."""

    def __init__(
        self,
        kind: str,
        handler: ProviderHandler,
        *,
        cancel: ProviderCancel | None = None,
    ) -> None:
        if kind not in {"mcp", "host"} or not callable(handler):
            raise ValueError("Callable Provider transport must be mcp or host")
        if cancel is not None and not callable(cancel):
            raise ValueError("Provider cancel handler must be callable")
        self.kind = kind
        self._handler = handler
        self._cancel = cancel

    def invoke(
        self,
        request: Mapping[str, Any],
        request_bytes: bytes,
        *,
        timeout_ms: int,
        max_output_bytes: int,
        cancellation_grace_ms: int,
        cancel_event: threading.Event,
    ) -> bytes:
        del request_bytes, timeout_ms, cancellation_grace_ms
        try:
            result = self._handler(copy.deepcopy(dict(request)), cancel_event)
        except ProviderTransportError:
            raise
        except Exception as exc:
            raise ProviderTransportError(
                "PROVIDER_RPC_UNAVAILABLE", "Callable Provider failed before a response"
            ) from exc
        if isinstance(result, Mapping):
            try:
                content = json.dumps(
                    result,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            except (TypeError, ValueError) as exc:
                raise ProviderTransportError(
                    "PROVIDER_RPC_MALFORMED", "Callable Provider returned invalid JSON"
                ) from exc
        elif isinstance(result, bytes):
            content = result
        else:
            raise ProviderTransportError(
                "PROVIDER_RPC_MALFORMED", "Callable Provider returned unsupported output"
            )
        if len(content) > max_output_bytes:
            raise ProviderTransportError(
                "PROVIDER_RPC_OUTPUT_LIMIT", "Callable Provider exceeded output budget"
            )
        return content

    def cancel(self, request_id: str, *, grace_ms: int) -> None:
        del grace_ms
        if self._cancel is None:
            return
        try:
            self._cancel(request_id)
        except Exception:
            return


class SubprocessProviderTransport:
    """One-request-per-process JSON transport with bounded streams and tree kill."""

    kind = "subprocess"

    def __init__(
        self,
        descriptor: Mapping[str, Any],
        *,
        work_root: str | Path,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        contract = compile_external_provider(descriptor)["contract"]
        if contract["transport"] != self.kind:
            raise ValueError("Subprocess transport requires a subprocess descriptor")
        binding = contract["deployment"]["subprocess"]
        if not isinstance(binding, Mapping):
            raise ValueError("Subprocess Provider binding is missing")
        if binding.get("protocol", "provider_rpc") != "provider_rpc":
            raise ValueError("Command Provider requires the command transport")
        root = _real_directory(Path(work_root), "Provider work root")
        working = _real_directory(Path(binding["working_directory"]), "Provider cwd")
        try:
            working.relative_to(root)
        except ValueError as exc:
            raise ValueError("Provider cwd escapes its work root") from exc
        executable = _real_executable(Path(binding["executable"]))
        for argument in binding["arguments"]:
            _validate_argument_path(str(argument), root)
        self._command = [str(executable), *binding["arguments"]]
        self._working_directory = working
        self._environment = _sanitized_environment(environment)
        self._processes: dict[str, subprocess.Popen[bytes]] = {}
        self._guard = threading.Lock()

    def invoke(
        self,
        request: Mapping[str, Any],
        request_bytes: bytes,
        *,
        timeout_ms: int,
        max_output_bytes: int,
        cancellation_grace_ms: int,
        cancel_event: threading.Event,
    ) -> bytes:
        request_id = str(request["request_id"])
        process = self._launch(cancellation_grace_ms)
        with self._guard:
            self._processes[request_id] = process
        capture = _start_capture(process, max_output_bytes)
        try:
            _write_request(process, request_bytes)
            reason = _monitor_process(
                process,
                capture["exceeded"],
                cancel_event,
                timeout_ms=timeout_ms,
            )
            if reason is not None:
                _terminate_process_tree(process, cancellation_grace_ms)
            _join_capture(capture, process, cancellation_grace_ms)
            return _validated_process_output(
                process,
                capture,
                reason=reason,
                maximum=max_output_bytes,
            )
        except ProviderTransportError:
            raise
        except (OSError, ValueError) as exc:
            _terminate_process_tree(process, cancellation_grace_ms)
            raise ProviderTransportError(
                "PROVIDER_RPC_UNAVAILABLE", "Provider process I/O failed"
            ) from exc
        finally:
            with self._guard:
                self._processes.pop(request_id, None)
            _close_process_streams(process)

    def _launch(self, cancellation_grace_ms: int) -> subprocess.Popen[bytes]:
        return _launch_subprocess(
            self._command, self._working_directory, self._environment,
            cancellation_grace_ms,
        )

    def cancel(self, request_id: str, *, grace_ms: int) -> None:
        with self._guard:
            process = self._processes.get(request_id)
        if process is not None:
            _terminate_process_tree(process, grace_ms)


def _launch_subprocess(command: list[str], working_directory: Path, environment: Mapping[str, str], grace_ms: int) -> subprocess.Popen[bytes]:
    flags: dict[str, Any] = {"start_new_session": True}
    if os.name == "nt":
        flags = {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | windows_job_creation_flags()}
    try:
        process = subprocess.Popen(command, cwd=working_directory, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, **flags)
        if os.name == "nt" and not _bind_windows_isolation(process, grace_ms):
            raise ProviderTransportError("PROVIDER_RPC_ISOLATION_FAILED", "Provider process isolation could not be established")
        return process
    except OSError as exc:
        raise ProviderTransportError("PROVIDER_RPC_UNAVAILABLE", "Provider process could not start") from exc


def _start_capture(
    process: subprocess.Popen[bytes], maximum: int
) -> dict[str, Any]:
    stdout = bytearray()
    stderr = bytearray()
    exceeded = threading.Event()
    readers = [
        threading.Thread(
            target=_read_stream,
            args=(process.stdout, stdout, maximum, exceeded),
            daemon=True,
            name="gravity-provider-stdout",
        ),
        threading.Thread(
            target=_read_stream,
            args=(process.stderr, stderr, _STDERR_LIMIT, exceeded),
            daemon=True,
            name="gravity-provider-stderr",
        ),
    ]
    for reader in readers:
        reader.start()
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exceeded": exceeded,
        "readers": readers,
    }


def _write_request(process: subprocess.Popen[bytes], content: bytes) -> None:
    if process.stdin is None:
        raise OSError("Provider stdin is unavailable")
    process.stdin.write(content)
    process.stdin.close()


def _monitor_process(
    process: subprocess.Popen[bytes],
    output_limit: threading.Event,
    cancel_event: threading.Event,
    *,
    timeout_ms: int,
) -> str | None:
    deadline = time.monotonic() + timeout_ms / 1000
    while process.poll() is None:
        if cancel_event.is_set():
            return "PROVIDER_RPC_CANCELLED"
        if output_limit.is_set():
            return "PROVIDER_RPC_OUTPUT_LIMIT"
        if time.monotonic() >= deadline:
            return "PROVIDER_RPC_TIMEOUT"
        time.sleep(0.005)
    return None


def _join_capture(
    capture: Mapping[str, Any],
    process: subprocess.Popen[bytes],
    grace_ms: int,
) -> None:
    readers = capture["readers"]
    for reader in readers:
        reader.join(timeout=max(0.1, grace_ms / 1000 + 0.1))
    if any(reader.is_alive() for reader in readers):
        _terminate_process_tree(process, grace_ms)
        raise ProviderTransportError(
            "PROVIDER_RPC_UNAVAILABLE", "Provider process streams did not close"
        )


def _validated_process_output(
    process: subprocess.Popen[bytes],
    capture: Mapping[str, Any],
    *,
    reason: str | None,
    maximum: int,
) -> bytes:
    if reason is not None:
        raise ProviderTransportError(reason, "Provider process did not complete safely")
    stdout = capture["stdout"]
    if capture["exceeded"].is_set() or len(stdout) > maximum:
        raise ProviderTransportError(
            "PROVIDER_RPC_OUTPUT_LIMIT", "Provider process exceeded output budget"
        )
    if process.returncode != 0:
        raise ProviderTransportError("PROVIDER_RPC_UNAVAILABLE", "Provider process failed")
    return bytes(stdout)


def _close_process_streams(process: subprocess.Popen[bytes]) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
    close_windows_job(process)


def _bind_windows_isolation(
    process: subprocess.Popen[bytes], grace_ms: int
) -> bool:
    if attach_windows_job(process) and resume_windows_job_process(process):
        return True
    _terminate_process_tree(process, grace_ms)
    _close_process_streams(process)
    return False


def _read_stream(
    stream: Any,
    target: bytearray,
    maximum: int,
    exceeded: threading.Event,
) -> None:
    if stream is None:
        return
    try:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                return
            remaining = maximum + 1 - len(target)
            if remaining > 0:
                target.extend(chunk[:remaining])
            if len(target) > maximum or len(chunk) > remaining:
                exceeded.set()
                return
    except OSError:
        return


def _terminate_process_tree(process: subprocess.Popen[bytes], grace_ms: int) -> None:
    with _process_termination_lock(process):
        _terminate_process_tree_locked(process, grace_ms)


def _process_termination_lock(process: subprocess.Popen[bytes]) -> Any:
    with _TERMINATION_LOCK_CREATION_GUARD:
        guard = getattr(process, _TERMINATION_LOCK_ATTRIBUTE, None)
        if guard is None:
            guard = threading.Lock()
            setattr(process, _TERMINATION_LOCK_ATTRIBUTE, guard)
        return guard


def _terminate_process_tree_locked(
    process: subprocess.Popen[bytes], grace_ms: int
) -> None:
    if process.poll() is not None:
        close_windows_job(process)
        return
    grace = max(0.25 if os.name == "nt" else 0.05, grace_ms / 1000)
    if os.name == "nt" and close_windows_job(process):
        _wait_after_job_close(process, grace)
        return
    try:
        if os.name == "nt":
            system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
            taskkill = system_root / "System32" / "taskkill.exe"
            subprocess.run(
                [str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                check=False,
                capture_output=True,
                timeout=grace,
            )
        else:
            os.killpg(process.pid, signal.SIGTERM)
    except (OSError, subprocess.SubprocessError):
        try:
            process.terminate()
        except OSError:
            pass
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            return


def _wait_after_job_close(process: subprocess.Popen[bytes], grace: float) -> None:
    try:
        process.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            return
        try:
            process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            return


def _real_directory(path: Path, label: str) -> Path:
    supplied = path.absolute()
    _assert_unlinked(supplied, label)
    selected = supplied.resolve()
    if not selected.is_dir():
        raise ValueError(f"{label} is not a directory")
    return selected


def _real_executable(path: Path) -> Path:
    supplied = path.absolute()
    _assert_unlinked(supplied, "Provider executable")
    selected = supplied.resolve()
    try:
        metadata = selected.lstat()
    except OSError as exc:
        raise ValueError("Provider executable is unavailable") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or not selected.is_file()
    ):
        raise ValueError("Provider executable is not a regular file")
    return selected


def _validate_argument_path(value: str, root: Path) -> None:
    normalized = value.replace("\\", "/")
    if "/../" in f"/{normalized}/" or normalized.startswith("../"):
        raise ValueError("Provider argument path escapes its work root")
    candidate = Path(value)
    if not candidate.is_absolute():
        return
    supplied = candidate.absolute()
    try:
        supplied.relative_to(root)
    except ValueError as exc:
        raise ValueError("Provider argument path escapes its work root") from exc
    _assert_unlinked(supplied, "Provider argument path")


def _assert_unlinked(path: Path, label: str) -> None:
    for candidate in (path, *path.parents):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise ValueError(f"{label} is unavailable") from exc
        attributes = getattr(metadata, "st_file_attributes", 0)
        reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        if stat.S_ISLNK(metadata.st_mode) or bool(attributes & reparse):
            raise ValueError(f"{label} contains a link or reparse point")


def _sanitized_environment(explicit: Mapping[str, str] | None) -> dict[str, str]:
    result = {
        key: os.environ[key]
        for key in _SAFE_AMBIENT_KEYS
        if key in os.environ and not key.upper().startswith("GRAVITY_")
    }
    result.update({"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
    if explicit is None:
        return result
    if not isinstance(explicit, Mapping) or len(explicit) > 64:
        raise ValueError("Provider environment is invalid")
    for key, value in explicit.items():
        if (
            not isinstance(key, str)
            or _ENVIRONMENT_KEY.fullmatch(key) is None
            or key.upper().startswith("GRAVITY_")
            or not isinstance(value, str)
            or len(value) > 4096
            or "\x00" in value
        ):
            raise ValueError("Provider environment contains a forbidden entry")
        result[key] = value
    return result


__all__ = [
    "CallableProviderTransport",
    "ProviderTransport",
    "ProviderTransportError",
    "SubprocessProviderTransport",
]
