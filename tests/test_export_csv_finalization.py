from __future__ import annotations

import csv
import contextlib
from dataclasses import replace
import gzip
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gravity_insight.blob import ArchivePolicy
from gravity_insight.cli import main
from gravity_insight.contracts.envelope_obligations import EnvelopeObligations
from gravity_insight.export_contracts import ExportContractRegistry
from gravity_insight.export_file import export_file_policies
from gravity_insight.export_models import ExportJobSnapshot, ExportState
from gravity_insight.export_results import export_result_envelope
from tests.test_gravity_insight_export_integration import CONTRACT_PATH
from tests.test_gravity_insight_export_runtime import (
    FakeBlobTransport, FakeClock, FakeGateway, FakeResponse, blob_policy,
    creation_request, orchestrator_for, source_for,
)


OPERATION = "export.analysis.origin_event.start"
CONTRACT = ExportContractRegistry.from_file(CONTRACT_PATH).get(OPERATION)
HEADERS = tuple(CONTRACT.privacy["required_columns"])


def synthetic_csv():
    # Match the observed BOM/five-text-cell/quoted-JSON shape, never its values.
    rows = [
        [f"synthetic-{index}", "2026-01-01 00:00:00", "2026-01-02 01:02:03",
         "fixture_level", json.dumps({"level": index, "note": 'a,b "quoted" \u6d4b\u8bd5',
                                      "nested": {"text": "x" * 500}}, ensure_ascii=False)]
        for index in range(1, 4)
    ]
    stream = io.StringIO(newline="")
    csv.writer(stream, lineterminator="\n").writerows([HEADERS, *rows])
    return stream.getvalue().encode("utf-8-sig"), rows


def run_download(root, data, *, archive_policy=None, response=None, privacy_override=None):
    source = replace(source_for(data),
                     url="https://files.example.test/signed/report.csv.gz?token=secret",
                     declared_path="/signed/report.csv.gz")
    gateway = FakeGateway(ExportJobSnapshot("job-1", ExportState.QUEUED),
                          [ExportJobSnapshot("job-1", ExportState.READY, source)])
    transport = FakeBlobTransport([response or FakeResponse(data)])
    governed_policy, privacy = export_file_policies(CONTRACT, root)
    policy = replace(blob_policy(root),
                     allowed_extensions=governed_policy.allowed_extensions,
                     magic_signatures=governed_policy.magic_signatures,
                     mime_types_by_extension=governed_policy.mime_types_by_extension,
                     max_declared_size_bytes=governed_policy.max_declared_size_bytes,
                     max_stream_size_bytes=governed_policy.max_stream_size_bytes,
                     archive_policy=archive_policy or governed_policy.archive_policy)
    result = orchestrator_for(gateway, transport, FakeClock()).start(
        creation_request(HEADERS), "events.csv.gz", policy, privacy_override or privacy)
    return result, export_result_envelope(OPERATION, result)


class ExportCsvFinalizationTests(unittest.TestCase):
    def test_staged_gzip_commits_full_synthetic_custom_event_file(self):
        raw, rows = synthetic_csv()
        compressed = gzip.compress(raw)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, envelope = run_download(root, compressed)
            self.assertEqual(ExportState.COMMITTED, result.state, envelope)
            output = (root / "events.csv.gz").read_bytes()
            parsed = list(csv.reader(io.StringIO(gzip.decompress(output).decode("utf-8-sig"))))
            self.assertEqual([list(HEADERS), *rows], parsed)
            self.assertEqual(("complete", len(rows)),
                             (envelope["completion_status"], envelope["file"]["rows"]))
            self.assertEqual(hashlib.sha256(output).hexdigest(), result.receipt.committed_sha256)
            self.assertEqual([root / "events.csv.gz"], list(root.iterdir()))
            obligations = EnvelopeObligations.from_dict(envelope["obligations"])
            self.assertEqual("complete", obligations.data_completeness.state.value)

    def test_corrupt_gzip_trailer_never_commits_or_reports_complete(self):
        compressed = bytearray(gzip.compress(synthetic_csv()[0]))
        compressed[-8] ^= 1
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, envelope = run_download(root, bytes(compressed))
            self.assertEqual((ExportState.FAILED, "partial", False),
                             (result.state, envelope["completion_status"], envelope["ok"]))
            self.assertEqual("compression", envelope["diagnostics"]["stage"])
            self.assertNotIn("COMMITTED", envelope["history"])
            self.assertEqual([], list(root.iterdir()))
            obligations = EnvelopeObligations.from_dict(envelope["obligations"])
            self.assertEqual(("failed", "unknown", "CONTRACT_CHANGED"), (
                obligations.execution_status.state.value, obligations.data_completeness.state.value,
                obligations.diagnostic_evidence.code))

    def test_schema_and_encoding_diagnostics_do_not_expose_values(self):
        cases = [
            (b"\xffPRIVATE-CELL-VALUE", "encoding"),
            (b"PRIVATE-CELL-VALUE\nvalue\n", "headers"),
            (synthetic_csv()[0] + b"PRIVATE-CELL-VALUE\n", "csv_framing"),
        ]
        for raw, stage in cases:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                result, envelope = run_download(root, gzip.compress(raw))
                self.assertEqual("CONTRACT_CHANGED", envelope["error"]["code"])
                self.assertEqual(stage, envelope["diagnostics"]["stage"])
                self.assertNotIn("PRIVATE-CELL-VALUE", json.dumps(envelope))
                self.assertIsNone(result.receipt)
                self.assertEqual([], list(root.iterdir()))

    def test_unclosed_quote_is_framing_failure_not_a_partial_success(self):
        raw = synthetic_csv()[0] + b'"PRIVATE-CELL-VALUE'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result, envelope = run_download(root, gzip.compress(raw))
            self.assertEqual({"stage": "csv_framing", "reason": "invalid_csv",
                              "line": 5, "rows_processed": 3}, envelope["diagnostics"])
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch("gravity_insight.cli.dispatch_command", return_value=envelope):
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    exit_code = main(["export", "list"])
            self.assertEqual((3, ""), (exit_code, stdout.getvalue()))
            self.assertEqual(envelope["diagnostics"], json.loads(stderr.getvalue())["diagnostics"])
            self.assertNotIn("PRIVATE-CELL-VALUE", stderr.getvalue())
            self.assertEqual([], list(root.iterdir()))

    def test_gzip_eof_and_http_byte_completeness_are_separate_diagnostics(self):
        compressed = gzip.compress(synthetic_csv()[0])
        truncated = compressed[:-5]
        response = FakeResponse(truncated)
        response.headers["Content-Length"] = str(len(compressed))
        for data, http_response, stage in (
            (truncated, None, "compression"),
            (compressed, response, "completeness"),
        ):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                result, envelope = run_download(root, data, response=http_response)
                self.assertEqual(stage, envelope["diagnostics"]["stage"])
                self.assertFalse(envelope["ok"])
                self.assertNotEqual("complete", envelope["completion_status"])
                self.assertEqual([], list(root.iterdir()))

    def test_gzip_expansion_obeys_both_policy_budgets(self):
        raw = synthetic_csv()[0]
        policies = (
            ArchivePolicy(max_uncompressed_size_bytes=len(raw) - 1),
            ArchivePolicy(max_compression_ratio=1),
        )
        for policy in policies:
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                result, envelope = run_download(root, gzip.compress(raw), archive_policy=policy)
                self.assertEqual("BLOB_SIZE_LIMIT", result.error.code)
                self.assertEqual("gzip_expansion_limit", envelope["diagnostics"]["reason"])
                self.assertEqual([], list(root.iterdir()))

    def test_gzip_projection_still_removes_contracted_credentials(self):
        _, rows = synthetic_csv()
        stream = io.StringIO(newline="")
        csv.writer(stream).writerows([
            [*HEADERS, "password"], *[[*row, "DO-NOT-PUBLISH"] for row in rows],
        ])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, privacy = export_file_policies(CONTRACT, root)
            privacy = replace(privacy, allowed_columns=(*HEADERS, "password"),
                              redact_fields=("password",))
            result, envelope = run_download(
                root, gzip.compress(stream.getvalue().encode("utf-8-sig")), privacy_override=privacy)
            self.assertTrue(envelope["ok"], envelope)
            text = gzip.decompress((root / "events.csv.gz").read_bytes()).decode("utf-8")
            self.assertNotIn("DO-NOT-PUBLISH", text)
            self.assertEqual([list(HEADERS), *rows], list(csv.reader(io.StringIO(text))))
