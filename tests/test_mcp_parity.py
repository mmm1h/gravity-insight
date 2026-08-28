from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from gravity_sdk import GravitySDK
from gravity_sdk.capability_trust_cli import dispatch as capability_dispatch
from gravity_sdk.journey_cli import dispatch as journey_dispatch
from gravity_sdk.mcp.server import MCPServer
from tests.test_mcp_protocol import request_params


ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests/fixtures/mcp_parity_corpus.json"


class MCPParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.workspace = SimpleNamespace(root=root, state_root=root / "state", apps={})
        self.network_calls = 0

        def network_client():
            self.network_calls += 1
            raise AssertionError("Frozen parity corpus must remain offline")

        self.sdk = GravitySDK(
            workspace=self.workspace,
            insight_factory=network_client,
            sql_factory=network_client,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_frozen_cli_sdk_mcp_parity_corpus(self) -> None:
        corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
        self.assertEqual("gravity.mcp-parity-corpus.v1", corpus["schema_version"])
        self.assertEqual(4, len(corpus["cases"]))

        for case in corpus["cases"]:
            with self.subTest(case=case["case_id"], question=case["question"]):
                cli = self._cli(case)
                sdk = self._sdk(case)
                mcp = self._mcp(case)
                fields = case["semantic_fields"]
                self.assertEqual(
                    {field: sdk[field] for field in fields},
                    {field: cli[field] for field in fields},
                )
                self.assertEqual(
                    {field: sdk[field] for field in fields},
                    {field: mcp[field] for field in fields},
                )
        self.assertEqual(0, self.network_calls)

    def _cli(self, case: dict) -> dict:
        factory = Mock()
        factory.return_value = self.sdk
        factory.from_env.return_value = self.sdk
        arguments = case["arguments"]
        with (
            patch("gravity_sdk.sdk.GravitySDK", factory),
            patch("gravity_sdk.workspace.load_workspace", return_value=self.workspace),
        ):
            if case["case_id"] == "journey-list":
                return journey_dispatch(
                    SimpleNamespace(journey_command="list", workspace=None),
                    lambda _value: self.fail("list must not read input"),
                )
            if case["case_id"] == "capability-describe":
                return capability_dispatch(
                    SimpleNamespace(
                        capabilities_command="trust",
                        identity_kind=arguments["identity_kind"],
                        selector=arguments["selector"],
                        workspace=None,
                    ),
                    lambda _value: self.fail("trust must not read input"),
                )
            command = (
                "can-run"
                if case["case_id"] == "journey-can-run"
                else "run"
            )
            return journey_dispatch(
                SimpleNamespace(
                    journey_command=command,
                    journey_id=arguments["journey_id"],
                    input="{}",
                    workspace=None,
                ),
                lambda _value: arguments["inputs"],
            )

    def _sdk(self, case: dict) -> dict:
        arguments = case["arguments"]
        if case["case_id"] == "journey-list":
            return self.sdk.journeys.list()
        if case["case_id"] == "journey-can-run":
            return self.sdk.journeys.can_run(
                arguments["journey_id"], arguments["inputs"]
            )
        if case["case_id"] == "capability-describe":
            return self.sdk.capability_trust.trust(
                arguments["identity_kind"], arguments["selector"]
            )
        return self.sdk.journeys.run(
            arguments["journey_id"], arguments["inputs"]
        )

    def _mcp(self, case: dict) -> dict:
        server = MCPServer(self.sdk)
        response = server.handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": request_params(
                    name=case["mcp_tool"], arguments=case["arguments"]
                ),
            }
        )
        return response["result"]["structuredContent"]["result"]


if __name__ == "__main__":
    unittest.main()
