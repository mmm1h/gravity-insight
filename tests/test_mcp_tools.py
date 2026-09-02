from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from gravity_insight import GravitySDK
from gravity_insight.mcp.results import call_tool_result
from gravity_insight.mcp.server import MCPServer
from gravity_insight.mcp.tool_catalog import tool_catalog
from tests.test_mcp_protocol import request_params
from tests.test_analysis_result_contract import success_result
from tests.test_repo_context_provider import (
    ALIASES,
    WINDOWS,
    TemporaryGitRepo,
    context_item,
    context_requirement,
)


def initialized_server(sdk) -> MCPServer:
    return MCPServer(sdk)


def tool_call(server: MCPServer, name: str, arguments: dict) -> dict:
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": request_params(name=name, arguments=arguments),
        }
    )
    return response["result"]


class MCPToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        workspace = SimpleNamespace(root=root, state_root=root / "state", apps={})
        self.network_calls = 0

        def network_client():
            self.network_calls += 1
            raise AssertionError("Tool constructed a target client")

        self.sdk = GravitySDK(
            workspace=workspace,
            insight_factory=network_client,
            sql_factory=network_client,
        )
        self.server = initialized_server(self.sdk)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_inspect_can_run_describe_and_execute_delegate_existing_services(self) -> None:
        inspected = tool_call(
            self.server, "gravity.inspect", {"kind": "journey"}
        )
        readiness = tool_call(
            self.server,
            "gravity.journey_can_run",
            {"journey_id": "analysis.event-trend", "inputs": {}},
        )
        trust = tool_call(
            self.server,
            "gravity.capability_describe",
            {"identity_kind": "product", "selector": "analysis.query.spec:event"},
        )
        execution = tool_call(
            self.server,
            "gravity.execute",
            {"journey_id": "analysis.event-trend", "inputs": {}},
        )

        self.assertEqual(11, inspected["structuredContent"]["result"]["count"])
        self.assertEqual(
            "blocked", readiness["structuredContent"]["result"]["can_run_status"]
        )
        self.assertEqual(
            "analysis.query.spec:event",
            trust["structuredContent"]["result"]["selector"],
        )
        self.assertEqual("blocked", execution["structuredContent"]["result"]["status"])
        self.assertFalse(readiness["isError"])
        self.assertTrue(execution["isError"])
        self.assertEqual(0, self.network_calls)

    def test_skill_inspection_reads_synced_hub_state_without_target_network(self) -> None:
        inspected = tool_call(self.server, "gravity.inspect", {"kind": "skill"})

        result = inspected["structuredContent"]["result"]
        self.assertEqual("gravity.skill-hub-list.v1", result["schema_version"])
        self.assertEqual(0, result["count"])
        self.assertFalse(result["network_called"])
        self.assertEqual(0, self.network_calls)

    def test_execute_rejects_raw_operation_shape_before_network(self) -> None:
        result = tool_call(
            self.server,
            "gravity.execute",
            {"operation": "analysis.event.query", "inputs": {}},
        )

        self.assertTrue(result["isError"])
        self.assertEqual(
            "MCP_INPUT_INVALID",
            result["structuredContent"]["result"]["error"]["code"],
        )
        self.assertEqual(0, self.network_calls)

    def test_export_uses_governed_analysis_artifact_local_delivery(self) -> None:
        destination = Path(self.temporary.name) / "analysis.json"
        result = tool_call(
            self.server,
            "gravity.export",
            {
                "analysis_result": success_result(),
                "format": "json",
                "destination": str(destination),
                "confirm": True,
            },
        )

        receipt = result["structuredContent"]["result"]
        self.assertFalse(result["isError"])
        self.assertEqual("written", receipt["status"])
        self.assertTrue(destination.is_file())
        self.assertFalse(receipt["network_called"])
        self.assertEqual(0, self.network_calls)

    def test_export_requires_explicit_confirmation_before_local_mutation(self) -> None:
        destination = Path(self.temporary.name) / "unconfirmed.json"
        for confirmation in (None, False, 1):
            with self.subTest(confirmation=confirmation):
                arguments = {
                    "analysis_result": success_result(),
                    "format": "json",
                    "destination": str(destination),
                }
                if confirmation is not None:
                    arguments["confirm"] = confirmation
                result = tool_call(self.server, "gravity.export", arguments)
                self.assertTrue(result["isError"])
                self.assertEqual(
                    "MCP_INPUT_INVALID",
                    result["structuredContent"]["result"]["error"]["code"],
                )
        self.assertFalse(destination.exists())
        self.assertEqual(0, self.network_calls)

    def test_effect_annotations_are_frozen_and_never_authorize_execution(self) -> None:
        catalog = tool_catalog()
        annotations = {
            item["name"]: item["annotations"] for item in catalog["tools"]
        }
        self.assertEqual(
            {
                "gravity.inspect": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "gravity.journey_can_run": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "gravity.capability_describe": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
                "gravity.execute": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
                "gravity.export": {
                    "readOnlyHint": False,
                    "destructiveHint": False,
                    "idempotentHint": False,
                    "openWorldHint": False,
                },
                "gravity.context_pack": {
                    "readOnlyHint": True,
                    "destructiveHint": False,
                    "idempotentHint": True,
                    "openWorldHint": False,
                },
            },
            annotations,
        )

        annotations["gravity.export"].update(
            readOnlyHint=True, destructiveHint=False, idempotentHint=True
        )
        destination = Path(self.temporary.name) / "annotation-bypass.json"
        result = tool_call(
            self.server,
            "gravity.export",
            {
                "analysis_result": success_result(),
                "format": "json",
                "destination": str(destination),
            },
        )

        self.assertTrue(result["isError"])
        self.assertEqual(
            "MCP_INPUT_INVALID",
            result["structuredContent"]["result"]["error"]["code"],
        )
        self.assertFalse(destination.exists())
        self.assertFalse(
            next(
                item
                for item in tool_catalog()["tools"]
                if item["name"] == "gravity.export"
            )["annotations"]["readOnlyHint"]
        )
        self.assertEqual(0, self.network_calls)

    def test_context_pack_delegates_public_repo_provider_offline(self) -> None:
        repo = TemporaryGitRepo()
        self.addCleanup(repo.close)
        repo.write("docs/context.md", "# Current context\n")
        repo.commit()

        result = tool_call(
            self.server,
            "gravity.context_pack",
            {
                "root": str(repo.root),
                "project_id": "demo",
                "requirement": context_requirement(
                    [context_item("current", "docs/context.md")]
                ),
                "requested_time": WINDOWS,
                "entity_aliases": ALIASES,
            },
        )

        pack = result["structuredContent"]["result"]
        self.assertFalse(result["isError"])
        self.assertEqual("available", pack["status"])
        self.assertEqual(1, len(pack["items"]))
        self.assertFalse(pack["network_called"])
        self.assertEqual(0, self.network_calls)

    def test_result_mapping_preserves_empty_partial_and_domain_error_states(self) -> None:
        cases = (
            ({"schema_version": "x", "ok": True, "status": "empty"}, False),
            ({"schema_version": "x", "ok": True, "status": "partial"}, False),
            ({"schema_version": "x", "ok": False, "status": "blocked"}, True),
        )
        for domain, expected_error in cases:
            with self.subTest(status=domain["status"]):
                result = call_tool_result(
                    "gravity.execute", domain, execution=True
                )
                self.assertEqual(domain, result["structuredContent"]["result"])
                self.assertIs(expected_error, result["isError"])


if __name__ == "__main__":
    unittest.main()
