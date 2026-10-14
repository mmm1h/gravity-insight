from __future__ import annotations

import json
import unittest

from gravity_insight.app_snapshot import SCHEMA_VERSION, app_snapshot
from gravity_insight.cache import is_metadata_operation
from gravity_insight.drift import ProjectionDrift
from gravity_insight.executor import _project as project_response
from gravity_insight.models import load_operation_manifest
from gravity_insight.paths import MANIFEST_ROOT
from gravity_insight.agents.fixed_snapshots import fixed_snapshot_query


class _SnapshotClient:
    def __init__(self, name: str, cid: int) -> None:
        self.name = name
        self.cid = cid
        self.calls = 0

    def batch(self, requests, *, max_workers=6):
        self.calls += 1
        results = []
        for request in requests:
            data = {"list": [], "page_info": {}}
            if request["operation_id"] == "app.detail":
                data = {"app": {"id": 7, "cid": self.cid, "name": self.name}}
            results.append(
                {
                    "operation_id": request["operation_id"],
                    "request_id": request["request_id"],
                    "ok": True,
                    "status": "success",
                    "data": {"status": "success", "data": data},
                }
            )
        return results


class AppConfigurationSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        operations = load_operation_manifest(MANIFEST_ROOT / "candidates.json")
        cls.operation = next(
            item for item in operations if item.operation_id == "app.detail"
        )

    def project(self, data):
        return project_response(self.operation, {"data": data}, {"app_id": "7"})

    def test_configuration_projection_is_a_recursive_public_allowlist(self) -> None:
        raw = {
            "app": {"id": 7, "remark": "safe", "download_url": "x"},
            "wx_app": {"secret": "x"},
            "ta_conf": {"ta_conf_type": 2, "ta_url": "x"},
            "postback_conf": {"alipay": {"key": "x", "user_id_mode": 1}},
            "booking_info": {
                "enable_booking": True,
                "callback_url": "https://example.invalid/a?sig=x",
            },
            "extra_attribution_conf": {
                "enable_asa_query": True,
                "new_toggle": "x",
            },
            "attributed_order": {"channel_list": ["x"]},
            "dryrun_mode": {"baidu": 0, "new_platform": "x"},
            "distinct_strategy": 2,
            "reactive_window": 14,
            "new_root": "x",
        }
        projected, warnings, drift, audit = self.project(raw)
        self._assert_safe_projection(projected, warnings, drift, audit)

    def _assert_safe_projection(self, projected, warnings, drift, audit) -> None:
        self.assertEqual({"id": 7, "remark": "safe"}, projected["app"])
        self.assertEqual({}, projected["wx_app"])
        self.assertEqual({"ta_conf_type": 2}, projected["ta_conf"])
        self.assertEqual(
            {"alipay": {"user_id_mode": 1}}, projected["postback_conf"]
        )
        self.assertEqual({"enable_booking": True}, projected["booking_info"])
        self.assertEqual({}, projected["attributed_order"])
        self.assertEqual({"baidu": 0}, projected["dryrun_mode"])
        self.assertEqual(ProjectionDrift.ADDITIVE, drift)
        self.assertTrue(warnings)
        self.assertIsNotNone(audit)
        serialized = json.dumps(projected, sort_keys=True)
        for forbidden in ("secret", "download_url", "callback_url", "sig=x"):
            self.assertNotIn(forbidden, serialized)

    def test_empty_and_missing_configuration_containers_are_safe(self) -> None:
        projected, warnings, drift, _audit = self.project(
            {
                "app": {"id": 7},
                "wx_app": {},
                "postback_conf": {},
                "attributed_order": {},
            }
        )
        self.assertEqual(
            {
                "app": {"id": 7},
                "wx_app": {},
                "postback_conf": {},
                "attributed_order": {},
            },
            projected,
        )
        self.assertEqual(ProjectionDrift.NONE, drift)
        self.assertTrue(any("optional response data key" in item for item in warnings))

    def test_configuration_container_type_drift_fails_closed(self) -> None:
        projected, warnings, drift, audit = self.project(
            {"app": {"id": 7}, "wx_app": "credential-shaped-scalar"}
        )
        self.assertNotIn("wx_app", projected)
        self.assertEqual(ProjectionDrift.BREAKING, drift)
        self.assertTrue(warnings)
        self.assertIsNotNone(audit)

        null_projected, _warnings, null_drift, _audit = self.project(
            {"app": {"id": 7}, "wx_app": None}
        )
        self.assertIsNone(null_projected["wx_app"])
        self.assertEqual(ProjectionDrift.NONE, null_drift)

    def test_snapshot_is_uncached_and_keeps_client_principals_isolated(self) -> None:
        self.assertFalse(is_metadata_operation(self.operation))
        north = _SnapshotClient("north", 91)
        south = _SnapshotClient("south", 92)

        north_result = app_snapshot(north, 7, max_workers=1)
        south_result = app_snapshot(south, 7, max_workers=1)

        self.assertEqual(SCHEMA_VERSION, north_result["schema_version"])
        self.assertEqual(
            "north", north_result["results"][0]["data"]["data"]["app"]["name"]
        )
        self.assertEqual(
            "south", south_result["results"][0]["data"]["data"]["app"]["name"]
        )
        self.assertEqual((2, 2), (north.calls, south.calls))

    def test_contract_declares_all_safe_configuration_leaves(self) -> None:
        projection = self.operation.response_projection
        self.assertEqual(
            {
                "wx_app", "ta_conf", "postback_conf", "booking_info",
                "extra_attribution_conf", "attributed_order", "dryrun_mode",
            },
            set(projection.data_item_keys) - {"app"},
        )
        self.assertEqual(
            {"baidu", "bytedance", "facebook", "google", "kuaishou", "tencent"},
            set(projection.data_item_keys["dryrun_mode"]),
        )
        self.assertEqual((), projection.data_item_keys["wx_app"])
        self.assertEqual((), projection.data_item_keys["attributed_order"])

    def test_agent_discovers_application_configuration_snapshot(self) -> None:
        self.assertTrue(fixed_snapshot_query("app_snapshot", "应用配置"))
        self.assertTrue(fixed_snapshot_query("app_snapshot", "app configuration"))


if __name__ == "__main__":
    unittest.main()
