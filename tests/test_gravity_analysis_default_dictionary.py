from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk import GravityInsightClient, GravitySDK, cli
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.analysis_default_dictionary import SCHEMA_VERSION, analysis_default_dictionary
from gravity_sdk.plan import AdapterContext
from gravity_sdk import plan_analysis_default_adapter as plan_subject
from gravity_sdk.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "analysis.default_val.list"


def _manifest():
    root = ROOT / "src" / "gravity_sdk" / "contracts" / "operations"
    operations = []
    for name in ("app.list", OPERATION_ID):
        operations.append(json.loads((root / f"{name}.json").read_text(encoding="utf-8"))["operation"])
    return {"manifest_version": 1, "operations": operations}


class _Transport:
    is_test_transport = True

    def __init__(self, data):
        self.data, self.calls = data, []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return TransportResponse(200, {"code": 0, "data": self.data}, "2026-08-16T00:00:00Z")


class _Workspace:
    def resolve_app(self, value):
        if value != "main":
            raise ValueError(value)
        return 7


class AnalysisDefaultDictionaryTests(unittest.TestCase):
    def test_core_exposes_registered_keys_and_audits_additive_drift(self):
        transport = _Transport({"api": ["v1"], "cocoscreator": ["v2"]})
        client = GravityInsightClient._from_manifest_for_tests(_manifest(), transport=transport)
        result = analysis_default_dictionary(client, 7)
        self.assertEqual((SCHEMA_VERSION, "success", 2),
                         (result["schema_version"], result["status"], result["value_count"]))
        self.assertEqual({"api", "cocoscreator"}, set(result["data"]))
        self.assertEqual(("POST", {"app_id": 7, "subject": "$lib_version"}),
                         (transport.calls[0][0], dict(transport.calls[0][2]["body"])))

        changed = GravityInsightClient._from_manifest_for_tests(
            _manifest(), transport=_Transport({"api": [], "new_sdk": ["v3"]})
        )
        changed_result = analysis_default_dictionary(changed, 7)
        self.assertEqual("empty", changed_result["status"])
        self.assertEqual(
            {
                "schema_version": "gravity.response-drift.v1",
                "direction": "response",
                "classification": "additive",
                "fields": [{"path": "/data/new_sdk", "observed_type": "array"}],
            },
            changed_result["result_audit"]["response_drift"],
        )

    def test_cli_sdk_plan_and_agent_share_one_fillable_product(self):
        parsed = cli.build_parser().parse_args(["analysis", "defaults", "--app", "main"])
        expected = {"schema_version": SCHEMA_VERSION, "ok": True, "status": "success"}
        workspace = _Workspace()
        with (patch("gravity_sdk.capability_cli.load_workspace", return_value=workspace),
              patch("gravity_sdk.capability_cli.runtime.build_client", return_value=object()),
              patch("gravity_sdk.capability_cli.analysis_default_dictionary",
                    return_value=expected) as facade):
            self.assertIs(expected, parsed._gravity_handler(parsed, None))
        self.assertEqual(7, facade.call_args.args[1])

        sdk = GravitySDK(workspace=workspace, insight_factory=lambda: object())
        with patch("gravity_sdk.analysis_default_dictionary.analysis_default_dictionary",
                   return_value=expected) as core:
            self.assertIs(expected, sdk.analysis_default_dictionary("main"))
        self.assertEqual(7, core.call_args.args[1])

        context = AdapterContext("defaults", "run", "composite", workspace,
                                 ("data",), (), 1, 10)
        request = {"name": "analysis_default_dictionary", "app": "main"}
        plan_subject.validate_analysis_default_dictionary_plan(request, context, workspace)
        plan_sdk = SimpleNamespace(analysis_default_dictionary=lambda *a, **k: expected)
        self.assertEqual(SCHEMA_VERSION,
                         plan_subject.execute_analysis_default_dictionary_plan(
                             plan_sdk, request, context)["schema_version"])

        card = discover_capabilities("查询分析默认值字典", client=object(), limit=1)["candidates"][0]
        self.assertEqual("composite:analysis_default_dictionary", card["selector"])
        typo_card = discover_capabilities("分析默人值字典", client=object(), limit=1)["candidates"][0]
        self.assertEqual(card["selector"], typo_card["selector"])
        self.assertEqual("gravity.agent-call-bound.v1", card["call_bound"]["schema_version"])
        self.assertEqual(request, card["plan_node"]["request"] | {"app": "main"})


if __name__ == "__main__":
    unittest.main()
