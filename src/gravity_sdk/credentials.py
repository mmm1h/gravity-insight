"""Credential loading and single-flight refresh for Gravity Insight."""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping
from zoneinfo import ZoneInfo

from .errors import AuthenticationError, CredentialError


GRAVITY_HOST = "https://api-insight.gravity-engine.com"
LOGIN_PATH = "/account_center/api/v1/user_login/v2/"
DEFAULT_ENV_PATH = Path(__file__).resolve().parents[3] / ".env.gravity.local"
TOKEN_KEYS = ("GRAVITY_AUTH_TOKEN", "GRAVITY_AUTHORIZATION")
EXPIRY_KEY = "GRAVITY_AUTH_TOKEN_EXPIRES_AT_ASIA_SHANGHAI"
UPDATED_KEY = "GRAVITY_AUTH_UPDATED_AT"
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _read_env_file(path: Path) -> dict[str, str]:
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


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    try:
        if re_is_number(text):
            parsed = datetime.fromtimestamp(float(text), timezone.utc)
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (OverflowError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(timezone.utc)


def re_is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class CredentialConfig:
    username: str | None = field(default=None, repr=False)
    password: str | None = field(default=None, repr=False)
    token: str | None = field(default=None, repr=False)
    expires_at: datetime | None = None
    updated_at: datetime | None = None
    token_source: str | None = None

    @classmethod
    def from_env(
        cls,
        path: Path = DEFAULT_ENV_PATH,
        environ: Mapping[str, str] | None = None,
    ) -> "CredentialConfig":
        file_values = _read_env_file(path)
        # Explicit mappings are deterministic overrides. Ambient process values can be
        # stale after the refresh workflow updates the file and user environment because
        # a child process cannot mutate its parent's already-inherited environment.
        environment = os.environ if environ is None else environ
        environment_values = _gravity_values(environment)
        values = dict(file_values)
        values.update(environment_values)
        token, token_values, token_source = _select_token_source(
            file_values, environment_values, ambient=environ is None
        )
        configured_expiry = _parse_datetime(token_values.get(EXPIRY_KEY))
        return cls(
            username=values.get("GRAVITY_USERNAME", "").strip() or None,
            password=values.get("GRAVITY_PASSWORD", "").strip() or None,
            token=token,
            expires_at=(_jwt_expiry(token) or configured_expiry) if token else configured_expiry,
            updated_at=_parse_datetime(token_values.get(UPDATED_KEY)),
            token_source=token_source,
        )


def _gravity_values(values: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in values.items() if key.startswith("GRAVITY_")}


def _select_token_source(
    file_values: Mapping[str, str], environment_values: Mapping[str, str], *, ambient: bool
) -> tuple[str | None, Mapping[str, str], str | None]:
    file_token = _token_from(file_values)
    environment_token = _token_from(environment_values)
    if (ambient and file_token and environment_token and file_token != environment_token
            and _file_credential_is_newer(file_values, environment_values)):
        return file_token, file_values, "credential_file"
    if environment_token:
        return environment_token, environment_values, "process_environment"
    return file_token, file_values, "credential_file" if file_token else None


def _token_from(values: Mapping[str, str]) -> str | None:
    return next(
        (
            values.get(key, "").strip()
            for key in TOKEN_KEYS
            if values.get(key, "").strip()
        ),
        None,
    )


def _file_credential_is_newer(
    file_values: Mapping[str, str], environment_values: Mapping[str, str]
) -> bool:
    file_updated = _parse_datetime(file_values.get(UPDATED_KEY))
    environment_updated = _parse_datetime(environment_values.get(UPDATED_KEY))
    if file_updated is not None:
        return environment_updated is None or file_updated > environment_updated
    file_token = _token_from(file_values)
    environment_token = _token_from(environment_values)
    file_expiry = _jwt_expiry(file_token) or _parse_datetime(file_values.get(EXPIRY_KEY)) if file_token else None
    environment_expiry = (
        _jwt_expiry(environment_token)
        or _parse_datetime(environment_values.get(EXPIRY_KEY))
        if environment_token
        else None
    )
    now = _now()
    return bool(
        file_expiry
        and file_expiry > now
        and environment_expiry
        and environment_expiry <= now
    )


@dataclass(frozen=True)
class Credential:
    token: str = field(repr=False)
    expires_at: datetime | None = None
    updated_at: datetime | None = None
    gravity_id: str | None = field(default=None, repr=False)
    company_id: str | None = field(default=None, repr=False)
    is_superuser: bool | None = field(default=None, repr=False)
    email: str | None = field(default=None, repr=False)

    def authorization_headers(self) -> dict[str, str]:
        headers = {"Authorization": self.token}
        if self.gravity_id is not None:
            headers["Gravity_Id"] = self.gravity_id
        if self.company_id is not None:
            headers["gravity_Cid"] = self.company_id
        if self.is_superuser is not None:
            headers["gravity_Super"] = "true" if self.is_superuser else "false"
        if self.email is not None:
            headers["gravity_Email"] = self.email
        return headers

    def expired(self, now: datetime, skew: timedelta) -> bool:
        return self.expires_at is not None and self.expires_at <= now + skew


LoginFunction = Callable[[str, str], Mapping[str, Any]]
LoginRequestFunction = Callable[[Mapping[str, Any], float], Mapping[str, Any]]


class CredentialProvider:
    """Load an existing token and coalesce concurrent account/password refreshes."""

    def __init__(
        self,
        env_path: Path = DEFAULT_ENV_PATH,
        *,
        environ: MutableMapping[str, str] | None = None,
        session: Any | None = None,
        login: LoginFunction | None = None,
        login_request: LoginRequestFunction | None = None,
        clock: Callable[[], datetime] = _now,
        expiry_skew: timedelta = timedelta(minutes=2),
        timeout: float = 30.0,
        free_login_day: int = 7,
        persist: bool = True,
    ) -> None:
        if free_login_day not in range(1, 8):
            raise ValueError("free_login_day must be between 1 and 7")
        if timeout <= 0:
            raise ValueError("credential timeout must be positive")
        self.env_path = Path(env_path)
        self._environ = environ
        self._session = session
        self._login = login
        self._login_request = login_request
        self._clock = clock
        self._expiry_skew = expiry_skew
        self._timeout = timeout
        self._free_login_day = free_login_day
        self._persist = persist
        self._condition = threading.Condition()
        self._refreshing = False
        self._generation = 0
        self._credential: Credential | None = None
        self._config: CredentialConfig | None = None

    @classmethod
    def from_env(cls, env_path: Path = DEFAULT_ENV_PATH, **kwargs: Any) -> "CredentialProvider":
        return cls(env_path, **kwargs)

    def _load(self) -> Credential | None:
        config = CredentialConfig.from_env(self.env_path, self._environ)
        self._config = config
        if not config.token:
            return None
        return Credential(config.token, config.expires_at, config.updated_at)

    def get(self, *, force_refresh: bool = False) -> Credential:
        return self._get(force_refresh=force_refresh, rejected_token=None)

    def _get(
        self,
        *,
        force_refresh: bool,
        rejected_token: str | None,
    ) -> Credential:
        with self._condition:
            if self._credential is None:
                self._credential = self._load()
            if (
                rejected_token is not None
                and self._usable(self._credential)
                and self._credential is not None
                and self._credential.token != rejected_token
            ):
                return self._credential
            start_generation = self._generation
            if not force_refresh and self._usable(self._credential):
                return self._credential  # type: ignore[return-value]
            while self._refreshing:
                self._condition.wait()
                if (
                    rejected_token is not None
                    and self._usable(self._credential)
                    and self._credential is not None
                    and self._credential.token != rejected_token
                ):
                    return self._credential
                if self._generation > start_generation and self._usable(self._credential):
                    return self._credential  # type: ignore[return-value]
                if not force_refresh and self._usable(self._credential):
                    return self._credential  # type: ignore[return-value]
            self._refreshing = True

        try:
            credential = self._perform_login()
            if self._persist:
                self._persist_credential(credential)
        except BaseException:
            with self._condition:
                self._refreshing = False
                self._condition.notify_all()
            raise
        with self._condition:
            self._credential = credential
            self._generation += 1
            self._refreshing = False
            self._condition.notify_all()
            return credential

    def refresh(self) -> Credential:
        return self.get(force_refresh=True)

    def refresh_if_rejected(self, rejected: Credential | str) -> Credential:
        """Refresh only if *rejected* is still the current token.

        This closes the staggered-401 race: a request that receives a late 401 for
        an old token reuses the credential already produced by another thread
        instead of starting a second login.
        """

        rejected_token = rejected.token if isinstance(rejected, Credential) else rejected
        if not isinstance(rejected_token, str) or not rejected_token:
            raise CredentialError("rejected Gravity credential is invalid")
        return self._get(force_refresh=True, rejected_token=rejected_token)

    def bind_http_runtime(
        self,
        session: Any,
        login_request: LoginRequestFunction,
    ) -> None:
        """Bind login to the same long-lived session and requester as reads."""

        if session is None or not callable(login_request):
            raise ValueError("a Gravity session and login requester are required")
        with self._condition:
            if self._refreshing:
                raise CredentialError("cannot replace Gravity HTTP state during refresh")
            self._session = session
            self._login_request = login_request

    def invalidate(self) -> None:
        with self._condition:
            if self._credential:
                self._credential = Credential(
                    self._credential.token,
                    self._clock() - timedelta(seconds=1),
                    self._credential.updated_at,
                )

    def authorization_headers(self) -> dict[str, str]:
        return self.get().authorization_headers()

    def _usable(self, credential: Credential | None) -> bool:
        return bool(credential and credential.token and not credential.expired(self._clock(), self._expiry_skew))

    def _perform_login(self) -> Credential:
        config = self._config or CredentialConfig.from_env(self.env_path, self._environ)
        self._config = config
        if not config.username or not config.password:
            raise CredentialError("Gravity credentials are missing or the token has expired")
        try:
            if self._login is not None:
                payload = self._login(config.username, config.password)
            else:
                payload = self._http_login(config.username, config.password)
        except CredentialError:
            raise
        except Exception as exc:
            raise AuthenticationError("Gravity login failed") from exc
        return self._credential_from_login(payload)

    def _http_login(self, username: str, password: str) -> Mapping[str, Any]:
        if self._session is None:
            try:
                import requests
            except ImportError as exc:  # pragma: no cover
                raise CredentialError("requests is required for Gravity login") from exc
            session = requests.Session()
        else:
            session = self._session
        body = {
            "action_type": "email",
            "username": username.strip(),
            "password": hashlib.md5(password.strip().encode("utf-8")).hexdigest(),
            "product_name": "turbo",
            "free_login_day": self._free_login_day,
        }
        if self._login_request is not None:
            try:
                payload = self._login_request(body, self._timeout)
            except CredentialError:
                raise
            except Exception as exc:
                raise AuthenticationError("Gravity login request failed") from exc
        else:
            try:
                response = session.request(
                    "POST",
                    GRAVITY_HOST + LOGIN_PATH,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "Origin": "https://web.gravity-engine.com",
                        "Referer": "https://web.gravity-engine.com/",
                    },
                    json=body,
                    timeout=self._timeout,
                    allow_redirects=False,
                )
            except Exception as exc:
                raise AuthenticationError("Gravity login request failed") from exc
            if getattr(response, "status_code", 500) != 200:
                raise AuthenticationError("Gravity login was rejected")
            try:
                payload = response.json()
            except (TypeError, ValueError) as exc:
                raise AuthenticationError("Gravity login returned invalid JSON") from exc
        if not isinstance(payload, Mapping):
            raise AuthenticationError("Gravity login returned an invalid envelope")
        return payload

    def _credential_from_login(self, payload: Mapping[str, Any]) -> Credential:
        if payload.get("code") not in (None, 0, 200):
            raise AuthenticationError("Gravity login was rejected")
        data = payload.get("data", payload)
        if not isinstance(data, Mapping):
            raise AuthenticationError("Gravity login returned an invalid envelope")
        user = data.get("user", data)
        if not isinstance(user, Mapping):
            raise AuthenticationError("Gravity login did not return a user context")
        token = user.get("Authorization") or user.get("authorization") or user.get("token")
        if not isinstance(token, str) or not token.strip():
            raise AuthenticationError("Gravity login did not return an authorization token")
        now = self._clock()
        explicit_expiry = _jwt_expiry(token) or _parse_datetime(
            str(user.get("expires_at") or data.get("expires_at") or "") or None
        )
        try:
            days = int(data.get("day", self._free_login_day))
        except (TypeError, ValueError):
            days = self._free_login_day
        expiry = explicit_expiry or now + timedelta(days=max(1, min(days, 7)))
        return Credential(
            token.strip(),
            expiry,
            now,
            str(user["id"]) if user.get("id") is not None else None,
            str(user["company_id"]) if user.get("company_id") is not None else None,
            bool(user["is_superuser"]) if user.get("is_superuser") is not None else None,
            str(user["email"]) if user.get("email") is not None else None,
        )

    def _persist_credential(self, credential: Credential) -> None:
        updated = credential.updated_at or self._clock()
        expiry = credential.expires_at
        updates = {
            "GRAVITY_AUTH_TOKEN": credential.token,
            EXPIRY_KEY: expiry.astimezone(SHANGHAI).isoformat(timespec="seconds") if expiry else "",
            UPDATED_KEY: updated.astimezone(SHANGHAI).isoformat(timespec="seconds"),
        }
        _atomic_update_env(self.env_path, updates)
        if self._environ is not None:
            self._environ.update(updates)


def _atomic_update_env(path: Path, updates: Mapping[str, str]) -> None:
    for value in updates.values():
        if "\n" in value or "\r" in value:
            raise CredentialError("credential values must not contain line breaks")
    try:
        existing = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    except (OSError, UnicodeError) as exc:
        raise CredentialError("could not read the Gravity credential file") from exc
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise CredentialError("the Gravity credential path must be a regular file")
    remaining = dict(updates)
    lines: list[str] = []
    for line in existing.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                lines.append(f"{key}={remaining.pop(key)}")
                continue
        lines.append(line)
    lines.extend(f"{key}={value}" for key, value in remaining.items())
    content = "\n".join(lines).rstrip("\n") + "\n"
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


def _jwt_expiry(token: str) -> datetime | None:
    """Read a JWT exp claim without trusting any other unsigned token content."""

    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")))
        exp = decoded.get("exp") if isinstance(decoded, Mapping) else None
        if isinstance(exp, bool) or not isinstance(exp, (int, float)):
            return None
        return datetime.fromtimestamp(exp, timezone.utc)
    except (UnicodeError, ValueError, OSError, json.JSONDecodeError):
        return None


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
