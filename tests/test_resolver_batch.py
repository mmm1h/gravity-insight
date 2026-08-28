from __future__ import annotations

import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk.errors import InputValidationError
from gravity_sdk.resolver_batch import MAX_EXPANDED_ITEMS, resolver_batch_schema, run_many
from gravity_sdk.resolver_support import error_diagnostic, parse_parameter_assignments


class ResolverBatchTests(unittest.TestCase):
    def test_parameter_requires_name_value_pair_without_raising_name_error(self) -> None:
        with self.assertRaises(InputValidationError) as raised:
            parse_parameter_assignments(["missing-separator"])

        self.assertEqual("param", raised.exception.field)
        self.assertIn('actual value: "missing-separator"', str(raised.exception))

    def test_schema_describes_selectors_expansion_and_bounded_execution(self) -> None:
        schema = resolver_batch_schema()

        self.assertEqual("gravity-insight.resolver-batch-schema.v1", schema["schema_version"])
        item = schema["wrapper"]["properties"]["requests"]["items"]
        self.assertEqual(["selector"], item["required"])
        self.assertEqual(
            [
                "all_pages", "app", "apps", "end", "input", "inputs",
                "output_fields", "parameters", "request_id", "selector", "start",
            ],
            item["allowed_fields"],
        )
        self.assertEqual(1, schema["execution"]["inner_page_workers"])
        self.assertEqual(5, schema["execution"]["default_max_pages"])
        self.assertEqual(200, schema["execution"]["default_max_items"])
        self.assertEqual(MAX_EXPANDED_ITEMS, schema["execution"]["max_expanded_items"])

    def test_run_many_expands_apps_preserves_order_and_isolates_failure(self) -> None:
        beta_started = threading.Event()
        calls: list[dict] = []
        lock = threading.Lock()

        def resolve(selector, **kwargs):
            with lock:
                calls.append({"selector": selector, **kwargs})
            if selector == "bad.operation":
                raise InputValidationError("synthetic invalid item", field="selector")
            if kwargs["app"] == "alpha":
                beta_started.wait(2)
            elif kwargs["app"] == "beta":
                beta_started.set()
            return {
                "schema_version": "gravity-insight.resolve.v1",
                "ok": True,
                "status": "success",
                "operation_id": selector.removeprefix("@"),
                "result": {"status": "success", "data": {"list": []}},
            }

        workspace = SimpleNamespace(apps={"beta": 2, "alpha": 1})
        requests = {
            "requests": [
                {
                    "selector": "@weekly",
                    "input": {"token": "must-not-be-echoed"},
                    "parameters": {"event": "purchase"},
                    "apps": "*",
                    "request_id": "weekly",
                    "all_pages": True,
                },
                {
                    "selector": "app.list",
                    "apps": [3, "alpha"],
                    "request_id": "apps",
                },
                {"selector": "bad.operation", "request_id": "bad"},
            ]
        }
        with patch("gravity_sdk.resolver_batch.resolve_and_run", side_effect=resolve):
            result = run_many(
                requests,
                client=object(),
                workspace=workspace,
                max_workers=5,
            )

        self.assertEqual("gravity-insight.resolver-batch.v1", result["schema_version"])
        self.assertEqual(3, result["request_count"])
        self.assertEqual(5, result["total_count"])
        self.assertEqual(4, result["success_count"])
        self.assertEqual(1, result["failure_count"])
        self.assertEqual(2, result["exit_code"])
        self.assertEqual(
            ["weekly:alpha", "weekly:beta", "apps:3", "apps:alpha", "bad"],
            [item["request_id"] for item in result["results"]],
        )
        self.assertEqual("caller", result["results"][-1]["error"]["category"])
        self.assertNotIn("must-not-be-echoed", json.dumps(result))
        self.assertTrue(all(call["max_workers"] == 1 for call in calls))
        self.assertTrue(all(call["max_pages"] == 5 for call in calls))
        self.assertTrue(all(call["max_items"] == 200 for call in calls))
        weekly = [call for call in calls if call["selector"] == "@weekly"]
        self.assertTrue(all(call["read_all"] is True for call in weekly))

    def test_invalid_wrapper_fails_before_any_resolver_work(self) -> None:
        with patch("gravity_sdk.resolver_batch.resolve_and_run") as resolve:
            with self.assertRaises(InputValidationError) as raised:
                run_many(
                    [{"selector": "app.list", "input": {}, "inputs": {}}],
                    client=object(),
                    workspace=SimpleNamespace(apps={}),
                )

        self.assertEqual("inputs", raised.exception.field)
        self.assertIn("batch schema --mode run", raised.exception.next_action)
        resolve.assert_not_called()

    def test_apps_expansion_is_bounded_before_workers_start(self) -> None:
        apps = {f"app-{index}": index + 1 for index in range(MAX_EXPANDED_ITEMS + 1)}
        with patch("gravity_sdk.resolver_batch.resolve_and_run") as resolve:
            with self.assertRaises(InputValidationError) as raised:
                run_many(
                    [{"selector": "app.list", "apps": "*"}],
                    client=object(),
                    workspace=SimpleNamespace(apps=apps),
                )

        self.assertEqual("requests", raised.exception.field)
        resolve.assert_not_called()

    def test_local_exception_text_is_never_exposed_by_resolver_or_batch(self) -> None:
        secret = "transport failed password=hunter2 token=abc123"
        diagnostic = error_diagnostic(RuntimeError(secret), priority=10)
        self.assertNotIn(secret, json.dumps(diagnostic))
        self.assertEqual("local_io_error", diagnostic["code"])

        unsafe_failure = {
            "schema_version": "gravity-insight.resolve.v1",
            "ok": False,
            "status": "error",
            "operation_id": "app.list",
            "diagnostics": [
                {"code": "LOCAL_IO_ERROR", "priority": 10, "message": secret}
            ],
        }
        with patch(
            "gravity_sdk.resolver_batch.resolve_and_run", return_value=unsafe_failure
        ):
            result = run_many(
                [{"selector": "app.list", "request_id": "unsafe"}],
                client=object(),
                workspace=SimpleNamespace(apps={}),
            )

        rendered = json.dumps(result)
        self.assertNotIn("hunter2", rendered)
        self.assertNotIn("abc123", rendered)
        self.assertIsNone(result["results"][0]["result"])
        self.assertIn("request_id alone", result["results"][0]["error"]["next_action"])


if __name__ == "__main__":
    unittest.main()
