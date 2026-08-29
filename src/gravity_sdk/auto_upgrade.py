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
    UpdateStateBusy, UpdateStateError, build_update_state, hold_update_lease,
    is_newer, mark_upgrade_attempt, optional_text, recent_incomplete_upgrade,
    read_update_state, record_upgrade_attempt, resolve_target_python,
    runtime_scope_id, success_is_recent, utc, valid_etag, version_tuple,
    write_update_state,
)
from .receipt import DISTRIBUTION_HTTP_KIND, perform_http_request
from .runtime_scope import gravity_insight_cache_root


AUTO_UPGRADE_ENV = "GRAVITY_SDK_AUTO_UPGRADE"
PINNED_VERSION_ENV = "GRAVITY_SDK_PINNED_VERSION"
TARGET_PYTHON_ENV = "GRAVITY_SDK_AUTO_UPGRADE_TARGET_PYTHON"
UPDATE_CHECK_INTERVAL = timedelta(hours=24)
UPDATE_STATE_FILENAME = "update-check.json"
UPGRADE_RESTART_EXIT_CODE = 75
TERMINAL_UPGRADE_STATUSES = frozenset(
    {
        "attempt_busy", "attempt_suppressed", "downgrade_rejected", "failed",
        "upgrade_failed", "upgrade_incomplete", "verification_failed",
        "restart_failed", "target_rejected", "target_unconfigured",
    }
)

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
    """Return the release cache isolated to this imported runtime."""

    filename = Path(UPDATE_STATE_FILENAME)
    return gravity_insight_cache_root() / (
        f"{filename.stem}-{_runtime_scope_id()}{filename.suffix}"
    )


def update_attempt_state_path(state_path: Path | None = None) -> Path:
    """Return the upgrade-attempt state isolated to this imported runtime."""

    path = update_state_path() if state_path is None else Path(state_path)
    return path.with_name(f"{path.stem}.attempt{path.suffix}")


def startup_update_enabled(
    argv: Sequence[str], *, environ: Mapping[str, str] | None = None
) -> bool:
    """Keep diagnostic, evaluation, test, pinned, and re-exec paths offline."""

    env = os.environ if environ is None else environ
    args = list(argv)
    if args[:1] == ["doctor"] or args[:2] == ["insight", "doctor"]:
        return False
    pinned = str(env.get(PINNED_VERSION_ENV, "")).strip()
    if version_tuple(pinned) is not None and pinned == __version__:
        return False
    if env.get(_REEXEC_ENV) == "1":
        return False
    return str(env.get(AUTO_UPGRADE_ENV, "")).strip().casefold() in {"1", "true", "yes", "on"}


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
    target_python: str | os.PathLike[str] | None = None,
) -> UpdateCheck:
    """Check and upgrade an explicit external interpreter before command work."""

    env = os.environ if environ is None else environ
    if not startup_update_enabled(argv, environ=env):
        return UpdateCheck("disabled")
    output = sys.stderr if stderr is None else stderr
    selected_now = utc(now)
    path = update_state_path() if state_path is None else Path(state_path)
    incomplete = _safe_incomplete_attempt(path, selected_now)
    if incomplete is not None:
        _warn_incomplete_attempt(incomplete, output)
        return incomplete
    checked = _safe_check(state_path=path, now=selected_now, request=request)
    if checked.status == "failed":
        _warn_check_failure(checked, output)
        return checked
    return _apply_checked_upgrade(
        checked,
        argv=argv,
        state_path=path,
        now=selected_now,
        run=run,
        execv=execv,
        output=output,
        target_python=target_python,
    )


def _apply_checked_upgrade(
    checked: UpdateCheck,
    *,
    argv: Sequence[str],
    state_path: Path,
    now: datetime,
    run: Callable[..., subprocess.CompletedProcess[str]] | None,
    execv: Callable[[str, list[str]], Any] | None,
    output: TextIO,
    target_python: str | os.PathLike[str] | None,
) -> UpdateCheck:
    version = checked.latest_version
    if _downgrade_is_offered(checked):
        assert version is not None
        detail = f"release source offered {version} below running version {__version__}"
        return _reject("downgrade_rejected", version, detail, f"Gravity SDK rejected downgrade from {__version__} to {version}.", output)
    if not _upgrade_is_due(checked):
        return checked
    assert version is not None

    target, target_failure = resolve_target_python(target_python, sys.executable)
    if target is None:
        status = "target_rejected" if target_python is not None else "target_unconfigured"
        return _reject(status, version, target_failure, f"Gravity SDK cannot upgrade to {version} ({target_failure}).", output)

    attempted = _safe_record_attempt(state_path, version, now)
    if attempted.status == "failed":
        _warn_check_failure(attempted, output)
        return attempted
    if attempted.status != "attempt_due":
        if attempted.status in {"attempt_busy", "attempt_suppressed"}:
            _warn_incomplete_attempt(attempted, output)
        return attempted

    failure = _pip_upgrade(version, target, run)
    if failure is not None:
        mark_failure = _safe_mark_attempt(state_path, version, now, "failed")
        detail = failure if mark_failure is None else f"{failure}; {mark_failure}"
        print(
            f"error: Gravity SDK auto-upgrade to {version} failed ({detail}). "
            "pip may have modified the target environment, so this command was not run. "
            "Repair or retry the installation before running it again.",
            file=output,
        )
        return UpdateCheck("upgrade_failed", latest_version=version, detail=detail)

    verification_failure = _verify_installed_version(version, target, run)
    if verification_failure is not None:
        _safe_mark_attempt(state_path, version, now, "failed")
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
    attempt_mark_failure = _safe_mark_attempt(state_path, version, now, "verified")
    if attempt_mark_failure is not None:
        print(
            f"error: Gravity SDK was verified at {version}, but its upgrade state "
            f"could not be finalized ({attempt_mark_failure}). This command was not "
            "run; rerun it once.",
            file=output,
        )
        return UpdateCheck(
            "verification_failed",
            latest_version=version,
            detail=attempt_mark_failure,
        )
    return _restart(
        argv, version, target_python=target, execv=execv, output=output
    )


def _reject(
    status: str, version: str, detail: str | None, message: str, output: TextIO
) -> UpdateCheck:
    print(f"error: {message} This command was not run.", file=output)
    return UpdateCheck(status, latest_version=version, detail=detail)


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


def _safe_incomplete_attempt(path: Path, now: datetime) -> UpdateCheck | None:
    try:
        attempted = recent_incomplete_upgrade(
            update_attempt_state_path(path), now, UPDATE_CHECK_INTERVAL
        )
    except Exception:
        return UpdateCheck(
            "upgrade_incomplete",
            detail="local upgrade-attempt state is unreadable",
        )
    if attempted is None:
        return None
    return UpdateCheck(
        "upgrade_incomplete",
        latest_version=optional_text(attempted.get("attempted_version")),
        detail="a recent upgrade attempt did not complete verification",
    )


def _safe_mark_attempt(
    path: Path, version: str, now: datetime, status: str
) -> str | None:
    try:
        mark_upgrade_attempt(update_attempt_state_path(path), version, now, status)
    except Exception:
        return "local upgrade-attempt state is unavailable"
    return None


def _warn_check_failure(checked: UpdateCheck, output: TextIO) -> None:
    print(
        f"error: Gravity SDK update check failed ({checked.detail}). "
        "This command was not run.",
        file=output,
    )


def _warn_incomplete_attempt(checked: UpdateCheck, output: TextIO) -> None:
    print(
        "error: Gravity SDK detected an upgrade that is active or was not fully "
        f"verified ({checked.detail or checked.status}). This command was not run; "
        "repair or retry the installation first.",
        file=output,
    )


def _pip_upgrade(
    version: str,
    target_python: Path,
    run: Callable[..., subprocess.CompletedProcess[str]] | None,
) -> str | None:
    command = [
        str(target_python), "-m", "pip", "install", "--isolated",
        "--disable-pip-version-check", "--no-input", "--no-cache-dir", "--no-compile", "--upgrade",
        "--only-binary=:all:", "--index-url", _PYPI_INDEX_URL,
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
    target_python: Path,
    run: Callable[..., subprocess.CompletedProcess[str]] | None,
) -> str | None:
    probe = f"""
import base64, hashlib, json
from importlib.metadata import distribution
from pathlib import Path
import gravity_sdk

selected = distribution({_DISTRIBUTION_NAME!r})
package_files = [
    item for item in (selected.files or ()) if item.parts
    and item.parts[0] == "gravity_sdk"
]
init_files = [item for item in package_files if tuple(item.parts) == ("gravity_sdk", "__init__.py")]
imported_init = Path(gravity_sdk.__file__).resolve()
owned_import = (
    len(init_files) == 1
    and Path(selected.locate_file(init_files[0])).resolve() == imported_init
)
hashes_match = bool(package_files)
for item in package_files:
    installed = Path(selected.locate_file(item)).resolve()
    recorded = item.hash
    if recorded is None or not installed.is_file():
        hashes_match = False
        break
    digest = hashlib.new(recorded.mode, installed.read_bytes()).digest()
    actual = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    if actual != recorded.value:
        hashes_match = False
        break
print(json.dumps({{"distribution_version": selected.version,
    "code_verified": owned_import and hashes_match,
    "package_file_count": len(package_files)}}, sort_keys=True))
""".strip()
    checked = _run_subprocess([str(target_python), "-c", probe], run, timeout=30)
    if checked is None or checked.returncode != 0:
        return (
            "the fresh interpreter could not be started"
            if checked is None
            else f"the fresh interpreter exited with code {checked.returncode}"
        )
    try:
        result = json.loads(str(checked.stdout or ""))
    except (json.JSONDecodeError, TypeError, ValueError):
        return "the fresh interpreter returned invalid verification data"
    if not isinstance(result, Mapping):
        return "the fresh interpreter returned invalid verification data"
    actual = str(result.get("distribution_version", "")).strip()
    if actual != expected:
        return f"the fresh interpreter reported distribution version {actual or 'unknown'}"
    if result.get("code_verified") is not True or not isinstance(
        result.get("package_file_count"), int
    ) or result["package_file_count"] < 1:
        return "the imported package does not match the installed distribution files"
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
    target_python: Path,
    execv: Callable[[str, list[str]], Any] | None,
    output: TextIO,
) -> UpdateCheck:
    print(
        f"Gravity SDK upgraded from {__version__} to {version}; restarting this command.",
        file=output,
    )
    executable = str(target_python)
    replacement = [executable, "-m", "gravity_sdk", *argv]
    replace = os.execv if execv is None else execv
    previous = os.environ.get(_REEXEC_ENV)
    os.environ[_REEXEC_ENV] = "1"
    try:
        replace(executable, replacement)
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
        return UpdateCheck(
            "cached", latest_version=optional_text(state.get("latest_version"))
        )
    previous = state or build_update_state(
        successful_checked_at=None,
        etag=None,
        latest_version=None,
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
    headers = {"Accept": "application/json", "User-Agent": f"gravity-sdk/{__version__}"}
    etag = state.get("etag")
    if isinstance(etag, str) and etag:
        headers["If-None-Match"] = etag
    return headers


def _response_state(
    response: Any, state: Mapping[str, Any], now: datetime
) -> tuple[int, dict[str, Any]] | UpdateCheck:
    status = int(getattr(response, "status_code", 0))
    if status == 304:
        etag = optional_text(state.get("etag"))
        latest_version = optional_text(state.get("latest_version"))
        if etag is None or latest_version is None:
            return UpdateCheck(
                "failed",
                detail="PyPI release source returned HTTP 304 without reusable state",
            )
        return status, build_update_state(
            successful_checked_at=now,
            etag=etag,
            latest_version=latest_version,
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
    )


def _record_upgrade_attempt(path: Path, version: str, now: datetime) -> UpdateCheck:
    try:
        state = read_update_state(path)
        if (
            state is None
            or state.get("latest_version") != version
            or not success_is_recent(state, now, UPDATE_CHECK_INTERVAL)
        ):
            return UpdateCheck("failed", detail="successful update-check state is missing")
        outcome = record_upgrade_attempt(
            update_attempt_state_path(path), version, now, UPDATE_CHECK_INTERVAL
        )
        return UpdateCheck(
            "attempt_due" if outcome == "due" else "attempt_suppressed",
            latest_version=version,
        )
    except UpdateStateBusy:
        return UpdateCheck("attempt_busy", latest_version=version)
    except UpdateStateError as exc:
        return UpdateCheck("failed", detail=str(exc))


def _runtime_scope_id() -> str:
    return runtime_scope_id(sys.executable, Path(__file__).resolve().parent)


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


def _upgrade_is_due(checked: UpdateCheck) -> bool:
    eligible = checked.status in {"cached", "checked", "not_modified"}
    return eligible and bool(checked.latest_version and is_newer(checked.latest_version, __version__))


def _downgrade_is_offered(checked: UpdateCheck) -> bool:
    eligible = checked.status in {"cached", "checked", "not_modified"}
    return eligible and bool(checked.latest_version and is_newer(__version__, checked.latest_version))


__all__ = ["AUTO_UPGRADE_ENV", "DISTRIBUTION_HTTP_KIND", "PINNED_VERSION_ENV", "TARGET_PYTHON_ENV", "TERMINAL_UPGRADE_STATUSES", "UPDATE_CHECK_INTERVAL", "UPGRADE_RESTART_EXIT_CODE", "UpdateCheck", "check_latest_version", "maybe_auto_upgrade", "startup_update_enabled", "update_attempt_state_path", "update_state_path"]
