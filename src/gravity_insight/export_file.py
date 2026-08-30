"""Verified file policies for governed exports."""
from __future__ import annotations

from contextlib import contextmanager
import gzip
from pathlib import Path
import re
from typing import Any, Iterator, Mapping, TextIO

from .blob import ArchivePolicy, BlobPolicy, MagicSignature
from .export_models import ExportPrivacyContract, _export_error

_HEX = re.compile(r"^[0-9a-fA-F]{2,}$")


def export_file_policies(
    contract: Any,
    root: Path,
) -> tuple[BlobPolicy, ExportPrivacyContract]:
    protocol = _verified_file_protocol(contract.privacy)
    allowed = tuple(
        str(value) for value in contract.privacy.get("allowed_columns", [])
    )
    required = tuple(
        str(value) for value in contract.privacy.get("required_columns", [])
    )
    if not allowed:
        raise _export_error(
            "export file has no approved column allowlist",
            code="EXPORT_PRIVACY_DENIED",
            stage="privacy_policy",
        )
    return (
        _blob_policy(contract.privacy, protocol, root),
        ExportPrivacyContract(
            allowed_columns=allowed,
            required_columns=required,
            redact_fields=tuple(
                str(value) for value in contract.privacy.get("redact_fields", [])
            ),
            format=protocol[0],
            classification=str(
                contract.privacy.get("classification", "restricted")
            ),
            allow_contracted_identifiers=bool(
                contract.privacy.get("allow_contracted_identifiers", False)
            ),
            encoding=str(contract.privacy.get("encoding", "utf-8")),
            delimiter=str(contract.privacy.get("delimiter", ",")),
        ),
    )


def _verified_file_protocol(
    privacy: Mapping[str, Any],
) -> tuple[str, str, str, list[Any], Mapping[str, Any], bytes]:
    values = (
        privacy.get("format"),
        privacy.get("extension"),
        privacy.get("mime_type"),
        privacy.get("allowed_hosts"),
        privacy.get("allowed_path_prefixes"),
        _magic_bytes(privacy),
    )
    file_format, extension, mime_type, hosts, prefixes, magic = values
    valid = (
        file_format in {"csv", "jsonl", "xlsx"}
        and isinstance(extension, str)
        and isinstance(mime_type, str)
        and isinstance(hosts, list)
        and bool(hosts)
        and isinstance(prefixes, Mapping)
        and isinstance(magic, bytes)
        and bool(magic)
    )
    if not valid:
        raise _export_error(
            "export file protocol has not been verified online",
            code="EXPORT_FORMAT_UNSUPPORTED",
            stage="configuration",
        )
    return values


def _magic_bytes(privacy: Mapping[str, Any]) -> bytes | None:
    hex_value = privacy.get("magic_prefix_hex")
    if isinstance(hex_value, str) and _HEX.fullmatch(hex_value) and len(hex_value) % 2 == 0:
        return bytes.fromhex(hex_value)
    text = privacy.get("magic_prefix_utf8")
    if isinstance(text, str) and text:
        return text.encode("utf-8")
    return None


def _blob_policy(
    privacy: Mapping[str, Any],
    protocol: tuple[str, str, str, list[Any], Mapping[str, Any], bytes],
    root: Path,
) -> BlobPolicy:
    file_format, extension, mime_type, hosts, prefixes, magic = protocol
    maximum = int(privacy.get("max_size_bytes", 100 * 1024 * 1024))
    return BlobPolicy(
        allowed_extensions=frozenset({extension}),
        allowed_mime_types=frozenset({mime_type}),
        magic_signatures={
            extension: (MagicSignature(0, magic),)
        },
        mime_types_by_extension={extension: (mime_type,)},
        max_declared_size_bytes=maximum,
        max_stream_size_bytes=maximum,
        allowed_hosts=frozenset(str(value) for value in hosts),
        allowed_redirect_hosts=frozenset(
            str(value) for value in privacy.get("allowed_redirect_hosts", [])
        ),
        allowed_path_prefixes={
            str(host): tuple(str(value) for value in values)
            for host, values in prefixes.items()
        },
        destination_root=root,
        temporary_root=root,
        overwrite_policy="deny",
        request_timeout_seconds=60.0,
        require_effect_receipt=True,
        archive_policy=_archive_policy(privacy, file_format),
    )


def _archive_policy(
    privacy: Mapping[str, Any],
    file_format: str,
) -> ArchivePolicy:
    return ArchivePolicy(
        enabled=file_format == "xlsx",
        max_uncompressed_size_bytes=int(
            privacy.get("max_uncompressed_size_bytes", 128 * 1024 * 1024)
        ),
        max_entries=int(privacy.get("max_archive_entries", 1_000)),
        max_nested_depth=0,
        max_compression_ratio=float(privacy.get("max_compression_ratio", 100.0)),
    )


@contextmanager
def open_export_csv(path: Path, encoding: str) -> Iterator[TextIO]:
    """Open a verified CSV or gzip-wrapped CSV without decoding cell values."""

    text_encoding = encoding + "-sig" if encoding.casefold() == "utf-8" else encoding
    if path.name.casefold().endswith(".csv.gz"):
        with gzip.open(path, "rt", encoding=text_encoding, newline="") as handle:
            yield handle
        return
    with path.open("r", encoding=text_encoding, newline="") as handle:
        yield handle


__all__ = ["export_file_policies", "open_export_csv"]
