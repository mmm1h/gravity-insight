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
LOCKED_CORPUS = ROOT / "tests/fixtures/mcp_locked_execution_corpus.json"


class OfflineRegistryDiscovery:
    def __init__(self, state: str) -> None:
        self.state = state
        self.attempts = 0

    def discover(self) -> dict:
        self.attempts += 1
        if self.state == "outage":
            raise ConnectionError("synthetic offline registry outage")
        return {"status": "available", "network_called": False}


class LockedJourneyService:
    def __init__(self, registry: OfflineRegistryDiscovery, lock_digest: str) -> None:
        self.registry = registry
        self.lock_digest = lock_digest

    def run(self, journey_id: str, inputs: dict) -> dict:
        return {
            "schema_version": "gravity.analysis-result.v1",
            "ok": True,
            "status": "success",
            "exit_code": 0,
            "journey": {
                "journey_id": journey_id,
                "version": 1,
                "lock_digest": self.lock_digest,
            },
            "scope": dict(inputs),
            "network_called": False,
        }


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

    def test_locked_execution_succeeds_with_registry_discovery_outage(self) -> None:
        corpus = json.loads(LOCKED_CORPUS.read_text(encoding="utf-8"))
        self.assertEqual(
            "gravity.mcp-locked-execution-corpus.v1", corpus["schema_version"]
        )
        self.assertEqual(2, len(corpus["cases"]))

        for case in corpus["cases"]:
            registry = OfflineRegistryDiscovery(case["discovery_state"])
            service = LockedJourneyService(registry, case["lock_digest"])
            if case["discovery_state"] == "outage":
                with self.assertRaisesRegex(ConnectionError, "registry outage"):
                    registry.discover()
            else:
                self.assertEqual("available", registry.discover()["status"])
            discovery_attempts = registry.attempts
            self.sdk._journey_service = service

            response = MCPServer(self.sdk).handle(
                {
                    "jsonrpc": "2.0",
                    "id": 9,
                    "method": "tools/call",
                    "params": request_params(
                        name="gravity.execute",
                        arguments={
                            "journey_id": case["journey_id"],
                            "inputs": case["inputs"],
                        },
                    ),
                }
            )
            result = response["result"]
            domain = result["structuredContent"]["result"]
            self.assertFalse(result["isError"])
            self.assertEqual("success", domain["status"])
            self.assertEqual(case["lock_digest"], domain["journey"]["lock_digest"])
            self.assertEqual(discovery_attempts, registry.attempts)
            self.assertFalse(domain["network_called"])
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
