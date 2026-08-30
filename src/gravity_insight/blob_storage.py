"""Fail-closed local path and staging-file operations."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import sys
import tempfile
from typing import Any

from .blob_models import BlobResumeState, BlobTransferError
from .blob_policy import BlobPolicy, _select_extension

_REPARSE_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)


def _is_reparse_stat(path: Path, value: os.stat_result) -> bool:
    if stat.S_ISLNK(value.st_mode):
        return True
    if bool(getattr(value, "st_file_attributes", 0) & _REPARSE_ATTRIBUTE):
        return True
    junction_check = getattr(path, "is_junction", None)
    return bool(junction_check and junction_check())


def _reparse_stat(path: Path, value: os.stat_result) -> bool:
    facade = sys.modules.get(f"{__package__}.blob")
    check = getattr(facade, "_is_reparse_stat", _is_reparse_stat)
    return check(path, value)

def _prepare_destination(destination: str | Path, policy: BlobPolicy) -> tuple[Path, str]:
    if policy.destination_root is None:
        raise BlobTransferError(
            "download policy has no destination root",
            code="BLOB_POLICY_INVALID",
            stage="destination_policy",
        )
    raw = os.fspath(destination)
    parts = _safe_relative_parts(raw, stage="destination_policy")
    root = _require_plain_directory(policy.destination_root, stage="destination_policy")
    candidate = root.joinpath(*parts)
    parent = candidate.parent
    _require_plain_directory(parent, boundary=root, stage="destination_policy")
    temporary_root = _require_plain_directory(
        policy.temporary_root or policy.destination_root,
        stage="destination_policy",
    )
    try:
        parent.relative_to(temporary_root)
    except ValueError as exc:
        raise BlobTransferError(
            "destination is outside the configured temporary root",
            code="BLOB_PATH_ESCAPE",
            stage="destination_policy",
        ) from exc
    if os.path.lexists(candidate):
        value = os.lstat(candidate)
        if _reparse_stat(candidate, value):
            raise BlobTransferError(
                "destination is a symlink or reparse point",
                code="BLOB_PATH_REPARSE",
                stage="destination_policy",
            )
        if policy.overwrite_policy == "deny":
            raise BlobTransferError(
                "destination already exists",
                code="BLOB_OVERWRITE_DENIED",
                stage="destination_policy",
            )
        if not stat.S_ISREG(value.st_mode):
            raise BlobTransferError(
                "replace policy only permits a regular destination file",
                code="BLOB_PATH_UNSAFE",
                stage="destination_policy",
            )
    extension = _select_extension(candidate.name, policy.allowed_extensions)
    return candidate, extension


def _prepare_local_source(relative_path: str | Path, root: Path) -> Path:
    parts = _safe_relative_parts(os.fspath(relative_path), stage="upload_policy")
    safe_root = _require_plain_directory(root, stage="upload_policy")
    candidate = safe_root.joinpath(*parts)
    _require_plain_directory(candidate.parent, boundary=safe_root, stage="upload_policy")
    try:
        value = os.lstat(candidate)
    except FileNotFoundError as exc:
        raise BlobTransferError(
            "upload source does not exist",
            code="LOCAL_IO_ERROR",
            stage="upload_policy",
        ) from exc
    if _reparse_stat(candidate, value) or not stat.S_ISREG(value.st_mode):
        raise BlobTransferError(
            "upload source must be a plain regular file",
            code="BLOB_PATH_REPARSE",
            stage="upload_policy",
        )
    return candidate


def _safe_relative_parts(raw: str, *, stage: str) -> tuple[str, ...]:
    if not raw or "\x00" in raw:
        raise BlobTransferError(
            "local blob path is empty or contains NUL",
            code="BLOB_PATH_ESCAPE",
            stage=stage,
        )
    windows = PureWindowsPath(raw)
    posix = PurePosixPath(raw.replace("\\", "/"))
    if windows.is_absolute() or windows.drive or windows.root or posix.is_absolute():
        raise BlobTransferError(
            "absolute and device paths are not allowed",
            code="BLOB_PATH_ESCAPE",
            stage=stage,
        )
    parts = tuple(posix.parts)
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise BlobTransferError(
            "local blob path contains traversal",
            code="BLOB_PATH_ESCAPE",
            stage=stage,
        )
    if any(":" in part for part in parts):
        raise BlobTransferError(
            "local blob path contains a device or alternate stream marker",
            code="BLOB_PATH_ESCAPE",
            stage=stage,
        )
    for part in parts:
        trimmed = part.rstrip(" .")
        basename = trimmed.split(".", 1)[0].upper()
        if trimmed != part or basename in _WINDOWS_RESERVED_NAMES:
            raise BlobTransferError(
                "local blob path contains a reserved Windows device name",
                code="BLOB_PATH_ESCAPE",
                stage=stage,
            )
    return parts


def _require_plain_directory(
    path: Path,
    *,
    boundary: Path | None = None,
    stage: str,
) -> Path:
    lexical = Path(os.path.abspath(path))
    try:
        value = os.lstat(lexical)
    except FileNotFoundError as exc:
        raise BlobTransferError(
            "configured local directory does not exist",
            code="LOCAL_IO_ERROR",
            stage=stage,
        ) from exc
    if _reparse_stat(lexical, value) or not stat.S_ISDIR(value.st_mode):
        raise BlobTransferError(
            "configured local directory is a symlink or reparse point",
            code="BLOB_PATH_REPARSE",
            stage=stage,
        )
    _assert_plain_ancestors(lexical, stage=stage)
    if boundary is not None:
        safe_boundary = Path(os.path.abspath(boundary))
        try:
            boundary_stat = os.lstat(safe_boundary)
        except FileNotFoundError as exc:
            raise BlobTransferError(
                "configured local root does not exist",
                code="LOCAL_IO_ERROR",
                stage=stage,
            ) from exc
        if _reparse_stat(safe_boundary, boundary_stat) or not stat.S_ISDIR(
            boundary_stat.st_mode
        ):
            raise BlobTransferError(
                "configured local root is a symlink or reparse point",
                code="BLOB_PATH_REPARSE",
                stage=stage,
            )
        try:
            relative = lexical.relative_to(safe_boundary)
        except ValueError as exc:
            raise BlobTransferError(
                "local path escapes its configured root",
                code="BLOB_PATH_ESCAPE",
                stage=stage,
            ) from exc
        current = safe_boundary
        for part in relative.parts:
            current = current / part
            try:
                current_stat = os.lstat(current)
            except FileNotFoundError as exc:
                raise BlobTransferError(
                    "local path component does not exist",
                    code="LOCAL_IO_ERROR",
                    stage=stage,
                ) from exc
            if _reparse_stat(current, current_stat):
                raise BlobTransferError(
                    "local path contains a symlink or reparse point",
                    code="BLOB_PATH_REPARSE",
                    stage=stage,
                )
        try:
            lexical.resolve(strict=True).relative_to(safe_boundary.resolve(strict=True))
        except ValueError as exc:
            raise BlobTransferError(
                "resolved local path escapes its configured root",
                code="BLOB_PATH_ESCAPE",
                stage=stage,
            ) from exc
    return lexical


def _assert_plain_ancestors(path: Path, *, stage: str) -> None:
    parts = path.parts
    if not parts:
        return
    current = Path(parts[0])
    for part in parts[1:]:
        current = current / part
        try:
            value = os.lstat(current)
        except FileNotFoundError as exc:
            raise BlobTransferError(
                "local path component does not exist",
                code="LOCAL_IO_ERROR",
                stage=stage,
            ) from exc
        if _reparse_stat(current, value):
            raise BlobTransferError(
                "local path contains a symlink or reparse point",
                code="BLOB_PATH_REPARSE",
                stage=stage,
            )


def _validate_resume_state(
    resume: BlobResumeState | None,
    policy: BlobPolicy,
) -> Path | None:
    if resume is None:
        return None
    if not policy.allow_range_resume:
        raise BlobTransferError(
            "range resume is disabled by policy",
            code="BLOB_RESUME_DISABLED",
            stage="resume_policy",
        )
    if resume.bytes_received <= 0 or not (resume.etag or resume.last_modified):
        raise BlobTransferError(
            "resume requires bytes and an ETag or Last-Modified validator",
            code="BLOB_RESUME_INVALID",
            stage="resume_policy",
        )
    root_value = policy.temporary_root or policy.destination_root
    if root_value is None:
        raise BlobTransferError(
            "resume policy has no temporary root",
            code="BLOB_POLICY_INVALID",
            stage="resume_policy",
        )
    root = _require_plain_directory(root_value, stage="resume_policy")
    partial = Path(os.path.abspath(resume.partial_path))
    _require_plain_directory(partial.parent, boundary=root, stage="resume_policy")
    try:
        value = os.lstat(partial)
    except FileNotFoundError as exc:
        raise BlobTransferError(
            "resume partial file does not exist",
            code="BLOB_RESUME_INVALID",
            stage="resume_policy",
        ) from exc
    if _reparse_stat(partial, value) or not stat.S_ISREG(value.st_mode):
        raise BlobTransferError(
            "resume partial must be a plain regular file",
            code="BLOB_PATH_REPARSE",
            stage="resume_policy",
        )
    if value.st_size != resume.bytes_received:
        raise BlobTransferError(
            "resume byte count does not match the partial file",
            code="BLOB_RESUME_INVALID",
            stage="resume_policy",
        )
    if value.st_size > policy.max_stream_size_bytes:
        raise BlobTransferError(
            "resume partial exceeds the streaming size cap",
            code="BLOB_SIZE_LIMIT",
            stage="resume_policy",
        )
    return partial


def _new_staging_path(parent: Path, *, suffix: str = ".part") -> Path:
    try:
        descriptor, raw_path = tempfile.mkstemp(prefix=".blob-", suffix=suffix, dir=parent)
        os.close(descriptor)
        return Path(raw_path)
    except OSError as exc:
        raise BlobTransferError(
            "could not create a local staging file",
            code="LOCAL_IO_ERROR",
            stage="staging",
        ) from exc


def _copy_prefix(
    source: Path,
    output: Any,
    digest: Any,
    maximum: int,
    chunk_size: int,
) -> int:
    total = 0
    try:
        with source.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum:
                    raise BlobTransferError(
                        "resume partial exceeds the streaming size cap",
                        code="BLOB_SIZE_LIMIT",
                        stage="stream",
                    )
                output.write(chunk)
                digest.update(chunk)
    except BlobTransferError:
        raise
    except OSError as exc:
        raise BlobTransferError(
            "could not read the resume partial",
            code="LOCAL_IO_ERROR",
            stage="stream",
        ) from exc
    return total


def _hash_regular_file(path: Path, maximum: int, chunk_size: int) -> tuple[int, str]:
    try:
        value = os.lstat(path)
        if _reparse_stat(path, value) or not stat.S_ISREG(value.st_mode):
            raise BlobTransferError(
                "staged blob is not a plain regular file",
                code="BLOB_PATH_REPARSE",
                stage="integrity",
            )
        if value.st_size > maximum:
            raise BlobTransferError(
                "staged blob exceeds the streaming size cap",
                code="BLOB_SIZE_LIMIT",
                stage="integrity",
                details={"limit": maximum},
            )
        digest = hashlib.sha256()
        total = 0
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum:
                    raise BlobTransferError(
                        "staged blob exceeded the streaming size cap while reading",
                        code="BLOB_SIZE_LIMIT",
                        stage="integrity",
                    )
                digest.update(chunk)
        if total != value.st_size:
            raise BlobTransferError(
                "staged blob changed during verification",
                code="BLOB_LOCAL_RACE",
                stage="integrity",
            )
        return total, digest.hexdigest()
    except BlobTransferError:
        raise
    except OSError as exc:
        raise BlobTransferError(
            "could not verify the staged blob",
            code="LOCAL_IO_ERROR",
            stage="integrity",
        ) from exc
