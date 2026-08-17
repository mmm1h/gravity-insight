"""Strict compilation boundary for one saved Analysis artifact.

Saved definitions exist in two deliberately distinct public formats.  Caller
definitions may already be compact Analysis Spec v1 objects, while Gravity Web
persists the proven chart shape rooted at ``calculateBody``.  This module
selects the format structurally; it never guesses by retrying another compiler.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .analysis_spec import compile_query_spec, prepare_query_spec, validate_query_spec
from .dashboard_artifact import compile_dashboard_chart, validate_dashboard_window
from .domains import ANALYSIS_QUERY_OPERATIONS
from .errors import InputValidationError, UnsupportedOperationError
from ._field_policy_analysis import validate_analysis_shape
from .saved_analysis_support import decoded_config, supported_subject
from .actionable_error_values import actual_value


COMPACT_SPEC = "compact_spec"
WEB_ARTIFACT = "web_artifact"
_INSPECTION_DATE = "2000-01-01"


@dataclass(frozen=True)
class CompiledSavedArtifact:
    """One saved definition normalized to an exact stable Analysis request."""

    artifact_mode: str
    kind: str
    operation_id: str
    inputs: dict[str, Any]
    validation_status: str
    live_metadata_dependencies: tuple[str, ...]
    date_range: dict[str, Any] | None
    date_override_applied: bool
    limitations: tuple[str, ...]

    def safe_summary(self) -> dict[str, Any]:
        return {
            "artifact_mode": self.artifact_mode,
            "kind": self.kind,
            "operation_id": self.operation_id,
            "validation": {
                "status": self.validation_status,
                "live_metadata_dependencies": list(
                    self.live_metadata_dependencies
                ),
            },
            "date_range": self.date_range,
            "date_override_applied": self.date_override_applied,
            "limitations": list(self.limitations),
        }


def saved_artifact_mode(definition: Mapping[str, Any]) -> str:
    """Classify a decoded definition without compiling or fallback guessing."""

    config = decoded_config(definition.get("config"))
    return WEB_ARTIFACT if "calculateBody" in config else COMPACT_SPEC


def validate_saved_window(start: Any, end: Any) -> None:
    """Validate an optional paired window before any catalog or client call."""

    _paired_window(start, end)


def preflight_saved_definition(
    definition: Mapping[str, Any], *, app: str, workspace: Any,
    start: str | None = None, end: str | None = None,
) -> None:
    """Compile caller-owned structure without constructing an Insight client."""

    _paired_window(start, end)
    kind = supported_subject(definition.get("subject"))
    config = decoded_config(definition.get("config"))
    if "calculateBody" not in config:
        compile_query_spec(
            kind, config, workspace=workspace, app=app, start=start, end=end
        )
        return
    if start is None or end is None:
        raise InputValidationError(
            f"actual value: {actual_value((start, end))}; " + ("saved Web artifact replay requires explicit start and end"),
            field="start/end",
        )
    compile_dashboard_chart(
        _OfflineValidator(), _dashboard_report(definition, config),
        app_id=app, start=start, end=end
    )


class _OfflineValidator:
    @staticmethod
    def validate(operation_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
        kind = next(
            (name for name, selected in ANALYSIS_QUERY_OPERATIONS.items()
             if selected == operation_id),
            None,
        )
        if kind is None:
            raise UnsupportedOperationError("saved artifact operation is not registered")
        validate_analysis_shape(kind, inputs)
        return {"ok": True, "status": "valid_offline"}


def compile_saved_artifact(
    client: Any,
    definition: Mapping[str, Any],
    *,
    app: str,
    workspace: Any,
    start: str | None = None,
    end: str | None = None,
) -> CompiledSavedArtifact:
    """Compile and offline-validate one explicitly classified definition."""

    _paired_window(start, end)
    kind = supported_subject(definition.get("subject"))
    config = decoded_config(definition.get("config"))
    mode = WEB_ARTIFACT if "calculateBody" in config else COMPACT_SPEC
    if mode == WEB_ARTIFACT:
        if start is None or end is None:
            raise InputValidationError(
                f"actual value: {actual_value((start, end))}; " + ("saved Web artifact replay requires explicit start and end"),
                field="start/end",
                next_action="Retry with an inclusive date window no longer than 90 days.",
            )
        compiled = compile_dashboard_chart(
            client,
            _dashboard_report(definition, config),
            app_id=app,
            start=start,
            end=end,
        )
        return CompiledSavedArtifact(
            artifact_mode=mode,
            kind=compiled.kind,
            operation_id=compiled.operation_id,
            inputs=compiled.inputs,
            validation_status=compiled.validation_status,
            live_metadata_dependencies=compiled.live_metadata_dependencies,
            date_range=_date_range(start, end),
            date_override_applied=compiled.date_override_applied,
            limitations=compiled.limitations,
        )
    compiled, validation = validate_query_spec(
        client,
        kind,
        config,
        workspace=workspace,
        app=app,
        start=start,
        end=end,
    )
    return CompiledSavedArtifact(
        artifact_mode=mode,
        kind=compiled.kind,
        operation_id=compiled.operation_id,
        inputs=compiled.inputs,
        validation_status=_validation_status(validation),
        live_metadata_dependencies=_dependencies(validation),
        date_range=_date_range(start, end) if start is not None else None,
        date_override_applied=start is not None,
        limitations=(),
    )


def inspect_saved_artifact(
    client: Any,
    definition: Mapping[str, Any],
    *,
    app: str,
    workspace: Any,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Return eligibility without exposing config or compiled request values."""

    _paired_window(start, end)
    mode = saved_artifact_mode(definition)
    if mode == WEB_ARTIFACT and start is None:
        # A fixed synthetic window validates the registered Web structure and
        # FieldPolicy only.  It is never returned or executed.
        compiled = compile_saved_artifact(
            client,
            definition,
            app=app,
            workspace=workspace,
            start=_INSPECTION_DATE,
            end=_INSPECTION_DATE,
        )
        summary = compiled.safe_summary()
        summary.update(
            {
                "replay_status": "requires_window",
                "date_range": None,
                "date_override_applied": False,
            }
        )
        return summary
    compiled = compile_saved_artifact(
        client,
        definition,
        app=app,
        workspace=workspace,
        start=start,
        end=end,
    )
    return {**compiled.safe_summary(), "replay_status": "supported"}


def prepare_saved_artifact(
    client: Any,
    definition: Mapping[str, Any],
    *,
    app: str,
    workspace: Any,
    start: str | None = None,
    end: str | None = None,
) -> dict[str, Any]:
    """Return a caller-safe preview for compact or Web saved definitions."""

    mode = saved_artifact_mode(definition)
    if mode == COMPACT_SPEC:
        kind = supported_subject(definition.get("subject"))
        preview = prepare_query_spec(
            client,
            kind,
            decoded_config(definition.get("config")),
            workspace=workspace,
            app=app,
            start=start,
            end=end,
        )
        return {
            **preview,
            "artifact_mode": mode,
            "date_range": _date_range(start, end) if start is not None else None,
            "date_override_applied": start is not None,
            "limitations": [],
        }
    compiled = compile_saved_artifact(
        client,
        definition,
        app=app,
        workspace=workspace,
        start=start,
        end=end,
    )
    return {
        **compiled.safe_summary(),
        "compiled_input": None,
        "input_values_redacted": True,
        "plan_node": None,
        "next_action": (
            "Execute the saved reference with the same explicit date window; "
            "the compiled Web request is intentionally not returned."
        ),
    }


def _dashboard_report(
    definition: Mapping[str, Any], config: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "report_id": str(definition.get("id") or "local-definition"),
        "name": str(definition.get("name") or "saved-analysis"),
        "subject": definition.get("subject"),
        "config": config,
    }


def _paired_window(start: Any, end: Any) -> None:
    if (start is None) != (end is None):
        raise InputValidationError(
            f"actual value: {actual_value((start, end))}; " + ("saved Analysis start and end must be provided together"),
            field="start/end",
        )
    if start is not None:
        validate_dashboard_window(start, end)


def _date_range(start: str, end: str) -> dict[str, Any]:
    return {"start": start.strip(), "end": end.strip(), "inclusive": True}


def _validation_status(value: Mapping[str, Any]) -> str:
    status = str(value.get("status") or "").strip().casefold()
    return status if status in {"valid_offline", "needs_live_metadata"} else "valid_offline"


def _dependencies(value: Mapping[str, Any]) -> tuple[str, ...]:
    raw = value.get("live_metadata_dependencies", ())
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(str(item) for item in raw if isinstance(item, str))


__all__ = [
    "COMPACT_SPEC",
    "WEB_ARTIFACT",
    "CompiledSavedArtifact",
    "compile_saved_artifact",
    "inspect_saved_artifact",
    "prepare_saved_artifact",
    "preflight_saved_definition",
    "saved_artifact_mode",
    "validate_saved_window",
]
