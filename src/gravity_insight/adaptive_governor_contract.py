"""Private identities and stable constants for the Runtime HTTP Governor."""

from __future__ import annotations

import contextvars
import hashlib
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, NoReturn

from .error_models import ErrorCategory
from .errors import TransportError


SCHEMA_VERSION = "gravity.adaptive-governor-snapshot.v1"
POLICY_REVISION = "gravity.governor-policy.adaptive.v1"
ADAPTIVE = "adaptive"
STATIC = "static"
TOTAL_CAPACITY = 25
BUSINESS_CAPACITY = 24
SQL_CAPACITY = 2
MAX_QUEUE = 128
MAX_LANES = 1_024
MAX_SCOPES = 64
MAX_SNAPSHOT_LANES = 256
CIRCUIT_FAILURE_THRESHOLD = 3
CIRCUIT_COOLDOWN_SECONDS = 30.0
SLOW_RESPONSE_SECONDS = 2.0
MAX_WAIT_SECONDS = 30.0
PROCESS_SCOPE = "gravity-governor-process-http"

_CURRENT_JOURNEY: contextvars.ContextVar[str] = contextvars.ContextVar(
    "gravity_governor_journey", default="direct"
)


class GovernorRequestError(TransportError):
    """A request stopped before HTTP because governed capacity denied it."""

    category = ErrorCategory.UPSTREAM
    retryable = True


def raise_request_failure(error: Exception) -> NoReturn:
    """Preserve Governor denials while scrubbing raw transport failures."""

    if isinstance(error, GovernorRequestError):
        raise error
    raise TransportError(
        "Gravity request failed before a response was received"
    ) from error


@dataclass(frozen=True)
class GovernorRequest:
    """Value-free request identity consumed by the process Governor."""

    scope_key: str
    host_key: str
    operation_class: str
    profile: str
    journey_key: str
    request_key: str | None
    coalesce_safe: bool
    timeout_seconds: float
    cancellation: threading.Event | None = None

    @property
    def lane_key(self) -> tuple[str, str, str, str]:
        return self.scope_key, self.host_key, self.operation_class, self.profile


@contextmanager
def governor_journey(value: Any) -> Iterator[None]:
    token = _CURRENT_JOURNEY.set(str(value or "direct"))
    try:
        yield
    finally:
        _CURRENT_JOURNEY.reset(token)


def current_journey_key() -> str:
    return private_journey_key(_CURRENT_JOURNEY.get())


def private_scope_key(value: Any) -> str:
    return _private_key("scope", value or PROCESS_SCOPE)


def private_journey_key(value: Any) -> str:
    return _private_key("journey", value or "direct")


def private_host_key(value: Any) -> str:
    return _private_key("host", str(value or "unknown").casefold())


def profile_limits(
    profile: str, business_limit: int, sql_limit: int
) -> tuple[int, int]:
    if profile == "sql":
        return sql_limit, sql_limit
    if profile == "login":
        return 1, 1
    if profile == "insight":
        return min(6, business_limit), business_limit
    return min(4, business_limit), business_limit


def response_status_class(response: Any) -> str:
    status = getattr(response, "status_code", None)
    if type(status) is not int:
        return "unknown"
    if 200 <= status < 300:
        return "success"
    if 300 <= status < 400:
        return "redirect"
    if status == 429:
        return "rate_limited"
    if 400 <= status < 500:
        return "client_error"
    if 500 <= status < 600:
        return "server_error"
    return "unknown"


def validate_configuration(
    mode: str, total: int, business: int, sql: int, queue: int
) -> None:
    capacities = (total, business, sql, queue)
    valid = mode in {ADAPTIVE, STATIC}
    valid = valid and all(type(value) is int and value > 0 for value in capacities)
    valid = valid and total <= TOTAL_CAPACITY and business <= BUSINESS_CAPACITY
    valid = valid and business < total and sql <= business and queue <= MAX_QUEUE
    if not valid:
        raise ValueError("Adaptive Governor configuration is invalid")


def mode_from_environment() -> str:
    selected = os.environ.get("GRAVITY_GOVERNOR_MODE", ADAPTIVE).strip().casefold()
    if selected not in {ADAPTIVE, STATIC}:
        raise ValueError("GRAVITY_GOVERNOR_MODE must be adaptive or static")
    return selected


def _private_key(kind: str, value: Any) -> str:
    return hashlib.sha256(
        f"gravity-governor-{kind}-v1\0{value}".encode("utf-8")
    ).hexdigest()


__all__ = [
    "ADAPTIVE",
    "BUSINESS_CAPACITY",
    "CIRCUIT_COOLDOWN_SECONDS",
    "CIRCUIT_FAILURE_THRESHOLD",
    "GovernorRequest",
    "GovernorRequestError",
    "MAX_LANES",
    "MAX_QUEUE",
    "MAX_SCOPES",
    "MAX_SNAPSHOT_LANES",
    "MAX_WAIT_SECONDS",
    "POLICY_REVISION",
    "PROCESS_SCOPE",
    "SCHEMA_VERSION",
    "SLOW_RESPONSE_SECONDS",
    "SQL_CAPACITY",
    "STATIC",
    "TOTAL_CAPACITY",
    "current_journey_key",
    "governor_journey",
    "private_host_key",
    "private_scope_key",
    "raise_request_failure",
]
