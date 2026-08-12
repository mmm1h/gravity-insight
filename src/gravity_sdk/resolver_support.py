"""Mechanical input binding and diagnostics used by the Resolver pipeline."""

from __future__ import annotations

import copy
import difflib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import (
    ErrorCode,
    ErrorDetail,
    GravityInsightError,
    InputValidationError,
    error_detail_from_exception,
)
from .find_metadata import search_metadata
from .workspace import Recipe, Workspace


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ][^ ]+)?$")


def parse_parameter_assignments(values: list[str] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for assignment in values or []:
        if "=" not in assignment:
            raise InputValidationError("--param must use NAME=VALUE", field="param")
        name, raw = assignment.split("=", 1)
        if not name or "." in name:
            raise InputValidationError(
                "--param name must be a non-empty recipe parameter", field="param"
            )
        try:
            result[name] = json.loads(raw)
        except json.JSONDecodeError:
            result[name] = raw
    return result


def build_inputs(
    recipe: Recipe | None,
    workspace: Workspace,
    description: Mapping[str, Any],
    supplied: Mapping[str, Any],
    parameters: Mapping[str, Any],
    *,
    app: str | int | None,
    start: str | None,
    end: str | None,
) -> dict[str, Any]:
    inputs = copy.deepcopy(dict(recipe.input)) if recipe is not None else {}
    inputs.update(copy.deepcopy(dict(supplied)))
    if recipe is not None:
        return _build_recipe_inputs(
            inputs,
            recipe,
            workspace,
            description,
            parameters,
            app=app,
            start=start,
            end=end,
        )
    return _build_direct_inputs(
        inputs, workspace, description, parameters, app=app, start=start, end=end
    )


def _build_recipe_inputs(
    inputs: dict[str, Any],
    recipe: Recipe,
    workspace: Workspace,
    description: Mapping[str, Any],
    parameters: Mapping[str, Any],
    *,
    app: str | int | None,
    start: str | None,
    end: str | None,
) -> dict[str, Any]:
    values = dict(parameters)
    if start is not None:
        values["start"] = start
    if end is not None:
        values["end"] = end
    unknown = sorted(set(values) - set(recipe.parameters))
    if unknown:
        raise InputValidationError(
            "unknown recipe parameters: " + ", ".join(unknown), field="param"
        )
    missing = sorted(set(recipe.required_parameters) - set(values))
    if missing:
        raise InputValidationError(
            "missing required recipe parameters: " + ", ".join(missing), field="param"
        )
    for name, value in values.items():
        set_input_path(inputs, recipe.parameters[name], value)
    bindings = recipe.bindings
    if bindings.app_ref is not None and bindings.app_input is not None:
        selected = app if app is not None else bindings.app_ref
        set_input_path(inputs, bindings.app_input, str(workspace.resolve_app(selected)))
    elif app is not None:
        _bind_direct_app(inputs, description, workspace.resolve_app(app), recipe.operation)
    if bindings.report_ref is not None and bindings.report_input is not None:
        set_input_path(inputs, bindings.report_input, bindings.report_ref)
    return inputs


def _build_direct_inputs(
    inputs: dict[str, Any],
    workspace: Workspace,
    description: Mapping[str, Any],
    parameters: Mapping[str, Any],
    *,
    app: str | int | None,
    start: str | None,
    end: str | None,
) -> dict[str, Any]:
    operation_id = str(description.get("operation_id", ""))
    if parameters:
        raise InputValidationError(
            "--param is available only with @recipe selectors", field="param"
        )
    if app is not None:
        _bind_direct_app(inputs, description, workspace.resolve_app(app), operation_id)
    _bind_direct_dates(inputs, description, start, end, operation_id)
    return inputs


def _bind_direct_app(
    inputs: dict[str, Any],
    description: Mapping[str, Any],
    app_id: int,
    operation_id: str,
) -> None:
    fields = description.get("input_schema", {})
    if not isinstance(fields, Mapping) or "app_id" not in fields:
        raise InputValidationError(f"{operation_id} does not accept --app", field="app")
    inputs["app_id"] = str(app_id)


def _bind_direct_dates(
    inputs: dict[str, Any],
    description: Mapping[str, Any],
    start: str | None,
    end: str | None,
    operation_id: str,
) -> None:
    if (start is None) != (end is None):
        raise InputValidationError("--start and --end must be supplied together")
    if start is None:
        return
    fields = description.get("input_schema", {})
    fields = fields if isinstance(fields, Mapping) else {}
    if {"start", "end"} <= set(fields):
        inputs.update({"start": start, "end": end})
    elif {"start_date", "end_date"} <= set(fields):
        inputs.update({"start_date": start, "end_date": end})
    elif _object_date_list(fields):
        set_input_path(inputs, "date_list.0.start_date", start)
        set_input_path(inputs, "date_list.0.end_date", end)
    elif isinstance(fields.get("date_list"), Mapping):
        inputs["date_list"] = [start, end]
    else:
        raise InputValidationError(
            f"{operation_id} does not expose a schema-derived date input; use --input or --set",
            field="start",
        )


def _object_date_list(fields: Mapping[str, Any]) -> bool:
    date_list = fields.get("date_list")
    return isinstance(date_list, Mapping) and date_list.get("item_type") == "object"


def set_input_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cursor: Any = target
    for index, part in enumerate(parts[:-1]):
        next_is_index = parts[index + 1].isdigit()
        if part.isdigit():
            cursor = _array_child(cursor, int(part), next_is_index)
        else:
            cursor = _object_child(cursor, part, next_is_index)
    leaf = parts[-1]
    if leaf.isdigit():
        _set_array_value(cursor, int(leaf), value)
    elif isinstance(cursor, dict):
        cursor[leaf] = value
    else:
        raise InputValidationError(f"recipe input path crosses a non-object at {leaf}")


def _array_child(value: Any, index: int, next_is_index: bool) -> Any:
    if not isinstance(value, list):
        raise InputValidationError(f"recipe input path requires an array at {index}")
    while len(value) <= index:
        value.append([] if next_is_index else {})
    return value[index]


def _object_child(value: Any, name: str, next_is_index: bool) -> Any:
    if not isinstance(value, dict):
        raise InputValidationError(f"recipe input path crosses a non-object at {name}")
    child = value.get(name)
    if child is None:
        child = [] if next_is_index else {}
        value[name] = child
    return child


def _set_array_value(value: Any, index: int, selected: Any) -> None:
    if not isinstance(value, list):
        raise InputValidationError(f"recipe input path requires an array at {index}")
    while len(value) <= index:
        value.append(None)
    value[index] = selected


def missing_parent_bindings(
    description: Mapping[str, Any], inputs: Mapping[str, Any]
) -> list[Mapping[str, Any]]:
    parents = description.get("required_parent", [])
    if not isinstance(parents, list):
        return []
    return [
        parent
        for parent in parents
        if isinstance(parent, Mapping)
        and str(parent.get("target_input") or "") not in inputs
    ]


def apply_parent_selections(inputs: dict[str, Any], parents: Mapping[str, Any]) -> None:
    for binding in parents.get("bindings", []):
        if not isinstance(binding, Mapping) or binding.get("selected") is None:
            continue
        target = binding.get("target_input")
        if isinstance(target, str) and target:
            inputs[target] = binding["selected"]


def validation_summary(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "status": value.get("status", "error"),
        "ok": value.get("ok") is True,
        "network_called": value.get("network_called", False),
        "live_metadata_dependencies": value.get("live_metadata_dependencies", []),
        "error": value.get("error"),
    }


def validation_diagnostic(
    validation: Mapping[str, Any], operation_id: str
) -> dict[str, Any]:
    error = validation.get("error")
    return {
        "code": "input_invalid",
        "priority": 10,
        "message": "The built input does not match the current operation contract.",
        "error": error if isinstance(error, Mapping) else None,
        "next_action": f"Run `gravity insight operations describe {operation_id}` and correct --input, --set, or recipe parameters.",
    }


def add_parent_diagnostics(
    diagnostics: list[dict[str, Any]],
    bindings: list[Mapping[str, Any]],
    operation_id: str,
) -> None:
    for binding in bindings:
        diagnostics.append({
            "code": "parent_required",
            "priority": 20,
            "message": "A declared parent resource still requires caller selection.",
            "target_input": binding.get("target_input"),
            "parent_operation_id": binding.get("parent_operation_id"),
            "candidates": list(binding.get("candidates", []))[:20],
            "next_action": f"Run `gravity insight parents resolve {operation_id}` or bind one candidate with --set.",
        })


def add_event_diagnostics(
    diagnostics: list[dict[str, Any]],
    inputs: Mapping[str, Any],
    description: Mapping[str, Any],
    *,
    database: Path | None,
) -> None:
    strings = _candidate_strings(inputs, description)
    if not strings:
        return
    try:
        names = _event_names(database, inputs.get("app_id"))
    except (InputValidationError, OSError):
        diagnostics.append({
            "code": "metadata_unavailable",
            "priority": 50,
            "message": "The local metadata catalog is unavailable.",
            "next_action": "Run `gravity metadata sync --all-apps` before requesting local event suggestions.",
        })
        return
    suggestions = _closest_events(strings, names)
    if suggestions:
        diagnostics.append({
            "code": "closest_event_names",
            "priority": 40,
            "message": "Local metadata contains mechanically similar event names; no business binding was inferred.",
            "suggestions": suggestions[:5],
        })


def _event_names(database: Path | None, app_id: Any) -> list[str]:
    catalog = search_metadata(
        "",
        database=database,
        app_id=str(app_id) if app_id is not None else None,
        kind="event",
        limit=100,
    )
    return sorted({
        str(item["name"])
        for item in catalog.get("results", [])
        if isinstance(item, Mapping) and item.get("name")
    })


def _closest_events(
    strings: list[tuple[str, str]], names: list[str]
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for path, selected in strings:
        scored = sorted(
            (
                (
                    round(difflib.SequenceMatcher(
                        None, selected.casefold(), name.casefold()
                    ).ratio() * 100),
                    name,
                )
                for name in names
            ),
            reverse=True,
        )[:3]
        matches = [{"name": name, "score": score} for score, name in scored if score >= 45]
        if matches:
            suggestions.append({"input_path": path, "candidates": matches})
    return suggestions


def _candidate_strings(
    inputs: Mapping[str, Any], description: Mapping[str, Any]
) -> list[tuple[str, str]]:
    input_schema = description.get("input_schema", {})
    sensitive = _sensitive_fields(input_schema)
    found: list[tuple[str, str]] = []

    def visit(value: Any, path: str, root: str) -> None:
        if root in sensitive:
            return
        if isinstance(value, Mapping):
            for name, item in value.items():
                visit(item, f"{path}.{name}" if path else str(name), root or str(name))
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                visit(item, f"{path}.{index}", root)
        elif isinstance(value, str) and 2 <= len(value) <= 128:
            if not value.isdecimal() and not _DATE_RE.fullmatch(value):
                found.append((path, value))

    visit(inputs, "", "")
    return found[:20]


def _sensitive_fields(input_schema: Any) -> set[str]:
    if not isinstance(input_schema, Mapping):
        return set()
    return {
        str(name)
        for name, specification in input_schema.items()
        if isinstance(specification, Mapping) and specification.get("sensitive") is True
    }


def description_fingerprint(description: Mapping[str, Any]) -> str | None:
    health = description.get("health")
    value = health.get("contract_fingerprint") if isinstance(health, Mapping) else None
    return value if isinstance(value, str) and value else None


def error_diagnostic(exc: Exception, *, priority: int) -> dict[str, Any]:
    if isinstance(exc, GravityInsightError):
        detail = error_detail_from_exception(exc).to_dict()
        return {
            "code": str(detail.get("code", "error")).casefold(),
            "priority": priority,
            "message": detail.get("message", str(exc)),
            "error": detail,
            "next_action": detail.get("next_action"),
        }
    detail = ErrorDetail.create(
        ErrorCode.INPUT_INVALID if isinstance(exc, ValueError) else ErrorCode.LOCAL_IO_ERROR,
        (
            "Resolver could not bind or validate this request."
            if isinstance(exc, ValueError)
            else "Resolver failed while processing a local dependency."
        ),
        next_action=(
            "Review the selector inputs and retry this request."
            if isinstance(exc, ValueError)
            else "Check the local workspace and paths, then retry this request."
        ),
    )
    value = detail.to_dict()
    return {
        "code": detail.code.casefold(),
        "priority": priority,
        "message": detail.message,
        "error": value,
        "next_action": detail.next_action,
    }


def diagnostic(
    code: str,
    priority: int,
    message: str,
    *,
    next_action: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "priority": priority, "message": message}
    if next_action:
        result["next_action"] = next_action
    return result


__all__ = [
    "add_event_diagnostics", "add_parent_diagnostics", "apply_parent_selections",
    "build_inputs", "description_fingerprint", "diagnostic", "error_diagnostic",
    "missing_parent_bindings", "parse_parameter_assignments", "validation_diagnostic",
    "validation_summary",
]
