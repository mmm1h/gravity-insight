"""Default-on startup release checks and immutable installation handoff."""

from __future__ import annotations

import json
import os
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
    hold_update_lease,
    is_newer,
    optional_text,
    read_update_state,
    resolve_target_python,
    runtime_scope_id,
    success_is_recent,
    utc,
    valid_etag,
    version_tuple,
    write_update_state,
)
from .control_plane.update_models import UpdatePlanRequest
from .receipt import DISTRIBUTION_HTTP_KIND, perform_http_request
from .runtime_scope import gravity_insight_cache_root


AUTO_UPGRADE_ENV = "GRAVITY_INSIGHT_AUTO_UPGRADE"
PINNED_VERSION_ENV = "GRAVITY_INSIGHT_PINNED_VERSION"
TARGET_PYTHON_ENV = "GRAVITY_INSIGHT_AUTO_UPGRADE_TARGET_PYTHON"
UPDATE_CHECK_INTERVAL = timedelta(hours=24)
UPDATE_STATE_FILENAME = "update-check.json"
UPDATE_POLICY_EXIT_CODE = 75
TERMINAL_UPGRADE_STATUSES = frozenset(
    {"downgrade_rejected", "failed", "target_rejected", "target_unconfigured"}
)

_DISTRIBUTION_NAME = "gravity-insight"
_PYPI_JSON_URL = "https://pypi.org/pypi/gravity-insight/json"
_LEGACY_AUTO_UPGRADE_ENV = "GRAVITY_SDK_AUTO_UPGRADE"
_LEGACY_PINNED_VERSION_ENV = "GRAVITY_SDK_PINNED_VERSION"
_LEGACY_TARGET_PYTHON_ENV = "GRAVITY_SDK_AUTO_UPGRADE_TARGET_PYTHON"


@dataclass(frozen=True)
class UpdateCheck:
    status: str
    latest_version: str | None = None
    detail: str | None = None
    state: Mapping[str, Any] | None = None
    plan: UpdatePlanRequest | None = None


def _environment_value(
    environ: Mapping[str, str], primary_name: str, legacy_name: str
) -> str | None:
    if primary_name in environ:
        return environ[primary_name]
    return environ.get(legacy_name)


def _target_python_from_environment(
    environ: Mapping[str, str] | None = None,
) -> str | None:
    env = os.environ if environ is None else environ
    return _environment_value(env, TARGET_PYTHON_ENV, _LEGACY_TARGET_PYTHON_ENV)


def update_state_path() -> Path:
    """Return the release cache isolated to this imported runtime."""

    filename = Path(UPDATE_STATE_FILENAME)
    return gravity_insight_cache_root() / (
        f"{filename.stem}-{_runtime_scope_id()}{filename.suffix}"
    )


def update_attempt_state_path(state_path: Path | None = None) -> Path:
    """Return the retired attempt-state location for state-file migration tests."""

    path = update_state_path() if state_path is None else Path(state_path)
    return path.with_name(f"{path.stem}.attempt{path.suffix}")


def startup_update_enabled(
    argv: Sequence[str], *, environ: Mapping[str, str] | None = None
) -> bool:
    """Keep diagnostic, evaluation, test, and exact-pinned paths offline."""

    env = os.environ if environ is None else environ
    args = list(argv)
    if args[:1] == ["doctor"] or args[:2] == ["insight", "doctor"]:
        return False
    pinned = str(
        _environment_value(env, PINNED_VERSION_ENV, _LEGACY_PINNED_VERSION_ENV) or ""
    ).strip()
    if version_tuple(pinned) is not None and pinned == __version__:
        return False
    configured = _environment_value(env, AUTO_UPGRADE_ENV, _LEGACY_AUTO_UPGRADE_ENV)
    return configured is None or configured.strip().casefold() in {"1", "true", "yes", "on"}


def maybe_auto_upgrade(
    argv: Sequence[str],
    *,
    environ: Mapping[str, str] | None = None,
    state_path: Path | None = None,
    now: datetime | None = None,
    request: Callable[[Mapping[str, str]], Any] | None = None,
    stderr: TextIO | None = None,
    target_python: str | os.PathLike[str] | None = None,
) -> UpdateCheck:
    """Install a newer release into an isolated stage before command dispatch."""

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
    if not _upgrade_is_due(checked):
        return checked
    from ._auto_upgrade_install import prepare_install

    try:
        status, receipt, detail = prepare_install(
            checked.latest_version,
            target_python=target_python or _target_python_from_environment(env),
            cache_root=path.parent, now=selected_now, environment=env,
        )
        result = UpdateCheck(status, latest_version=checked.latest_version, state=receipt, detail=detail)
    except Exception as exc:
        result = UpdateCheck("failed", latest_version=checked.latest_version,
                             detail=f"{type(exc).__name__}: {exc}")
    if result.status == "installed":
        print(f"Gravity SDK installed {result.latest_version} in an isolated stage; "
              f"this process still runs {__version__}; CLI will re-exec before dispatch.", file=output)
    else:
        _warn_check_failure(result, output)
    return result


def _plan_checked_update(
    checked: UpdateCheck,
    *,
    target_python: str | os.PathLike[str] | None,
    output: TextIO,
) -> UpdateCheck:
    version = checked.latest_version
    if _downgrade_is_offered(checked):
        assert version is not None
        detail = f"release source offered {version} below running version {__version__}"
        return _reject(
            "downgrade_rejected",
            version,
            detail,
            f"Gravity SDK rejected downgrade from {__version__} to {version}.",
            output,
        )
    if not _upgrade_is_due(checked):
        return checked
    assert version is not None
    target, target_failure = resolve_target_python(target_python, sys.executable)
    if target is None:
        status = "target_rejected" if target_python is not None else "target_unconfigured"
        return _reject(
            status,
            version,
            target_failure,
            f"Gravity SDK cannot plan update {version} ({target_failure}).",
            output,
        )
    plan = UpdatePlanRequest.create(
        current_version=__version__,
        target_version=version,
        target_environment=str(target),
    )
    print(
        f"Gravity SDK update {version} is available; external Installer plan request "
        f"{plan.request_id} targets {target}. Runtime did not install, change the "
        "project lock, or restart; continuing this command.",
        file=output,
    )
    return UpdateCheck("plan_ready", latest_version=version, plan=plan)


def _reject(
    status: str,
    version: str,
    detail: str | None,
    message: str,
    output: TextIO,
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


def _warn_check_failure(checked: UpdateCheck, output: TextIO) -> None:
    print(
        f"warning: Gravity SDK startup update {checked.status} ({checked.detail}). "
        f"Continuing this command with {__version__}. Check network/index and cache "
        "permissions, then retry; set GRAVITY_INSIGHT_AUTO_UPGRADE=0 to disable updates.",
        file=output,
    )


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
    headers = {
        "Accept": "application/json",
        "User-Agent": f"gravity-insight/{__version__}",
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
    return eligible and bool(
        checked.latest_version and is_newer(checked.latest_version, __version__)
    )


def _downgrade_is_offered(checked: UpdateCheck) -> bool:
    eligible = checked.status in {"cached", "checked", "not_modified"}
    return eligible and bool(
        checked.latest_version and is_newer(__version__, checked.latest_version)
    )


__all__ = [
    "AUTO_UPGRADE_ENV",
    "DISTRIBUTION_HTTP_KIND",
    "PINNED_VERSION_ENV",
    "TARGET_PYTHON_ENV",
    "TERMINAL_UPGRADE_STATUSES",
    "UPDATE_CHECK_INTERVAL",
    "UPDATE_POLICY_EXIT_CODE",
    "UpdateCheck",
    "check_latest_version",
    "maybe_auto_upgrade",
    "startup_update_enabled",
    "update_attempt_state_path",
    "update_state_path",
]
