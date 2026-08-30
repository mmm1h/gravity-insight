from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gravity_insight import GravityInsightClient, GravitySDK, cli
from gravity_insight.agent import discover_capabilities
from gravity_insight.plan import AdapterContext
from gravity_insight import plan_realtime_event_catalog_adapter as plan_subject
from gravity_insight.realtime_event_catalog import SCHEMA_VERSION, realtime_event_catalog
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ID = "analysis.realtime_event.list"


def _manifest():
    root = ROOT / "src" / "gravity_insight" / "contracts" / "operations"
    operations = []
    for name in ("app.list", OPERATION_ID):
        operations.append(
            json.loads((root / f"{name}.json").read_text(encoding="utf-8"))["operation"]
        )
    return {"manifest_version": 1, "operations": operations}


class _Transport:
    is_test_transport = True

    def __init__(self, data):
        self.data, self.calls = data, []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return TransportResponse(200, {"code": 0, "data": self.data}, "2026-08-18T00:00:00Z")


class _Workspace:
    def resolve_app(self, value):
        if value != "main":
            raise ValueError(value)
        return 7


class RealtimeEventCatalogTests(unittest.TestCase):
    def test_core_projects_observed_item_keys_and_omits_raw_properties(self):
        transport = _Transport(
            {
                "list": [
                    {
                        "client_id": "c1",
                        "client_time": "2026-08-18 18:00:00",
                        "event_name": "profile_set",
                        "event_type": "profile",
                        "request_id": "r1",
                        "request_time": "2026-08-18 18:00:01",
                        "raw_properties": {"account_id": "hidden"},
                        "request_ip": "0.0.0.0",
                    }
                ]
            }
        )
        client = GravityInsightClient._from_manifest_for_tests(
            _manifest(), transport=transport
        )
        result = realtime_event_catalog(
            client,
            7,
            start="2026-08-18 00:00:00",
            end="2026-08-18 23:59:59",
        )
        self.assertEqual(SCHEMA_VERSION, result["schema_version"])
        self.assertEqual("success", result["status"])
        self.assertEqual(1, result["item_count"])
        item = result["data"]["list"][0]
        self.assertEqual("c1", item["client_id"])
        self.assertNotIn("raw_properties", item)
        self.assertEqual("POST", transport.calls[0][0])
        self.assertEqual(
            {
                "app_id": 7,
                "filters": {"event_type": "profile"},
                "page": 1,
                "page_size": 50,
                "request_time": ["2026-08-18 00:00:00", "2026-08-18 23:59:59"],
            },
            dict(transport.calls[0][2]["body"]),
        )

    def test_cli_sdk_plan_and_agent_share_one_fillable_product(self):
        parsed = cli.build_parser().parse_args(
            [
                "analysis",
                "realtime-events",
                "--app",
                "main",
                "--start",
                "2026-08-18 00:00:00",
                "--end",
                "2026-08-18 23:59:59",
            ]
        )
        expected = {"schema_version": SCHEMA_VERSION, "ok": True, "status": "success"}
        workspace = _Workspace()
        with (
            patch("gravity_insight.capability_cli.load_workspace", return_value=workspace),
            patch("gravity_insight.capability_cli.runtime.build_client", return_value=object()),
            patch(
                "gravity_insight.capability_cli.realtime_event_catalog",
                return_value=expected,
            ) as facade,
        ):
            self.assertIs(expected, parsed._gravity_handler(parsed, None))
        self.assertEqual(7, facade.call_args.args[1])

        sdk = GravitySDK(workspace=workspace, insight_factory=lambda: object())
        with patch(
            "gravity_insight.realtime_event_catalog.realtime_event_catalog",
            return_value=expected,
        ) as core:
            self.assertIs(
                expected,
                sdk.realtime_event_catalog(
                    "main",
                    start="2026-08-18 00:00:00",
                    end="2026-08-18 23:59:59",
                ),
            )
        self.assertEqual(7, core.call_args.args[1])

        context = AdapterContext(
            "realtime-events", "run", "composite", workspace, ("data",), (), 1, 10
        )
        request = {
            "name": "realtime_event_catalog",
            "app": "main",
            "start": "2026-08-18 00:00:00",
            "end": "2026-08-18 23:59:59",
        }
        plan_subject.validate_realtime_event_catalog_plan(request, context, workspace)
        plan_sdk = SimpleNamespace(realtime_event_catalog=lambda *a, **k: expected)
        self.assertEqual(
            SCHEMA_VERSION,
            plan_subject.execute_realtime_event_catalog_plan(
                plan_sdk, request, context
            )["schema_version"],
        )

        card = discover_capabilities("查询实时事件目录", client=object(), limit=1)[
            "candidates"
        ][0]
        self.assertEqual("composite:realtime_event_catalog", card["selector"])
        self.assertEqual("gravity.agent-call-bound.v1", card["call_bound"]["schema_version"])
        self.assertEqual(
            request,
            card["plan_node"]["request"]
            | {
                "app": "main",
                "start": "2026-08-18 00:00:00",
                "end": "2026-08-18 23:59:59",
            },
        )


if __name__ == "__main__":
    unittest.main()
