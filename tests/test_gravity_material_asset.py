from __future__ import annotations

from copy import deepcopy
import hashlib
import inspect
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from gravity_insight.agent import discover_capabilities
from gravity_insight.artifact_transfer import (
    ArtifactTransferError,
    validate_artifact_transfer,
)
from gravity_insight.cli import build_parser, main
from gravity_insight.client import GravityInsightClient
from gravity_insight.errors import (
    ContractChangedError,
    InputValidationError,
    error_detail_from_exception,
    exit_code_for_error,
)
from gravity_insight.material_asset import fetch_material_asset
from gravity_insight.material_asset import (
    MaterialAssetSourceUnsupportedError,
    MaterialAssetUnavailableError,
)
from gravity_insight.material_asset_contract import _validate_sources, material_asset_contract
from gravity_insight.material_asset_transfer import MaterialAssetHttpError
from gravity_insight.result_audit import error_receipt_references
from gravity_insight.sdk import GravitySDK
from gravity_insight.transport import TransportResponse


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

    def _source_values(
        self, operation_id: str, inputs: dict[str, object]
    ) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
        self.calls.append((operation_id, inputs))
        if "url" in inputs:
            raise InputValidationError("unknown operation input fields: url", field="url")
        if self.row is not None:
            row = self.row
        elif self.source == "local":
            row = {
                "id": 7,
                "thumbnail_url": (
                    "https://tos-accelerate.gravity-engine.com/tenant/image/"
                    "video_thumbnail_url_asset.jpg"
                ),
            }
        else:
            row = {
                "material_id": 8,
                "file_url": (
                    "https://v26-cc.oceanengine.com/a/b/video/tos/cn/"
                    "tos-cn-ve-51/asset"
                ),
            }
        data_key = "list" if self.source == "local" else "video_material_list"
        public_row = {
            key: value for key, value in row.items() if key not in {"file_url", "thumbnail_url"}
        }
        result: dict[str, object] = {
            "status": "success",
            "data": {data_key: [public_row]},
        }
        if self.with_receipt:
            result["result_audit"] = {
                "schema_version": "gravity.result-audit.v1",
                "fact_paths": {},
                "http_receipts": [SOURCE_RECEIPT],
            }
        return result, (row,)

    def read(self, operation_id: str, inputs: dict[str, object]) -> dict[str, object]:
        return self._source_values(operation_id, inputs)[0]

    def _read_material_asset_source(
        self, operation_id: str, inputs: dict[str, object]
    ) -> tuple[dict[str, object], tuple[dict[str, object], ...]]:
        return self._source_values(operation_id, inputs)


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
        self.assertEqual("contract_allowlist", contract["initial_host_policy"])
        self.assertEqual("url_fields_omitted", contract["public_source_projection"])
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
        changed = deepcopy(contract["sources"])
        changed["bytedance_project"]["roles"]["file"]["allowed_sources"][0][
            "host"
        ] = "v27-cc.oceanengine.com"
        mutations.append(changed)
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(ContractChangedError):
                _validate_sources(value)

    def test_public_source_contracts_omit_both_private_url_fields(self) -> None:
        operation_root = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "gravity_insight"
            / "contracts"
            / "operations"
        )
        local = json.loads(
            (operation_root / "material.local.list.json").read_text(encoding="utf-8")
        )["operation"]
        project = json.loads(
            (
                operation_root / "material.bytedance.project_material.list.json"
            ).read_text(encoding="utf-8")
        )["operation"]
        self.assertEqual(4, local["contract_version"])
        self.assertEqual(4, project["contract_version"])
        for visible, omitted in (
            (
                local["response_projection"]["item_keys"],
                local["response_projection"]["known_omitted_item_keys"],
            ),
            (
                project["response_projection"]["data_item_keys"][
                    "video_material_list"
                ],
                project["response_projection"]["known_omitted_data_item_keys"][
                    "video_material_list"
                ],
            ),
        ):
            self.assertTrue({"file_url", "thumbnail_url"}.isdisjoint(visible))
            self.assertEqual({"file_url", "thumbnail_url"}, set(omitted))

    def test_bytedance_observed_video_and_thumbnail_origins_commit(self) -> None:
        row = {
            "material_id": 8,
            "file_url": (
                "https://v26-cc.oceanengine.com/a/b/video/tos/cn/"
                "tos-cn-ve-51/asset"
            ),
            "thumbnail_url": (
                "https://p26-sign.douyinpic.com/tos-cn-v-123/"
                "asset~tplv-noop.image?x-signature=private"
            ),
        }
        cases = (
            ("file", "asset.mp4", b"\x00\x00\x00\x18ftypisomvideo", "video/mp4"),
            ("thumbnail", "asset.jpg", b"\xff\xd8\xffimage", "image/jpeg"),
        )
        with TemporaryDirectory() as raw:
            root = Path(raw)
            for role, name, payload, content_type in cases:
                with self.subTest(role=role):
                    transport = FakeTransport(
                        FakeResponse(payload, content_type=content_type)
                    )
                    result = fetch_material_asset(
                        FakeClient(source="bytedance_project", row=row),
                        "bytedance_project",
                        {"advertiser_id": 1, "project_id": 2},
                        "material_id",
                        8,
                        role,
                        root / name,
                        _transport=transport,
                    )
                    self.assertEqual(payload, (root / name).read_bytes())
                    self.assertEqual(content_type, result["artifact"]["media_type"])
                    self.assertEqual(1, len(transport.download_calls))

    def test_unobserved_bytedance_shard_is_rejected_before_binary_network(self) -> None:
        client = FakeClient(
            source="bytedance_project",
            row={
                "material_id": 8,
                "file_url": (
                    "https://v27-cc.oceanengine.com/a/b/video/tos/cn/"
                    "tos-cn-ve-51/asset"
                ),
            },
        )
        transport = FakeTransport()
        with TemporaryDirectory() as raw:
            with self.assertRaises(MaterialAssetSourceUnsupportedError):
                fetch_material_asset(
                    client,
                    "bytedance_project",
                    {"advertiser_id": 1, "project_id": 2},
                    "material_id",
                    8,
                    "file",
                    Path(raw) / "asset.mp4",
                    _transport=transport,
                )
        self.assertEqual([], transport.download_calls)

    def test_fresh_reference_runs_through_schema_and_same_host_redirect(self) -> None:
        payload = b"\xff\xd8\xff" + b"a" * 29
        redirect = FakeResponse(
            status=302,
            headers={"Location": "/tenant/image/video_thumbnail_url_final.jpg"},
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
                "https://tos-accelerate.gravity-engine.com/tenant/image/"
                "video_thumbnail_url_asset.jpg",
                "https://tos-accelerate.gravity-engine.com/tenant/image/"
                "video_thumbnail_url_final.jpg",
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
        self.assertEqual("MATERIAL_ASSET_SOURCE_UNSUPPORTED", raised.exception.code)
        self.assertEqual("source_contract", raised.exception.reason_category)
        self.assertEqual(1, len(transport.download_calls))
        self.assertTrue(redirect.closed)

    def test_same_host_redirect_path_outside_contract_is_rejected(self) -> None:
        redirect = FakeResponse(
            status=302,
            headers={"Location": "/tenant/unregistered/asset.jpg"},
        )
        transport = FakeTransport(redirect)
        with TemporaryDirectory() as raw:
            output = Path(raw) / "thumb.jpg"
            with self.assertRaises(MaterialAssetSourceUnsupportedError) as raised:
                fetch_material_asset(
                    FakeClient(),
                    "local",
                    {},
                    "id",
                    7,
                    "thumbnail",
                    output,
                    _transport=transport,
                )
            self.assertFalse(output.exists())
        self.assertEqual("MATERIAL_ASSET_SOURCE_UNSUPPORTED", raised.exception.code)
        self.assertEqual(1, len(transport.download_calls))
        self.assertTrue(redirect.closed)

    def test_redirect_limit_is_enforced_without_final_commit(self) -> None:
        redirects = tuple(
            FakeResponse(
                status=302,
                headers={
                    "Location": (
                        f"/tenant/image/video_thumbnail_url_hop-{number}.jpg"
                    )
                },
            )
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

    def test_indistinguishable_terminal_asset_statuses_use_one_error(self) -> None:
        for status in (400, 401, 403, 404, 410):
            with self.subTest(status=status), TemporaryDirectory() as raw:
                with self.assertRaises(MaterialAssetUnavailableError) as raised:
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
                self.assertFalse(detail.retryable)
                self.assertEqual("MATERIAL_ASSET_BINARY_UNAVAILABLE", detail.code)
                self.assertEqual(
                    "indistinguishable_binary_unavailable",
                    raised.exception.reason_category,
                )
                self.assertNotIn(str(status), detail.message)

    def test_retryable_terminal_asset_statuses_keep_upstream_semantics(self) -> None:
        for status in (429, 503):
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
                self.assertTrue(detail.retryable)

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
        self.assertFalse(card["source_contract"]["public_source_urls"])
        self.assertEqual(
            "contract_allowlist", card["source_contract"]["initial_host_policy"]
        )
        self.assertEqual(
            ["advertiser_id", "project_id"],
            card["source_contract"]["source_inputs"]["bytedance_project"],
        )
        self.assertEqual(
            "MATERIAL_ASSET_BINARY_UNAVAILABLE",
            card["source_contract"]["unavailable_error"],
        )
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
            def _read_material_asset_source(self, operation_id, inputs):
                self.calls.append((operation_id, inputs))
                row = {
                    "id": 7,
                    "thumbnail_url": (
                        "https://tos-accelerate.gravity-engine.com/tenant/image/"
                        "video_thumbnail_url_asset.jpg"
                    ),
                }
                public = {"status": "success", "data": {"list": [{"id": 7}]}}
                return public, (row, dict(row))

        with TemporaryDirectory() as raw:
            root = Path(raw)
            for client, reference in (
                (FakeClient(with_receipt=True), 99),
                (DuplicateClient(), 7),
            ):
                with self.subTest(reference=reference, client=type(client).__name__):
                    transport = FakeTransport()
                    with self.assertRaises(MaterialAssetUnavailableError) as raised:
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
                "thumbnail_url": (
                    "https://tos-accelerate.gravity-engine.com/tenant/image/"
                    "video_thumbnail_url_asset.jpg"
                ),
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
            "file_url": (
                "https://tos-accelerate.gravity-engine.com/tenant/video/asset.mp4"
            ),
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

    def test_url_sentinel_stays_out_of_source_success_and_error_outputs(self) -> None:
        sentinel = "PRIVATE_URL_SENTINEL_19"
        private_url = (
            "https://tos-accelerate.gravity-engine.com/tenant/image/"
            f"video_thumbnail_url_{sentinel}.jpg?x-signature={sentinel}"
        )

        class SourceTransport:
            def __init__(self) -> None:
                self.calls = 0

            def request(self, *_args, **_kwargs):
                self.calls += 1
                return TransportResponse(
                    200,
                    {
                        "code": 0,
                        "data": {
                            "list": [{"id": 7, "thumbnail_url": private_url}]
                        },
                    },
                    "2026-08-30T00:00:00Z",
                )

        source_transport = SourceTransport()
        client = GravityInsightClient.from_env(transport=source_transport)
        public_source = client.read("material.local.list", {})
        self.assertEqual({"id": 7}, public_source["data"]["list"][0])

        with TemporaryDirectory() as raw:
            root = Path(raw)
            success = fetch_material_asset(
                client,
                "local",
                {},
                "id",
                7,
                "thumbnail",
                root / "success.jpg",
                _transport=FakeTransport(FakeResponse(b"\xff\xd8\xffsafe")),
            )
            with self.assertRaises(MaterialAssetUnavailableError) as raised:
                fetch_material_asset(
                    client,
                    "local",
                    {},
                    "id",
                    7,
                    "thumbnail",
                    root / "unavailable.jpg",
                    _transport=FakeTransport(FakeResponse(status=404)),
                )

        public_values = {
            "source": public_source,
            "success": success,
            "error": error_detail_from_exception(raised.exception).to_dict(),
            "error_receipts": error_receipt_references(raised.exception),
        }
        serialized = json.dumps(public_values, ensure_ascii=True, sort_keys=True)
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn(private_url, serialized)
        self.assertNotIn(sentinel, str(raised.exception))
        self.assertEqual(3, source_transport.calls)

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
                "gravity_insight.material_asset.fetch_material_asset", fake_fetch
            ), patch(
                "gravity_insight.material_cli.runtime.build_client", return_value=object()
            ), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(0, main(argv))
            self.assertEqual(b"binary", output.read_bytes())

            sdk = GravitySDK(insight=object())
            sentinel = {"ok": True}
            with patch(
                "gravity_insight.material_asset.fetch_material_asset",
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
