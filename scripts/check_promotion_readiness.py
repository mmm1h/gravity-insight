"""Audit current Agent Runtime component ownership and maturity projection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

try:
    from scripts.validate_agent_runtime_requirement_graph import (
        DEFAULT_INDEX,
        DEFAULT_MARKDOWN,
        RequirementGraphError,
        parse_markdown_requirement_table,
        validate_markdown_projection,
        validate_requirement_graph,
    )
except ModuleNotFoundError:
    from validate_agent_runtime_requirement_graph import (  # type: ignore[no-redef]
        DEFAULT_INDEX,
        DEFAULT_MARKDOWN,
        RequirementGraphError,
        parse_markdown_requirement_table,
        validate_markdown_projection,
        validate_requirement_graph,
    )


REMEDIATION_BY_CODE = {
    "machine_owner_missing": "Assign at least one existing machine source and owner.",
    "bounded_limits_missing": "State the current bounded or experimental limits in index.json.",
    "index_markdown_maturity_mismatch": "Regenerate the Markdown maturity from index.json.",
    "experimental_not_declared": "Use experimental maturity and state graduation evidence; do not claim stable.",
}


def build_promotion_readiness(
    document: Mapping[str, Any],
    component_rows: Mapping[str, Mapping[str, Any]],
    *,
    structural_errors: list[str] | None = None,
) -> dict[str, Any]:
    blockers: list[dict[str, str]] = []
    results: list[dict[str, Any]] = []
    for component in document.get("components", []):
        component_id = str(component.get("id"))
        maturity = str(component.get("maturity"))
        reasons: list[str] = []
        if not component.get("owner") or not component.get("machine_sources"):
            reasons.append("machine_owner_missing")
        if maturity in {"bounded", "experimental"} and not component.get("limits"):
            reasons.append("bounded_limits_missing")
        row = component_rows.get(component_id, {})
        if row.get("maturity") != maturity:
            reasons.append("index_markdown_maturity_mismatch")
        if component_id == "mcp-stdio" and maturity != "experimental":
            reasons.append("experimental_not_declared")
        results.append(
            {
                "id": component_id,
                "maturity": maturity,
                "owned": not reasons,
                "blockers": reasons,
            }
        )
        blockers.extend(
            {
                "id": component_id,
                "code": reason,
                "remediation": REMEDIATION_BY_CODE[reason],
            }
            for reason in reasons
        )
    errors = list(structural_errors or [])
    experimental = sorted(
        item["id"] for item in results if item["maturity"] == "experimental"
    )
    projection_parity = not any(
        item["code"] == "index_markdown_maturity_mismatch" for item in blockers
    )
    complete = bool(results) and not blockers and not errors
    return {
        "schema_version": "gravity.agent-runtime-component-audit.v1",
        "promotion_complete": complete,
        "all_components_owned": all(item["owned"] for item in results),
        "projection_parity": projection_parity,
        "release_exceptions": experimental,
        "structural_errors": errors,
        "summary": {
            "component_count": len(results),
            "owned_component_count": sum(item["owned"] for item in results),
            "blocker_count": len(blockers) + len(errors),
        },
        "blockers": blockers,
        "components": results,
    }


def evaluate_promotion_readiness(
    index_path: Path = DEFAULT_INDEX,
    markdown_path: Path = DEFAULT_MARKDOWN,
) -> dict[str, Any]:
    document = json.loads(index_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    errors: list[str] = []
    try:
        validate_requirement_graph(document, index_path=index_path)
        rows = validate_markdown_projection(document, markdown)
    except RequirementGraphError as exc:
        errors.append(str(exc))
        try:
            rows = parse_markdown_requirement_table(markdown)
        except RequirementGraphError:
            rows = {}
    return build_promotion_readiness(document, rows, structural_errors=errors)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Audit current Agent Runtime component ownership and maturity."
    )
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = evaluate_promotion_readiness(args.index, args.markdown)
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        print(f"component readiness check failed: {exc}", file=sys.stderr)
        return 2
    if args.output is not None:
        _write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["promotion_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
