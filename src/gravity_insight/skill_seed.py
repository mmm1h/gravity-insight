"""Validation and offline opening of the wheel's sealed Skill seed."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from importlib import resources
from pathlib import PurePosixPath
from typing import Any, Mapping

from ._version import __version__
from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)
from .skill_hub_contract import (
    SkillHubContractError,
    artifact_path,
    compile_hub_index,
    compile_hub_source,
)
from .skill_hub_source import HubSourceSession
from .skill_package import SkillPackageError, validate_package_entries


BUNDLED_SKILL_SEED_NAME = "skill-seed-v1.zip"
_SEED_SCHEMA_VERSION = "gravity.skill-library-build.v2"
_AGENT_INDEX_SCHEMA = "agent-skill-index-v1.schema.json"
_MAX_SEED_BYTES = 128 * 1024 * 1024
_MAX_SEED_FILES = 20_005
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_ZIP_MODE = 0o100644


def open_bundled_hub_source(
    content: bytes | None = None,
    *,
    runtime_version: str = __version__,
) -> HubSourceSession:
    """Open the wheel's sealed mirror without defining another transport."""

    selected = read_bundled_skill_seed() if content is None else content
    validated = validate_bundled_skill_seed(
        selected, runtime_version=runtime_version
    )
    source = validated["source"]
    index = validated["index"]
    files = validated["files"]

    def read(relative: str, maximum: int) -> bytes:
        name = artifact_path(relative)
        artifact = files.get(name)
        if artifact is None:
            raise SkillHubContractError(
                "HUB_SEED_INVALID", "Bundled Skill artifact is missing"
            )
        if len(artifact) > maximum:
            raise SkillHubContractError(
                "HUB_SOURCE_OUTPUT_LIMIT",
                "Bundled Skill artifact exceeds its byte budget",
            )
        return artifact

    return HubSourceSession(
        source,
        str(source["https"]["source_revision"]),
        index,
        False,
        read,
        seed_digest=str(validated["seed_digest"]),
    )


def validate_bundled_skill_seed(
    content: bytes,
    *,
    runtime_version: str = __version__,
) -> dict[str, Any]:
    """Validate the outer seed, build receipt, indexes, and Agent archives."""

    if not isinstance(content, bytes) or not 1 <= len(content) <= _MAX_SEED_BYTES:
        raise SkillHubContractError("HUB_SEED_INVALID", "Bundled Skill seed is invalid")
    try:
        files = _seed_files(content)
        manifest = _seed_json(files, "build-manifest.json", "build manifest")
        release_rows = _validate_seed_manifest(manifest)
        if set(files) != {"build-manifest.json", *release_rows}:
            raise SkillHubContractError(
                "HUB_SEED_INVALID", "Bundled Skill seed file set changed"
            )
        _validate_release_digests(files, release_rows)
        compiled_source = compile_hub_source(
            _seed_json(files, "source.json", "Hub Source")
        )
        compiled_index = _compile_index_bytes(files["index.json"], runtime_version)
        agent_index = _seed_json(files, "agent-index.json", "Agent Skill index")
        validate_schema(agent_index, _AGENT_INDEX_SCHEMA, "Agent Skill index")
        agent_packages = _validate_seed_bindings(
            manifest,
            compiled_source["contract"],
            compiled_index,
            agent_index,
            files,
        )
    except SkillHubContractError:
        raise
    except (AgentRuntimeContractError, SkillPackageError) as exc:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill seed validation failed"
        ) from exc
    return {
        "schema_version": "gravity.skill-seed-validation.v1",
        "seed_digest": hashlib.sha256(content).hexdigest(),
        "build_manifest_digest": canonical_digest(manifest),
        "source": compiled_source["contract"],
        "source_descriptor_digest": compiled_source["digest"],
        "index": compiled_index,
        "agent_index": agent_index,
        "agent_packages": agent_packages,
        "skill_count": len(compiled_index["skills"]),
        "agent_skill_count": len(agent_index["skills"]),
        "files": files,
        "network_called": False,
    }


def read_bundled_skill_seed() -> bytes:
    """Read the package resource without opening or validating the ZIP."""

    try:
        return (
            resources.files("gravity_insight")
            .joinpath("skill_seed", BUNDLED_SKILL_SEED_NAME)
            .read_bytes()
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        raise SkillHubContractError(
            "HUB_SEED_UNAVAILABLE", "Bundled Skill seed is unavailable"
        ) from exc


def _seed_files(content: bytes) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            _validate_outer_archive(archive, members)
            if sum(member.file_size for member in members) > _MAX_SEED_BYTES:
                raise SkillHubContractError(
                    "HUB_SEED_INVALID", "Bundled Skill seed exceeds its byte budget"
                )
            result: dict[str, bytes] = {}
            for member in members:
                _validate_outer_member(member)
                result[member.filename] = _read_member(
                    archive, member, "Bundled Skill seed member changed"
                )
            return result
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill seed is not a valid ZIP"
        ) from exc


def _validate_outer_archive(
    archive: zipfile.ZipFile, members: list[zipfile.ZipInfo]
) -> None:
    names = [item.filename for item in members]
    valid = (
        not archive.comment
        and 5 <= len(members) <= _MAX_SEED_FILES
        and names == sorted(names)
        and len(names) == len(set(names))
        and len(names) == len({name.casefold() for name in names})
    )
    if not valid:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill seed entries are invalid"
        )


def _validate_outer_member(member: zipfile.ZipInfo) -> None:
    path = PurePosixPath(member.filename)
    valid = (
        not path.is_absolute()
        and len(path.parts) == 1
        and all(part not in {"", ".", ".."} for part in path.parts)
        and not member.is_dir()
        and not member.flag_bits & 0x1
        and member.date_time == _ZIP_TIME
        and member.compress_type == zipfile.ZIP_STORED
        and member.create_system == 3
        and member.external_attr >> 16 == _ZIP_MODE
        and member.file_size >= 1
    )
    if not valid:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill seed member is unsafe"
        )


def _read_member(
    archive: zipfile.ZipFile, member: zipfile.ZipInfo, message: str
) -> bytes:
    value = archive.read(member)
    if len(value) != member.file_size:
        raise SkillHubContractError("HUB_SEED_INVALID", message)
    return value


def _seed_json(files: Mapping[str, bytes], name: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(files[name].decode("utf-8"))
    except (KeyError, UnicodeError, json.JSONDecodeError) as exc:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", f"Bundled {label} is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise SkillHubContractError(
            "HUB_SEED_INVALID", f"Bundled {label} must be an object"
        )
    return value


def _validate_seed_manifest(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    expected = {
        "artifact_kind",
        "schema_version",
        "canonical_source",
        "canonical_source_sha256",
        "publish_target",
        "publish_base_url",
        "files",
        "release_assets",
    }
    valid = (
        set(manifest) == expected
        and manifest.get("artifact_kind") == "skill_library_build"
        and manifest.get("schema_version") == _SEED_SCHEMA_VERSION
        and manifest.get("canonical_source") == "skills/library"
        and manifest.get("publish_target") == "github_release"
        and _sha256(manifest.get("canonical_source_sha256"))
        and isinstance(manifest.get("publish_base_url"), str)
    )
    if not valid:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill build manifest changed"
        )
    all_rows = _seed_rows(manifest.get("files"), "build files")
    release_rows = _seed_rows(manifest.get("release_assets"), "release assets")
    bound = all(all_rows.get(name) == row for name, row in release_rows.items())
    if not 4 <= len(release_rows) <= _MAX_SEED_FILES - 1 or not bound:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill release asset binding changed"
        )
    if any("/" in name for name in release_rows):
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill release assets must be flat"
        )
    return release_rows


def _seed_rows(value: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise SkillHubContractError("HUB_SEED_INVALID", f"Bundled {label} changed")
    result: dict[str, dict[str, Any]] = {}
    previous = ""
    for item in value:
        if not _valid_seed_row(item, previous):
            raise SkillHubContractError(
                "HUB_SEED_INVALID", f"Bundled {label} changed"
            )
        previous = item["path"]
        result[item["path"]] = dict(item)
    return result


def _valid_seed_row(value: Any, previous: str) -> bool:
    if not isinstance(value, dict) or set(value) != {"path", "size_bytes", "sha256"}:
        return False
    path = value.get("path")
    size = value.get("size_bytes")
    return (
        isinstance(path, str)
        and bool(path)
        and path > previous
        and isinstance(size, int)
        and not isinstance(size, bool)
        and size >= 1
        and _sha256(value.get("sha256"))
    )


def _validate_release_digests(
    files: Mapping[str, bytes], rows: Mapping[str, Mapping[str, Any]]
) -> None:
    for name, row in rows.items():
        artifact = files[name]
        if row["size_bytes"] != len(artifact):
            raise SkillHubContractError(
                "HUB_SEED_DIGEST_MISMATCH", "Bundled Skill seed artifact changed"
            )
        if row["sha256"] != hashlib.sha256(artifact).hexdigest():
            raise SkillHubContractError(
                "HUB_SEED_DIGEST_MISMATCH", "Bundled Skill seed artifact changed"
            )


def _validate_seed_bindings(
    manifest: Mapping[str, Any],
    source: Mapping[str, Any],
    index: Mapping[str, Any],
    agent_index: Mapping[str, Any],
    files: Mapping[str, bytes],
) -> dict[str, dict[str, bytes]]:
    source_digest = str(manifest["canonical_source_sha256"])
    https = source["https"]
    publish_base = str(manifest["publish_base_url"])
    runtime_entries = list(index["skills"].values())
    agent_entries = list(agent_index["skills"])
    source_bound = (
        source["transport"] == "static_https"
        and source["git"] is None
        and https["source_revision"] == source_digest
        and https["index_url"] == f"{publish_base}/index.json"
        and https["artifact_base_url"] == f"{publish_base}/"
        and agent_index.get("canonical_source_sha256") == source_digest
    )
    if not source_bound or len(runtime_entries) != len(agent_entries):
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill source binding changed"
        )
    runtime_ids = [item["skill_uri"] for item in runtime_entries]
    agent_ids = [item["skill_uri"] for item in agent_entries]
    if runtime_ids != agent_ids:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Runtime and Agent Skill sets differ"
        )
    expected_assets = {
        "index.json",
        "agent-index.json",
        "agent-skill-index-v1.schema.json",
        "source.json",
        *(item["archive"]["path"] for item in runtime_entries),
        *(item["archive"]["path"] for item in agent_entries),
    }
    if set(files) != {"build-manifest.json", *expected_assets}:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill asset references changed"
        )
    return {
        entry["skill_uri"]: _validate_agent_seed_archive(
            files[entry["archive"]["path"]], entry
        )
        for entry in agent_entries
    }


def _validate_agent_seed_archive(
    content: bytes, entry: Mapping[str, Any]
) -> dict[str, bytes]:
    metadata = entry["archive"]
    valid = (
        metadata["size_bytes"] == len(content)
        and metadata["sha256"] == hashlib.sha256(content).hexdigest()
        and metadata["media_type"]
        == "application/vnd.gravity.agent-skill.v1+zip"
    )
    if not valid:
        raise SkillHubContractError(
            "HUB_SEED_DIGEST_MISMATCH", "Bundled Agent Skill archive changed"
        )
    expected = {
        f"{entry['directory']}/{item['path']}": item for item in entry["files"]
    }
    try:
        package_files = _read_agent_archive(content, entry["directory"], expected)
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Agent Skill archive is invalid"
        ) from exc
    validate_package_entries(package_files, allow_skill_md=True)
    return package_files


def _read_agent_archive(
    content: bytes,
    directory: str,
    expected: Mapping[str, Mapping[str, Any]],
) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        members = archive.infolist()
        names = [item.filename for item in members]
        if names != sorted(expected) or len(names) != len(set(names)):
            raise SkillHubContractError(
                "HUB_SEED_INVALID", "Bundled Agent Skill entries changed"
            )
        result: dict[str, bytes] = {}
        for member in members:
            relative, value = _read_agent_member(
                archive, member, directory, expected[member.filename]
            )
            result[relative] = value
        return result


def _read_agent_member(
    archive: zipfile.ZipFile,
    member: zipfile.ZipInfo,
    directory: str,
    metadata: Mapping[str, Any],
) -> tuple[str, bytes]:
    path = PurePosixPath(member.filename)
    valid = (
        not path.is_absolute()
        and bool(path.parts)
        and all(part not in {"", ".", ".."} for part in path.parts)
        and path.parts[0] == directory
        and not member.is_dir()
        and not member.flag_bits & 0x1
        and member.date_time == _ZIP_TIME
        and member.compress_type == zipfile.ZIP_STORED
        and member.create_system == 3
        and member.external_attr >> 16 == _ZIP_MODE
    )
    if not valid:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Agent Skill member is unsafe"
        )
    value = _read_member(archive, member, "Bundled Agent Skill member changed")
    if metadata["size_bytes"] != len(value):
        raise SkillHubContractError(
            "HUB_SEED_DIGEST_MISMATCH", "Bundled Agent Skill content changed"
        )
    if metadata["sha256"] != hashlib.sha256(value).hexdigest():
        raise SkillHubContractError(
            "HUB_SEED_DIGEST_MISMATCH", "Bundled Agent Skill content changed"
        )
    relative = PurePosixPath(*path.parts[1:]).as_posix()
    return relative, value


def _compile_index_bytes(content: bytes, runtime_version: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill Hub index is invalid"
        ) from exc
    if not isinstance(value, dict):
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill Hub index must be an object"
        )
    return compile_hub_index(value, runtime_version=runtime_version)


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


__all__ = [
    "BUNDLED_SKILL_SEED_NAME",
    "open_bundled_hub_source",
    "read_bundled_skill_seed",
    "validate_bundled_skill_seed",
]
