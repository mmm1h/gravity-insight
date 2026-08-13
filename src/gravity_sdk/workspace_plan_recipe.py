"""Typed expansion for project-owned, multi-node Plan recipes."""

from __future__ import annotations

import copy
import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

from .errors import ErrorCategory, InputValidationError
from .plan import validate_plan
from .plan_binding import pointer_tokens, resolve_pointer, set_pointer, validate_json


_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_PARAMETER_TYPES = frozenset({"string", "integer", "number", "boolean"})
_STRING_FORMATS = frozenset({"date", "date-time"})
_RECIPE_FIELDS = frozenset({"description", "parameters", "plan"})
_PARAMETER_FIELDS = frozenset({"type", "format", "required", "bindings"})


class PlanRecipeError(InputValidationError):
    """A local, zero-request failure in a workspace Plan recipe contract."""

    code = "PLAN_RECIPE_INVALID"
    category = ErrorCategory.LOCAL

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(
            message,
            field=field,
            next_action="Correct the workspace Plan recipe or its parameters, then retry.",
        )


@dataclass(frozen=True)
class PlanRecipeParameter:
    name: str
    value_type: str
    value_format: str | None
    required: bool
    bindings: tuple[str, ...]

    def contract(self) -> dict[str, Any]:
        contract = {
            "type": self.value_type,
            "required": self.required,
            "bindings": list(self.bindings),
        }
        if self.value_format is not None:
            contract["format"] = self.value_format
        return contract


@dataclass(frozen=True)
class PlanRecipe:
    """One validated literal Plan plus explicit typed request bindings."""

    name: str
    description: str
    parameters: Mapping[str, PlanRecipeParameter]
    plan: Mapping[str, Any]

    def parameter_contract(self) -> dict[str, Any]:
        return {
            name: parameter.contract()
            for name, parameter in sorted(self.parameters.items())
        }


def validate_plan_recipes(
    value: Any,
    path: Path,
    *,
    error: Callable[[str], Exception],
) -> dict[str, PlanRecipe]:
    """Validate every Plan recipe without constructing a client or adapter."""

    if not isinstance(value, dict):
        raise error(f"{path}: [plan_recipes] must be a table")
    return {
        name: _validate_plan_recipe(name, raw, path, error)
        for name, raw in value.items()
    }


def expand_plan_recipe(
    recipe: PlanRecipe,
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the exact Plan v1 object produced by typed request-leaf binding."""

    supplied = dict(parameters or {})
    unknown = sorted(set(supplied) - set(recipe.parameters))
    if unknown:
        raise PlanRecipeError(
            f"unknown Plan recipe parameter: {unknown[0]}", field=f"parameters.{unknown[0]}"
        )
    missing = sorted(
        name
        for name, parameter in recipe.parameters.items()
        if parameter.required and name not in supplied
    )
    if missing:
        raise PlanRecipeError(
            f"missing required Plan recipe parameter: {missing[0]}",
            field=f"parameters.{missing[0]}",
        )

    expanded = copy.deepcopy(dict(recipe.plan))
    for name, value in supplied.items():
        parameter = recipe.parameters[name]
        _validate_parameter_value(parameter, value)
        for pointer in parameter.bindings:
            try:
                resolve_pointer(expanded, pointer)
                set_pointer(expanded, pointer, copy.deepcopy(value))
            except (IndexError, KeyError, TypeError, ValueError) as exc:
                raise PlanRecipeError(
                    f"Plan recipe parameter binding path does not exist: {pointer}",
                    field=f"parameters.{name}.bindings",
                ) from exc
    validate_plan(expanded)
    return expanded


def parse_plan_recipe_parameters(values: list[str] | None) -> dict[str, Any]:
    """Parse repeatable NAME=JSON_VALUE arguments under the local recipe boundary."""

    parameters: dict[str, Any] = {}
    for assignment in values or []:
        if "=" not in assignment:
            raise PlanRecipeError("--param must use NAME=VALUE", field="param")
        name, raw = assignment.split("=", 1)
        if not _NAME_RE.fullmatch(name) or name in parameters:
            raise PlanRecipeError(
                "--param names must be unique Plan recipe parameter names", field="param"
            )
        try:
            parameters[name] = json.loads(raw)
        except json.JSONDecodeError:
            parameters[name] = raw
    return parameters


def _validate_plan_recipe(
    name: str,
    raw: Any,
    path: Path,
    error: Callable[[str], Exception],
) -> PlanRecipe:
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name) or not isinstance(raw, dict):
        raise error(f"{path}: invalid Plan recipe definition: {name!r}")
    missing = sorted({"parameters", "plan"} - set(raw))
    unknown = sorted(set(raw) - _RECIPE_FIELDS)
    if missing or unknown:
        details = [
            *(f"missing {field}" for field in missing),
            *(f"unknown {field}" for field in unknown),
        ]
        raise error(f"{path}: invalid plan_recipes.{name}: {', '.join(details)}")
    description = raw.get("description", "")
    if not isinstance(description, str):
        raise error(f"{path}: plan_recipes.{name}.description must be a string")
    plan = raw["plan"]
    if not isinstance(plan, dict):
        raise error(f"{path}: plan_recipes.{name}.plan must be a table")
    try:
        validate_json(plan)
        validate_plan(plan)
    except (TypeError, ValueError) as exc:
        raise error(f"{path}: plan_recipes.{name}.plan is not a valid gravity.plan.v1 object") from exc
    parameters = _validate_parameters(name, raw["parameters"], plan, path, error)
    return PlanRecipe(name, description, parameters, copy.deepcopy(plan))


def _validate_parameters(
    recipe_name: str,
    value: Any,
    plan: Mapping[str, Any],
    path: Path,
    error: Callable[[str], Exception],
) -> dict[str, PlanRecipeParameter]:
    if not isinstance(value, dict) or not value:
        raise error(f"{path}: plan_recipes.{recipe_name}.parameters must be a non-empty table")
    parameters: dict[str, PlanRecipeParameter] = {}
    claimed_bindings: set[str] = set()
    for name, raw in value.items():
        field = f"plan_recipes.{recipe_name}.parameters.{name}"
        parameter = _parameter_definition(name, raw, field, path, error)
        _validate_parameter_bindings(
            parameter, field, plan, claimed_bindings, path, error
        )
        parameters[name] = parameter
    return parameters


def _parameter_definition(
    name: Any,
    raw: Any,
    field: str,
    path: Path,
    error: Callable[[str], Exception],
) -> PlanRecipeParameter:
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name) or not isinstance(raw, dict):
        raise error(f"{path}: invalid {field}")
    missing = sorted({"type", "required", "bindings"} - set(raw))
    unknown = sorted(set(raw) - _PARAMETER_FIELDS)
    if missing or unknown:
        raise error(f"{path}: invalid {field} fields")
    value_type = raw["type"]
    value_format = raw.get("format")
    required = raw["required"]
    bindings = _binding_array(raw["bindings"], field, path, error)
    if value_type not in _PARAMETER_TYPES:
        raise error(f"{path}: {field}.type is unsupported")
    if value_format is not None and (
        value_type != "string" or value_format not in _STRING_FORMATS
    ):
        raise error(f"{path}: {field}.format is unsupported for {value_type}")
    if type(required) is not bool:
        raise error(f"{path}: {field}.required must be a boolean")
    return PlanRecipeParameter(
        name, str(value_type), value_format, required, tuple(bindings)
    )


def _binding_array(
    value: Any,
    field: str,
    path: Path,
    error: Callable[[str], Exception],
) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) for item in value)
        or len(value) != len(set(value))
    ):
        raise error(f"{path}: {field}.bindings must be a unique non-empty string array")
    return value


def _validate_parameter_bindings(
    parameter: PlanRecipeParameter,
    field: str,
    plan: Mapping[str, Any],
    claimed: set[str],
    path: Path,
    error: Callable[[str], Exception],
) -> None:
    for pointer in parameter.bindings:
        _validate_binding_path(field, pointer, plan, claimed, path, error)
        try:
            _validate_parameter_value(parameter, resolve_pointer(plan, pointer))
        except PlanRecipeError as exc:
            raise error(f"{path}: {field} does not match the bound literal value") from exc
        claimed.add(pointer)


def _validate_binding_path(
    field: str,
    pointer: str,
    plan: Mapping[str, Any],
    claimed: set[str],
    path: Path,
    error: Callable[[str], Exception],
) -> None:
    try:
        tokens = pointer_tokens(pointer)
        valid_scope = (
            len(tokens) >= 4
            and tokens[0] == "nodes"
            and tokens[1].isascii()
            and tokens[1].isdigit()
            and tokens[2] == "request"
        )
        if not valid_scope or pointer in claimed:
            raise ValueError("binding is outside a unique request leaf")
        bound = resolve_pointer(plan, pointer)
        if isinstance(bound, (dict, list)) or bound is None:
            raise TypeError("binding target is not an existing non-null scalar")
    except (IndexError, KeyError, TypeError, ValueError) as exc:
        raise error(f"{path}: {field}.bindings path does not exist: {pointer}") from exc


def _validate_parameter_value(parameter: PlanRecipeParameter, value: Any) -> None:
    value_type = parameter.value_type
    valid = {
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: type(item) is int,
        "number": lambda item: type(item) is int
        or type(item) is float and math.isfinite(item),
        "boolean": lambda item: type(item) is bool,
    }[value_type](value)
    if not valid:
        raise PlanRecipeError(
            f"Plan recipe parameter {parameter.name} must be {value_type}",
            field=f"parameters.{parameter.name}",
        )
    if parameter.value_format == "date":
        try:
            if len(value) != 10 or date.fromisoformat(value).isoformat() != value:
                raise ValueError("date is not canonical")
        except (TypeError, ValueError) as exc:
            raise PlanRecipeError(
                f"Plan recipe parameter {parameter.name} must use YYYY-MM-DD",
                field=f"parameters.{parameter.name}",
            ) from exc
    if parameter.value_format == "date-time":
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("date-time lacks an offset")
        except (TypeError, ValueError) as exc:
            raise PlanRecipeError(
                f"Plan recipe parameter {parameter.name} must be an ISO 8601 date-time with offset",
                field=f"parameters.{parameter.name}",
            ) from exc


__all__ = [
    "PlanRecipe",
    "PlanRecipeError",
    "PlanRecipeParameter",
    "expand_plan_recipe",
    "parse_plan_recipe_parameters",
    "validate_plan_recipes",
]
