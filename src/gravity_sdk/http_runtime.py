"""Shared authenticated HTTP runtime for the controlled Gravity clients.

The runtime deliberately exposes profiles rather than hosts or origins.  Insight
requests are still authorized by their manifest policy before reaching this
module; SQL has one exact POST route.

``get_shared_runtime()`` (in ``shared_runtime``) is shared **per resolved
credential file** inside one process: that file's session, credential
provider, and connection pool. The 10 rps host limiter and 25-total/24-business
Governor stay process-wide so two accounts in one process cannot multiply
upstream traffic. Different credential files no longer reuse one runtime.
"""

from __future__ import annotations

import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Collection, Mapping, MutableMapping

from .content_encoding import ACCEPT_ENCODING
from .adaptive_governor import (
    AdaptiveRequestGovernor,
    SQL_CAPACITY,
    get_process_governor,
)
from .adaptive_governor_contract import raise_request_failure
from .credentials import (
    GRAVITY_HOST,
    CredentialProvider,
    validated_login_payload,
)
from .errors import (
    AuthenticationError,
    PermissionUnavailableError,
    PolicyViolation,
    SqlValidationError,
    TransportError,
)
from .http_retry import (
    is_retryable_exception as _is_retryable_exception,
    response_payload as _response_payload,
    retry_delay as _retry_delay,
    unit_random as _unit_random,
)
from .host_rate_limiter import (
    DEFAULT_REQUESTS_PER_SECOND,
    HostRateLimiter,
)
from .http_runtime_observation import perform_runtime_attempt
from .paths import STATE_ROOT
from .process_limits import MAX_CONCURRENCY
from .runtime_scope import resolve_env_path
from .receipt import (
    authorized_request_receipt_context,
    request_attempt_context,
    request_receipt_context,
)
from .registry import _consume_authorized_request
from .runtime_principal import (
    current_principal_id as _current_principal_id,
    refresh_if_rejected as _refresh_if_rejected,
)


DEFAULT_CONCURRENCY = 6
MAX_SQL_CONCURRENCY = SQL_CAPACITY
# One spare connection allows a login on the 401 recovery path while twenty-four
# business requests are in flight.
CONNECTION_POOL_SIZE = MAX_CONCURRENCY + 1
FALLBACK_CHROME_MAJOR = 150
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_AUTH_HEADER_NAMES = frozenset(
    {"Authorization", "Gravity_Id", "gravity_Cid", "gravity_Super", "gravity_Email"}
)


@dataclass(frozen=True)
class RequestProfile:
    """An immutable, repository-owned route and browser-origin policy."""

    name: str
    origin: str
    referer: str
    methods: frozenset[str]
    exact_paths: frozenset[str] = field(default_factory=frozenset)
    exact_routes: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    path_prefixes: tuple[str, ...] = ()

    def accepts(self, method: str, path: str) -> bool:
        return method in self.methods and (
            (method, path) in self.exact_routes
            or path in self.exact_paths
            or any(path.startswith(prefix) for prefix in self.path_prefixes)
        )


INSIGHT_PROFILE = RequestProfile(
    "insight",
    "https://web.gravity-engine.com",
    "https://web.gravity-engine.com/",
    frozenset({"GET", "POST"}),
    path_prefixes=("/account_center/api/", "/apprank/api/", "/report/", "/turbo_engine/"),
)
SQL_PROFILE = RequestProfile(
    "sql",
    "https://bi.gravity-engine.com",
    "https://bi.gravity-engine.com/",
    frozenset({"POST"}),
    exact_paths=frozenset({"/custom_sql/api/sql/execute"}),
)
_LOGIN_PROFILE = RequestProfile(
    "login",
    "https://web.gravity-engine.com",
    "https://web.gravity-engine.com/",
    frozenset({"POST"}),
    exact_paths=frozenset({"/account_center/api/v1/user_login/v2/"}),
)
_PROFILES = {
    profile.name: profile for profile in (INSIGHT_PROFILE, SQL_PROFILE, _LOGIN_PROFILE)
}


def _detect_chrome_major() -> int:
    """Return an installed Chrome major, or a deterministic browser-like fallback."""

    override = os.environ.get("GRAVITY_CHROME_MAJOR", "").strip()
    if override.isdigit() and 100 <= int(override) <= 999:
        return int(override)
    if os.name == "nt":  # pragma: no branch - platform dependent
        try:
            import winreg

            locations = (
                (winreg.HKEY_CURRENT_USER, r"Software\Google\Chrome\BLBeacon"),
                (winreg.HKEY_LOCAL_MACHINE, r"Software\Google\Chrome\BLBeacon"),
                (
                    winreg.HKEY_LOCAL_MACHINE,
                    r"Software\WOW6432Node\Google\Chrome\BLBeacon",
                ),
            )
            for hive, key_name in locations:
                try:
                    with winreg.OpenKey(hive, key_name) as key:
                        version = str(winreg.QueryValueEx(key, "version")[0])
                except OSError:
                    continue
                match = re.match(r"^(\d+)\.", version)
                if match and 100 <= int(match.group(1)) <= 999:
                    return int(match.group(1))
        except (ImportError, OSError):
            pass
    return FALLBACK_CHROME_MAJOR


def browser_headers(chrome_major: int | None = None) -> dict[str, str]:
    """Build one internally consistent set of Chrome request headers."""

    major = chrome_major or _detect_chrome_major()
    if isinstance(major, bool) or not isinstance(major, int) or not 100 <= major <= 999:
        raise ValueError("Chrome major must be an integer between 100 and 999")
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 "
            "Safari/537.36"
        ),
        "sec-ch-ua": (
            f'"Not_A Brand";v="99", "Chromium";v="{major}", '
            f'"Google Chrome";v="{major}"'
        ),
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-site",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": ACCEPT_ENCODING,
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
    }


BROWSER_HEADERS: Mapping[str, str] = MappingProxyType(browser_headers(_detect_chrome_major()))


@dataclass(frozen=True)
class RuntimeResponse:
    status_code: int
    payload: Any
    fetched_at: str
    headers: Mapping[str, str]
    retry_after_ms: int | None = None


class _GravityRequester:
    """Low-level request executor used only through repository-owned profiles."""

    def __init__(
        self,
        session: Any,
        limiter: HostRateLimiter,
        *,
        timeout: float = 120.0,
        attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
        wall_clock: Callable[[], datetime] | None = None,
        random_source: Callable[[], float] = random.random,
        receipt_root: Path = STATE_ROOT,
        observation_scope_key: str = "local-runtime",
        observation_clock: Callable[[], float] = time.monotonic,
        governor: AdaptiveRequestGovernor | None = None,
    ) -> None:
        if timeout <= 0 or attempts < 1 or attempts > 5:
            raise ValueError("invalid Gravity timeout or retry count")
        self.session = session
        self.limiter = limiter
        self.timeout = timeout
        self.attempts = attempts
        self.sleeper = sleeper
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self.random_source = random_source
        self.receipt_root = receipt_root
        self.observation_scope_key = observation_scope_key
        self.observation_clock = observation_clock
        self.governor = governor if governor is not None else get_process_governor()
        self.business_limit = self.governor.business_capacity
        self.sql_limit = self.governor.sql_capacity

    def request(
        self,
        profile: RequestProfile,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        timeout: float | None = None,
        attempts: int | None = None,
        receipt_context: Mapping[str, Any] | None = None,
    ) -> RuntimeResponse:
        profile = _validated_profile(profile)
        normalized_method = method.upper()
        if not _safe_path(path) or not profile.accepts(normalized_method, path):
            raise PolicyViolation("Gravity request is outside its controlled route profile")
        _validate_profile_payload(profile, normalized_method, params, json_body)
        request_timeout, request_attempts = (self.timeout if timeout is None else timeout), (self.attempts if attempts is None else attempts)
        if request_timeout <= 0 or request_attempts < 1 or request_attempts > 5:
            raise ValueError("invalid Gravity timeout or retry count")
        extra_headers = dict(headers or {})
        if set(extra_headers) - _AUTH_HEADER_NAMES:
            raise PolicyViolation("Gravity requester accepts only credential headers")
        request_headers = {
            **BROWSER_HEADERS, **extra_headers,
            "Origin": profile.origin, "Referer": profile.referer,
        }
        for attempt in range(request_attempts):
            retry_after_ms = None
            rate_delay = self.limiter.acquire(GRAVITY_HOST, self.sleeper)
            attempt_receipt = request_attempt_context(receipt_context, attempt)
            try:
                response = perform_runtime_attempt(
                    self, profile, normalized_method, path, request_headers,
                    params, json_body, request_timeout, request_attempts,
                    attempt_receipt, rate_delay,
                )
            except Exception as exc:
                if attempt + 1 < request_attempts and _is_retryable_exception(exc):
                    self.sleeper(self._backoff(attempt))
                    continue
                raise_request_failure(exc)
            status = int(getattr(response, "status_code", 0))
            if status == 429:
                delay = _retry_delay(
                    response,
                    attempt,
                    wall_clock=self.wall_clock,
                    random_source=self.random_source,
                )
                self.limiter.defer(GRAVITY_HOST, delay)
                retry_after_ms = int(delay * 1_000)
            if status in _RETRYABLE_STATUS and attempt + 1 < request_attempts:
                if status != 429:
                    self.sleeper(self._backoff(attempt))
                continue
            payload = _response_payload(response)
            fetched_at = (
                self.wall_clock()
                .astimezone(timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )
            raw_headers = getattr(response, "headers", {})
            response_headers = (
                {str(key): str(value) for key, value in raw_headers.items()}
                if isinstance(raw_headers, Mapping)
                else {}
            )
            return RuntimeResponse(status, payload, fetched_at, response_headers, retry_after_ms)
        raise TransportError("Gravity request failed after bounded retries")

    def login(self, body: Mapping[str, Any], timeout: float) -> Mapping[str, Any]:
        response = self.request(
            _LOGIN_PROFILE,
            "POST",
            "/account_center/api/v1/user_login/v2/",
            json_body=body,
            timeout=timeout,
            receipt_context=request_receipt_context(
                operation_id="authentication",
                method="POST",
                path="/account_center/api/v1/user_login/v2/",
                body=body,
                effect="login",
            ),
        )
        return validated_login_payload(response.status_code, response.payload, response.retry_after_ms)

    def _backoff(self, attempt: int) -> float:
        base = float(min(2 ** (attempt + 1), 8))
        return base * (1.0 + 0.2 * _unit_random(self.random_source))


class GravityHttpRuntime:
    """Long-lived session, credentials, requester, and limiter shared by clients."""

    def __init__(
        self,
        *,
        env_path: Path | None = None,
        session: Any | None = None,
        credentials: CredentialProvider | Any | None = None,
        limiter: HostRateLimiter | None = None,
        requests_per_second: float = DEFAULT_REQUESTS_PER_SECOND,
        timeout: float = 120.0,
        attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
        rate_clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] | None = None,
        random_source: Callable[[], float] = random.random,
        interval_jitter_ratio: float = 0.1,
        governor: AdaptiveRequestGovernor | None = None,
        persist_credentials: bool = True,
        environ: MutableMapping[str, str] | None = None,
        receipt_root: Path = STATE_ROOT,
        isolated: bool = False,
        observation_scope_key: str | None = None,
    ) -> None:
        selected_env, resolved_isolated = resolve_env_path(env_path)
        if isolated:
            resolved_isolated = True
        env_path = selected_env
        isolated = resolved_isolated
        selected_observation_scope = observation_scope_key or (
            f"local-runtime:{id(self)}:{time.monotonic_ns()}"
        )
        self.__session = session or _build_session()
        self.__limiter = limiter or HostRateLimiter(
            clock=rate_clock,
            random_source=random_source,
            interval_jitter_ratio=interval_jitter_ratio,
        )
        self.__limiter.configure(GRAVITY_HOST, requests_per_second)
        self.__governor = (
            governor if governor is not None else get_process_governor()
        )
        self.__requester = _GravityRequester(
            self.__session,
            self.__limiter,
            timeout=timeout,
            attempts=attempts,
            sleeper=sleeper,
            wall_clock=wall_clock,
            random_source=random_source,
            receipt_root=receipt_root,
            observation_scope_key=selected_observation_scope,
            observation_clock=rate_clock,
            governor=self.__governor,
        )
        self.__observation_scope_key = selected_observation_scope
        if credentials is None:
            self.__credentials = CredentialProvider.from_env(
                env_path,
                environ=environ,
                session=self.__session,
                login_request=self.__requester.login,
                persist=persist_credentials,
                isolated=isolated,
            )
        else:
            self.__credentials = credentials
            if isinstance(credentials, CredentialProvider):
                credentials.bind_http_runtime(
                    self.__session,
                    self.__requester.login,
                )

    def current_principal_id(self) -> str | None:
        """Expose only the authenticated upstream account identifier."""

        return _current_principal_id(self.__credentials)

    def governor_observations(
        self, *, after_sequence: int = 0, limit: int = 1_000
    ) -> dict[str, Any]:
        """Return this private Runtime partition without performing I/O."""

        from .governor_observation import observation_snapshot

        return observation_snapshot(
            self.__observation_scope_key,
            after_sequence=after_sequence,
            limit=limit,
        )

    def adaptive_governor_snapshot(self) -> dict[str, Any]:
        """Return this private Runtime scope's active policy without I/O."""

        return self.__governor.snapshot(self.__observation_scope_key)

    def request(
        self,
        profile: RequestProfile,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        semantic_auth_codes: Collection[int] = (),
        timeout: float | None = None,
        attempts: int | None = None,
    ) -> RuntimeResponse:
        profile = _validated_profile(profile)
        if profile is not SQL_PROFILE:
            raise PolicyViolation(
                "Insight requests require a manifest-authorized transport"
            )
        return self._authenticated_request(
            profile,
            method,
            path,
            params=params,
            json_body=json_body,
            semantic_auth_codes=semantic_auth_codes,
            timeout=timeout,
            attempts=attempts,
            receipt_context=request_receipt_context(
                operation_id="sql.query",
                method=method,
                path=path,
                query=params,
                body=json_body,
                effect="read",
                coalesce_safe=True,
            ),
        )

    def _request_insight(
        self,
        method: str,
        path: str,
        *,
        policy_authorization: object,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        semantic_auth_codes: Collection[int] = (),
        timeout: float | None = None,
        attempts: int | None = None,
    ) -> RuntimeResponse:
        """Consume a PolicyEngine receipt at the final pre-network boundary."""

        wire_query, wire_body = _consume_authorized_request(
            policy_authorization,
            method=method,
            path=path,
            query=params,
            body=json_body,
        )
        receipt_context = authorized_request_receipt_context(
            policy_authorization,
            method=method,
            path=path,
            query=wire_query,
            body=wire_body,
        )
        return self._authenticated_request(
            INSIGHT_PROFILE,
            method,
            path,
            params=wire_query,
            json_body=wire_body or None,
            semantic_auth_codes=semantic_auth_codes,
            timeout=timeout,
            attempts=attempts,
            receipt_context=receipt_context,
        )

    def _authenticated_request(
        self,
        profile: RequestProfile,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        json_body: Mapping[str, Any] | None,
        semantic_auth_codes: Collection[int],
        timeout: float | None,
        attempts: int | None,
        receipt_context: Mapping[str, Any],
    ) -> RuntimeResponse:
        refreshed = False
        while True:
            credential = self.__credentials.get()
            response = self.__requester.request(
                profile,
                method,
                path,
                headers=credential.authorization_headers(),
                params=params,
                json_body=json_body,
                timeout=timeout,
                attempts=attempts,
                receipt_context={**receipt_context, "retry": refreshed},
            )
            semantic_code = (
                response.payload.get("code")
                if isinstance(response.payload, Mapping)
                else None
            )
            rejected = (
                response.status_code in {401, 403}
                or semantic_code in semantic_auth_codes
            )
            if rejected and not refreshed:
                _refresh_if_rejected(self.__credentials, credential)
                refreshed = True
                continue
            if rejected:
                if response.status_code == 403:
                    raise PermissionUnavailableError(
                        "the authenticated Gravity account cannot read this capability"
                    )
                raise AuthenticationError(
                    "Gravity authorization is invalid or expired"
                )
            return response


def _build_session() -> Any:
    try:
        import requests
        from requests.adapters import HTTPAdapter
    except ImportError as exc:  # pragma: no cover
        raise TransportError("requests is required for Gravity") from exc
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    adapter = HTTPAdapter(
        pool_connections=CONNECTION_POOL_SIZE,
        pool_maxsize=CONNECTION_POOL_SIZE,
        pool_block=True,
        max_retries=0,
    )
    session.mount("https://", adapter)
    return session


def _validated_profile(profile: RequestProfile) -> RequestProfile:
    canonical = _PROFILES.get(getattr(profile, "name", ""))
    if canonical is not profile:
        raise PolicyViolation("Gravity request profile is not repository-owned")
    return canonical


def _safe_path(path: str) -> bool:
    return (
        isinstance(path, str)
        and path.startswith("/")
        and not path.startswith("//")
        and "?" not in path
        and "#" not in path
        and "\\" not in path
        and ".." not in path.split("/")
    )


def _validate_profile_payload(
    profile: RequestProfile,
    method: str,
    params: Mapping[str, Any] | None,
    json_body: Mapping[str, Any] | None,
) -> None:
    if method == "GET" and json_body is not None and profile is not INSIGHT_PROFILE:
        raise PolicyViolation("controlled GET requests cannot send a JSON body")
    if profile is not SQL_PROFILE:
        return
    if params:
        raise SqlValidationError(
            "Gravity SQL must omit query parameters; send only the JSON body",
            field="params",
        )
    if not isinstance(json_body, Mapping) or set(json_body) != {"sql", "tabId"}:
        raise SqlValidationError(
            "Gravity SQL body must contain only sql and tabId",
            field="sql",
        )
    sql = json_body.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise SqlValidationError(
            "Gravity SQL text must be a non-empty string",
            field="sql",
        )
    if json_body.get("tabId") != "1":
        raise SqlValidationError(
            "Gravity SQL tabId must be the fixed value 1",
            field="tabId",
        )


__all__ = [
    "MAX_CONCURRENCY",
    "SQL_PROFILE",
]
