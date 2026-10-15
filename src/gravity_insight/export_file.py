"""Verified file policies for governed exports."""
from __future__ import annotations

from contextlib import contextmanager
import gzip
import io
import os
from pathlib import Path
import re
from typing import Any, Iterator, Mapping, TextIO
import xml.etree.ElementTree as ET
import zipfile

from .blob import ArchivePolicy, BlobPolicy, MagicSignature
from .export_models import ExportPrivacyContract, _export_error, _user_event_scope_error
from .contracts.user_event_export_scope import UserEventScopeError

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
            scope_contract=contract.privacy.get("file_schema", {}).get("scope_contract"),
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
    limit_reason: str | None = None,
) -> Iterator[TextIO]:
    """Open a verified CSV or gzip-wrapped CSV without decoding cell values."""

    text_encoding = encoding + "-sig" if encoding.casefold() == "utf-8" else encoding
    compressed = extension == ".csv.gz" if extension is not None else path.name.casefold().endswith(".csv.gz")
    if compressed:
        with gzip.open(path, "rb") as binary:
            with io.BufferedReader(
                _BoundedCsvReader(binary, max_uncompressed_bytes, limit_reason)
            ) as bounded:
                with io.TextIOWrapper(bounded, encoding=text_encoding, newline="") as handle:
                    yield handle
        return
    with path.open("r", encoding=text_encoding, newline="") as handle:
        yield handle


class _BoundedCsvReader(io.RawIOBase):
    """Bound expanded bytes before text buffering, including concatenated members."""

    def __init__(
        self, source: Any, maximum: int | None, limit_reason: str | None,
    ) -> None:
        self._source = source
        self._remaining = maximum
        self._limit_reason = limit_reason

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
                    details={"reason": self._limit_reason},
                    next_action=(
                        "Split the same full interval into adjacent, non-overlapping "
                        "closed date windows; keep App, event, columns, and empty "
                        "conditions unchanged; evaluate and reconcile every child window."
                    ),
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


_CELL_REFERENCE = re.compile(r"^([A-Z]+)[1-9][0-9]*$")

_FORBIDDEN_XLSX_PARTS = (
    "xl/activex/",
    "xl/comments",
    "xl/connections.xml",
    "xl/embeddings/",
    "xl/externallinks/",
    "xl/vbaproject.bin",
)

def _xlsx_worksheet_names(archive: zipfile.ZipFile) -> tuple[str, ...]:
    names = tuple(info.filename for info in archive.infolist() if not info.is_dir())
    lowered = tuple(name.casefold() for name in names)
    if any(
        name == forbidden or name.startswith(forbidden)
        for name in lowered
        for forbidden in _FORBIDDEN_XLSX_PARTS
    ):
        raise _export_error(
            "XLSX contains an unsupported active or external part",
            code="EXPORT_FORMAT_INVALID",
            stage="finalizer",
        )
    worksheets = tuple(
        name
        for name in names
        if name.casefold().startswith("xl/worksheets/")
        and name.casefold().endswith(".xml")
    )
    if not worksheets:
        raise _export_error(
            "XLSX contains no worksheet",
            code="EXPORT_FORMAT_INVALID",
            stage="finalizer",
        )
    return worksheets

def _xlsx_shared_strings(archive: zipfile.ZipFile) -> tuple[str, ...]:
    name = next(
        (
            info.filename
            for info in archive.infolist()
            if info.filename.casefold() == "xl/sharedstrings.xml"
        ),
        None,
    )
    if name is None:
        return ()
    root = _xlsx_xml_root(archive, name)
    return tuple(
        "".join(node.text or "" for node in item.iter() if _local_name(node.tag) == "t")
        for item in root.iter()
        if _local_name(item.tag) == "si"
    )

def _xlsx_sheet_schema(
    archive: zipfile.ZipFile,
    name: str,
    shared_strings: tuple[str, ...],
    *,
    contract: ExportPrivacyContract | None = None,
    empty_counts: dict[str, int] | None = None,
    number_formats: tuple[str, ...] = (),
) -> tuple[tuple[str, ...], int]:
    root = _xlsx_xml_root(archive, name)
    header: tuple[str, ...] | None = None
    rows = 0
    for row in (node for node in root.iter() if _local_name(node.tag) == "row"):
        typed = _xlsx_requires_typed(contract)
        values = _xlsx_row_values(row, shared_strings, reject_formulas=typed)
        if header is None:
            if not values:
                continue
            last_column = max(values)
            header = tuple(values.get(index, "") for index in range(last_column + 1))
            if not typed:
                header = tuple(value.strip() for value in header)
            if contract is not None:
                _validate_actual_schema(header, contract, stage="headers")
        elif values:
            _validate_xlsx_cells(row, values, header, contract, empty_counts, rows, number_formats)
            if any(value != "" for value in values.values()):
                _validate_xlsx_scope(values, header, contract)
                rows += 1
    if header is None:
        raise _export_error(
            "XLSX worksheet has no header row",
            code="EXPORT_SCHEMA_MISMATCH",
            stage="finalizer",
        )
    return header, rows

def _xlsx_requires_typed(contract: ExportPrivacyContract | None) -> bool:
    return bool(contract and (contract.column_types or contract.scope_contract))


def _validate_xlsx_scope(values: Mapping[int, str], header: tuple[str, ...], contract: ExportPrivacyContract | None) -> None:
    if contract is not None and contract.user_event_scope is not None:
        try:
            contract.user_event_scope.verify_row(*(values.get(header.index(name), "") for name in ("客户(client_id)", "事件发生时间", "事件")))
        except UserEventScopeError as exc:
            raise _user_event_scope_error(exc, "scope_validation") from None


def _validate_xlsx_cells(
    row: ET.Element,
    values: Mapping[int, str],
    header: tuple[str, ...],
    contract: ExportPrivacyContract | None,
    empty_counts: dict[str, int] | None,
    rows: int,
    number_formats: tuple[str, ...],
) -> None:
    if max(values) >= len(header):
        raise _export_error(
            "XLSX row extends beyond its contracted header",
            code="EXPORT_SCHEMA_MISMATCH", stage="headers",
        )
    if contract is None or not contract.column_types:
        return
    cells = {
        _xlsx_column_index(_CELL_REFERENCE.fullmatch(cell.attrib["r"]).group(1)): cell
        for cell in row if _local_name(cell.tag) == "c"
    }
    for index, name in enumerate(header):
        spec = contract.column_types[name]
        cell = cells.get(index)
        value = values.get(index, "")
        empty = value == ""
        if empty and spec.get("nullable") is True:
            if empty_counts is not None:
                empty_counts[name] += 1
            continue
        if not xlsx_cell_matches(cell, value, spec, number_formats):
            raise _export_error(
                "XLSX cell violates its contracted storage or value type",
                code="EXPORT_TYPE_MISMATCH", stage="cell_types",
                details={"column": index + 1, "rows_processed": rows},
            )

def _xlsx_row_values(
    row: ET.Element,
    shared_strings: tuple[str, ...],
    *, reject_formulas: bool = False,
) -> dict[int, str]:
    values: dict[int, str] = {}
    for cell in (node for node in row if _local_name(node.tag) == "c"):
        reference = str(cell.attrib.get("r", ""))
        match = _CELL_REFERENCE.fullmatch(reference)
        if match is None:
            raise ValueError("invalid XLSX cell reference")
        column_index = _xlsx_column_index(match.group(1))
        if column_index in values or (reject_formulas and any(_local_name(node.tag) == "f" for node in cell)):
            raise ValueError("duplicate or formula XLSX cell")
        values[column_index] = _xlsx_cell_text(cell, shared_strings)
    return values

def _xlsx_xml_root(archive: zipfile.ZipFile, name: str) -> ET.Element:
    data = archive.read(name)
    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise ValueError("XLSX XML declarations are unsafe")
    return ET.fromstring(data)

def _xlsx_cell_text(cell: ET.Element, shared_strings: tuple[str, ...]) -> str:
    cell_type = cell.attrib.get("t", "")
    if cell_type == "inlineStr":
        return "".join(
            node.text or "" for node in cell.iter() if _local_name(node.tag) == "t"
        )
    value = next(
        (node.text or "" for node in cell if _local_name(node.tag) == "v"),
        "",
    )
    if cell_type != "s":
        return value
    index = int(value)
    if index < 0 or index >= len(shared_strings):
        raise ValueError("XLSX shared string index is invalid")
    return shared_strings[index]

def _xlsx_column_index(value: str) -> int:
    result = 0
    for character in value:
        result = result * 26 + (ord(character) - ord("A") + 1)
    if not 1 <= result <= 16_384:
        raise ValueError("XLSX column is outside the spreadsheet limit")
    return result - 1

def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1]

def _validate_actual_schema(
    actual: tuple[str, ...],
    contract: ExportPrivacyContract,
    *,
    stage: str = "finalizer",
) -> None:
    if not actual or any(not column for column in actual):
        raise _export_error(
            "export has no complete actual schema",
            code="EXPORT_SCHEMA_MISMATCH",
            stage=stage,
        )
    if len(set(actual)) != len(actual):
        raise _export_error(
            "export schema contains duplicate columns",
            code="EXPORT_SCHEMA_MISMATCH",
            stage=stage,
        )
    unknown = sorted(set(actual) - set(contract.allowed_columns))
    missing = sorted(set(contract.required_columns) - set(actual))
    if unknown or missing:
        raise _export_error(
            "actual export schema violates the privacy contract",
            code="EXPORT_SCHEMA_MISMATCH",
            stage=stage,
            details=(
                {"unknown_column_count": len(unknown), "missing_column_count": len(missing)}
                if contract.column_types else
                {"unknown_columns": unknown, "missing_required_columns": missing}
            ),
        )
    if contract.column_order and actual != tuple(name for name in contract.column_order if name in actual):
        raise _export_error(
            "actual export column order violates the projection contract",
            code="EXPORT_SCHEMA_MISMATCH", stage=stage,
        )


__all__ = ["export_file_policies", "open_export_csv"]
