from __future__ import annotations

import threading
import unittest

from gravity_sdk.errors import ContractChangedError, InputValidationError, PaginationError
from gravity_sdk.multidim_product import (
    FRONTEND_ADREPORT_DATA_CONF,
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
        "filters": [{"field": "click_company", "operator": "IN", "values": ["CN"]}],
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
        self.assertEqual(
            (1, "unproven_single_condition_only"),
            (
                schema["x-cli-shortcuts"]["filter"]["max_occurrences"],
                schema["x-cli-shortcuts"]["filter"]["combination_logic"],
            ),
        )
        self.assertEqual(
            [
                "CONTAINS", "EQUALS", "GT", "GTE", "IN", "LT", "LTE",
                "NOT_EQUALS", "NOT_IN", "RANGE_IN",
            ],
            schema["properties"]["filters"]["items"]["properties"]["operator"]["enum"],
        )
        cases = [
            {**_inputs(), "page": 1},
            {**_inputs(), "date_list": ["2026-8-1", "2026-08-07"]},
            {**_inputs(), "date_list": ["2026-08-08", "2026-08-07"]},
            {**_inputs(), "metrics_list": ["x"] * 501},
            {**_inputs(), "metrics_list": [""]},
            {**_inputs(), "filters": [{"field": "x", "operator": False, "values": []}]},
            {**_inputs(), "filters": [{"field": "x", "operator": 1, "values": []}]},
            {**_inputs(), "filters": [{"field": "x", "operator": "EQUALS", "values": []}]},
            {**_inputs(), "filters": [{"field": "x", "operator": "IN", "values": [[1]]}]},
            {
                **_inputs(),
                "filters": [
                    {"field": "click_company", "operator": "IN", "values": [1 << 13_607]}
                ],
            },
            {**_inputs(), "multi_keys": [7, 2]},
            {**_inputs(), "metrics_list": [], "custom_metrics_list": [], "data_dims": ["country"]},
            {**_inputs(), "metrics_list": [], "custom_metrics_list": [], "relate_dims": ["country"]},
        ]
        for value in cases:
            with self.subTest(value=value), self.assertRaises(InputValidationError):
                normalize_multidim_inputs(value)
        dynamic = {
            **_inputs(),
            "data_dims": ["country"],
            "filters": [{"field": "country", "operator": "EQUALS", "values": ["CN"]}],
        }
        self.assertEqual("country", normalize_multidim_inputs(dynamic)["filters"][0]["field"])
        profiled = normalize_multidim_inputs(
            {**_inputs(), "data_conf": FRONTEND_ADREPORT_DATA_CONF}
        )
        self.assertEqual(FRONTEND_ADREPORT_DATA_CONF, profiled["data_conf"])
        with self.assertRaises(InputValidationError):
            normalize_multidim_inputs(
                {**_inputs(), "data_conf": {**FRONTEND_ADREPORT_DATA_CONF, "accumulate": True}}
            )

    def test_binding_replaces_app_filters_and_prepare_is_value_safe_offline(self) -> None:
        supplied = _inputs()
        supplied["filters"].append({"field": "day", "operator": "EQUALS", "values": ["2026-08-01"]})
        supplied["filters"].append({"field": "app_id", "operator": "IN", "values": [99]})
        bound = bind_multidim_app(supplied, "007")
        self.assertEqual(
            [
                {"field": "click_company", "operator": "IN", "values": ["CN"]},
                {"field": "day", "operator": "EQUALS", "values": ["2026-08-01"]},
                {"field": "app_id", "operator": "EQUALS", "values": ["7"]},
            ],
            bound["filters"],
        )

        class Bomb:
            def __getattribute__(self, _name):
                raise AssertionError("prepare must not access the client")

        preview = prepare_multidim_query(Bomb(), supplied, app_id=7)
        self.assertEqual(MULTIDIM_PREVIEW_SCHEMA_VERSION, preview["schema_version"])
        self.assertEqual(("7", False, False), (preview["app_id"], preview["network_called"], preview["query_executed"]))
        self.assertNotIn("inputs", preview)
        self.assertNotIn("plan_node", preview)
        self.assertNotIn("CN", repr(preview))
        for app_id in ("9" * 129, 10**5000):
            with self.subTest(app_id_type=type(app_id)), self.assertRaises(InputValidationError):
                bind_multidim_app(supplied, app_id)

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

    def test_result_contract_is_strict_and_drops_request_values(self) -> None:
        value = {**_inputs(), "metrics_list": [], "custom_metrics_list": []}
        malformed = [
            {"data": {"list": []}},
            {"status": "mystery", "data": {"list": []}},
            {"status": "success", "data": {"list": [1]}},
            {"status": "empty", "data": {"list": [{"day": "2026-08-01"}]}},
        ]
        for response in malformed:
            client = _Client()
            client.read = lambda *_args, response=response, **_kwargs: response
            with self.subTest(response=response), self.assertRaises(ContractChangedError):
                run_multidim_query(client, value, app_id=7)

        client = _Client()
        client.read = lambda *_args, **_kwargs: {
            "schema_version": "gravity-insight.read.v1",
            "operation_id": "report.multidim.query",
            "status": "success",
            "data": {"list": [{"day": "2026-08-01"}]},
            "page": {"item_count": 1, "has_more": False, "private": "token=secret"},
            "request": {"inputs": {"filters": ["token=secret"]}},
            "next_page_input": {"filters": ["token=secret"]},
            "source": {"private": "token=secret"},
            "fetched_at": "token=secret",
            "warnings": ["token=secret"],
        }
        safe = run_multidim_query(client, value, app_id=7)
        self.assertEqual(
            {"schema_version", "operation_id", "ok", "status", "data", "page", "result_audit"},
            set(safe["query"]),
        )
        self.assertNotIn("token=secret", repr(safe))

        failure = _Client()
        failure.read = lambda *_args, **_kwargs: {
            "ok": False,
            "status": "error",
            "data": {"list": [{"private": "token=secret"}]},
            "error": {"code": "UPSTREAM_UNAVAILABLE", "message": "token=secret"},
        }
        failed = run_multidim_query(failure, value, app_id=7, include_total=True)
        self.assertFalse(failed["ok"])
        self.assertEqual("error", failed["status"])
        self.assertNotIn("data", failed["query"])
        self.assertFalse(any(call[1] == "report.multidim.calc_total" for call in failure.calls))

        for total_response in malformed:
            total_client = _Client()
            total_client.schema = lambda operation_id=None: (
                {"input_fields": {"data_list": {}, "metrics_list": {}}}
                if operation_id == "report.multidim.calc_total"
                else _Client.schema(total_client, operation_id)
            )
            total_client.read = lambda operation_id, _inputs=None, response=total_response: (
                response
                if operation_id == "report.multidim.calc_total"
                else {"status": "success", "data": {"list": [{"day": "2026-08-01"}]}}
            )
            with self.subTest(total_response=total_response), self.assertRaises(ContractChangedError):
                run_multidim_query(total_client, value, app_id=7, include_total=True)


if __name__ == "__main__":
    unittest.main()
