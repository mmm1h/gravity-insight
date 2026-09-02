"""Thin MCP delegates for Runtime inspection, readiness and execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..skill_hub_client import SkillHubClient


class AnalysisTools:
    def __init__(
        self,
        sdk: Any,
        *,
        metadata: Callable[[], Mapping[str, Any]],
    ) -> None:
        self._sdk = sdk
        self._metadata = metadata
        workspace = getattr(sdk, "workspace", None)
        self._skill_state_root = getattr(workspace, "state_root", None)

    def inspect(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        kind = arguments["kind"]
        identifier = arguments.get("identifier")
        if kind == "server":
            return dict(self._metadata())
        if kind == "journey":
            return (
                self._sdk.journeys.describe(identifier)
                if identifier is not None
                else self._sdk.journeys.list()
            )
        skills = SkillHubClient(self._skill_state_root)
        return skills.show(identifier) if identifier is not None else skills.list()

    def journey_can_run(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        return self._sdk.journeys.can_run(
            arguments["journey_id"], arguments.get("inputs", {})
        )

    def capability_describe(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        return self._sdk.capability_trust.trust(
            arguments["identity_kind"], arguments["selector"]
        )

    def execute(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        return self._sdk.journeys.run(
            arguments["journey_id"], arguments["inputs"]
        )


__all__ = ["AnalysisTools"]
