from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

try:
    from scripts.validate_agent_runtime_requirement_graph import (
        DEFAULT_INDEX,
        DEFAULT_MARKDOWN,
        RequirementGraphError,
        parse_markdown_milestone_table,
        parse_markdown_requirement_table,
        parse_spec_status,
        validate_requirement_graph,
    )
except ModuleNotFoundError:
    from validate_agent_runtime_requirement_graph import (
        DEFAULT_INDEX,
        DEFAULT_MARKDOWN,
        RequirementGraphError,
        parse_markdown_milestone_table,
        parse_markdown_requirement_table,
        parse_spec_status,
        validate_requirement_graph,
    )


def _dependencies(item: Mapping[str, Any]) -> list[str]:
    return [
        *[str(value) for value in item.get("dependencies", [])],
        *[str(value) for value in item.get("milestone_dependencies", [])],
    ]


def build_promotion_readiness(
    document: Mapping[str, Any],
    requirement_rows: Mapping[str, Mapping[str, Any]],
    milestone_rows: Mapping[str, Mapping[str, Any]],
    spec_statuses: Mapping[str, str],
    *,
    structural_errors: list[str] | None = None,
) -> dict[str, Any]:
    requirements = list(document.get("requirements", []))
    status_by_id = {
        str(requirement["id"]): str(requirement["status"])
        for requirement in requirements
    }
    for requirement in requirements:
        for milestone in requirement.get("milestones", []):
            status_by_id[str(milestone["id"])] = str(milestone["status"])

    requirement_results: list[dict[str, Any]] = []
    milestone_results: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []

    for requirement in requirements:
        requirement_id = str(requirement["id"])
        index_status = str(requirement["status"])
        markdown_status = requirement_rows.get(requirement_id, {}).get("status")
        spec_status = spec_statuses.get(requirement_id)
        reasons: list[str] = []
        if index_status != "fixed_dev":
            reasons.append("requirement_not_fixed_dev")
        if markdown_status != index_status:
            reasons.append("index_markdown_status_mismatch")
        if spec_status != index_status:
            reasons.append("spec_status_mismatch")
        dependencies = _dependencies(requirement)
        dependency_statuses = {
            dependency: status_by_id.get(dependency, "missing")
            for dependency in dependencies
        }
        if any(status != "fixed_dev" for status in dependency_statuses.values()):
            reasons.append("dependency_not_fixed_dev")
        result = {
            "id": requirement_id,
            "kind": "requirement",
            "statuses": {
                "index_json": index_status,
                "index_markdown": markdown_status,
                "spec": spec_status,
            },
            "dependencies": dependency_statuses,
            "ready": not reasons,
            "blockers": reasons,
        }
        requirement_results.append(result)
        blockers.extend(
            {"id": requirement_id, "kind": "requirement", "code": reason}
            for reason in reasons
        )

        for milestone in requirement.get("milestones", []):
            milestone_id = str(milestone["id"])
            index_milestone_status = str(milestone["status"])
            markdown_row = milestone_rows.get(milestone_id, {})
            markdown_milestone_status = markdown_row.get("status")
            milestone_reasons: list[str] = []
            if index_milestone_status != "fixed_dev":
                milestone_reasons.append("milestone_not_fixed_dev")
            if markdown_milestone_status != index_milestone_status:
                milestone_reasons.append("index_markdown_status_mismatch")
            if markdown_row.get("parent_id") != requirement_id:
                milestone_reasons.append("milestone_parent_mismatch")
            milestone_dependencies = _dependencies(milestone)
            if list(markdown_row.get("dependencies", [])) != milestone_dependencies:
                milestone_reasons.append("milestone_dependencies_mismatch")
            milestone_dependency_statuses = {
                dependency: status_by_id.get(dependency, "missing")
                for dependency in milestone_dependencies
            }
            if any(
                status != "fixed_dev"
                for status in milestone_dependency_statuses.values()
            ):
                milestone_reasons.append("dependency_not_fixed_dev")
            milestone_result = {
                "id": milestone_id,
                "kind": "milestone",
                "parent_id": requirement_id,
                "statuses": {
                    "index_json": index_milestone_status,
                    "index_markdown": markdown_milestone_status,
                    "parent_spec": spec_status,
                },
                "dependencies": milestone_dependency_statuses,
                "ready": not milestone_reasons,
                "blockers": milestone_reasons,
            }
            milestone_results.append(milestone_result)
            blockers.extend(
                {"id": milestone_id, "kind": "milestone", "code": reason}
                for reason in milestone_reasons
            )

    errors = list(structural_errors or [])
    all_fixed = all(status == "fixed_dev" for status in status_by_id.values())
    status_parity = not any(
        blocker["code"]
        in {
            "index_markdown_status_mismatch",
            "spec_status_mismatch",
            "milestone_parent_mismatch",
            "milestone_dependencies_mismatch",
        }
        for blocker in blockers
    )
    ready = all_fixed and status_parity and not blockers and not errors
    return {
        "schema_version": "gravity.agent-runtime-promotion-readiness.v1",
        "ready": ready,
        "all_index_requirements_fixed_dev": all_fixed,
        "status_parity": status_parity,
        "structural_errors": errors,
        "summary": {
            "requirement_count": len(requirement_results),
            "milestone_count": len(milestone_results),
            "ready_requirement_count": sum(
                1 for item in requirement_results if item["ready"]
            ),
            "ready_milestone_count": sum(
                1 for item in milestone_results if item["ready"]
            ),
            "blocker_count": len(blockers) + len(errors),
        },
        "blockers": blockers,
        "requirements": requirement_results,
        "milestones": milestone_results,
    }


def evaluate_promotion_readiness(
    index_path: Path = DEFAULT_INDEX,
    markdown_path: Path = DEFAULT_MARKDOWN,
) -> dict[str, Any]:
    document = json.loads(index_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    structural_errors: list[str] = []
    try:
        validate_requirement_graph(document, index_path=index_path)
    except RequirementGraphError as exc:
        structural_errors.append(str(exc))
    try:
        requirement_rows = parse_markdown_requirement_table(markdown)
    except RequirementGraphError as exc:
        structural_errors.append(str(exc))
        requirement_rows = {}
    try:
        milestone_rows = parse_markdown_milestone_table(markdown)
    except RequirementGraphError as exc:
        structural_errors.append(str(exc))
        milestone_rows = {}

    spec_statuses: dict[str, str] = {}
    index_root = index_path.resolve().parent
    for requirement in document.get("requirements", []):
        requirement_id = str(requirement["id"])
        try:
            spec_statuses[requirement_id] = parse_spec_status(
                (index_root / requirement["path"]).read_text(encoding="utf-8"),
                requirement_id,
            )
        except (OSError, RequirementGraphError) as exc:
            structural_errors.append(str(exc))
    return build_promotion_readiness(
        document,
        requirement_rows,
        milestone_rows,
        spec_statuses,
        structural_errors=structural_errors,
    )


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report Agent Runtime main-promotion readiness and blockers."
    )
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = evaluate_promotion_readiness(args.index, args.markdown)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        print(f"promotion readiness check failed: {exc}", file=sys.stderr)
        return 2
    if args.output is not None:
        _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
