"""Local Built-in Skill package validation, readiness, and materialization."""

from __future__ import annotations

import copy
import os
import shutil
import stat
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from .agent_runtime_contracts import AgentRuntimeContractError
from .capability_trust import (
    CapabilityTrustService,
    assess_capability_requirement,
)
from .errors import InputValidationError
from .skill_contract import (
    normalize_skill_identity,
    skill_artifacts,
)
from .skill_render import (
    render_agent_export,
    render_package_files,
    skill_package_descriptor,
)


MAX_PACKAGE_FILES = 64
MAX_FILE_BYTES = 262_144
MAX_TOTAL_BYTES = 2_097_152
MAX_PATH_DEPTH = 6
_PACKAGE_BASE = Path(__file__).resolve().parent


class SkillPackageError(AgentRuntimeContractError):
    """A Built-in Skill package or export violates its static boundary."""


class LocalSkillResolver:
    """Read exact Built-in packages without remote lookup or code loading."""

    def __init__(
        self,
        *,
        capability_trust: CapabilityTrustService | None = None,
        artifacts: Sequence[Mapping[str, Any]] | None = None,
        package_roots: Mapping[str, str | Path] | None = None,
    ) -> None:
        selected = skill_artifacts() if artifacts is None else artifacts
        self._artifacts = {
            str(item["skill_uri"]): copy.deepcopy(dict(item)) for item in selected
        }
        self._capability_trust = capability_trust or CapabilityTrustService()
        self._package_roots = {
            normalize_skill_identity(identity): Path(path).expanduser().absolute()
            for identity, path in (package_roots or {}).items()
        }

    def list(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for identity, artifact in sorted(self._artifacts.items()):
            validate_skill_package(
                artifact, root=self._package_roots.get(identity)
            )
            contract = artifact["contract"]
            rows.append(
                {
                    "skill_uri": identity,
                    "namespace": contract["namespace"],
                    "skill_id": contract["skill_id"],
                    "version": contract["version"],
                    "specification": contract["specification"],
                    "lifecycle": contract["lifecycle"],
                    "readiness": contract["readiness"],
                    "validation": contract["validation"],
                    "summary": contract["summary"],
                    "manifest_digest": artifact["digest"],
                    "package_digest": skill_package_descriptor(artifact)[
                        "package_digest"
                    ],
                }
            )
        return {
            "schema_version": "gravity.skill-list.v1",
            "status": "success",
            "count": len(rows),
            "skills": rows,
            "network_called": False,
        }

    def describe(self, identifier: str) -> dict[str, Any]:
        artifact = self._artifact(identifier)
        package = validate_skill_package(
            artifact, root=self._package_roots.get(artifact["skill_uri"])
        )
        contract = artifact["contract"]
        return {
            "schema_version": "gravity.skill-description.v1",
            "skill": {
                "skill_uri": artifact["skill_uri"],
                "namespace": contract["namespace"],
                "skill_id": contract["skill_id"],
                "version": contract["version"],
                "specification": contract["specification"],
                "lifecycle": contract["lifecycle"],
                "readiness": contract["readiness"],
                "validation": contract["validation"],
                "summary": contract["summary"],
                "description": contract["description"],
                "runtime_requires": contract["runtime_requires"],
                "manifest_digest": artifact["digest"],
            },
            "dependencies": _dependencies(contract),
            "routing": copy.deepcopy(contract["routing"]),
            "requirements": copy.deepcopy(contract["requirements"]),
            "claim_policy": copy.deepcopy(contract["claim_policy"]),
            "effects": copy.deepcopy(contract["effects"]),
            "request_budget": copy.deepcopy(contract["request_budget"]),
            "output_schema": contract["output_schema"],
            "package": package,
            "network_called": False,
        }

    def get(self, identifier: str) -> dict[str, Any]:
        artifact = self._artifact(identifier)
        description = self.describe(identifier)
        readiness = self._readiness(artifact)
        return {
            "schema_version": "gravity.skill-result.v1",
            "status": readiness["status"],
            "skill": description["skill"],
            "package": description["package"],
            "dependencies": description["dependencies"],
            "readiness": readiness,
            "guide": render_package_files(artifact)["GUIDE.md"].decode("utf-8"),
            "network_called": False,
        }

    def export_agent(self, identifier: str) -> dict[str, Any]:
        artifact = self._artifact(identifier)
        validate_skill_package(
            artifact, root=self._package_roots.get(artifact["skill_uri"])
        )
        contracts = [item["contract"] for item in self._artifacts.values()]
        export = render_agent_export(artifact, contracts)
        validate_package_entries(
            {
                item["path"]: item["content"].encode("utf-8")
                for item in export["files"]
            },
            allow_skill_md=True,
        )
        return export

    def materialize_agent(
        self, identifier: str, destination: str | Path
    ) -> dict[str, Any]:
        export = self.export_agent(identifier)
        supplied_parent = Path(destination).expanduser()
        if supplied_parent.is_symlink():
            raise InputValidationError(
                "actual value: linked path; Agent Skill export destination must "
                "be a non-link directory",
                field="output",
                next_action="Choose a real parent directory and retry.",
            )
        parent = supplied_parent.resolve()
        if parent.exists() and not parent.is_dir():
            raise InputValidationError(
                "actual value: non-directory path; Agent Skill export destination "
                "must be a directory",
                field="output",
                next_action="Choose a parent directory and retry.",
            )
        parent.mkdir(parents=True, exist_ok=True)
        target = parent / export["directory"]
        if target.exists() or target.is_symlink():
            raise InputValidationError(
                "actual value: existing target; Agent Skill export refuses to overwrite",
                field="output",
                next_action="Choose an empty parent directory or remove the prior export explicitly.",
            )
        temporary = parent / f".{export['directory']}.tmp-{uuid.uuid4().hex}"
        try:
            temporary.mkdir()
            for item in export["files"]:
                path = temporary / Path(*PurePosixPath(item["path"]).parts)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(item["content"], encoding="utf-8", newline="\n")
                path.chmod(0o644)
            os.replace(temporary, target)
        except Exception:
            shutil.rmtree(temporary, ignore_errors=True)
            raise
        return {
            "schema_version": "gravity.agent-skill-materialization.v1",
            "status": "written",
            "skill_uri": export["skill_uri"],
            "name": export["name"],
            "output": str(target),
            "package_digest": export["package_digest"],
            "file_count": len(export["files"]),
            "network_called": False,
        }

    def _artifact(self, identifier: str) -> dict[str, Any]:
        identity = normalize_skill_identity(identifier)
        artifact = self._artifacts.get(identity)
        if artifact is None:
            raise InputValidationError(
                f"actual value: {identity}; Skill identity is not registered",
                field="skill",
                next_action="Run `gravity skills list` and use an exact skill_uri.",
            )
        return copy.deepcopy(artifact)

    def _readiness(self, artifact: Mapping[str, Any]) -> dict[str, Any]:
        contract = artifact["contract"]
        capability_results: list[dict[str, Any]] = []
        reasons: list[str] = []
        dependency_ready = True
        for requirement in contract["capability_dependencies"]:
            result = self._capability_trust.trust(
                str(requirement["identity_kind"]), str(requirement["selector"])
            )
            capability_results.append(result)
            status, selected = assess_capability_requirement(result, requirement)
            if status != "stable":
                dependency_ready = False
                reasons.extend(selected)
        if contract["lifecycle"] in {"deprecated", "revoked"}:
            dependency_ready = False
            reasons.append(
                "SKILL_REVOKED"
                if contract["lifecycle"] == "revoked"
                else "SKILL_DEPRECATED"
            )
        if contract["readiness"] != "executable":
            dependency_ready = False
            if not reasons:
                reasons.append("SKILL_DECLARED_BLOCKED")
        return {
            "status": "executable" if dependency_ready else "blocked",
            "declared": contract["readiness"],
            "validation": contract["validation"],
            "capabilities": capability_results,
            "reason_codes": list(dict.fromkeys(reasons)),
        }


def validate_skill_package(
    artifact: Mapping[str, Any], *, root: str | Path | None = None
) -> dict[str, Any]:
    expected = render_package_files(artifact)
    if root is not None and Path(root).is_symlink():
        raise SkillPackageError("Built-in Skill package root is missing or linked")
    selected = Path(root).resolve() if root is not None else (
        _PACKAGE_BASE / skill_package_descriptor(artifact)["resource_root"]
    )
    if not selected.is_dir() or selected.is_symlink():
        raise SkillPackageError("Built-in Skill package root is missing or linked")
    entries: dict[str, bytes] = {}
    for path in selected.rglob("*"):
        if path.is_symlink():
            raise SkillPackageError("Built-in Skill package contains a link")
        if path.is_dir():
            continue
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise SkillPackageError("Built-in Skill package contains a non-file")
        if metadata.st_nlink != 1:
            raise SkillPackageError("Built-in Skill package contains a hardlink")
        if stat.S_IMODE(metadata.st_mode) & 0o111:
            raise SkillPackageError("Built-in Skill package contains an executable file")
        relative = path.relative_to(selected).as_posix()
        entries[relative] = path.read_bytes()
    validate_package_entries(entries, expected=expected)
    return skill_package_descriptor(artifact)


def validate_package_entries(
    entries: Mapping[str, bytes],
    *,
    expected: Mapping[str, bytes] | None = None,
    allow_skill_md: bool = False,
) -> None:
    if not isinstance(entries, Mapping) or not 1 <= len(entries) <= MAX_PACKAGE_FILES:
        raise SkillPackageError("Skill package file count is outside the boundary")
    normalized: dict[str, bytes] = {}
    casefolded: set[str] = set()
    total = 0
    for raw_path, content in entries.items():
        path = _safe_package_path(raw_path, allow_skill_md=allow_skill_md)
        key = path.casefold()
        if key in casefolded:
            raise SkillPackageError("Skill package paths collide by case")
        casefolded.add(key)
        if not isinstance(content, bytes) or not 1 <= len(content) <= MAX_FILE_BYTES:
            raise SkillPackageError("Skill package file size is outside the boundary")
        total += len(content)
        normalized[path] = content
    if total > MAX_TOTAL_BYTES:
        raise SkillPackageError("Skill package total size is outside the boundary")
    if expected is not None and normalized != dict(expected):
        raise SkillPackageError("Built-in Skill package differs from its Render Model")


def _safe_package_path(value: Any, *, allow_skill_md: bool) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or ":" in value
    ):
        raise SkillPackageError("Skill package path is not normalized")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise SkillPackageError("Skill package path escapes its boundary")
    if len(path.parts) > MAX_PATH_DEPTH:
        raise SkillPackageError("Skill package path depth is outside the boundary")
    if any(part.casefold() == "scripts" for part in path.parts):
        raise SkillPackageError("ordinary Skill packages cannot contain scripts")
    if path.as_posix() != value:
        raise SkillPackageError("Skill package path is not canonical")
    if value == "SKILL.md" and not allow_skill_md:
        raise SkillPackageError("SKILL.md belongs only to Agent Skills export")
    return value


def _dependencies(contract: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "journeys": copy.deepcopy(contract["covers_journeys"]),
        "capabilities": copy.deepcopy(contract["capability_dependencies"]),
        "semantics": copy.deepcopy(contract["semantic_dependencies"]),
        "operators": copy.deepcopy(contract["operator_dependencies"]),
        "models": copy.deepcopy(contract["model_dependencies"]),
        "context": copy.deepcopy(contract["context_dependencies"]),
    }


__all__ = [
    "LocalSkillResolver",
    "MAX_FILE_BYTES",
    "MAX_PACKAGE_FILES",
    "MAX_PATH_DEPTH",
    "MAX_TOTAL_BYTES",
    "SkillPackageError",
    "validate_package_entries",
    "validate_skill_package",
]
