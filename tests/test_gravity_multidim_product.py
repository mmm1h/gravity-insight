from __future__ import annotations

import threading
import unittest

from gravity_sdk.errors import ContractChangedError, InputValidationError, PaginationError
from gravity_sdk.multidim_product import (
    MULTIDIM_INPUT_SCHEMA_VERSION,
    MULTIDIM_PREVIEW_SCHEMA_VERSION,
    bind_multidim_app,
    multidim_input_schema,
    normalize_multidim_inputs,
    prepare_multidim_query,
    run_multidim_query,
)


def _inputs() -> dict[str, object]:
    return {
        "date_list": ["2026-08-01", "2026-08-07"],
        "time_dims": "day",
        "metrics_list": ["ap_cost"],
        "custom_metrics_list": ["custom_cost"],
        "data_dims": [],
        "filters": [{"field": "country", "operator": "IN", "values": ["CN"]}],
    }


class _Client:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def schema(self, operation_id=None):
        self.calls.append(("schema", operation_id))
        resource = "metric" if operation_id.endswith("metric.list") else "custom_metric"
        return {"operation_id": operation_id, "domain": "report", "resource": resource, "action": "list"}

    def read_all(self, operation_id, inputs=None, **bounds):
        self.calls.append(("read_all", operation_id, inputs, bounds, threading.get_ident()))
        rows = {
            "report.multidim.metric.list": [{"name": "ap_cost", "exclusion_dims": []}],
            "report.multidim.custom_metric.list": [{"name": "custom_cost", "exclusion_dims": []}],
            "report.multidim.custom_metric.shared.list": [],
            "report.multidim.query": [{"ap_cost": 1, "custom_cost": 2}],
        }[operation_id]
        return {"status": "success", "data": {"list": rows}, "page": {"item_count": len(rows)}}

    def read(self, operation_id, inputs=None):
        self.calls.append(("read", operation_id, inputs))
        return {
            "status": "success",
            "data": {"list": [{"ap_cost": 1}, {"ap_cost": 2}]},
            "page": {"item_count": 0},
        }


class GravityMultidimProductTests(unittest.TestCase):
    def test_schema_and_normalizer_are_closed_and_bounded(self) -> None:
        schema = multidim_input_schema()
        self.assertEqual(MULTIDIM_INPUT_SCHEMA_VERSION, schema["schema_version"])
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(["date_list", "time_dims", "metrics_list"], schema["required"])
        self.assertEqual(500, schema["properties"]["metrics_list"]["maxItems"])
        self.assertEqual(100, schema["properties"]["data_dims"]["maxItems"])
        cases = [
            {**_inputs(), "page": 1},
            {**_inputs(), "date_list": ["2026-8-1", "2026-08-07"]},
            {**_inputs(), "date_list": ["2026-08-08", "2026-08-07"]},
            {**_inputs(), "metrics_list": ["x"] * 501},
            {**_inputs(), "filters": [{"field": "x", "operator": False, "values": []}]},
            {**_inputs(), "filters": [{"field": "x", "operator": "IN", "values": [[1]]}]},
            {**_inputs(), "multi_keys": [7, 2]},
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(InputValidationError):
                normalize_multidim_inputs(value)

    def test_binding_replaces_app_filters_and_prepare_is_value_safe_offline(self) -> None:
        supplied = _inputs()
        supplied["filters"].append({"field": "app_id", "operator": "IN", "values": [99]})
        bound = bind_multidim_app(supplied, "007")
        apps = [item for item in bound["filters"] if item["field"] == "app_id"]
        self.assertEqual([{"field": "app_id", "operator": "EQUALS", "values": ["7"]}], apps)

        class Bomb:
            def __getattribute__(self, _name):
                raise AssertionError("prepare must not access the client")

        preview = prepare_multidim_query(Bomb(), supplied, app_id=7)
        self.assertEqual(MULTIDIM_PREVIEW_SCHEMA_VERSION, preview["schema_version"])
        self.assertEqual(("7", False, False), (preview["app_id"], preview["network_called"], preview["query_executed"]))
        self.assertNotIn("inputs", preview)
        self.assertNotIn("plan_node", preview)
        self.assertNotIn("CN", repr(preview))

    def test_plan_worker_budget_is_sequential_and_query_receives_same_budget(self) -> None:
        client = _Client()
        caller = threading.get_ident()
        result = run_multidim_query(client, _inputs(), app_id=7, read_all=True, max_workers=1)
        metadata = [call for call in client.calls if call[0] == "read_all" and call[1] != "report.multidim.query"]
        self.assertEqual({caller}, {call[4] for call in metadata})
        self.assertTrue(all(call[3] == {"max_workers": 1} for call in metadata))
        query = next(call for call in client.calls if call[:2] == ("read_all", "report.multidim.query"))
        self.assertEqual({"max_pages": 1000, "max_items": 100000, "max_workers": 1}, query[3])
        self.assertEqual(("7", True, True), (result["app_id"], result["network_called"], result["query_executed"]))

        direct = _Client()
        run_multidim_query(direct, _inputs(), app_id=7, read_all=True, max_workers=6)
        metadata_options = [
            call[3]
            for call in direct.calls
            if call[0] == "read_all" and call[1] != "report.multidim.query"
        ]
        self.assertEqual([{"max_workers": 2}] * 3, metadata_options)

    def test_single_page_item_budget_stops_before_total(self) -> None:
        client = _Client()
        value = {**_inputs(), "metrics_list": [], "custom_metrics_list": []}
        with self.assertRaises(PaginationError):
            run_multidim_query(client, value, app_id=7, include_total=True, max_items=1)
        self.assertFalse(any(call[1] == "report.multidim.calc_total" for call in client.calls))

        for field in ("include_total", "read_all"):
            client.calls.clear()
            with self.subTest(field=field), self.assertRaises(InputValidationError):
                run_multidim_query(client, value, app_id=7, **{field: "false"})
            self.assertEqual([], client.calls)

        client.read = lambda *_args, **_kwargs: {"status": "success", "data": {"list": {}}}
        with self.assertRaises(ContractChangedError):
            run_multidim_query(client, value, app_id=7)


if __name__ == "__main__":
    unittest.main()
