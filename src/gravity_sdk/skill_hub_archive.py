"""Bounded archive validation for no-code Skills and reviewed Trusted wheels."""

from __future__ import annotations

import configparser
import hashlib
import io
import json
import os
import re
import stat
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .agent_runtime_contracts import canonical_digest
from .skill_contract import SkillContractError, compile_skill_manifest, skill_uri
from .skill_hub_contract import SkillHubContractError
from .skill_hub_paths import assert_unlinked_path, is_reparse
from .skill_package import (
    MAX_FILE_BYTES,
    MAX_PACKAGE_FILES,
    MAX_PATH_DEPTH,
    MAX_TOTAL_BYTES,
    validate_package_entries,
)
from .skill_render import render_package_files, skill_package_descriptor


MAX_COMPRESSION_RATIO = 100
MAX_WHEEL_FILES = 4096
MAX_WHEEL_FILE_BYTES = 16 * 1024 * 1024
MAX_WHEEL_TOTAL_BYTES = 128 * 1024 * 1024
MAX_WHEEL_PATH_DEPTH = 16
_DISTRIBUTION_NORMALIZE = re.compile(r"[-_.]+")


def validate_skill_archive(
    content: bytes, index_entry: Mapping[str, Any]
) -> dict[str, Any]:
    _outer_boundary(content, index_entry["archive"])
    files = _zip_files(
        content,
        max_files=MAX_PACKAGE_FILES,
        max_file_bytes=MAX_FILE_BYTES,
        max_total_bytes=MAX_TOTAL_BYTES,
        max_depth=MAX_PATH_DEPTH,
        allow_empty=False,
    )
    try:
        manifest_value = json.loads(files["manifest.json"].decode("utf-8"))
    except (KeyError, UnicodeError, json.JSONDecodeError, SkillContractError) as exc:
        raise SkillHubContractError(
            "HUB_SKILL_ARCHIVE_INVALID", "Skill archive Manifest is unavailable"
        ) from exc
    manifest = compile_skill_manifest(manifest_value, label="Hub archive Manifest")
    identity = skill_uri(manifest)
    artifact = {
        "contract": manifest,
        "digest": canonical_digest(manifest),
        "skill_uri": identity,
    }
    package = skill_package_descriptor(artifact)
    try:
        validate_package_entries(files, expected=render_package_files(artifact))
    except Exception as exc:
        raise SkillHubContractError(
            "HUB_SKILL_ARCHIVE_INVALID", "Skill archive differs from its Render Model"
        ) from exc
    if (
        identity != index_entry["skill_uri"]
        or manifest != index_entry["manifest"]
        or package != index_entry["package"]
    ):
        raise SkillHubContractError(
            "HUB_SKILL_DIGEST_MISMATCH", "Skill archive identity or digest changed"
        )
    return {
        "skill_uri": identity,
        "artifact": artifact,
        "package": package,
        "files": files,
    }


def validate_skill_directory(
    root: Path, *, expected_digest: str | None = None
) -> dict[str, Any]:
    try:
        root_metadata = root.lstat()
    except OSError as exc:
        raise SkillHubContractError("HUB_CAS_MISSING", "Skill CAS entry is missing") from exc
    selected = root.resolve()
    if root.is_symlink() or is_reparse(root_metadata) or not selected.is_dir():
        raise SkillHubContractError(
            "HUB_CAS_TAMPERED", "Skill CAS entry is missing or linked"
        )
    files = _directory_files(selected)
    return _compiled_skill_directory(files, expected_digest)


def _directory_files(root: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    total = 0
    for current, directories, names in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        for name in directories:
            _validate_cas_directory(base / name)
        for name in names:
            path = base / name
            relative = path.relative_to(root).as_posix()
            content = _read_cas_file(path, relative)
            files[relative] = content
            total += len(content)
            if len(files) > MAX_PACKAGE_FILES or total > MAX_TOTAL_BYTES:
                raise SkillHubContractError(
                    "HUB_CAS_TAMPERED", "Skill CAS resource budget changed"
                )
    return files


def _validate_cas_directory(path: Path) -> None:
    metadata = path.lstat()
    if path.is_symlink() or is_reparse(metadata):
        raise SkillHubContractError(
            "HUB_CAS_TAMPERED", "Skill CAS contains a linked directory"
        )


def _read_cas_file(path: Path, relative: str) -> bytes:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or is_reparse(metadata)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) & 0o111
        or not 1 <= metadata.st_size <= MAX_FILE_BYTES
    ):
        raise SkillHubContractError(
            "HUB_CAS_TAMPERED", "Skill CAS file boundary changed"
        )
    _archive_path(relative, MAX_PATH_DEPTH)
    content = path.read_bytes()
    if len(content) != metadata.st_size:
        raise SkillHubContractError(
            "HUB_CAS_TAMPERED", "Skill CAS file changed while reading"
        )
    return content


def _compiled_skill_directory(
    files: Mapping[str, bytes], expected_digest: str | None
) -> dict[str, Any]:
    try:
        manifest = compile_skill_manifest(
            json.loads(files["manifest.json"].decode("utf-8")),
            label="CAS Skill manifest",
        )
    except (KeyError, UnicodeError, json.JSONDecodeError, SkillContractError) as exc:
        raise SkillHubContractError(
            "HUB_CAS_TAMPERED", "Skill CAS Manifest changed"
        ) from exc
    artifact = {
        "contract": manifest,
        "digest": canonical_digest(manifest),
        "skill_uri": skill_uri(manifest),
    }
    package = skill_package_descriptor(artifact)
    try:
        validate_package_entries(files, expected=render_package_files(artifact))
    except Exception as exc:
        raise SkillHubContractError(
            "HUB_CAS_TAMPERED", "Skill CAS differs from its Render Model"
        ) from exc
    if expected_digest is not None and package["package_digest"] != expected_digest:
        raise SkillHubContractError("HUB_CAS_TAMPERED", "Skill CAS digest changed")
    return {"artifact": artifact, "package": package, "files": files}


def validate_trusted_wheel(
    content: bytes, index_entry: Mapping[str, Any]
) -> dict[str, Any]:
    _outer_boundary(content, index_entry["archive"])
    files = _zip_files(
        content,
        max_files=MAX_WHEEL_FILES,
        max_file_bytes=MAX_WHEEL_FILE_BYTES,
        max_total_bytes=MAX_WHEEL_TOTAL_BYTES,
        max_depth=MAX_WHEEL_PATH_DEPTH,
        allow_empty=True,
    )
    metadata_paths = [name for name in files if name.endswith(".dist-info/METADATA")]
    wheel_paths = [name for name in files if name.endswith(".dist-info/WHEEL")]
    record_paths = [name for name in files if name.endswith(".dist-info/RECORD")]
    if len(metadata_paths) != 1 or len(wheel_paths) != 1 or len(record_paths) != 1:
        raise SkillHubContractError(
            "TRUSTED_PACK_WHEEL_INVALID", "Trusted wheel dist-info is incomplete"
        )
    metadata = BytesParser().parsebytes(files[metadata_paths[0]])
    descriptor = index_entry["descriptor"]
    if (
        _normalized_distribution(str(metadata.get("Name", "")))
        != _normalized_distribution(descriptor["distribution"])
        or metadata.get("Version") != descriptor["version"]
        or metadata.get("Gravity-Trusted-Pack-ID") != descriptor["pack_id"]
    ):
        raise SkillHubContractError(
            "TRUSTED_PACK_WHEEL_INVALID", "Trusted wheel distribution changed"
        )
    groups = _wheel_groups(files)
    if groups != set(descriptor["allowed_groups"]):
        raise SkillHubContractError(
            "TRUSTED_PACK_GROUP_INVALID", "Trusted wheel entry-point groups changed"
        )
    return {
        "distribution": descriptor["distribution"],
        "version": descriptor["version"],
        "wheel_sha256": hashlib.sha256(content).hexdigest(),
        "allowed_groups": sorted(groups),
        "file_count": len(files),
        "uncompressed_bytes": sum(len(value) for value in files.values()),
    }


def validate_wheel_file(
    path: Path, *, expected_sha256: str, expected_size: int
) -> Path:
    supplied = path.absolute()
    try:
        assert_unlinked_path(
            supplied,
            reason="TRUSTED_PACK_WHEEL_TAMPERED",
            label="Trusted wheel path",
        )
        metadata = supplied.lstat()
        content = supplied.read_bytes()
    except OSError as exc:
        raise SkillHubContractError(
            "TRUSTED_PACK_WHEEL_MISSING", "Trusted wheel is missing"
        ) from exc
    selected = supplied.resolve()
    attributes = getattr(metadata, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    if (
        bool(attributes & reparse)
        or stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or selected.suffix.casefold() != ".whl"
        or len(content) != expected_size
        or hashlib.sha256(content).hexdigest() != expected_sha256
    ):
        raise SkillHubContractError(
            "TRUSTED_PACK_WHEEL_TAMPERED", "Trusted wheel boundary changed"
        )
    return selected


def _zip_files(
    content: bytes,
    *,
    max_files: int,
    max_file_bytes: int,
    max_total_bytes: int,
    max_depth: int,
    allow_empty: bool,
) -> dict[str, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (OSError, zipfile.BadZipFile) as exc:
        raise SkillHubContractError("HUB_ARCHIVE_INVALID", "Artifact is not a valid ZIP") from exc
    infos = archive.infolist()
    if not 1 <= len(infos) <= max_files:
        raise SkillHubContractError("HUB_ARCHIVE_LIMIT", "Archive file count exceeds bounds")
    names: set[str] = set()
    folded: set[str] = set()
    total = 0
    for info in infos:
        name = _archive_path(info.filename, max_depth)
        key = name.casefold()
        if info.is_dir() or name in names or key in folded:
            raise SkillHubContractError("HUB_ARCHIVE_PATH_INVALID", "Archive paths collide")
        names.add(name)
        folded.add(key)
        _zip_info_boundary(info, max_file_bytes, allow_empty=allow_empty)
        total += info.file_size
        if total > max_total_bytes:
            raise SkillHubContractError("HUB_ARCHIVE_LIMIT", "Archive bytes exceed bounds")
    try:
        files = {info.filename: archive.read(info) for info in infos}
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise SkillHubContractError("HUB_ARCHIVE_INVALID", "Archive extraction failed") from exc
    if any(len(files[info.filename]) != info.file_size for info in infos):
        raise SkillHubContractError("HUB_ARCHIVE_INVALID", "Archive size metadata changed")
    return files


def _zip_info_boundary(
    info: zipfile.ZipInfo, maximum: int, *, allow_empty: bool
) -> None:
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    ratio = info.file_size / max(1, info.compress_size)
    if (
        info.flag_bits & 0x1
        or info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
        or not (0 if allow_empty else 1) <= info.file_size <= maximum
        or ratio > MAX_COMPRESSION_RATIO
        or stat.S_ISLNK(mode)
        or file_type not in {0, stat.S_IFREG}
        or stat.S_IMODE(mode) & 0o111
    ):
        raise SkillHubContractError("HUB_ARCHIVE_UNSAFE", "Archive member is unsafe")


def _archive_path(value: Any, maximum_depth: int) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise SkillHubContractError("HUB_ARCHIVE_PATH_INVALID", "Archive path is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or len(path.parts) > maximum_depth
        or path.as_posix() != value
    ):
        raise SkillHubContractError("HUB_ARCHIVE_PATH_INVALID", "Archive path escapes")
    return value


def _outer_boundary(content: bytes, archive: Mapping[str, Any]) -> None:
    if (
        not isinstance(content, bytes)
        or len(content) != archive["size_bytes"]
        or hashlib.sha256(content).hexdigest() != archive["sha256"]
    ):
        raise SkillHubContractError(
            "HUB_ARTIFACT_DIGEST_MISMATCH", "Artifact bytes changed"
        )


def _wheel_groups(files: Mapping[str, bytes]) -> set[str]:
    paths = [name for name in files if name.endswith(".dist-info/entry_points.txt")]
    if len(paths) != 1:
        raise SkillHubContractError(
            "TRUSTED_PACK_GROUP_INVALID", "Trusted wheel entry points are missing"
        )
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(files[paths[0]].decode("utf-8"))
    except (UnicodeError, configparser.Error) as exc:
        raise SkillHubContractError(
            "TRUSTED_PACK_GROUP_INVALID", "Trusted wheel entry points are invalid"
        ) from exc
    groups = set(parser.sections())
    if not groups or not groups.issubset({"gravity.operators", "gravity.models"}):
        raise SkillHubContractError(
            "TRUSTED_PACK_GROUP_INVALID", "Trusted wheel has an unapproved group"
        )
    if any(not parser.items(group) for group in groups):
        raise SkillHubContractError(
            "TRUSTED_PACK_GROUP_INVALID", "Trusted wheel group is empty"
        )
    return groups


def _normalized_distribution(value: str) -> str:
    return _DISTRIBUTION_NORMALIZE.sub("-", value).casefold()


__all__ = [
    "MAX_COMPRESSION_RATIO",
    "validate_skill_archive",
    "validate_skill_directory",
    "validate_trusted_wheel",
    "validate_wheel_file",
]
