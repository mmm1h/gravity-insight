"""Shared JSON and schema primitives for Agent Runtime machine contracts."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .compiler import ContractError, JsonSchemaValidator


_PACKAGE_ROOT = Path(__file__).resolve().parent
_SCHEMA_ROOT = _PACKAGE_ROOT / "contracts" / "schema"


class AgentRuntimeContractError(ValueError):
    """An Agent Runtime artifact is malformed or contradicts its schema."""


def canonical_digest(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AgentRuntimeContractError(
            "Agent Runtime artifact must be canonical JSON"
        ) from exc
    return hashlib.sha256(encoded).hexdigest()


def load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AgentRuntimeContractError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise AgentRuntimeContractError(f"{label} must be a JSON object")
    return value


def validate_schema(
    value: Mapping[str, Any], schema_name: str, label: str
) -> None:
    try:
        _validator(schema_name).validate(value)
    except ContractError as exc:
        raise AgentRuntimeContractError(f"{label} does not match {schema_name}") from exc


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


@lru_cache(maxsize=None)
def _validator(schema_name: str) -> JsonSchemaValidator:
    selected = Path(schema_name)
    if selected.name != schema_name or selected.suffix != ".json":
        raise AgentRuntimeContractError("schema name must be one package filename")
    schema = load_json_object(_SCHEMA_ROOT / selected, f"{schema_name} schema")
    try:
        return JsonSchemaValidator(schema, schema_name)
    except ContractError as exc:
        raise AgentRuntimeContractError(f"{schema_name} schema is invalid") from exc


__all__ = [
    "AgentRuntimeContractError",
    "canonical_digest",
    "is_sha256",
    "load_json_object",
    "validate_schema",
]
