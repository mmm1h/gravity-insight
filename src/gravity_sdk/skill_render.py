"""Deterministic Built-in package, docs, and Agent Skills Render Model."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .agent_runtime_contracts import canonical_digest, validate_schema
from .skill_contract import skill_uri


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
}


def render_guide(contract: Mapping[str, Any]) -> str:
    guide = contract["guide"]
    lines = [
        f"# {guide['title']}",
        "",
        str(guide["applicability"]),
        "",
    ]
    lines.extend(
        f"{index}. {step}" for index, step in enumerate(guide["steps"], 1)
    )
    lines.extend(("", str(guide["context_boundary"]), ""))
    return "\n".join(lines)


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
        f"compatibility: {_yaml_string('Requires gravity-sdk ' + contract['runtime_requires'])}",
        "metadata:",
        f"  gravity-namespace: {_yaml_string(contract['namespace'])}",
        f"  gravity-skill-id: {_yaml_string(contract['skill_id'])}",
        f"  gravity-version: {_yaml_string(contract['version'])}",
        f"  gravity-package-digest: {_yaml_string(package_digest)}",
        "---",
        "",
        f"# {contract['guide']['title']}",
        "",
        "Read `references/GUIDE.md` before using this Skill and consult the other references only when needed.",
        "",
        "This export is static workflow guidance. Gravity Journey readiness, host routing, effects, authorization, and execution contracts remain authoritative.",
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
    "render_guide",
    "render_package_files",
    "skill_package_descriptor",
]
