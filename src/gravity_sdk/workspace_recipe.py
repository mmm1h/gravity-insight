"""Schema-shaped validation for project-owned workspace recipes."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping


_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_INPUT_PATH_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*(?:\.(?:[A-Za-z_][A-Za-z0-9_]*|[0-9]+))*$"
)
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_FIELDS = {
    "operation",
    "bindings",
    "parameters",
    "required_parameters",
    "input",
    "output_fields",
    "contract_fingerprint",
}


@dataclass(frozen=True)
class RecipeBindings:
    app_ref: str | None
    app_input: str | None
    report_ref: str | None
    report_input: str | None


@dataclass(frozen=True)
class Recipe:
    """Validated project-owned query declaration."""

    name: str
    operation: str
    description: str
    bindings: RecipeBindings
    parameters: Mapping[str, str]
    required_parameters: tuple[str, ...]
    input: Mapping[str, Any]
    output_fields: tuple[str, ...]
    contract_fingerprint: str


def validate_recipes(
    value: Any,
    apps: Mapping[str, int],
    path: Path,
    *,
    error: Callable[[str], Exception],
) -> dict[str, Recipe]:
    if not isinstance(value, dict):
        raise error(f"{path}: [recipes] must be a table")
    recipes: dict[str, Recipe] = {}
    for name, raw in value.items():
        recipes[name] = _validate_recipe(name, raw, apps, path, error)
    return recipes


def _validate_recipe(
    name: str,
    raw: Any,
    apps: Mapping[str, int],
    path: Path,
    error: Callable[[str], Exception],
) -> Recipe:
    if not _NAME_RE.fullmatch(name) or not isinstance(raw, dict):
        raise error(f"{path}: invalid recipe definition: {name!r}")
    _validate_fields(name, raw, path, error)
    operation = raw["operation"]
    description = raw.get("description", "")
    if not isinstance(operation, str) or not _NAME_RE.fullmatch(operation):
        raise error(f"{path}: recipes.{name}.operation must be an operation id")
    if not isinstance(description, str):
        raise error(f"{path}: recipes.{name}.description must be a string")
    bindings = _validate_bindings(name, raw["bindings"], apps, path, error)
    parameters = _validate_parameters(name, raw["parameters"], path, error)
    required_parameters = _string_list(
        raw["required_parameters"], name, "required_parameters", path, error, empty=True
    )
    if len(required_parameters) != len(set(required_parameters)):
        raise error(f"{path}: recipes.{name}.required_parameters contains duplicates")
    undeclared = sorted(set(required_parameters) - set(parameters))
    if undeclared:
        raise error(
            f"{path}: recipes.{name}.required_parameters are not declared: "
            + ", ".join(undeclared)
        )
    static_input = raw["input"]
    if not isinstance(static_input, dict):
        raise error(f"{path}: recipes.{name}.input must be a table")
    _json_value(static_input, name, path, error)
    output_fields = _string_list(
        raw["output_fields"], name, "output_fields", path, error, empty=False
    )
    if len(output_fields) != len(set(output_fields)):
        raise error(f"{path}: recipes.{name}.output_fields contains duplicates")
    fingerprint = _fingerprint(name, raw["contract_fingerprint"], path, error)
    return Recipe(
        name, operation, description, bindings, parameters,
        tuple(required_parameters), dict(static_input), tuple(output_fields), fingerprint,
    )


def _validate_fields(
    name: str, raw: Mapping[str, Any], path: Path, error: Callable[[str], Exception]
) -> None:
    missing = sorted(_REQUIRED_FIELDS - set(raw))
    unknown = sorted(set(raw) - (_REQUIRED_FIELDS | {"description"}))
    if missing or unknown:
        details = [
            *(f"missing {field}" for field in missing),
            *(f"unknown {field}" for field in unknown),
        ]
        raise error(f"{path}: invalid recipes.{name}: {', '.join(details)}")


def _validate_bindings(
    name: str,
    value: Any,
    apps: Mapping[str, int],
    path: Path,
    error: Callable[[str], Exception],
) -> RecipeBindings:
    if not isinstance(value, dict):
        raise error(f"{path}: recipes.{name}.bindings must be a table")
    allowed = {"app_ref", "app_input", "report_ref", "report_input"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise error(
            f"{path}: recipes.{name}.bindings has unknown fields: " + ", ".join(unknown)
        )
    app_ref, app_input = value.get("app_ref"), value.get("app_input")
    report_ref, report_input = value.get("report_ref"), value.get("report_input")
    _paired(name, "app", app_ref, app_input, path, error)
    _paired(name, "report", report_ref, report_input, path, error)
    if app_ref is None and report_ref is None:
        raise error(f"{path}: recipes.{name}.bindings requires app_ref or report_ref")
    if app_ref is not None and (not isinstance(app_ref, str) or app_ref not in apps):
        raise error(
            f"{path}: recipes.{name}.bindings.app_ref must name an alias in [apps]"
        )
    _input_path(name, "app_input", app_input, path, error)
    _input_path(name, "report_input", report_input, path, error)
    if report_ref is not None and (
        not isinstance(report_ref, str) or not report_ref.strip()
    ):
        raise error(
            f"{path}: recipes.{name}.bindings.report_ref must be a non-empty string"
        )
    return RecipeBindings(app_ref, app_input, report_ref, report_input)


def _paired(
    name: str,
    prefix: str,
    reference: Any,
    input_path: Any,
    path: Path,
    error: Callable[[str], Exception],
) -> None:
    if (reference is None) != (input_path is None):
        raise error(
            f"{path}: recipes.{name}.bindings {prefix}_ref and {prefix}_input must be paired"
        )


def _input_path(
    name: str,
    field: str,
    selected: Any,
    path: Path,
    error: Callable[[str], Exception],
) -> None:
    if selected is not None and (
        not isinstance(selected, str) or not _INPUT_PATH_RE.fullmatch(selected)
    ):
        raise error(f"{path}: recipes.{name}.bindings.{field} must be an input path")


def _validate_parameters(
    name: str, value: Any, path: Path, error: Callable[[str], Exception]
) -> dict[str, str]:
    if not isinstance(value, dict):
        raise error(f"{path}: recipes.{name}.parameters must be a table")
    parameters: dict[str, str] = {}
    for parameter, input_path in value.items():
        if not _NAME_RE.fullmatch(parameter) or not isinstance(input_path, str):
            raise error(f"{path}: invalid recipes.{name}.parameters entry: {parameter!r}")
        if not _INPUT_PATH_RE.fullmatch(input_path):
            raise error(
                f"{path}: recipes.{name}.parameters.{parameter} must be an input path"
            )
        parameters[parameter] = input_path
    return parameters


def _string_list(
    value: Any,
    name: str,
    field: str,
    path: Path,
    error: Callable[[str], Exception],
    *,
    empty: bool,
) -> list[str]:
    if not isinstance(value, list) or (not value and not empty) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise error(f"{path}: recipes.{name}.{field} must be a string array")
    return value


def _json_value(
    value: Any, name: str, path: Path, error: Callable[[str], Exception]
) -> None:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise error(f"{path}: recipes.{name}.input contains a non-JSON value") from exc


def _fingerprint(
    name: str, value: Any, path: Path, error: Callable[[str], Exception]
) -> str:
    if not isinstance(value, str) or not _FINGERPRINT_RE.fullmatch(value):
        raise error(
            f"{path}: recipes.{name}.contract_fingerprint must be 64 lowercase hex characters"
        )
    return value


__all__ = ["Recipe", "RecipeBindings", "validate_recipes"]
