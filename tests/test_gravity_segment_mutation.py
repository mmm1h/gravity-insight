from __future__ import annotations

import json
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from gravity_sdk.agents.segment import segment_mutation_cards
from gravity_sdk.errors import InputValidationError, PolicyViolation
from gravity_sdk.models import load_operation_manifest
from gravity_sdk.mutation import MutationExecutor
from gravity_sdk.prober.read_semantics import assert_probe_read_semantics
from gravity_sdk.registry import PolicyEngine, Registry, _consume_authorized_request
from gravity_sdk.segment_mutation import (
    create_segment_from_rule,
    delete_segment,
    is_sdk_segment_remark,
)
from gravity_sdk.transport import Transport


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_ROOT = ROOT / "src" / "gravity_sdk" / "manifests"
CONTRACT_ROOT = ROOT / "src" / "gravity_sdk" / "contracts"


def _registry() -> Registry:
    operations = []
    for path in sorted(MANIFEST_ROOT.glob("*.json")):
        operations.extend(load_operation_manifest(path))
    return Registry(operations)


class _Runtime:
    def __init__(self, *, status_code=200, payload=None) -> None:
        self.calls: list[dict[str, object]] = []
        self.status_code = status_code
        self.payload = payload or {"code": 0, "data": True}

    def _request_insight(self, method, path, **kwargs):
        query, body = _consume_authorized_request(
            kwargs["policy_authorization"],
            method=method,
            path=path,
            query=kwargs.get("params"),
            body=kwargs.get("json_body"),
        )
        self.calls.append(
            {
                "method": method,
                "path": path,
                "query": query,
                "body": body,
                "attempts": kwargs.get("attempts"),
            }
        )
        return SimpleNamespace(
            status_code=self.status_code,
            payload=self.payload,
            fetched_at="2026-08-16T00:00:00Z",
            retry_after_ms=None,
        )


class _ExistingClient:
    def __init__(self) -> None:
        self.preview_input = None
        self.writes = 0

    def _preview_mutation(self, operation_id, inputs):
        self.preview_input = dict(inputs)
        return {
            "schema_version": "gravity-insight.mutation.v1",
            "ok": True,
            "status": "preview",
            "operation_id": operation_id,
            "network_called": False,
            "request": {"method": "POST", "path": "/registered/", "body": dict(inputs)},
        }

    def read_all(self, operation_id, inputs, **kwargs):
        marker = str(self.preview_input["remark"])
        return {
            "ok": True,
            "status": "success",
            "data": {
                "list": [
                    {
                        "segment_id": "1",
                        "app_id": "1",
                        "segment_name": self.preview_input["name"],
                        "segment_remark": marker,
                    }
                ]
            },
            "truncated": False,
            "next_page_input": None,
        }

    def read(self, operation_id, inputs):
        return {
            "ok": True,
            "status": "success",
            "data": {
                "segment_id": "1",
                "app_id": "1",
                "segment_name": self.preview_input["name"],
                "segment_remark": self.preview_input["remark"],
            },
        }

    def _execute_mutation(self, operation_id, inputs):
        self.writes += 1
        raise AssertionError("idempotent preflight must suppress the write")


class _UnmarkedClient:
    def __init__(self, *, owner_id="2", principal_id="1", allow_write=False) -> None:
        self.writes = 0
        self.owner_id = owner_id
        self.principal_id = principal_id
        self.allow_write = allow_write
        self.deleted = False

    def _current_principal_id(self):
        return self.principal_id

    def read(self, operation_id, inputs):
        return {
            "ok": True,
            "status": "success",
            "data": {
                "segment_id": str(inputs["segment_id"]),
                "app_id": "1",
                "segment_name": "同事手建",
                "segment_remark": "manual",
                "create_user_id": self.owner_id,
                "create_user_name": "owner",
            },
        }

    def read_all(self, operation_id, inputs, **kwargs):
        return {
            "ok": True,
            "status": "empty" if self.deleted else "success",
            "data": {"list": []},
            "truncated": False,
            "next_page_input": None,
        }

    def _preview_mutation(self, operation_id, inputs):
        return {"operation_id": operation_id, "status": "preview"}

    def _execute_mutation(self, operation_id, inputs):
        self.writes += 1
        if not self.allow_write:
            raise AssertionError("foreign delete must not reach transport")
        self.deleted = True
        return {"operation_id": operation_id, "attempts": 1}


class GravitySegmentMutationTests(unittest.TestCase):
    def test_registered_mutation_preview_is_zero_network_and_execute_is_one_shot(self):
        registry = _registry()
        policy = PolicyEngine(registry)
        runtime = _Runtime()
        transport = Transport(policy=policy, runtime=runtime)
        executor = MutationExecutor(registry, policy, transport)
        executor.bind_call_guard(lambda _operation_id: {})
        inputs = {"segment_id": "1"}

        preview = executor.preview("analysis.segment.by.manual.update", inputs)
        self.assertFalse(preview["network_called"])
        self.assertEqual([], runtime.calls)

        result = executor.execute("analysis.segment.by.manual.update", inputs)
        self.assertTrue(result["network_called"])
        self.assertEqual(1, result["attempts"])
        self.assertEqual(1, len(runtime.calls))
        self.assertEqual(1, runtime.calls[0]["attempts"])
        self.assertEqual({"segment_id": 1}, runtime.calls[0]["body"])
        with self.assertRaisesRegex(PolicyViolation, "read-only"):
            policy.authorize_operation("analysis.segment.by.manual.update")

        cases = (
            (200, {"code": 0, "extra": {"error": "无数据"}, "data": None}),
            (204, {}),
        )
        for status_code, payload in cases:
            with self.subTest(status_code=status_code):
                case_policy = PolicyEngine(registry)
                case_runtime = _Runtime(status_code=status_code, payload=payload)
                case_executor = MutationExecutor(
                    registry,
                    case_policy,
                    Transport(policy=case_policy, runtime=case_runtime),
                )
                case_executor.bind_call_guard(lambda _operation_id: {})

                empty = case_executor.execute(
                    "analysis.segment.by.manual.update", {"segment_id": "1"}
                )

                self.assertEqual("empty", empty["status"])
                self.assertEqual({}, empty["data"])
                self.assertEqual(1, len(case_runtime.calls))
                self.assertNotIn("response_drift", empty["result_audit"])

    def test_same_marker_is_idempotent_and_sends_no_write(self):
        client = _ExistingClient()
        result = create_segment_from_rule(
            client,
            {"name": "SDK规则测试", "start": "2026-08-15"},
            app=1,
            execute=True,
        )
        self.assertEqual("already_exists", result["status"])
        self.assertTrue(result["idempotent_reuse"])
        self.assertEqual(0, client.writes)
        self.assertTrue(is_sdk_segment_remark(client.preview_input["remark"]))

    def test_delete_reads_preimage_and_refuses_unmarked_target(self):
        client = _UnmarkedClient()
        with self.assertRaises(InputValidationError) as captured:
            delete_segment(client, "1", execute=True)
        error = captured.exception
        self.assertEqual("OWNERSHIP_REQUIRED", error.code)
        self.assertIn("owner", error.next_action)
        self.assertIn("actual value:", str(error))
        self.assertIn('"object_id":"1"', str(error))
        self.assertIn('"owner_id":"2"', str(error))
        self.assertIn('"owner_field":"create_user_id"', str(error))
        self.assertIn('"current_principal_id":"1"', str(error))
        self.assertIn("create_user_id=2", error.next_action)
        self.assertEqual(0, client.writes)

        owned = _UnmarkedClient(owner_id="1", allow_write=True)
        result = delete_segment(owned, "1", execute=True)
        self.assertEqual(("deleted", 1), (result["status"], owned.writes))
        self.assertEqual("upstream_owner", result["target"]["ownership"]["basis"])

        marked = _UnmarkedClient(owner_id="9", allow_write=True)
        marked.read = lambda operation_id, inputs: {
            "ok": True,
            "status": "success",
            "data": {
                "segment_id": str(inputs["segment_id"]),
                "app_id": "1",
                "segment_name": "SDK分群",
                "segment_remark": "GSDK-aabbccddeeff",
                "create_user_id": "9",
                "create_user_name": "other",
            },
        }
        kept = delete_segment(marked, "1", execute=True)
        self.assertEqual("sdk_source_marker", kept["target"]["ownership"]["basis"])
        self.assertEqual(1, marked.writes)

    def test_registered_mutation_action_name_is_not_an_authorization_boundary(self):
        operation = _registry().get("analysis.segment.by.manual.update")
        shared = replace(operation, action="share")
        policy = PolicyEngine(Registry([shared]))
        self.assertEqual(shared, policy.authorize_mutation_operation(shared.operation_id))

    def test_registered_mutation_passes_prober_gate_but_tampering_does_not(self):
        path = CONTRACT_ROOT / "operations" / "analysis.segment.by.manual.update.json"
        source = json.loads(path.read_text(encoding="utf-8"))
        assert_probe_read_semantics(source)
        source["operation"]["path_template"] = "/report/api/v3/dataanalysis/segment/delete/"
        with self.assertRaisesRegex(PolicyViolation, "not an exact registered"):
            assert_probe_read_semantics(source)

    def test_agent_returns_confirmation_handoff_without_plan_node(self):
        cards = segment_mutation_cards(
            "把漏斗流失的人保存成分群", domain=None, platform=None
        )
        self.assertEqual(1, len(cards))
        card = cards[0]
        self.assertEqual("mutation", card["effect"])
        self.assertFalse(card["plan_executable"])
        self.assertFalse(card["natural_language_auto_execute"])
        self.assertTrue(card["confirmation_required"])
        self.assertEqual("--dry-run", card["next"]["argv"][-1])
        self.assertEqual("--execute", card["next"]["then_argv"][-1])


if __name__ == "__main__":
    unittest.main()
