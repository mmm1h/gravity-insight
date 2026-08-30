from __future__ import annotations

import contextlib
import io
import json
import logging
import unittest
from collections.abc import Mapping
from unittest.mock import patch

from gravity_sdk import GravitySDK, cli
from gravity_sdk.errors import error_detail_from_exception, error_envelope
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_user_detail_aggregate_adapter import (
    USER_DETAIL_AGGREGATE_NAME,
    execute_user_detail_aggregate_plan,
    project_user_detail_aggregate_result,
    validate_user_detail_aggregate_plan,
)
from gravity_sdk.user_detail_aggregate_contract import (
    BOUNDS_REQUIRED,
    CARDINALITY_LIMIT,
    FIELD_UNSUPPORTED,
    INPUT_SCHEMA_VERSION,
    MIXED_TYPE,
    METADATA_OPERATION_ID,
    SOURCE_OPERATION_ID,
    AggregateBoundsError,
    normalize_user_detail_aggregate_inputs,
)
from gravity_sdk.user_detail_aggregate_product import run_user_detail_aggregate


SENTINEL = "ISSUE39-USER-ROW-SENTINEL-7f3c"
RECEIPT_A = "a" * 32
RECEIPT_B = "b" * 32


def _audit(receipt_id: str) -> dict[str, object]:
    return {
        "schema_version": "gravity.result-audit.v1",
        "fact_paths": {"operation_id": "/operation_id"},
        "http_receipts": [
            {"receipt_id": receipt_id, "storage_status": "stored"}
        ],
    }


def _metadata() -> dict[str, object]:
    return {
        "schema_version": "gravity-insight.read.v1",
        "ok": True,
        "status": "success",
        "operation_id": METADATA_OPERATION_ID,
        "contract_version": "2",
        "schema_fingerprint": "c" * 64,
        "source": {"contract_fingerprint": "d" * 64},
        "data": {
            "list": [
                {"name": "$pay_count", "data_type": "INT"},
                {"name": "$pay_amount_sum", "data_type": "FLOAT"},
                {"name": "assignment_property", "data_type": "STRING"},
            ]
        },
        "result_audit": _audit(RECEIPT_A),
    }


def _source(
    rows: list[dict[str, object]], *, completeness: str = "complete"
) -> dict[str, object]:
    return {
        "schema_version": "gravity-insight.read.v1",
        "ok": True,
        "status": "empty" if not rows else "success",
        "operation_id": SOURCE_OPERATION_ID,
        "contract_version": "3",
        "schema_fingerprint": "e" * 64,
        "source": {
            "system": "gravity_insight",
            "contract_fingerprint": "f" * 64,
        },
        "request": {"inputs": {"page": 1, "page_size": 100}},
        "data": {"list": rows},
        "page": {
            "number": 1,
            "size": 100,
            "item_count": len(rows),
            "total_pages": 2 if rows else 1,
            "total_items": len(rows),
            "has_more": False,
            "pages_fetched": 2 if rows else 1,
            "fetch_strategy": "parallel_known_total" if rows else "single_page",
        },
        "completeness": completeness,
        "pagination_evidence": "wire",
        "result_audit": _audit(RECEIPT_B),
    }


def _inputs(*, max_cells: int = 200) -> dict[str, object]:
    return {
        "source": {"app_id": "101", "date": "2026-08-29"},
        "filters": [
            {"field": "Version", "operator": "IN", "values": ["1.0", "2.0"]}
        ],
        "group_by": ["Version", "userassignment_property"],
        "measures": [
            {"name": "users", "op": "count"},
            {
                "name": "payers",
                "op": "count_if",
                "condition": {
                    "field": "user$pay_count",
                    "operator": "GT",
                    "values": [0],
                },
            },
            {"name": "revenue", "op": "sum", "field": "user$pay_amount_sum"},
        ],
        "bounds": {"max_pages": 100, "max_items": 10_000, "max_cells": max_cells},
    }


class _Client:
    def __init__(self, source: Mapping[str, object]) -> None:
        self.source = source
        self.calls: list[tuple[str, dict[str, object], dict[str, int]]] = []

    def schema(self, operation_id: str) -> dict[str, object]:
        if operation_id != SOURCE_OPERATION_ID:
            raise AssertionError(operation_id)
        return {
            "operation_id": operation_id,
            "response_projection": {
                "item_keys": [
                    "Version",
                    "LatestLoginDay",
                    "ClientID",
                    "user_id",
                    "device_id",
                    "Name",
                    "device_info",
                ],
                "nested_item_keys": {"device_info": ["Oaid"]},
            },
        }

    def read_all(self, operation_id: str, inputs: Mapping[str, object], **options):
        self.calls.append((operation_id, dict(inputs), dict(options)))
        return _metadata() if operation_id == METADATA_OPERATION_ID else self.source


class UserDetailAggregateTests(unittest.TestCase):
    def test_multi_page_reduction_returns_only_cells_and_value_free_evidence(self) -> None:
        rows = [
            {
                "Version": "1.0",
                "userassignment_property": "control",
                "user$pay_count": 1,
                "user$pay_amount_sum": 4.5,
                "ClientID": f"{SENTINEL}-client",
                "user_id": f"{SENTINEL}-user",
                "device_id": f"{SENTINEL}-device",
                "unused_custom_value": SENTINEL,
            },
            {
                "Version": "1.0",
                "userassignment_property": "control",
                "user$pay_count": 0,
                "user$pay_amount_sum": 0.5,
                "ClientID": f"{SENTINEL}-client-2",
                "user_id": f"{SENTINEL}-user-2",
                "device_id": f"{SENTINEL}-device-2",
                "unused_custom_value": SENTINEL,
            },
            {
                "Version": "2.0",
                "userassignment_property": "treatment",
                "user$pay_count": 2,
                "user$pay_amount_sum": 7.0,
                "ClientID": f"{SENTINEL}-client-3",
                "user_id": f"{SENTINEL}-user-3",
                "device_id": f"{SENTINEL}-device-3",
                "unused_custom_value": SENTINEL,
            },
        ]
        client = _Client(_source(rows))

        result = run_user_detail_aggregate(client, _inputs(), max_workers=4)
        rendered = json.dumps(result, ensure_ascii=False, sort_keys=True)

        self.assertNotIn(SENTINEL, rendered)
        self.assertNotIn("data", result)
        self.assertNotIn("request", result)
        self.assertEqual(6, result["cell_count"])
        self.assertEqual(2, result["group_count"])
        self.assertEqual(2, result["pagination"]["consumed_pages"])
        self.assertEqual(3, result["pagination"]["consumed_items"])
        self.assertEqual("complete", result["pagination"]["completeness"])
        self.assertIn("complete_collection_count", result["pagination"]["claims"]["allowed"])
        self.assertEqual(
            {RECEIPT_A, RECEIPT_B},
            {
                item["receipt_id"]
                for item in result["result_audit"]["http_receipts"]
            },
        )
        self.assertEqual(
            [METADATA_OPERATION_ID, SOURCE_OPERATION_ID],
            [item[0] for item in client.calls],
        )
        self.assertEqual(
            {
                "Version",
                "userassignment_property",
                "user$pay_amount_sum",
                "user$pay_count",
            },
            set(client.calls[1][1]["fields"]),
        )
        cells = {
            (item["group"]["Version"], item["measure"]): item["value"]
            for item in result["cells"]
        }
        self.assertEqual(2, cells[("1.0", "users")])
        self.assertEqual(1, cells[("1.0", "payers")])
        self.assertEqual(5.0, cells[("1.0", "revenue")])

    def test_empty_ungrouped_result_returns_explicit_zero_cells(self) -> None:
        inputs = _inputs()
        inputs["filters"] = []
        inputs["group_by"] = []
        result = run_user_detail_aggregate(_Client(_source([])), inputs)

        self.assertEqual("empty", result["status"])
        self.assertEqual(3, result["cell_count"])
        self.assertEqual(
            {"users": 0, "payers": 0, "revenue": 0},
            {item["measure"]: item["value"] for item in result["cells"]},
        )

    def test_unknown_source_completeness_forbids_complete_collection_claims(self) -> None:
        inputs = _inputs()
        inputs["group_by"] = []
        result = run_user_detail_aggregate(
            _Client(_source([{"Version": "1.0", "user$pay_count": 1, "user$pay_amount_sum": 1.0}], completeness="unknown")),
            inputs,
        )

        self.assertEqual("unknown", result["pagination"]["completeness"])
        self.assertIn(
            "complete_collection_count",
            result["pagination"]["claims"]["forbidden"],
        )

    def test_unsupported_field_fails_before_detail_read(self) -> None:
        inputs = _inputs()
        inputs["group_by"] = ["ClientID"]
        client = _Client(_source([]))

        with self.assertRaises(Exception) as raised:
            run_user_detail_aggregate(client, inputs)

        detail = error_detail_from_exception(raised.exception)
        self.assertEqual(FIELD_UNSUPPORTED, detail.code)
        self.assertEqual("caller", detail.category)
        self.assertEqual([METADATA_OPERATION_ID], [item[0] for item in client.calls])
        self.assertEqual(
            [RECEIPT_A],
            [
                item["receipt_id"]
                for item in error_envelope(raised.exception)["result_audit"][
                    "http_receipts"
                ]
            ],
        )

    def test_mixed_types_fail_atomically_and_sentinel_never_enters_any_boundary(self) -> None:
        rows = [
            {
                "Version": SENTINEL,
                "userassignment_property": "control",
                "user$pay_count": 1,
                "user$pay_amount_sum": 1.0,
                "ClientID": SENTINEL,
                "user_id": SENTINEL,
                "device_id": SENTINEL,
            },
            {
                "Version": 2,
                "userassignment_property": "control",
                "user$pay_count": 1,
                "user$pay_amount_sum": 2.0,
                "ClientID": SENTINEL,
                "user_id": SENTINEL,
                "device_id": SENTINEL,
            },
        ]
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root = logging.getLogger()
        root.addHandler(handler)
        try:
            with self.assertRaises(Exception) as raised:
                run_user_detail_aggregate(_Client(_source(rows)), _inputs())
        finally:
            root.removeHandler(handler)
        envelope = error_envelope(raised.exception, operation_id=SOURCE_OPERATION_ID)
        rendered = json.dumps(envelope, ensure_ascii=False, sort_keys=True)

        self.assertEqual(MIXED_TYPE, envelope["error"]["code"])
        self.assertEqual("upstream", envelope["error"]["category"])
        self.assertNotIn(SENTINEL, str(raised.exception))
        self.assertNotIn(SENTINEL, rendered)
        self.assertNotIn(SENTINEL, stream.getvalue())
        self.assertNotIn("cells", envelope)
        self.assertEqual(
            [RECEIPT_B],
            [
                item["receipt_id"]
                for item in envelope["result_audit"]["http_receipts"]
                if item["receipt_id"] == RECEIPT_B
            ],
        )

    def test_high_cardinality_fails_without_partial_cells(self) -> None:
        rows = [
            {
                "Version": version,
                "userassignment_property": "group",
                "user$pay_count": 1,
                "user$pay_amount_sum": 1.0,
            }
            for version in ("1.0", "2.0")
        ]
        with self.assertRaises(Exception) as raised:
            run_user_detail_aggregate(_Client(_source(rows)), _inputs(max_cells=3))

        detail = error_detail_from_exception(raised.exception)
        self.assertEqual(CARDINALITY_LIMIT, detail.code)
        self.assertEqual("caller", detail.category)
        self.assertNotIn("cells", str(raised.exception))

    def test_missing_or_invalid_bounds_have_one_stable_zero_network_code(self) -> None:
        cases = (
            {key: value for key, value in _inputs().items() if key != "bounds"},
            {**_inputs(), "bounds": {"max_pages": 100, "max_items": 10_000}},
            {
                **_inputs(),
                "bounds": {"max_pages": 100, "max_items": 10_000, "max_cells": 201},
            },
        )
        for value in cases:
            with self.subTest(value=value), self.assertRaises(AggregateBoundsError) as raised:
                normalize_user_detail_aggregate_inputs(value)
            self.assertEqual(BOUNDS_REQUIRED, raised.exception.code)

    def test_existing_json_and_ndjson_row_rendering_is_byte_locked(self) -> None:
        row_result = {
            "schema_version": "gravity-insight.read.v1",
            "operation_id": SOURCE_OPERATION_ID,
            "status": "success",
            "data": {"list": [{"ClientID": "client-1", "Version": "1.0"}]},
            "total": 1,
        }
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            cli._write_json(row_result)
        self.assertEqual(
            '{\n  "data": {\n    "list": [\n      {\n        "ClientID": "client-1",\n        "Version": "1.0"\n      }\n    ]\n  },\n  "operation_id": "analysis.user_detail.list",\n  "schema_version": "gravity-insight.read.v1",\n  "status": "success",\n  "total": 1\n}\n',
            stdout.getvalue(),
        )
        self.assertEqual(
            '{"ClientID": "client-1", "Version": "1.0"}\n'
            '{"_gravity_insight": {"next_page_input": null, "operation_id": '
            '"analysis.user_detail.list", "result_source": null, "rows_written": 1, '
            '"schema_version": "gravity-insight.ndjson-meta.v1", "status": "success", '
            '"total": 1, "truncated": false}}\n',
            cli._render_ndjson(row_result),
        )

    def test_cli_and_sdk_share_one_offline_and_execution_core(self) -> None:
        source = _source(
            [
                {
                    "Version": "1.0",
                    "userassignment_property": "control",
                    "user$pay_count": 1,
                    "user$pay_amount_sum": 4.5,
                }
            ]
        )
        client = _Client(source)
        parser = cli.build_parser()
        with patch("gravity_sdk.user_detail_aggregate_cli.runtime.build_client") as build:
            schema_args = parser.parse_args(
                ["analysis", "user-detail-aggregate", "--input-schema"]
            )
            schema = schema_args._gravity_handler(schema_args, cli._object_input)
            dry_args = parser.parse_args(
                [
                    "analysis",
                    "user-detail-aggregate",
                    "--input",
                    json.dumps(_inputs()),
                    "--dry-run",
                ]
            )
            preview = dry_args._gravity_handler(dry_args, cli._object_input)
        self.assertEqual(INPUT_SCHEMA_VERSION, schema["schema_version"])
        self.assertFalse(preview["network_called"])
        build.assert_not_called()

        live_args = parser.parse_args(
            [
                "analysis",
                "user-detail-aggregate",
                "--input",
                json.dumps(_inputs()),
                "--concurrency",
                "4",
            ]
        )
        with patch(
            "gravity_sdk.user_detail_aggregate_cli.runtime.build_client",
            return_value=client,
        ):
            cli_result = live_args._gravity_handler(live_args, cli._object_input)

        built: list[bool] = []
        sdk = GravitySDK(insight_factory=lambda: built.append(True) or _Client(source))
        sdk_preview = sdk.prepare_user_detail_aggregate(_inputs())
        self.assertEqual([], built)
        sdk_result = sdk.user_detail_aggregate(_inputs(), max_workers=4)
        self.assertEqual([True], built)
        self.assertEqual(cli_result["cells"], sdk_result["cells"])
        self.assertFalse(sdk_preview["network_called"])

    def test_plan_uses_one_worker_and_reconstructs_away_sentinel_containers(self) -> None:
        rows = [
            {
                "Version": "1.0",
                "userassignment_property": "control",
                "user$pay_count": 1,
                "user$pay_amount_sum": 4.5,
                "ClientID": SENTINEL,
                "user_id": SENTINEL,
                "device_id": SENTINEL,
            }
        ]
        native = run_user_detail_aggregate(_Client(_source(rows)), _inputs())
        native["data"] = {"list": [{"ClientID": SENTINEL}]}
        native["request"] = {"inputs": {"client_id": SENTINEL}}
        native["source"]["unexpected"] = SENTINEL
        native["pagination"]["next_page_input"] = {"cursor": SENTINEL}
        native["pagination_audit"]["unexpected"] = SENTINEL
        request = {
            "name": USER_DETAIL_AGGREGATE_NAME,
            "input_schema_version": INPUT_SCHEMA_VERSION,
            "inputs": _inputs(),
        }
        context = AdapterContext(
            node_id="aggregate",
            execution_id="aggregate",
            kind="composite",
            workspace=object(),
            output_fields=(),
            dynamic_targets=(),
            max_pages=100,
            max_items=200,
        )
        validate_user_detail_aggregate_plan(object(), object(), request, context)

        class SDK:
            insight = object()

        with patch(
            "gravity_sdk.user_detail_aggregate_product.run_user_detail_aggregate",
            return_value=native,
        ) as run:
            safe = execute_user_detail_aggregate_plan(SDK(), request, context)
        self.assertEqual(1, run.call_args.kwargs["max_workers"])
        self.assertNotIn(SENTINEL, json.dumps(safe, sort_keys=True))
        self.assertNotIn("data", safe)
        self.assertNotIn("request", safe)
        projected = project_user_detail_aggregate_result(
            safe,
            ("cells",),
            context,
        )
        self.assertIn("cells", projected)
        self.assertNotIn("query", projected)


if __name__ == "__main__":
    unittest.main()
