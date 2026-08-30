"""Blob type verification and atomic publication."""
from __future__ import annotations

import os
from pathlib import Path
import stat

from .blob_archive import _ZIP_MAGICS, _inspect_zip_file
from .blob_models import BlobTransferError
from .blob_policy import BlobPolicy
from .blob_storage import _reparse_stat, _require_plain_directory

def _inspect_type_and_archive(
    path: Path,
    extension: str,
    content_type: str,
    policy: BlobPolicy,
) -> None:
    if extension not in policy.allowed_extensions:
        raise BlobTransferError(
            "blob extension is outside the allowlist",
            code="BLOB_EXTENSION_MISMATCH",
            stage="type_check",
        )
    if content_type not in policy.allowed_mime_types:
        raise BlobTransferError(
            "blob MIME type is outside the allowlist",
            code="BLOB_MIME_MISMATCH",
            stage="type_check",
        )
    extension_mimes = policy.mime_types_by_extension.get(extension, ())
    if content_type not in extension_mimes:
        raise BlobTransferError(
            "blob MIME type does not match its extension",
            code="BLOB_TYPE_MISMATCH",
            stage="type_check",
        )
    signatures = policy.magic_signatures.get(extension, ())
    if not signatures:
        raise BlobTransferError(
            "blob extension has no configured magic signature",
            code="BLOB_POLICY_INVALID",
            stage="type_check",
        )
    maximum_probe = max(
        4,
        max(signature.offset + len(signature.value) for signature in signatures),
    )
    try:
        with path.open("rb") as handle:
            probe = handle.read(maximum_probe)
    except OSError as exc:
        raise BlobTransferError(
            "could not read blob magic bytes",
            code="LOCAL_IO_ERROR",
            stage="type_check",
        ) from exc
    if not any(
        len(probe) >= signature.offset + len(signature.value)
        and probe[signature.offset : signature.offset + len(signature.value)]
        == signature.value
        for signature in signatures
    ):
        raise BlobTransferError(
            "blob magic bytes do not match its extension and MIME",
            code="BLOB_MAGIC_MISMATCH",
            stage="type_check",
        )
    is_zip = probe.startswith(_ZIP_MAGICS)
    if extension == ".zip" and not is_zip:
        raise BlobTransferError(
            "ZIP extension does not contain ZIP magic bytes",
            code="BLOB_MAGIC_MISMATCH",
            stage="type_check",
        )
    if is_zip:
        if not policy.archive_policy.enabled:
            raise BlobTransferError(
                "archives are disabled by policy",
                code="BLOB_ARCHIVE_BLOCKED",
                stage="archive_check",
            )
        _inspect_zip_file(path, policy.archive_policy)
def _commit_staging(staging: Path, destination: Path, policy: BlobPolicy) -> None:
    _require_plain_directory(
        destination.parent,
        boundary=Path(os.path.abspath(policy.destination_root)),
        stage="commit",
    )
    if os.path.lexists(destination):
        value = os.lstat(destination)
        if _reparse_stat(destination, value):
            raise BlobTransferError(
                "destination became a symlink or reparse point",
                code="BLOB_PATH_REPARSE",
                stage="commit",
            )
        if policy.overwrite_policy == "deny":
            raise BlobTransferError(
                "destination appeared before commit",
                code="BLOB_OVERWRITE_DENIED",
                stage="commit",
            )
        if not stat.S_ISREG(value.st_mode):
            raise BlobTransferError(
                "replace target is not a regular file",
                code="BLOB_PATH_UNSAFE",
                stage="commit",
            )
    try:
        if policy.overwrite_policy == "replace":
            os.replace(staging, destination)
        else:
            # Hard-link publication is the portable no-clobber atomic commit.
            os.link(staging, destination, follow_symlinks=False)
            try:
                staging.unlink()
            except OSError:
                destination.unlink(missing_ok=True)
                raise
    except FileExistsError as exc:
        raise BlobTransferError(
            "destination appeared before commit",
            code="BLOB_OVERWRITE_DENIED",
            stage="commit",
        ) from exc
    except OSError as exc:
        raise BlobTransferError(
            "could not atomically commit the verified blob",
            code="LOCAL_IO_ERROR",
            stage="commit",
        ) from exc
