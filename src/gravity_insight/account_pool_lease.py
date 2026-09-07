"""One bounded read pinned to a principal generation, shared by its page workers."""

from __future__ import annotations

import threading
from typing import Any

from .errors import CredentialError, GravityInsightError, PolicyViolation


class ReadGenerationChanged(CredentialError):
    code = "ACCOUNT_GENERATION_CHANGED"


class AccountReadLease:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.failure: BaseException | None = None
        self.refreshed = False
        self.check_generation = lambda: None
        self.check_capability = lambda operation_id: None
        self.sql_products: frozenset[str] = frozenset()
        self.runtime: Any | None = None

    def check(self) -> None:
        with self.lock:
            if self.failure is not None:
                raise self.failure
            self.check_generation()

    def reject(self, failure: BaseException) -> None:
        with self.lock:
            if self.failure is None:
                self.failure = failure

    def after_refresh(self) -> None:
        with self.lock:
            self.refreshed = True
            self.failure = ReadGenerationChanged(
                "credential generation changed; restart the complete logical read"
            )
            raise self.failure


class LeasedRuntime:
    """Pass a per-call lease to the existing runtime, never replace its requester."""

    def __init__(self, runtime: Any, lease: AccountReadLease) -> None:
        self.runtime = runtime
        self.lease = lease
        self.lease.runtime = runtime

    def current_principal_id(self) -> str | None:
        return self.runtime.current_principal_id()

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        self.lease.check()
        try:
            return getattr(self.runtime, method)(*args, _read_lease=self.lease, **kwargs)
        except GravityInsightError as exc:
            self.lease.reject(exc)
            raise

    def request(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("request", *args, **kwargs)

    def _request_insight(self, *args: Any, **kwargs: Any) -> Any:
        return self._call("_request_insight", *args, **kwargs)

    def governor_observations(self, **options: Any) -> Any:
        return self.runtime.governor_observations(**options)

    def adaptive_governor_snapshot(self) -> Any:
        return self.runtime.adaptive_governor_snapshot()


def check_read_lease(lease: Any, receipt_context: Any) -> None:
    if lease is None:
        return
    if receipt_context.get("_governor_effect") != "read":
        error = PolicyViolation(
            "account failover only accepts governed reads", code="ACCOUNT_MUTATION_BLOCKED"
        )
        lease.reject(error)
        raise error
    lease.check()
    lease.check_capability(receipt_context["operation_id"])
