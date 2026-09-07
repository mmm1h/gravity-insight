"""Runtime call adapter for central governance and value-free observation."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .credentials import GRAVITY_HOST, validated_login_payload
from .receipt import PRODUCTION_HTTP_KIND, perform_http_request, request_receipt_context


ReceiptBinding = tuple[Path, str]
ReceiptBindingResolver = Callable[[], ReceiptBinding]


def perform_runtime_login(
    requester: Any, profile: Any, body: Mapping[str, Any], timeout: float,
) -> Mapping[str, Any]:
    """Keep login on the same generation-bound requester as business traffic."""

    response = requester.request(
        profile,
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


def resolve_receipt_binding(requester: Any) -> ReceiptBinding:
    """Freeze storage and observation coordinates before rate waits and I/O."""

    binding = (
        requester.receipt_binding_resolver()
        if requester.receipt_binding_resolver is not None
        else requester.receipt_binding
    )
    requester.receipt_binding = binding
    requester.observation_scope_key = binding[1]
    return binding


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
    binding: ReceiptBinding,
) -> Any:
    """Call the existing request boundary with value-free policy metadata."""

    from .governor_observation import runtime_attempt_context

    return perform_http_request(
        requester.session.request,
        method,
        GRAVITY_HOST + path,
        kind=PRODUCTION_HTTP_KIND,
        headers=headers,
        params=dict(params or {}),
        json=dict(json_body) if json_body is not None else None,
        timeout=timeout,
        allow_redirects=False,
        http_receipt=receipt_context,
        receipt_root=binding[0],
        governor_context=runtime_attempt_context(
            scope_key=binding[1],
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
