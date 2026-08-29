from __future__ import annotations

from copy import deepcopy
import hashlib
import inspect
import io
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from gravity_sdk.agent import discover_capabilities
from gravity_sdk.artifact_transfer import (
    ArtifactTransferError,
    validate_artifact_transfer,
)
from gravity_sdk.cli import build_parser, main
from gravity_sdk.errors import (
    ContractChangedError,
    InputValidationError,
    error_detail_from_exception,
    exit_code_for_error,
)
from gravity_sdk.material_asset import fetch_material_asset
from gravity_sdk.material_asset_contract import _validate_sources, material_asset_contract
from gravity_sdk.material_asset_transfer import MaterialAssetHttpError
from gravity_sdk.result_audit import error_receipt_references
from gravity_sdk.sdk import GravitySDK


SOURCE_RECEIPT = {"receipt_id": "a" * 32, "storage_status": "stored"}


class FakeClient:
    def __init__(
        self,
        source: str = "local",
        *,
        row: dict[str, object] | None = None,
        with_receipt: bool = False,
    ) -> None:
        self.source = source
        self.row = row
        self.with_receipt = with_receipt
        self.calls: list[tuple[str, dict[str, object]]] = []

    def read(self, operation_id: str, inputs: dict[str, object]) -> dict[str, object]:
        self.calls.append((operation_id, inputs))
        if "url" in inputs:
            raise InputValidationError("unknown operation input fields: url", field="url")
        if self.row is not None:
            row = self.row
        elif self.source == "local":
            row = {
                "id": 7,
                "thumbnail_url": "https://unlisted.example.test/thumb.jpg",
            }
        else:
            row = {
                "material_id": 8,
                "file_url": "https://v99-anywhere.example.test/video.mp4",
            }
        data_key = "list" if self.source == "local" else "video_material_list"
        result: dict[str, object] = {"status": "success", "data": {data_key: [row]}}
        if self.with_receipt:
            result["result_audit"] = {
                "schema_version": "gravity.result-audit.v1",
                "fact_paths": {},
                "http_receipts": [SOURCE_RECEIPT],
            }
        return result


class FakeResponse:
    def __init__(
        self,
        data: bytes = b"",
        *,
        status: int = 200,
        content_type: str = "image/jpeg",
        headers: dict[str, str] | None = None,
        chunks: list[bytes | BaseException] | None = None,
        include_length: bool = True,
    ) -> None:
        self.status_code = status
        self.headers = dict(headers or {})
        if status == 200:
            self.headers.setdefault("Content-Type", content_type)
            if include_length:
                self.headers.setdefault("Content-Length", str(len(data)))
        self.chunks = list(chunks if chunks is not None else [data])
        self.closed = False

    def iter_content(self, chunk_size: int):
        del chunk_size
        for value in self.chunks:
            if isinstance(value, BaseException):
                raise value
            yield value

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.download_calls: list[tuple[str, dict[str, str], float]] = []

    def open_download(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout: float,
    ) -> FakeResponse:
        self.download_calls.append((url, dict(headers), timeout))
        if not self.responses:
            raise AssertionError("unexpected binary request")
        return self.responses.pop(0)


class MaterialAssetTests(unittest.TestCase):
    def test_source_contract_locks_type_limits_redirects_and_private_url_boundary(self) -> None:
        contract = material_asset_contract()
        self.assertEqual("gravity.material-asset-contract.v2", contract["schema_version"])
        self.assertFalse(contract["accepts_caller_url"])
        self.assertEqual("fresh_response_exact_host", contract["initial_host_policy"])
        self.assertEqual("same_host_only", contract["redirect_policy"])
        file_role = contract["sources"]["local"]["roles"]["file"]
        image_role = contract["sources"]["local"]["roles"]["thumbnail"]
        self.assertEqual((1024 * 1024 * 1024, [".mp4"]), (
            file_role["max_bytes"], file_role["extensions"]
        ))
        self.assertEqual((16 * 1024 * 1024, [".jpg", ".jpeg"]), (
            image_role["max_bytes"], image_role["extensions"]
        ))

        mutations = []
        changed = deepcopy(contract["sources"])
        changed["local"]["reference_fields"] = ["url"]
        mutations.append(changed)
        changed = deepcopy(contract["sources"])
        changed["local"]["roles"]["thumbnail"]["max_bytes"] += 1
        mutations.append(changed)
        changed = deepcopy(contract["sources"])
        changed["local"]["roles"]["thumbnail"]["magic_signatures"][0]["hex"] = "89504e47"
        mutations.append(changed)
        changed = deepcopy(contract["sources"])
        changed["local"]["roles"]["file"]["max_redirects"] = 2
        mutations.append(changed)
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(ContractChangedError):
                _validate_sources(value)

    def test_fresh_reference_runs_through_schema_and_same_host_redirect(self) -> None:
        payload = b"\xff\xd8\xff" + b"a" * 29
        redirect = FakeResponse(
            status=302,
            headers={"Location": "/final.jpg"},
        )
        completed = FakeResponse(payload)
        transport = FakeTransport(redirect, completed)
        client = FakeClient(with_receipt=True)
        with TemporaryDirectory() as raw:
            root = Path(raw)
            result = fetch_material_asset(
                client,
                "local",
                {"page": 1},
                "id",
                "7",
                "thumbnail",
                root / "thumb.jpg",
                _transport=transport,
            )
            self.assertEqual(payload, (root / "thumb.jpg").read_bytes())
            self.assertNotIn(str(root), repr(result))
        artifact = validate_artifact_transfer(result["artifact"])
        self.assertEqual("gravity.material-asset.v2", result["schema_version"])
        self.assertEqual("gravity.artifact-transfer.v1", artifact["schema_version"])
        self.assertEqual("thumb.jpg", artifact["local_ref"])
        self.assertEqual(1, artifact["transfer"]["redirect_count"])
        self.assertFalse(artifact["transfer"]["cross_host_redirect"])
        self.assertEqual(
            [
                "https://unlisted.example.test/thumb.jpg",
                "https://unlisted.example.test/final.jpg",
            ],
            [call[0] for call in transport.download_calls],
        )
        self.assertEqual(
            [SOURCE_RECEIPT], result["result_audit"]["http_receipts"]
        )
        self.assertNotIn("url", artifact["source"])
        self.assertTrue(redirect.closed)
        self.assertTrue(completed.closed)

    def test_cross_host_redirect_fails_before_second_request_or_commit(self) -> None:
        redirect = FakeResponse(
            status=302,
            headers={"Location": "https://evil.example.test/final.jpg"},
        )
        transport = FakeTransport(redirect)
        with TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "thumb.jpg"
            with self.assertRaises(ArtifactTransferError) as raised:
                fetch_material_asset(
                    FakeClient(), "local", {}, "id", 7, "thumbnail", output,
                    _transport=transport,
                )
            self.assertFalse(output.exists())
            self.assertFalse(list(root.glob(".blob-*")))
        self.assertEqual("ARTIFACT_REDIRECT_DENIED", raised.exception.code)
        self.assertEqual("redirect_policy", raised.exception.reason_category)
        self.assertEqual(1, len(transport.download_calls))
        self.assertTrue(redirect.closed)

    def test_redirect_limit_is_enforced_without_final_commit(self) -> None:
        redirects = tuple(
            FakeResponse(status=302, headers={"Location": f"/hop-{number}.jpg"})
            for number in range(4)
        )
        transport = FakeTransport(*redirects)
        with TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaises(ArtifactTransferError) as raised:
                fetch_material_asset(
                    FakeClient(),
                    "local",
                    {},
                    "id",
                    7,
                    "thumbnail",
                    root / "thumb.jpg",
                    _transport=transport,
                )
            self.assertEqual("ARTIFACT_REDIRECT_LIMIT", raised.exception.code)
            self.assertFalse((root / "thumb.jpg").exists())
            self.assertFalse(list(root.glob(".blob-*")))
        self.assertEqual(4, len(transport.download_calls))
        self.assertTrue(all(response.closed for response in redirects))

    def test_http_statuses_remain_upstream_without_asset_state_taxonomy(self) -> None:
        for status, retryable in (
            (403, False),
            (404, False),
            (410, False),
            (429, True),
            (503, True),
        ):
            with self.subTest(status=status), TemporaryDirectory() as raw:
                with self.assertRaises(MaterialAssetHttpError) as raised:
                    fetch_material_asset(
                        FakeClient(),
                        "local",
                        {},
                        "id",
                        7,
                        "thumbnail",
                        Path(raw) / "thumb.jpg",
                        _transport=FakeTransport(FakeResponse(status=status)),
                    )
                detail = error_detail_from_exception(raised.exception)
                self.assertEqual("upstream", detail.category)
                self.assertEqual(3, exit_code_for_error(raised.exception))
                self.assertEqual(retryable, detail.retryable)
                self.assertIn(f"HTTP {status}", detail.message)

    def test_caller_cannot_supply_url_and_agent_handoff_has_no_url_slot(self) -> None:
        transport = FakeTransport(FakeResponse(b"\xff\xd8\xff"))
        with TemporaryDirectory() as raw, self.assertRaises(InputValidationError):
            fetch_material_asset(
                FakeClient(),
                "local",
                {"url": "https://caller.invalid"},
                "id",
                7,
                "thumbnail",
                Path(raw) / "thumb.jpg",
                _transport=transport,
            )
        self.assertEqual([], transport.download_calls)
        self.assertNotIn("url", inspect.signature(fetch_material_asset).parameters)
        card = discover_capabilities(
            "下载精确平台素材视频文件", client=object()
        )["candidates"][0]
        self.assertEqual("material.asset.fetch", card["selector"])
        self.assertIsNone(card["plan_node"])
        self.assertFalse(card["source_contract"]["accepts_caller_url"])
        self.assertEqual(
            "gravity.artifact-transfer.v1",
            card["source_contract"]["artifact_schema_version"],
        )
        self.assertEqual("same_host_only", card["source_contract"]["redirect_policy"])
        self.assertEqual(["output_root"], card["optional_inputs"])
        self.assertNotIn("url", card["required_inputs"])

    def test_output_root_and_extension_fail_before_source_or_binary_network(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            cases = ("../escape.jpg", "thumb.png", str(root / "absolute.jpg"))
            for destination in cases:
                with self.subTest(destination=destination):
                    client = FakeClient()
                    transport = FakeTransport()
                    with self.assertRaises(ArtifactTransferError) as raised:
                        fetch_material_asset(
                            client,
                            "local",
                            {},
                            "id",
                            7,
                            "thumbnail",
                            destination,
                            output_root=root,
                            _transport=transport,
                        )
                    self.assertEqual("ARTIFACT_OUTPUT_DENIED", raised.exception.code)
                    self.assertEqual([], client.calls)
                    self.assertEqual([], transport.download_calls)
            existing = root / "existing.jpg"
            existing.write_bytes(b"original")
            client = FakeClient()
            with self.assertRaises(ArtifactTransferError):
                fetch_material_asset(
                    client,
                    "local",
                    {},
                    "id",
                    7,
                    "thumbnail",
                    "existing.jpg",
                    output_root=root,
                    _transport=FakeTransport(),
                )
            self.assertEqual([], client.calls)
            self.assertEqual(b"original", existing.read_bytes())

    def test_reference_must_match_exactly_one_fresh_source_row(self) -> None:
        class DuplicateClient(FakeClient):
            def read(self, operation_id, inputs):
                self.calls.append((operation_id, inputs))
                row = {
                    "id": 7,
                    "thumbnail_url": "https://files.example.test/thumb.jpg",
                }
                return {"status": "success", "data": {"list": [row, dict(row)]}}

        with TemporaryDirectory() as raw:
            root = Path(raw)
            for client, reference in (
                (FakeClient(with_receipt=True), 99),
                (DuplicateClient(), 7),
            ):
                with self.subTest(reference=reference, client=type(client).__name__):
                    transport = FakeTransport()
                    with self.assertRaises(InputValidationError) as raised:
                        fetch_material_asset(
                            client,
                            "local",
                            {},
                            "id",
                            reference,
                            "thumbnail",
                            root / f"{type(client).__name__}.jpg",
                            _transport=transport,
                        )
                    self.assertEqual([], transport.download_calls)
                    if client.with_receipt:
                        self.assertEqual(
                            [SOURCE_RECEIPT],
                            error_receipt_references(raised.exception),
                        )

    def test_overlong_exact_reference_fails_before_binary_and_final_commit(self) -> None:
        reference = "x" * 257
        client = FakeClient(
            row={
                "id": reference,
                "thumbnail_url": "https://files.example.test/thumb.jpg",
            },
            with_receipt=True,
        )
        transport = FakeTransport()
        with TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaises(ArtifactTransferError) as raised:
                fetch_material_asset(
                    client,
                    "local",
                    {},
                    "id",
                    reference,
                    "thumbnail",
                    root / "thumb.jpg",
                    _transport=transport,
                )
            self.assertEqual("ARTIFACT_REFERENCE_INVALID", raised.exception.code)
            self.assertEqual([SOURCE_RECEIPT], error_receipt_references(raised.exception))
            self.assertEqual([], transport.download_calls)
            self.assertFalse((root / "thumb.jpg").exists())

    def test_explicit_root_returns_only_nested_relative_reference(self) -> None:
        payload = b"\xff\xd8\xffsafe"
        with TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "nested").mkdir()
            result = fetch_material_asset(
                FakeClient(),
                "local",
                {},
                "id",
                7,
                "thumbnail",
                "nested/preview.jpeg",
                output_root=root,
                _transport=FakeTransport(FakeResponse(payload)),
            )
            self.assertEqual(payload, (root / "nested" / "preview.jpeg").read_bytes())
            self.assertEqual("nested/preview.jpeg", result["artifact"]["local_ref"])
            self.assertNotIn(str(root), repr(result))

    def test_mime_and_magic_mismatch_leave_no_visible_or_partial_file(self) -> None:
        cases = (
            (
                FakeResponse(b"\xff\xd8\xff", content_type="image/png"),
                "ARTIFACT_MIME_MISMATCH",
            ),
            (FakeResponse(b"not-a-jpeg"), "ARTIFACT_MAGIC_MISMATCH"),
        )
        for response, expected in cases:
            with self.subTest(expected=expected), TemporaryDirectory() as raw:
                root = Path(raw)
                with self.assertRaises(ArtifactTransferError) as raised:
                    fetch_material_asset(
                        FakeClient(),
                        "local",
                        {},
                        "id",
                        7,
                        "thumbnail",
                        root / "thumb.jpg",
                        _transport=FakeTransport(response),
                    )
                self.assertEqual(expected, raised.exception.code)
                self.assertFalse((root / "thumb.jpg").exists())
                self.assertFalse(list(root.glob(".blob-*")))

    def test_interrupted_stream_leaves_no_visible_or_partial_artifact(self) -> None:
        response = FakeResponse(
            chunks=[b"\xff\xd8\xffpartial", OSError("connection reset")],
            include_length=False,
        )
        with TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaises(ArtifactTransferError) as raised:
                fetch_material_asset(
                    FakeClient(),
                    "local",
                    {},
                    "id",
                    7,
                    "thumbnail",
                    root / "thumb.jpg",
                    _transport=FakeTransport(response),
                )
            self.assertEqual("ARTIFACT_TRANSPORT_FAILED", raised.exception.code)
            self.assertFalse((root / "thumb.jpg").exists())
            self.assertFalse(list(root.glob(".blob-*")))

    def test_source_size_and_md5_are_verified_before_mp4_commit(self) -> None:
        payload = b"\x00\x00\x00\x18ftypisom" + b"video"
        digest = hashlib.md5(payload, usedforsecurity=False).hexdigest()
        good_row = {
            "id": 7,
            "file_url": "https://media.example.test/video.mp4",
            "file_size": len(payload),
            "file_md5": digest,
        }
        with TemporaryDirectory() as raw:
            root = Path(raw)
            result = fetch_material_asset(
                FakeClient(row=good_row),
                "local",
                {},
                "id",
                7,
                "file",
                root / "video.mp4",
                _transport=FakeTransport(
                    FakeResponse(payload, content_type="video/mp4")
                ),
            )
            self.assertTrue(result["artifact"]["integrity"]["source_size_verified"])
            self.assertTrue(result["artifact"]["integrity"]["source_md5_verified"])
            self.assertEqual(hashlib.sha256(payload).hexdigest(), result["artifact"]["sha256"])

        bad_row = {**good_row, "file_md5": "0" * 32}
        with TemporaryDirectory() as raw:
            root = Path(raw)
            with self.assertRaises(ArtifactTransferError) as raised:
                fetch_material_asset(
                    FakeClient(row=bad_row),
                    "local",
                    {},
                    "id",
                    7,
                    "file",
                    root / "video.mp4",
                    _transport=FakeTransport(
                        FakeResponse(payload, content_type="video/mp4")
                    ),
                )
            self.assertEqual("ARTIFACT_DIGEST_MISMATCH", raised.exception.code)
            self.assertFalse((root / "video.mp4").exists())
            self.assertFalse(list(root.glob(".blob-*")))

    def test_public_result_redacts_transport_and_private_local_values(self) -> None:
        payload = b"\xff\xd8\xffprivate"
        with TemporaryDirectory() as raw:
            root = Path(raw)
            result = fetch_material_asset(
                FakeClient(with_receipt=True),
                "local",
                {"secret_filter": "private-input"},
                "id",
                7,
                "thumbnail",
                root / "thumb.jpg",
                _transport=FakeTransport(FakeResponse(payload)),
            )
            rendered = repr(result)
            for forbidden in (
                "https://",
                "private-input",
                str(root),
                "Authorization",
                "Cookie",
            ):
                self.assertNotIn(forbidden, rendered)
            self.assertEqual([SOURCE_RECEIPT], result["result_audit"]["http_receipts"])

    def test_cli_and_sdk_preserve_file_effect_with_optional_root(self) -> None:
        args = build_parser().parse_args([
            "materials",
            "fetch",
            "--source",
            "local",
            "--input",
            "{}",
            "--ref-field",
            "id",
            "--ref",
            "7",
            "--role",
            "thumbnail",
            "--output",
            "asset.jpg",
            "--output-root",
            "artifacts",
        ])
        self.assertTrue(args.product_file_output)
        self.assertEqual("artifacts", args.output_root)
        with TemporaryDirectory() as raw:
            root = Path(raw)
            output = root / "asset.jpg"

            def fake_fetch(*values, **options):
                output.write_bytes(b"binary")
                self.assertEqual(root, Path(options["output_root"]))
                return {
                    "schema_version": "gravity.material-asset.v2",
                    "ok": True,
                    "status": "success",
                }

            argv = [
                "materials",
                "fetch",
                "--source",
                "local",
                "--input",
                "{}",
                "--ref-field",
                "id",
                "--ref",
                "7",
                "--role",
                "thumbnail",
                "--output",
                str(output),
                "--output-root",
                str(root),
            ]
            with patch(
                "gravity_sdk.material_asset.fetch_material_asset", fake_fetch
            ), patch(
                "gravity_sdk.material_cli.runtime.build_client", return_value=object()
            ), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(0, main(argv))
            self.assertEqual(b"binary", output.read_bytes())

            sdk = GravitySDK(insight=object())
            sentinel = {"ok": True}
            with patch(
                "gravity_sdk.material_asset.fetch_material_asset",
                return_value=sentinel,
            ) as fetch:
                self.assertIs(
                    sentinel,
                    sdk.fetch_material_asset(
                        "local",
                        {},
                        "id",
                        7,
                        "thumbnail",
                        "asset.jpg",
                        output_root=root,
                    ),
                )
            self.assertEqual(root, fetch.call_args.kwargs["output_root"])


if __name__ == "__main__":
    unittest.main()
