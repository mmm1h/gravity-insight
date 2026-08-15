from __future__ import annotations

import io
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gravity_sdk.agent import discover_capabilities
from gravity_sdk.cli import build_parser, main
from gravity_sdk.errors import InputValidationError, error_detail_from_exception, exit_code_for_error
from gravity_sdk.material_asset import fetch_material_asset
from gravity_sdk.material_asset_transfer import MaterialAssetHttpError


class FakeClient:
    def __init__(self, source: str = "local") -> None:
        self.source = source
        self.calls: list[tuple[str, dict[str, object]]] = []

    def read(self, operation_id: str, inputs: dict[str, object]) -> dict[str, object]:
        self.calls.append((operation_id, inputs))
        if "url" in inputs:
            raise InputValidationError("unknown operation input fields: url", field="url")
        if self.source == "local":
            data = {"list": [{
                "id": 7,
                "thumbnail_url": "https://unlisted.example.test/thumb.jpg",
            }]}
        else:
            data = {"video_material_list": [{
                "material_id": 8,
                "file_url": "https://v99-anywhere.example.test/video.mp4",
            }]}
        return {"status": "success", "data": data}


class FakeResponse:
    def __init__(
        self, data: bytes = b"", *, status: int = 200,
        content_type: str = "image/jpeg", final_url: str | None = None,
    ) -> None:
        self.data = data
        self.status_code = status
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(data))}
        self.url = final_url or "https://unlisted.example.test/thumb.jpg"
        self.history = [SimpleNamespace(status_code=302)] if final_url else []
        self.closed = False

    def iter_content(self, chunk_size: int):
        yield self.data

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.urls: list[str] = []

    def open_download(self, url: str, *, timeout: float) -> FakeResponse:
        self.urls.append(url)
        return self.response


class MaterialAssetTests(unittest.TestCase):
    def test_fresh_response_url_downloads_fully_without_host_gate(self) -> None:
        payload = b"\xff\xd8\xff" + b"a" * 29
        response = FakeResponse(
            payload, final_url="https://p77-cdn.example.test/final.jpg"
        )
        transport = FakeTransport(response)
        with TemporaryDirectory() as raw:
            output = Path(raw) / "thumb.jpg"
            result = fetch_material_asset(
                FakeClient(), "local", {"page": 1}, "id", "7", "thumbnail",
                output, _transport=transport,
            )
            self.assertEqual(payload, output.read_bytes())
        self.assertEqual(
            ["https://unlisted.example.test/thumb.jpg"], transport.urls
        )
        self.assertTrue(result["file"]["complete"])
        self.assertEqual(1, result["file"]["redirect_count"])
        self.assertTrue(result["file"]["cross_host_redirect"])
        self.assertNotIn("url", result["file"])
        self.assertTrue(response.closed)

    def test_http_statuses_are_upstream_without_invented_asset_states(self) -> None:
        for status, retryable in ((403, False), (404, False), (410, False), (429, True), (503, True)):
            with self.subTest(status=status), TemporaryDirectory() as raw:
                with self.assertRaises(MaterialAssetHttpError) as raised:
                    fetch_material_asset(
                        FakeClient(), "local", {}, "id", 7, "thumbnail",
                        Path(raw) / "thumb.jpg",
                        _transport=FakeTransport(FakeResponse(status=status)),
                    )
                detail = error_detail_from_exception(raised.exception)
                self.assertEqual("upstream", detail.category)
                self.assertEqual(3, exit_code_for_error(raised.exception))
                self.assertEqual(retryable, detail.retryable)
                self.assertIn(f"HTTP {status}", detail.message)

    def test_caller_cannot_supply_a_url_and_agent_handoff_has_no_url_slot(self) -> None:
        transport = FakeTransport(FakeResponse(b"\xff\xd8\xff"))
        with TemporaryDirectory() as raw, self.assertRaises(InputValidationError):
            fetch_material_asset(
                FakeClient(), "local", {"url": "https://caller.invalid"},
                "id", 7, "thumbnail", Path(raw) / "thumb.jpg",
                _transport=transport,
            )
        self.assertEqual([], transport.urls)
        found = discover_capabilities(
            "下载精确平台素材视频文件", client=object()
        )
        card = found["candidates"][0]
        self.assertEqual("material.asset.fetch", card["selector"])
        self.assertIsNone(card["plan_node"])
        self.assertFalse(card["source_contract"]["accepts_caller_url"])
        self.assertNotIn("url", card["required_inputs"])

    def test_cli_marks_output_as_the_product_file(self) -> None:
        args = build_parser().parse_args([
            "materials", "fetch", "--source", "local", "--input", "{}",
            "--ref-field", "id", "--ref", "7", "--role", "thumbnail",
            "--output", "asset.jpg",
        ])
        self.assertTrue(args.product_file_output)
        with TemporaryDirectory() as raw:
            output = Path(raw) / "asset.jpg"

            def fake_fetch(*values, **options):
                output.write_bytes(b"binary")
                return {"schema_version": "gravity.material-asset.v1", "ok": True, "status": "success"}

            argv = [
                "materials", "fetch", "--source", "local", "--input", "{}",
                "--ref-field", "id", "--ref", "7", "--role", "thumbnail",
                "--output", str(output),
            ]
            with patch("gravity_sdk.material_asset.fetch_material_asset", fake_fetch), patch(
                "gravity_sdk.material_cli.runtime.build_client", return_value=object()
            ), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(0, main(argv))
            self.assertEqual(b"binary", output.read_bytes())


if __name__ == "__main__":
    unittest.main()
