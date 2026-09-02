"""Deterministic Runtime Hub and Agent Skill Render Model."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .agent_runtime_contracts import canonical_digest, validate_schema
from .skill_contract import skill_uri
from .skill_support.project_bindings import (
    _context_binding_template,
    _semantic_binding_template,
    render_project_bindings_template,
)


PACKAGE_SCHEMA_VERSION = "gravity.skill-package.v1"
AGENT_EXPORT_SCHEMA_VERSION = "gravity.agent-skill-export.v1"
_PACKAGE_SCHEMA = "skill-package-v1.schema.json"
_AGENT_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_ROLES = {
    "manifest.json": ("manifest", "application/json"),
    "GUIDE.md": ("guide", "text/markdown"),
    "provenance.json": ("provenance", "application/json"),
    "references/SCHEMA.json": ("schema", "application/json"),
    "references/CLAIMS.md": ("claims", "text/markdown"),
    "references/EXAMPLES.md": ("examples", "text/markdown"),
    "references/PROJECT_BINDINGS.json": ("asset", "application/json"),
}


def render_guide(contract: Mapping[str, Any]) -> str:
    guide = contract["guide"]
    lines = [
        f"# {guide['title']}",
        "",
        "## Applicability",
        "",
        str(guide["applicability"]),
        "",
        "## Quick Workflow",
        "",
    ]
    lines.extend(
        f"{index}. {step}" for index, step in enumerate(guide["steps"], 1)
    )
    lines.extend(
        (
            "",
            "## Context Boundary",
            "",
            str(guide["context_boundary"]),
            "",
        )
    )
    method = contract.get("method")
    if method is None:
        lines.extend(
            (
                "## Method Status",
                "",
                "This Skill has no completed Method contract. Use its declared "
                "readiness and dependency gaps; do not infer missing methodology.",
                "",
            )
        )
    else:
        lines.extend(_render_method(contract, method))
    return "\n".join(lines)


def _render_method(contract: Mapping[str, Any], method: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for renderer in (_method_intro, _method_assumptions, _method_procedure,
                     _method_formulas, _method_dimension_scan,
                     _method_diagnostic_tree, _method_checks_and_states,
                     _method_dependencies):
        lines.extend(renderer(method))
    lines.extend(_method_handoff(contract, method))
    return lines


def _method_intro(method: Mapping[str, Any]) -> list[str]:
    return [
        "## Business Question", "", str(method["business_question"]), "",
        "## Scope", "", "### Applicable", "",
        *[f"- {value}" for value in method["scope"]["applicable"]], "",
        "### Not Applicable", "",
        *[f"- {value}" for value in method["scope"]["not_applicable"]], "",
        "## Assumptions and Project Calibration", "",
    ]


def _method_assumptions(method: Mapping[str, Any]) -> list[str]:
    lines: list[str] = []
    for key, title in (("inputs", "Inputs"), ("time", "Time"),
                       ("cohort", "Cohort"), ("unit", "Unit"),
                       ("attribution", "Attribution")):
        lines.extend((f"### {title}", ""))
        lines.extend(f"- {value}" for value in method["assumptions"][key])
        lines.append("")
    lines.extend(("### Required Project Calibration", ""))
    calibrations = method["assumptions"]["requires_project_calibration"]
    lines.extend([f"- `{item['calibration_id']}`: {item['subject']}"
                  for item in calibrations] or ["- None."])
    return [*lines, ""]


def _method_procedure(method: Mapping[str, Any]) -> list[str]:
    lines = ["## Deterministic Procedure", ""]
    for step in method["procedure"]:
        dependencies = ", ".join(step["depends_on"]) or "none"
        lines.extend((f"### `{step['step_id']}`", "", str(step["instruction"]), "",
                      f"- Depends on: `{dependencies}`",
                      f"- On failure: `{step['on_failure']}`", ""))
    return lines


def _method_formulas(method: Mapping[str, Any]) -> list[str]:
    lines = ["## Formulas", ""]
    for formula in method["formulas"]:
        lines.extend((f"### `{formula['formula_id']}`", "",
                      f"- Expression: `{formula['expression']}`",
                      f"- Numerator: {formula['numerator']}",
                      f"- Denominator: {formula['denominator']}",
                      f"- Window: {formula['window']}", f"- Unit: {formula['unit']}",
                      f"- Interpretation: {formula['interpretation']}", "- Variables:"))
        lines.extend(f"  - `{item['symbol']}`: {item['definition']} "
                     f"(aggregation: {item['aggregation']}; distinct by: "
                     f"{item['distinct_by'] or 'not applicable'})"
                     for item in formula["variables"])
        lines.append("")
    return lines


def _method_dimension_scan(method: Mapping[str, Any]) -> list[str]:
    scan = method["dimension_scan"]
    dimensions = ", ".join(f"`{item['dimension_id']}` ({item['label']})"
                           for item in scan["dimensions"])
    return ["## Dimension Scan and Contribution", "", f"- Dimensions: {dimensions}",
            f"- Baseline: {scan['baseline']}",
            f"- Contribution formula: `{scan['contribution_formula']}`",
            f"- Ranking rule: {scan['ranking_rule']}",
            f"- Minimum volume: {scan['minimum_volume_rule']}",
            f"- Residual policy: {scan['residual_policy']}", ""]


def _method_diagnostic_tree(method: Mapping[str, Any]) -> list[str]:
    tree = method["diagnostic_tree"]
    lines = ["## Diagnostic Tree", "", str(tree["root_question"]), ""]
    for branch in tree["branches"]:
        lines.extend((f"### `{branch['branch_id']}`", "",
                      f"- Condition: {branch['condition']}", "- Checks:",
                      *[f"  - {value}" for value in branch["checks"]], "- Leaves:"))
        for leaf in branch["leaves"]:
            lines.extend((f"  - `{leaf['leaf_id']}`: {leaf['condition']}",
                          f"    - Conclusion: {leaf['conclusion']}", "    - Exclusions:",
                          *[f"      - {value}" for value in leaf["exclusions"]]))
        lines.append("")
    return lines


def _method_checks_and_states(method: Mapping[str, Any]) -> list[str]:
    checks = method["data_checks"]
    lines = ["## Exclusions and Data Checks", "", "### Exclusions", ""]
    lines.extend(f"- {value}" for value in method["exclusions"])
    lines.extend(("", "### Completeness", ""))
    lines.extend(f"- {value}" for value in checks["completeness"])
    lines.extend(("", "### Data Quality", ""))
    lines.extend(f"- {value}" for value in checks["data_quality"])
    lines.extend(("", f"Failure behavior: {checks['failure_behavior']}", "",
                  "## Result States and Sections", ""))
    lines.extend(f"- `{state}` / `{value['reason_code']}`: {value['behavior']}"
                 for state, value in method["states"].items())
    lines.extend(("", "Result sections:", ""))
    lines.extend(f"- `{item['section_id']}`: {item['title']}"
                 for item in method["result"]["sections"])
    return [*lines, ""]


def _method_dependencies(method: Mapping[str, Any]) -> list[str]:
    return ["## Dependency Status", "",
            *(f"- `{item['kind']}` `{item['identity']}`: `{item['status']}` / "
              f"`{item['reason_code']}`. {item['evidence']}"
              for item in method["dependency_status"])]


def _method_handoff(contract: Mapping[str, Any], method: Mapping[str, Any]) -> list[str]:
    handoff = method["handoff"]
    return ["", "## Handoff", "", f"- Kind: `{handoff['kind']}`",
            f"- Target: `{handoff['target'] or 'none'}`",
            f"- Authorization boundary: {handoff['authorization_boundary']}",
            "- Conditions:", *[f"  - {value}" for value in handoff["conditions"]], "",
            "## Run Examples", "",
            "Read `references/EXAMPLES.md` for structured success, "
            "empty/partial, and blocked/gap examples.", "",
            f"Method revision: `{method['method_revision']}`. Skill version: "
            f"`{contract['version']}`.", ""]


def render_package_files(artifact: Mapping[str, Any]) -> dict[str, bytes]:
    contract = artifact["contract"]
    identity = artifact["skill_uri"]
    provenance = {
        "artifact_kind": "skill_provenance",
        "schema_version": "gravity.skill-provenance.v1",
        "skill_uri": identity,
        "manifest_digest": artifact["digest"],
        "source": contract["provenance"],
    }
    schema_reference = {
        "schema_version": "gravity.skill-reference.v1",
        "skill_uri": identity,
        "manifest_digest": artifact["digest"],
        "manifest": contract,
    }
    return {
        "manifest.json": _json_bytes(contract),
        "GUIDE.md": render_guide(contract).encode("utf-8"),
        "provenance.json": _json_bytes(provenance),
        "references/SCHEMA.json": _json_bytes(schema_reference),
        "references/CLAIMS.md": render_claims(contract).encode("utf-8"),
        "references/EXAMPLES.md": render_examples(contract).encode("utf-8"),
        "references/PROJECT_BINDINGS.json": _json_bytes(
            render_project_bindings_template(contract)
        ),
    }


def render_claims(contract: Mapping[str, Any]) -> str:
    policy = contract["claim_policy"]
    lines = [
        "# Claim Policy",
        "",
        "## Allowed",
        "",
        *[f"- `{value}`" for value in policy["allowed"]],
        "",
        "## Forbidden",
        "",
        *[f"- `{value}`" for value in policy["forbidden"]],
        "",
        "## Forbidden Without Context",
        "",
    ]
    conditional = policy["forbidden_without_context"]
    lines.extend(
        [f"- `{value}`" for value in conditional]
        if conditional
        else ["- None beyond the always-forbidden claims above."]
    )
    lines.append("")
    return "\n".join(lines)


def render_examples(contract: Mapping[str, Any]) -> str:
    lines = ["# Run Examples", ""]
    method = contract.get("method")
    if method is None:
        lines.extend(
            (
                "No structured run examples are available because this Skill has "
                "no completed Method contract.",
                "",
                "Treat the missing method as a content gap and do not invent inputs "
                "or expected claims.",
                "",
            )
        )
        return "\n".join(lines)
    for example in method["examples"]["run_examples"]:
        expected = example["expected"]
        lines.extend(
            (
                f"## `{example['example_id']}`",
                "",
                f"- Scenario: `{example['scenario']}`",
                f"- Question: {example['question']}",
                f"- Selector: `{example['selector']}`",
                "- Input template:",
                "",
                "```json",
                json.dumps(
                    example["input_template"],
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                ),
                "```",
                "",
                f"- Expected status: `{expected['status']}`",
                f"- Expected completeness: `{expected['completeness']}`",
                f"- Expected sections: `{', '.join(expected['sections'])}`",
                f"- Allowed claims: `{', '.join(expected['allowed_claims']) or 'none'}`",
                f"- Forbidden claims: `{', '.join(expected['forbidden_claims'])}`",
                f"- Reason codes: `{', '.join(expected['reason_codes']) or 'none'}`",
                f"- Network called: `{str(expected['network_called']).lower()}`",
                "",
            )
        )
    return "\n".join(lines)


def skill_package_descriptor(artifact: Mapping[str, Any]) -> dict[str, Any]:
    contract = artifact["contract"]
    files = render_package_files(artifact)
    file_rows = [
        {
            "path": path,
            "role": _ROLES[path][0],
            "media_type": _ROLES[path][1],
            "size_bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        for path, content in sorted(files.items())
    ]
    digest_body = {
        "skill_uri": artifact["skill_uri"],
        "manifest_digest": artifact["digest"],
        "files": file_rows,
    }
    result = {
        "artifact_kind": "skill_package",
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "skill_uri": artifact["skill_uri"],
        "namespace": contract["namespace"],
        "skill_id": contract["skill_id"],
        "version": contract["version"],
        "manifest_digest": artifact["digest"],
        "package_digest": canonical_digest(digest_body),
        "resource_root": (
            f"skills/{contract['namespace']}.{contract['skill_id']}"
        ),
        "files": file_rows,
        "provenance": copy.deepcopy(contract["provenance"]),
    }
    validate_schema(result, _PACKAGE_SCHEMA, "Skill Package")
    return result


def agent_skill_name(
    contract: Mapping[str, Any],
    registry: Sequence[Mapping[str, Any]],
) -> str:
    identity = skill_uri(contract)
    base = _agent_base(contract)
    collisions = sum(_agent_base(item) == base for item in registry) > 1
    result = _bounded_name(base, identity, force_suffix=collisions)
    if not 1 <= len(result) <= 64 or _AGENT_NAME.fullmatch(result) is None:
        raise ValueError("Agent Skill name generation violated the open specification")
    return result


def render_agent_export(
    artifact: Mapping[str, Any],
    registry: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    contract = artifact["contract"]
    package = skill_package_descriptor(artifact)
    name = agent_skill_name(contract, registry)
    files = {
        "SKILL.md": _agent_skill_markdown(contract, name, package["package_digest"]),
        "references/GUIDE.md": render_guide(contract),
        "references/SCHEMA.json": render_package_files(artifact)[
            "references/SCHEMA.json"
        ].decode("utf-8"),
        "references/CLAIMS.md": render_claims(contract),
        "references/EXAMPLES.md": render_examples(contract),
        "references/PROJECT_BINDINGS.json": render_package_files(artifact)[
            "references/PROJECT_BINDINGS.json"
        ].decode("utf-8"),
    }
    rows = [
        {
            "path": path,
            "size_bytes": len(content.encode("utf-8")),
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "content": content,
        }
        for path, content in sorted(files.items())
    ]
    return {
        "schema_version": AGENT_EXPORT_SCHEMA_VERSION,
        "skill_uri": artifact["skill_uri"],
        "name": name,
        "directory": name,
        "package_digest": package["package_digest"],
        "files": rows,
        "network_called": False,
    }


def render_docs_mirror(artifact: Mapping[str, Any]) -> str:
    contract = artifact["contract"]
    package = skill_package_descriptor(artifact)
    journey = contract["covers_journeys"][0]
    return "\n".join(
        (
            "<!-- generated by scripts/generate_agent_skills.py; do not edit -->",
            render_guide(contract).rstrip(),
            "",
            "## Machine Identity",
            "",
            f"- Skill: `{contract['namespace']}/{contract['skill_id']}@{contract['version']}`",
            f"- Package digest: `{package['package_digest']}`",
            f"- Journey: `{journey}`",
            f"- Readiness: run `gravity journey can-run {journey} --input <request.json>`.",
            "- Current static blocker: required completeness is `complete`; the underlying operation remains `unknown` until authoritative evidence changes it.",
            "",
        )
    )


def _agent_skill_markdown(
    contract: Mapping[str, Any], name: str, package_digest: str
) -> str:
    frontmatter = [
        "---",
        f"name: {name}",
        f"description: {_yaml_string(contract['description'])}",
        "metadata:",
        f"  gravity-namespace: {_yaml_string(contract['namespace'])}",
        f"  gravity-skill-id: {_yaml_string(contract['skill_id'])}",
        f"  gravity-version: {_yaml_string(contract['version'])}",
        f"  gravity-runtime-requires: {_yaml_string(contract['runtime_requires'])}",
        f"  gravity-package-digest: {_yaml_string(package_digest)}",
        "---",
        "",
        f"# {contract['guide']['title']}",
        "",
        "Read `references/GUIDE.md` before using this Skill.",
        "",
        "Before selecting or executing a Gravity product, read `references/SCHEMA.json` for the exact identity, routing hints, effects, dependencies, request budget, and declared readiness and validation.",
        "",
        "Before reporting findings, read `references/CLAIMS.md` and keep every conclusion within its allowed claim policy.",
        "",
        "Read `references/EXAMPLES.md` before the first run. Use its input templates and expected status/claim boundaries; never substitute missing project bindings with guessed values.",
        "",
        "When project dependencies are unresolved, read `references/PROJECT_BINDINGS.json`, fill the project-owned Semantic and Context fields in tracked artifacts, and retry the same exact Skill version.",
        "",
        "This export is static workflow guidance. Gravity Journey readiness, host routing, effects, authorization, and execution contracts remain authoritative. Treat `blocked`, `unvalidated`, or unresolved dependencies as a stop for execution and business claims; report the exact gap instead.",
        "",
    ]
    return "\n".join(frontmatter)


def _agent_base(contract: Mapping[str, Any]) -> str:
    raw = f"{contract['namespace']}-{contract['skill_id']}".casefold()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", raw)).strip("-")


def _bounded_name(base: str, identity: str, *, force_suffix: bool) -> str:
    needs_suffix = force_suffix or len(base) > 64
    if not needs_suffix:
        return base
    suffix = "-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:8]
    prefix = base[: 64 - len(suffix)].rstrip("-")
    return prefix + suffix


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _yaml_string(value: Any) -> str:
    return json.dumps(str(value), ensure_ascii=False)


__all__ = [
    "AGENT_EXPORT_SCHEMA_VERSION",
    "PACKAGE_SCHEMA_VERSION",
    "agent_skill_name",
    "render_agent_export",
    "render_claims",
    "render_docs_mirror",
    "render_examples",
    "render_guide",
    "render_package_files",
    "render_project_bindings_template",
    "skill_package_descriptor",
]
