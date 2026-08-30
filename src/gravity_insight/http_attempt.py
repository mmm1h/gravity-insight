"""Canonical governed boundary for one actual Runtime-owned HTTP attempt."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


def perform_governed_http_request(
    request: Callable[..., Any],
    request_args: Sequence[Any],
    request_kwargs: Mapping[str, Any],
    *,
    kind: str,
    receipt_context: Mapping[str, Any] | None,
    receipt_root: Path | None,
    governor_context: Mapping[str, Any] | None,
    governor_clock: Callable[[], float],
    adaptive_governor: Any | None,
    cancellation: Any | None,
) -> Any:
    call = lambda: _perform_actual_http_request(
        request,
        request_args,
        request_kwargs,
        kind=kind,
        receipt_context=receipt_context,
        receipt_root=receipt_root,
        governor_context=governor_context,
        governor_clock=governor_clock,
    )
    if (
        adaptive_governor is None
        and receipt_context is None
        and governor_context is None
    ):
        return call()
    from .adaptive_governor import get_process_governor
    from .adaptive_governor_http import build_governor_request

    governor = (
        adaptive_governor
        if adaptive_governor is not None
        else get_process_governor()
    )
    descriptor = build_governor_request(
        request_args,
        request_kwargs,
        receipt_context=receipt_context,
        governor_context=governor_context,
        cancellation=cancellation,
    )
    return governor.execute(descriptor, call)


def _perform_actual_http_request(
    request: Callable[..., Any],
    request_args: Sequence[Any],
    request_kwargs: Mapping[str, Any],
    *,
    kind: str,
    receipt_context: Mapping[str, Any] | None,
    receipt_root: Path | None,
    governor_context: Mapping[str, Any] | None,
    governor_clock: Callable[[], float],
) -> Any:
    from . import receipt as evidence

    evidence.record_http_request(kind=kind)
    active = (
        evidence._ActiveHttpReceipt(receipt_context, receipt_root)
        if receipt_context is not None and receipt_root is not None
        else None
    )
    token = evidence._ACTIVE_HTTP_RECEIPT.set(active) if active is not None else None
    started = evidence._governor_clock_value(governor_clock)
    finished = started
    response: Any = None
    error: BaseException | None = None
    try:
        response = request(*request_args, **request_kwargs)
        finished = evidence._governor_clock_value(governor_clock, fallback=started)
        evidence.record_active_http_response(response)
        return response
    except BaseException as caught:
        error = caught
        finished = evidence._governor_clock_value(governor_clock, fallback=started)
        raise
    finally:
        evidence._record_governor_observation(
            request_args,
            request_kwargs,
            receipt_context=receipt_context,
            governor_context=governor_context,
            response=response,
            error=error,
            duration_seconds=max(0.0, finished - started),
        )
        if token is not None:
            evidence._ACTIVE_HTTP_RECEIPT.reset(token)


__all__ = ["perform_governed_http_request"]
