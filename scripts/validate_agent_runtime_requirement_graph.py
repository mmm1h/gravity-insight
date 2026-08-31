"""Validate the current Agent Runtime component index and Markdown projection."""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
import sys
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "specs/agent-runtime/index.json"
DEFAULT_MARKDOWN = ROOT / "specs/agent-runtime/index.md"
EXPECTED_SCHEMA = "gravity.agent-runtime-components.v1"
EXPECTED_MATURITY = {"stable", "bounded", "experimental"}
EXPECTED_KEYS = {
    "schema_version",
    "canonical_architecture",
    "maturity_model",
    "components",
}


class RequirementGraphError(ValueError):
    """Retained public error name for callers of the former graph validator."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RequirementGraphError(message)


def _path(value: Any, *, field: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{field} must be a path")
    path = PurePosixPath(value)
    _require(
        not path.is_absolute(),
        f"{field} must be relative to specs/agent-runtime",
    )
    return path.as_posix()


def _validate_target(index_path: Path, value: Any, *, field: str) -> str:
    relative = _path(value, field=field)
    target = (index_path.parent / relative).resolve()
    _require(
        target == ROOT or ROOT in target.parents,
        f"{field} escapes the repository: {relative}",
    )
    _require(target.exists(), f"{field} path does not exist: {relative}")
    return relative


def validate_requirement_graph(
    document: Mapping[str, Any], *, index_path: Path = DEFAULT_INDEX
) -> dict[str, Mapping[str, Any]]:
    """Validate the component index; the historical function name remains callable."""

    _require(set(document) == EXPECTED_KEYS, "component index keys are invalid")
    _require(document.get("schema_version") == EXPECTED_SCHEMA, "schema_version is invalid")
    _validate_target(
        index_path,
        document.get("canonical_architecture"),
        field="canonical_architecture",
    )
    model = document.get("maturity_model")
    _require(isinstance(model, Mapping), "maturity_model must be an object")
    _require(set(model) == EXPECTED_MATURITY, "maturity_model tokens are invalid")
    _require(
        all(isinstance(value, str) and value for value in model.values()),
        "maturity_model descriptions must be non-empty strings",
    )
    components = document.get("components")
    _require(isinstance(components, list) and components, "components must be non-empty")
    by_id: dict[str, Mapping[str, Any]] = {}
    for position, component in enumerate(components):
        _require(isinstance(component, Mapping), f"components[{position}] must be an object")
        component_id = component.get("id")
        _require(
            isinstance(component_id, str)
            and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", component_id) is not None,
            f"components[{position}].id is invalid",
        )
        _require(component_id not in by_id, f"duplicate component ID: {component_id}")
        _require(
            component.get("maturity") in EXPECTED_MATURITY,
            f"{component_id}.maturity is invalid",
        )
        _require(
            isinstance(component.get("owner"), str) and bool(component["owner"]),
            f"{component_id}.owner must be non-empty",
        )
        sources = component.get("machine_sources")
        _require(
            isinstance(sources, list)
            and bool(sources)
            and len(sources) == len(set(sources)),
            f"{component_id}.machine_sources must be non-empty and unique",
        )
        for source_position, source in enumerate(sources):
            _validate_target(
                index_path,
                source,
                field=f"{component_id}.machine_sources[{source_position}]",
            )
        _validate_target(
            index_path,
            component.get("reference"),
            field=f"{component_id}.reference",
        )
        if component["maturity"] != "stable":
            limits = component.get("limits")
            _require(
                isinstance(limits, list)
                and bool(limits)
                and all(isinstance(value, str) and value for value in limits),
                f"{component_id}.limits must state every bounded/experimental limit",
            )
        by_id[component_id] = component
    return by_id


def parse_markdown_requirement_table(markdown: str) -> dict[str, dict[str, str]]:
    """Parse the component table; retained name avoids a second projection API."""

    rows: dict[str, dict[str, str]] = {}
    for line in markdown.splitlines():
        match = re.match(r"^\| `([^`]+)` \| `([^`]+)` \| (.+) \| (.+) \|$", line)
        if match is None:
            continue
        component_id, maturity, owner, detail = match.groups()
        _require(component_id not in rows, f"duplicate Markdown component ID: {component_id}")
        rows[component_id] = {
            "maturity": maturity,
            "owner": owner.strip(),
            "detail": detail.strip(),
        }
    _require(rows, "index.md has no Component table")
    return rows


def parse_markdown_milestone_table(markdown: str) -> dict[str, dict[str, str]]:
    """The current component projection has no delivery milestones."""

    _require("## Milestones" not in markdown, "retired Milestones section is present")
    return {}


def validate_markdown_projection(
    document: Mapping[str, Any], markdown: str
) -> dict[str, dict[str, str]]:
    components = validate_requirement_graph(document)
    rows = parse_markdown_requirement_table(markdown)
    _require(
        set(rows) == set(components),
        "Markdown component IDs differ from index.json",
    )
    for component_id, component in components.items():
        _require(
            rows[component_id]["maturity"] == component["maturity"],
            f"{component_id} maturity differs between JSON and Markdown",
        )
    parse_markdown_milestone_table(markdown)
    return rows


def validate_spec_status_projection(
    document: Mapping[str, Any], *, index_path: Path = DEFAULT_INDEX
) -> dict[str, Mapping[str, Any]]:
    """Released Requirement prose no longer exists; validate machine owners instead."""

    return validate_requirement_graph(document, index_path=index_path)


def validate_repository(
    index_path: Path = DEFAULT_INDEX, markdown_path: Path = DEFAULT_MARKDOWN
) -> dict[str, Any]:
    document = json.loads(index_path.read_text(encoding="utf-8"))
    _require(isinstance(document, dict), "index.json must contain an object")
    components = validate_requirement_graph(document, index_path=index_path)
    rows = validate_markdown_projection(
        document, markdown_path.read_text(encoding="utf-8")
    )
    counts = {
        maturity: sum(
            component["maturity"] == maturity for component in components.values()
        )
        for maturity in sorted(EXPECTED_MATURITY)
    }
    return {
        "component_count": len(components),
        "markdown_component_count": len(rows),
        "maturity_counts": counts,
    }


def main() -> int:
    try:
        result = validate_repository()
    except (json.JSONDecodeError, OSError, RequirementGraphError) as exc:
        print(f"Agent Runtime component index validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
