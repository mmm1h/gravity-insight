"""Offline Business Semantic registry, compiler, and resolver."""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from .actionable_error_values import actual_value
from .agent_runtime_contracts import canonical_digest
from .errors import ErrorCategory, InputValidationError, exit_code_for_category
from .semantic_contract import (
    SemanticContractError,
    builtin_semantic_source,
    compile_semantic_source,
    load_semantic_source,
    range_contains,
)
from .semantic_registry_graph import semantic_conflicts, validate_semantic_graph


_URI = re.compile(
    r"^(metric|dimension|entity|cohort|event|sku|activity|release)://"
    r"[a-z0-9.-]+/[a-z0-9./-]+@[1-9][0-9]*$"
)
_KINDS = frozenset(
    {"metric", "dimension", "entity", "cohort", "event", "sku", "activity", "release"}
)
_LOCAL_EXIT = exit_code_for_category(ErrorCategory.LOCAL)


class SemanticRegistry:
    """Compile exact local sources and resolve definitions without inference."""

    def __init__(
        self,
        sources: Sequence[Mapping[str, Any] | str | Path] = (),
        *,
        include_builtins: bool = True,
    ) -> None:
        compiled = [_compile_source_input(source) for source in sources]
        if include_builtins:
            compiled.insert(0, builtin_semantic_source())
        _reject_duplicate_sources(compiled)
        self._sources = tuple(
            sorted(compiled, key=lambda item: item["source"]["source_id"])
        )
        self._definitions = _artifacts(self._sources, "definitions")
        self._bindings = _artifacts(self._sources, "bindings")
        self._conflicts = semantic_conflicts(self._definitions, self._bindings)
        validate_semantic_graph(self._definitions, self._bindings)
        self._digest = canonical_digest(
            {
                "sources": [
                    {
                        "source_id": item["source"]["source_id"],
                        "digest": item["digest"],
                    }
                    for item in self._sources
                ]
            }
        )

    @classmethod
    def from_paths(
        cls,
        paths: Sequence[str | Path],
        *,
        include_builtins: bool = True,
    ) -> "SemanticRegistry":
        """Compile explicit local source files into one offline registry."""

        return cls(paths, include_builtins=include_builtins)

    @property
    def digest(self) -> str:
        return self._digest

    def list(self, *, kind: str | None = None) -> dict[str, Any]:
        if kind is not None and kind not in _KINDS:
            raise InputValidationError(
                f"actual value: {actual_value(kind)}; kind must be a registered Semantic kind",
                field="kind",
                next_action="Run `gravity semantics list` without --kind to inspect the allowed kinds.",
            )
        rows = [
            _definition_summary(item)
            for item in sorted(self._definitions, key=_definition_sort_key)
            if kind is None or item["contract"]["kind"] == kind
        ]
        return {
            "schema_version": "gravity.semantic-list.v1",
            "status": "success",
            "registry_digest": self._digest,
            "count": len(rows),
            "definitions": rows,
            "network_called": False,
        }

    def describe(self, uri: str) -> dict[str, Any]:
        selected = _semantic_uri(uri)
        definitions = [
            _public_artifact(item)
            for item in self._definitions
            if item["contract"]["uri"] == selected
        ]
        bindings = [
            _public_artifact(item)
            for item in self._bindings
            if item["contract"]["semantic_uri"] == selected
        ]
        if not definitions:
            return _gap(
                "gravity.semantic-description.v1",
                selected,
                "missing",
                "SEMANTIC_DEFINITION_MISSING",
                registry_digest=self._digest,
            )
        return {
            "schema_version": "gravity.semantic-description.v1",
            "status": "success",
            "uri": selected,
            "registry_digest": self._digest,
            "definitions": definitions,
            "bindings": bindings,
            "conflicts": copy.deepcopy(self._conflicts.get(selected, [])),
            "reason_codes": [],
            "network_called": False,
        }

    def resolve(
        self,
        uri: str,
        *,
        project_id: str | None = None,
        app_alias: str | None = None,
        at: str | None = None,
        start: str | None = None,
        end: str | None = None,
    ) -> dict[str, Any]:
        selected = _semantic_uri(uri)
        window = _window(at=at, start=start, end=end)
        definition = _select_definition(
            self._definitions, selected, window, registry_digest=self._digest
        )
        if "status" in definition:
            return definition
        binding = self._resolve_binding(
            definition,
            project_id=project_id,
            app_alias=app_alias,
            window=window,
        )
        if isinstance(binding, Mapping) and "status" in binding:
            return dict(binding)
        return _resolved_resolution(
            selected,
            definition,
            binding if isinstance(binding, Mapping) else None,
            window,
            registry_digest=self._digest,
        )

    def validate(self, source: Mapping[str, Any]) -> dict[str, Any]:
        try:
            compiled = compile_semantic_source(source)
            candidate = SemanticRegistry([compiled["source"]], include_builtins=True)
            reasons = sorted(
                {
                    reason
                    for values in candidate._conflicts.values()
                    for reason in values
                }
            )
            if reasons:
                return _invalid_validation(reasons)
        except SemanticContractError as exc:
            return _invalid_validation([exc.reason_code])
        return {
            "schema_version": "gravity.semantic-validation.v1",
            "status": "valid",
            "ok": True,
            "source_id": compiled["source"]["source_id"],
            "source_digest": compiled["digest"],
            "registry_digest": candidate.digest,
            "definition_count": len(compiled["definitions"]),
            "binding_count": len(compiled["bindings"]),
            "reason_codes": [],
            "network_called": False,
        }

    def dependencies(self, uris: Sequence[str], **scope: Any) -> dict[str, Any]:
        if isinstance(uris, (str, bytes)):
            raise InputValidationError(
                "actual value: string; semantic dependencies must be an array of URIs",
                field="semantic_dependencies",
            )
        results = [self.resolve(uri, **scope) for uri in uris]
        reasons = [
            code for result in results for code in result.get("reason_codes", [])
        ]
        return {
            "schema_version": "gravity.semantic-dependencies.v1",
            "status": "resolved" if not reasons else "blocked",
            "ok": not reasons,
            "exit_code": 0 if not reasons else _LOCAL_EXIT,
            "dependencies": results,
            "reason_codes": list(dict.fromkeys(reasons)),
            "network_called": False,
        }

    def _resolve_binding(
        self,
        definition: Mapping[str, Any],
        *,
        project_id: str | None,
        app_alias: str | None,
        window: tuple[date, date],
    ) -> Mapping[str, Any] | None:
        if not definition["contract"]["binding_required"]:
            return None
        candidates = _binding_candidates(
            self._bindings,
            definition["contract"]["uri"],
            project_id=project_id,
            app_alias=app_alias,
        )
        if not candidates:
            return self._binding_gap(definition, "missing", "SEMANTIC_BINDING_MISSING")
        matching = [
            item
            for item in candidates
            if range_contains(item["contract"]["effective_range"], *window)
        ]
        if not matching:
            return self._binding_gap(
                definition, "expired", "SEMANTIC_EFFECTIVE_RANGE_MISMATCH"
            )
        if len(matching) != 1:
            return self._binding_conflict_gap(
                definition, project_id=project_id, app_alias=app_alias
            )
        return matching[0]

    def _binding_gap(
        self, definition: Mapping[str, Any], status: str, reason: str
    ) -> dict[str, Any]:
        return _gap(
            "gravity.semantic-resolution.v1",
            definition["contract"]["uri"],
            status,
            reason,
            registry_digest=self._digest,
        )

    def _binding_conflict_gap(
        self,
        definition: Mapping[str, Any],
        *,
        project_id: str | None,
        app_alias: str | None,
    ) -> dict[str, Any]:
        ambiguous = project_id is None or app_alias is None
        return self._binding_gap(
            definition,
            "ambiguous" if ambiguous else "conflicting",
            "SEMANTIC_BINDING_AMBIGUOUS" if ambiguous else "SEMANTIC_BINDING_CONFLICT",
        )


def _compile_source_input(source: Mapping[str, Any] | str | Path) -> dict[str, Any]:
    return (
        compile_semantic_source(source)
        if isinstance(source, Mapping)
        else load_semantic_source(source)
    )


def _reject_duplicate_sources(compiled: Sequence[Mapping[str, Any]]) -> None:
    source_ids = [item["source"]["source_id"] for item in compiled]
    if len(source_ids) != len(set(source_ids)):
        raise SemanticContractError(
            "SEMANTIC_SOURCE_CONFLICT", "Semantic source identity is duplicated"
        )


def _artifacts(
    sources: Sequence[Mapping[str, Any]], artifact_key: str
) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            **copy.deepcopy(artifact),
            "source_id": source["source"]["source_id"],
            "source_digest": source["digest"],
        }
        for source in sources
        for artifact in source[artifact_key]
    )


def _definition_summary(item: Mapping[str, Any]) -> dict[str, Any]:
    contract = item["contract"]
    return {
        "uri": contract["uri"],
        "kind": contract["kind"],
        "version": contract["version"],
        "owner": contract["owner"],
        "authority": contract["authority"],
        "display_name": contract["display_name"],
        "effective_range": copy.deepcopy(contract["effective_range"]),
        "digest": item["digest"],
        "source_id": item["source_id"],
    }


def _definition_sort_key(item: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        item["contract"]["uri"],
        str(item["contract"]["effective_range"]),
        item["source_id"],
    )


def _select_definition(
    definitions: Sequence[Mapping[str, Any]],
    uri: str,
    window: tuple[date, date],
    *,
    registry_digest: str,
) -> dict[str, Any]:
    candidates = [item for item in definitions if item["contract"]["uri"] == uri]
    if not candidates:
        return _gap(
            "gravity.semantic-resolution.v1",
            uri,
            "missing",
            "SEMANTIC_DEFINITION_MISSING",
            registry_digest=registry_digest,
        )
    matching = [
        item
        for item in candidates
        if range_contains(item["contract"]["effective_range"], *window)
    ]
    if not matching:
        return _gap(
            "gravity.semantic-resolution.v1",
            uri,
            "expired",
            "SEMANTIC_EFFECTIVE_RANGE_MISMATCH",
            registry_digest=registry_digest,
        )
    if len(matching) != 1:
        return _gap(
            "gravity.semantic-resolution.v1",
            uri,
            "conflicting",
            "SEMANTIC_DEFINITION_CONFLICT",
            registry_digest=registry_digest,
        )
    return dict(matching[0])


def _binding_candidates(
    bindings: Sequence[Mapping[str, Any]],
    uri: str,
    *,
    project_id: str | None,
    app_alias: str | None,
) -> list[Mapping[str, Any]]:
    return [
        item
        for item in bindings
        if item["contract"]["semantic_uri"] == uri
        and (project_id is None or item["contract"]["project_id"] == project_id)
        and (app_alias is None or item["contract"]["app_alias"] == app_alias)
    ]


def _resolved_resolution(
    uri: str,
    definition: Mapping[str, Any],
    binding: Mapping[str, Any] | None,
    window: tuple[date, date],
    *,
    registry_digest: str,
) -> dict[str, Any]:
    digest = canonical_digest(
        {
            "definition": definition["digest"],
            "binding": binding["digest"] if binding is not None else None,
            "window": [value.isoformat() for value in window],
        }
    )
    return {
        "schema_version": "gravity.semantic-resolution.v1",
        "status": "resolved",
        "ok": True,
        "uri": uri,
        "registry_digest": registry_digest,
        "semantic_digest": digest,
        "definition": _public_artifact(definition),
        "binding": _public_artifact(binding),
        "requested_range": {
            "start": window[0].isoformat(),
            "end": window[1].isoformat(),
        },
        "reason_codes": [],
        "network_called": False,
    }


def _window(
    *, at: str | None, start: str | None, end: str | None
) -> tuple[date, date]:
    if at is not None and (start is not None or end is not None):
        raise InputValidationError(
            "actual value: mixed point/range; use either at or start/end",
            field="at/start/end",
            next_action="Retry `gravity semantics resolve` with --at or with --start and --end.",
        )
    if at is not None:
        selected = _date(at, "at")
        return selected, selected
    if (start is None) != (end is None):
        raise InputValidationError(
            "actual value: incomplete range; start and end must be provided together",
            field="start/end",
        )
    if start is None:
        today = date.today()
        return today, today
    selected_start, selected_end = _date(start, "start"), _date(end, "end")
    if selected_start > selected_end:
        raise InputValidationError(
            "actual value: reversed range; start must not follow end",
            field="start/end",
        )
    return selected_start, selected_end


def _date(value: Any, field: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise InputValidationError(
            f"actual value: {actual_value(value)}; {field} must be YYYY-MM-DD",
            field=field,
        ) from None
    if parsed.isoformat() != value:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; {field} must be canonical YYYY-MM-DD",
            field=field,
        )
    return parsed


def _semantic_uri(value: Any) -> str:
    if not isinstance(value, str) or _URI.fullmatch(value.strip()) is None:
        raise InputValidationError(
            f"actual value: {actual_value(value)}; uri must be an exact versioned Semantic URI",
            field="uri",
            next_action="Run `gravity semantics list` and use an exact uri.",
        )
    return value.strip()


def _public_artifact(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "contract": copy.deepcopy(value["contract"]),
        "digest": value["digest"],
        "source_id": value["source_id"],
        "source_digest": value["source_digest"],
    }


def _gap(
    schema_version: str,
    uri: str,
    status: str,
    reason: str,
    *,
    registry_digest: str,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "status": status,
        "ok": False,
        "exit_code": _LOCAL_EXIT,
        "uri": uri,
        "registry_digest": registry_digest,
        "definition": None,
        "binding": None,
        "reason_codes": [reason],
        "network_called": False,
    }


def _invalid_validation(reasons: Sequence[str]) -> dict[str, Any]:
    return {
        "schema_version": "gravity.semantic-validation.v1",
        "status": "invalid",
        "ok": False,
        "exit_code": _LOCAL_EXIT,
        "reason_codes": list(dict.fromkeys(reasons)),
        "network_called": False,
    }


__all__ = ["SemanticRegistry"]
