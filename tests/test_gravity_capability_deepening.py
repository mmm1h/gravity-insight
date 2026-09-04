from __future__ import annotations

import unittest

from gravity_insight.analysis_context import ANALYSIS_CONTEXT_SOURCES, analysis_context
from gravity_insight.app_snapshot import app_snapshot
from gravity_insight.errors import (
    ContractChangedError,
    InputValidationError,
    error_detail_from_exception,
)
from gravity_insight.output_projection import apply_output_fields, project_output


class _BatchClient:
    def __init__(self, *, omit: str | None = None, app_cid: object = "91") -> None:
        self.omit = omit
        self.app_cid = app_cid
        self.calls: list[tuple[list[dict], int]] = []

    def batch(self, requests, *, max_workers=6):
        copied = [dict(item) for item in requests]
        self.calls.append((copied, max_workers))
        results = []
        for request in reversed(copied):
            if request["request_id"] == self.omit:
                continue
            operation_id = request["operation_id"]
            data = {"list": [{"id": request["request_id"]}], "page_info": {}}
            if operation_id == "app.detail":
                data = {"app": {"id": "7", "cid": self.app_cid}}
            results.append(
                {
                    "operation_id": operation_id,
                    "request_id": request["request_id"],
                    "ok": True,
                    "status": "success",
                    "data": {"status": "success", "data": data},
                }
            )
        return results


class CapabilityDeepeningTests(unittest.TestCase):
    def test_analysis_context_restores_source_order_and_isolates_missing_result(self):
        client = _BatchClient(omit="metric_tags")

        result = analysis_context(client, "7", max_workers=5)

        self.assertEqual(
            [item["source"] for item in result["results"]],
            [source.source for source in ANALYSIS_CONTEXT_SOURCES],
        )
        missing = result["results"][7]
        self.assertFalse(missing["ok"])
        self.assertEqual(missing["error"]["code"], "BATCH_RESULT_MISSING")
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["exit_code"], 4)
        self.assertEqual(client.calls[0][1], 5)

    def test_app_snapshot_uses_detail_cid_and_keeps_six_stable_sources(self):
        client = _BatchClient(app_cid=91)

        result = app_snapshot(client, 7, max_workers=4)

        self.assertEqual(result["company_id"], 91)
        self.assertEqual(len(result["results"]), 6)
        capacity_request = next(
            request
            for request in client.calls[1][0]
            if request["request_id"] == "capacity"
        )
        self.assertEqual(capacity_request["inputs"], {"company_id": 91})
        self.assertEqual(
            [item["scope"] for item in result["results"]],
            ["app", "app", "company", "workspace", "workspace", "workspace"],
        )

    def test_output_projection_validates_and_projects_dynamic_item_fields(self):
        schema = {
            "response_projection": {
                "data_keys": ["list", "page_info"],
                "item_keys": ["id", "name"],
                "dynamic_item_fields": ["query_fields"],
            }
        }
        envelope = {
            "status": "success",
            "data": {
                "list": [{"id": 1, "name": "x", "cost": 2, "secret": 3}],
                "page_info": {"page": 1},
            },
        }

        projected = project_output(
            schema,
            "report.example.query",
            envelope,
            ["id", "cost"],
            request_inputs={"query_fields": ["cost"]},
        )

        self.assertEqual(projected["data"]["list"], [{"id": 1, "cost": 2}])
        self.assertEqual(projected["data"]["page_info"], {"page": 1})
        with self.assertRaises(InputValidationError):
            project_output(schema, "report.example.query", envelope, ["secret"])

    def test_non_object_operation_output_belongs_to_contract_maintainers(self):
        schema = {"response_projection": {"item_keys": ["id"]}}

        with self.assertRaises(ContractChangedError) as caught:
            apply_output_fields("not-an-object", schema, ["id"])  # type: ignore[arg-type]

        detail = error_detail_from_exception(caught.exception)
        self.assertEqual("CONTRACT_CHANGED", detail.code)
        self.assertEqual("upstream", detail.category)
        self.assertNotEqual("caller", detail.category)
        self.assertIsNone(detail.field)
        self.assertIn("Repair owner:", detail.next_action)
        self.assertIn("not the caller", detail.next_action)
        self.assertIn("Next step:", detail.next_action)
        self.assertIn("Stop condition:", detail.next_action)

    def test_invalid_operation_schema_belongs_to_runtime_contract_owner(self):
        envelope = {"status": "success", "data": {"list": []}}

        for schema in ({}, {"response_projection": []}, []):
            with self.subTest(schema=schema), self.assertRaises(
                ContractChangedError
            ) as caught:
                apply_output_fields(envelope, schema, ["id"])  # type: ignore[arg-type]
            detail = error_detail_from_exception(caught.exception)
            self.assertEqual(("CONTRACT_CHANGED", "upstream"), (
                detail.code, detail.category,
            ))
            self.assertIsNone(detail.field)
            self.assertIn(
                "Repair owner: Gravity Runtime operation-contract maintainer.",
                detail.next_action,
            )
            self.assertIn("Next step:", detail.next_action)
            self.assertIn("Stop condition:", detail.next_action)


if __name__ == "__main__":
    unittest.main()
