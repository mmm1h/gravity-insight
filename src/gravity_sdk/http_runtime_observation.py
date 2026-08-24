"""Runtime call adapter for central governance and value-free observation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .credentials import GRAVITY_HOST
from .receipt import perform_http_request


def perform_runtime_attempt(
    requester: Any,
    profile: Any,
    method: str,
    path: str,
    headers: Mapping[str, str],
    params: Mapping[str, Any] | None,
    json_body: Mapping[str, Any] | None,
    timeout: float,
    attempts: int,
    receipt_context: Mapping[str, Any],
    rate_delay: float,
) -> Any:
    """Call the existing request boundary with value-free policy metadata."""

    from .governor_observation import runtime_attempt_context

    return perform_http_request(
        requester.session.request,
        method,
        GRAVITY_HOST + path,
        headers=headers,
        params=dict(params or {}),
        json=dict(json_body) if json_body is not None else None,
        timeout=timeout,
        allow_redirects=False,
        http_receipt=receipt_context,
        receipt_root=requester.receipt_root,
        governor_context=runtime_attempt_context(
            scope_key=requester.observation_scope_key,
            profile=profile.name,
            rate_delay_seconds=rate_delay,
            attempt_budget=attempts,
            timeout_seconds=timeout,
            business_limit=requester.business_limit,
            sql_limit=requester.sql_limit,
        ),
        governor_clock=requester.observation_clock,
        adaptive_governor=requester.governor,
    )


__all__ = ["perform_runtime_attempt"]
