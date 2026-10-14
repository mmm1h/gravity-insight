from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator

from gravity_insight import GravityInsightClient, GravitySDK, InputValidationError
from gravity_insight.agents.metadata_search import metadata_search_capability_cards
from gravity_insight.find import metadata_capability_cards
from gravity_insight.find_metadata import search_metadata
from gravity_insight.material_metrics import (
    CATALOG_ID,
    CATALOG_VERSION,
    SCHEMA_VERSION,
    catalog_document,
    catalog_metadata,
    metric_names,
)
from gravity_insight.material_performance import material_performance
from gravity_insight.plan import AdapterContext
from gravity_insight.plan_metadata_adapter import (
    execute_metadata_plan,
    validate_metadata_plan,
)
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]


def _operation(operation_id: str) -> dict[str, Any]:
    return json.loads(
        (
            ROOT
            / "src"
            / "gravity_insight"
            / "contracts"
            / "operations"
            / f"{operation_id}.json"
        ).read_text(encoding="utf-8")
    )["operation"]


class _Transport:
    is_test_transport = True

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        self.calls.append((method, path, kwargs))
        return TransportResponse(200, self.payload, "2026-10-14T00:00:00Z")


def _client(payload: Mapping[str, Any]) -> tuple[GravityInsightClient, _Transport]:
    transport = _Transport(payload)
    client = GravityInsightClient._from_manifest_for_tests(
        {
            "manifest_version": 1,
            "operations": [
                _operation("app.list"),
                _operation("material.metric.list"),
                _operation("material.report.query"),
            ],
        },
        transport=transport,
    )
    return client, transport


def _context(**overrides: Any) -> AdapterContext:
    values = {
        "node_id": "metadata",
        "execution_id": "metadata",
        "kind": "metadata_search",
        "workspace": None,
        "output_fields": (),
        "dynamic_targets": (),
        "max_pages": 1,
        "max_items": 20,
    }
    values.update(overrides)
    return AdapterContext(**values)


class MaterialMetricCatalogTests(unittest.TestCase):
    def test_catalog_is_versioned_complete_and_schema_valid(self) -> None:
        document = dict(catalog_document())
        schema = json.loads(
            (
                ROOT
                / "src"
                / "gravity_insight"
                / "contracts"
                / "schema"
                / "material-metric-catalog-v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        Draft202012Validator(schema).validate(document)
        metadata = catalog_metadata()
        self.assertEqual(
            (SCHEMA_VERSION, CATALOG_ID, CATALOG_VERSION, 762),
            (
                document["schema_version"],
                document["catalog_id"],
                document["catalog_version"],
                metadata["metric_count"],
            ),
        )
        self.assertEqual(
            {
                "aggregate": 32,
                "bytedance": 132,
                "tencent": 310,
                "kuaishou": 176,
                "gravity": 112,
            },
            metadata["platform_counts"],
        )
        self.assertIn("AdClick", metric_names("aggregate"))
        self.assertIn("stat_cost", metric_names("bytedance"))
        self.assertIn("AppRealRegisterCnt", metric_names("gravity"))

    def test_offline_search_reaches_cli_sdk_plan_and_agent_contracts(self) -> None:
        result = search_metadata(
            "点击数", kind="material_metric", platform="aggregate", limit=5
        )
        self.assertEqual((True, "runtime", "AdClick"), (
            result["offline"], result["scope"], result["results"][0]["name"],
        ))
        self.assertGreaterEqual(result["total"], 1)
        sdk = GravitySDK(insight_factory=lambda: (_ for _ in ()).throw(
            AssertionError("offline catalog must not construct a client")
        ))
        sdk_result = sdk.analysis_vocabulary(
            "AdClick", kind="material_metric", platform="aggregate"
        )
        self.assertEqual((True, 0), (
            sdk_result["ok"], sdk_result["exit_code"]
        ))
        self.assertGreaterEqual(sdk_result["total"], 1)
        request = {
            "query": "AdClick",
            "kind": "material_metric",
            "platform": "aggregate",
            "limit": 5,
        }
        validate_metadata_plan(request, _context())
        plan_result = execute_metadata_plan(request, _context(), database=None)
        self.assertEqual("AdClick", plan_result["results"][0]["name"])

        cards = metadata_search_capability_cards(
            "搜索素材指标", domain="material", platform="aggregate"
        )
        self.assertEqual("metadata:material_metric", cards[0]["selector"])
        self.assertEqual("aggregate", cards[0]["input_template"]["platform"])
        rows, warnings = metadata_capability_cards("AdClick", limit=5)
        self.assertEqual([], warnings)
        aggregate = next(
            card for card in rows
            if card.get("platform") == "aggregate"
            and card.get("request_fragment") == {"metrics_list": ["AdClick"]}
        )
        self.assertTrue(aggregate["offline"])

        with self.assertRaises(InputValidationError):
            search_metadata("", kind="material_metric", platform="bilibili")
        with self.assertRaises(InputValidationError):
            search_metadata("", kind="metric", platform="aggregate")

    def test_dynamic_aggregate_query_is_app_bound_and_safely_projected(self) -> None:
        payload = {
            "code": 0,
            "data": {
                "list": [{
                    "file_name": "creative.mp4",
                    "material_id": "m-1",
                    "designer_id": 7,
                    "designer_name": "private person",
                    "album_id": 9,
                    "create_time": "2026-10-14 01:02:03",
                    "AdClick": 12,
                    "file_url": "https://private.invalid/material",
                    "thumbnail_url": "https://private.invalid/thumbnail",
                }],
                "total": {"AdClick": 12},
                "update_at": {"bytedance": "2026-10-14 02:00:00"},
                "page_info": {
                    "page": 1,
                    "page_size": 10,
                    "total_page": 1,
                    "total_number": 1,
                },
            },
        }
        client, transport = _client(payload)
        result = material_performance(
            client,
            [17],
            "2026-10-14",
            "2026-10-14",
            platforms=("aggregate",),
            metrics={"aggregate": ("AdClick",)},
            gravity_metrics=(),
            data_dimension="designer_id",
            relate_dimensions=("album_id",),
            statistics=("create_time",),
            order_by={"aggregate": ({"field": "AdClick", "sort": 1},)},
            decimal_point=3,
            max_pages=2,
            max_items=10,
        )
        self.assertEqual("success", result["status"])
        component = result["results"][0]
        self.assertEqual(
            {
                "file_name": "creative.mp4",
                "material_id": "m-1",
                "designer_id": 7,
                "album_id": 9,
                "create_time": "2026-10-14 01:02:03",
                "AdClick": 12,
            },
            component["data"]["list"][0],
        )
        self.assertEqual({"AdClick": 12}, component["data"]["total"])
        self.assertEqual(
            {"bytedance": "2026-10-14 02:00:00"},
            component["data"]["update_at"],
        )
        self.assertNotIn("private person", repr(result))
        self.assertNotIn("private.invalid", repr(result))
        body = transport.calls[0][2]["body"]
        self.assertEqual(
            [
                {"field": "ad_platform", "operator": "EQUALS", "values": ["aggregate"]},
                {"field": "app_id", "operator": "IN", "values": ["17"]},
            ],
            body["filters"],
        )
        self.assertEqual(("AdClick", 3), (
            body["metrics_list"][0], body["decimal_point"]
        ))

    def test_unknown_metrics_and_mismatched_time_lines_fail_before_network(self) -> None:
        client, transport = _client({"code": 0, "data": {"list": []}})
        base = {
            "app_ids": [17],
            "start": "2026-10-14",
            "end": "2026-10-14",
            "platforms": ("aggregate",),
            "gravity_metrics": (),
            "max_items": 10,
        }
        with self.assertRaises(InputValidationError):
            material_performance(
                client,
                metrics={"aggregate": ("not_a_metric",)},
                **base,
            )
        with self.assertRaises(InputValidationError):
            material_performance(
                client,
                metrics={"aggregate": ("AdClick",)},
                time_lines={"aggregate": "ACTIVE_TIME"},
                **base,
            )
        self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
