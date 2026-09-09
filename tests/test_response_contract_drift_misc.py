from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight import GravityInsightClient
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]


def manifest(operation_id: str) -> dict[str, Any]:
    contract_root = ROOT / "src" / "gravity_insight" / "contracts" / "operations"
    operations: list[dict[str, Any]] = []
    pending = [operation_id]
    loaded: set[str] = set()
    while pending:
        current = pending.pop()
        if current in loaded:
            continue
        path = contract_root / f"{current}.json"
        operation = json.loads(path.read_text(encoding="utf-8"))["operation"]
        operations.append(operation)
        loaded.add(current)
        pending.extend(
            parent["operation_id"]
            for parent in operation.get("required_parent", [])
            if parent.get("operation_id")
        )
    return {"manifest_version": 1, "operations": operations}


class StaticTransport:
    is_test_transport = True

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        return TransportResponse(200, self.payload, "2026-09-05T00:00:00Z")


def read(
    operation_id: str, payload: Mapping[str, Any], inputs: Mapping[str, Any]
) -> dict[str, Any]:
    client = GravityInsightClient._from_manifest_for_tests(
        manifest(operation_id), transport=StaticTransport(payload)
    )
    return client.read(operation_id, inputs)


class MiscResponseContractDriftTests(unittest.TestCase):
    def test_primary_list_shape_drift_fails_closed(self) -> None:
        for operation_id in ("app.list", "app.permission_menu.list"):
            for observed, data in (
                ("string", {"list": "private malformed rows"}),
                ("missing", {}),
                ("null", {"list": None}),
            ):
                with self.subTest(operation=operation_id, observed=observed):
                    result = read(operation_id, {"code": 0, "data": data}, {})
                    self.assertFalse(result["ok"])
                    self.assertEqual("contract_changed", result["status"])
                    self.assertEqual("CONTRACT_CHANGED", result["error"]["code"])
                    drift = result["result_audit"]["response_drift"]
                    self.assertIn(
                        {"classification": "breaking", "path": "/data/list",
                         "expected_type": "array", "observed_type": observed},
                        drift["fields"],
                    )
                    self.assertNotIn("private malformed rows", json.dumps(result))

    def test_primary_list_arrays_keep_success_and_empty_semantics(self) -> None:
        for rows, status in (([{"id": 1, "name": "fixture"}], "success"), ([], "empty")):
            with self.subTest(status=status):
                result = read("app.list", {"code": 0, "data": {
                    "list": rows,
                    "page_info": {"page": 1, "page_size": 6000, "total_page": 1},
                }}, {})
                self.assertTrue(result["ok"])
                self.assertEqual(status, result["status"])
                self.assertEqual(rows, result["data"]["list"])
                self.assertNotIn("response_drift", result["result_audit"])

    def test_bytedance_project_scalar_additions_are_projected_without_drift(self) -> None:
        fields = {
            "delay": 1,
            "download_url": "https://download.invalid/project",
            "operator_id": 17,
            "operator_name": "operator",
        }
        payload = {
            "code": 0,
            "data": {
                "list": [{"id": 1, **fields}],
                "page_info": {"page": 1, "page_size": 10, "total_page": 1},
            },
        }

        result = read(
            "promotion.bytedance.project.list",
            payload,
            {"date_list": ["2026-09-05", "2026-09-05"]},
        )

        self.assertEqual("success", result["status"])
        self.assertEqual(fields, {key: result["data"]["list"][0][key] for key in fields})
        self.assertNotIn("response_drift", result["result_audit"])

    def test_permission_menu_children_contract_recurses_to_the_next_level(self) -> None:
        grandchild = {
            "id": 3,
            "name": "grandchild",
            "parent_id": 2,
            "person_num": 1,
            "children": [],
        }
        child = {
            "id": 2,
            "name": "child",
            "parent_id": 1,
            "person_num": 2,
            "children": [grandchild],
        }
        payload = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "id": 1,
                        "name": "root",
                        "parent_id": None,
                        "person_num": 3,
                        "children": [child],
                    }
                ]
            },
        }

        result = read("app.permission_menu.list", payload, {})

        self.assertEqual("success", result["status"])
        self.assertEqual(grandchild, result["data"]["list"][0]["children"][0]["children"][0])
        self.assertNotIn("response_drift", result["result_audit"])

    def test_attribution_personnel_scalar_additions_are_projected_without_drift(self) -> None:
        fields = {
            "create_user_id": 11,
            "create_user_name": "creator",
            "operator_id": 12,
            "operator_name": "operator",
            "update_user_id": 13,
            "update_user_name": "updater",
        }
        payload = {
            "code": 0,
            "data": {
                "list": [{"id": 1, **fields}],
                "page_info": {"page": 1, "page_size": 20, "total_page": 1},
            },
        }

        result = read(
            "attribution.postback_map_collect.list", payload, {"app_id": "29034827"}
        )

        self.assertEqual("success", result["status"])
        self.assertEqual(fields, {key: result["data"]["list"][0][key] for key in fields})
        self.assertNotIn("response_drift", result["result_audit"])

    def test_unshaped_media_enum_container_is_declared_but_not_exposed(self) -> None:
        payload = {
            "code": 0,
            "data": {
                "bytedance": {
                    "optimization_goal": [{"code": "install", "name": "Install"}]
                },
                "tencent": {},
                "kuaishou": {},
                "dy_mini_game": {"unverified_shape": [{"unknown": "private"}]},
            },
        }

        result = read("report.multidim.media_enum.list", payload, {})

        self.assertEqual("success", result["status"])
        self.assertEqual(
            {
                "bytedance": {
                    "optimization_goal": [{"code": "install", "name": "Install"}]
                },
                "tencent": {},
                "kuaishou": {},
            },
            result["data"],
        )
        self.assertNotIn("response_drift", result["result_audit"])
        self.assertNotIn("private", json.dumps(result))

    def test_new_scalar_declaration_still_rejects_non_json_values(self) -> None:
        payload = {
            "code": 0,
            "data": {
                "list": [{"id": 1, "delay": float("nan")}],
                "page_info": {"page": 1, "page_size": 10, "total_page": 1},
            },
        }

        result = read(
            "promotion.bytedance.project.list",
            payload,
            {"date_list": ["2026-09-05", "2026-09-05"]},
        )

        self.assertFalse(result["ok"])
        self.assertEqual("contract_changed", result["status"])
        self.assertEqual("CONTRACT_CHANGED", result["error"]["code"])
        self.assertEqual({"id": 1}, result["data"]["list"][0])
        self.assertTrue(
            any("non-JSON scalar" in warning for warning in result["warnings"])
        )


if __name__ == "__main__":
    unittest.main()
