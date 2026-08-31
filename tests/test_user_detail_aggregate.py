from __future__ import annotations

import copy
import contextlib
import io
import json
import logging
import unittest
from collections.abc import Mapping
from dataclasses import replace
from unittest.mock import patch

from gravity_insight import GravitySDK, cli
from gravity_insight.errors import error_detail_from_exception, error_envelope
from gravity_insight.pagination_completeness import (
    STABLE_PRODUCT_SURFACES,
    SURFACE_PARITY_OUTCOMES,
    stable_product_surface_matrix,
    surface_contract,
    surface_parity_sample,
    validate_surface_pair,
    validate_surface_registry,
)
from gravity_insight.plan import PlanAdapter, PlanAdapters, execute_plan
from gravity_insight.plan_adapters import build_plan_adapters
from gravity_insight.user_detail_aggregate_contract import (
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
from gravity_insight.user_detail_aggregate_product import run_user_detail_aggregate


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
        with patch("gravity_insight.user_detail_aggregate_cli.runtime.build_client") as build:
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
            "gravity_insight.user_detail_aggregate_cli.runtime.build_client",
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


class _PlanInsight(_Client):
    def operations(self, **_options):
        return []


class _PlanSDK:
    def __init__(self, source):
        self.insight = _PlanInsight(source)
        self.workspace = object()


def _aggregate_plan(inputs):
    return {
        "schema_version": "gravity.plan.v1",
        "budget": {"max_workers": 4, "max_total_items": 2_000},
        "nodes": [{
            "id": "aggregate",
            "kind": "composite",
            "request": {
                "name": "user_detail_aggregate",
                "input_schema_version": INPUT_SCHEMA_VERSION,
                "inputs": inputs,
            },
            "limits": {"max_pages": 200, "max_items": 200},
        }],
    }


class SurfaceParityHarnessTests(unittest.TestCase):
    def test_registry_generates_one_parameterized_product_outcome_matrix(self) -> None:
        matrix = stable_product_surface_matrix()
        self.assertEqual(len(STABLE_PRODUCT_SURFACES), len(matrix))
        self.assertEqual(len(matrix), len({item["name"] for item in matrix}))
        for contract in STABLE_PRODUCT_SURFACES:
            for outcome in SURFACE_PARITY_OUTCOMES:
                with self.subTest(product=contract.name, outcome=outcome):
                    direct, plan = surface_parity_sample(contract, outcome)
                    validate_surface_pair(contract, direct, plan)
        validate_surface_registry()

    def test_six_dimensions_each_reject_an_injected_direct_plan_drift(self) -> None:
        base = surface_contract("user_detail_aggregate")
        assert base is not None
        direct, plan = surface_parity_sample(base, "partial")
        mutations = {
            "input contract": lambda contract, value: (
                replace(contract, plan=replace(
                    contract.plan, input_contract="changed-input.v2"
                )),
                value,
            ),
            "result schema": lambda contract, value: (
                contract, {**value, "schema_version": "changed-result.v2"}
            ),
            "completeness": lambda contract, value: (
                contract,
                {**value, "pagination": {
                    **value["pagination"], "completeness": "prefix"
                }},
            ),
            "allowed claims": lambda contract, value: (
                contract,
                {**value, "pagination": {
                    **value["pagination"],
                    "claims": {
                        **value["pagination"]["claims"],
                        "allowed": ["returned_items", "complete_collection"],
                    },
                }},
            ),
            "privacy": lambda contract, value: (
                replace(contract, plan=replace(contract.plan, privacy="raw-user-rows")),
                value,
            ),
            "error taxonomy": lambda contract, value: (
                contract,
                {**value, "error": {**value["error"], "category": "local"}},
            ),
        }
        for dimension, mutate in mutations.items():
            contract, changed = mutate(base, copy.deepcopy(plan))
            with self.subTest(dimension=dimension), self.assertRaisesRegex(
                RuntimeError, dimension
            ):
                validate_surface_pair(contract, direct, changed)

    def test_user_detail_success_and_empty_preserve_full_direct_evidence(self) -> None:
        contract = surface_contract("user_detail_aggregate")
        assert contract is not None
        cases = (
            ("success", "unknown", [{
                "Version": "1.0",
                "userassignment_property": "control",
                "user$pay_count": 1,
                "user$pay_amount_sum": 4.5,
                "ClientID": SENTINEL,
            }]),
            ("empty", "complete", []),
        )
        for expected_status, completeness, rows in cases:
            with self.subTest(status=expected_status):
                source = _source(rows, completeness=completeness)
                direct = run_user_detail_aggregate(
                    _PlanInsight(source), _inputs(), max_workers=4
                )
                sdk = _PlanSDK(source)
                dry_run = execute_plan(
                    _aggregate_plan(_inputs()),
                    adapters=build_plan_adapters(sdk),
                    workspace=sdk.workspace,
                    dry_run=True,
                )
                plan = execute_plan(
                    _aggregate_plan(_inputs()),
                    adapters=build_plan_adapters(sdk),
                    workspace=sdk.workspace,
                )
                product = plan["results"][0]["result"]
                self.assertEqual(("validated", 0), (dry_run["status"], dry_run["exit_code"]))
                self.assertEqual((True, expected_status), (plan["ok"], product["status"]))
                validate_surface_pair(contract, direct, product)
                for field in ("pagination", "pagination_audit", "source", "result_audit"):
                    self.assertEqual(direct[field], product[field], field)
                self.assertNotIn(SENTINEL, repr(product))
                self.assertTrue(all(
                    call[2]["max_workers"] == 1 for call in sdk.insight.calls
                ))
                if expected_status == "success":
                    tampered = copy.deepcopy(direct)
                    tampered["data"] = {"list": [{"ClientID": SENTINEL}]}
                    tampered["request"] = {"inputs": {"client_id": SENTINEL}}
                    tampered["source"]["unexpected"] = SENTINEL
                    tampered["pagination"]["next_page_input"] = {"cursor": SENTINEL}
                    tampered["pagination_audit"]["unexpected"] = SENTINEL
                    projected_plan = _aggregate_plan(_inputs())
                    projected_plan["nodes"][0]["output_fields"] = ["cells"]
                    with patch(
                        "gravity_insight.user_detail_aggregate_product.run_user_detail_aggregate",
                        return_value=tampered,
                    ) as run:
                        projected = execute_plan(
                            projected_plan,
                            adapters=build_plan_adapters(sdk),
                            workspace=sdk.workspace,
                        )["results"][0]["result"]
                    self.assertEqual(1, run.call_args.kwargs["max_workers"])
                    self.assertIn("cells", projected)
                    self.assertNotIn("query", projected)
                    self.assertNotIn(SENTINEL, repr(projected))

    def test_user_detail_error_taxonomy_matches_and_is_not_retried(self) -> None:
        inputs = _inputs()
        inputs["group_by"] = ["ClientID"]
        with self.assertRaises(Exception) as raised:
            run_user_detail_aggregate(_PlanInsight(_source([])), inputs)
        direct_error = error_detail_from_exception(raised.exception)
        sdk = _PlanSDK(_source([]))
        result = execute_plan(
            _aggregate_plan(inputs),
            adapters=build_plan_adapters(sdk),
            workspace=sdk.workspace,
        )
        plan_error = result["results"][0]["error"]
        self.assertEqual(
            (direct_error.code, direct_error.category, direct_error.retryable),
            (plan_error["code"], plan_error["category"], plan_error["retryable"]),
        )
        self.assertFalse(plan_error["retryable"])
        self.assertEqual(1, len(sdk.insight.calls))

    def test_result_envelope_type_error_keeps_safe_contract_classification(self) -> None:
        calls = []
        adapter = PlanAdapter(
            execute=lambda request, context: calls.append(context.node_id)
            or {"schema_version": "fixture.v1", "ok": True, "status": "success"},
            validate=lambda request, context: None,
        )
        with patch(
            "gravity_insight.plan_execution.aggregate_completeness",
            side_effect=[TypeError("private"), "unknown", "unknown"],
        ):
            result = execute_plan(
                {
                    "schema_version": "gravity.plan.v1",
                    "nodes": [{"id": "fixture", "kind": "run", "request": {}}],
                },
                adapters=PlanAdapters(run=adapter),
                workspace=object(),
            )
        error = result["results"][0]["error"]
        self.assertEqual(["fixture"], calls)
        self.assertEqual(
            (
                "PLAN_ADAPTER_CONTRACT_INCOMPATIBLE",
                "local",
                "result_envelope",
                "type_error",
                False,
            ),
            (
                error["code"], error["category"], error["stage"],
                error["cause"], error["retryable"],
            ),
        )


if __name__ == "__main__":
    unittest.main()
