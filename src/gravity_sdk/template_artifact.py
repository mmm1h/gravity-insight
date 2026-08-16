"""Strict compilation and quarantine policy for Analysis template config."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .analysis_spec import compile_query_spec
from .dashboard_artifact import compile_dashboard_chart, validate_dashboard_window
from .dashboard_artifact_contract import SUBJECT_KINDS
from .errors import InputValidationError, UnsupportedOperationError
from .saved_analysis_support import decoded_config


_COMPACT_KINDS = frozenset({"event", "funnel", "retention", "property", "scatter"})
_SUBJECT_BY_KIND = {kind: subject for subject, kind in SUBJECT_KINDS.items()}
_ORIGIN_FIELDS = frozenset(
    {
        "Filtering", "compareList", "dateListFormModel", "date_extra_data",
        "filterCondition", "groupBy", "groupByCreateTime", "queryItemList",
        "splitEvent", "splitEventOtherData",
    }
)


@dataclass(frozen=True)
class CompiledTemplate:
    mode: str
    kind: str
    operation_id: str
    inputs: dict[str, Any]
    validation_status: str
    live_metadata_dependencies: tuple[str, ...]
    date_override_applied: bool
    limitations: tuple[str, ...]


def compile_template_artifact(
    client: Any,
    item: Mapping[str, Any],
    *,
    app_id: str,
    workspace: Any,
    start: str,
    end: str,
) -> dict[str, Any]:
    """Compile only proven config shapes; return value-free gaps otherwise."""

    validate_dashboard_window(start, end)
    config = decoded_config(item.get("config"))
    if "originParams" in config:
        return _origin_report(config)
    kind = _template_kind(item.get("sub_type"))
    if kind is None:
        return _gap(
            "unknown", [_quarantine("config.subject", "unregistered_template_sub_type")]
        )
    if "calculateBody" in config:
        return _compile_web(client, item, config, kind, app_id, start, end)
    return _compile_compact(client, config, kind, app_id, workspace, start, end)


def _compile_web(
    client: Any, item: Mapping[str, Any], config: Mapping[str, Any], kind: str,
    app_id: str, start: str, end: str,
) -> dict[str, Any]:
    try:
        compiled = compile_dashboard_chart(
            client,
            {
                "report_id": _identifier(item.get("id"), "id"),
                "name": _text(item.get("name"), "name"),
                "subject": _SUBJECT_BY_KIND[kind],
                "config": config,
            },
            app_id=app_id,
            start=start,
            end=end,
        )
    except (InputValidationError, UnsupportedOperationError) as exc:
        return _compile_gap("web_artifact", exc)
    normalized = CompiledTemplate(
        "web_artifact", compiled.kind, compiled.operation_id, compiled.inputs,
        compiled.validation_status, compiled.live_metadata_dependencies,
        compiled.date_override_applied,
        compiled.limitations,
    )
    return _success(normalized)


def _compile_compact(
    client: Any, config: Mapping[str, Any], kind: str, app_id: str,
    workspace: Any, start: str, end: str,
) -> dict[str, Any]:
    try:
        compiled = compile_query_spec(
            kind, config, workspace=workspace, app=app_id, start=start, end=end
        )
    except (InputValidationError, UnsupportedOperationError) as exc:
        return _compile_gap("compact_spec", exc)
    validation = client.validate(compiled.operation_id, compiled.inputs)
    if not isinstance(validation, Mapping) or validation.get("ok") is not True:
        return _gap("compact_spec", [_quarantine("config", "stable_validation_failed")])
    status = str(validation.get("status") or "valid_offline")
    dependencies = _dependencies(validation)
    return _success(CompiledTemplate(
        "compact_spec", kind, compiled.operation_id, compiled.inputs,
        status, dependencies, kind != "property", (),
    ))


def _success(compiled: CompiledTemplate) -> dict[str, Any]:
    return {
        "artifact_mode": compiled.mode,
        "kind": compiled.kind,
        "operation_id": compiled.operation_id,
        "validation_status": compiled.validation_status,
        "live_metadata_dependencies": list(compiled.live_metadata_dependencies),
        "date_override_applied": compiled.date_override_applied,
        "limitations": list(compiled.limitations),
        "quarantine": [],
        "compiled": compiled,
    }


def _origin_report(config: Mapping[str, Any]) -> dict[str, Any]:
    unknown_top = set(config) - {"originParams", "events", "user_properties"}
    origin = config.get("originParams")
    if not isinstance(origin, Mapping):
        return _gap(
            "origin_params", [_quarantine("config.originParams", "structure_unknown")]
        )
    quarantine: list[dict[str, str]] = []
    if unknown_top:
        quarantine.append(_quarantine("config.<unregistered>", "privacy_review_required"))
    if set(origin) - _ORIGIN_FIELDS:
        quarantine.append(_quarantine(
            "config.originParams.<unregistered>", "privacy_review_required"
        ))
    dispositions = (
        ("Filtering", "filter_shape_not_registered"),
        ("queryItemList", "formula_token_semantics_unproven"),
        ("groupBy", "group_mapping_unproven"),
        ("groupByCreateTime", "time_group_mapping_unproven"),
        ("filterCondition", "condition_combination_semantics_unproven"),
        ("splitEvent", "split_event_mapping_unproven"),
        ("splitEventOtherData", "split_event_auxiliary_mapping_unproven"),
        ("compareList", "period_compare_owned_by_separate_capability"),
    )
    for field, reason in dispositions:
        if field in origin:
            quarantine.append(_quarantine(f"config.originParams.{field}", reason))
    for field in ("dateListFormModel", "date_extra_data"):
        if field in origin:
            quarantine.append(_quarantine(
                f"config.originParams.{field}",
                "replaced_by_explicit_window_but_shape_not_forwarded",
            ))
    for field in ("events", "user_properties"):
        if field in config:
            quarantine.append(_quarantine(
                f"config.{field}", "metadata_only_not_query_semantics"
            ))
    if not quarantine:
        quarantine.append(_quarantine(
            "config.originParams", "structure_not_proven_executable"
        ))
    return _gap("origin_params", quarantine)


def _gap(mode: str, quarantine: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "artifact_mode": mode,
        "kind": None,
        "operation_id": None,
        "date_override_applied": False,
        "limitations": [],
        "quarantine": quarantine,
        "compiled": None,
    }


def _compile_gap(mode: str, exc: Exception) -> dict[str, Any]:
    field = getattr(exc, "field", None)
    selected = (
        "config" if field in {None, "", "spec"}
        else str(field).replace("spec.", "config.", 1)
    )
    return _gap(mode, [_quarantine(
        selected, "unregistered_or_invalid_analysis_semantics"
    )])


def _quarantine(path: str, reason: str) -> dict[str, str]:
    return {"field": path, "disposition": "quarantined", "reason": reason}


def _template_kind(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    selected = value.strip()
    if selected in SUBJECT_KINDS:
        return SUBJECT_KINDS[selected]
    return selected if selected in _COMPACT_KINDS else None


def _identifier(value: Any, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise UnsupportedOperationError(f"Analysis template {field} is invalid")
    selected = str(value).strip()
    if not selected or len(selected) > 256:
        raise UnsupportedOperationError(f"Analysis template {field} is invalid")
    return selected


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise UnsupportedOperationError(f"Analysis template {field} is invalid")
    return value.strip()


def _dependencies(value: Mapping[str, Any]) -> tuple[str, ...]:
    dependencies = value.get("live_metadata_dependencies", ())
    if not isinstance(dependencies, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(
        item for item in dependencies if isinstance(item, str) and item
    ))


__all__ = ["CompiledTemplate", "compile_template_artifact"]
