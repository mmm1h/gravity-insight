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


MAIN_INTEGRATED_STATUSES = frozenset({"merged_main", "released"})
HISTORICAL_DELIVERY_STATUS = "fixed_dev"


def build_promotion_readiness(
    document: Mapping[str, Any],
    requirement_rows: Mapping[str, Mapping[str, Any]],
    milestone_rows: Mapping[str, Mapping[str, Any]],
    spec_statuses: Mapping[str, str],
    *,
    structural_errors: list[str] | None = None,
) -> dict[str, Any]:
    requirements = list(document.get("requirements", []))
    main_integration = document.get("main_integration", {})
    release_exceptions = list(main_integration.get("release_exceptions", []))
    exception_by_id = {
        str(exception.get("id")): exception
        for exception in release_exceptions
        if isinstance(exception, Mapping)
    }
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
        if index_status not in MAIN_INTEGRATED_STATUSES:
            reasons.append("requirement_not_main_integrated")
        if markdown_status != index_status:
            reasons.append("index_markdown_status_mismatch")
        if spec_status != HISTORICAL_DELIVERY_STATUS:
            reasons.append("historical_spec_delivery_status_mismatch")
        exception = exception_by_id.get(requirement_id)
        if index_status == "merged_main" and exception is None:
            reasons.append("undeclared_release_exception")
        if exception is not None and exception.get("status") != index_status:
            reasons.append("release_exception_status_mismatch")
        dependencies = _dependencies(requirement)
        dependency_statuses = {
            dependency: status_by_id.get(dependency, "missing")
            for dependency in dependencies
        }
        if any(
            status not in MAIN_INTEGRATED_STATUSES
            for status in dependency_statuses.values()
        ):
            reasons.append("dependency_not_main_integrated")
        result = {
            "id": requirement_id,
            "kind": "requirement",
            "statuses": {
                "index_json": index_status,
                "index_markdown": markdown_status,
                "spec": spec_status,
            },
            "dependencies": dependency_statuses,
            "main_integrated": not reasons,
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
            if index_milestone_status not in MAIN_INTEGRATED_STATUSES:
                milestone_reasons.append("milestone_not_main_integrated")
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
                status not in MAIN_INTEGRATED_STATUSES
                for status in milestone_dependency_statuses.values()
            ):
                milestone_reasons.append("dependency_not_main_integrated")
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
                "main_integrated": not milestone_reasons,
                "blockers": milestone_reasons,
            }
            milestone_results.append(milestone_result)
            blockers.extend(
                {"id": milestone_id, "kind": "milestone", "code": reason}
                for reason in milestone_reasons
            )

    errors = list(structural_errors or [])
    declared_exception_ids = set(exception_by_id)
    if len(exception_by_id) != len(release_exceptions):
        errors.append("release exceptions must have unique non-empty IDs")
    unknown_exceptions = sorted(declared_exception_ids - set(status_by_id))
    if unknown_exceptions:
        errors.append(f"unknown release exceptions: {unknown_exceptions}")
    all_main_integrated = all(
        status in MAIN_INTEGRATED_STATUSES for status in status_by_id.values()
    )
    projection_parity = not any(
        blocker["code"]
        in {
            "index_markdown_status_mismatch",
            "historical_spec_delivery_status_mismatch",
            "milestone_parent_mismatch",
            "milestone_dependencies_mismatch",
            "undeclared_release_exception",
            "release_exception_status_mismatch",
        }
        for blocker in blockers
    )
    promotion_complete = (
        all_main_integrated and projection_parity and not blockers and not errors
    )
    return {
        "schema_version": "gravity.agent-runtime-promotion-audit.v2",
        "promotion_complete": promotion_complete,
        "all_index_requirements_main_integrated": all_main_integrated,
        "projection_parity": projection_parity,
        "release_exceptions": sorted(declared_exception_ids),
        "structural_errors": errors,
        "summary": {
            "requirement_count": len(requirement_results),
            "milestone_count": len(milestone_results),
            "main_integrated_requirement_count": sum(
                1 for item in requirement_results if item["main_integrated"]
            ),
            "main_integrated_milestone_count": sum(
                1 for item in milestone_results if item["main_integrated"]
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
        description="Audit the completed Agent Runtime main promotion and blockers."
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
    return 0 if result["promotion_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
