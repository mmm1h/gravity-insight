"""Shared authenticated HTTP runtime for the controlled Gravity clients.

The runtime deliberately exposes profiles rather than hosts or origins.  Insight
requests are still authorized by their manifest policy before reaching this
module; SQL has one exact POST route.  Both profiles consequently share the same
session, credential provider, connection pool, and per-host rate-limit bucket.
"""

from __future__ import annotations

import email.utils
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Collection, Mapping, MutableMapping
from urllib.parse import urlsplit

from .content_encoding import ACCEPT_ENCODING
from .credentials import (
    DEFAULT_ENV_PATH,
    GRAVITY_HOST,
    Credential,
    CredentialProvider,
)
from .errors import (
    AuthenticationError,
    CredentialError,
    PermissionUnavailableError,
    PolicyViolation,
    SqlValidationError,
    TransportError,
)
from .registry import _consume_authorized_request


DEFAULT_REQUESTS_PER_SECOND = 10.0
MAX_REQUESTS_PER_SECOND = 100.0
DEFAULT_CONCURRENCY = 6
MAX_CONCURRENCY = 24
MAX_SQL_CONCURRENCY = 2
# One spare connection allows a login on the 401 recovery path while twenty-four
# business requests are in flight.
CONNECTION_POOL_SIZE = MAX_CONCURRENCY + 1
FALLBACK_CHROME_MAJOR = 150
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_PROCESS_BUSINESS_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENCY)
_PROCESS_SQL_SLOTS = threading.BoundedSemaphore(MAX_SQL_CONCURRENCY)
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
    exact_routes=frozenset({("GET", "/account_center/api/v1/user/list/")}),
    path_prefixes=("/turbo_engine/", "/report/"),
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


@dataclass
class _HostBucket:
    requests_per_second: float
    lock: threading.Lock = field(default_factory=threading.Lock)
    next_at: float = 0.0
    cooldown_until: float = 0.0
    cooldown_generation: int = 0


class HostRateLimiter:
    """Thread-safe proactive limiter with an independent bucket for each host."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        random_source: Callable[[], float] = random.random,
        interval_jitter_ratio: float = 0.1,
    ) -> None:
        if not 0 <= interval_jitter_ratio <= 1:
            raise ValueError("rate-limit jitter ratio must be between 0 and 1")
        self._clock = clock
        self._random = random_source
        self._jitter_ratio = interval_jitter_ratio
        self._buckets_lock = threading.Lock()
        self._buckets: dict[str, _HostBucket] = {}

    def configure(self, host: str, requests_per_second: float) -> None:
        key = _canonical_host(host)
        rate = _validated_rate(requests_per_second)
        with self._buckets_lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                self._buckets[key] = _HostBucket(rate)
            elif bucket.requests_per_second != rate:
                raise ValueError("a Gravity host cannot use conflicting rate-limit quotas")

    def acquire(self, host: str, sleeper: Callable[[float], None] = time.sleep) -> float:
        """Reserve under lock, wait outside it, and honor late server cooldowns."""

        bucket = self._bucket(host)
        with bucket.lock:
            now = self._clock()
            slot = max(now, bucket.next_at, bucket.cooldown_until)
            interval = 1.0 / bucket.requests_per_second
            jitter = interval * self._jitter_ratio * _unit_random(self._random)
            bucket.next_at = slot + interval + jitter
            delay = max(0.0, slot - now)
            cooldown_generation = bucket.cooldown_generation
        total_delay = delay
        if delay:
            sleeper(delay)

        # A concurrent 429 may publish a cooldown after this caller reserved its
        # original slot. Re-reserve only when the generation changes, keeping
        # every sleep outside the bucket lock and preserving post-cooldown spacing.
        while True:
            with bucket.lock:
                if cooldown_generation == bucket.cooldown_generation:
                    return total_delay
                cooldown_generation = bucket.cooldown_generation
                now = self._clock()
                slot = max(now, bucket.next_at, bucket.cooldown_until)
                interval = 1.0 / bucket.requests_per_second
                jitter = interval * self._jitter_ratio * _unit_random(self._random)
                bucket.next_at = slot + interval + jitter
                delay = max(0.0, slot - now)
            total_delay += delay
            if delay:
                sleeper(delay)

    def defer(self, host: str, delay: float) -> None:
        """Publish a server-directed cooldown to all callers of this host."""

        if delay <= 0:
            return
        bucket = self._bucket(host)
        with bucket.lock:
            proposed = self._clock() + float(delay)
            if proposed > bucket.cooldown_until:
                bucket.cooldown_until = proposed
                bucket.next_at = max(bucket.next_at, proposed)
                bucket.cooldown_generation += 1

    def _bucket(self, host: str) -> _HostBucket:
        key = _canonical_host(host)
        with self._buckets_lock:
            bucket = self._buckets.get(key)
        if bucket is None:
            raise ValueError("Gravity host rate limit was not configured")
        return bucket


@dataclass(frozen=True)
class RuntimeResponse:
    status_code: int
    payload: Any
    fetched_at: str
    headers: Mapping[str, str]


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
    ) -> RuntimeResponse:
        profile = _validated_profile(profile)
        normalized_method = method.upper()
        if not _safe_path(path) or not profile.accepts(normalized_method, path):
            raise PolicyViolation("Gravity request is outside its controlled route profile")
        _validate_profile_payload(profile, normalized_method, params, json_body)
        request_timeout = self.timeout if timeout is None else timeout
        request_attempts = self.attempts if attempts is None else attempts
        if request_timeout <= 0 or request_attempts < 1 or request_attempts > 5:
            raise ValueError("invalid Gravity timeout or retry count")
        extra_headers = dict(headers or {})
        if set(extra_headers) - _AUTH_HEADER_NAMES:
            raise PolicyViolation("Gravity requester accepts only credential headers")
        request_headers = {
            **BROWSER_HEADERS,
            **extra_headers,
            "Origin": profile.origin,
            "Referer": profile.referer,
        }
        for attempt in range(request_attempts):
            self.limiter.acquire(GRAVITY_HOST, self.sleeper)
            try:
                response = self.session.request(
                    normalized_method,
                    GRAVITY_HOST + path,
                    headers=request_headers,
                    params=dict(params or {}),
                    json=dict(json_body) if json_body is not None else None,
                    timeout=request_timeout,
                    allow_redirects=False,
                )
            except Exception as exc:
                if attempt + 1 < request_attempts and _is_retryable_exception(exc):
                    self.sleeper(self._backoff(attempt))
                    continue
                raise TransportError(
                    "Gravity request failed before a response was received"
                ) from exc
            status = int(getattr(response, "status_code", 0))
            if status == 429:
                delay = _retry_delay(
                    response,
                    attempt,
                    wall_clock=self.wall_clock,
                    random_source=self.random_source,
                )
                self.limiter.defer(GRAVITY_HOST, delay)
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
            return RuntimeResponse(status, payload, fetched_at, response_headers)
        raise TransportError("Gravity request failed after bounded retries")

    def login(self, body: Mapping[str, Any], timeout: float) -> Mapping[str, Any]:
        response = self.request(
            _LOGIN_PROFILE,
            "POST",
            "/account_center/api/v1/user_login/v2/",
            json_body=body,
            timeout=timeout,
        )
        if response.status_code != 200:
            raise AuthenticationError("Gravity login was rejected")
        if response.payload is None:
            raise AuthenticationError("Gravity login returned invalid JSON")
        return response.payload

    def _backoff(self, attempt: int) -> float:
        base = float(min(2 ** (attempt + 1), 8))
        return base * (1.0 + 0.2 * _unit_random(self.random_source))


class GravityHttpRuntime:
    """Long-lived session, credentials, requester, and limiter shared by clients."""

    def __init__(
        self,
        *,
        env_path: Path = DEFAULT_ENV_PATH,
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
        business_slots: threading.BoundedSemaphore | None = None,
        sql_slots: threading.BoundedSemaphore | None = None,
        persist_credentials: bool = True,
        environ: MutableMapping[str, str] | None = None,
    ) -> None:
        self.__session = session or _build_session()
        self.__limiter = limiter or HostRateLimiter(
            clock=rate_clock,
            random_source=random_source,
            interval_jitter_ratio=interval_jitter_ratio,
        )
        self.__limiter.configure(GRAVITY_HOST, requests_per_second)
        self.__business_slots = business_slots or _PROCESS_BUSINESS_SLOTS
        self.__sql_slots = sql_slots or _PROCESS_SQL_SLOTS
        self.__requester = _GravityRequester(
            self.__session,
            self.__limiter,
            timeout=timeout,
            attempts=attempts,
            sleeper=sleeper,
            wall_clock=wall_clock,
            random_source=random_source,
        )
        if credentials is None:
            self.__credentials = CredentialProvider.from_env(
                env_path,
                environ=environ,
                session=self.__session,
                login_request=self.__requester.login,
                persist=persist_credentials,
            )
        else:
            self.__credentials = credentials
            if isinstance(credentials, CredentialProvider):
                credentials.bind_http_runtime(
                    self.__session,
                    self.__requester.login,
                )

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
        return self._authenticated_request(
            INSIGHT_PROFILE,
            method,
            path,
            params=wire_query,
            json_body=wire_body or None,
            semantic_auth_codes=semantic_auth_codes,
            timeout=timeout,
            attempts=attempts,
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
    ) -> RuntimeResponse:
        is_sql = profile is SQL_PROFILE
        if is_sql:
            self.__sql_slots.acquire()
        try:
            self.__business_slots.acquire()
            try:
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
            finally:
                self.__business_slots.release()
        finally:
            if is_sql:
                self.__sql_slots.release()


_SHARED_LOCK = threading.Lock()
_SHARED_RUNTIME: GravityHttpRuntime | None = None
_SHARED_ENV_PATH: Path | None = None
_PROCESS_LIMITER = HostRateLimiter()


def get_shared_runtime(
    *,
    env_path: Path = DEFAULT_ENV_PATH,
    requests_per_second: float | None = None,
    timeout: float = 120.0,
    attempts: int = 3,
) -> GravityHttpRuntime:
    """Return the process-wide runtime used by both Insight and SQL clients."""

    global _SHARED_RUNTIME, _SHARED_ENV_PATH
    resolved_path = Path(env_path).resolve()
    rate = (
        _rate_from_environment()
        if requests_per_second is None
        else _validated_rate(requests_per_second)
    )
    with _SHARED_LOCK:
        if _SHARED_RUNTIME is None:
            _SHARED_RUNTIME = GravityHttpRuntime(
                env_path=resolved_path,
                limiter=_PROCESS_LIMITER,
                requests_per_second=rate,
                timeout=timeout,
                attempts=attempts,
            )
            _SHARED_ENV_PATH = resolved_path
        elif _SHARED_ENV_PATH != resolved_path:
            raise CredentialError(
                "the process-wide Gravity runtime already uses another credential file"
            )
        else:
            _PROCESS_LIMITER.configure(GRAVITY_HOST, rate)
        return _SHARED_RUNTIME


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
        raise SqlValidationError("Gravity SQL does not accept query parameters")
    if not isinstance(json_body, Mapping) or set(json_body) != {"sql", "tabId"}:
        raise SqlValidationError("Gravity SQL body must contain only sql and tabId")
    sql = json_body.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        raise SqlValidationError("Gravity SQL text must be a non-empty string")
    if json_body.get("tabId") != "1":
        raise SqlValidationError("Gravity SQL tabId is fixed")


def _canonical_host(host: str) -> str:
    parsed = urlsplit(host)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Gravity rate-limit host must be an HTTPS origin")
    port = f":{parsed.port}" if parsed.port else ""
    return f"https://{parsed.hostname.lower()}{port}"


def _validated_rate(value: float) -> float:
    if isinstance(value, bool):
        raise ValueError("requests_per_second must be numeric")
    try:
        rate = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("requests_per_second must be numeric") from exc
    if not 0 < rate <= MAX_REQUESTS_PER_SECOND:
        raise ValueError(
            f"requests_per_second must be greater than 0 and at most {MAX_REQUESTS_PER_SECOND:g}"
        )
    return rate


def _rate_from_environment() -> float:
    value = os.environ.get("GRAVITY_REQUESTS_PER_SECOND", "").strip()
    return DEFAULT_REQUESTS_PER_SECOND if not value else _validated_rate(value)


def _response_payload(response: Any) -> Any:
    try:
        return response.json()
    except (TypeError, ValueError):
        return None


def _refresh_if_rejected(provider: Any, credential: Credential) -> Credential:
    refresh = getattr(provider, "refresh_if_rejected", None)
    if callable(refresh):
        return refresh(credential)
    return provider.refresh()


def _is_retryable_exception(exc: BaseException) -> bool:
    try:
        import requests
    except ImportError:  # pragma: no cover
        return isinstance(exc, (TimeoutError, OSError))
    return isinstance(exc, (requests.Timeout, requests.ConnectionError))


def _retry_delay(
    response: Any,
    attempt: int,
    *,
    wall_clock: Callable[[], datetime],
    random_source: Callable[[], float],
) -> float:
    value = getattr(response, "headers", {}).get("Retry-After")
    if value:
        try:
            minimum = max(0.0, min(float(value), 30.0))
        except (TypeError, ValueError):
            try:
                retry_at = email.utils.parsedate_to_datetime(value)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                minimum = max(
                    0.0,
                    min((retry_at - wall_clock()).total_seconds(), 30.0),
                )
            except (TypeError, ValueError, OverflowError):
                minimum = -1.0
        if minimum >= 0:
            # Positive-only jitter never retries earlier than Retry-After.
            return minimum + min(1.0, max(0.05, minimum * 0.1)) * _unit_random(
                random_source
            )
    base = float(min(2 ** (attempt + 1), 8))
    return base * (1.0 + 0.2 * _unit_random(random_source))


def _unit_random(source: Callable[[], float]) -> float:
    try:
        value = float(source())
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("random source must return a number") from exc
    return max(0.0, min(value, 1.0))


__all__ = [
    "SQL_PROFILE",
    "get_shared_runtime",
]
