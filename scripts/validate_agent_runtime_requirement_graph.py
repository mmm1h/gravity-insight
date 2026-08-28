from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INDEX = ROOT / "specs/agent-runtime/index.json"
DEFAULT_MARKDOWN = ROOT / "specs/agent-runtime/index.md"
_TABLE_LINK = re.compile(r"^\[(?P<id>[A-Z0-9-]+)\]\((?P<path>[^)]+)\)$")
_CODE_VALUE = re.compile(r"`([^`]+)`")
_STATUS_ROW = re.compile(r"^\|\s*Status\s*\|(?P<value>.*)\|\s*$")


class RequirementGraphError(ValueError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RequirementGraphError(message)


def _references(item: dict[str, Any], field: str, owner: str) -> list[str]:
    values = item.get(field, [])
    _require(isinstance(values, list), f"{owner}.{field} must be an array")
    _require(
        all(isinstance(value, str) and value for value in values),
        f"{owner}.{field} must contain non-empty IDs",
    )
    return values


def validate_requirement_graph(
    document: dict[str, Any], *, index_path: Path = DEFAULT_INDEX
) -> dict[str, int]:
    requirements = document.get("requirements")
    _require(isinstance(requirements, list), "requirements must be an array")

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[str, list[str]] = {}
    requirement_ids: list[str] = []
    index_root = index_path.resolve().parent

    for position, requirement in enumerate(requirements):
        _require(isinstance(requirement, dict), f"requirements[{position}] must be an object")
        requirement_id = requirement.get("id")
        _require(
            isinstance(requirement_id, str) and requirement_id,
            f"requirements[{position}].id must be a non-empty string",
        )
        _require(requirement_id not in nodes, f"duplicate requirement ID: {requirement_id}")
        nodes[requirement_id] = requirement
        requirement_ids.append(requirement_id)

        path_value = requirement.get("path")
        _require(
            isinstance(path_value, str) and path_value,
            f"{requirement_id}.path must be a non-empty string",
        )
        path = (index_root / path_value).resolve()
        _require(
            path == index_root or index_root in path.parents,
            f"{requirement_id}.path escapes the requirement directory: {path_value}",
        )
        _require(path.is_file(), f"{requirement_id}.path does not exist: {path_value}")

        milestones = requirement.get("milestones", [])
        _require(isinstance(milestones, list), f"{requirement_id}.milestones must be an array")
        for milestone_position, milestone in enumerate(milestones):
            _require(
                isinstance(milestone, dict),
                f"{requirement_id}.milestones[{milestone_position}] must be an object",
            )
            milestone_id = milestone.get("id")
            _require(
                isinstance(milestone_id, str) and milestone_id,
                f"{requirement_id}.milestones[{milestone_position}].id must be non-empty",
            )
            _require(milestone_id not in nodes, f"duplicate requirement ID: {milestone_id}")
            nodes[milestone_id] = milestone

    for requirement in requirements:
        requirement_id = requirement["id"]
        edges[requirement_id] = [
            *_references(requirement, "dependencies", requirement_id),
            *_references(requirement, "milestone_dependencies", requirement_id),
        ]
        for milestone in requirement.get("milestones", []):
            milestone_id = milestone["id"]
            edges[milestone_id] = [
                *_references(milestone, "dependencies", milestone_id),
                *_references(milestone, "milestone_dependencies", milestone_id),
            ]

    for owner, dependencies in edges.items():
        for dependency in dependencies:
            _require(
                dependency in nodes,
                f"{owner} references unknown dependency: {dependency}",
            )

    state: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> None:
        if state.get(node) == 2:
            return
        if state.get(node) == 1:
            start = stack.index(node)
            cycle = [*stack[start:], node]
            raise RequirementGraphError(
                "requirement graph contains a cycle: " + " -> ".join(cycle)
            )
        state[node] = 1
        stack.append(node)
        for dependency in edges[node]:
            visit(dependency)
        stack.pop()
        state[node] = 2

    for node in nodes:
        visit(node)

    return {
        "requirement_count": len(requirement_ids),
        "graph_node_count": len(nodes),
        "dependency_edge_count": sum(len(values) for values in edges.values()),
    }


def parse_markdown_requirement_table(markdown: str) -> dict[str, dict[str, str]]:
    lines = markdown.splitlines()
    try:
        start = lines.index("## Requirements") + 1
    except ValueError as exc:
        raise RequirementGraphError("index.md has no Requirements section") from exc

    rows: dict[str, dict[str, str]] = {}
    for line in lines[start:]:
        if line.startswith("## "):
            break
        if not line.startswith("| ["):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        _require(len(cells) == 5, f"malformed requirement table row: {line}")
        link = _TABLE_LINK.fullmatch(cells[0])
        _require(link is not None, f"malformed requirement table link: {cells[0]}")
        state_match = _CODE_VALUE.search(cells[3])
        _require(state_match is not None, f"missing requirement state: {line}")
        requirement_id = link.group("id")
        _require(
            requirement_id not in rows,
            f"duplicate index.md requirement ID: {requirement_id}",
        )
        rows[requirement_id] = {
            "path": link.group("path"),
            "status": state_match.group(1),
        }
    _require(rows, "index.md Requirements table has no requirement rows")
    return rows


def parse_markdown_milestone_table(markdown: str) -> dict[str, dict[str, Any]]:
    lines = markdown.splitlines()
    try:
        start = lines.index("## Milestones") + 1
    except ValueError as exc:
        raise RequirementGraphError("index.md has no Milestones section") from exc

    rows: dict[str, dict[str, Any]] = {}
    for line in lines[start:]:
        if line.startswith("## "):
            break
        if not line.startswith("| R"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        _require(len(cells) == 4, f"malformed milestone table row: {line}")
        milestone_id, parent_id, dependencies_cell, status_cell = cells
        status_match = _CODE_VALUE.search(status_cell)
        _require(status_match is not None, f"missing milestone state: {line}")
        _require(
            milestone_id not in rows,
            f"duplicate index.md milestone ID: {milestone_id}",
        )
        dependencies = (
            []
            if dependencies_cell == "-"
            else [value.strip() for value in dependencies_cell.split(",")]
        )
        _require(
            all(dependencies),
            f"malformed milestone dependencies: {line}",
        )
        rows[milestone_id] = {
            "parent_id": parent_id,
            "dependencies": dependencies,
            "status": status_match.group(1),
        }
    return rows


def parse_spec_status(markdown: str, requirement_id: str) -> str:
    rows = [match for line in markdown.splitlines() if (match := _STATUS_ROW.match(line))]
    _require(
        len(rows) == 1,
        f"{requirement_id} spec must contain exactly one Status row; found={len(rows)}",
    )
    status_match = _CODE_VALUE.search(rows[0].group("value"))
    _require(status_match is not None, f"{requirement_id} spec Status row has no code value")
    return status_match.group(1)


def validate_markdown_projection(
    document: dict[str, Any], markdown: str
) -> dict[str, int]:
    requirements = document.get("requirements")
    _require(isinstance(requirements, list), "requirements must be an array")
    expected = {item["id"]: item for item in requirements}
    actual = parse_markdown_requirement_table(markdown)
    _require(
        set(actual) == set(expected),
        "index.md requirement IDs differ from index.json: "
        f"missing={sorted(set(expected) - set(actual))}, "
        f"extra={sorted(set(actual) - set(expected))}",
    )
    for requirement_id, requirement in expected.items():
        row = actual[requirement_id]
        _require(
            row["path"] == requirement["path"],
            f"{requirement_id} path differs: json={requirement['path']} markdown={row['path']}",
        )
        _require(
            row["status"] == requirement["status"],
            f"{requirement_id} status differs: "
            f"json={requirement['status']} markdown={row['status']}",
        )

    expected_milestones = {
        milestone["id"]: {
            "parent_id": requirement["id"],
            "dependencies": [
                *_references(milestone, "dependencies", milestone["id"]),
                *_references(
                    milestone,
                    "milestone_dependencies",
                    milestone["id"],
                ),
            ],
            "status": milestone["status"],
        }
        for requirement in requirements
        for milestone in requirement.get("milestones", [])
    }
    actual_milestones = parse_markdown_milestone_table(markdown)
    _require(
        set(actual_milestones) == set(expected_milestones),
        "index.md milestone IDs differ from index.json: "
        f"missing={sorted(set(expected_milestones) - set(actual_milestones))}, "
        f"extra={sorted(set(actual_milestones) - set(expected_milestones))}",
    )
    for milestone_id, expected_row in expected_milestones.items():
        _require(
            actual_milestones[milestone_id] == expected_row,
            f"{milestone_id} milestone projection differs: "
            f"json={expected_row} markdown={actual_milestones[milestone_id]}",
        )
    return {
        "markdown_requirement_count": len(actual),
        "markdown_milestone_count": len(actual_milestones),
    }


def validate_spec_status_projection(
    document: dict[str, Any], *, index_path: Path = DEFAULT_INDEX
) -> dict[str, int]:
    requirements = document.get("requirements")
    _require(isinstance(requirements, list), "requirements must be an array")
    index_root = index_path.resolve().parent
    for requirement in requirements:
        requirement_id = requirement["id"]
        spec_path = (index_root / requirement["path"]).resolve()
        spec_status = parse_spec_status(
            spec_path.read_text(encoding="utf-8"), requirement_id
        )
        _require(
            spec_status == requirement["status"],
            f"{requirement_id} spec status differs: "
            f"json={requirement['status']} spec={spec_status}",
        )
    return {"spec_status_count": len(requirements)}


def validate_repository(
    index_path: Path = DEFAULT_INDEX, markdown_path: Path = DEFAULT_MARKDOWN
) -> dict[str, int]:
    document = json.loads(index_path.read_text(encoding="utf-8"))
    graph = validate_requirement_graph(document, index_path=index_path)
    projection = validate_markdown_projection(
        document, markdown_path.read_text(encoding="utf-8")
    )
    spec_projection = validate_spec_status_projection(document, index_path=index_path)
    return {**graph, **projection, **spec_projection}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args(argv)
    try:
        summary = validate_repository(args.index, args.markdown)
    except (json.JSONDecodeError, OSError, RequirementGraphError) as exc:
        print(f"requirement graph validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
