"""Streaming contract finalizers for verified exports."""
from __future__ import annotations

import csv
import gzip
import json
import os
from pathlib import Path
import shutil
from typing import Mapping
import xml.etree.ElementTree as ET
import zipfile
import zlib

from .blob import ArchivePolicy, BlobFinalizationResult, BlobMetadata, BlobTransferError
from .executor import _redact
from .export_file import (
    open_export_csv, write_export_csv, xlsx_number_formats, _validate_actual_schema,
    _xlsx_worksheet_names, _xlsx_shared_strings, _xlsx_xml_root, _xlsx_sheet_schema,
)
from .export_models import (
    ExportPrivacyContract, _assert_exportable_classification, _export_error,
)

class ExportPrivacyFinalizer:
    """Validate actual tabular schema and remove only contracted credentials."""

    def __init__(
        self, contract: ExportPrivacyContract, *, archive_policy: ArchivePolicy | None = None,
    ) -> None:
        self._contract = contract
        self._archive_policy = archive_policy or ArchivePolicy()

    def finalize(
        self,
        source_path: Path,
        output_path: Path,
        metadata: BlobMetadata,
    ) -> BlobFinalizationResult:
        _assert_exportable_classification(self._contract)
        if self._contract.scope_contract and (self._contract.user_event_scope is None or self._contract.user_event_scope.job_id is None):
            raise _export_error("a task-bound scope is required before finalization", code="EXPORT_JOB_INVALID", stage="scope_receipt")
        if self._contract.format == "csv":
            if metadata.extension not in {".csv", ".csv.gz"}:
                raise _export_error(
                    "CSV finalizer received a non-CSV blob",
                    code="EXPORT_FORMAT_UNSUPPORTED",
                    stage="finalizer",
                )
            return self._finalize_csv(source_path, output_path, metadata)
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
        metadata: BlobMetadata,
    ) -> BlobFinalizationResult:
        rows = 0
        reader = None
        try:
            ratio_maximum = int(
                metadata.size_bytes * self._archive_policy.max_compression_ratio
            )
            if self._archive_policy.max_uncompressed_size_bytes <= ratio_maximum:
                maximum = self._archive_policy.max_uncompressed_size_bytes
                limit_reason = "gzip_expanded_byte_budget"
            else:
                maximum = ratio_maximum
                limit_reason = "gzip_compression_ratio_budget"
            # Transfer staging names are .part/.final; only verified metadata binds the container.
            with open_export_csv(
                source_path, self._contract.encoding,
                extension=metadata.extension, max_uncompressed_bytes=maximum,
                limit_reason=limit_reason,
            ) as source_handle:
                reader = csv.DictReader(source_handle, delimiter=self._contract.delimiter, strict=True)
                header = tuple(reader.fieldnames or ())
                _validate_actual_schema(header, self._contract, stage="headers")
                output_header = _redacted_columns(header, self._contract)
                if not output_header:
                    raise _export_error(
                        "contract projection removed every export column",
                        code="EXPORT_SCHEMA_MISMATCH",
                        stage="finalizer",
                    )
                with write_export_csv(
                    output_path, self._contract.encoding, metadata.extension,
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
                                stage="csv_framing",
                                details={"line": reader.line_num, "rows_processed": rows},
                            )
                        projected = _redact(
                            dict(row),
                            self._contract.redact_fields,
                            allow_contracted_identifiers=(
                                self._contract.contracted_identifiers_allowed
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
        except BlobTransferError:
            raise
        except (gzip.BadGzipFile, EOFError, zlib.error, LookupError, UnicodeError, csv.Error, OSError) as exc:
            stage = _csv_failure_stage(exc)
            raise _export_error(
                "CSV export could not be parsed and finalized safely",
                code="LOCAL_IO_ERROR" if stage == "local_io" else "EXPORT_FORMAT_INVALID",
                stage=stage,
                details={"line": reader.reader.line_num if reader is not None else 0, "rows_processed": rows},
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
                                self._contract.contracted_identifiers_allowed
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
                if (self._contract.column_types or self._contract.scope_contract) and len(worksheet_names) != 1:
                    raise _export_error("typed export requires one worksheet", code="EXPORT_SCHEMA_MISMATCH", stage="headers")
                shared_strings = _xlsx_shared_strings(archive)
                styles = _xlsx_xml_root(archive, "xl/styles.xml") if self._contract.column_types and "xl/styles.xml" in archive.namelist() else None
                number_formats = xlsx_number_formats(styles)
                schemas: list[tuple[str, ...]] = []
                rows = 0
                empty_counts = {header: 0 for header in self._contract.column_types}
                for worksheet_name in worksheet_names:
                    header, worksheet_rows = _xlsx_sheet_schema(
                        archive,
                        worksheet_name,
                        shared_strings,
                        contract=self._contract,
                        empty_counts=empty_counts,
                        number_formats=number_formats,
                    )
                    _validate_actual_schema(header, self._contract, stage="headers")
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
        except (ET.ParseError, KeyError, OSError, ValueError, zipfile.BadZipFile):
            raise _export_error(
                "XLSX export could not be parsed and finalized safely",
                code="EXPORT_FORMAT_INVALID",
                stage="xlsx_framing",
            ) from None
        return BlobFinalizationResult(
            schema=schemas[0],
            rows_processed=rows,
            details={
                "worksheets": len(schemas),
                **({"empty_values_by_column": empty_counts,
                    "temporal_semantics": self._contract.temporal_semantics}
                   if self._contract.column_types else {}),
                **({"user_event_scope_verification": "verified"} if self._contract.user_event_scope is not None else {}),
            },
        )


def _csv_failure_stage(error: Exception) -> str:
    if isinstance(error, (gzip.BadGzipFile, EOFError, zlib.error)):
        return "compression"
    if isinstance(error, (LookupError, UnicodeError)):
        return "encoding"
    if isinstance(error, csv.Error):
        return "csv_framing"
    return "local_io"


def _redacted_columns(
    actual: tuple[str, ...],
    contract: ExportPrivacyContract,
) -> tuple[str, ...]:
    sentinel = {column: None for column in actual}
    projected = _redact(
        sentinel,
        contract.redact_fields,
        allow_contracted_identifiers=contract.contracted_identifiers_allowed,
    )
    if not isinstance(projected, Mapping):
        raise _export_error(
            "contract projection did not return an object schema",
            code="EXPORT_SCHEMA_MISMATCH",
            stage="finalizer",
        )
    return tuple(column for column in actual if column in projected)
