"""Manifest invariants that distinguish replayable reads from mutations."""

from __future__ import annotations

from typing import Any

from .errors import ManifestError


def validate_operation_effect(
    *,
    stability: str,
    effect: str,
    executable: bool,
    non_executable_stability: bool,
    response_projection: Any,
    live_probe: Any,
) -> None:
    if stability == "stable" and not executable:
        raise ManifestError("stable operations must be executable")
    if non_executable_stability and executable:
        raise ManifestError(
            f"{stability} operations must be declared non-executable"
        )
    if (
        stability == "stable"
        and effect == "read"
        and response_projection.data_shape == "object"
        and not response_projection.data_keys
    ):
        raise ManifestError("stable object responses must declare explicit data_keys")
    if stability == "stable" and effect == "read" and not live_probe.enabled:
        raise ManifestError("stable reads must declare an enabled minimum live probe")
    if effect == "mutation" and live_probe.enabled:
        raise ManifestError("mutation operations must not declare a repeatable live probe")


__all__ = ["validate_operation_effect"]
