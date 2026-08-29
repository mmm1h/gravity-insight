"""Principal-scoped current Capability Validation Results."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    load_json_object,
    validate_schema,
)
from .data_quality import validate_data_quality_result


SCHEMA_VERSION = "gravity.capability-validation.v1"
STORE_SCHEMA_VERSION = "gravity.capability-validation-store.v1"
STORE_RELATIVE_PATH = Path("agent-runtime") / "capability-validations.v1.json"
_SCHEMA_NAME = "capability-validation-v1.schema.json"
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")


class CapabilityValidationError(AgentRuntimeContractError):
    """A current Validation Result or its private store is invalid."""


class CapabilityValidationStore:
    """Load current Validation only from one already principal-scoped root."""

    def __init__(
        self,
        state_root: str | Path | None = None,
        *,
        scope_bound: bool = False,
        values: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self._state_root = (
            Path(state_root).expanduser().resolve()
            if state_root is not None
            else None
        )
        self._scope_bound = bool(scope_bound)
        self._provided = (
            tuple(copy.deepcopy(dict(value)) for value in values)
            if values is not None
            else None
        )
        self._loaded: dict[tuple[str, str], dict[str, Any]] | None = None

    def get(self, identity_kind: str, selector: str) -> dict[str, Any] | None:
        selected = self._values().get((identity_kind, selector))
        return copy.deepcopy(selected) if selected is not None else None

    def list(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            copy.deepcopy(value)
            for _, value in sorted(self._values().items(), key=lambda item: item[0])
        )

    def _values(self) -> dict[tuple[str, str], dict[str, Any]]:
        if self._loaded is not None:
            return self._loaded
        if self._provided is not None:
            values = self._provided
        elif not self._scope_bound or self._state_root is None:
            values = ()
        else:
            path = self._state_root / STORE_RELATIVE_PATH
            if not path.is_file():
                values = ()
            else:
                document = load_json_object(path, "Capability Validation store")
                if set(document) != {"schema_version", "validations"}:
                    raise CapabilityValidationError(
                        "Capability Validation store fields are invalid"
                    )
                if document["schema_version"] != STORE_SCHEMA_VERSION:
                    raise CapabilityValidationError(
                        "Capability Validation store schema version changed"
                    )
                raw = document["validations"]
                if not isinstance(raw, list):
                    raise CapabilityValidationError(
                        "Capability Validation store entries must be an array"
                    )
                values = tuple(raw)
        loaded: dict[tuple[str, str], dict[str, Any]] = {}
        for value in values:
            validation = validate_capability_validation(value)
            key = validation_identity(validation)
            if key in loaded:
                raise CapabilityValidationError(
                    "Capability Validation identity is duplicated"
                )
            loaded[key] = validation
        self._loaded = loaded
        return loaded


def validate_capability_validation(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CapabilityValidationError("Capability Validation must be an object")
    selected = copy.deepcopy(dict(value))
    try:
        validate_schema(selected, _SCHEMA_NAME, "Capability Validation")
        validate_data_quality_result(selected["data_quality"])
    except AgentRuntimeContractError as exc:
        raise CapabilityValidationError(str(exc)) from exc
    validated_at = parse_utc_timestamp(selected["validated_at"])
    expires_at = parse_utc_timestamp(selected["expires_at"])
    if expires_at <= validated_at:
        raise CapabilityValidationError(
            "Capability Validation expiry must follow validation time"
        )
    reasons = selected["reason_codes"]
    if any(_REASON_CODE.fullmatch(code) is None for code in reasons):
        raise CapabilityValidationError("Capability Validation reason code is invalid")
    if selected["trust_status"] == "stable" and reasons:
        raise CapabilityValidationError(
            "stable Capability Validation cannot carry reason codes"
        )
    return selected


def validation_identity(value: Mapping[str, Any]) -> tuple[str, str]:
    return str(value["identity_kind"]), str(value["selector"])


def validation_digest(value: Mapping[str, Any]) -> str:
    selected = validate_capability_validation(value)
    return canonical_digest(selected)


def parse_utc_timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise CapabilityValidationError(
            "Capability Validation timestamp must use canonical UTC Z form"
        )
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise CapabilityValidationError(
            "Capability Validation timestamp is invalid"
        ) from exc
    rendered = parsed.astimezone(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    if rendered != value:
        raise CapabilityValidationError(
            "Capability Validation timestamp is not canonical"
        )
    return parsed


__all__ = [
    "CapabilityValidationError",
    "CapabilityValidationStore",
    "SCHEMA_VERSION",
    "STORE_RELATIVE_PATH",
    "STORE_SCHEMA_VERSION",
    "parse_utc_timestamp",
    "validate_capability_validation",
    "validation_digest",
    "validation_identity",
]
