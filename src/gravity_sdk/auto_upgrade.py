"""Bounded startup upgrades from immutable Gravity SDK Git tags."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, BinaryIO, TextIO

import requests

from . import __version__
from .runtime_scope import gravity_insight_cache_root


AUTO_UPGRADE_ENV = "GRAVITY_SDK_AUTO_UPGRADE"
PINNED_VERSION_ENV = "GRAVITY_SDK_PINNED_VERSION"
DISTRIBUTION_HTTP_KIND = "code_distribution"
UPDATE_CHECK_INTERVAL = timedelta(hours=24)
UPDATE_STATE_SCHEMA_VERSION = 1
UPDATE_STATE_FILENAME = "update-check.json"

_REEXEC_ENV = "GRAVITY_SDK_UPGRADE_REEXEC"
_TAGS_URL = "https://github.com/mmm1h/gravity-sdk/releases.atom"
_INSTALL_URL = "git+https://github.com/mmm1h/gravity-sdk.git@{tag}"
_VERSION_PATTERN = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_STATE_FIELDS = frozenset({"schema_version", "checked_at", "etag", "latest_tag"})
_ATOM_NAMESPACE = "{http://www.w3.org/2005/Atom}"


@dataclass(frozen=True)
class UpdateCheck:
    status: str
    latest_tag: str | None = None
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
    checked = _safe_check(state_path=state_path, now=now, request=request)
    if checked.status == "failed":
        _warn_check_failure(checked, output)
        return checked
    if checked.latest_tag is None or not _is_newer(checked.latest_tag, __version__):
        return checked

    tag = checked.latest_tag
    failure = _pip_upgrade(tag, run)
    if failure is not None:
        print(
            f"warning: Gravity SDK auto-upgrade to {tag} failed; continuing with "
            f"version {__version__} ({failure}).",
            file=output,
        )
        return UpdateCheck("upgrade_failed", latest_tag=tag, detail=failure)
    return _restart(argv, tag, execv=execv, output=output)


def _safe_check(
    *,
    state_path: Path | None,
    now: datetime | None,
    request: Callable[[Mapping[str, str]], Any] | None,
) -> UpdateCheck:
    try:
        return check_latest_tag(state_path=state_path, now=now, request=request)
    except Exception:
        return UpdateCheck("failed", detail="local update-check state is unavailable")


def _warn_check_failure(checked: UpdateCheck, output: TextIO) -> None:
    print(
        "warning: Gravity SDK update check failed; continuing with "
        f"version {__version__} ({checked.detail}).",
        file=output,
    )


def _pip_upgrade(
    tag: str,
    run: Callable[..., subprocess.CompletedProcess[str]] | None,
) -> str | None:
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--upgrade",
        _INSTALL_URL.format(tag=tag),
    ]
    runner = subprocess.run if run is None else run
    try:
        installed = runner(
            command,
            text=True,
            capture_output=True,
            check=False,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError):
        installed = None
    if installed is None or installed.returncode != 0:
        return (
            "pip could not be started"
            if installed is None
            else f"pip exited with code {installed.returncode}"
        )
    return None


def _restart(
    argv: Sequence[str],
    tag: str,
    *,
    execv: Callable[[str, list[str]], Any] | None,
    output: TextIO,
) -> UpdateCheck:
    print(
        f"Gravity SDK upgraded from {__version__} to {tag.removeprefix('v')}; "
        "restarting this command.",
        file=output,
    )
    replacement = [sys.executable, "-m", "gravity_sdk", *argv]
    replace = os.execv if execv is None else execv
    previous = os.environ.get(_REEXEC_ENV)
    os.environ[_REEXEC_ENV] = "1"
    try:
        replace(sys.executable, replacement)
    except OSError:
        print(
            "warning: Gravity SDK was upgraded but the fresh process could not be "
            f"started; continuing with version {__version__}.",
            file=output,
        )
        return UpdateCheck("restart_failed", latest_tag=tag)
    finally:
        if previous is None:
            os.environ.pop(_REEXEC_ENV, None)
        else:
            os.environ[_REEXEC_ENV] = previous
    return UpdateCheck("restarted", latest_tag=tag)


def check_latest_tag(
    *,
    state_path: Path | None = None,
    now: datetime | None = None,
    request: Callable[[Mapping[str, str]], Any] | None = None,
) -> UpdateCheck:
    """Read/claim the machine interval and query GitHub on the distribution plane."""

    selected_now = _utc(now)
    path = update_state_path() if state_path is None else Path(state_path)
    claimed = _claim_check(path, selected_now)
    if claimed.status != "due":
        return claimed

    state = claimed.state
    if not isinstance(state, Mapping):
        return UpdateCheck("failed", detail="update-check state is invalid")
    headers = _distribution_headers(state)
    transport = _distribution_get if request is None else request
    try:
        response = transport(headers)
    except Exception:
        return UpdateCheck("failed", detail="GitHub tag source is unavailable")

    converted = _response_state(response, state, selected_now)
    if isinstance(converted, UpdateCheck):
        return converted
    status, refreshed = converted
    try:
        _write_state(path, refreshed)
    except Exception:
        return UpdateCheck("failed", detail="update-check state could not be refreshed")
    return UpdateCheck(
        "not_modified" if status == 304 else "checked",
        latest_tag=refreshed["latest_tag"],
    )


def _distribution_headers(state: Mapping[str, Any]) -> dict[str, str]:
    headers = {
        "Accept": "application/atom+xml",
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
        return status, _not_modified_state(state, now)
    if status != 200:
        return UpdateCheck(
            "failed", detail=f"GitHub tag source returned HTTP {status or 'unknown'}"
        )
    try:
        latest_tag = _latest_release_tag(response.content)
    except (AttributeError, ElementTree.ParseError, TypeError, ValueError):
        return UpdateCheck("failed", detail="GitHub tag source returned invalid data")
    response_etag = str(getattr(response, "headers", {}).get("ETag", "")).strip()
    return status, _state(
        now,
        etag=response_etag if _valid_etag(response_etag) else None,
        latest_tag=latest_tag,
    )


def _not_modified_state(state: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    etag = state.get("etag")
    latest_tag = state.get("latest_tag")
    return _state(
        now,
        etag=etag if isinstance(etag, str) else None,
        latest_tag=latest_tag if isinstance(latest_tag, str) else None,
    )


def _claim_check(path: Path, now: datetime) -> UpdateCheck:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return UpdateCheck("failed", detail="update-check state is not writable")
    with os.fdopen(descriptor, "r+b") as handle:
        if not _try_lock(handle):
            return UpdateCheck("busy")
        try:
            try:
                state = _read_state(handle)
            except (OSError, UnicodeError, ValueError):
                return UpdateCheck("failed", detail="update-check state is unreadable")
            if state is not None and now - _checked_at(state) < UPDATE_CHECK_INTERVAL:
                latest = state.get("latest_tag")
                return UpdateCheck(
                    "cached", latest_tag=latest if isinstance(latest, str) else None
                )
            previous = state or _state(now, etag=None, latest_tag=None)
            claim = _state(
                now,
                etag=previous.get("etag") if isinstance(previous.get("etag"), str) else None,
                latest_tag=(
                    previous.get("latest_tag")
                    if isinstance(previous.get("latest_tag"), str)
                    else None
                ),
            )
            try:
                _write_locked(handle, claim)
            except OSError:
                return UpdateCheck("failed", detail="update-check state is not writable")
            return UpdateCheck("due", state=previous)
        finally:
            _unlock(handle)


def _read_state(handle: BinaryIO) -> dict[str, Any] | None:
    handle.seek(0)
    raw = handle.read()
    if not raw:
        return None
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict) or set(value) != _STATE_FIELDS:
        raise ValueError("update-check state fields are invalid")
    if value.get("schema_version") != UPDATE_STATE_SCHEMA_VERSION:
        raise ValueError("update-check state schema is invalid")
    if not all(value.get(key) is None or isinstance(value.get(key), str) for key in ("etag", "latest_tag")):
        raise ValueError("update-check state values are invalid")
    _checked_at(value)
    latest = value.get("latest_tag")
    if latest is not None and _version_from_tag(latest) is None:
        raise ValueError("update-check tag is invalid")
    etag = value.get("etag")
    if etag is not None and not _valid_etag(etag):
        raise ValueError("update-check ETag is invalid")
    return value


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_RDWR)
    with os.fdopen(descriptor, "r+b") as handle:
        if not _try_lock(handle):
            raise OSError("update-check state is busy")
        try:
            _write_locked(handle, state)
        finally:
            _unlock(handle)


def _write_locked(handle: BinaryIO, state: Mapping[str, Any]) -> None:
    payload = (json.dumps(dict(state), sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    handle.seek(0)
    handle.write(payload)
    handle.truncate()
    handle.flush()
    os.fsync(handle.fileno())


def _try_lock(handle: BinaryIO) -> bool:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle: BinaryIO) -> None:
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _distribution_get(headers: Mapping[str, str]) -> requests.Response:
    """Fetch code-distribution metadata without entering Gravity production HTTP."""

    return requests.get(
        _TAGS_URL,
        headers=dict(headers),
        timeout=(2.0, 4.0),
        allow_redirects=False,
    )


def _latest_release_tag(value: bytes) -> str | None:
    if not isinstance(value, bytes) or len(value) > 1024 * 1024:
        raise ValueError("tags feed must be bounded bytes")
    root = ElementTree.fromstring(value)
    tags = {
        str(title.text).strip()
        for entry in root.findall(f"{_ATOM_NAMESPACE}entry")
        if (title := entry.find(f"{_ATOM_NAMESPACE}title")) is not None
        and title.text is not None
        and _version_from_tag(str(title.text).strip()) is not None
    }
    return max(tags, key=lambda tag: _version_from_tag(tag) or (-1, -1, -1)) if tags else None


def _is_newer(tag: str, current_version: str) -> bool:
    available = _version_from_tag(tag)
    current = _version_tuple(current_version)
    return available is not None and current is not None and available > current


def _version_from_tag(tag: str) -> tuple[int, int, int] | None:
    return _version_tuple(tag[1:]) if tag.startswith("v") else None


def _version_tuple(version: str) -> tuple[int, int, int] | None:
    matched = _VERSION_PATTERN.fullmatch(version)
    return tuple(int(part) for part in matched.groups()) if matched else None  # type: ignore[return-value]


def _state(
    checked_at: datetime, *, etag: str | None, latest_tag: str | None
) -> dict[str, Any]:
    return {
        "schema_version": UPDATE_STATE_SCHEMA_VERSION,
        "checked_at": _utc(checked_at).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "etag": etag,
        "latest_tag": latest_tag,
    }


def _checked_at(state: Mapping[str, Any]) -> datetime:
    value = state.get("checked_at")
    if not isinstance(value, str):
        raise ValueError("update-check timestamp is invalid")
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _utc(value: datetime | None) -> datetime:
    selected = datetime.now(timezone.utc) if value is None else value
    if selected.tzinfo is None:
        raise ValueError("update-check time must include a timezone")
    return selected.astimezone(timezone.utc)


def _valid_etag(value: str) -> bool:
    return bool(value) and len(value) <= 512 and "\r" not in value and "\n" not in value


__all__ = [
    "AUTO_UPGRADE_ENV",
    "DISTRIBUTION_HTTP_KIND",
    "PINNED_VERSION_ENV",
    "UPDATE_CHECK_INTERVAL",
    "UpdateCheck",
    "check_latest_tag",
    "maybe_auto_upgrade",
    "startup_update_enabled",
    "update_state_path",
]
