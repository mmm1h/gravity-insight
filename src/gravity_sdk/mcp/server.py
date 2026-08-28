"""Minimal stable MCP JSON-RPC 2.0 server over local stdio."""

from __future__ import annotations

import contextlib
import io
import json
import sys
from collections.abc import Mapping
from typing import Any, TextIO

from ..agent_runtime_contracts import canonical_digest
from .analysis_tools import AnalysisTools
from .product_tools import ProductTools
from .resources import ResourceCatalog, ResourceError, resource_contract
from .results import call_tool_result, exception_tool_result
from .schemas import MAX_OUTPUT_BYTES, MCPInputError, validate_arguments
from .tool_catalog import tool_catalog, tool_definition


PROTOCOL_VERSION = "2026-07-28"
SERVER_NAME = "gravity-runtime"
SERVER_VERSION = "0.1.0-experimental"
METADATA_SCHEMA_VERSION = "gravity.mcp-server-metadata.v1"
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603
_UNSUPPORTED_PROTOCOL_VERSION = -32022
_PROTOCOL_VERSION_KEY = "io.modelcontextprotocol/protocolVersion"
_CLIENT_INFO_KEY = "io.modelcontextprotocol/clientInfo"
_CLIENT_CAPABILITIES_KEY = "io.modelcontextprotocol/clientCapabilities"
_SERVER_INFO_KEY = "io.modelcontextprotocol/serverInfo"


class MCPProtocolError(ValueError):
    def __init__(
        self,
        code: int,
        message: str,
        data: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = dict(data) if data is not None else None


def server_metadata() -> dict[str, Any]:
    tools = tool_catalog()
    resources = resource_contract()
    payload = {
        "schema_version": METADATA_SCHEMA_VERSION,
        "name": SERVER_NAME,
        "version": SERVER_VERSION,
        "lifecycle": "experimental",
        "protocol_versions": [PROTOCOL_VERSION],
        "transports": ["stdio"],
        "entry_point": "gravity-mcp",
        "tool_catalog_fingerprint": tools["fingerprint"],
        "resource_catalog_fingerprint": resources["fingerprint"],
        "rollback": "remove_adapter_without_data_migration",
    }
    payload["fingerprint"] = canonical_digest(payload)
    return payload


class MCPServer:
    def __init__(
        self,
        sdk: Any,
        *,
        resources: ResourceCatalog | None = None,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
    ) -> None:
        self._sdk = sdk
        self._stdin = stdin or sys.stdin
        self._stdout = stdout or sys.stdout
        self._stderr = stderr or sys.stderr
        self._analysis = AnalysisTools(sdk, metadata=server_metadata)
        self._products = ProductTools(sdk)
        self._resources = resources or ResourceCatalog(
            sdk, metadata=server_metadata
        )
        self._handlers = {
            "gravity.inspect": self._analysis.inspect,
            "gravity.journey_can_run": self._analysis.journey_can_run,
            "gravity.capability_describe": self._analysis.capability_describe,
            "gravity.execute": self._analysis.execute,
            "gravity.export": self._products.export,
            "gravity.context_pack": self._products.context_pack,
        }

    def serve_forever(self) -> int:
        for line in self._stdin:
            if not line.strip():
                continue
            response = self.process_line(line)
            if response is not None:
                self._write(response)
        return 0

    def process_line(self, line: str) -> dict[str, Any] | None:
        try:
            message = json.loads(line)
        except (json.JSONDecodeError, UnicodeError):
            return _error_response(None, _PARSE_ERROR, "Parse error")
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                return self.handle(message)
        except MCPProtocolError as exc:
            request_id = message.get("id") if isinstance(message, Mapping) else None
            return _error_response(request_id, exc.code, exc.message, exc.data)
        except Exception:
            self._log("internal protocol adapter failure")
            request_id = message.get("id") if isinstance(message, Mapping) else None
            return _error_response(request_id, _INTERNAL_ERROR, "Internal error")
        finally:
            if captured.getvalue():
                self._log("suppressed non-protocol handler stdout")

    def handle(self, message: Any) -> dict[str, Any] | None:
        request_id, method, params = _request(message)
        if method == "initialize":
            raise MCPProtocolError(
                _METHOD_NOT_FOUND,
                "Initialization is unavailable on this modern MCP server",
                {"supportedVersions": [PROTOCOL_VERSION]},
            )
        _request_metadata(params)
        if method == "server/discover":
            return _success_response(request_id, self._discover())
        if method == "notifications/cancelled":
            return None
        if method == "ping":
            return _success_response(request_id, {})
        if method == "tools/list":
            return _success_response(request_id, {"tools": tool_catalog()["tools"]})
        if method == "tools/call":
            return _success_response(request_id, self._call_tool(params))
        if method == "resources/list":
            return _success_response(
                request_id, self._resources.list(params.get("cursor"))
            )
        if method == "resources/templates/list":
            return _success_response(request_id, self._resources.templates())
        if method == "resources/read":
            return _success_response(request_id, self._read_resource(params))
        if request_id is None:
            return None
        raise MCPProtocolError(_METHOD_NOT_FOUND, "Method not found")

    def _discover(self) -> dict[str, Any]:
        return {
            "supportedVersions": [PROTOCOL_VERSION],
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
            },
            "instructions": "Use registered Journey Tools and governed Resources; raw operations are unavailable.",
        }

    def _call_tool(self, params: Mapping[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or tool_definition(name) is None:
            raise MCPProtocolError(_INVALID_PARAMS, "Unknown Tool")
        requested_maximum = (
            arguments.get("max_output_bytes")
            if isinstance(arguments, Mapping)
            else None
        )
        maximum = (
            requested_maximum
            if isinstance(requested_maximum, int)
            and not isinstance(requested_maximum, bool)
            and 1_024 <= requested_maximum <= MAX_OUTPUT_BYTES
            else MAX_OUTPUT_BYTES
        )
        try:
            selected = validate_arguments(name, arguments)
            value = self._handlers[name](selected)
            if not isinstance(value, Mapping):
                raise MCPInputError("Tool owner returned a non-object result")
            return call_tool_result(
                name,
                value,
                max_bytes=maximum,
                execution=name in {"gravity.execute", "gravity.export"},
            )
        except Exception as exc:
            return exception_tool_result(name, exc, max_bytes=maximum)

    def _read_resource(self, params: Mapping[str, Any]) -> dict[str, Any]:
        uri = params.get("uri")
        if not isinstance(uri, str):
            raise MCPProtocolError(_INVALID_PARAMS, "Resource URI is required")
        try:
            value = self._resources.read(uri)
        except ResourceError as exc:
            raise MCPProtocolError(_INVALID_PARAMS, "Resource is unavailable") from exc
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(
                        value,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                        allow_nan=False,
                    ),
                }
            ]
        }

    def _write(self, response: Mapping[str, Any]) -> None:
        frame = json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        self._stdout.write(frame + "\n")
        self._stdout.flush()

    def _log(self, message: str) -> None:
        self._stderr.write(f"gravity-mcp: {message}\n")
        self._stderr.flush()


def _request(message: Any) -> tuple[str | int | None, str, dict[str, Any]]:
    if not isinstance(message, Mapping) or message.get("jsonrpc") != "2.0":
        raise MCPProtocolError(_INVALID_REQUEST, "Invalid Request")
    request_id = message.get("id")
    if isinstance(request_id, bool) or request_id is not None and not isinstance(
        request_id, (str, int)
    ):
        raise MCPProtocolError(_INVALID_REQUEST, "Invalid Request")
    method = message.get("method")
    params = message.get("params", {})
    if not isinstance(method, str) or not isinstance(params, Mapping):
        raise MCPProtocolError(_INVALID_REQUEST, "Invalid Request")
    return request_id, method, dict(params)


def _request_metadata(params: Mapping[str, Any]) -> None:
    metadata = params.get("_meta")
    if not isinstance(metadata, Mapping):
        raise MCPProtocolError(_INVALID_PARAMS, "Required request metadata is missing")
    version = metadata.get(_PROTOCOL_VERSION_KEY)
    if version != PROTOCOL_VERSION:
        raise MCPProtocolError(
            _UNSUPPORTED_PROTOCOL_VERSION,
            "Unsupported protocol version",
            {"supported": [PROTOCOL_VERSION], "requested": version},
        )
    capabilities = metadata.get(_CLIENT_CAPABILITIES_KEY)
    client = metadata.get(_CLIENT_INFO_KEY)
    if not isinstance(capabilities, Mapping) or (
        client is not None and not isinstance(client, Mapping)
    ):
        raise MCPProtocolError(_INVALID_PARAMS, "Required request metadata is invalid")


def _success_response(request_id: Any, result: Mapping[str, Any]) -> dict[str, Any] | None:
    if request_id is None:
        return None
    selected = dict(result)
    selected.setdefault("resultType", "complete")
    metadata = selected.setdefault("_meta", {})
    metadata[_SERVER_INFO_KEY] = {"name": SERVER_NAME, "version": SERVER_VERSION}
    return {"jsonrpc": "2.0", "id": request_id, "result": selected}


def _error_response(
    request_id: Any,
    code: int,
    message: str,
    data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = dict(data)
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": error,
    }


def main() -> int:
    captured = io.StringIO()
    try:
        from ..sdk import GravitySDK

        with contextlib.redirect_stdout(captured):
            sdk = GravitySDK.from_env(attempts=1)
        if captured.getvalue():
            sys.stderr.write("gravity-mcp: suppressed non-protocol startup stdout\n")
            sys.stderr.flush()
            captured = io.StringIO()
        return MCPServer(sdk).serve_forever()
    except Exception:
        if captured.getvalue():
            sys.stderr.write("gravity-mcp: suppressed non-protocol startup stdout\n")
        sys.stderr.write("gravity-mcp: startup failed\n")
        sys.stderr.flush()
        return 1


__all__ = [
    "MCPProtocolError",
    "MCPServer",
    "METADATA_SCHEMA_VERSION",
    "PROTOCOL_VERSION",
    "SERVER_NAME",
    "SERVER_VERSION",
    "main",
    "server_metadata",
]
