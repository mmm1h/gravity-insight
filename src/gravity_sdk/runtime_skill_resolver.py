"""Offline Built-in or exact Team Skill resolution for Core Runtime."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any

from . import __version__
from .agent_runtime_contracts import canonical_digest
from .context_contract import ContextContractError
from .errors import InputValidationError
from .operator_contract import builtin_operator_artifacts
from .repo_context_git import assert_clean_paths, git_snapshot
from .repo_context_index import read_context_file
from .runtime_compatibility import normalized_version, runtime_satisfies
from .skill_contract import (
    SkillContractError,
    normalize_skill_identity,
    skill_artifact,
    validate_skill_journey_parity,
)
from .skill_hub_archive import validate_skill_directory
from .skill_hub_contract import SkillHubContractError
from .skill_hub_locks import compile_skills_lock, compile_trusted_packs_lock
from .skill_hub_paths import assert_unlinked_path
from .skill_hub_state import (
    compile_trusted_installation_state,
    read_json,
)
from .skill_package import SkillPackageError, validate_skill_package
from .trusted_pack_hub import verify_trusted_pack_startup


SCHEMA_VERSION = "gravity.runtime-skill-resolution.v1"
SKILLS_LOCK_NAME = "gravity.skills.lock.json"
TRUSTED_PACKS_LOCK_NAME = "gravity.trusted-packs.lock.json"
TRUSTED_PACK_STATE_NAME = "trusted-packs-installation.json"
_MAX_LOCK_BYTES = 1_048_576
_DistributionLookup = Callable[[str], Any]


class RuntimeSkillResolver:
    """Resolve code-owned Built-ins or one exact project-locked Team package."""

    def __init__(
        self,
        *,
        workspace: Any,
        cas_root: str | Path | None = None,
        runtime_version: str = __version__,
        distribution_lookup: _DistributionLookup = importlib_metadata.distribution,
    ) -> None:
        self._workspace = workspace
        self._runtime_version = normalized_version(runtime_version)
        state_root = getattr(workspace, "state_root", None)
        self._state_root = Path(state_root) if state_root is not None else None
        self._cas_root = (
            Path(cas_root)
            if cas_root is not None
            else self._state_root / "skill-hub-cas"
            if self._state_root is not None
            else None
        )
        self._distribution_lookup = distribution_lookup

    def resolve(
        self,
        identifier: Any,
        *,
        journey: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return a value-free resolution; expected local gaps never raise."""

        try:
            identity = normalize_skill_identity(identifier)
        except InputValidationError:
            return _result(None, ["SKILL_DEPENDENCY_UNRESOLVED"])
        builtin = skill_artifact(identity)
        if builtin is not None:
            return self._resolve_builtin(builtin, journey)
        return self._resolve_locked(identity, journey)

    def _resolve_builtin(
        self,
        artifact: dict[str, Any],
        journey: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        try:
            package = validate_skill_package(artifact)
            artifact["package_digest"] = package["package_digest"]
            artifact["runtime_binding"] = _binding("unlocked")
            reasons = _artifact_reasons(artifact, journey)
        except SkillPackageError:
            return _result(None, ["SKILL_PACKAGE_INVALID"])
        return _result(artifact, reasons)

    def _resolve_locked(
        self,
        identity: str,
        journey: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        artifact: dict[str, Any] | None = None
        paths = [SKILLS_LOCK_NAME]
        try:
            root, revision = self._project_snapshot()
            lock = compile_skills_lock(
                _tracked_json(
                    root,
                    SKILLS_LOCK_NAME,
                    missing_reason="HUB_SKILL_MISSING",
                    invalid_reason="SKILLS_LOCK_INVALID",
                )
            )
            if lock["runtime_version"] != self._runtime_version:
                raise SkillHubContractError(
                    "HUB_RUNTIME_INCOMPATIBLE",
                    "Skill lock targets another Runtime version",
                )
            entry = next(
                (item for item in lock["skills"] if item["skill_uri"] == identity),
                None,
            )
            if entry is None:
                raise SkillHubContractError(
                    "HUB_SKILL_MISSING", "Exact Team Skill is absent from the lock"
                )
            verified = self._cas_artifact(entry)
            artifact = copy.deepcopy(verified["artifact"])
            artifact["package_digest"] = verified["package"]["package_digest"]
            artifact["runtime_binding"] = _binding(
                "locked",
                team_lock_digest=lock["lock_digest"],
                hub_source=lock["source"],
            )
            _validate_locked_entry(
                artifact,
                verified["package"],
                entry,
                runtime_version=self._runtime_version,
            )
            reasons = _artifact_reasons(artifact, journey)
            trusted_reasons, trusted_paths = self._trusted_binding(artifact)
            paths.extend(trusted_paths)
            reasons.extend(trusted_reasons)
            _assert_project_snapshot(root, revision, paths)
            return _result(artifact, list(dict.fromkeys(reasons)))
        except SkillHubContractError as exc:
            return _result(artifact, [exc.reason_code])
        except ContextContractError as exc:
            return _result(artifact, [_context_reason(exc.reason_code)])

    def _project_snapshot(self) -> tuple[Path, str]:
        supplied = getattr(self._workspace, "root", None)
        if supplied is None:
            raise SkillHubContractError(
                "HUB_SOURCE_UNAVAILABLE", "Project repository root is unavailable"
            )
        candidate = Path(supplied)
        root = candidate.resolve()
        if candidate.is_symlink() or not root.is_dir():
            raise SkillHubContractError(
                "HUB_SOURCE_UNAVAILABLE", "Project repository root is unavailable"
            )
        try:
            snapshot = git_snapshot(root)
        except ContextContractError as exc:
            raise SkillHubContractError(
                "HUB_SOURCE_UNAVAILABLE", "Project Git snapshot is unavailable"
            ) from exc
        return root, snapshot["source_revision"]

    def _cas_artifact(self, entry: Mapping[str, Any]) -> dict[str, Any]:
        if self._cas_root is None:
            raise SkillHubContractError(
                "HUB_CAS_MISSING", "Runtime Skill CAS root is missing"
            )
        root = assert_unlinked_path(
            self._cas_root,
            reason="HUB_CAS_TAMPERED",
            label="Runtime Skill CAS root",
        )
        if not root.is_dir():
            raise SkillHubContractError(
                "HUB_CAS_MISSING", "Runtime Skill CAS root is missing"
            )
        path = root / "skills" / "sha256" / str(entry["package_digest"])
        assert_unlinked_path(
            path,
            reason="HUB_CAS_TAMPERED",
            label="Runtime Skill CAS entry",
        )
        return validate_skill_directory(
            path, expected_digest=str(entry["package_digest"])
        )

    def _trusted_binding(
        self, artifact: dict[str, Any]
    ) -> tuple[list[str], list[str]]:
        contract = artifact["contract"]
        builtin_operators = {
            item["contract"]["uri"] for item in builtin_operator_artifacts()
        }
        required_operators = set(contract["operator_dependencies"]) - builtin_operators
        required_models = set(contract["model_dependencies"])
        if not required_operators and not required_models:
            return [], []

        supplied_root = getattr(self._workspace, "root", None)
        if supplied_root is None:
            return ["HUB_SOURCE_UNAVAILABLE"], []
        root = Path(supplied_root).resolve()
        binding = artifact["runtime_binding"]
        paths = [TRUSTED_PACKS_LOCK_NAME]
        try:
            lock = compile_trusted_packs_lock(
                _tracked_json(
                    root,
                    TRUSTED_PACKS_LOCK_NAME,
                    missing_reason="HUB_TRUSTED_PACK_MISSING",
                    invalid_reason="TRUSTED_PACK_LOCK_INVALID",
                )
            )
            binding["trusted_pack_lock_digest"] = lock["lock_digest"]
            if lock["runtime_version"] != self._runtime_version:
                raise SkillHubContractError(
                    "HUB_RUNTIME_INCOMPATIBLE",
                    "Trusted Pack lock targets another Runtime version",
                )
            _validate_trusted_coverage(lock, required_operators, required_models)

            if self._state_root is None:
                raise SkillHubContractError(
                    "TRUSTED_PACK_STATE_INVALID", "Trusted Pack state is unavailable"
                )
            state_path = self._state_root / TRUSTED_PACK_STATE_NAME
            try:
                state = compile_trusted_installation_state(read_json(state_path))
            except SkillHubContractError as exc:
                reason = (
                    exc.reason_code
                    if exc.reason_code.startswith("TRUSTED_PACK_STATE_")
                    else "TRUSTED_PACK_STATE_INVALID"
                )
                raise SkillHubContractError(
                    reason, "Trusted Pack state is unavailable"
                ) from exc
            binding["trusted_pack_state_digest"] = state["state_digest"]
            verification = verify_trusted_pack_startup(
                lock,
                state,
                distribution_lookup=self._distribution_lookup,
            )
            binding["trusted_pack_verification_digest"] = canonical_digest(
                verification
            )
            if not verification["ok"]:
                return list(verification["reason_codes"]), paths
            return [], paths
        except SkillHubContractError as exc:
            return [exc.reason_code], paths


def _tracked_json(
    root: Path,
    relative: str,
    *,
    missing_reason: str,
    invalid_reason: str,
) -> dict[str, Any]:
    try:
        content, _path = read_context_file(
            root,
            relative,
            maximum=_MAX_LOCK_BYTES,
            require_tracked=True,
            max_depth=1,
        )
    except ContextContractError as exc:
        if exc.reason_code == "CONTEXT_RESOURCE_MISSING":
            reason = missing_reason
        elif exc.reason_code == "CONTEXT_SNAPSHOT_CHANGED":
            reason = "HUB_SOURCE_SNAPSHOT_CHANGED"
        else:
            reason = invalid_reason
        raise SkillHubContractError(reason, f"Project lock {relative} is unavailable") from exc
    try:
        value = json.loads(content)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SkillHubContractError(
            invalid_reason, f"Project lock {relative} is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise SkillHubContractError(
            invalid_reason, f"Project lock {relative} must be an object"
        )
    return value


def _assert_project_snapshot(root: Path, revision: str, paths: list[str]) -> None:
    assert_clean_paths(root, paths)
    if git_snapshot(root)["source_revision"] != revision:
        raise ContextContractError(
            "CONTEXT_SNAPSHOT_CHANGED", "Project lock snapshot changed"
        )


def _validate_locked_entry(
    artifact: Mapping[str, Any],
    package: Mapping[str, Any],
    entry: Mapping[str, Any],
    *,
    runtime_version: str,
) -> None:
    contract = artifact["contract"]
    dependencies = {
        "journeys": sorted(contract["covers_journeys"]),
        "capabilities": sorted(
            copy.deepcopy(contract["capability_dependencies"]),
            key=_capability_dependency_key,
        ),
        "semantics": sorted(contract["semantic_dependencies"]),
        "operators": sorted(contract["operator_dependencies"]),
        "models": sorted(contract["model_dependencies"]),
        "context": {
            "required": sorted(contract["context_dependencies"]["required"]),
            "optional": sorted(contract["context_dependencies"]["optional"]),
        },
    }
    try:
        compatible = runtime_satisfies(runtime_version, contract["runtime_requires"])
    except ValueError as exc:
        raise SkillHubContractError(
            "HUB_RUNTIME_INCOMPATIBLE", "Team Skill Runtime requirement is invalid"
        ) from exc
    if not compatible:
        raise SkillHubContractError(
            "HUB_RUNTIME_INCOMPATIBLE", "Team Skill does not support this Runtime"
        )
    if (
        artifact["skill_uri"] != entry["skill_uri"]
        or artifact["digest"] != entry["manifest_digest"]
        or package["package_digest"] != entry["package_digest"]
        or contract["runtime_requires"] != entry["runtime_requires"]
        or dependencies != entry["dependencies"]
    ):
        raise SkillHubContractError(
            "HUB_SKILL_DIGEST_MISMATCH",
            "Team Skill lock and verified CAS content disagree",
        )
    if contract["provenance"]["source_kind"] != "independent":
        raise SkillHubContractError(
            "HUB_SKILL_INVALID", "Team Skill provenance is not independent"
        )


def _validate_trusted_coverage(
    lock: Mapping[str, Any],
    operators: set[str],
    models: set[str],
) -> None:
    for identity, field in (
        *((identity, "operators") for identity in sorted(operators)),
        *((identity, "models") for identity in sorted(models)),
    ):
        matches = [item for item in lock["packs"] if identity in item[field]]
        if not matches:
            raise SkillHubContractError(
                "HUB_TRUSTED_PACK_MISSING",
                "Locked Skill dependency has no Trusted Pack coverage",
            )
        if len(matches) != 1:
            raise SkillHubContractError(
                "TRUSTED_PACK_LOCK_INVALID",
                "Locked Skill dependency has ambiguous Trusted Pack coverage",
            )


def _capability_dependency_key(value: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(value[field])
        for field in (
            "identity_kind",
            "selector",
            "contract_version",
            "minimum_trust",
            "completeness",
            "data_quality",
        )
    )


def _artifact_reasons(
    artifact: Mapping[str, Any], journey: Mapping[str, Any] | None
) -> list[str]:
    contract = artifact["contract"]
    reasons: list[str] = []
    if journey is not None:
        try:
            validate_skill_journey_parity(contract, journey["contract"])
        except (KeyError, SkillContractError):
            reasons.append("SKILL_DEPENDENCY_UNRESOLVED")
    if contract["lifecycle"] in {"deprecated", "revoked"}:
        reasons.append(
            "SKILL_REVOKED"
            if contract["lifecycle"] == "revoked"
            else "SKILL_DEPRECATED"
        )
    if contract["readiness"] != "executable":
        reasons.append("SKILL_DECLARED_BLOCKED")
    if contract["validation"] != "validated":
        reasons.append("SKILL_UNVALIDATED")
    if contract["effects"] != ["read"]:
        reasons.append("SKILL_EFFECT_UNSUPPORTED")
    return reasons


def _binding(
    resolution: str,
    *,
    team_lock_digest: str | None = None,
    hub_source: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    source = copy.deepcopy(dict(hub_source)) if hub_source is not None else None
    return {
        "resolution": resolution,
        "team_lock_digest": team_lock_digest,
        "hub_source_digest": canonical_digest(source) if source is not None else None,
        "hub_source_reference": source,
        "trusted_pack_lock_digest": None,
        "trusted_pack_state_digest": None,
        "trusted_pack_verification_digest": None,
    }


def _result(
    artifact: Mapping[str, Any] | None, reasons: list[str]
) -> dict[str, Any]:
    selected = list(dict.fromkeys(reasons))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "resolved" if not selected else "blocked",
        "ok": not selected,
        "skill": copy.deepcopy(dict(artifact)) if artifact is not None else None,
        "reason_codes": selected,
        "network_called": False,
    }


def _context_reason(reason: str) -> str:
    return (
        "HUB_SOURCE_SNAPSHOT_CHANGED"
        if reason == "CONTEXT_SNAPSHOT_CHANGED"
        else "HUB_SOURCE_UNAVAILABLE"
    )


__all__ = [
    "RuntimeSkillResolver",
    "SCHEMA_VERSION",
    "SKILLS_LOCK_NAME",
    "TRUSTED_PACKS_LOCK_NAME",
    "TRUSTED_PACK_STATE_NAME",
]
