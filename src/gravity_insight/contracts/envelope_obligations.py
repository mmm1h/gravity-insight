"""Typed facts that a consumer-facing result envelope must preserve."""

from __future__ import annotations

import copy
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any


SCHEMA_VERSION = "gravity.envelope-obligations.v1"
SCHEMA_NAME = "envelope-obligations-v1.schema.json"
_EVIDENCE_CODE = re.compile(r"^[A-Z][A-Z0-9_]{1,127}$")


def _mapping(
    value: Any, required: set[str], optional: set[str] | None = None
) -> Mapping[str, Any]:
    allowed = required | (optional or set())
    if not isinstance(value, Mapping) or not required <= set(value) or set(value) - allowed:
        raise ValueError("envelope obligation object has missing or unsupported fields")
    return value


class ExecutionState(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_STARTED = "not_started"


class CompletenessState(str, Enum):
    COMPLETE = "complete"
    PREFIX = "prefix"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class SemanticState(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class DiagnosticState(str, Enum):
    NONE = "none"
    AVAILABLE = "available"
    INCOMPLETE = "incomplete"


class DiagnosticCategory(str, Enum):
    CALLER = "caller"
    UPSTREAM = "upstream"
    LOCAL = "local"


class MutationState(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    NOT_ATTEMPTED = "not_attempted"
    APPLIED = "applied"
    CONFIRMED = "confirmed"
    UNCERTAIN = "uncertain"


def _code(value: str) -> str:
    if not isinstance(value, str) or _EVIDENCE_CODE.fullmatch(value) is None:
        raise ValueError(
            "obligation evidence codes must be stable upper-snake-case identifiers"
        )
    return value


def _diagnostic_codes(values: tuple[str, ...], state: DiagnosticState) -> None:
    if len(values) > 64 or len(set(values)) != len(values):
        raise ValueError("diagnostic evidence codes must be a unique bounded sequence")
    for value in values:
        _code(value)
    if state is DiagnosticState.NONE and values:
        raise ValueError("diagnostic state none cannot carry evidence codes")
    if state is not DiagnosticState.NONE and not values:
        raise ValueError("diagnostic failures require evidence codes")


def _diagnostic_shape(
    state: DiagnosticState,
    details: tuple[Any, ...],
    code: str | None,
    category: DiagnosticCategory | None,
    retryable: bool | None,
) -> None:
    if state is DiagnosticState.NONE and any(value is not None for value in details):
        raise ValueError("diagnostic state none cannot carry diagnostic details")
    if state is DiagnosticState.AVAILABLE and (
        code is None or category is None or retryable is None
    ):
        raise ValueError("available diagnostics require code, category, and retryable")


@dataclass(frozen=True)
class ExecutionStatus:
    state: ExecutionState
    evidence_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, ExecutionState):
            raise TypeError("execution status state must be ExecutionState")
        _code(self.evidence_code)

    def to_dict(self) -> dict[str, str]:
        return {"state": self.state.value, "evidence_code": self.evidence_code}


@dataclass(frozen=True)
class DataCompleteness:
    state: CompletenessState
    evidence_code: str
    facts: Mapping[str, bool | int | float | str | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.state, CompletenessState):
            raise TypeError("data completeness state must be CompletenessState")
        _code(self.evidence_code)
        if len(self.facts) > 16 or any(
            not isinstance(name, str) or not name for name in self.facts
        ):
            raise ValueError(
                "data completeness facts must have one to sixteen named scalar facts"
            )
        allowed = (bool, int, float, str, type(None))
        if any(not isinstance(value, allowed) for value in self.facts.values()) or any(
            isinstance(value, float) and not math.isfinite(value)
            for value in self.facts.values()
        ):
            raise ValueError("data completeness facts must be JSON scalar values")

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "evidence_code": self.evidence_code,
            "facts": dict(self.facts),
        }


@dataclass(frozen=True)
class SemanticValidity:
    state: SemanticState
    evidence_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.state, SemanticState):
            raise TypeError("semantic validity state must be SemanticState")
        if len(self.evidence_codes) > 64 or len(set(self.evidence_codes)) != len(
            self.evidence_codes
        ):
            raise ValueError("semantic evidence codes must be a unique bounded sequence")
        if self.state is not SemanticState.NOT_APPLICABLE and not self.evidence_codes:
            raise ValueError("applicable semantic validity requires evidence codes")
        for value in self.evidence_codes:
            _code(value)

    def to_dict(self) -> dict[str, Any]:
        return {"state": self.state.value, "evidence_codes": list(self.evidence_codes)}


@dataclass(frozen=True)
class DiagnosticEvidence:
    state: DiagnosticState
    evidence_codes: tuple[str, ...] = ()
    code: str | None = None
    category: DiagnosticCategory | None = None
    retryable: bool | None = None
    field: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.state, DiagnosticState):
            raise TypeError("diagnostic evidence state must be DiagnosticState")
        if self.category is not None and not isinstance(self.category, DiagnosticCategory):
            raise TypeError("diagnostic category must be DiagnosticCategory")
        _diagnostic_codes(self.evidence_codes, self.state)
        if self.code is not None:
            _code(self.code)
        details = (self.code, self.category, self.retryable, self.field)
        _diagnostic_shape(
            self.state, details, self.code, self.category, self.retryable
        )
        if self.field is not None and (not self.field or len(self.field) > 512):
            raise ValueError("diagnostic field must be a non-empty bounded path")

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "state": self.state.value,
            "evidence_codes": list(self.evidence_codes),
        }
        if self.code is not None:
            result["code"] = self.code
        if self.category is not None:
            result["category"] = self.category.value
        if self.retryable is not None:
            result["retryable"] = self.retryable
        if self.field is not None:
            result["field"] = self.field
        return result


@dataclass(frozen=True)
class MutationCertainty:
    state: MutationState
    evidence_code: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, MutationState):
            raise TypeError("mutation certainty state must be MutationState")
        _code(self.evidence_code)

    def to_dict(self) -> dict[str, str]:
        return {"state": self.state.value, "evidence_code": self.evidence_code}


@dataclass(frozen=True)
class EnvelopeObligations:
    execution_status: ExecutionStatus
    data_completeness: DataCompleteness
    semantic_validity: SemanticValidity
    diagnostic_evidence: DiagnosticEvidence
    mutation_certainty: MutationCertainty

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> EnvelopeObligations:
        root = _mapping(
            value,
            {
                "schema_version",
                "execution_status",
                "data_completeness",
                "semantic_validity",
                "diagnostic_evidence",
                "mutation_certainty",
            },
        )
        if root["schema_version"] != SCHEMA_VERSION:
            raise ValueError("envelope obligations have an unsupported schema version")
        execution = _mapping(root["execution_status"], {"state", "evidence_code"})
        completeness = _mapping(
            root["data_completeness"], {"state", "evidence_code", "facts"}
        )
        semantics = _mapping(root["semantic_validity"], {"state", "evidence_codes"})
        diagnostics = _mapping(
            root["diagnostic_evidence"],
            {"state", "evidence_codes"},
            {"code", "category", "retryable", "field"},
        )
        mutation = _mapping(root["mutation_certainty"], {"state", "evidence_code"})
        category = diagnostics.get("category")
        return cls(
            execution_status=ExecutionStatus(
                ExecutionState(execution["state"]), execution["evidence_code"]
            ),
            data_completeness=DataCompleteness(
                CompletenessState(completeness["state"]),
                completeness["evidence_code"],
                completeness["facts"],
            ),
            semantic_validity=SemanticValidity(
                SemanticState(semantics["state"]), tuple(semantics["evidence_codes"])
            ),
            diagnostic_evidence=DiagnosticEvidence(
                DiagnosticState(diagnostics["state"]),
                tuple(diagnostics["evidence_codes"]),
                diagnostics.get("code"),
                DiagnosticCategory(category) if category is not None else None,
                diagnostics.get("retryable"),
                diagnostics.get("field"),
            ),
            mutation_certainty=MutationCertainty(
                MutationState(mutation["state"]), mutation["evidence_code"]
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": SCHEMA_VERSION,
            "execution_status": self.execution_status.to_dict(),
            "data_completeness": self.data_completeness.to_dict(),
            "semantic_validity": self.semantic_validity.to_dict(),
            "diagnostic_evidence": self.diagnostic_evidence.to_dict(),
            "mutation_certainty": self.mutation_certainty.to_dict(),
        }
        return result

    def with_semantics(
        self,
        semantic_validity: SemanticValidity,
        diagnostic_evidence: DiagnosticEvidence,
    ) -> EnvelopeObligations:
        return replace(
            self,
            semantic_validity=semantic_validity,
            diagnostic_evidence=diagnostic_evidence,
        )


def serialize_envelope(
    payload: Mapping[str, Any], obligations: EnvelopeObligations
) -> dict[str, Any]:
    """Serialize already-decided facts; this boundary does not infer them."""

    if type(obligations) is not EnvelopeObligations:
        raise TypeError("consumer envelopes require an EnvelopeObligations value")
    selected = copy.deepcopy(dict(payload))
    if "obligations" in selected:
        raise ValueError("consumer envelope payload cannot prebuild obligations")
    selected["obligations"] = obligations.to_dict()
    return selected


def classify_data_completeness(value: Any) -> DataCompleteness:
    """Collapse string and object-shaped inner completeness without guessing."""

    observed: list[CompletenessState] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            raw = item.get("completeness")
            if isinstance(raw, str):
                try:
                    observed.append(CompletenessState(raw))
                except ValueError:
                    observed.append(CompletenessState.UNKNOWN)
            elif isinstance(raw, Mapping):
                status = raw.get("status")
                try:
                    observed.append(CompletenessState(status))
                except (TypeError, ValueError):
                    observed.append(CompletenessState.UNKNOWN)
            for nested in item.values():
                if isinstance(nested, (Mapping, list, tuple)):
                    visit(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(value)
    facts = {"observed_conclusions": len(observed)}
    if CompletenessState.PREFIX in observed:
        return DataCompleteness(
            CompletenessState.PREFIX, "NESTED_PREFIX_OBSERVED", facts
        )
    if CompletenessState.UNKNOWN in observed:
        return DataCompleteness(
            CompletenessState.UNKNOWN, "NESTED_UNKNOWN_OBSERVED", facts
        )
    if observed:
        return DataCompleteness(
            CompletenessState.COMPLETE, "ALL_OBSERVED_COLLECTIONS_COMPLETE", facts
        )
    return DataCompleteness(
        CompletenessState.UNKNOWN, "NO_COMPLETENESS_EVIDENCE", facts
    )


def diagnostic_evidence(value: Any) -> DiagnosticEvidence:
    """Preserve only typed error facts; raw exception text has no field here."""

    if not isinstance(value, Mapping):
        return DiagnosticEvidence(DiagnosticState.NONE)
    code = value.get("code")
    category = value.get("category")
    retryable = value.get("retryable")
    try:
        selected_category = DiagnosticCategory(category)
        _code(code)
    except (TypeError, ValueError):
        return DiagnosticEvidence(
            DiagnosticState.INCOMPLETE,
            ("DIAGNOSTIC_FIELDS_INVALID_OR_MISSING",),
        )
    if type(retryable) is not bool:
        return DiagnosticEvidence(
            DiagnosticState.INCOMPLETE,
            ("DIAGNOSTIC_FIELDS_INVALID_OR_MISSING",),
        )
    field_value = value.get("field")
    field_value = (
        field_value if isinstance(field_value, str) and field_value else None
    )
    return DiagnosticEvidence(
        DiagnosticState.AVAILABLE,
        ("STRUCTURED_ERROR_DETAIL",),
        code,
        selected_category,
        retryable,
        field_value,
    )


__all__ = [
    "CompletenessState",
    "DataCompleteness",
    "DiagnosticCategory",
    "DiagnosticEvidence",
    "DiagnosticState",
    "EnvelopeObligations",
    "ExecutionState",
    "ExecutionStatus",
    "MutationCertainty",
    "MutationState",
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "SemanticState",
    "SemanticValidity",
    "classify_data_completeness",
    "diagnostic_evidence",
    "serialize_envelope",
]
