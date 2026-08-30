"""Compatibility facade for policy-bound blob transfer primitives."""

# Implementation is partitioned by responsibility; these re-exports preserve
# the original ``gravity_insight.blob`` API.
from .blob_models import (
    ArchivePolicy,
    AuthorizedBlobSource,
    AuthorizedUploadTarget,
    BlobFinalizationResult,
    BlobFinalizer,
    BlobMetadata,
    BlobReceipt,
    BlobResumeState,
    BlobTransferError,
    BlobTransport,
    MagicSignature,
    RequestsBlobTransport,
    SafeLocalSource,
    UploadReceipt,
)
from .blob_policy import BlobPolicy
from .blob_storage import _is_reparse_stat
from .blob_transfer import SafeBlobTransfer

__all__ = [
    "ArchivePolicy", "AuthorizedBlobSource", "AuthorizedUploadTarget",
    "BlobFinalizationResult", "BlobFinalizer", "BlobMetadata", "BlobPolicy",
    "BlobReceipt", "BlobResumeState", "BlobTransferError", "BlobTransport",
    "MagicSignature", "RequestsBlobTransport", "SafeBlobTransfer",
    "SafeLocalSource", "UploadReceipt",
]
