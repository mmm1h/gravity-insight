"""Private account and generated-session persistence for Gravity credentials."""

from __future__ import annotations

import getpass
import os
import subprocess
import tempfile
from collections.abc import Collection, Mapping
from pathlib import Path

from .errors import CredentialError


SESSION_ENV_NAME = ".env.gravity.session.local"
TOKEN_KEYS = ("GRAVITY_AUTH_TOKEN", "GRAVITY_AUTHORIZATION")
EXPIRY_KEY = "GRAVITY_AUTH_TOKEN_EXPIRES_AT_ASIA_SHANGHAI"
UPDATED_KEY = "GRAVITY_AUTH_UPDATED_AT"
PRINCIPAL_ID_KEY = "GRAVITY_PRINCIPAL_ID"
SESSION_USERNAME_KEY = "GRAVITY_SESSION_USERNAME"


def read_env_file(path: Path) -> dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError) as exc:
        raise CredentialError("could not read the Gravity credential file") from exc
    values: dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def session_path(env_path: Path) -> Path:
    """Return the private token cache that belongs to this account file."""

    selected = Path(env_path)
    dedicated = selected.with_name(f"{selected.stem}.session.local")
    if dedicated.exists() or selected.name != ".env.gravity.local":
        return dedicated
    return selected.with_name(SESSION_ENV_NAME)


def bound_session_values(
    env_path: Path, username: str | None
) -> dict[str, str]:
    """Return the cached session only when it still belongs to *username*."""

    selected_path = session_path(env_path)
    values = read_env_file(selected_path)
    if not values:
        return {}
    expected = (username or "").strip()
    bound = values.get(SESSION_USERNAME_KEY, "").strip()
    if not expected or bound == expected:
        return values
    selected_path.unlink(missing_ok=True)
    return {}


def save_account_credentials(username: str, password: str, path: Path) -> None:
    """Persist the two user-managed fields and remove legacy token settings."""

    normalized_username = username.strip()
    if not normalized_username or not password:
        raise CredentialError("Gravity username and password are required")
    if any("\n" in value or "\r" in value for value in (normalized_username, password)):
        raise CredentialError("credential values must not contain line breaks")
    atomic_update_env(
        Path(path),
        {
            "GRAVITY_USERNAME": normalized_username,
            "GRAVITY_PASSWORD": password,
        },
        remove_keys={
            *TOKEN_KEYS,
            EXPIRY_KEY,
            UPDATED_KEY,
            PRINCIPAL_ID_KEY,
            "GRAVITY_SDK_HOME",
        },
    )
    session_path(path).unlink(missing_ok=True)


def clear_account_credentials(path: Path) -> None:
    """Roll back a failed first-run login so the next run prompts again."""

    atomic_update_env(
        Path(path),
        {},
        remove_keys={
            "GRAVITY_USERNAME",
            "GRAVITY_PASSWORD",
            *TOKEN_KEYS,
            EXPIRY_KEY,
            UPDATED_KEY,
            PRINCIPAL_ID_KEY,
            "GRAVITY_SDK_HOME",
        },
    )
    session_path(path).unlink(missing_ok=True)


def migrate_legacy_session(path: Path) -> bool:
    """Move an old token setting out of the user-managed account file."""

    selected_path = Path(path)
    values = read_env_file(selected_path)
    token = _token_from(values)
    if not token:
        return False
    selected_session_path = session_path(selected_path)
    if not _token_from(read_env_file(selected_session_path)):
        atomic_update_env(
            selected_session_path,
            {
                "GRAVITY_AUTH_TOKEN": token,
                EXPIRY_KEY: values.get(EXPIRY_KEY, ""),
                UPDATED_KEY: values.get(UPDATED_KEY, ""),
                PRINCIPAL_ID_KEY: values.get(PRINCIPAL_ID_KEY, ""),
                SESSION_USERNAME_KEY: values.get("GRAVITY_USERNAME", ""),
            },
        )
    atomic_update_env(
        selected_path,
        {},
        remove_keys={
            *TOKEN_KEYS,
            EXPIRY_KEY,
            UPDATED_KEY,
            PRINCIPAL_ID_KEY,
            "GRAVITY_SDK_HOME",
        },
    )
    return True


def _token_from(values: Mapping[str, str]) -> str | None:
    return next(
        (values.get(key, "").strip() for key in TOKEN_KEYS if values.get(key, "").strip()),
        None,
    )


def atomic_update_env(
    path: Path,
    updates: Mapping[str, str],
    *,
    remove_keys: Collection[str] = (),
) -> None:
    if any("\n" in value or "\r" in value for value in updates.values()):
        raise CredentialError("credential values must not contain line breaks")
    try:
        existing = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    except (OSError, UnicodeError) as exc:
        raise CredentialError("could not read the Gravity credential file") from exc
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise CredentialError("the Gravity credential path must be a regular file")
    content = _updated_content(existing, updates, remove_keys)
    _atomic_write(path, content)


def _updated_content(
    existing: str,
    updates: Mapping[str, str],
    remove_keys: Collection[str],
) -> str:
    remaining = dict(updates)
    removed = set(remove_keys) - set(remaining)
    lines: list[str] = []
    for line in existing.splitlines():
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if stripped and "=" in stripped else None
        if key in removed:
            continue
        if key in remaining:
            lines.append(f"{key}={remaining.pop(key)}")
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    return "\n".join(lines).rstrip("\n") + "\n"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _restrict_secret_file(temporary)
        os.replace(temporary, path)
    except OSError as exc:
        raise CredentialError("could not atomically update the Gravity credential file") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _restrict_secret_file(path: Path) -> None:
    if os.name != "nt":  # pragma: no cover - exercised by Linux CI
        path.chmod(0o600)
        return
    domain = os.environ.get("USERDOMAIN", "").strip()
    if not domain or domain.upper() == "WORKGROUP":
        domain = os.environ.get("COMPUTERNAME", "").strip()
    username = os.environ.get("USERNAME", "").strip() or getpass.getuser()
    account = "\\".join(part for part in (domain, username) if part) or username
    try:
        result = subprocess.run(
            [
                "icacls.exe",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"{account}:(F)",
                "*S-1-5-18:(F)",
                "*S-1-5-32-544:(F)",
            ],
            check=False,
            capture_output=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CredentialError("could not restrict the Gravity credential file") from exc
    if result.returncode:
        raise CredentialError("could not restrict the Gravity credential file")


# Compatibility alias retained for existing internal tests and callers.
_atomic_update_env = atomic_update_env
