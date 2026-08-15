from __future__ import annotations

import json
import re
import threading
import unittest
from pathlib import Path
from typing import Any, Mapping

try:
    from gravity_sdk import GravityInsightClient
    from gravity_sdk.errors import InputValidationError
    from gravity_sdk.transport import TransportResponse
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_sdk import GravityInsightClient
    from gravity_sdk.errors import InputValidationError
    from gravity_sdk.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "src" / "gravity_sdk" / "manifests"
QUERY_ID = "1723000000000Abcdefghijk12345678"


class RoutingTransport:
    is_test_transport = True

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.lock = threading.Lock()

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        with self.lock:
            self.calls.append((method, path, kwargs))
        payload = self.handler(method, path, kwargs)
        return TransportResponse(200, payload, "2026-08-08T06:00:00Z")


def repository_manifest(*operation_ids: str) -> dict[str, Any]:
    all_operations: dict[str, dict[str, Any]] = {}
    for path in sorted(MANIFEST_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        for operation in document.get("operations", []):
            all_operations[operation["operation_id"]] = operation

    selected: dict[str, dict[str, Any]] = {}
    pending = list(operation_ids)
    while pending:
        operation_id = pending.pop()
        if operation_id in selected:
            continue
        operation = all_operations.get(operation_id)
        if operation is None:
            raise AssertionError(f"missing repository operation: {operation_id}")
        selected[operation_id] = operation
        pending.extend(operation.get("required_parent", ()))
    return {"manifest_version": 1, "operations": list(selected.values())}


def client_for(*operation_ids: str, handler, allow_experimental: bool = False):
    transport = RoutingTransport(handler)
    client = GravityInsightClient._from_manifest_for_tests(
        repository_manifest(*operation_ids),
        transport=transport,
        allow_experimental=allow_experimental,
    )
    return client, transport


def page(rows: list[Mapping[str, Any]], *, page_size: int = 2_000) -> dict[str, Any]:
    return {
        "code": 0,
        "data": {
            "list": rows,
            "page_info": {
                "page": 1,
                "page_size": page_size,
                "total_page": 1,
                "total_number": len(rows),
            },
        },
    }


def event_metadata() -> dict[str, Any]:
    return page([{"name": "purchase", "cname": "purchase", "visible": True}])


def clean_event_result() -> dict[str, Any]:
    return {
        "code": 0,
        "data": {
            "list": [
                [
                    {
                        "start_date": "2026-08-07",
                        "end_date": "2026-08-07",
                        "target": {"purchase": 3},
                        "list": [{"purchase": 3}],
                        "event_index": 0,
                    }
                ]
            ],
            "target_list": ["purchase"],
            "default_limit": 50,
            "date_list": [{"start_date": "2026-08-07", "end_date": "2026-08-07"}],
        },
    }


def event_inputs(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "query_id": QUERY_ID,
        "app_id": "101",
        "query_item_list": [
            {
                "event_name": "purchase",
                "event_label": "purchase",
                "custom_name": "purchase",
                "target": {"name": "PresetAllCount", "field": "PresetAllCount"},
                "conditions": [],
                "cond_logic": "AND",
                "event_index": 0,
            }
        ],
        "group_by_list": [
            {"type": "default_event", "field": "create_time", "group_by": "day"}
        ],
        "date_list": [{"start_date": "2026-08-07", "end_date": "2026-08-07"}],
        "calc_layer_y": True,
        "aggregate_config": {
            "to_calc_type": "approximate",
            "period_calc_method_map": {},
        },
        "extra_data": {"client_server_time": "CLIENT"},
    }
    values.update(overrides)
    return values


class GravityInsightAnalysisTests(unittest.TestCase):
    def test_funnel_daily_projection_is_mode_aware_and_fail_closed(self) -> None:
        operation = repository_manifest("analysis.funnel.query")["operations"][0]
        inputs = json.loads(json.dumps(operation["live_probe"]["input"]))
        inputs.update(app_id="101", query_id=QUERY_ID, to_calc_each_day=True)
        daily = {
            "date_list": [{"2026-08-07": [{"cnt": {"0": 3, "1": 2}, "group": None}]}],
            "aggregate_by_date": {"2026-08-07": {"0": 3, "1": 2}},
            "aggregate_date": None,
            "window_funnel_mode": 0,
        }
        cases = ((daily, "success"), ({**daily, "aggregate_by_date": None}, "contract_changed"))
        for data, status in cases:
            client, _ = client_for(
                "analysis.funnel.query",
                handler=lambda *_args, data=data: {"code": 0, "data": data},
            )
            client._executor._field_validator = lambda *_args: None
            result = client.read("analysis.funnel.query", inputs)
            self.assertEqual(status, result["status"])
            if status == "success":
                self.assertEqual([], result["warnings"])

    def test_funnel_rejects_live_incompatible_user_property_type_offline(self) -> None:
        manifest = repository_manifest("analysis.funnel.query")
        inputs = json.loads(json.dumps(manifest["operations"][0]["live_probe"]["input"]))
        inputs.update(
            app_id="101",
            query_id=QUERY_ID,
            date_list=[{"start_date": "2026-08-07", "end_date": "2026-08-07"}],
        )
        for step in inputs["query_item_list"]:
            step["event_name"] = "purchase"
        inputs["global_conditions"] = [
            {
                "operator": "IN",
                "field": "$ea_click_company",
                "type": "user_property",
                "value": ["bytedance"],
            }
        ]
        client, transport = client_for(
            "analysis.funnel.query",
            handler=lambda *_args: (_ for _ in ()).throw(AssertionError("network")),
        )

        invalid = client.validate("analysis.funnel.query", inputs)
        self.assertFalse(invalid["ok"])
        self.assertEqual("INPUT_INVALID", invalid["error"]["code"])
        self.assertEqual("global_conditions", invalid["error"]["field"])
        self.assertIn("type to `user`", invalid["error"]["next_action"])
        with self.assertRaises(InputValidationError):
            client.read("analysis.funnel.query", inputs)

        inputs["global_conditions"][0]["type"] = "user"
        accepted = client.validate("analysis.funnel.query", inputs)
        self.assertTrue(accepted["ok"])
        self.assertEqual("needs_live_metadata", accepted["status"])
        self.assertEqual([], transport.calls)

    def test_analysis_promoted_object_profile_is_fixed_and_supports_full_page(
        self,
    ) -> None:
        def handler(_method: str, path: str, kwargs: Mapping[str, Any]):
            self.assertTrue(path.endswith("user/promoted_object/list/"))
            self.assertEqual("PostBackMap_PostBackMap", kwargs["query"]["origin"])
            self.assertEqual(1, kwargs["query"]["performance_mode"])
            self.assertEqual(5_000, kwargs["query"]["page_size"])
            return page([], page_size=5_000)

        client, transport = client_for("promotion.object.list", handler=handler)
        result = client.read(
            "promotion.object.list",
            {"app_id": "101", "page": 1, "page_size": 5_000},
        )
        self.assertEqual("empty", result["status"])
        self.assertEqual(1, len(transport.calls))
        with self.assertRaises(InputValidationError):
            client.read(
                "promotion.object.list",
                {"app_id": "101", "page": 1, "page_size": 5_001},
            )
        self.assertEqual(1, len(transport.calls))

    def test_stable_metadata_uses_fixed_visible_filter(self) -> None:
        client, transport = client_for(
            "analysis.event.list",
            handler=lambda _method, _path, _kwargs: event_metadata(),
        )
        with self.assertRaises(InputValidationError):
            client.read(
                "analysis.event.list",
                {"app_id": "101", "filters": "[]"},
            )
        self.assertEqual([], transport.calls)

        result = client.read("analysis.event.list", {"app_id": "101"})
        self.assertEqual("success", result["status"])
        query = dict(transport.calls[0][2]["query"])
        self.assertEqual(
            '[{"field":"visible","operator":1,"values":[true]}]',
            query["filters"],
        )

    def test_global_property_metadata_projects_dimension_table_contract(self) -> None:
        nested_dimension = {
            "name": "region_id",
            "cname": "region",
            "data_type": "STRING",
            "dim_using_table_name": "region_dimension",
        }
        client, _transport = client_for(
            "analysis.event_property.list",
            "analysis.user_property.list",
            handler=lambda _method, _path, _kwargs: page(
                [
                    {
                        "name": "region_id",
                        "cname": "region",
                        "data_type": "STRING",
                        "dim_table": [nested_dimension],
                    }
                ]
            ),
        )
        for operation_id in (
            "analysis.event_property.list",
            "analysis.user_property.list",
        ):
            with self.subTest(operation_id=operation_id):
                result = client.read(
                    operation_id, {"app_id": "101", "page": 1, "page_size": 1}
                )
                self.assertEqual("success", result["status"])
                self.assertEqual(
                    [nested_dimension], result["data"]["list"][0]["dim_table"]
                )

    def test_event_query_attests_event_specific_dimension_table_metadata(self) -> None:
        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path.endswith("event_list/"):
                return event_metadata()
            if path.endswith("event_property_list/"):
                return page([])
            if path.endswith("event_info/"):
                return {
                    "code": 0,
                    "data": {
                        "properties": {
                            "common": [
                                {
                                    "name": "amount",
                                    "cname": "amount",
                                    "data_type": "FLOAT",
                                    "dim_table": [
                                        {
                                            "name": "region_id",
                                            "cname": "region",
                                            "data_type": "STRING",
                                            "dim_using_table_name": "region_dimension",
                                        }
                                    ],
                                }
                            ],
                            "custom": [],
                            "preset": [],
                        }
                    },
                }
            return clean_event_result()

        client, transport = client_for(
            "analysis.event.query",
            "analysis.event.info",
            "analysis.event_property.list",
            handler=handler,
        )
        inputs = event_inputs()
        inputs["query_item_list"][0]["target"] = {
            "name": "SumCount",
            "field": "region_id",
            "dim_using_table_name": "region_dimension",
        }
        result = client.read("analysis.event.query", inputs)
        self.assertEqual("success", result["status"])
        self.assertTrue(
            any(path.endswith("event_info/") for _, path, _ in transport.calls)
        )

        rejected, rejected_transport = client_for(
            "analysis.event.query",
            "analysis.event.info",
            "analysis.event_property.list",
            handler=handler,
        )
        invalid = event_inputs()
        invalid["query_item_list"][0]["target"] = {
            "name": "SumCount",
            "field": "region_id",
            "dim_using_table_name": "unregistered_dimension",
        }
        with self.assertRaisesRegex(InputValidationError, "dimension table"):
            rejected.read("analysis.event.query", invalid)
        self.assertFalse(
            any(
                path.endswith("dataanalysis/query_sql/")
                for _, path, _ in rejected_transport.calls
            )
        )

    def test_event_query_accepts_object_dates_and_projects_exact_aggregate_shape(
        self,
    ) -> None:
        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path.endswith("event_list/"):
                return event_metadata()
            if path.endswith("event_property_list/"):
                return page([])
            return clean_event_result()

        client, transport = client_for(
            "analysis.event.query", "analysis.event_property.list", handler=handler
        )
        result = client.read("analysis.event.query", event_inputs())

        self.assertEqual("success", result["status"])
        self.assertEqual(3, len(transport.calls))
        self.assertEqual("POST", transport.calls[-1][0])
        self.assertEqual(
            "/report/api/v3/dataanalysis/query_sql/", transport.calls[-1][1]
        )
        self.assertEqual(QUERY_ID, transport.calls[-1][2]["body"]["query_id"])
        self.assertEqual(
            {"list", "target_list", "default_limit", "date_list"},
            set(result["data"]),
        )
        self.assertEqual([], result["warnings"])

    def test_event_query_accepts_preset_user_count_with_user_filter(self) -> None:
        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path.endswith("event_list/"):
                return event_metadata()
            if path.endswith("event_property_list/"):
                return page([])
            if path.endswith("user_property_list/"):
                return page(
                    [
                        {
                            "name": "$pay_count",
                            "cname": "pay count",
                            "data_type": "INT",
                            "visible": True,
                        }
                    ]
                )
            if path.endswith("event_info/"):
                raise AssertionError("PresetUserCount must not require event metadata")
            return clean_event_result()

        client, transport = client_for(
            "analysis.event.query",
            "analysis.event_property.list",
            "analysis.user_property.list",
            handler=handler,
        )
        inputs = event_inputs()
        inputs["query_item_list"][0]["target"] = {
            "name": "PresetUserCount",
            "field": "PresetUserCount",
        }
        inputs["query_item_list"][0]["conditions"] = [
            {
                "operator": "GREATER",
                "field": "$pay_count",
                "type": "user",
                "value": ["0"],
            }
        ]

        result = client.read("analysis.event.query", inputs)

        self.assertEqual("success", result["status"])
        self.assertFalse(
            any(path.endswith("event_info/") for _, path, _ in transport.calls)
        )

    def test_event_split_and_custom_scatter_use_full_frontend_structures(self) -> None:
        def handler(_method: str, path: str, kwargs: Mapping[str, Any]):
            if path.endswith("event_list/"):
                return event_metadata()
            if path.endswith("event_property_list/"):
                return page(
                    [
                        {
                            "name": "amount",
                            "cname": "amount",
                            "data_type": "FLOAT",
                            "visible": True,
                        }
                    ]
                )
            if path.endswith("dataanalysis/scatter/"):
                item = kwargs["body"]["query_item_list"][0]
                self.assertEqual(
                    {"zone_type": "custom", "range_list": [0, 10, 100]},
                    item["calc_zone"],
                )
                self.assertEqual("amount", item["prop_to_calc"])
                return {"code": 0, "data": {}}
            split = kwargs["body"]["split_event"]
            self.assertEqual("after", split["order"])
            self.assertEqual(["purchase"], split["event_list"])
            self.assertEqual("amount", split["group_by_list"][0]["field"])
            return clean_event_result()

        event_client, _event_transport = client_for(
            "analysis.event.query",
            "analysis.event_property.list",
            handler=handler,
        )
        event_result = event_client.read(
            "analysis.event.query",
            event_inputs(
                split_event={
                    "order": "after",
                    "event_list": ["purchase"],
                    "group_by_list": [
                        {
                            "type": "event",
                            "field": "amount",
                            "group_by": "amount",
                        }
                    ],
                }
            ),
        )
        self.assertEqual("success", event_result["status"])

        scatter_client, _scatter_transport = client_for(
            "analysis.scatter.query",
            "analysis.event_property.list",
            handler=handler,
        )
        scatter_result = scatter_client.read(
            "analysis.scatter.query",
            {
                "query_id": QUERY_ID,
                "app_id": "101",
                "query_item_list": [
                    {
                        **event_inputs()["query_item_list"][0],
                        "calc_zone": {
                            "zone_type": "custom",
                            "range_list": [0, 10, 100],
                        },
                        "prop_to_calc": "amount",
                        "prop_to_calc_sub": "SumCount",
                    }
                ],
                "date_list": [{"start_date": "2026-08-07", "end_date": "2026-08-07"}],
            },
        )
        self.assertEqual("empty", scatter_result["status"])

    def test_query_id_and_deep_input_rejections_happen_before_network(self) -> None:
        client, transport = client_for(
            "analysis.event.query",
            handler=lambda *_args: (_ for _ in ()).throw(AssertionError("network")),
        )
        invalid_cases = [
            event_inputs(query_id="caller-controlled"),
            event_inputs(
                date_list=[{"start_date": "2026-01-01", "end_date": "2026-08-07"}]
            ),
            event_inputs(
                query_item_list=[
                    {
                        **event_inputs()["query_item_list"][0],
                        "query_sql": "select 1",
                    }
                ]
            ),
        ]
        for inputs in invalid_cases:
            with self.subTest(inputs=inputs), self.assertRaises(InputValidationError):
                client.read("analysis.event.query", inputs)
        self.assertEqual([], transport.calls)

    def test_unknown_event_stops_after_live_metadata(self) -> None:
        client, transport = client_for(
            "analysis.event.query",
            handler=lambda _method, _path, _kwargs: event_metadata(),
        )
        inputs = event_inputs()
        inputs["query_item_list"][0]["event_name"] = "not_registered"
        with self.assertRaisesRegex(InputValidationError, "absent from live metadata"):
            client.read("analysis.event.query", inputs)
        self.assertEqual(1, len(transport.calls))
        self.assertTrue(transport.calls[0][1].endswith("event_list/"))

    def test_custom_user_property_target_uses_live_metadata(self) -> None:
        metadata = page(
            [
                {
                    "name": "score",
                    "cname": "score",
                    "is_preset": False,
                    "visible": True,
                }
            ]
        )

        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path.endswith("user_property_list/"):
                return metadata
            return {"code": 0, "data": {"target": "score", "list": [{"value": 3}]}}

        client, transport = client_for(
            "analysis.property.query", handler=handler, allow_experimental=True
        )
        inputs = {
            "query_id": QUERY_ID,
            "app_id": "101",
            "query_item": {
                "target": {
                    "name": "SumCount",
                    "field": "score",
                    "cname": "score",
                    "data_type": "INT",
                },
                "conditions": [],
                "custom_name": "score",
            },
        }
        result = client.read("analysis.property.query", inputs)
        self.assertEqual("success", result["status"])
        self.assertEqual(2, len(transport.calls))
        self.assertTrue(transport.calls[0][1].endswith("user_property_list/"))

    def test_property_group_can_return_requested_user_identifier_values(self) -> None:
        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path.endswith("user_property_list/"):
                return page(
                    [
                        {
                            "name": "client_id",
                            "cname": "ClientID",
                            "data_type": "STRING",
                            "visible": True,
                        }
                    ]
                )
            return {
                "code": 0,
                "data": {
                    "target": "PresetUserCount",
                    "list": [{"client_id": "client-raw-1", "value": 1}],
                },
            }

        client, _transport = client_for(
            "analysis.property.query",
            handler=handler,
        )
        result = client.read(
            "analysis.property.query",
            {
                "query_id": QUERY_ID,
                "app_id": "101",
                "query_item": {
                    "target": {
                        "name": "PresetUserCount",
                        "field": "PresetUserCount",
                        "cname": "",
                        "data_type": "INT",
                    },
                    "conditions": [],
                    "custom_name": "",
                },
                "group_by_list": [
                    {
                        "type": "user_property",
                        "field": "client_id",
                        "group_by": "client_id",
                    }
                ],
            },
        )
        self.assertEqual("success", result["status"])
        self.assertEqual("client-raw-1", result["data"]["list"][0]["client_id"])

    def test_retention_projection_drops_identifiers_from_dynamic_containers(
        self,
    ) -> None:
        retention = {
            "code": 0,
            "data": {
                "total": [
                    {
                        "group_cols": ["client-secret-123"],
                        "values": [1, 2],
                        "percent_values": [100.0, 50.0],
                        "is_total": True,
                        "uid": "private-uid",
                    }
                ],
                "x": [],
                "y": [],
                "date_to_week": {},
                "date_to_month": {},
                "extra_data": {"clientid": "private-client"},
            },
        }

        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path.endswith("event_list/"):
                return event_metadata()
            if path.endswith("event_property_list/"):
                return page([])
            return retention

        client, transport = client_for(
            "analysis.retention.query",
            "analysis.event_property.list",
            handler=handler,
            allow_experimental=True,
        )
        step = event_inputs()["query_item_list"][0]
        second = {**step, "event_index": 1}
        result = client.read(
            "analysis.retention.query",
            {
                "query_id": QUERY_ID,
                "app_id": "101",
                "query_item_list": [step, second],
                "date_list": [{"start_date": "2026-08-07", "end_date": "2026-08-07"}],
            },
        )
        encoded = json.dumps(result["data"], ensure_ascii=False)
        self.assertEqual("success", result["status"])
        self.assertIn("response_drift", result["result_audit"])
        self.assertNotIn("private", encoded)
        self.assertNotIn("uid", encoded.casefold())
        fields = result["result_audit"]["response_drift"]["fields"]
        self.assertTrue(all(set(field) == {"path", "observed_type"} for field in fields))
        self.assertEqual(3, len(transport.calls))

    def test_retention_accepts_typed_before_after_and_rejects_unsafe_formula(
        self,
    ) -> None:
        def handler(_method: str, path: str, kwargs: Mapping[str, Any]):
            if path.endswith("event_list/"):
                return event_metadata()
            if path.endswith("event_property_list/"):
                return page([])
            before_after = kwargs["body"]["query_item_before_after"]
            self.assertEqual("+", before_after["formula"])
            self.assertEqual("two_point", before_after["decimal_point"])
            self.assertEqual("purchase", before_after["after"]["event_name"])
            row = {
                "group_cols": [], "init_custom_before_components": [],
                "init_custom_before_num": 0, "init_num": 2, "is_total": 1,
                "percent_values": ["100.00%"], "percent_values_loss": ["0.00%"],
                "values": [2], "values_another_event": [{"cumulative_total": 1, "period_calc_method": "SUM"}],
                "values_loss": [1],
            }
            return {"code": 0, "data": {
                "total": [row], "x": ["2026-08-07"],
                "y": {"2026-08-07": [row]},
                "date_to_week": {"2026-08-03": [row]},
                "date_to_month": {"2026-08-01": [row]},
            }}

        client, transport = client_for(
            "analysis.retention.query",
            "analysis.event_property.list",
            handler=handler,
        )
        step = event_inputs()["query_item_list"][0]
        inputs = {
            "query_id": QUERY_ID,
            "app_id": "101",
            "query_item_list": [step, {**step, "event_index": 1}],
            "date_list": [{"start_date": "2026-08-07", "end_date": "2026-08-07"}],
            "query_item_before_after": {
                "after": {
                    "event_name": "purchase",
                    "custom_name": "purchase",
                    "target": {
                        "name": "PresetAllCount",
                        "field": "PresetAllCount",
                    },
                    "conditions": [],
                    "cond_logic": "AND",
                    "prop_to_calc": "PresetAllCount",
                    "prop_to_calc_target": "PresetAllCount",
                },
                "formula": "+",
                "decimal_point": "two_point",
                "before_decimal_point": "integer",
                "a_to_b": True,
                "name": "return metric",
            },
        }
        result = client.read("analysis.retention.query", inputs)
        self.assertEqual("success", result["status"])
        self.assertTrue(
            any(path.endswith("user/retention/") for _, path, _ in transport.calls)
        )

        invalid = json.loads(json.dumps(inputs))
        invalid["query_item_before_after"]["formula"] = "**"
        with self.assertRaisesRegex(InputValidationError, "formula"):
            client.read("analysis.retention.query", invalid)
        self.assertEqual(
            1,
            sum(path.endswith("user/retention/") for _, path, _ in transport.calls),
        )

    def test_segment_codec_hides_raw_filters_and_uses_exact_get_query(self) -> None:
        client, transport = client_for(
            "analysis.segment.list",
            handler=lambda _method, _path, _kwargs: page([], page_size=1),
            allow_experimental=True,
        )
        with self.assertRaises(InputValidationError):
            client.read(
                "analysis.segment.list",
                {"app_id": "101", "filters": "[]"},
            )
        self.assertEqual([], transport.calls)

        result = client.read(
            "analysis.segment.list", {"app_id": "101", "page": 1, "page_size": 1}
        )
        self.assertEqual("empty", result["status"])
        method, _path, kwargs = transport.calls[0]
        self.assertEqual("GET", method)
        self.assertEqual({}, dict(kwargs["body"]))
        query = dict(kwargs["query"])
        self.assertFalse(query["to_response_origin_query"])
        self.assertEqual(
            [{"field": "app_id", "operator": 1, "values": [101]}],
            json.loads(query["filters"]),
        )

    def test_event_info_probe_resolves_parent_and_projects_dimension_tables(
        self,
    ) -> None:
        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path.endswith("/open_app/list/"):
                return page([{"id": 101, "name": "app"}], page_size=1)
            if path.endswith("event_list/"):
                return event_metadata()
            if path.endswith("event_info/"):
                row = {
                    "name": "amount",
                    "cname": "amount",
                    "data_type": "FLOAT",
                    "is_preset": True,
                    "dim_table": [
                        {
                            "name": "region_id",
                            "cname": "region",
                            "data_type": "STRING",
                            "dim_using_table_name": "region_dimension",
                        }
                    ],
                    "extra": {"private": "omitted"},
                    "rules": [{"private": "omitted"}],
                }
                return {
                    "code": 0,
                    "data": {
                        "properties": {
                            "common": [row],
                            "custom": [],
                            "preset": [],
                        }
                    },
                }
            raise AssertionError(path)

        client, transport = client_for("analysis.event.info", handler=handler)
        result = client.probe("analysis.event.info")
        self.assertEqual("success", result["status"])
        self.assertEqual(
            {"common", "custom", "preset"}, set(result["data"]["properties"])
        )
        self.assertEqual(
            [
                {
                    "name": "region_id",
                    "cname": "region",
                    "data_type": "STRING",
                    "dim_using_table_name": "region_dimension",
                }
            ],
            result["data"]["properties"]["common"][0]["dim_table"],
        )
        self.assertNotIn("private", json.dumps(result["data"]))
        self.assertEqual(3, len(transport.calls))

    def test_user_detail_rejects_unregistered_controls_before_network(self) -> None:
        client, transport = client_for(
            "analysis.user_detail.list",
            handler=lambda *_args: (_ for _ in ()).throw(AssertionError("network")),
        )
        with self.assertRaises(InputValidationError):
            client.read(
                "analysis.user_detail.list",
                {"app_id": "101", "query_sql": "select 1"},
            )
        self.assertEqual([], transport.calls)

    def test_user_detail_supports_full_typed_query_and_standard_pagination(
        self,
    ) -> None:
        def handler(_method: str, path: str, kwargs: Mapping[str, Any]):
            if path.endswith(
                ("user_property_list/", "event_property_list/", "segment/list/")
            ):
                return page([])
            if path.endswith("user/detail/list/"):
                body = kwargs["body"]
                self.assertRegex(body["query_id"], r"^\d{13}[A-Za-z0-9]{19}$")
                self.assertEqual(101, body["app_id"])
                self.assertEqual(1, body["page"])
                self.assertEqual(1, body["page_size"])
                self.assertEqual("AND", body["user_cond_logic"])
                self.assertEqual("OR", body["postback_cond_logic"])
                self.assertEqual([], body["order_by_list"])
                self.assertEqual([], body["postback_conditions"])
                self.assertEqual(
                    [
                        {
                            "operator": "RANGE_IN",
                            "field": "create_date_list",
                            "type": "default_user",
                            "value": [
                                "2026-08-08 00:00:00",
                                "2026-08-08 23:59:59",
                            ],
                        },
                        {
                            "operator": "IN",
                            "field": "client_id_list",
                            "type": "default_user",
                            "value": ["client-1"],
                        },
                    ],
                    body["global_conditions"],
                )
                return page(
                    [
                        {
                            "ClientID": "client-1",
                            "user_id": "uid-1",
                            "device_id": "device-1",
                            "Name": "registered-name",
                        }
                    ],
                    page_size=1,
                )
            raise AssertionError(path)

        client, transport = client_for(
            "analysis.user_detail.list",
            "analysis.user_property.list",
            "analysis.event_property.list",
            "analysis.segment.list",
            handler=handler,
        )
        result = client.read(
            "analysis.user_detail.list",
            {
                "app_id": "101",
                "client_id": "client-1",
                "date": "2026-08-08",
                "fields": ["ClientID", "user_id", "device_id"],
                "page": 1,
                "page_size": 1,
                "postback_cond_logic": "OR",
            },
        )
        self.assertEqual("success", result["status"])
        self.assertEqual("client-1", result["data"]["list"][0]["ClientID"])
        self.assertEqual("uid-1", result["data"]["list"][0]["user_id"])
        self.assertEqual("device-1", result["data"]["list"][0]["device_id"])
        self.assertEqual("registered-name", result["data"]["list"][0]["Name"])
        self.assertEqual(4, len(transport.calls))

    def test_user_detail_accepts_registered_personal_fields(self) -> None:
        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path.endswith(
                ("user_property_list/", "event_property_list/", "segment/list/")
            ):
                return page([])
            if path.endswith("user/detail/list/"):
                return page([{
                    "AdClickTime": "2026-08-08 01:02:03",
                    "Name": "registered-name",
                    "WXOpenID": "registered-open-id",
                    "bytedanceMid1": 7,
                    "user$city": "registered-city",
                    "userdevice_id": "registered-device",
                }])
            raise AssertionError(path)

        client, transport = client_for(
            "analysis.user_detail.list",
            "analysis.user_property.list",
            "analysis.event_property.list",
            "analysis.segment.list",
            handler=handler,
        )

        result = client.read(
            "analysis.user_detail.list",
            {
                "app_id": "101",
                "fields": [
                    "AdClickTime",
                    "Name",
                    "WXOpenID",
                    "bytedanceMid1",
                    "user$city",
                    "userdevice_id",
                ],
            },
        )

        self.assertEqual("success", result["status"])
        self.assertEqual(
            {
                "AdClickTime": "2026-08-08 01:02:03",
                "Name": "registered-name",
                "WXOpenID": "registered-open-id",
                "bytedanceMid1": 7,
                "user$city": "registered-city",
                "userdevice_id": "registered-device",
            },
            result["data"]["list"][0],
        )
        self.assertTrue(any(path.endswith("user/detail/list/") for _, path, _ in transport.calls))

    def test_user_detail_154th_top_level_key_is_recorded_additive_drift(self) -> None:
        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path.endswith(
                ("user_property_list/", "event_property_list/", "segment/list/")
            ):
                return page([])
            if path.endswith("user/detail/list/"):
                return page([{"Name": "registered", "future_154": "new"}])
            raise AssertionError(path)

        client, _transport = client_for(
            "analysis.user_detail.list",
            "analysis.user_property.list",
            "analysis.event_property.list",
            "analysis.segment.list",
            handler=handler,
        )

        result = client.read(
            "analysis.user_detail.list",
            {"app_id": "101", "fields": ["Name"]},
        )

        self.assertEqual("success", result["status"])
        self.assertIn("response_drift", result["result_audit"])
        self.assertEqual({"Name": "registered"}, result["data"]["list"][0])
        self.assertNotIn("future_154", result["data"]["list"][0])

    def test_order_and_monetization_project_selected_total_metrics(self) -> None:
        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path.endswith(
                ("user_property_list/", "event_property_list/", "segment/list/")
            ):
                return page([])
            if path.endswith("user/pay_event/list/"):
                payload = page([{"Amount": 10, "BackAmount": 2}], page_size=1)
                payload["data"]["total"] = [{"Amount": 10, "BackAmount": 2}]
                return payload
            if path.endswith("monetization_detail/list/"):
                payload = page([{"event$ecpm": 3.5, "samount": 7}], page_size=1)
                payload["data"]["total"] = [{"event$ecpm": 3.5, "samount": 7}]
                return payload
            raise AssertionError(path)

        client, _transport = client_for(
            "analysis.order_detail.list",
            "analysis.monetization_detail.list",
            "analysis.user_property.list",
            "analysis.event_property.list",
            "analysis.segment.list",
            handler=handler,
        )
        order = client.read(
            "analysis.order_detail.list",
            {
                "app_id": "101",
                "date": "2026-08-08",
                "fields": ["Amount", "BackAmount"],
                "page_size": 1,
            },
        )
        self.assertEqual("success", order["status"])
        self.assertEqual([{"Amount": 10, "BackAmount": 2}], order["data"]["total"])

        monetization = client.read(
            "analysis.monetization_detail.list",
            {
                "app_id": "101",
                "date": "2026-08-08",
                "fields": ["event$ecpm", "samount"],
                "page_size": 1,
            },
        )
        self.assertEqual("success", monetization["status"])
        self.assertEqual(
            [{"event$ecpm": 3.5, "samount": 7}],
            monetization["data"]["total"],
        )

    def test_user_postback_log_uses_exact_unpaged_object_contract(self) -> None:
        def handler(method: str, path: str, kwargs: Mapping[str, Any]):
            self.assertEqual("POST", method)
            self.assertTrue(path.endswith("user/postback_log/list/"))
            self.assertEqual({"app_id": 101, "client_id": "client-1"}, kwargs["body"])
            return {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "event_type": "purchase",
                            "status": "success",
                            "postback_time": "2026-08-08 10:00:00",
                            "trace_id": "trace-1",
                        }
                    ]
                },
            }

        client, transport = client_for(
            "analysis.user_postback_log.list", handler=handler
        )
        result = client.read(
            "analysis.user_postback_log.list",
            {"app_id": "101", "client_id": "client-1"},
        )
        self.assertEqual("success", result["status"])
        self.assertEqual("trace-1", result["data"]["list"][0]["trace_id"])
        self.assertEqual(1, len(transport.calls))

    def test_user_event_supports_date_range_selected_fields_and_full_profiles(
        self,
    ) -> None:
        def handler(_method: str, path: str, kwargs: Mapping[str, Any]):
            if path.endswith("event_list/"):
                return event_metadata()
            if path.endswith("event_property_list/"):
                return page(
                    [
                        {
                            "name": "amount",
                            "cname": "amount",
                            "data_type": "FLOAT",
                            "visible": True,
                        }
                    ]
                )
            if path.endswith(("user_property_list/", "segment/list/")):
                return page([])
            if path.endswith("user/event/list/"):
                body = kwargs["body"]
                self.assertEqual(["2026-08-01", "2026-08-08"], body["date_list"])
                self.assertEqual({"page": 2, "page_size": 20}, body["page_info"])
                self.assertEqual("hour", body["group_by"])
                self.assertNotIn("fields", body)
                return {
                    "code": 0,
                    "data": {
                        "event_timeline": [
                            {
                                "timeline": "2026-08-08",
                                "list": [
                                    {
                                        "事件名称": "purchase",
                                        "事件时间": "2026-08-08 10:00:00",
                                        "amount": 3,
                                        "unselected": "omitted",
                                    }
                                ],
                            }
                        ],
                        "summary": [],
                        "device": {
                            "Oaid": "registered-device-id",
                            "Phone_Brand": "brand",
                        },
                        "user": {"ClientID": "client-1", "user_id": "user-1"},
                        "re_attribute_records": [{"ReAttributeAdAid": "aid-1"}],
                    },
                }
            raise AssertionError(path)

        client, _transport = client_for(
            "analysis.user_event.list",
            "analysis.event.list",
            "analysis.event_property.list",
            "analysis.user_property.list",
            "analysis.segment.list",
            handler=handler,
        )
        result = client.read(
            "analysis.user_event.list",
            {
                "app_id": "101",
                "client_id": "client-1",
                "date_list": ["2026-08-01", "2026-08-08"],
                "page": 2,
                "page_size": 20,
                "group_by": "hour",
                "event_list": ["purchase"],
                "fields": ["amount"],
            },
        )
        self.assertEqual("success", result["status"])
        event = result["data"]["event_timeline"][0]["list"][0]
        self.assertEqual(3, event["amount"])
        self.assertNotIn("unselected", event)
        self.assertEqual("registered-device-id", result["data"]["device"]["Oaid"])
        self.assertEqual("brand", result["data"]["device"]["Phone_Brand"])
        self.assertEqual("user-1", result["data"]["user"]["user_id"])
        self.assertEqual(
            "aid-1",
            result["data"]["re_attribute_records"][0]["ReAttributeAdAid"],
        )

    def test_user_event_requires_one_date_source_and_bounded_manual_page(self) -> None:
        client, transport = client_for(
            "analysis.user_event.list",
            handler=lambda *_args: (_ for _ in ()).throw(AssertionError("network")),
        )
        invalid_inputs = (
            {"app_id": "101", "client_id": "client-1"},
            {
                "app_id": "101",
                "client_id": "client-1",
                "date": "2026-08-08",
                "date_list": ["2026-08-01", "2026-08-08"],
            },
            {
                "app_id": "101",
                "client_id": "client-1",
                "date": "2026-08-08",
                "page_size": 201,
            },
        )
        for inputs in invalid_inputs:
            with self.subTest(inputs=inputs), self.assertRaises(InputValidationError):
                client.read("analysis.user_event.list", inputs)
        self.assertEqual([], transport.calls)

    def test_user_event_conditions_use_event_specific_dimension_metadata(self) -> None:
        def handler(_method: str, path: str, kwargs: Mapping[str, Any]):
            if path.endswith("event_list/"):
                return event_metadata()
            if path.endswith(
                ("user_property_list/", "event_property_list/", "segment/list/")
            ):
                return page([])
            if path.endswith("event_info/"):
                return {
                    "code": 0,
                    "data": {
                        "properties": {
                            "common": [
                                {
                                    "name": "amount",
                                    "cname": "amount",
                                    "data_type": "FLOAT",
                                    "dim_table": [
                                        {
                                            "name": "region_id",
                                            "cname": "region",
                                            "data_type": "STRING",
                                            "dim_using_table_name": "region_dimension",
                                        }
                                    ],
                                }
                            ],
                            "custom": [],
                            "preset": [],
                        }
                    },
                }
            if path.endswith("user/event/list/"):
                condition = kwargs["body"]["query_item_list"][0]["conditions"][0]
                self.assertEqual("region_dimension", condition["dim_using_table_name"])
                return {"code": 0, "data": {"event_timeline": []}}
            raise AssertionError(path)

        client, _transport = client_for(
            "analysis.user_event.list",
            "analysis.event.info",
            "analysis.event.list",
            "analysis.event_property.list",
            "analysis.user_property.list",
            "analysis.segment.list",
            handler=handler,
        )
        result = client.read(
            "analysis.user_event.list",
            {
                "app_id": "101",
                "client_id": "client-1",
                "date": "2026-08-08",
                "query_item_list": [
                    {
                        "event_name": "purchase",
                        "event_label": "purchase",
                        "cond_logic": "AND",
                        "conditions": [
                            {
                                "operator": "IN",
                                "field": "region_id",
                                "type": "event",
                                "value": ["north"],
                                "dim_using_table_name": "region_dimension",
                            }
                        ],
                    }
                ],
            },
        )
        self.assertEqual("empty", result["status"])

    def test_segment_member_wire_matches_frontend_and_preserves_page_info(self) -> None:
        def handler(_method: str, path: str, kwargs: Mapping[str, Any]):
            if path.endswith(("user_property_list/", "event_property_list/")):
                return page([])
            if path.endswith("segment/list/"):
                return page([{"segment_id": "8", "app_id": 101}])
            if path.endswith("segment/user/detail/list/"):
                self.assertEqual(
                    {
                        "tmp_segment_id": 8,
                        "app_id": 101,
                        "segment_id": 8,
                        "to_update_segment": False,
                    },
                    kwargs["body"],
                )
                return page([{
                    "ClientID": "client-1",
                    "Name": "member",
                    "WXOpenID": "open-id",
                    "device_info": {"Imei": "device-id"},
                }], page_size=20)
            raise AssertionError(path)

        client, _transport = client_for(
            "analysis.segment.user_detail.list",
            "analysis.user_property.list",
            "analysis.event_property.list",
            "analysis.segment.list",
            handler=handler,
        )
        result = client.read(
            "analysis.segment.user_detail.list",
            {
                "app_id": "101",
                "segment_id": "8",
                "fields": ["ClientID", "Name", "WXOpenID", "device_info"],
            },
        )
        self.assertEqual("success", result["status"])
        self.assertEqual("client-1", result["data"]["list"][0]["ClientID"])
        self.assertEqual("member", result["data"]["list"][0]["Name"])
        self.assertEqual("open-id", result["data"]["list"][0]["WXOpenID"])
        self.assertEqual("device-id", result["data"]["list"][0]["device_info"]["Imei"])
        self.assertEqual(1, result["data"]["page_info"]["total_page"])
        self.assertIsNone(result["page"])

    def test_analysis_configuration_reads_are_stable_and_contracted(self) -> None:
        operation_ids = {
            "analysis.report_config.get",
            "analysis.event_property_group.list",
            "analysis.report_config.list",
        }
        client, transport = client_for(
            *operation_ids,
            handler=lambda _method, path, _kwargs: (
                {
                    "code": 0,
                    "data": {
                        "config": '{"commonFilter":[]}',
                        "name": "saved-analysis",
                        "remark": "",
                        "update_user_name": "operator",
                    },
                    "extra": {},
                }
                if path.endswith("report_config/info/")
                else (_ for _ in ()).throw(AssertionError(path))
            ),
        )
        operations = {
            item["operation_id"]: item
            for item in client.operations(domain="analysis", stability=None)
            if item["operation_id"] in operation_ids
        }
        self.assertEqual(operation_ids, set(operations))
        self.assertEqual(
            "stable", operations["analysis.report_config.get"]["stability"]
        )
        self.assertTrue(operations["analysis.report_config.get"]["executable"])
        self.assertEqual(
            "stable", operations["analysis.report_config.list"]["stability"]
        )
        self.assertTrue(operations["analysis.report_config.list"]["executable"])
        self.assertEqual(
            "stable", operations["analysis.event_property_group.list"]["stability"]
        )
        self.assertTrue(
            operations["analysis.event_property_group.list"]["executable"]
        )

        result = client.read("analysis.report_config.get", {"app_id": "101", "id": "1"})
        self.assertEqual("success", result["status"])
        self.assertEqual('{"commonFilter":[]}', result["data"]["config"])
        self.assertEqual(1, len(transport.calls))

    def test_event_queries_compose_in_bounded_batch(self) -> None:
        def handler(_method: str, path: str, _kwargs: Mapping[str, Any]):
            if path.endswith("event_list/"):
                return event_metadata()
            if path.endswith("event_property_list/"):
                return page([])
            return clean_event_result()

        client, transport = client_for(
            "analysis.event.query", "analysis.event_property.list", handler=handler
        )
        requests = [
            {
                "operation_id": "analysis.event.query",
                "request_id": f"event-{index}",
                "inputs": event_inputs(
                    query_id=f"172300000000{index}Abcdefghijk12345678"
                ),
            }
            for index in (1, 2)
        ]
        results = client.batch(requests, max_workers=2)
        self.assertEqual(
            ["event-1", "event-2"], [item["request_id"] for item in results]
        )
        self.assertTrue(all(item["ok"] for item in results))
        self.assertEqual(
            2,
            sum(
                path.endswith("query_sql/")
                for _method, path, _kwargs in transport.calls
            ),
        )
        self.assertEqual(
            1,
            sum(
                path.endswith("event_list/")
                for _method, path, _kwargs in transport.calls
            ),
        )

    def test_domain_query_id_format_is_frontend_compatible(self) -> None:
        from gravity_sdk.domains import new_analysis_query_id

        self.assertRegex(
            new_analysis_query_id(), re.compile(r"^\d{13}[A-Za-z0-9]{19}$")
        )


if __name__ == "__main__":
    unittest.main()
