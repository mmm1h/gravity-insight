"""ZIP archive safety inspection."""
from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import zipfile

from .blob_models import ArchivePolicy, BlobTransferError

_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

@dataclass
class _ArchiveTotals:
    entries: int = 0
    uncompressed_bytes: int = 0


def _inspect_zip_file(path: Path, policy: ArchivePolicy) -> None:
    totals = _ArchiveTotals()
    try:
        with zipfile.ZipFile(path) as archive:
            _inspect_zip(archive, policy, totals, depth=0)
    except BlobTransferError:
        raise
    except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
        _archive_error(
            "archive_inspection_failed",
            f"archive could not be safely inspected ({type(exc).__name__})",
            next_action="Request a regenerated valid ZIP archive; do not retry the same file.",
            exception_type=type(exc).__name__,
            cause=exc,
        )


def _inspect_zip(
    archive: zipfile.ZipFile,
    policy: ArchivePolicy,
    totals: _ArchiveTotals,
    *,
    depth: int,
) -> None:
    for entry in archive.infolist():
        totals.entries += 1
        _validate_entry(entry, policy, totals)
        if entry.is_dir():
            continue
        nested_bytes = _read_entry(archive, entry)
        if nested_bytes is not None:
            _inspect_nested(entry, nested_bytes, policy, totals, depth)


def _validate_entry(
    entry: zipfile.ZipInfo,
    policy: ArchivePolicy,
    totals: _ArchiveTotals,
) -> None:
    name = _display_name(entry.filename)
    if totals.entries > policy.max_entries:
        _archive_error(
            "entry_count_cap",
            f"archive entry count {totals.entries} exceeds cap {policy.max_entries} at {name!r}",
            next_action="Produce a smaller archive or request a reviewed policy change.",
            entry=name,
            observed_entries=totals.entries,
            max_entries=policy.max_entries,
        )
    _validate_archive_name(entry.filename)
    unix_type = (entry.external_attr >> 16) & 0o170000
    if unix_type == stat.S_IFLNK:
        _archive_error(
            "symlink_entry",
            f"archive entry {name!r} is a symlink",
            next_action="Remove the symlink entry and regenerate the archive.",
            entry=name,
            unix_type=unix_type,
        )
    if entry.flag_bits & 0x1:
        _archive_error(
            "encrypted_entry",
            f"archive entry {name!r} is encrypted (flag_bits={entry.flag_bits})",
            next_action="Provide an unencrypted archive whose entries can be inspected.",
            entry=name,
            flag_bits=entry.flag_bits,
        )
    if entry.is_dir():
        return
    totals.uncompressed_bytes += entry.file_size
    if totals.uncompressed_bytes > policy.max_uncompressed_size_bytes:
        _archive_error(
            "uncompressed_size_cap",
            f"archive declared uncompressed bytes {totals.uncompressed_bytes} exceed cap {policy.max_uncompressed_size_bytes} at {name!r}",
            next_action="Produce a smaller archive or request a reviewed policy change.",
            entry=name,
            entry_file_size=entry.file_size,
            observed_uncompressed_bytes=totals.uncompressed_bytes,
            max_uncompressed_size_bytes=policy.max_uncompressed_size_bytes,
        )
    ratio = entry.file_size / max(entry.compress_size, 1)
    if entry.file_size > 0 and ratio > policy.max_compression_ratio:
        _archive_error(
            "compression_ratio_cap",
            f"archive entry {name!r} compression ratio {ratio:.6f} exceeds cap {policy.max_compression_ratio:.6f}",
            next_action="Produce a less-compressible/smaller export or request a reviewed policy change.",
            entry=name,
            declared_uncompressed_size=entry.file_size,
            compressed_size=entry.compress_size,
            observed_compression_ratio=round(ratio, 6),
            max_compression_ratio=policy.max_compression_ratio,
        )


def _read_entry(
    archive: zipfile.ZipFile,
    entry: zipfile.ZipInfo,
) -> bytes | None:
    name = _display_name(entry.filename)
    with archive.open(entry, "r") as member:
        first = member.read(4)
        consumed = len(first)
        nested = first.startswith(_ZIP_MAGICS)
        nested_bytes = bytearray(first) if nested else None
        while True:
            chunk = member.read(64 * 1024)
            if not chunk:
                break
            consumed += len(chunk)
            if consumed > entry.file_size:
                _archive_error(
                    "expanded_beyond_declared_size",
                    f"archive entry {name!r} expanded to at least {consumed} bytes beyond declared {entry.file_size}",
                    next_action="Reject this malformed archive and request a regenerated file.",
                    entry=name,
                    declared_uncompressed_size=entry.file_size,
                    observed_uncompressed_bytes=consumed,
                )
            if nested_bytes is not None:
                nested_bytes.extend(chunk)
    if consumed != entry.file_size:
        _archive_error(
            "size_metadata_mismatch",
            f"archive entry {name!r} declared {entry.file_size} bytes but yielded {consumed}",
            next_action="Reject this malformed archive and request a regenerated file.",
            entry=name,
            declared_uncompressed_size=entry.file_size,
            observed_uncompressed_bytes=consumed,
        )
    return bytes(nested_bytes) if nested_bytes is not None else None


def _inspect_nested(
    entry: zipfile.ZipInfo,
    nested_bytes: bytes,
    policy: ArchivePolicy,
    totals: _ArchiveTotals,
    depth: int,
) -> None:
    name = _display_name(entry.filename)
    observed_depth = depth + 1
    if depth >= policy.max_nested_depth:
        _archive_error(
            "nested_archive_depth_cap",
            f"archive entry {name!r} contains nested ZIP depth {observed_depth}, exceeding cap {policy.max_nested_depth}",
            next_action="Remove the nested archive or request a reviewed depth-policy change.",
            entry=name,
            observed_nested_depth=observed_depth,
            max_nested_depth=policy.max_nested_depth,
        )
    try:
        with zipfile.ZipFile(io.BytesIO(nested_bytes)) as child:
            _inspect_zip(child, policy, totals, depth=observed_depth)
    except BlobTransferError:
        raise
    except (RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
        _archive_error(
            "nested_archive_inspection_failed",
            f"nested archive entry {name!r} could not be safely inspected ({type(exc).__name__})",
            next_action="Remove or regenerate the malformed nested archive.",
            entry=name,
            exception_type=type(exc).__name__,
            cause=exc,
        )


def _validate_archive_name(name: str) -> None:
    display = _display_name(name)
    if not name or "\x00" in name or name.startswith(("/", "\\")):
        _archive_error(
            "absolute_or_empty_entry_path",
            f"archive entry path {display!r} is absolute, empty, or contains NUL",
            next_action="Regenerate the archive with relative non-empty entry paths.",
            entry=display,
        )
    windows = PureWindowsPath(name)
    normalized = PurePosixPath(name.replace("\\", "/"))
    if windows.drive or any(part in {"", ".", ".."} for part in normalized.parts):
        _archive_error(
            "traversal_entry_path",
            f"archive entry path {display!r} can escape or alias its extraction root",
            next_action="Regenerate the archive without drive, empty, dot, or parent path segments.",
            entry=display,
        )


def _display_name(name: str) -> str:
    return " ".join(name.replace("\x00", "<NUL>").splitlines())[:240] or "<empty>"


def _archive_error(
    rule: str,
    message: str,
    *,
    next_action: str,
    cause: BaseException | None = None,
    **observed: object,
) -> None:
    error = BlobTransferError(
        message,
        code="BLOB_ARCHIVE_UNSAFE",
        stage="archive_check",
        details={"rule": rule, **observed, "next_action": next_action},
    )
    if cause is None:
        raise error
    raise error from cause
