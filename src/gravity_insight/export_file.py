"""Verified file policies for governed exports."""
from __future__ import annotations

from contextlib import contextmanager
import gzip
import io
import os
from pathlib import Path
import re
from typing import Any, Iterator, Mapping, TextIO

from .blob import ArchivePolicy, BlobPolicy, MagicSignature
from .export_models import ExportPrivacyContract, _export_error

_HEX = re.compile(r"^[0-9a-fA-F]{2,}$")


def xlsx_number_formats(root: Any | None) -> tuple[str, ...]:
    """Resolve format names from an already safety-parsed style tree."""
    if root is None:
        return ("General",)
    custom = {
        node.attrib.get("numFmtId"): node.attrib.get("formatCode", "")
        for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "numFmt"
    }
    if any(not isinstance(key, str) or not key.isdecimal() or int(key) < 164 for key in custom):
        raise ValueError("XLSX custom formats cannot override built-in formats")
    cell_formats = next((node for node in root if node.tag.rsplit("}", 1)[-1] == "cellXfs"), None)
    if cell_formats is None:
        raise ValueError("XLSX lacks cell formats")
    # Unknown built-ins, including dates, cannot satisfy the verified General format.
    return tuple(
        "General" if node.attrib.get("numFmtId", "0") == "0"
        else custom.get(node.attrib.get("numFmtId"), "")
        for node in cell_formats if node.tag.rsplit("}", 1)[-1] == "xf"
    )


def xlsx_cell_matches(cell: Any | None, value: str, spec: Mapping, formats: tuple[str, ...]) -> bool:
    if cell is None or not value or cell.attrib.get("t", "n") not in spec["cell_storage_types"]:
        return False
    style = cell.attrib.get("s", "0")
    index = int(style) if re.fullmatch(r"[0-9]{1,6}", style) else -1
    if not 0 <= index < len(formats) or formats[index] not in spec["number_formats"]:
        return False
    return spec["logical_type"] != "integer" or re.fullmatch(r"-?[0-9]+", value) is not None


def export_file_policies(
    contract: Any,
    root: Path,
    *,
    requested_columns: tuple[str, ...] | None = None,
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
    order: tuple[str, ...] = ()
    types: dict[str, Any] = {}
    if contract.privacy.get("column_order") == "request_code_lexicographic":
        codes = contract.privacy["request_columns"]
        labels = dict(zip(codes, allowed, strict=True))
        selected = requested_columns if requested_columns is not None else tuple(codes)
        if not selected or len(set(selected)) != len(selected) or set(selected) - set(codes):
            raise _export_error("invalid file projection", code="EXPORT_COLUMNS_INVALID", stage="headers")
        order = tuple(labels[code] for code in sorted(selected))
        allowed = order
        if requested_columns is not None:
            required = order
        types = {
            item["header"]: item for item in contract.privacy["file_schema"]["columns"]
            if item["header"] in allowed
        }
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
            column_order=order,
            column_types=types,
            temporal_semantics=contract.privacy.get("temporal_semantics"),
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
def open_export_csv(
    path: Path,
    encoding: str,
    *,
    extension: str | None = None,
    max_uncompressed_bytes: int | None = None,
) -> Iterator[TextIO]:
    """Open a verified CSV or gzip-wrapped CSV without decoding cell values."""

    text_encoding = encoding + "-sig" if encoding.casefold() == "utf-8" else encoding
    compressed = extension == ".csv.gz" if extension is not None else path.name.casefold().endswith(".csv.gz")
    if compressed:
        with gzip.open(path, "rb") as binary:
            with io.BufferedReader(_BoundedCsvReader(binary, max_uncompressed_bytes)) as bounded:
                with io.TextIOWrapper(bounded, encoding=text_encoding, newline="") as handle:
                    yield handle
        return
    with path.open("r", encoding=text_encoding, newline="") as handle:
        yield handle


class _BoundedCsvReader(io.RawIOBase):
    """Bound expanded bytes before text buffering, including concatenated members."""

    def __init__(self, source: Any, maximum: int | None) -> None:
        self._source = source
        self._remaining = maximum

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: Any) -> int:
        size = len(buffer)
        if self._remaining is not None:
            size = min(size, self._remaining + 1)
        chunk = self._source.read(size)
        if self._remaining is not None:
            self._remaining -= len(chunk)
            if self._remaining < 0:
                raise _export_error(
                    "CSV gzip expansion exceeds the governed size or ratio limit",
                    code="BLOB_SIZE_LIMIT",
                    stage="compression",
                )
        buffer[:len(chunk)] = chunk
        return len(chunk)


@contextmanager
def write_export_csv(path: Path, encoding: str, extension: str) -> Iterator[TextIO]:
    """Finish the declared container, including its trailer, before durable commit."""

    with path.open("wb") as raw:
        if extension == ".csv.gz":
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding=encoding, newline="") as text:
                    yield text
            raw.flush()
            os.fsync(raw.fileno())
        else:
            with io.TextIOWrapper(raw, encoding=encoding, newline="") as text:
                yield text
                text.flush()
                os.fsync(text.fileno())


__all__ = ["export_file_policies", "open_export_csv"]
