from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from gravity_sdk import GravitySDK
from gravity_sdk.mcp.server import MCPServer, PROTOCOL_VERSION, main


def request_params(**values) -> dict:
    return {
        **values,
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
            "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1"},
            "io.modelcontextprotocol/clientCapabilities": {},
        },
    }


def discover(server: MCPServer) -> dict:
    return server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "server/discover",
            "params": request_params(),
        }
    )


def call(server: MCPServer, name: str, arguments: dict) -> dict:
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": request_params(name=name, arguments=arguments),
        }
    )
    return response["result"]


class MCPProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        workspace = SimpleNamespace(root=root, state_root=root / "state", apps={})
        self.network_calls = 0

        def network_client():
            self.network_calls += 1
            raise AssertionError("MCP offline path constructed a target client")

        self.sdk = GravitySDK(
            workspace=workspace,
            insight_factory=network_client,
            sql_factory=network_client,
        )
        self.server = MCPServer(self.sdk)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_discovery_and_atomic_tool_catalog_are_protocol_conformant(self) -> None:
        discovered = discover(self.server)
        listed = self.server.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/list",
                "params": request_params(),
            }
        )

        self.assertEqual(
            [PROTOCOL_VERSION], discovered["result"]["supportedVersions"]
        )
        self.assertEqual("complete", discovered["result"]["resultType"])
        self.assertIn(
            "io.modelcontextprotocol/serverInfo", discovered["result"]["_meta"]
        )
        names = [item["name"] for item in listed["result"]["tools"]]
        self.assertEqual(
            [
                "gravity.inspect",
                "gravity.journey_can_run",
                "gravity.capability_describe",
                "gravity.execute",
                "gravity.export",
                "gravity.context_pack",
            ],
            names,
        )
        tools = {item["name"]: item for item in listed["result"]["tools"]}
        inspect_branches = tools["gravity.inspect"]["inputSchema"]["oneOf"]
        inspect_kinds = {
            branch["properties"]["kind"]["const"]: branch for branch in inspect_branches
        }
        self.assertIn(
            "installed versioned workflow",
            inspect_kinds["skill"]["properties"]["kind"]["description"],
        )
        self.assertIn(
            "registered business task",
            inspect_kinds["journey"]["properties"]["kind"]["description"],
        )
        identity_description = tools["gravity.capability_describe"]["inputSchema"][
            "properties"
        ]["identity_kind"]["description"]
        for concept in ("atomic wire contract", "question-level", "multi-component"):
            self.assertIn(concept, identity_description)
        for tool in listed["result"]["tools"]:
            self.assertEqual(
                "https://json-schema.org/draft/2020-12/schema",
                tool["inputSchema"]["$schema"],
            )
            self.assertEqual(
                "https://json-schema.org/draft/2020-12/schema",
                tool["outputSchema"]["$schema"],
            )
        self.assertEqual(0, self.network_calls)

    def test_malformed_and_unsupported_requests_use_json_rpc_errors(self) -> None:
        parse_error = self.server.process_line("{not-json\n")
        batch_error = self.server.process_line("[]\n")
        missing_metadata = self.server.process_line(
            '{"jsonrpc":"2.0","id":4,"method":"tools/list","params":{}}\n'
        )
        legacy = self.server.process_line(
            '{"jsonrpc":"2.0","id":6,"method":"initialize","params":{}}\n'
        )
        unsupported = self.server.process_line(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/list",
                    "params": {
                        "_meta": {
                            "io.modelcontextprotocol/protocolVersion": "1900-01-01",
                            "io.modelcontextprotocol/clientCapabilities": {},
                        }
                    },
                }
            )
        )

        self.assertEqual(-32700, parse_error["error"]["code"])
        self.assertEqual(-32600, batch_error["error"]["code"])
        self.assertEqual(-32602, missing_metadata["error"]["code"])
        self.assertEqual(
            [PROTOCOL_VERSION], legacy["error"]["data"]["supportedVersions"]
        )
        self.assertEqual(-32022, unsupported["error"]["code"])
        self.assertEqual(
            [PROTOCOL_VERSION], unsupported["error"]["data"]["supported"]
        )
        self.assertEqual(0, self.network_calls)

    def test_invalid_and_blocked_tool_calls_make_zero_target_requests(self) -> None:
        invalid = call(
            self.server,
            "gravity.execute",
            {"journey_id": "analysis.event-trend"},
        )
        blocked = call(
            self.server,
            "gravity.execute",
            {"journey_id": "analysis.event-trend", "inputs": {}},
        )

        self.assertTrue(invalid["isError"])
        self.assertEqual(
            "MCP_INPUT_INVALID",
            invalid["structuredContent"]["result"]["error"]["code"],
        )
        self.assertTrue(blocked["isError"])
        self.assertEqual("blocked", blocked["structuredContent"]["result"]["status"])
        self.assertEqual(0, self.network_calls)

    def test_result_budget_rejects_without_serializing_the_large_value(self) -> None:
        class Journeys:
            def can_run(self, *_args):
                return {"status": "success", "payload": "x" * 10_000}

        self.sdk._journey_service = Journeys()
        result = call(
            self.server,
            "gravity.journey_can_run",
            {
                "journey_id": "analysis.event-trend",
                "max_output_bytes": 1_024,
            },
        )

        self.assertTrue(result["isError"])
        self.assertEqual(
            "MCP_OUTPUT_BUDGET_EXCEEDED",
            result["structuredContent"]["result"]["error"]["code"],
        )

    def test_stdio_stdout_contains_frames_only_and_stderr_is_value_free(self) -> None:
        secret = "token=do-not-log"

        class Journeys:
            def list(self):
                print(secret)
                return {"schema_version": "test.v1", "status": "success"}

        class Trust:
            def trust(self, *_args):
                return {"status": "unknown"}

        class SDK:
            workspace = SimpleNamespace(root=Path.cwd(), state_root=Path("tmp"), apps={})
            journeys = Journeys()
            capability_trust = Trust()

            def capabilities(self, **_options):
                print(secret)
                return {"status": "success"}

        frames = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": request_params(),
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": request_params(
                    name="gravity.inspect", arguments={"kind": "journey"}
                ),
            },
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "resources/read",
                "params": request_params(uri="gravity://catalog/capabilities"),
            },
        ]
        stdin = io.StringIO("".join(json.dumps(item) + "\n" for item in frames))
        stdout, stderr = io.StringIO(), io.StringIO()

        code = MCPServer(SDK(), stdin=stdin, stdout=stdout, stderr=stderr).serve_forever()

        rendered = stdout.getvalue().splitlines()
        self.assertEqual(0, code)
        self.assertEqual(3, len(rendered))
        self.assertTrue(all(json.loads(line)["jsonrpc"] == "2.0" for line in rendered))
        self.assertNotIn(secret, stdout.getvalue())
        self.assertNotIn(secret, stderr.getvalue())
        self.assertEqual(
            2, stderr.getvalue().count("suppressed non-protocol handler stdout")
        )

    def test_entry_point_suppresses_startup_stdout_without_leaking_values(self) -> None:
        secret = "token=startup-secret"
        stdout, stderr = io.StringIO(), io.StringIO()

        def sdk_from_env(**_options):
            print(secret)
            return self.sdk

        with (
            patch("gravity_sdk.sdk.GravitySDK.from_env", side_effect=sdk_from_env),
            patch("sys.stdin", io.StringIO()),
            patch("sys.stdout", stdout),
            patch("sys.stderr", stderr),
        ):
            code = main()

        self.assertEqual(0, code)
        self.assertEqual("", stdout.getvalue())
        self.assertNotIn(secret, stderr.getvalue())
        self.assertEqual(
            "gravity-mcp: suppressed non-protocol startup stdout\n",
            stderr.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
