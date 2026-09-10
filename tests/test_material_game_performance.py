from __future__ import annotations

import copy
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from gravity_insight import GravitySDK, cli
from gravity_insight.contracts import join_key
from gravity_insight.errors import InputValidationError
from gravity_insight.material_game_contract import prepare_material_game_performance
from gravity_insight.material_game_performance import material_game_performance
from gravity_insight.material_performance_result import MATERIAL_REPORT_OPERATION
from gravity_insight.user_detail_aggregate_contract import SOURCE_OPERATION_ID


def source(operation, rows, *, total=1, pages=1, completeness="unknown", more=False):
    return {
        "operation_id": operation,
        "ok": True,
        "status": "success" if rows else "empty",
        "data": {"list": rows},
        "completeness": completeness,
        "page": {"pages_fetched": pages, "item_count": len(rows), "total_pages": total, "has_more": more},
        "next_page_input": {"page": pages + 1} if more else None,
    }


def report(material_id="901", subtype="video", created="2026-09-01 10:00:00"):
    return {
        "material_id": material_id,
        "file_type": subtype,
        "create_time": created,
        "stat_cost": 42,
        "ctr": "2.1%",
        "designer_name": "PRIVATE-PERSON",
    }


class Client:
    def __init__(self, reports=None, daily=None):
        self.calls = []
        self.reports = source(
            MATERIAL_REPORT_OPERATION, reports if reports is not None else [report()], completeness="complete"
        )
        self.daily = daily or {}

    def schema(self, operation):
        return {
            "response_projection": {
                "item_keys": [
                    "CreateTime",
                    "bytedanceMid1",
                    "bytedanceMid3",
                    "Version",
                    "user$pay_count",
                    "usertotal_session_time",
                ],
                "nested_item_keys": {},
            }
        }

    def read_all(self, *args, **kwargs):
        raise AssertionError("no metadata/read_all request in this product")

    def read_limited(self, operation, inputs, **bounds):
        self.calls.append((operation, copy.deepcopy(inputs), bounds))
        if operation == MATERIAL_REPORT_OPERATION:
            return copy.deepcopy(self.reports)
        assert operation == SOURCE_OPERATION_ID
        return copy.deepcopy(self.daily.get(inputs["date"], source(SOURCE_OPERATION_ID, [])))


def user(day, **values):
    return {"CreateTime": day + " 12:00:00", "bytedanceMid3": "901", "ClientID": "PRIVATE-USER", **values}


class MaterialGamePerformanceTests(unittest.TestCase):
    def test_three_platform_mappings_and_bytedance_subtype_reuse(self):
        for platform, subtype, field in (
            ("bytedance", "image", "bytedanceMid1"),
            ("bytedance", "video", "bytedanceMid3"),
            ("kuaishou", "other", "bytedanceMid3"),
            ("tencent", "other", "bytedanceMid3"),
        ):
            with self.subTest(platform=platform, subtype=subtype):
                client = Client([report(subtype=subtype)])
                with patch(
                    "gravity_insight.material_game_performance.resolve_proven_join_key",
                    wraps=join_key.resolve_proven_join_key,
                ) as resolve:
                    result = material_game_performance(
                        client, "101", ["901"], platform, start="2026-09-01", end="2026-09-01"
                    )
                self.assertGreaterEqual(resolve.call_count, 1)
                self.assertEqual(result["materials"][0]["join_key"]["right"]["path"], "data.list[]." + field)

    def test_nonproven_namespaces_fail_closed_without_fallback_or_network(self):
        for state in ("disproven", "insufficient_evidence"):
            registry = join_key.join_key_registry()
            for mapping in registry["mappings"]:
                if mapping["platform"] == "kuaishou" and mapping["object_type"] == "material":
                    mapping["namespace_status"] = state
            client = Client()
            with patch.object(join_key, "_registry", return_value=registry):
                result = material_game_performance(client, "101", ["901"], "kuaishou")
            self.assertEqual(result["materials"][0]["join_key"]["namespace_states"], [state])
            self.assertEqual(client.calls, [])
        client = Client()
        result = material_game_performance(client, "101", ["901"], "bytedance", object_type="creative")
        self.assertEqual(result["materials"][0]["join_key"]["namespace_states"], ["insufficient_evidence"])
        self.assertEqual(client.calls, [])

    def test_multi_day_counts_share_reads_and_preserve_unknown_completeness(self):
        client = Client(
            [report(), report("902")],
            {
                "2026-09-01": source(
                    SOURCE_OPERATION_ID, [user("2026-09-01"), user("2026-09-01", bytedanceMid3="902")]
                ),
                "2026-09-02": source(SOURCE_OPERATION_ID, [user("2026-09-02"), user("2026-09-02")]),
            },
        )
        result = material_game_performance(
            client, "101", ["901", "902"], "bytedance", start="2026-09-01", end="2026-09-02"
        )
        self.assertEqual(
            [m["matched_users"]["candidate_observations"]["observed_value"] for m in result["materials"]],
            [3, 1],
        )
        self.assertIsNone(result["materials"][0]["matched_users"]["value"])
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(client.calls[-1][2]["max_pages"], 999)
        serialized = json.dumps(result)
        self.assertNotIn("PRIVATE-USER", serialized)
        self.assertNotIn("PRIVATE-PERSON", serialized)
        self.assertNotIn('"cells"', serialized)

    def test_cross_platform_id_collision_never_becomes_a_matched_user_total(self):
        client = Client(
            daily={
                "2026-09-01": source(
                    SOURCE_OPERATION_ID,
                    [
                        user("2026-09-01", AdPlatform="synthetic-platform-a"),
                        user("2026-09-01", AdPlatform="synthetic-platform-b"),
                    ],
                    completeness="complete",
                )
            }
        )
        result = material_game_performance(
            client, "101", ["901"], "bytedance", start="2026-09-01", end="2026-09-01"
        )
        count = result["materials"][0]["matched_users"]
        self.assertEqual(count["status"], "unavailable")
        self.assertEqual(count["reason"], "USER_PLATFORM_SCOPE_UNPROVEN")
        self.assertIsNone(count["value"])
        self.assertNotIn("observed_value", count)
        self.assertEqual(count["candidate_observations"]["observed_value"], 2)
        self.assertEqual(count["candidate_observations"]["status"], "diagnostic_only")
        self.assertIn("platform_scoped_user_counts_or_game_metrics", result["claims"]["forbidden"])

    def test_empty_observation_does_not_claim_zero_attributed_users(self):
        result = material_game_performance(Client(), "101", ["901"], "bytedance",
                                          start="2026-09-01", end="2026-09-01")
        count = result["materials"][0]["matched_users"]
        self.assertEqual((count["status"], count["value"]), ("unavailable", None))
        self.assertEqual(count["candidate_observations"]["observed_value"], 0)

    def test_partial_day_retains_position_and_never_zero_fills_dates(self):
        client = Client(
            daily={
                "2026-09-01": source(
                    SOURCE_OPERATION_ID, [user("2026-09-01")], total=4, completeness="prefix", more=True
                )
            }
        )
        result = material_game_performance(
            client, "101", ["901"], "bytedance", start="2026-09-01", end="2026-09-03", max_user_pages=1
        )
        self.assertEqual(result["budget"]["remaining_days"], 2)
        self.assertEqual(
            (
                result["budget"]["incomplete_date"],
                result["budget"]["next_page"],
                result["budget"]["remaining_pages"],
            ),
            ("2026-09-01", 2, 3),
        )
        count = result["materials"][0]["matched_users"]
        self.assertEqual(count["candidate_observations"]["observed_value"], 1)
        self.assertIsNone(count["value"])
        self.assertEqual(len(client.calls), 2)

    def test_global_item_and_day_bounds_and_unknown_remaining_pages(self):
        client = Client(daily={"2026-09-01": source(SOURCE_OPERATION_ID, [user("2026-09-01")])})
        result = material_game_performance(
            client, "101", ["901"], "bytedance", start="2026-09-01", end="2026-09-03", max_user_items=1
        )
        self.assertEqual(result["budget"]["stopped_reason"], "USER_SCAN_BUDGET_EXHAUSTED")
        self.assertEqual(result["budget"]["remaining_days"], 2)
        client.daily["2026-09-01"] = source(SOURCE_OPERATION_ID, [], total=None, more=None)
        result = material_game_performance(
            client, "101", ["901"], "bytedance", start="2026-09-01", end="2026-09-03"
        )
        self.assertIsNone(result["days"][0]["scan"]["remaining_pages"])
        self.assertEqual(result["budget"]["remaining_days"], 2)

    def test_auto_window_is_candidate_extends_backwards_and_override_is_exact(self):
        client = Client([report(created="2026-08-01 10:00:00")])
        result = material_game_performance(
            client, "101", ["901"], "bytedance", as_of="2026-09-02", lookback_days=2, max_days=1
        )
        window = result["materials"][0]["window"]
        self.assertEqual(window["start"], "2026-08-01")
        self.assertFalse(window["delivery_bounds_proven"])
        self.assertEqual(result["budget"]["stopped_reason"], "DAY_BUDGET_EXHAUSTED")
        self.assertEqual(client.calls[0][1]["date_list"], ["2026-09-01", "2026-09-02"])
        explicit = material_game_performance(
            Client(), "101", ["901"], "bytedance", start="2026-09-02", end="2026-09-02"
        )
        self.assertEqual(explicit["materials"][0]["window"]["mode"], "explicit")

    def test_missing_material_and_duplicate_report_are_not_totals(self):
        client = Client([])
        client.reports.update(completeness="prefix", next_page_input={"page": 2})
        client.reports["page"].update(has_more=True, total_pages=2)
        result = material_game_performance(client, "101", ["901"], "bytedance")
        self.assertEqual(
            result["materials"][0]["advertising"]["reason"], "MATERIAL_NOT_FOUND_IN_SCANNED_PREFIX"
        )
        self.assertEqual(len(client.calls), 1)
        duplicate = material_game_performance(
            Client([report(), report()]), "101", ["901"], "bytedance", start="2026-09-01", end="2026-09-01"
        )
        self.assertEqual(duplicate["materials"][0]["advertising"]["reason"], "MATERIAL_REPORT_DUPLICATE_ROWS")

    def test_input_and_offline_type_disclosure(self):
        client = Client()
        with self.assertRaises(InputValidationError):
            material_game_performance(client, "101", ["901"], "bytedance", start="2026-09-01")
        with self.assertRaises(InputValidationError):
            material_game_performance(client, "101", [str(n) for n in range(1, 22)], "bytedance")
        self.assertEqual(client.calls, [])
        preview = prepare_material_game_performance("101", ["901"], "bytedance")
        self.assertFalse(preview["network_called"])
        self.assertEqual(preview["metric_preflight"]["level"]["status"], "binding_required")

    def test_lexical_or_null_ordered_thresholds_are_rejected_before_network(self):
        client = Client()
        for value in ("5", None, True):
            with self.subTest(value=value), self.assertRaises(InputValidationError):
                material_game_performance(
                    client,
                    "101",
                    ["901"],
                    "bytedance",
                    metrics={
                        "level": {
                            "op": "count_if",
                            "condition": {
                                "field": "Version",
                                "operator": "GTE",
                                "values": [value],
                            },
                        },
                    },
                )
        self.assertEqual(client.calls, [])

    def test_cli_dry_run_does_not_build_client(self):
        output = io.StringIO()
        with (
            patch("gravity_insight.material_cli.runtime.build_client") as build,
            contextlib.redirect_stdout(output),
        ):
            code = cli.main(
                [
                    "materials",
                    "game-performance",
                    "--app",
                    "101",
                    "--platform",
                    "bytedance",
                    "--material-id",
                    "901",
                    "--dry-run",
                ]
            )
        self.assertEqual(code, 0, output.getvalue())
        build.assert_not_called()
        self.assertFalse(json.loads(output.getvalue())["network_called"])

    def test_typed_cli_ids_reach_the_execution_owner(self):
        output = io.StringIO()
        with (
            patch("gravity_insight.material_cli.runtime.build_client", return_value=Client()),
            patch(
                "gravity_insight.material_game_performance.material_game_performance",
                return_value={"ok": True},
            ) as run,
            contextlib.redirect_stdout(output),
        ):
            cli.main(
                [
                    "materials",
                    "game-performance",
                    "--app",
                    "101",
                    "--platform",
                    "bytedance",
                    "--material-ids-json",
                    "[901]",
                ]
            )
        self.assertEqual(run.call_args.args[2], [901])
        mismatch = material_game_performance(Client([report(901)]), "101", ["901"], "bytedance")
        self.assertEqual(mismatch["materials"][0]["advertising"]["reason"], "MATERIAL_ID_TYPE_MISMATCH")

    def test_result_binds_scope_and_executed_metric_without_string_values(self):
        client = Client(
            daily={
                "2026-09-01": source(
                    SOURCE_OPERATION_ID,
                    [user("2026-09-01", Version="PRIVATE-CONDITION", **{"user$pay_count": 2})],
                )
            }
        )
        metrics = {
            "payment": {
                "op": "count_if",
                "condition": {"field": "user$pay_count", "operator": "GT", "values": [0]},
            },
            "level": {
                "op": "count_if",
                "condition": {"field": "Version", "operator": "EQUALS", "values": ["PRIVATE-CONDITION"]},
            },
        }
        result = material_game_performance(
            client, "101", ["901"], "bytedance", start="2026-09-01", end="2026-09-01", metrics=metrics
        )
        self.assertEqual(result["scope"]["app_id"], "101")
        self.assertEqual(
            result["materials"][0]["metrics"]["payment"]["candidate_observations"]["definition"],
            {"name": "payment", **metrics["payment"]},
        )
        self.assertEqual(len(result["metric_binding_digests"]["level"]), 64)
        self.assertNotIn("PRIVATE-CONDITION", json.dumps(result))
        self.assertTrue(
            result["materials"][0]["metrics"]["level"]["candidate_observations"]["definition"]["condition"][
                "values_redacted"
            ]
        )

    def test_sdk_and_direct_agent_handoff(self):
        sdk = GravitySDK(insight=Client(), workspace=object())
        with (
            patch.object(sdk, "_resolve_app", return_value="101"),
            patch(
                "gravity_insight.material_game_performance.material_game_performance",
                return_value={"result": "delegated"},
            ) as run,
        ):
            self.assertEqual(
                sdk.material_game_performance("main", ["901"], "bytedance"), {"result": "delegated"}
            )
        self.assertEqual(run.call_args.args[1:4], ("101", ["901"], "bytedance"))
        from gravity_insight.agents.material_performance import material_game_capability_cards
        from gravity_insight.agents.handoff import attach_plan_node

        card = material_game_capability_cards("material.game_performance", domain=None, platform=None)[0]
        handoff = attach_plan_node(card, "material.game_performance")
        self.assertIsNone(handoff["plan_node"])
        self.assertEqual(handoff["next"]["argv"][1:3], ["materials", "game-performance"])
        from gravity_insight.agents.handoff import apply_workspace_prefix

        bound = apply_workspace_prefix(handoff, "other-workspace.json")
        self.assertEqual(bound["next"]["argv"][:3], ["gravity", "--workspace", "other-workspace.json"])
