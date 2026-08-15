"""Manifest-authorized Insight adapter over the shared Gravity HTTP runtime."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .credentials import CredentialProvider, GRAVITY_HOST
from .errors import (
    AuthenticationError,
    PermissionUnavailableError,
    PolicyViolation,
    RateLimitedError,
    TransportError,
    UnknownOperationError,
)
from .http_runtime import GravityHttpRuntime, HostRateLimiter
from .models import OperationSpec
from .registry import PolicyEngine


_AUTH_CODES = frozenset({2001, 10000, 10001})


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    payload: Mapping[str, Any]
    fetched_at: str


class Transport:
    """Transport for manifest-owned reads and separately authorized mutations."""

    def __init__(
        self,
        credentials: CredentialProvider | Any | None = None,
        *,
        policy: PolicyEngine,
        session: Any | None = None,
        timeout: float = 120.0,
        attempts: int = 3,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
        host: str = GRAVITY_HOST,
        requests_per_second: float = 10.0,
        rate_clock: Callable[[], float] = time.monotonic,
        random_source: Callable[[], float] = random.random,
        runtime: GravityHttpRuntime | None = None,
        limiter: HostRateLimiter | None = None,
    ) -> None:
        if not isinstance(policy, PolicyEngine):
            raise TypeError("Gravity Insight transport requires an operation policy")
        if host.rstrip("/") != GRAVITY_HOST:
            raise PolicyViolation("Gravity Insight transport host is fixed")
        if runtime is not None and (
            session is not None or limiter is not None or credentials is not None
        ):
            raise ValueError("an injected runtime owns its session, credentials, and limiter")
        if runtime is None:
            if credentials is None:
                raise TypeError("Gravity Insight transport requires credentials")
            # Explicit clocks/sleepers are test seams and intentionally get a local
            # deterministic limiter. Production clients obtain one process runtime.
            interval_jitter_ratio = (
                0.0
                if sleeper is not time.sleep or rate_clock is not time.monotonic
                else 0.1
            )
            runtime = GravityHttpRuntime(
                session=session,
                credentials=credentials,
                limiter=limiter,
                timeout=timeout,
                attempts=attempts,
                sleeper=sleeper,
                rate_clock=rate_clock,
                wall_clock=clock,
                random_source=random_source,
                interval_jitter_ratio=interval_jitter_ratio,
                requests_per_second=requests_per_second,
                persist_credentials=False,
            )
        self._policy = policy
        self.timeout = timeout
        self.attempts = attempts
        self.sleeper = sleeper
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.host = GRAVITY_HOST
        self._runtime = runtime

    def request(
        self,
        method: str,
        path: str,
        *,
        operation: OperationSpec,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        authorization: object | None = None,
    ) -> TransportResponse:
        method = method.upper()
        try:
            registered = self._policy.authorize_operation(operation.operation_id)
        except UnknownOperationError:
            raise PolicyViolation("transport operation is not owned by its registry") from None
        if registered != operation:
            raise PolicyViolation("transport operation is not owned by its registry")
        self._policy.authorize_request(operation, method, path)
        if method != operation.upstream_method or method not in {"GET", "POST"}:
            raise PolicyViolation("request method is not allowed by the operation contract")
        if not path.startswith("/") or path.startswith("//") or not operation.matches_path(path):
            raise PolicyViolation("request path is not allowed by the operation contract")
        if body is not None and not isinstance(body, Mapping):
            raise PolicyViolation("operation body must be an object")
        response = self._runtime._request_insight(
            method,
            path,
            policy_authorization=authorization,
            params=query,
            json_body=body,
            semantic_auth_codes=_AUTH_CODES,
            timeout=self.timeout,
            attempts=self.attempts,
        )
        status = response.status_code
        if 300 <= status < 400:
            raise TransportError(
                "Gravity request returned a redirect; cross-origin redirects are blocked"
            )
        _raise_for_status(status, response.retry_after_ms)
        if not isinstance(response.payload, Mapping):
            raise TransportError("Gravity returned an unexpected JSON envelope")
        if response.payload.get("code") in _AUTH_CODES:
            raise AuthenticationError("Gravity authorization is invalid or expired")
        return TransportResponse(status, response.payload, response.fetched_at)

    def mutate(
        self,
        method: str,
        path: str,
        *,
        operation: OperationSpec,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        authorization: object | None = None,
    ) -> TransportResponse:
        """Dispatch one exact mutation once; mutation retries are forbidden."""

        method = method.upper()
        try:
            registered = self._policy.authorize_mutation_operation(
                operation.operation_id
            )
        except UnknownOperationError:
            raise PolicyViolation(
                "transport mutation is not owned by its registry"
            ) from None
        if registered != operation:
            raise PolicyViolation("transport mutation is not owned by its registry")
        self._policy.authorize_mutation_request(operation, method, path)
        if method != operation.upstream_method or method != "POST":
            raise PolicyViolation(
                "mutation method is not allowed by the operation contract"
            )
        if not path.startswith("/") or path.startswith("//") or not operation.matches_path(path):
            raise PolicyViolation(
                "mutation path is not allowed by the operation contract"
            )
        if body is not None and not isinstance(body, Mapping):
            raise PolicyViolation("mutation body must be an object")
        response = self._runtime._request_insight(
            method,
            path,
            policy_authorization=authorization,
            params=query,
            json_body=body,
            semantic_auth_codes=_AUTH_CODES,
            timeout=self.timeout,
            attempts=1,
        )
        status = response.status_code
        if 300 <= status < 400:
            raise TransportError(
                "Gravity mutation returned a redirect; cross-origin redirects are blocked"
            )
        _raise_for_status(status, response.retry_after_ms, mutation=True)
        if not isinstance(response.payload, Mapping):
            raise TransportError("Gravity returned an unexpected mutation JSON envelope")
        if response.payload.get("code") in _AUTH_CODES:
            raise AuthenticationError("Gravity authorization is invalid or expired")
        return TransportResponse(status, response.payload, response.fetched_at)


def _raise_for_status(
    status: int, retry_after_ms: int | None, *, mutation: bool = False
) -> None:
    if status == 403:
        raise PermissionUnavailableError(
            "the authenticated Gravity account cannot perform this mutation"
            if mutation
            else "the authenticated Gravity account cannot read this capability"
        )
    if status == 401:
        raise AuthenticationError("Gravity authorization is invalid or expired")
    if status == 429:
        raise RateLimitedError(
            "Gravity request failed with HTTP 429",
            retry_after_ms=retry_after_ms,
        )
    if status >= 400:
        raise TransportError(f"Gravity request failed with HTTP {status}")
