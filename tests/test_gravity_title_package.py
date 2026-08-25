from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch

from gravity_sdk import GravitySDK
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.cli import main
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_title_package_adapter import (
    execute_title_package_plan,
    validate_title_package_plan,
)
from gravity_sdk.title_package import OPERATION_IDS, SCHEMA_VERSION, title_packages
class Client:
    def __init__(self, mode="success"):
        self.mode = mode
        self.calls = []
    def batch(self, requests, *, max_workers=6, max_pages=1_000,
              max_total_items=100_000):
        self.calls.append((requests, {
            "max_workers": max_workers,
            "max_pages": max_pages,
            "max_total_items": max_total_items,
        }))
        operation_id = requests[0]["operation_id"]
        if self.mode == "unavailable":
            return [{
                "operation_id": operation_id,
                "request_id": "title_packages",
                "ok": False,
                "status": "unavailable",
                "data": None,
                "error": {
                    "code": "UNSUPPORTED",
                    "category": "local",
                    "message": "hidden upstream detail",
                },
            }]
        rows = [] if self.mode == "empty" else [{
            "id": 7,
            "app_id": 101,
            "cid": 9,
            "title_package_name": "safe package",
            "title_num": 12,
            "plan_num": 3,
            "history_cost": 34.5,
            "history_click_rate": 0.12,
            "last_3_day_cost": 5.0,
            "last_3_day_click_rate": 0.2,
        }]
        if self.mode == "registered_fields":
            rows[0].update({
                "title_list": "registered title",
                "create_user_id": 3,
                "create_user_name": "registered creator",
                "update_user_id": 4,
            })
        if self.mode == "opaque_list":
            rows[0]["title_list"] = ["nested title", {"language": "zh"}]
        if self.mode == "opaque_dict":
            rows[0]["title_list"] = {"titles": ["nested title"]}
        if self.mode == "opaque_too_deep":
            opaque: object = "nested title"
            for _ in range(9):
                opaque = [opaque]
            rows[0]["title_list"] = opaque
        if self.mode == "opaque_too_many":
            rows[0]["title_list"] = ["nested title"] * 256
        if self.mode == "opaque_too_large":
            rows[0]["title_list"] = ["x" * 8_192] * 5
        if self.mode == "non_opaque_collection":
            rows[0]["title_package_name"] = ["not scalar"]
        truncated = self.mode == "partial"
        status = "empty" if self.mode == "empty" else "success"
        native = {
            "schema_version": "gravity-insight.read.v1",
            "operation_id": operation_id,
            "status": status,
            "data": {
                "list": rows,
                "page_info": {
                    "page": 1, "page_size": 100,
                    "total_page": 2 if truncated else 1,
                    "total_number": len(rows),
                },
            },
            "page": {
                "number": 1, "size": 100, "item_count": len(rows),
                "total_pages": 2 if truncated else 1,
                "total_items": len(rows), "has_more": truncated,
                "pages_fetched": 1, "fetch_strategy": "single_page",
                "max_workers": 1,
            },
            "truncated": truncated,
            "next_page_input": (
                {"page": 2, "page_size": 100} if truncated else None
            ),
            "error": None,
        }
        return [{
            "operation_id": operation_id,
            "request_id": "title_packages",
            "ok": True,
            "status": status,
            "data": native,
            "error": None,
        }]
class Workspace:
    def resolve_app(self, value):
        if value in {"game", 101}:
            return 101
        raise ValueError("unknown app")
class TitlePackageTests(unittest.TestCase):
    def test_both_kinds_share_one_bounded_envelope(self):
        for kind, operation_id in OPERATION_IDS.items():
            with self.subTest(kind=kind):
                client = Client()
                result = title_packages(
                    client, 101, kind, max_pages=7, max_items=40
                )
                requests, options = client.calls[0]
                self.assertEqual(
                    (SCHEMA_VERSION, "success", kind, operation_id, 1),
                    (result["schema_version"], result["status"],
                     result["package_kind"], result["operation_id"],
                     result["returned_items"]),
                )
                self.assertEqual(
                    (operation_id, 101, True, 40),
                    (requests[0]["operation_id"],
                     requests[0]["inputs"]["app_id"],
                     requests[0]["read_all"],
                     requests[0]["inputs"]["page_size"]),
                )
                self.assertEqual(
                    {"max_workers": 1, "max_pages": 7,
                     "max_total_items": 40}, options
                )
    def test_empty_partial_gap_and_registered_fields_are_explicit(self):
        empty = title_packages(Client("empty"), 101, "regular")
        self.assertEqual((True, "empty", 0),
                         (empty["ok"], empty["status"], empty["returned_items"]))
        partial = title_packages(Client("partial"), 101, "regular")
        self.assertEqual(
            (False, "partial", {"page": 2, "page_size": 100}),
            (partial["ok"], partial["status"],
             partial["results"][0]["continuation"]),
        )
        gap = title_packages(Client("unavailable"), 101, "standard")
        self.assertEqual((False, "unavailable", "UNSUPPORTED"),
                         (gap["ok"], gap["status"],
                          gap["results"][0]["error"]["code"]))
        self.assertNotIn("hidden", json.dumps(gap, ensure_ascii=False))
        opened = title_packages(Client("registered_fields"), 101, "regular")
        self.assertEqual("success", opened["status"])
        row = opened["results"][0]["data"]["data"]["list"][0]
        self.assertEqual("registered title", row["title_list"])
        self.assertIsInstance(row["create_user_id"], int)

    def test_opaque_title_list_accepts_bounded_list_and_dict(self):
        for mode, expected in (
            ("opaque_list", ["nested title", {"language": "zh"}]),
            ("opaque_dict", {"titles": ["nested title"]}),
        ):
            for kind in OPERATION_IDS:
                with self.subTest(mode=mode, kind=kind):
                    result = title_packages(Client(mode), 101, kind)
                    self.assertEqual("success", result["status"])
                    self.assertEqual(
                        expected,
                        result["results"][0]["data"]["data"]["list"][0]["title_list"],
                    )

    def test_opaque_title_list_bounds_fail_closed(self):
        for mode in ("opaque_too_deep", "opaque_too_many", "opaque_too_large"):
            with self.subTest(mode=mode):
                result = title_packages(Client(mode), 101, "standard")
                self.assertEqual(
                    (False, "contract_changed"),
                    (result["ok"], result["status"]),
                )

    def test_non_opaque_title_package_fields_still_require_scalars(self):
        result = title_packages(Client("non_opaque_collection"), 101, "regular")
        self.assertEqual(
            (False, "contract_changed"),
            (result["ok"], result["status"]),
        )
    def test_sdk_cli_plan_and_agent_use_the_same_product(self):
        sdk = GravitySDK(insight=Client(), workspace=Workspace())
        self.assertEqual(
            "standard", sdk.title_packages("game", "standard")["package_kind"]
        )
        stdout = io.StringIO()
        with patch("gravity_sdk.material_cli.runtime.build_client",
                   return_value=Client()), \
                patch("gravity_sdk.material_cli.load_workspace",
                      return_value=Workspace()), \
                contextlib.redirect_stdout(stdout):
            code = main([
                "materials", "title-packages", "--app", "game",
                "--package-kind", "regular", "--max-items", "2",
            ])
        self.assertEqual((0, SCHEMA_VERSION),
                         (code, json.loads(stdout.getvalue())["schema_version"]))
        context = AdapterContext(
            node_id="packages", execution_id="packages", kind="composite",
            workspace=Workspace(), output_fields=(), dynamic_targets=(),
            max_pages=5, max_items=10,
        )
        request = {"name": "title_package", "app": "game",
                   "package_kind": "standard"}
        validate_title_package_plan(request, context, Workspace())
        plan_sdk = type("SDK", (), {
            "title_packages": lambda _self, app, kind, **options:
                {"app": app, "kind": kind, **options}
        })()
        self.assertEqual("standard",
                         execute_title_package_plan(plan_sdk, request, context)["kind"])
        result = discover_capabilities("标题包指标", client=None, domain="material")
        card = result["candidates"][0]
        self.assertEqual(
            ("title_package", True, ["app", "package_kind"]),
            (card["composite"], card["plan_executable"], card["missing_inputs"]),
        )
        self.assertEqual(
            {"name": "title_package", "app": "<app:string|integer>",
             "package_kind": "<package_kind:string:enum>"},
            card["plan_node"]["request"],
        )
        self.assertEqual(
            ("gravity.agent-call-bound.v1", 1, 2),
            (card["call_bound"]["schema_version"],
             card["call_bound"]["known_inputs"],
             card["call_bound"]["unknown_capability"]),
        )
if __name__ == "__main__":
    unittest.main()
