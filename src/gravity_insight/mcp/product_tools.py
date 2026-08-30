"""Thin MCP delegates for local Analysis delivery and Context packing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..repo_context_provider import RepoContextProvider


class ProductTools:
    def __init__(self, sdk: Any) -> None:
        self._sdk = sdk

    def export(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        artifacts = self._sdk.analysis_artifacts
        artifact = artifacts.compile(arguments["analysis_result"])
        if arguments["format"] == "json":
            return artifacts.write_artifact(artifact, arguments["destination"])
        return artifacts.write_markdown(
            artifact,
            arguments["destination"],
            max_bytes=arguments.get("max_output_bytes", 100_000),
        )

    def context_pack(self, arguments: Mapping[str, Any]) -> dict[str, Any]:
        provider = RepoContextProvider(
            arguments["root"], project_id=arguments["project_id"]
        )
        return provider.pack(
            arguments["requirement"],
            requested_time=arguments["requested_time"],
            entity_aliases=arguments.get("entity_aliases"),
        )


__all__ = ["ProductTools"]
