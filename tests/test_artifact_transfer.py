from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from gravity_insight.agent_runtime_contracts import AgentRuntimeContractError
from gravity_insight.artifact_transfer import (
    ArtifactTransferError,
    ArtifactTransferService,
    _ArtifactTypeContract,
    _RequestsArtifactTransport,
    _ResolvedArtifactSource,
    validate_artifact_transfer,
)
from gravity_insight.blob_models import MagicSignature


class Response:
    def __init__(
        self,
        data: bytes,
        *,
        include_length: bool = True,
    ) -> None:
        self.status_code = 200
        self.headers = {"Content-Type": "image/jpeg"}
        if include_length:
            self.headers["Content-Length"] = str(len(data))
        self.data = data
        self.closed = False

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield self.data

    def close(self) -> None:
        self.closed = True


class Transport:
    def __init__(self, *responses: Response) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def open_download(self, url, *, headers, timeout):
        del headers, timeout
        self.calls.append(url)
        if not self.responses:
            raise AssertionError("binary request must not run")
        return self.responses.pop(0)


class Session:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, object]]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def image_contract(max_bytes: int = 64) -> _ArtifactTypeContract:
    return _ArtifactTypeContract(
        media_type="image/jpeg",
        extensions=(".jpg",),
        magic_signatures={
            ".jpg": (MagicSignature(0, b"\xff\xd8\xff"),),
        },
        max_bytes=max_bytes,
        allowed_sources={"files.example.test": (r"^/source\.jpg$",)},
        max_redirects=1,
        timeout_seconds=5,
    )


def source(
    *,
    url: str = "https://files.example.test/source.jpg",
    declared_size: int | None = None,
) -> _ResolvedArtifactSource:
    return _ResolvedArtifactSource(
        url=url,
        source_capability="material.asset.fetch",
        source_operation_id="material.local.list",
        reference_field="id",
        reference_value=7,
        role="thumbnail",
        declared_size=declared_size,
    )


class ArtifactTransferTests(unittest.TestCase):
    def test_declared_and_stream_caps_fail_without_visible_partial_artifact(self) -> None:
        payload = b"\xff\xd8\xff" + b"x" * 8
        with TemporaryDirectory() as raw:
            root = Path(raw)
            transport = Transport()
            service = ArtifactTransferService(transport)
            prepared = service.prepare("image.jpg", image_contract(8), output_root=root)
            with self.assertRaises(ArtifactTransferError) as raised:
                service.transfer(prepared, source(declared_size=len(payload)))
            self.assertEqual("ARTIFACT_SIZE_LIMIT", raised.exception.code)
            self.assertEqual([], transport.calls)
            self.assertEqual([], list(root.iterdir()))

        with TemporaryDirectory() as raw:
            root = Path(raw)
            transport = Transport(Response(payload, include_length=False))
            service = ArtifactTransferService(transport)
            prepared = service.prepare("image.jpg", image_contract(8), output_root=root)
            with self.assertRaises(ArtifactTransferError) as raised:
                service.transfer(prepared, source())
            self.assertEqual("ARTIFACT_SIZE_LIMIT", raised.exception.code)
            self.assertFalse((root / "image.jpg").exists())
            self.assertFalse(list(root.glob(".blob-*")))

    def test_non_https_or_authority_url_is_rejected_before_binary_request(self) -> None:
        urls = (
            "http://files.example.test/source.jpg",
            "https:///source.jpg",
            "https://user:secret@files.example.test/source.jpg",
            "https://files.example.test/source.jpg#fragment",
        )
        with TemporaryDirectory() as raw:
            root = Path(raw)
            for url in urls:
                with self.subTest(url=url):
                    transport = Transport()
                    service = ArtifactTransferService(transport)
                    prepared = service.prepare(
                        "image.jpg", image_contract(), output_root=root
                    )
                    with self.assertRaises(ArtifactTransferError) as raised:
                        service.transfer(prepared, source(url=url))
                    self.assertEqual("ARTIFACT_SOURCE_DENIED", raised.exception.code)
                    self.assertEqual([], transport.calls)
                    self.assertFalse((root / "image.jpg").exists())

    def test_default_http_transport_returns_only_opaque_receipt_reference(self) -> None:
        payload = b"\xff\xd8\xffreceipt"
        response = Response(payload)
        session = Session(response)
        with TemporaryDirectory() as raw:
            root = Path(raw)
            state = root / "state"
            service = ArtifactTransferService(
                _RequestsArtifactTransport("material.asset.fetch", session=session)
            )
            prepared = service.prepare(
                "image.jpg", image_contract(), output_root=root
            )
            with patch("gravity_insight.artifact_transfer.STATE_ROOT", state):
                outcome = service.transfer(prepared, source())
            self.assertEqual(payload, (root / "image.jpg").read_bytes())
            self.assertEqual(1, len(outcome.receipt_references))
            reference = outcome.receipt_references[0]
            self.assertEqual({"receipt_id", "storage_status"}, set(reference))
            receipts = list((state / "receipts" / "http").glob("*.json"))
            self.assertEqual(1, len(receipts))
            stored = receipts[0].read_text(encoding="utf-8")
            self.assertNotIn("files.example.test", stored)
            self.assertNotIn("source.jpg", stored)
            self.assertFalse(session.calls[0][1]["allow_redirects"])
            self.assertEqual("identity", session.calls[0][1]["headers"]["Accept-Encoding"])

    def test_schema_rejects_identity_path_privacy_and_limitation_tamper(self) -> None:
        payload = b"\xff\xd8\xffschema"
        with TemporaryDirectory() as raw:
            root = Path(raw)
            service = ArtifactTransferService(Transport(Response(payload)))
            prepared = service.prepare(
                "image.jpg", image_contract(), output_root=root
            )
            artifact = service.transfer(prepared, source()).artifact
        validate_artifact_transfer(artifact)
        cases = []
        changed = deepcopy(artifact)
        changed["local_ref"] = "../escape.jpg"
        cases.append(changed)
        changed = deepcopy(artifact)
        changed["artifact_id"] = "sha256:" + "0" * 64
        cases.append(changed)
        changed = deepcopy(artifact)
        changed["source"]["url"] = "https://secret.invalid"
        cases.append(changed)
        changed = deepcopy(artifact)
        changed["limitations"].reverse()
        cases.append(changed)
        changed = deepcopy(artifact)
        changed["media_type"] = "video/mp4"
        cases.append(changed)
        changed = deepcopy(artifact)
        changed["transfer"]["final_host_family"] = "other.example.test"
        cases.append(changed)
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(AgentRuntimeContractError):
                    validate_artifact_transfer(value)

    def test_metadata_schema_failure_happens_before_atomic_commit(self) -> None:
        payload = b"\xff\xd8\xffschema"
        with TemporaryDirectory() as raw:
            root = Path(raw)
            service = ArtifactTransferService(Transport(Response(payload)))
            prepared = service.prepare(
                "image.jpg", image_contract(), output_root=root
            )
            with patch(
                "gravity_insight.artifact_transfer.validate_artifact_transfer",
                side_effect=AgentRuntimeContractError("tampered schema"),
            ), self.assertRaises(ArtifactTransferError) as raised:
                service.transfer(prepared, source())
            self.assertEqual("ARTIFACT_CONTRACT_CHANGED", raised.exception.code)
            self.assertFalse((root / "image.jpg").exists())
            self.assertFalse(list(root.glob(".blob-*")))


if __name__ == "__main__":
    unittest.main()
