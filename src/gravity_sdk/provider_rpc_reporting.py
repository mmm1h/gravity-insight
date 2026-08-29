"""Public result rendering for guarded external Provider calls."""

from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from .external_context_contract import compile_rpc_result
from .provider_rpc_state import ProviderRpcState


def render_rpc_result(
    *,
    provider_uri: str,
    provider_digest: str,
    state: ProviderRpcState,
    status: str,
    ok: bool,
    operation: str,
    request_id: str | None,
    resources: Sequence[Mapping[str, Any]],
    context_items: Sequence[Mapping[str, Any]],
    next_cursor: str | None,
    reason_codes: Sequence[str],
    exit_code: int | None,
    called: bool,
    provider_stats: Mapping[str, Any],
) -> dict[str, Any]:
    result = {
        "schema_version": "gravity.provider-rpc-result.v1",
        "status": status,
        "ok": ok,
        "provider_uri": provider_uri,
        "provider_digest": provider_digest,
        "operation": operation,
        "request_id": request_id,
        "resources": copy.deepcopy(list(resources)),
        "context_items": copy.deepcopy(list(context_items)),
        "next_cursor": next_cursor,
        "reason_codes": list(reason_codes),
        "exit_code": exit_code,
        "enforced_rpc": state.stats_snapshot(),
        "provider_reported": {
            **copy.deepcopy(dict(provider_stats)),
            "enforced": False,
        },
        "circuit": state.circuit_snapshot(),
        "provider_rpc_called": called,
        "provider_internal_io_controlled": False,
        "provider_internal_network": "not_observable",
    }
    return compile_rpc_result(result)


__all__ = ["render_rpc_result"]
