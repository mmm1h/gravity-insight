"""Stage A Skill Hub Source and Index contracts."""

from __future__ import annotations

import copy
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)
from .runtime_compatibility import runtime_satisfies, runtime_within
from .skill_contract import SkillContractError, compile_skill_manifest, skill_uri
from .skill_render import skill_package_descriptor
from .trusted_pack_contract import (
    TrustedPackContractError,
    compile_trusted_pack_descriptor,
)


SOURCE_SCHEMA_VERSION = "gravity.skill-hub-source.v1"
INDEX_SCHEMA_VERSION = "gravity.skill-hub-index.v1"
_SOURCE_SCHEMA = "skill-hub-source-v1.schema.json"
_INDEX_SCHEMA = "skill-hub-index-v1.schema.json"


class SkillHubContractError(AgentRuntimeContractError):
    """A Stage A Hub source, index, or artifact boundary is invalid."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def compile_hub_source(value: Mapping[str, Any]) -> dict[str, Any]:
    contract = _object(value, "HUB_SOURCE_INVALID", "Hub Source")
    _schema(contract, _SOURCE_SCHEMA, "HUB_SOURCE_INVALID", "Hub Source")
    transport = contract["transport"]
    if (transport == "git") != (contract["git"] is not None) or (
        transport == "static_https"
    ) != (contract["https"] is not None):
        raise SkillHubContractError(
            "HUB_SOURCE_INVALID", "Hub Source transport configuration disagrees"
        )
    if transport == "git":
        _source_url(contract["git"]["repository_uri"], git=True)
        _artifact_path(contract["git"]["index_path"])
    else:
        index = _source_url(contract["https"]["index_url"], git=False)
        base = _source_url(contract["https"]["artifact_base_url"], git=False)
        if (index.scheme, index.hostname, index.port) != (
            base.scheme,
            base.hostname,
            base.port,
        ) or not contract["https"]["artifact_base_url"].endswith("/"):
            raise SkillHubContractError(
                "HUB_SOURCE_INVALID",
                "Static HTTPS index and artifact base must share one exact origin",
            )
        if contract["https"]["source_revision"].casefold() in {
            "latest",
            "current",
            "head",
        }:
            raise SkillHubContractError(
                "HUB_SOURCE_TRUST_UNSUPPORTED",
                "Static HTTPS source revision must be immutable and exact",
            )
    return {"contract": contract, "digest": canonical_digest(contract)}


def compile_hub_index(
    value: Mapping[str, Any], *, runtime_version: str | None = None
) -> dict[str, Any]:
    contract = _object(value, "HUB_INDEX_INVALID", "Hub Index")
    _schema(contract, _INDEX_SCHEMA, "HUB_INDEX_INVALID", "Hub Index")
    if not contract["skills"] and not contract["trusted_packs"]:
        raise SkillHubContractError("HUB_INDEX_EMPTY", "Hub Index has no artifacts")
    skills = [_compile_skill_entry(item, runtime_version) for item in contract["skills"]]
    packs = [_compile_pack_entry(item, runtime_version) for item in contract["trusted_packs"]]
    _unique(skills, "skill_uri", "Skill identities")
    _unique(packs, "pack_id", "Trusted Pack identities")
    archives = [item["archive"]["path"] for item in (*skills, *packs)]
    if len(archives) != len(set(archives)):
        raise SkillHubContractError(
            "HUB_INDEX_CONFLICT", "Hub artifact paths are duplicated"
        )
    normalized = {
        **contract,
        "skills": sorted(skills, key=lambda item: item["skill_uri"]),
        "trusted_packs": sorted(packs, key=lambda item: item["pack_id"]),
    }
    return {
        "contract": normalized,
        "digest": canonical_digest(normalized),
        "skills": {item["skill_uri"]: copy.deepcopy(item) for item in normalized["skills"]},
        "trusted_packs": {
            item["pack_id"]: copy.deepcopy(item) for item in normalized["trusted_packs"]
        },
    }


def artifact_path(value: str) -> str:
    return _artifact_path(value)


def _compile_skill_entry(
    value: Mapping[str, Any], runtime_version: str | None
) -> dict[str, Any]:
    selected = copy.deepcopy(dict(value))
    try:
        manifest = compile_skill_manifest(
            selected["manifest"], label="Hub Skill manifest"
        )
    except SkillContractError as exc:
        raise SkillHubContractError(
            "HUB_SKILL_INVALID", "Hub Skill Manifest is invalid"
        ) from exc
    identity = skill_uri(manifest)
    artifact = {
        "contract": manifest,
        "digest": canonical_digest(manifest),
        "skill_uri": identity,
    }
    package = skill_package_descriptor(artifact)
    if selected["skill_uri"] != identity or selected["package"] != package:
        raise SkillHubContractError(
            "HUB_SKILL_DIGEST_MISMATCH", "Hub Skill Manifest or Package changed"
        )
    if runtime_version is not None:
        try:
            compatible = runtime_satisfies(runtime_version, manifest["runtime_requires"])
        except ValueError as exc:
            raise SkillHubContractError(
                "HUB_RUNTIME_INVALID", "Skill runtime compatibility is invalid"
            ) from exc
        if not compatible:
            raise SkillHubContractError(
                "HUB_RUNTIME_INCOMPATIBLE", "Skill does not support this Runtime"
            )
    _archive(selected["archive"], "application/vnd.gravity.skill-package.v1+zip")
    return {
        "skill_uri": identity,
        "manifest": manifest,
        "package": package,
        "archive": copy.deepcopy(selected["archive"]),
    }


def _compile_pack_entry(
    value: Mapping[str, Any], runtime_version: str | None
) -> dict[str, Any]:
    selected = copy.deepcopy(dict(value))
    try:
        compiled = compile_trusted_pack_descriptor(selected["descriptor"])
    except TrustedPackContractError as exc:
        raise SkillHubContractError(
            "HUB_TRUSTED_PACK_INVALID", "Trusted Pack descriptor is invalid"
        ) from exc
    contract = compiled["contract"]
    if (
        selected["pack_id"] != contract["pack_id"]
        or selected["descriptor_digest"] != compiled["digest"]
        or selected["archive"]["sha256"] != contract["wheel_sha256"]
    ):
        raise SkillHubContractError(
            "HUB_TRUSTED_PACK_DIGEST_MISMATCH", "Trusted Pack descriptor changed"
        )
    if runtime_version is not None:
        compatibility = contract["runtime_compatibility"]
        try:
            compatible = runtime_within(
                runtime_version, compatibility["minimum"], compatibility["maximum"]
            )
        except ValueError as exc:
            raise SkillHubContractError(
                "HUB_RUNTIME_INVALID", "Trusted Pack runtime compatibility is invalid"
            ) from exc
        if not compatible:
            raise SkillHubContractError(
                "HUB_RUNTIME_INCOMPATIBLE", "Trusted Pack does not support this Runtime"
            )
    _archive(selected["archive"], "application/vnd.python.wheel")
    return {
        "pack_id": contract["pack_id"],
        "descriptor": contract,
        "descriptor_digest": compiled["digest"],
        "archive": copy.deepcopy(selected["archive"]),
    }


def _archive(value: Mapping[str, Any], media_type: str) -> None:
    _artifact_path(value["path"])
    if value["media_type"] != media_type:
        raise SkillHubContractError(
            "HUB_ARTIFACT_INVALID", "Hub artifact media type changed"
        )


def _artifact_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise SkillHubContractError(
            "HUB_ARTIFACT_PATH_INVALID", "Hub artifact path is not normalized"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or len(path.parts) > 8
        or path.as_posix() != value
    ):
        raise SkillHubContractError(
            "HUB_ARTIFACT_PATH_INVALID", "Hub artifact path escapes its boundary"
        )
    return value


def _source_url(value: str, *, git: bool) -> Any:
    parsed = urlparse(value)
    try:
        parsed.port
    except ValueError as exc:
        raise SkillHubContractError(
            "HUB_SOURCE_TRUST_UNSUPPORTED", "Hub Source URL port is invalid"
        ) from exc
    allowed = {"https", "ssh"} if git else {"https"}
    if (
        parsed.scheme not in allowed
        or not parsed.hostname
        or parsed.password is not None
        or (parsed.username is not None and parsed.scheme == "https")
        or parsed.query
        or parsed.fragment
    ):
        raise SkillHubContractError(
            "HUB_SOURCE_TRUST_UNSUPPORTED",
            "Hub Source URL is outside the Stage A trust boundary",
        )
    return parsed


def _unique(values: Sequence[Mapping[str, Any]], key: str, label: str) -> None:
    identities = [item[key] for item in values]
    if len(identities) != len(set(identities)):
        raise SkillHubContractError("HUB_INDEX_CONFLICT", f"{label} are duplicated")


def _schema(value: Mapping[str, Any], schema: str, reason: str, label: str) -> None:
    try:
        validate_schema(value, schema, label)
    except AgentRuntimeContractError as exc:
        raise SkillHubContractError(reason, str(exc)) from exc


def _object(value: Any, reason: str, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SkillHubContractError(reason, f"{label} must be an object")
    return copy.deepcopy(dict(value))


__all__ = [
    "INDEX_SCHEMA_VERSION",
    "SOURCE_SCHEMA_VERSION",
    "SkillHubContractError",
    "artifact_path",
    "compile_hub_index",
    "compile_hub_source",
]
