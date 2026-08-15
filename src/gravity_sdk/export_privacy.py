"""Streaming contract finalizers for verified exports."""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import re
import shutil
from typing import Mapping
import xml.etree.ElementTree as ET
import zipfile

from .blob import BlobFinalizationResult, BlobMetadata, BlobTransferError
from .executor import _redact
from .export_models import (
    ExportPrivacyContract, _assert_exportable_classification, _export_error,
)

class ExportPrivacyFinalizer:
    """Validate actual tabular schema and remove only contracted credentials."""

    def __init__(self, contract: ExportPrivacyContract) -> None:
        self._contract = contract

    def finalize(
        self,
        source_path: Path,
        output_path: Path,
        metadata: BlobMetadata,
    ) -> BlobFinalizationResult:
        _assert_exportable_classification(self._contract)
        if self._contract.format == "csv":
            if metadata.extension != ".csv":
                raise _export_error(
                    "CSV finalizer received a non-CSV blob",
                    code="EXPORT_FORMAT_UNSUPPORTED",
                    stage="finalizer",
                )
            return self._finalize_csv(source_path, output_path)
        if self._contract.format == "xlsx":
            if metadata.extension != ".xlsx":
                raise _export_error(
                    "XLSX finalizer received a non-XLSX blob",
                    code="EXPORT_FORMAT_UNSUPPORTED",
                    stage="finalizer",
                )
            return self._finalize_xlsx(source_path, output_path)
        if metadata.extension not in {".jsonl", ".ndjson"}:
            raise _export_error(
                "JSONL finalizer received an unsupported extension",
                code="EXPORT_FORMAT_UNSUPPORTED",
                stage="finalizer",
            )
        return self._finalize_jsonl(source_path, output_path)

    def _finalize_csv(
        self,
        source_path: Path,
        output_path: Path,
    ) -> BlobFinalizationResult:
        try:
            with source_path.open(
                "r",
                encoding=self._contract.encoding + "-sig"
                if self._contract.encoding.casefold() == "utf-8"
                else self._contract.encoding,
                newline="",
            ) as source_handle:
                reader = csv.DictReader(source_handle, delimiter=self._contract.delimiter)
                header = tuple(reader.fieldnames or ())
                _validate_actual_schema(header, self._contract)
                output_header = _redacted_columns(header, self._contract)
                if not output_header:
                    raise _export_error(
                        "contract projection removed every export column",
                        code="EXPORT_SCHEMA_MISMATCH",
                        stage="finalizer",
                    )
                rows = 0
                with output_path.open(
                    "w",
                    encoding=self._contract.encoding,
                    newline="",
                ) as output_handle:
                    writer = csv.DictWriter(
                        output_handle,
                        fieldnames=list(output_header),
                        delimiter=self._contract.delimiter,
                        extrasaction="raise",
                        lineterminator="\n",
                    )
                    writer.writeheader()
                    for row in reader:
                        if None in row or any(value is None for value in row.values()):
                            raise _export_error(
                                "CSV row width does not match its header",
                                code="EXPORT_SCHEMA_MISMATCH",
                                stage="finalizer",
                                details={"line": reader.line_num},
                            )
                        projected = _redact(
                            dict(row),
                            self._contract.redact_fields,
                            allow_contracted_identifiers=(
                                self._contract.allow_contracted_identifiers
                            ),
                        )
                        if not isinstance(projected, Mapping):
                            raise _export_error(
                                "CSV contract projection did not return an object",
                                code="EXPORT_SCHEMA_MISMATCH",
                                stage="finalizer",
                            )
                        writer.writerow({column: projected[column] for column in output_header})
                        rows += 1
                    output_handle.flush()
                    os.fsync(output_handle.fileno())
        except BlobTransferError:
            raise
        except (LookupError, UnicodeError, csv.Error, OSError) as exc:
            raise _export_error(
                "CSV export could not be parsed and finalized safely",
                code="EXPORT_FORMAT_INVALID",
                stage="finalizer",
            ) from exc
        return BlobFinalizationResult(schema=output_header, rows_processed=rows)

    def _finalize_jsonl(
        self,
        source_path: Path,
        output_path: Path,
    ) -> BlobFinalizationResult:
        rows = 0
        observed_columns: list[str] = []
        observed_set: set[str] = set()
        try:
            with source_path.open("r", encoding=self._contract.encoding) as source_handle:
                with output_path.open("w", encoding=self._contract.encoding) as output_handle:
                    for line_number, line in enumerate(source_handle, start=1):
                        if not line.strip():
                            continue
                        value = json.loads(line)
                        if not isinstance(value, Mapping):
                            raise _export_error(
                                "JSONL export rows must be objects",
                                code="EXPORT_SCHEMA_MISMATCH",
                                stage="finalizer",
                                details={"line": line_number},
                            )
                        header = tuple(str(key) for key in value)
                        _validate_actual_schema(header, self._contract)
                        projected = _redact(
                            dict(value),
                            self._contract.redact_fields,
                            allow_contracted_identifiers=(
                                self._contract.allow_contracted_identifiers
                            ),
                        )
                        if not isinstance(projected, Mapping) or not projected:
                            raise _export_error(
                                "contract projection removed every JSONL column",
                                code="EXPORT_SCHEMA_MISMATCH",
                                stage="finalizer",
                                details={"line": line_number},
                            )
                        for key in projected:
                            if key not in observed_set:
                                observed_columns.append(key)
                                observed_set.add(key)
                        output_handle.write(
                            json.dumps(
                                projected,
                                ensure_ascii=True,
                                separators=(",", ":"),
                                sort_keys=False,
                            )
                            + "\n"
                        )
                        rows += 1
                    if rows == 0:
                        raise _export_error(
                            "empty JSONL has no verifiable schema",
                            code="EXPORT_SCHEMA_MISMATCH",
                            stage="finalizer",
                        )
                    output_handle.flush()
                    os.fsync(output_handle.fileno())
        except BlobTransferError:
            raise
        except (LookupError, UnicodeError, json.JSONDecodeError, OSError) as exc:
            raise _export_error(
                "JSONL export could not be parsed and finalized safely",
                code="EXPORT_FORMAT_INVALID",
                stage="finalizer",
            ) from exc
        return BlobFinalizationResult(
            schema=tuple(observed_columns),
            rows_processed=rows,
        )

    def _finalize_xlsx(
        self,
        source_path: Path,
        output_path: Path,
    ) -> BlobFinalizationResult:
        try:
            with zipfile.ZipFile(source_path) as archive:
                worksheet_names = _xlsx_worksheet_names(archive)
                shared_strings = _xlsx_shared_strings(archive)
                schemas: list[tuple[str, ...]] = []
                rows = 0
                for worksheet_name in worksheet_names:
                    header, worksheet_rows = _xlsx_sheet_schema(
                        archive,
                        worksheet_name,
                        shared_strings,
                    )
                    _validate_actual_schema(header, self._contract)
                    output_header = _redacted_columns(header, self._contract)
                    if output_header != header:
                        raise _export_error(
                            "XLSX redaction would require rewriting the workbook",
                            code="EXPORT_SCHEMA_MISMATCH",
                            stage="finalizer",
                        )
                    schemas.append(header)
                    rows += worksheet_rows
                if any(schema != schemas[0] for schema in schemas[1:]):
                    raise _export_error(
                        "XLSX worksheets do not share one contracted schema",
                        code="EXPORT_SCHEMA_MISMATCH",
                        stage="finalizer",
                    )
            shutil.copyfile(source_path, output_path)
            with output_path.open("rb+") as output_handle:
                output_handle.flush()
                os.fsync(output_handle.fileno())
        except BlobTransferError:
            raise
        except (ET.ParseError, KeyError, OSError, ValueError, zipfile.BadZipFile) as exc:
            raise _export_error(
                "XLSX export could not be parsed and finalized safely",
                code="EXPORT_FORMAT_INVALID",
                stage="finalizer",
            ) from exc
        return BlobFinalizationResult(
            schema=schemas[0],
            rows_processed=rows,
            details={"worksheets": len(schemas)},
        )


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
) -> tuple[tuple[str, ...], int]:
    root = _xlsx_xml_root(archive, name)
    header: tuple[str, ...] | None = None
    rows = 0
    for row in (node for node in root.iter() if _local_name(node.tag) == "row"):
        values = _xlsx_row_values(row, shared_strings)
        if header is None:
            if not values:
                continue
            last_column = max(values)
            header = tuple(values.get(index, "").strip() for index in range(last_column + 1))
        elif values:
            if max(values) >= len(header):
                raise _export_error(
                    "XLSX row extends beyond its contracted header",
                    code="EXPORT_SCHEMA_MISMATCH",
                    stage="finalizer",
                )
            if any(value != "" for value in values.values()):
                rows += 1
    if header is None:
        raise _export_error(
            "XLSX worksheet has no header row",
            code="EXPORT_SCHEMA_MISMATCH",
            stage="finalizer",
        )
    return header, rows


def _xlsx_row_values(
    row: ET.Element,
    shared_strings: tuple[str, ...],
) -> dict[int, str]:
    values: dict[int, str] = {}
    for cell in (node for node in row if _local_name(node.tag) == "c"):
        reference = str(cell.attrib.get("r", ""))
        match = _CELL_REFERENCE.fullmatch(reference)
        if match is None:
            raise ValueError("invalid XLSX cell reference")
        column_index = _xlsx_column_index(match.group(1))
        if column_index in values:
            raise ValueError("duplicate XLSX cell reference")
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
) -> None:
    if not actual or any(not column for column in actual):
        raise _export_error(
            "export has no complete actual schema",
            code="EXPORT_SCHEMA_MISMATCH",
            stage="finalizer",
        )
    if len(set(actual)) != len(actual):
        raise _export_error(
            "export schema contains duplicate columns",
            code="EXPORT_SCHEMA_MISMATCH",
            stage="finalizer",
        )
    unknown = sorted(set(actual) - set(contract.allowed_columns))
    missing = sorted(set(contract.required_columns) - set(actual))
    if unknown or missing:
        raise _export_error(
            "actual export schema violates the privacy contract",
            code="EXPORT_SCHEMA_MISMATCH",
            stage="finalizer",
            details={"unknown_columns": unknown, "missing_required_columns": missing},
        )


def _redacted_columns(
    actual: tuple[str, ...],
    contract: ExportPrivacyContract,
) -> tuple[str, ...]:
    sentinel = {column: None for column in actual}
    projected = _redact(
        sentinel,
        contract.redact_fields,
        allow_contracted_identifiers=contract.allow_contracted_identifiers,
    )
    if not isinstance(projected, Mapping):
        raise _export_error(
            "contract projection did not return an object schema",
            code="EXPORT_SCHEMA_MISMATCH",
            stage="finalizer",
        )
    return tuple(column for column in actual if column in projected)
