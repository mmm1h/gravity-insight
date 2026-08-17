from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

try:
    from gravity_sdk import blob as blob_module
    from gravity_sdk.blob import (
        ArchivePolicy,
        AuthorizedBlobSource,
        AuthorizedUploadTarget,
        BlobPolicy,
        BlobResumeState,
        BlobTransferError,
        MagicSignature,
        SafeBlobTransfer,
        SafeLocalSource,
    )
except ModuleNotFoundError:  # source checkout without an editable install
    from gravity_sdk import blob as blob_module
    from gravity_sdk.blob import (
        ArchivePolicy,
        AuthorizedBlobSource,
        AuthorizedUploadTarget,
        BlobPolicy,
        BlobResumeState,
        BlobTransferError,
        MagicSignature,
        SafeBlobTransfer,
        SafeLocalSource,
    )


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
_AUTO = object()


class FakeResponse:
    def __init__(self, status_code=200, *, headers=None, chunks=()):
        self.status_code = status_code
        self.headers = dict(headers or {})
        self._chunks = list(chunks)
        self.closed = False

    def iter_content(self, *, chunk_size):
        for chunk in self._chunks:
            if isinstance(chunk, Exception):
                raise chunk
            yield chunk

    def close(self):
        self.closed = True


class FakeTransport:
    def __init__(self, responses=(), *, upload_response=None):
        self.responses = list(responses)
        self.upload_response = upload_response
        self.download_calls = []
        self.upload_calls = []

    def open_download(self, url, *, headers, timeout):
        self.download_calls.append((url, dict(headers), timeout))
        if not self.responses:
            raise AssertionError("unexpected download request")
        return self.responses.pop(0)

    def upload(
        self,
        url,
        *,
        file_path,
        file_field,
        content_type,
        form_fields,
        timeout,
    ):
        self.upload_calls.append(
            (
                url,
                file_path,
                file_field,
                content_type,
                dict(form_fields),
                timeout,
            )
        )
        if self.upload_response is None:
            raise AssertionError("unexpected upload request")
        return self.upload_response


def csv_policy(root: Path, **overrides) -> BlobPolicy:
    values = {
        "allowed_extensions": frozenset({".csv"}),
        "allowed_mime_types": frozenset({"text/csv"}),
        "magic_signatures": {".csv": (MagicSignature(0, b"id,"),)},
        "mime_types_by_extension": {".csv": ("text/csv",)},
        "max_declared_size_bytes": 1_024,
        "max_stream_size_bytes": 1_024,
        "allowed_hosts": frozenset({"files.example.test"}),
        "allowed_redirect_hosts": frozenset({"cdn.example.test"}),
        "allowed_path_prefixes": {
            "files.example.test": ("/signed/",),
            "cdn.example.test": ("/objects/",),
        },
        "destination_root": root,
        "temporary_root": root,
    }
    values.update(overrides)
    return BlobPolicy(**values)


def source_for(
    data: bytes,
    *,
    declared_size=_AUTO,
    declared_mime_type="text/csv",
    expected_sha256=_AUTO,
    url="https://files.example.test/signed/report.csv?token=secret",
    declared_path="/signed/report.csv",
    expires_at=NOW + timedelta(minutes=5),
    job_id="job-1",
) -> AuthorizedBlobSource:
    return AuthorizedBlobSource(
        url=url,
        declared_path=declared_path,
        expires_at=expires_at,
        authorization_scope="export-status:job-1",
        job_id=job_id,
        declared_size=len(data) if declared_size is _AUTO else declared_size,
        declared_mime_type=declared_mime_type,
        expected_sha256=(
            hashlib.sha256(data).hexdigest()
            if expected_sha256 is _AUTO
            else expected_sha256
        ),
    )


def response_for(data: bytes, *, headers=None, chunks=None) -> FakeResponse:
    response_headers = {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Length": str(len(data)),
        "ETag": '"version-1"',
    }
    response_headers.update(headers or {})
    return FakeResponse(
        headers=response_headers,
        chunks=[data] if chunks is None else chunks,
    )


def zip_bytes(entries: list[tuple[str, bytes]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries:
            archive.writestr(name, value)
    return output.getvalue()


def zip_policy(root: Path, archive_policy: ArchivePolicy) -> BlobPolicy:
    return BlobPolicy(
        allowed_extensions=frozenset({".zip"}),
        allowed_mime_types=frozenset({"application/zip"}),
        magic_signatures={".zip": (MagicSignature(0, b"PK"),)},
        mime_types_by_extension={".zip": ("application/zip",)},
        max_declared_size_bytes=1024 * 1024,
        max_stream_size_bytes=1024 * 1024,
        allowed_hosts=frozenset({"files.example.test"}),
        allowed_path_prefixes={"files.example.test": ("/signed/",)},
        archive_policy=archive_policy,
        destination_root=root,
        temporary_root=root,
    )


class SafeBlobTransferTests(unittest.TestCase):
    def test_download_streams_hashes_and_atomically_commits(self):
        data = b"id,name\n1,Alice\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = FakeTransport([response_for(data, chunks=[data[:5], data[5:]])])
            transfer = SafeBlobTransfer(transport, wall_clock=lambda: NOW)

            receipt = transfer.download(source_for(data), "report.csv", csv_policy(root))

            self.assertEqual(data, (root / "report.csv").read_bytes())
            self.assertEqual(hashlib.sha256(data).hexdigest(), receipt.source_sha256)
            self.assertEqual(receipt.source_sha256, receipt.committed_sha256)
            self.assertFalse(list(root.glob(".blob-*")))
            self.assertTrue(transport.responses == [])

    def test_destination_rejects_dotdot_and_absolute_escape(self):
        data = b"id,name\n1,Alice\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for destination in ("../escape.csv", root.parent / "absolute.csv"):
                with self.subTest(destination=destination):
                    transport = FakeTransport()
                    transfer = SafeBlobTransfer(transport, wall_clock=lambda: NOW)
                    with self.assertRaises(BlobTransferError) as raised:
                        transfer.download(source_for(data), destination, csv_policy(root))
                    self.assertEqual("BLOB_PATH_ESCAPE", raised.exception.code)
                    self.assertFalse(transport.download_calls)
            self.assertFalse((root.parent / "escape.csv").exists())
            self.assertFalse((root.parent / "absolute.csv").exists())

    def test_destination_rejects_real_symlink_component(self):
        data = b"id,name\n1,Alice\n"
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            link = root / "linked"
            try:
                os.symlink(outside, link, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlink unavailable: {exc}")
            transfer = SafeBlobTransfer(FakeTransport(), wall_clock=lambda: NOW)
            with self.assertRaises(BlobTransferError) as raised:
                transfer.download(source_for(data), "linked/report.csv", csv_policy(root))
            self.assertEqual("BLOB_PATH_REPARSE", raised.exception.code)
            self.assertFalse((Path(outside) / "report.csv").exists())

    def test_destination_rejects_reparse_point_even_without_symlink_mode(self):
        data = b"id,name\n1,Alice\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reparse = root / "reparse"
            reparse.mkdir()
            real_check = blob_module._is_reparse_stat

            def simulated_check(path, value):
                return Path(path) == reparse or real_check(path, value)

            transfer = SafeBlobTransfer(FakeTransport(), wall_clock=lambda: NOW)
            with patch.object(blob_module, "_is_reparse_stat", side_effect=simulated_check):
                with self.assertRaises(BlobTransferError) as raised:
                    transfer.download(source_for(data), "reparse/report.csv", csv_policy(root))
            self.assertEqual("BLOB_PATH_REPARSE", raised.exception.code)

    def test_redirect_to_non_allowlisted_host_fails_before_second_request(self):
        data = b"id,name\n1,Alice\n"
        redirect = FakeResponse(
            302,
            headers={"Location": "https://evil.example.test/objects/report.csv"},
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = FakeTransport([redirect])
            transfer = SafeBlobTransfer(transport, wall_clock=lambda: NOW)
            with self.assertRaises(BlobTransferError) as raised:
                transfer.download(source_for(data), "report.csv", csv_policy(root))
            self.assertEqual("BLOB_URL_DENIED", raised.exception.code)
            self.assertEqual(1, len(transport.download_calls))
            self.assertTrue(redirect.closed)
            self.assertFalse((root / "report.csv").exists())

    def test_oversized_declared_source_fails_before_network(self):
        data = b"id,name\n1,Alice\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transport = FakeTransport()
            transfer = SafeBlobTransfer(transport, wall_clock=lambda: NOW)
            with self.assertRaises(BlobTransferError) as raised:
                transfer.download(
                    source_for(data, declared_size=2_000),
                    "report.csv",
                    csv_policy(root, max_declared_size_bytes=100),
                )
            self.assertEqual("BLOB_SIZE_LIMIT", raised.exception.code)
            self.assertFalse(transport.download_calls)

    def test_authorized_declared_size_must_match_actual_stream_bytes(self):
        data = b"id,name\n1,Alice\n"
        response = FakeResponse(headers={"Content-Type": "text/csv"}, chunks=[data])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transfer = SafeBlobTransfer(FakeTransport([response]), wall_clock=lambda: NOW)
            with self.assertRaises(BlobTransferError) as raised:
                transfer.download(
                    source_for(data, declared_size=len(data) + 1),
                    "report.csv",
                    csv_policy(root),
                )
            self.assertEqual("BLOB_SIZE_MISMATCH", raised.exception.code)
            self.assertFalse((root / "report.csv").exists())
            self.assertFalse(list(root.glob(".blob-*")))

    def test_extension_mime_and_magic_must_all_agree(self):
        data = b"id,name\n1,Alice\n"
        cases = (
            (
                "bad-extension.json",
                source_for(data),
                response_for(data),
                "BLOB_EXTENSION_MISMATCH",
            ),
            (
                "report.csv",
                source_for(data, declared_mime_type="application/json"),
                response_for(data, headers={"Content-Type": "application/json"}),
                "BLOB_MIME_MISMATCH",
            ),
            (
                "report.csv",
                source_for(b"xx,name\n1,Alice\n"),
                response_for(b"xx,name\n1,Alice\n"),
                "BLOB_MAGIC_MISMATCH",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for destination, source, response, expected_code in cases:
                with self.subTest(expected_code=expected_code):
                    transfer = SafeBlobTransfer(FakeTransport([response]), wall_clock=lambda: NOW)
                    with self.assertRaises(BlobTransferError) as raised:
                        transfer.download(source, destination, csv_policy(root))
                    self.assertEqual(expected_code, raised.exception.code)
            self.assertFalse(list(root.iterdir()))

    def test_expected_sha256_mismatch_deletes_staging_file(self):
        data = b"id,name\n1,Alice\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transfer = SafeBlobTransfer(
                FakeTransport([response_for(data)]),
                wall_clock=lambda: NOW,
            )
            with self.assertRaises(BlobTransferError) as raised:
                transfer.download(
                    source_for(data, expected_sha256="0" * 64),
                    "report.csv",
                    csv_policy(root),
                )
            self.assertEqual("BLOB_HASH_MISMATCH", raised.exception.code)
            self.assertFalse(list(root.iterdir()))

    def test_zip_slip_entry_fails_closed(self):
        data = zip_bytes([("../escape.txt", b"owned")])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = source_for(
                data,
                declared_mime_type="application/zip",
                url="https://files.example.test/signed/report.zip",
                declared_path="/signed/report.zip",
            )
            response = response_for(data, headers={"Content-Type": "application/zip"})
            transfer = SafeBlobTransfer(FakeTransport([response]), wall_clock=lambda: NOW)
            with self.assertRaises(BlobTransferError) as raised:
                transfer.download(
                    source,
                    "report.zip",
                    zip_policy(root, ArchivePolicy(enabled=True)),
                )
            self.assertEqual("BLOB_ARCHIVE_UNSAFE", raised.exception.code)
            self.assertFalse((root.parent / "escape.txt").exists())

    def test_zip_bomb_uncompressed_size_cap_fails_closed(self):
        data = zip_bytes([("large.txt", b"x" * 100)])
        archive_policy = ArchivePolicy(
            enabled=True,
            max_uncompressed_size_bytes=10,
            max_entries=10,
            max_compression_ratio=10_000,
        )
        error = self._assert_zip_rejected(data, archive_policy)
        self.assertEqual("uncompressed_size_cap", error.details["rule"])
        self.assertEqual(100, error.details["observed_uncompressed_bytes"])
        self.assertEqual(10, error.details["max_uncompressed_size_bytes"])

    def test_zip_bomb_entry_count_cap_fails_closed(self):
        data = zip_bytes([("a.txt", b"a"), ("b.txt", b"b")])
        archive_policy = ArchivePolicy(
            enabled=True,
            max_uncompressed_size_bytes=100,
            max_entries=1,
            max_compression_ratio=10_000,
        )
        self._assert_zip_rejected(data, archive_policy)

    def test_zip_bomb_compression_ratio_reports_rule_and_measured_values(self):
        data = zip_bytes([("repeated.txt", b"x" * 1_000)])
        archive_policy = ArchivePolicy(
            enabled=True,
            max_uncompressed_size_bytes=10_000,
            max_entries=10,
            max_compression_ratio=2,
        )
        error = self._assert_zip_rejected(data, archive_policy)
        self.assertEqual("compression_ratio_cap", error.details["rule"])
        self.assertEqual("repeated.txt", error.details["entry"])
        self.assertEqual(1_000, error.details["declared_uncompressed_size"])
        self.assertGreater(error.details["observed_compression_ratio"], 2)
        self.assertIn("next_action", error.details)

    def test_zip_bomb_nested_archive_depth_cap_fails_closed(self):
        child = zip_bytes([("inside.txt", b"value")])
        data = zip_bytes([("nested.bin", child)])
        archive_policy = ArchivePolicy(
            enabled=True,
            max_uncompressed_size_bytes=10_000,
            max_entries=10,
            max_nested_depth=0,
            max_compression_ratio=10_000,
        )
        self._assert_zip_rejected(data, archive_policy)

    def _assert_zip_rejected(self, data: bytes, archive_policy: ArchivePolicy):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = source_for(
                data,
                declared_mime_type="application/zip",
                url="https://files.example.test/signed/report.zip",
                declared_path="/signed/report.zip",
            )
            response = response_for(data, headers={"Content-Type": "application/zip"})
            transfer = SafeBlobTransfer(FakeTransport([response]), wall_clock=lambda: NOW)
            with self.assertRaises(BlobTransferError) as raised:
                transfer.download(source, "report.zip", zip_policy(root, archive_policy))
            self.assertEqual("BLOB_ARCHIVE_UNSAFE", raised.exception.code)
            self.assertFalse((root / "report.zip").exists())
            self.assertFalse(list(root.glob(".blob-*")))
            return raised.exception

    def test_missing_content_length_still_enforces_streaming_cap(self):
        data = b"id," + b"x" * 20
        response = FakeResponse(headers={"Content-Type": "text/csv"}, chunks=[data[:5], data[5:]])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = csv_policy(
                root,
                max_declared_size_bytes=8,
                max_stream_size_bytes=8,
            )
            transfer = SafeBlobTransfer(FakeTransport([response]), wall_clock=lambda: NOW)
            with self.assertRaises(BlobTransferError) as raised:
                transfer.download(
                    source_for(data, declared_size=None),
                    "report.csv",
                    policy,
                )
            self.assertEqual("BLOB_SIZE_LIMIT", raised.exception.code)
            self.assertFalse((root / "report.csv").exists())

    def test_resume_rejects_changed_etag_before_appending(self):
        full_data = b"id,name\n1,Alice\n"
        partial = full_data[:3]
        remaining = full_data[3:]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            partial_path = root / "partial.resume"
            partial_path.write_bytes(partial)
            response = FakeResponse(
                206,
                headers={
                    "Content-Type": "text/csv",
                    "Content-Length": str(len(remaining)),
                    "Content-Range": f"bytes {len(partial)}-{len(full_data) - 1}/{len(full_data)}",
                    "ETag": '"version-2"',
                },
                chunks=[remaining],
            )
            transport = FakeTransport([response])
            transfer = SafeBlobTransfer(transport, wall_clock=lambda: NOW)
            with self.assertRaises(BlobTransferError) as raised:
                transfer.download(
                    source_for(full_data),
                    "report.csv",
                    csv_policy(root, allow_range_resume=True),
                    resume=BlobResumeState(
                        partial_path=partial_path,
                        bytes_received=len(partial),
                        etag='"version-1"',
                    ),
                )
            self.assertEqual(
                f"bytes={len(partial)}-",
                transport.download_calls[0][1]["Range"],
            )
            self.assertEqual("BLOB_RESUME_VALIDATOR_CHANGED", raised.exception.code)
            self.assertEqual(partial, partial_path.read_bytes())
            self.assertFalse((root / "report.csv").exists())

    def test_resume_request_omits_blank_if_range(self):
        from gravity_sdk.blob_download import _download_request_headers

        headers = _download_request_headers(
            BlobResumeState(partial_path=Path("partial"), bytes_received=4, etag="")
        )
        self.assertEqual("bytes=4-", headers["Range"])
        self.assertNotIn("If-Range", headers)
        present = _download_request_headers(
            BlobResumeState(
                partial_path=Path("partial"),
                bytes_received=4,
                etag='"version-1"',
            )
        )
        self.assertEqual('"version-1"', present["If-Range"])

    def test_interrupted_stream_returns_validator_bound_resume_state(self):
        data = b"id,name\n1,Alice\n"
        response = response_for(data, chunks=[data[:5], OSError("connection reset")])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            transfer = SafeBlobTransfer(FakeTransport([response]), wall_clock=lambda: NOW)
            with self.assertRaises(BlobTransferError) as raised:
                transfer.download(
                    source_for(data),
                    "report.csv",
                    csv_policy(root, allow_range_resume=True),
                )
            error = raised.exception
            self.assertEqual("BLOB_TRANSPORT_ERROR", error.code)
            self.assertTrue(error.retryable)
            self.assertIsNotNone(error.resume_state)
            self.assertEqual('"version-1"', error.resume_state.etag)
            self.assertEqual(data[:5], error.resume_state.partial_path.read_bytes())
            error.resume_state.partial_path.unlink()

    def test_signed_url_requires_https_declared_path_allowlist_and_fresh_expiry(self):
        data = b"id,name\n1,Alice\n"
        cases = (
            source_for(data, url="http://files.example.test/signed/report.csv"),
            source_for(data, declared_path="/signed/other.csv"),
            source_for(data, expires_at=NOW),
            source_for(
                data,
                url="https://files.example.test/other/report.csv",
                declared_path="/other/report.csv",
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for source in cases:
                with self.subTest(url=source.url, path=source.declared_path):
                    transport = FakeTransport()
                    transfer = SafeBlobTransfer(transport, wall_clock=lambda: NOW)
                    with self.assertRaises(BlobTransferError):
                        transfer.download(source, "report.csv", csv_policy(root))
                    self.assertFalse(transport.download_calls)

    def test_default_overwrite_policy_denies_existing_destination(self):
        data = b"id,name\n1,Alice\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "report.csv"
            destination.write_bytes(b"existing")
            transfer = SafeBlobTransfer(FakeTransport(), wall_clock=lambda: NOW)
            with self.assertRaises(BlobTransferError) as raised:
                transfer.download(source_for(data), "report.csv", csv_policy(root))
            self.assertEqual("BLOB_OVERWRITE_DENIED", raised.exception.code)
            self.assertEqual(b"existing", destination.read_bytes())

    def test_replace_overwrite_policy_replaces_existing_regular_file(self):
        data = b"id,name\n1,Alice\n"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "report.csv"
            destination.write_bytes(b"existing")
            transfer = SafeBlobTransfer(
                FakeTransport([response_for(data)]),
                wall_clock=lambda: NOW,
            )
            receipt = transfer.download(
                source_for(data),
                "report.csv",
                csv_policy(root, overwrite_policy="replace"),
            )
            self.assertEqual(data, destination.read_bytes())
            self.assertEqual(hashlib.sha256(data).hexdigest(), receipt.committed_sha256)
            self.assertFalse(list(root.glob(".blob-*")))

    def test_upload_is_implemented_but_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = AuthorizedUploadTarget(
                url="https://files.example.test/signed/upload",
                declared_path="/signed/upload",
                expires_at=NOW + timedelta(minutes=5),
                authorization_scope="file-upload:fixture",
                file_field="attachment",
                content_type="text/csv",
            )
            transport = FakeTransport()
            transfer = SafeBlobTransfer(transport, wall_clock=lambda: NOW)
            with self.assertRaises(BlobTransferError) as raised:
                transfer.upload(SafeLocalSource("report.csv"), target, csv_policy(root))
            self.assertEqual("UPLOAD_DISABLED", raised.exception.code)
            self.assertFalse(transport.upload_calls)

    def test_explicitly_enabled_upload_checks_and_records_server_digest(self):
        data = b"id,name\n1,Alice\n"
        digest = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "report.csv").write_bytes(data)
            target = AuthorizedUploadTarget(
                url="https://files.example.test/signed/upload",
                declared_path="/signed/upload",
                expires_at=NOW + timedelta(minutes=5),
                authorization_scope="file-upload:fixture",
                file_field="attachment",
                content_type="text/csv",
                form_fields={"purpose": "fixture"},
                server_digest_header="X-Content-SHA256",
            )
            response = FakeResponse(
                201,
                headers={"X-Upload-Receipt": "receipt-1", "X-Content-SHA256": digest},
            )
            transport = FakeTransport(upload_response=response)
            transfer = SafeBlobTransfer(transport, wall_clock=lambda: NOW)
            policy = csv_policy(root, allow_upload=True, upload_root=root)

            receipt = transfer.upload(SafeLocalSource("report.csv"), target, policy)

            self.assertEqual(digest, receipt.sha256)
            self.assertEqual(digest, receipt.server_sha256)
            self.assertEqual("receipt-1", receipt.server_receipt)
            self.assertEqual({"purpose": "fixture"}, transport.upload_calls[0][4])


if __name__ == "__main__":
    unittest.main()
