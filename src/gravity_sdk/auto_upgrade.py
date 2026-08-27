"""Bounded startup upgrades from exact Gravity Insight PyPI versions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, TextIO

import requests

from . import __version__
from ._auto_upgrade_state import (
    UpdateStateBusy,
    UpdateStateError,
    build_update_state,
    format_timestamp,
    hold_update_lease,
    optional_text,
    optional_timestamp,
    read_update_state,
    success_is_recent,
    utc,
    valid_etag,
    version_tuple,
    write_update_state,
)
from .receipt import DISTRIBUTION_HTTP_KIND, perform_http_request
from .runtime_scope import gravity_insight_cache_root


AUTO_UPGRADE_ENV = "GRAVITY_SDK_AUTO_UPGRADE"
PINNED_VERSION_ENV = "GRAVITY_SDK_PINNED_VERSION"
UPDATE_CHECK_INTERVAL = timedelta(hours=24)
UPDATE_STATE_FILENAME = "update-check.json"
UPGRADE_RESTART_EXIT_CODE = 75
TERMINAL_UPGRADE_STATUSES = frozenset({"verification_failed", "restart_failed"})

_REEXEC_ENV = "GRAVITY_SDK_UPGRADE_REEXEC"
_DISTRIBUTION_NAME = "gravity-insight"
_PYPI_JSON_URL = "https://pypi.org/pypi/gravity-insight/json"
_PYPI_INDEX_URL = "https://pypi.org/simple"


@dataclass(frozen=True)
class UpdateCheck:
    status: str
    latest_version: str | None = None
    detail: str | None = None
    state: Mapping[str, Any] | None = None


def update_state_path() -> Path:
    """Return the one machine-wide, principal-independent update state file."""

    return gravity_insight_cache_root() / UPDATE_STATE_FILENAME


def startup_update_enabled(
    argv: Sequence[str], *, environ: Mapping[str, str] | None = None
) -> bool:
    """Keep diagnostic, evaluation, test, pinned, and re-exec paths offline."""

    env = os.environ if environ is None else environ
    args = list(argv)
    if args[:1] == ["doctor"] or args[:2] == ["insight", "doctor"]:
        return False
    if str(env.get(PINNED_VERSION_ENV, "")).strip():
        return False
    if env.get(_REEXEC_ENV) == "1":
        return False
    return str(env.get(AUTO_UPGRADE_ENV, "1")).strip().casefold() not in {
        "0",
        "false",
        "no",
        "off",
    }


def maybe_auto_upgrade(
    argv: Sequence[str],
    *,
    environ: Mapping[str, str] | None = None,
    state_path: Path | None = None,
    now: datetime | None = None,
    request: Callable[[Mapping[str, str]], Any] | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    execv: Callable[[str, list[str]], Any] | None = None,
    stderr: TextIO | None = None,
) -> UpdateCheck:
    """Check, upgrade with pip, and replace this process before command work."""

    env = os.environ if environ is None else environ
    if not startup_update_enabled(argv, environ=env):
        return UpdateCheck("disabled")
    output = sys.stderr if stderr is None else stderr
    selected_now = utc(now)
    path = update_state_path() if state_path is None else Path(state_path)
    checked = _safe_check(state_path=path, now=selected_now, request=request)
    if checked.status == "failed":
        _warn_check_failure(checked, output)
        return checked
    version = checked.latest_version
    if checked.status not in {"checked", "not_modified"} or version is None or not _is_newer(
        version, __version__
    ):
        return checked

    attempted = _safe_record_attempt(path, version, selected_now)
    if attempted.status == "failed":
        _warn_check_failure(attempted, output)
        return attempted
    if attempted.status != "attempt_due":
        return attempted

    failure = _pip_upgrade(version, run)
    if failure is not None:
        print(
            f"warning: Gravity SDK auto-upgrade to {version} failed; continuing with "
            f"version {__version__} ({failure}).",
            file=output,
        )
        return UpdateCheck("upgrade_failed", latest_version=version, detail=failure)

    verification_failure = _verify_installed_version(version, run)
    if verification_failure is not None:
        print(
            f"error: pip reported a successful Gravity SDK upgrade to {version}, but "
            f"the installed version could not be verified ({verification_failure}). "
            "This command was not run; rerun it once.",
            file=output,
        )
        return UpdateCheck(
            "verification_failed",
            latest_version=version,
            detail=verification_failure,
        )
    return _restart(argv, version, execv=execv, output=output)


def _safe_check(
    *,
    state_path: Path,
    now: datetime,
    request: Callable[[Mapping[str, str]], Any] | None,
) -> UpdateCheck:
    try:
        return check_latest_version(state_path=state_path, now=now, request=request)
    except Exception:
        return UpdateCheck("failed", detail="local update-check state is unavailable")


def _safe_record_attempt(path: Path, version: str, now: datetime) -> UpdateCheck:
    try:
        return _record_upgrade_attempt(path, version, now)
    except Exception:
        return UpdateCheck("failed", detail="local update-attempt state is unavailable")


def _warn_check_failure(checked: UpdateCheck, output: TextIO) -> None:
    print(
        "warning: Gravity SDK update check failed; continuing with "
        f"version {__version__} ({checked.detail}).",
        file=output,
    )


def _pip_upgrade(
    version: str,
    run: Callable[..., subprocess.CompletedProcess[str]] | None,
) -> str | None:
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--isolated",
        "--disable-pip-version-check",
        "--no-input",
        "--no-cache-dir",
        "--upgrade",
        "--only-binary=:all:",
        "--index-url",
        _PYPI_INDEX_URL,
        f"{_DISTRIBUTION_NAME}=={version}",
    ]
    installed = _run_subprocess(command, run, timeout=300)
    if installed is None or installed.returncode != 0:
        return (
            "pip could not be started"
            if installed is None
            else f"pip exited with code {installed.returncode}"
        )
    return None


def _verify_installed_version(
    expected: str,
    run: Callable[..., subprocess.CompletedProcess[str]] | None,
) -> str | None:
    probe = (
        "from importlib.metadata import version; "
        f"print(version({_DISTRIBUTION_NAME!r}))"
    )
    checked = _run_subprocess([sys.executable, "-c", probe], run, timeout=30)
    if checked is None or checked.returncode != 0:
        return (
            "the fresh interpreter could not be started"
            if checked is None
            else f"the fresh interpreter exited with code {checked.returncode}"
        )
    actual = str(checked.stdout or "").strip()
    if actual != expected:
        return f"the fresh interpreter reported version {actual or 'unknown'}"
    return None


def _run_subprocess(
    command: list[str],
    run: Callable[..., subprocess.CompletedProcess[str]] | None,
    *,
    timeout: int,
) -> subprocess.CompletedProcess[str] | None:
    runner = subprocess.run if run is None else run
    try:
        return runner(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _restart(
    argv: Sequence[str],
    version: str,
    *,
    execv: Callable[[str, list[str]], Any] | None,
    output: TextIO,
) -> UpdateCheck:
    print(
        f"Gravity SDK upgraded from {__version__} to {version}; restarting this command.",
        file=output,
    )
    replacement = [sys.executable, "-m", "gravity_sdk", *argv]
    replace = os.execv if execv is None else execv
    previous = os.environ.get(_REEXEC_ENV)
    os.environ[_REEXEC_ENV] = "1"
    try:
        replace(sys.executable, replacement)
    except OSError as exc:
        detail = f"process replacement failed: {exc}"
    else:
        detail = "process replacement returned unexpectedly"
    finally:
        if previous is None:
            os.environ.pop(_REEXEC_ENV, None)
        else:
            os.environ[_REEXEC_ENV] = previous
    print(
        f"error: Gravity SDK was upgraded to {version}, but the fresh process did not "
        f"start ({detail}). This command was not run; rerun it once.",
        file=output,
    )
    return UpdateCheck("restart_failed", latest_version=version, detail=detail)


def check_latest_version(
    *,
    state_path: Path | None = None,
    now: datetime | None = None,
    request: Callable[[Mapping[str, str]], Any] | None = None,
) -> UpdateCheck:
    """Query PyPI while holding a short lease and cache only successful checks."""

    selected_now = utc(now)
    path = update_state_path() if state_path is None else Path(state_path)
    try:
        with hold_update_lease(path, selected_now):
            return _check_under_lease(path, selected_now, request)
    except UpdateStateBusy:
        return UpdateCheck("busy")
    except UpdateStateError as exc:
        return UpdateCheck("failed", detail=str(exc))


def _check_under_lease(
    path: Path,
    now: datetime,
    request: Callable[[Mapping[str, str]], Any] | None,
) -> UpdateCheck:
    state = read_update_state(path)
    if state is not None and success_is_recent(state, now, UPDATE_CHECK_INTERVAL):
        return UpdateCheck("cached")
    previous = state or build_update_state(
        successful_checked_at=None,
        etag=None,
        latest_version=None,
        attempted_version=None,
        attempted_at=None,
    )
    transport = _distribution_get if request is None else request
    try:
        response = transport(_distribution_headers(previous))
    except Exception:
        return UpdateCheck("failed", detail="PyPI release source is unavailable")
    converted = _response_state(response, previous, now)
    if isinstance(converted, UpdateCheck):
        return converted
    status, refreshed = converted
    try:
        write_update_state(path, refreshed)
    except (OSError, ValueError):
        return UpdateCheck("failed", detail="update-check state could not be refreshed")
    return UpdateCheck(
        "not_modified" if status == 304 else "checked",
        latest_version=refreshed["latest_version"],
    )


def _distribution_headers(state: Mapping[str, Any]) -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "User-Agent": f"gravity-sdk/{__version__}",
    }
    etag = state.get("etag")
    if isinstance(etag, str) and etag:
        headers["If-None-Match"] = etag
    return headers


def _response_state(
    response: Any, state: Mapping[str, Any], now: datetime
) -> tuple[int, dict[str, Any]] | UpdateCheck:
    status = int(getattr(response, "status_code", 0))
    if status == 304:
        return status, build_update_state(
            successful_checked_at=now,
            etag=optional_text(state.get("etag")),
            latest_version=optional_text(state.get("latest_version")),
            attempted_version=optional_text(state.get("attempted_version")),
            attempted_at=optional_timestamp(state.get("attempted_at")),
        )
    if status != 200:
        return UpdateCheck(
            "failed", detail=f"PyPI release source returned HTTP {status or 'unknown'}"
        )
    try:
        latest_version = _latest_pypi_version(response.content)
    except (AttributeError, json.JSONDecodeError, TypeError, ValueError):
        return UpdateCheck("failed", detail="PyPI release source returned invalid data")
    response_etag = str(getattr(response, "headers", {}).get("ETag", "")).strip()
    return status, build_update_state(
        successful_checked_at=now,
        etag=response_etag if valid_etag(response_etag) else None,
        latest_version=latest_version,
        attempted_version=optional_text(state.get("attempted_version")),
        attempted_at=optional_timestamp(state.get("attempted_at")),
    )


def _record_upgrade_attempt(path: Path, version: str, now: datetime) -> UpdateCheck:
    try:
        with hold_update_lease(path, now):
            state = read_update_state(path)
            return _record_attempt_under_lease(path, state, version, now)
    except UpdateStateBusy:
        return UpdateCheck("busy")
    except UpdateStateError as exc:
        return UpdateCheck("failed", detail=str(exc))


def _record_attempt_under_lease(
    path: Path,
    state: Mapping[str, Any] | None,
    version: str,
    now: datetime,
) -> UpdateCheck:
    if state is None:
        return UpdateCheck("failed", detail="successful update-check state is missing")
    attempted_at = optional_timestamp(state.get("attempted_at"))
    if (
        state.get("attempted_version") == version
        and attempted_at is not None
        and now - attempted_at < UPDATE_CHECK_INTERVAL
    ):
        return UpdateCheck("attempt_suppressed", latest_version=version)
    refreshed = dict(state)
    refreshed.update(attempted_version=version, attempted_at=format_timestamp(now))
    try:
        write_update_state(path, refreshed)
    except (OSError, ValueError):
        return UpdateCheck("failed", detail="update-attempt state could not be recorded")
    return UpdateCheck("attempt_due", latest_version=version)


def _distribution_get(headers: Mapping[str, str]) -> requests.Response:
    """Fetch PyPI metadata through the authoritative kind-aware boundary."""

    return perform_http_request(
        requests.get,
        _PYPI_JSON_URL,
        kind=DISTRIBUTION_HTTP_KIND,
        headers=dict(headers),
        timeout=(2.0, 4.0),
        allow_redirects=False,
    )


def _latest_pypi_version(value: bytes) -> str:
    if not isinstance(value, bytes) or len(value) > 1024 * 1024:
        raise ValueError("PyPI metadata must be bounded bytes")
    payload = json.loads(value.decode("utf-8"))
    if not isinstance(payload, Mapping) or not isinstance(payload.get("info"), Mapping):
        raise ValueError("PyPI metadata must contain package info")
    info = payload["info"]
    name = str(info.get("name", "")).strip().casefold().replace("_", "-")
    version = str(info.get("version", "")).strip()
    if name != _DISTRIBUTION_NAME or version_tuple(version) is None:
        raise ValueError("PyPI metadata package identity or version is invalid")
    return version


def _is_newer(available_version: str, current_version: str) -> bool:
    available = version_tuple(available_version)
    current = version_tuple(current_version)
    return available is not None and current is not None and available > current


__all__ = [
    "AUTO_UPGRADE_ENV",
    "DISTRIBUTION_HTTP_KIND",
    "PINNED_VERSION_ENV",
    "TERMINAL_UPGRADE_STATUSES",
    "UPDATE_CHECK_INTERVAL",
    "UPGRADE_RESTART_EXIT_CODE",
    "UpdateCheck",
    "check_latest_version",
    "maybe_auto_upgrade",
    "startup_update_enabled",
    "update_state_path",
]
