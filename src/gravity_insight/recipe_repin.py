"""Governed recipe fingerprint rewrite against the current operation contract."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .errors import InputValidationError
from .recipe import check_recipe, declared_input_fields, projection_fields
from .workspace import Recipe, Workspace


REPIN_SCHEMA = "gravity.recipe-repin.v1"
_FINGERPRINT_LINE = "contract_fingerprint"
_TABLE_PREFIX = "[recipes."


def assess_recipe_repin(recipe: Recipe, client: Any) -> dict[str, Any]:
    check = check_recipe(recipe, client)
    try:
        description = client.describe(recipe.operation)
    except Exception:
        description = {}
    if not isinstance(description, Mapping):
        description = {}
    previous = recipe.contract_fingerprint
    current = check.get("contract_fingerprint")
    if not isinstance(current, str):
        current = None
    fingerprint_changed = previous != current
    contract_diff = _contract_diff(recipe, description) if fingerprint_changed else _empty_diff()
    if not fingerprint_changed:
        classification = "unchanged"
    else:
        classification = _classify(contract_diff)
    return {
        "schema_version": REPIN_SCHEMA,
        "ok": False,
        "status": "blocked",
        "offline": True,
        "recipe": recipe.name,
        "operation_id": recipe.operation,
        "stability": check.get("stability"),
        "previous_fingerprint": previous,
        "current_fingerprint": current,
        "classification": classification,
        "contract_diff": contract_diff,
        "check": check,
        "written": False,
        "workspace": None,
        "reason": None,
    }


def apply_recipe_repin(
    workspace: Workspace,
    recipe: Recipe,
    assessment: Mapping[str, Any],
    *,
    allow_breaking: bool = False,
    reason: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    result = dict(assessment)
    classification = str(result.get("classification", ""))
    current = result.get("current_fingerprint")
    if not isinstance(current, str):
        raise InputValidationError(
            f"actual value: {type(current).__name__}; recipe operation has no current contract fingerprint",
            field="contract_fingerprint",
            next_action="Run `gravity recipe check` and inspect the operation description.",
        )
    if classification == "unchanged":
        result.update(ok=True, status="unchanged", written=False, reason=None)
        return _with_workspace(result, workspace)
    if classification == "breaking":
        acknowledged = allow_breaking and isinstance(reason, str) and bool(reason.strip())
        if not acknowledged:
            result.update(
                ok=False,
                status="blocked",
                written=False,
                reason=None,
                next_action=(
                    "Review contract_diff; retry with --allow-breaking "
                    "--reason <audit-text> only if the caller accepts the loss."
                ),
                next={
                    "argv": [
                        "gravity", "recipe", "accept-contract", recipe.name,
                        "--allow-breaking", "--reason", "<audit-text>",
                    ]
                },
            )
            if dry_run or not allow_breaking:
                return _with_workspace(result, workspace)
            raise InputValidationError(
                "actual value: empty; a breaking recipe accept-contract requires an audit reason",
                field="reason",
                next_action="Pass --reason with a non-empty explanation that the caller can audit.",
            )
        result["reason"] = reason.strip()
    elif allow_breaking or (isinstance(reason, str) and reason.strip()):
        raise InputValidationError(
            "actual value: additive; --allow-breaking is only valid for a breaking contract change",
            field="allow_breaking",
            next_action="Omit --allow-breaking and --reason; additive changes can be accepted directly.",
        )
    if dry_run:
        result.update(ok=True, status="preview", written=False)
        return _with_workspace(result, workspace)
    if workspace.path is None:
        raise InputValidationError(
            "actual value: None; no Gravity workspace is configured",
            field="workspace",
            next_action="Pass --workspace pointing at the caller gravity.toml that owns the recipe.",
        )
    _rewrite_fingerprint(workspace.path, recipe.name, current)
    result.update(ok=True, status="accepted", written=True)
    return _with_workspace(result, workspace)


def _contract_diff(recipe: Recipe, description: Mapping[str, Any]) -> dict[str, Any]:
    input_schema = description.get("input_schema", {})
    if not isinstance(input_schema, Mapping):
        input_schema = {}
    declared_inputs = declared_input_fields(recipe)
    current_inputs = {str(name) for name in input_schema}
    required = {
        str(field)
        for field, specification in input_schema.items()
        if isinstance(specification, Mapping)
        and specification.get("required") is True
        and "default" not in specification
    }
    added = [f"input.{name}" for name in sorted(required - declared_inputs)]
    removed = [f"input.{name}" for name in sorted(declared_inputs - current_inputs)]
    type_changed = _type_changes(recipe, input_schema)
    declared_outputs = set(recipe.output_fields)
    current_outputs = projection_fields(description.get("response_projection", {}))
    extra_outputs = [f"output.{name}" for name in sorted(current_outputs - declared_outputs)]
    added.extend(extra_outputs)
    removed.extend(f"output.{name}" for name in sorted(declared_outputs - current_outputs))
    return {
        "added": added,
        "removed": removed,
        "type_changed": type_changed,
    }


def _type_changes(recipe: Recipe, input_schema: Mapping[str, Any]) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    static = recipe.input if isinstance(recipe.input, Mapping) else {}
    for name, specification in input_schema.items():
        if not isinstance(specification, Mapping) or name not in static:
            continue
        expected = specification.get("type")
        if not isinstance(expected, str):
            continue
        actual = _json_type(static[name])
        if actual is not None and actual != expected:
            changes.append({
                "field": f"input.{name}",
                "from": actual,
                "to": expected,
            })
    return changes


def _json_type(value: Any) -> str | None:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, Mapping):
        return "object"
    return None


def _empty_diff() -> dict[str, Any]:
    return {"added": [], "removed": [], "type_changed": []}


def _classify(contract_diff: Mapping[str, Any]) -> str:
    if contract_diff.get("removed") or contract_diff.get("type_changed"):
        return "breaking"
    if contract_diff.get("added"):
        return "additive"
    return "fingerprint_only"


def _with_workspace(result: dict[str, Any], workspace: Workspace) -> dict[str, Any]:
    result["workspace"] = str(workspace.path) if workspace.path is not None else None
    return result


def _rewrite_fingerprint(path: Path, recipe_name: str, fingerprint: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated = _replace_recipe_fingerprint(text, recipe_name, fingerprint)
    if updated == text:
        raise InputValidationError(
            f"actual value: {recipe_name}; workspace file has no replaceable contract_fingerprint",
            field="contract_fingerprint",
            next_action="Edit the caller gravity.toml recipes.<name>.contract_fingerprint by hand.",
        )
    temporary = path.with_name(f".{path.name}.{path.stat().st_mtime_ns}.tmp")
    temporary.write_text(updated, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _replace_recipe_fingerprint(text: str, recipe_name: str, fingerprint: str) -> str:
    lines = text.splitlines(keepends=True)
    in_table = False
    replaced = False
    header = f"{_TABLE_PREFIX}{recipe_name}]"
    nested = f"{_TABLE_PREFIX}{recipe_name}."
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_table = stripped == header
            if stripped.startswith(nested):
                in_table = False
            continue
        if not in_table or replaced:
            continue
        if stripped.startswith(_FINGERPRINT_LINE) and "=" in stripped:
            prefix, _sep, suffix = line.partition("=")
            quote = "'" if "'" in suffix and '"' not in suffix else '"'
            lines[index] = f"{prefix}= {quote}{fingerprint}{quote}{_eol(line)}"
            replaced = True
    return "".join(lines) if replaced else text


def _eol(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    return "\n" if line.endswith("\n") else ""


__all__ = [
    "REPIN_SCHEMA",
    "apply_recipe_repin",
    "assess_recipe_repin",
]
