"""Thin runtime bridge to the canonical Gravity Insight SDK.

This module deliberately owns no HTTP, authentication, manifest, or pagination
implementation.  It only locates the canonical SDK and provides small CLI-side
helpers that are easy to replace in tests.
"""

from __future__ import annotations

import importlib
import inspect
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

from .json_output import to_jsonable
from .paths import PROJECT_ROOT


REPO_ROOT = PROJECT_ROOT
MANIFEST_DIR = Path(__file__).resolve().parent / "manifests"
_CLIENT_LOCK = threading.Lock()
_CLIENT: Any | None = None
_EXPERIMENTAL_CLIENT: Any | None = None


def _sdk_module():
    errors: list[BaseException] = []
    for name in ("gravity_sdk",):
        try:
            return importlib.import_module(name)
        except (ImportError, AttributeError) as exc:
            errors.append(exc)
    raise RuntimeError(
        "Gravity SDK is unavailable; install the gravity-insight package"
    ) from errors[-1]


def build_client(*, allow_experimental: bool = False):
    """Return one long-lived canonical client per CLI policy profile."""

    global _CLIENT, _EXPERIMENTAL_CLIENT
    selected = _EXPERIMENTAL_CLIENT if allow_experimental else _CLIENT
    if selected is None:
        with _CLIENT_LOCK:
            selected = _EXPERIMENTAL_CLIENT if allow_experimental else _CLIENT
            if selected is None:
                sdk = _sdk_module()
                client_class = getattr(sdk, "GravityInsightClient", None)
                if client_class is None:
                    raise RuntimeError("Gravity Insight SDK does not export GravityInsightClient")
                if allow_experimental:
                    selected = client_class.from_env(allow_experimental=True)
                    _EXPERIMENTAL_CLIENT = selected
                else:
                    selected = client_class.from_env()
                    _CLIENT = selected
    return selected


def operation_ids(operations: Any) -> set[str]:
    """Normalize operation IDs from list- or envelope-shaped SDK output."""

    value = to_jsonable(operations)
    if isinstance(value, Mapping):
        for key in ("operations", "data"):
            nested = value.get(key)
            if isinstance(nested, list):
                value = nested
                break
    if not isinstance(value, list):
        return set()
    result: set[str] = set()
    for item in value:
        if isinstance(item, str):
            result.add(item)
        elif isinstance(item, Mapping) and isinstance(item.get("operation_id"), str):
            result.add(item["operation_id"])
    return result


def resolve_operation_id(client: Any, candidates: str | Sequence[str]) -> str:
    """Select one registered operation ID from a stable CLI domain mapping."""

    choices = (candidates,) if isinstance(candidates, str) else tuple(candidates)
    available = operation_ids(client.operations())
    for operation_id in choices:
        if operation_id in available:
            return operation_id
    if len(choices) == 1 and not available:
        # Some test doubles and older SDK shims do not expose a normalized list.
        return choices[0]
    raise ValueError("No registered operation matches this domain command: " + ", ".join(choices))


def call_read(
    client: Any,
    operation_id: str,
    inputs: Mapping[str, Any],
    *,
    read_all: bool = False,
    limit: int | None = None,
    max_pages: int | None = None,
    max_items: int | None = None,
    max_workers: int | None = None,
    continue_without_total: bool = False,
    forward_var_kwargs: bool = False,
) -> Any:
    effective_items = max_items if max_items is not None else limit
    method = _read_method(client, read_all, max_pages, effective_items)
    kwargs = _read_options(
        method,
        max_pages=max_pages,
        max_items=effective_items,
        max_workers=max_workers,
        continue_without_total=continue_without_total,
        forward_var_kwargs=forward_var_kwargs,
    )
    return method(operation_id, dict(inputs), **kwargs)


def _read_method(
    client: Any, read_all: bool, max_pages: int | None, max_items: int | None
) -> Any:
    bounded = max_pages is not None or max_items is not None
    if not read_all and bounded and callable(getattr(client, "read_limited", None)):
        return client.read_limited
    return client.read_all if read_all or max_items is not None else client.read


def _read_options(
    method: Any,
    *,
    max_pages: int | None,
    max_items: int | None,
    max_workers: int | None,
    continue_without_total: bool,
    forward_var_kwargs: bool,
) -> dict[str, Any]:
    parameters = inspect.signature(method).parameters
    accepts_options = forward_var_kwargs and any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    kwargs: dict[str, Any] = {}
    if max_pages is not None and ("max_pages" in parameters or accepts_options):
        kwargs["max_pages"] = max_pages
    item_option = _item_option(parameters, max_items, accepts_options)
    if item_option is not None:
        name, value = item_option
        kwargs[name] = value
    if max_workers is not None and ("max_workers" in parameters or accepts_options):
        kwargs["max_workers"] = max_workers
    if continue_without_total and (
        "continue_without_total" in parameters or accepts_options
    ):
        kwargs["continue_without_total"] = True
    return kwargs


def _item_option(
    parameters: Mapping[str, inspect.Parameter],
    value: int | None,
    accepts_options: bool,
) -> tuple[str, int] | None:
    if value is None:
        return None
    for name in ("limit", "max_items", "max_rows"):
        if name in parameters:
            return name, value
    return ("max_items", value) if accepts_options else None


def call_batch(
    client: Any,
    requests: Sequence[Mapping[str, Any]],
    *,
    concurrency: int = 6,
    max_pages: int | None = None,
    max_total_items: int | None = None,
    forward_var_kwargs: bool = False,
) -> Any:
    method = client.batch
    parameters = inspect.signature(method).parameters
    accepts_options = forward_var_kwargs and any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in parameters.values()
    )
    kwargs: dict[str, Any] = {}
    if "concurrency" in parameters:
        kwargs["concurrency"] = concurrency
    elif "max_workers" in parameters or accepts_options:
        kwargs["max_workers"] = concurrency
    if max_pages is not None and ("max_pages" in parameters or accepts_options):
        kwargs["max_pages"] = max_pages
    if max_total_items is not None and (
        "max_total_items" in parameters or accepts_options
    ):
        kwargs["max_total_items"] = max_total_items
    return method([dict(item) for item in requests], **kwargs)


def credential_status() -> dict[str, Any]:
    """Report credential metadata without returning credential values."""

    from .runtime_scope import resolve_env_path

    env_path, _isolated = resolve_env_path()
    sdk = _sdk_module()
    config_class = getattr(sdk, "CredentialConfig", None)
    if config_class is None:
        raise RuntimeError("Gravity Insight SDK does not export CredentialConfig")
    config = config_class.from_env(env_path)
    token_present = bool(config.token)
    token_valid = bool(
        config.token
        and (
            config.expires_at is None
            or config.expires_at > datetime.now(timezone.utc) + timedelta(minutes=2)
        )
    )
    credentials_available = bool(config.username and config.password)
    if token_valid:
        state = "valid_token"
        next_action = "Run the requested Gravity Insight operation."
    elif credentials_available:
        state = "credentials_available"
        next_action = (
            "Run `gravity auth refresh` to exchange the "
            "configured username/password for a token."
        )
    else:
        state = "missing"
        next_action = (
            "Run `gravity` in an interactive terminal to configure the Gravity "
            "username and password, or place them in the ignored "
            "`.env.gravity.local` and run `gravity insight auth refresh`."
        )
    return {
        "status": state,
        "auth_state": state,
        "credential_present": token_present,
        "token_valid": token_valid,
        "token_source": getattr(config, "token_source", None),
        "account_hint": _masked_account(config.username),
        "username_present": bool(config.username),
        "password_present": bool(config.password),
        "can_exchange_credentials": credentials_available,
        "can_authenticate": token_valid or credentials_available,
        "expires_at_asia_shanghai": (
            config.expires_at.astimezone(ZoneInfo("Asia/Shanghai")).isoformat()
            if config.expires_at is not None
            else None
        ),
        "updated_at": (
            config.updated_at.isoformat() if config.updated_at is not None else None
        ),
        "next_action": next_action,
    }


def _masked_account(username: str | None) -> str | None:
    if not username:
        return None
    value = username.strip()
    if "@" in value:
        local, domain = value.rsplit("@", 1)
        if local and domain:
            return f"{local[:1]}***@{domain}"
    if len(value) <= 2:
        return "***"
    return f"{value[:1]}***{value[-1:]}"


def refresh_credentials() -> dict[str, Any]:
    """Refresh the SDK-managed session without exposing a token setting."""

    sdk = _sdk_module()
    provider_class = getattr(sdk, "CredentialProvider", None)
    if provider_class is None:
        raise RuntimeError("Gravity SDK does not export CredentialProvider")
    from .runtime_scope import resolve_env_path

    env_path, isolated = resolve_env_path()
    provider = provider_class(env_path, environ={}, isolated=isolated)
    provider.refresh()
    return {
        "status": "success",
        "refresh": {"action": "refreshed_internal_session"},
        "auth": credential_status(),
    }


def manifest_files() -> list[Path]:
    return sorted(MANIFEST_DIR.glob("*.json")) if MANIFEST_DIR.is_dir() else []


def validate_manifest_json() -> dict[str, Any]:
    files = manifest_files()
    operations = 0
    seen: set[str] = set()
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        items = payload.get("operations") if isinstance(payload, Mapping) else None
        if not isinstance(items, list) or not items:
            raise ValueError(f"manifest {path.name} has no operations")
        for item in items:
            operation_id = item.get("operation_id") if isinstance(item, Mapping) else None
            if not isinstance(operation_id, str) or not operation_id:
                raise ValueError(f"manifest {path.name} contains an invalid operation_id")
            if operation_id in seen:
                raise ValueError(f"duplicate operation_id: {operation_id}")
            seen.add(operation_id)
            method = str(item.get("upstream_method", "")).upper()
            if method not in {"GET", "POST"}:
                raise ValueError(f"operation {operation_id} is not read-only")
        operations += len(items)
    if not files:
        raise ValueError("no Gravity Insight manifests found")
    return {"manifest_files": len(files), "operations": operations}
