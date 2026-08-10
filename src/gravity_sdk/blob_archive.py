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
        raise BlobTransferError(
            "archive could not be safely inspected",
            code="BLOB_ARCHIVE_UNSAFE",
            stage="archive_check",
        ) from exc


def _inspect_zip(
    archive: zipfile.ZipFile,
    policy: ArchivePolicy,
    totals: _ArchiveTotals,
    *,
    depth: int,
) -> None:
    for entry in archive.infolist():
        totals.entries += 1
        if totals.entries > policy.max_entries:
            _archive_error("archive exceeds the entry-count cap")
        _validate_archive_name(entry.filename)
        unix_type = (entry.external_attr >> 16) & 0o170000
        if unix_type == stat.S_IFLNK:
            _archive_error("archive contains a symlink entry")
        if entry.flag_bits & 0x1:
            _archive_error("encrypted archive entries are not accepted")
        if entry.is_dir():
            continue
        totals.uncompressed_bytes += entry.file_size
        if totals.uncompressed_bytes > policy.max_uncompressed_size_bytes:
            _archive_error("archive exceeds the uncompressed-size cap")
        if entry.file_size > 0:
            ratio = entry.file_size / max(entry.compress_size, 1)
            if ratio > policy.max_compression_ratio:
                _archive_error("archive entry exceeds the compression-ratio cap")

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
                    _archive_error("archive entry expanded beyond its declared size")
                if nested_bytes is not None:
                    nested_bytes.extend(chunk)
            if consumed != entry.file_size:
                _archive_error("archive entry size does not match its metadata")
        if nested:
            if depth >= policy.max_nested_depth:
                _archive_error("archive exceeds the nested-archive depth cap")
            try:
                with zipfile.ZipFile(io.BytesIO(bytes(nested_bytes or b""))) as child:
                    _inspect_zip(child, policy, totals, depth=depth + 1)
            except BlobTransferError:
                raise
            except (RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
                raise BlobTransferError(
                    "nested archive could not be safely inspected",
                    code="BLOB_ARCHIVE_UNSAFE",
                    stage="archive_check",
                ) from exc


def _validate_archive_name(name: str) -> None:
    if not name or "\x00" in name or name.startswith(("/", "\\")):
        _archive_error("archive contains an absolute or empty entry path")
    windows = PureWindowsPath(name)
    normalized = PurePosixPath(name.replace("\\", "/"))
    if windows.drive or any(part in {"", ".", ".."} for part in normalized.parts):
        _archive_error("archive contains a traversal entry path")


def _archive_error(message: str) -> None:
    raise BlobTransferError(
        message,
        code="BLOB_ARCHIVE_UNSAFE",
        stage="archive_check",
    )
