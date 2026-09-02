"""Stable experimental Tool definitions, annotations and fingerprint."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from ..agent_runtime_contracts import canonical_digest
from .schemas import input_schema, output_schema


CATALOG_SCHEMA_VERSION = "gravity.mcp-tool-catalog.v1"


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    title: str
    description: str
    read_only: bool
    idempotent: bool

    def render(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": input_schema(self.name),
            "outputSchema": output_schema(),
            "annotations": {
                "readOnlyHint": self.read_only,
                "destructiveHint": False,
                "idempotentHint": self.idempotent,
                "openWorldHint": False,
            },
        }


_DEFINITIONS = (
    ToolDefinition(
        "gravity.inspect",
        "Inspect Gravity Runtime",
        "Inspect one selected metadata object without target network access. A Skill is a synced Hub workflow package; a Journey is a registered task and acceptance contract. Choose the kind explicitly.",
        True,
        True,
    ),
    ToolDefinition(
        "gravity.journey_can_run",
        "Assess Journey Readiness",
        "Assess one exact registered Journey and return existing Runtime readiness reasons.",
        True,
        True,
    ),
    ToolDefinition(
        "gravity.capability_describe",
        "Describe Capability Trust",
        "Read current Trust only for the exact identity layer named by identity_kind: operation is an atomic wire contract, product is one governed question-level capability, and composite is a bounded multi-component capability. Layers are not interchangeable.",
        True,
        True,
    ),
    ToolDefinition(
        "gravity.execute",
        "Execute Registered Journey",
        "Execute one exact registered Journey through its existing Runtime owner; raw operations are not accepted.",
        True,
        False,
    ),
    ToolDefinition(
        "gravity.export",
        "Export Analysis Result",
        "Compile a governed Analysis Result and, after explicit confirmation, publish JSON or Markdown to one local path.",
        False,
        False,
    ),
    ToolDefinition(
        "gravity.context_pack",
        "Assemble Context Pack",
        "Assemble a bounded project Repo Context Pack through the existing public provider.",
        True,
        True,
    ),
)


def tool_definitions() -> tuple[ToolDefinition, ...]:
    rendered = tuple(_DEFINITIONS)
    for item in rendered:
        item.render()
    return rendered


def tool_catalog() -> dict[str, Any]:
    tools = [item.render() for item in tool_definitions()]
    payload = {"schema_version": CATALOG_SCHEMA_VERSION, "tools": tools}
    payload["fingerprint"] = canonical_digest(payload)
    return copy.deepcopy(payload)


def tool_definition(name: str) -> ToolDefinition | None:
    return next((item for item in tool_definitions() if item.name == name), None)


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "ToolDefinition",
    "tool_catalog",
    "tool_definition",
    "tool_definitions",
]
