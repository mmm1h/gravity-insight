"""Shared fail-closed helpers for CT03 content contracts."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)


_MARKETING_NUMBER = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*(?:%|x\b)|\b\d+(?:\.\d+)?\s*倍)"
)
_INSTRUCTION_MARKERS = (
    "ignore previous instructions",
    "system message",
    "developer message",
    "run this command",
)


class ThinkingAIFullSpecificationError(AgentRuntimeContractError):
    """A full content specification violates the approved CT03 boundary."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def schema_copy(
    value: Mapping[str, Any], schema: str, code: str, label: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        invalid(code, f"{label} must be an object")
    selected = copy.deepcopy(dict(value))
    try:
        validate_schema(selected, schema, label)
    except AgentRuntimeContractError as exc:
        raise ThinkingAIFullSpecificationError(code, f"{label} is invalid") from exc
    return selected


def verify_digest(value: dict[str, Any], field: str, code: str) -> None:
    actual = value.pop(field)
    expected = canonical_digest(value)
    value[field] = actual
    if actual != expected:
        invalid(code, "canonical digest changed")


def validate_independent_text(text: str, source_title: str) -> None:
    folded = text.casefold()
    if source_title.casefold() in folded:
        invalid("THINKINGAI_FULL_CONTENT_LEAKAGE", "source title entered content")
    if _MARKETING_NUMBER.search(text):
        invalid("THINKINGAI_FULL_CONTENT_LEAKAGE", "marketing number entered content")
    if any(marker in folded for marker in _INSTRUCTION_MARKERS):
        invalid("THINKINGAI_FULL_CONTENT_LEAKAGE", "instruction text entered content")


def invalid(reason_code: str, message: str) -> None:
    raise ThinkingAIFullSpecificationError(reason_code, message)


__all__ = [
    "ThinkingAIFullSpecificationError",
    "invalid",
    "schema_copy",
    "validate_independent_text",
    "verify_digest",
]
