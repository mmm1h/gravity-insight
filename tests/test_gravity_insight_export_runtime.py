from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import tempfile
import unittest

try:
    from gravity_sdk.blob import (
        AuthorizedBlobSource,
        BlobMetadata,
        BlobPolicy,
        BlobTransferError,
        MagicSignature,
        SafeBlobTransfer,
    )
    from gravity_sdk.export_runtime import (
        ExportCreationRequest,
        ExportJobSnapshot,
        ExportOrchestrator,
        ExportPollingPolicy,
        ExportPrivacyContract,
        ExportPrivacyFinalizer,
        ExportRuntimeError,
        ExportState,
    )
except ModuleNotFoundError:  # source checkout without an editable install
    from gravity_sdk.blob import (
        AuthorizedBlobSource,
        BlobMetadata,
        BlobPolicy,
        BlobTransferError,
        MagicSignature,
        SafeBlobTransfer,
    )
    from gravity_sdk.export_runtime import (
        ExportCreationRequest,
        ExportJobSnapshot,
        ExportOrchestrator,
        ExportPollingPolicy,
        ExportPrivacyContract,
        ExportPrivacyFinalizer,
        ExportRuntimeError,
        ExportState,
    )


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, data: bytes):
        self.status_code = 200
        self.headers = {
            "Content-Type": "text/csv",
            "Content-Length": str(len(data)),
            "ETag": '"export-v1"',
        }
        self._data = data
        self.closed = False

    def iter_content(self, *, chunk_size):
        midpoint = max(1, len(self._data) // 2)
        yield self._data[:midpoint]
        yield self._data[midpoint:]

    def close(self):
        self.closed = True


class FakeBlobTransport:
    def __init__(self, responses=()):
        self.responses = list(responses)
        self.calls = []

    def open_download(self, url, *, headers, timeout):
        self.calls.append((url, dict(headers), timeout))
        if not self.responses:
            raise AssertionError("unexpected download")
        return self.responses.pop(0)

    def upload(self, *args, **kwargs):
        raise AssertionError("export tests never upload")


class FakeGateway:
    def __init__(
        self,
        create_snapshot=None,
        statuses=(),
        *,
        create_error=None,
        supports_cancel=False,
        cancel_snapshot=None,
    ):
        self.create_snapshot = create_snapshot
        self.statuses = list(statuses)
        self.create_error = create_error
        self.supports_cancel = supports_cancel
        self.cancel_snapshot = cancel_snapshot
        self.create_calls = []
        self.status_calls = []
        self.cancel_calls = []
        self.create_timeouts = []
        self.status_timeouts = []
        self.cancel_timeouts = []
        self.last_status = None

    def create(self, request, *, timeout_seconds):
        self.create_calls.append(request)
        self.create_timeouts.append(timeout_seconds)
        if self.create_error is not None:
            raise self.create_error
        return self.create_snapshot

    def status(self, job_id, *, timeout_seconds):
        self.status_calls.append(job_id)
        self.status_timeouts.append(timeout_seconds)
        if self.statuses:
            self.last_status = self.statuses.pop(0)
        if self.last_status is None:
            raise AssertionError("unexpected status call")
        return self.last_status

    def cancel(self, job_id, *, timeout_seconds):
        self.cancel_calls.append(job_id)
        self.cancel_timeouts.append(timeout_seconds)
        if self.cancel_snapshot is None:
            raise AssertionError("unexpected cancel call")
        return self.cancel_snapshot


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.value

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.value += seconds


def privacy_contract(**overrides) -> ExportPrivacyContract:
    values = {
        "allowed_columns": ("id", "name", "email"),
        "required_columns": ("id", "name"),
        "redact_fields": (),
        "format": "csv",
        "classification": "aggregate",
    }
    values.update(overrides)
    return ExportPrivacyContract(**values)


def creation_request(columns=("id", "name", "email")) -> ExportCreationRequest:
    return ExportCreationRequest(
        payload={"fixture": True},
        requested_columns=columns,
        idempotency_key="fixture-export-key-0001",
    )


def source_for(data: bytes, *, job_id="job-1") -> AuthorizedBlobSource:
    return AuthorizedBlobSource(
        url="https://files.example.test/signed/report.csv?token=secret",
        declared_path="/signed/report.csv",
        expires_at=NOW + timedelta(minutes=5),
        authorization_scope=f"export-status:{job_id}",
        job_id=job_id,
        declared_size=len(data),
        declared_mime_type="text/csv",
        expected_sha256=hashlib.sha256(data).hexdigest(),
    )


def blob_policy(root: Path) -> BlobPolicy:
    return BlobPolicy(
        allowed_extensions=frozenset({".csv"}),
        allowed_mime_types=frozenset({"text/csv"}),
        magic_signatures={".csv": (MagicSignature(0, b"id,"),)},
        mime_types_by_extension={".csv": ("text/csv",)},
        max_declared_size_bytes=1024,
        max_stream_size_bytes=1024,
        allowed_hosts=frozenset({"files.example.test"}),
        allowed_path_prefixes={"files.example.test": ("/signed/",)},
        destination_root=root,
        temporary_root=root,
    )


def orchestrator_for(gateway, transport, clock, *, polling=None, random_source=None):
    return ExportOrchestrator(
        gateway,
        SafeBlobTransfer(transport, wall_clock=lambda: NOW),
        polling_policy=polling
        or ExportPollingPolicy(
            timeout_seconds=20,
            initial_interval_seconds=1,
            multiplier=2,
            max_interval_seconds=3,
            jitter_ratio=0,
        ),
        monotonic_clock=clock.monotonic,
        sleeper=clock.sleep,
        random_source=random_source or (lambda: 0.5),
    )


class ExportOrchestratorTests(unittest.TestCase):
    def test_successful_state_machine_finalizes_privacy_before_commit(self):
        raw = b"id,name,email\n1,Alice,alice@example.test\n"
        ready = ExportJobSnapshot(
            "job-1",
            ExportState.READY,
            download_source=source_for(raw),
        )
        gateway = FakeGateway(
            ExportJobSnapshot("job-1", ExportState.QUEUED),
            [ExportJobSnapshot("job-1", ExportState.RUNNING), ready],
        )
        transport = FakeBlobTransport([FakeResponse(raw)])
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = orchestrator_for(gateway, transport, clock).start(
                creation_request(),
                "report.csv",
                blob_policy(root),
                privacy_contract(),
            )

            self.assertEqual(ExportState.COMMITTED, result.state)
            self.assertEqual(
                (
                    ExportState.CREATING,
                    ExportState.QUEUED,
                    ExportState.RUNNING,
                    ExportState.READY,
                    ExportState.DOWNLOADING,
                    ExportState.VERIFIED,
                    ExportState.COMMITTED,
                ),
                result.history,
            )
            self.assertEqual("id,name\n1,Alice\n", (root / "report.csv").read_text())
            self.assertNotEqual(result.receipt.source_sha256, result.receipt.committed_sha256)
            self.assertEqual(("id", "name"), result.receipt.finalization.schema)
            self.assertEqual(1, result.receipt.finalization.rows_processed)
            self.assertEqual([1, 2], clock.sleeps)
            self.assertEqual([20], gateway.create_timeouts)
            self.assertEqual([19, 17], gateway.status_timeouts)

    def test_actual_unknown_column_rejects_commit(self):
        raw = b"id,name,unexpected\n1,Alice,value\n"
        result, root = self._run_ready_failure(raw, privacy_contract())
        self.assertEqual(ExportState.FAILED, result.state)
        self.assertEqual("EXPORT_SCHEMA_MISMATCH", result.error.code)
        self.assertEqual(["unexpected"], result.error.details["unknown_columns"])
        self.assertFalse((root / "report.csv").exists())

    def test_actual_missing_required_column_rejects_commit(self):
        raw = b"id,email\n1,alice@example.test\n"
        result, root = self._run_ready_failure(raw, privacy_contract())
        self.assertEqual(ExportState.FAILED, result.state)
        self.assertEqual("EXPORT_SCHEMA_MISMATCH", result.error.code)
        self.assertEqual(["name"], result.error.details["missing_required_columns"])
        self.assertFalse((root / "report.csv").exists())

    def _run_ready_failure(self, raw, contract):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        gateway = FakeGateway(
            ExportJobSnapshot(
                "job-1",
                ExportState.READY,
                download_source=source_for(raw),
            )
        )
        result = orchestrator_for(
            gateway,
            FakeBlobTransport([FakeResponse(raw)]),
            FakeClock(),
        ).start(creation_request(), "report.csv", blob_policy(root), contract)
        self.assertFalse(list(root.glob(".blob-*")))
        return result, root

    def test_timeout_returns_resumable_job_id_without_cancelling(self):
        gateway = FakeGateway(
            ExportJobSnapshot("job-timeout", ExportState.RUNNING),
            [ExportJobSnapshot("job-timeout", ExportState.RUNNING)],
        )
        clock = FakeClock()
        polling = ExportPollingPolicy(
            timeout_seconds=3,
            initial_interval_seconds=1,
            multiplier=2,
            max_interval_seconds=2,
            jitter_ratio=0,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = orchestrator_for(
                gateway,
                FakeBlobTransport(),
                clock,
                polling=polling,
            ).start(
                creation_request(),
                "report.csv",
                blob_policy(root),
                privacy_contract(),
            )
        self.assertEqual(ExportState.TIMED_OUT, result.state)
        self.assertEqual("job-timeout", result.job_id)
        self.assertTrue(result.resumable)
        self.assertEqual("EXPORT_TIMEOUT", result.error.code)
        self.assertEqual(False, result.error.details["cancelled"])
        self.assertFalse(gateway.cancel_calls)
        self.assertEqual([1, 2], clock.sleeps)

    def test_polling_backoff_is_exponential_and_bounded(self):
        raw = b"id,name\n1,Alice\n"
        gateway = FakeGateway(
            ExportJobSnapshot("job-1", ExportState.QUEUED),
            [
                ExportJobSnapshot("job-1", ExportState.QUEUED),
                ExportJobSnapshot("job-1", ExportState.RUNNING),
                ExportJobSnapshot(
                    "job-1",
                    ExportState.READY,
                    download_source=source_for(raw),
                ),
            ],
        )
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = orchestrator_for(
                gateway,
                FakeBlobTransport([FakeResponse(raw)]),
                clock,
            ).start(
                creation_request(("id", "name")),
                "report.csv",
                blob_policy(root),
                privacy_contract(),
            )
        self.assertEqual(ExportState.COMMITTED, result.state)
        self.assertEqual([1, 2, 3], clock.sleeps)

    def test_polling_jitter_is_applied_but_stays_bounded(self):
        raw = b"id,name\n1,Alice\n"
        gateway = FakeGateway(
            ExportJobSnapshot("job-1", ExportState.QUEUED),
            [
                ExportJobSnapshot("job-1", ExportState.QUEUED),
                ExportJobSnapshot("job-1", ExportState.RUNNING),
                ExportJobSnapshot(
                    "job-1",
                    ExportState.READY,
                    download_source=source_for(raw),
                ),
            ],
        )
        clock = FakeClock()
        polling = ExportPollingPolicy(
            timeout_seconds=20,
            initial_interval_seconds=1,
            multiplier=2,
            max_interval_seconds=3,
            jitter_ratio=0.2,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = orchestrator_for(
                gateway,
                FakeBlobTransport([FakeResponse(raw)]),
                clock,
                polling=polling,
                random_source=lambda: 1.0,
            ).start(
                creation_request(("id", "name")),
                "report.csv",
                blob_policy(root),
                privacy_contract(),
            )
        self.assertEqual(ExportState.COMMITTED, result.state)
        self.assertAlmostEqual(1.2, clock.sleeps[0])
        self.assertAlmostEqual(2.4, clock.sleeps[1])
        self.assertEqual(3, clock.sleeps[2])

    def test_malformed_gateway_snapshot_fails_with_structured_protocol_error(self):
        gateway = FakeGateway({"job_id": "not-a-snapshot"})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = orchestrator_for(
                gateway,
                FakeBlobTransport(),
                FakeClock(),
            ).start(
                creation_request(),
                "report.csv",
                blob_policy(root),
                privacy_contract(),
            )
        self.assertEqual(ExportState.FAILED, result.state)
        self.assertEqual("EXPORT_PROTOCOL_ERROR", result.error.code)
        self.assertIsNone(result.job_id)

    def test_resume_polls_existing_job_without_create(self):
        raw = b"id,name\n1,Alice\n"
        gateway = FakeGateway(
            statuses=[
                ExportJobSnapshot(
                    "job-existing",
                    ExportState.READY,
                    download_source=source_for(raw, job_id="job-existing"),
                )
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = orchestrator_for(
                gateway,
                FakeBlobTransport([FakeResponse(raw)]),
                FakeClock(),
            ).resume(
                "job-existing",
                "report.csv",
                blob_policy(root),
                privacy_contract(),
            )
        self.assertEqual(ExportState.COMMITTED, result.state)
        self.assertFalse(gateway.create_calls)
        self.assertEqual(["job-existing"], gateway.status_calls)
        self.assertEqual(ExportState.READY, result.history[0])

    def test_create_failure_is_not_retried_without_verified_idempotency(self):
        gateway = FakeGateway(create_error=OSError("network unavailable"))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = orchestrator_for(
                gateway,
                FakeBlobTransport(),
                FakeClock(),
            ).start(
                creation_request(),
                "report.csv",
                blob_policy(root),
                privacy_contract(),
            )
        self.assertEqual(ExportState.FAILED, result.state)
        self.assertEqual("EXPORT_CREATE_FAILED", result.error.code)
        self.assertFalse(result.error.retryable)
        self.assertEqual(1, len(gateway.create_calls))
        self.assertFalse(gateway.status_calls)

    def test_cancel_without_verified_route_returns_cancel_unsupported(self):
        gateway = FakeGateway(supports_cancel=False)
        orchestrator = orchestrator_for(gateway, FakeBlobTransport(), FakeClock())
        with self.assertRaises(ExportRuntimeError) as raised:
            orchestrator.cancel("job-1")
        self.assertEqual("CANCEL_UNSUPPORTED", raised.exception.code)
        self.assertEqual("cancel", raised.exception.stage)
        self.assertFalse(gateway.cancel_calls)

    def test_creation_column_projection_fails_before_gateway(self):
        gateway = FakeGateway()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = orchestrator_for(
                gateway,
                FakeBlobTransport(),
                FakeClock(),
            ).start(
                creation_request(("id", "unknown")),
                "report.csv",
                blob_policy(root),
                privacy_contract(),
            )
        self.assertEqual(ExportState.FAILED, result.state)
        self.assertEqual("EXPORT_COLUMNS_INVALID", result.error.code)
        self.assertFalse(gateway.create_calls)

    def test_restricted_classification_fails_before_gateway(self):
        gateway = FakeGateway()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = orchestrator_for(
                gateway,
                FakeBlobTransport(),
                FakeClock(),
            ).start(
                creation_request(),
                "report.csv",
                blob_policy(root),
                privacy_contract(classification="restricted"),
            )
        self.assertEqual(ExportState.FAILED, result.state)
        self.assertEqual("EXPORT_PRIVACY_DENIED", result.error.code)
        self.assertFalse(gateway.create_calls)

    def test_upstream_failed_and_cancelled_are_terminal_branches(self):
        cases = (
            (
                ExportJobSnapshot(
                    "job-failed",
                    ExportState.FAILED,
                    failure_code="UPSTREAM_FIXTURE",
                    failure_message="fixture failed",
                ),
                ExportState.FAILED,
                "UPSTREAM_FIXTURE",
            ),
            (
                ExportJobSnapshot("job-cancelled", ExportState.CANCELLED),
                ExportState.CANCELLED,
                None,
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for snapshot, expected_state, expected_code in cases:
                with self.subTest(state=expected_state):
                    gateway = FakeGateway(snapshot)
                    result = orchestrator_for(
                        gateway,
                        FakeBlobTransport(),
                        FakeClock(),
                    ).start(
                        creation_request(),
                        "report.csv",
                        blob_policy(root),
                        privacy_contract(),
                    )
                    self.assertEqual(expected_state, result.state)
                    self.assertEqual(
                        expected_code,
                        result.error.code if result.error is not None else None,
                    )

    def test_state_regression_fails_closed(self):
        gateway = FakeGateway(
            ExportJobSnapshot("job-1", ExportState.RUNNING),
            [ExportJobSnapshot("job-1", ExportState.QUEUED)],
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = orchestrator_for(
                gateway,
                FakeBlobTransport(),
                FakeClock(),
            ).start(
                creation_request(),
                "report.csv",
                blob_policy(root),
                privacy_contract(),
            )
        self.assertEqual(ExportState.FAILED, result.state)
        self.assertEqual("EXPORT_STATE_INVALID", result.error.code)

    def test_jsonl_finalizer_is_streaming_and_uses_executor_redaction(self):
        contract = ExportPrivacyContract(
            allowed_columns=("id", "email"),
            required_columns=("id",),
            format="jsonl",
        )
        metadata = BlobMetadata(
            size_bytes=1,
            sha256="0" * 64,
            content_type="application/x-ndjson",
            extension=".jsonl",
            etag=None,
            last_modified=None,
            resumed=False,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.jsonl"
            output = root / "output.jsonl"
            source.write_text(
                '{"id":1,"email":"alice@example.test"}\n'
                '{"id":2,"email":"bob@example.test"}\n',
                encoding="utf-8",
            )
            result = ExportPrivacyFinalizer(contract).finalize(source, output, metadata)
            self.assertEqual('{"id":1}\n{"id":2}\n', output.read_text(encoding="utf-8"))
            self.assertEqual(("id",), result.schema)
            self.assertEqual(2, result.rows_processed)
            import gzip
            gz, out = root / "s.csv.gz", root / "o.csv"
            gz.write_bytes(gzip.compress(b"id\n1\n"))
            gzip_result = ExportPrivacyFinalizer(
                ExportPrivacyContract(("id",), ("id",), format="csv")
            ).finalize(gz, out, BlobMetadata(1, "0"*64, "text/csv", ".csv.gz", None, None, False))
            self.assertEqual((("id",), 1), (gzip_result.schema, gzip_result.rows_processed))


if __name__ == "__main__":
    unittest.main()
