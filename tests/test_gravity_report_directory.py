from __future__ import annotations

import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from gravity_sdk import GravitySDK
from gravity_sdk.agent import discover_capabilities
from gravity_sdk.agent_report_directory import (
    report_directory_query,
    report_subscriptions_query,
)
from gravity_sdk.cli import main
from gravity_sdk.errors import InputValidationError
from gravity_sdk.plan import AdapterContext
from gravity_sdk.plan_report_adapter import (
    execute_report_composite,
    validate_report_composite,
)
from gravity_sdk.prober.read_semantics import assert_probe_read_semantics
from gravity_sdk.report_contracts import (
    REPORT_DETAIL,
    REPORT_LIST,
    REPORT_UPDATE,
    SUBSCRIBE_CREATE,
    SUBSCRIBE_LIST,
)
from gravity_sdk.report_mutation import (
    create_report,
    create_subscription,
    delete_report,
    marker_in_report,
)
from gravity_sdk.report_products import report_directory, report_subscriptions


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "src" / "gravity_sdk" / "contracts" / "operations"


def _list_envelope(rows):
    return {
        "ok": True,
        "status": "empty" if not rows else "success",
        "data": {"list": [dict(row) for row in rows]},
        "truncated": False,
        "next_page_input": None,
    }


class CatalogClient:
    def __init__(self) -> None:
        self.calls = []
        self.report = {
            "id": "7", "name": "测试报表", "subject": "measurement_report",
            "config": "{}", "remark": "manual", "app_id": "1",
            "project_id": "0", "create_time": "2026-08-16",
        }
        self.subscription = {
            "id": "8", "name": "测试订阅", "wildcard_name": "测试订阅",
            "report_conf_template_id": "7", "report_type": 2,
            "subscribe_status": 0, "send_way": "[]",
        }

    def read_all(self, operation_id, inputs, **options):
        self.calls.append((operation_id, dict(inputs), dict(options)))
        rows = [self.report] if operation_id == REPORT_LIST else [self.subscription]
        return _list_envelope(rows)

    def read(self, operation_id, inputs):
        self.calls.append((operation_id, dict(inputs), {}))
        return {"ok": True, "status": "success", "data": dict(self.report)}


class MutationClient:
    def __init__(self, *, report=None, principal_id="1") -> None:
        self.report = report
        self.principal_id = principal_id
        self.preview_input = None
        self.reads = 0
        self.writes = 0

    def _current_principal_id(self):
        return self.principal_id

    def _preview_mutation(self, operation_id, inputs):
        self.preview_input = dict(inputs)
        return {
            "ok": True, "status": "preview", "operation_id": operation_id,
            "effect": "mutation", "network_called": False,
        }

    def read_all(self, operation_id, inputs, **options):
        self.reads += 1
        return _list_envelope([] if self.report is None else [self.report])

    def read(self, operation_id, inputs):
        self.reads += 1
        return {"ok": True, "status": "success", "data": dict(self.report)}

    def _execute_mutation(self, operation_id, inputs):
        self.writes += 1
        if inputs.get("is_delete") == 1:
            self.report = None
        else:
            self.report = {"id": "7", "app_id": inputs["app_id"], **dict(inputs)}
        return {"ok": True, "status": "success", "operation_id": operation_id, "attempts": 1}


class GravityReportDirectoryTests(unittest.TestCase):
    def test_core_sdk_cli_and_plan_expose_complete_read_products(self):
        client = CatalogClient()
        directory = report_directory(client, max_items=2, max_workers=2)
        subscriptions = report_subscriptions(client, max_items=2)
        self.assertEqual((1, "7"), (directory["item_count"], directory["items"][0]["definition"]["id"]))
        self.assertEqual((1, "8"), (subscriptions["item_count"], subscriptions["items"][0]["id"]))
        self.assertNotIn("empty_result_note", directory)
        empty_client = MutationClient()
        empty_directory = report_directory(empty_client, max_items=2)
        empty_subscriptions = report_subscriptions(empty_client, max_items=2)
        self.assertEqual("empty", empty_directory["status"])
        self.assertIn("permission-profile", empty_directory["next_action"])
        self.assertEqual("empty", empty_subscriptions["status"])
        self.assertIn("permission-profile", empty_subscriptions["next_action"])
        self.assertEqual("gravity-insight.report-directory.v1", GravitySDK(insight=CatalogClient()).report_directory()["schema_version"])

        stdout = io.StringIO()
        with patch("gravity_sdk.report_cli.runtime.build_client", return_value=CatalogClient()), contextlib.redirect_stdout(stdout):
            self.assertEqual(0, main(["reports", "directory", "--max-items", "2"]))
        self.assertEqual("gravity-insight.report-directory.v1", json.loads(stdout.getvalue())["schema_version"])

        context = AdapterContext(
            node_id="reports", execution_id="reports", kind="composite",
            workspace=object(), output_fields=(), dynamic_targets=(),
            max_pages=5, max_items=10,
        )
        validate_report_composite({"name": "report_directory"}, context, object(), frozenset())
        sdk = type("SDK", (), {"report_directory": lambda _self, **options: options})()
        self.assertEqual(10, execute_report_composite(sdk, {"name": "report_directory"}, context)["max_items"])

    def test_report_create_delete_marker_and_subscription_preview_fail_closed(self):
        client = MutationClient()
        preview = create_report(client, app_id=1, name="SDK测试", config={}, execute=False)
        self.assertEqual((False, 0, 0), (preview["network_called"], client.reads, client.writes))

        created = create_report(client, app_id=1, name="SDK测试", config={}, execute=True)
        self.assertEqual(("created", 1, True), (created["status"], client.writes, marker_in_report(client.report)))
        deleted = delete_report(client, 7, execute=True)
        self.assertEqual(("deleted", 2, None), (deleted["status"], client.writes, client.report))

        unmarked = MutationClient(report={
            "id": "7", "name": "手建", "subject": "measurement_report",
            "report_group_id": 0, "config": "{}", "remark": "manual",
            "create_user_id": "2", "create_user_name": "owner",
        })
        with self.assertRaises(InputValidationError) as captured:
            delete_report(unmarked, 7, execute=True)
        self.assertEqual("OWNERSHIP_REQUIRED", captured.exception.code)
        self.assertEqual(0, unmarked.writes)

        owned = MutationClient(report={
            "id": "7", "name": "自建", "subject": "measurement_report",
            "report_group_id": 0, "config": "{}", "remark": "manual",
            "create_user_id": "1", "create_user_name": "me",
        })
        self.assertEqual("deleted", delete_report(owned, 7, execute=True)["status"])

        subscription = MutationClient()
        subscribe_preview = create_subscription(
            subscription, report_id=7, report_name="SDK测试",
            subscribe_time=["2026-08-16", "2026-08-16"],
            selected_columns=["activation"], execute=False,
        )
        self.assertEqual(SUBSCRIBE_CREATE, subscribe_preview["operation_id"])
        self.assertEqual((0, "[]"), (
            subscription.preview_input["subscribe_status"],
            subscription.preview_input["send_way"],
        ))

    def test_agent_separates_reads_from_explicit_writes_and_declares_bounds(self):
        directory_query = "查看报表目录和定义"
        directory = discover_capabilities(directory_query, client=None, domain="report")["candidates"][0]
        subscriptions = discover_capabilities("查看报表订阅清单", client=None, domain="report")["candidates"][0]
        mutation = discover_capabilities("创建测试报表", client=None, domain="report")["candidates"][0]
        self.assertEqual(("report_directory", "report_subscriptions"), (directory["composite"], subscriptions["composite"]))
        self.assertEqual("gravity.agent-call-bound.v1", directory["call_bound"]["schema_version"])
        self.assertEqual((False, False, 2), (
            mutation["plan_executable"], mutation["natural_language_auto_execute"],
            mutation["next"]["call_count_after_discovery"],
        ))
        self.assertEqual(
            (True, False),
            (report_directory_query(directory_query), report_subscriptions_query(directory_query)),
        )
        for query in ("我订了哪些报表？", "有哪些报表会定时发给我？", "请查看定期发送给我的报表。"):
            with self.subTest(query=query):
                result = discover_capabilities(query, client=None, domain="report")
                self.assertEqual("composite:report_subscriptions", result["candidates"][0]["selector"])
                self.assertEqual(
                    (False, True),
                    (report_directory_query(query), report_subscriptions_query(query)),
                )

    def test_new_operation_contracts_pass_exact_read_semantics_gate(self):
        for operation_id in (
            REPORT_LIST, REPORT_DETAIL, REPORT_UPDATE, SUBSCRIBE_LIST,
            SUBSCRIBE_CREATE, "report.subscribe.delete", "report.template.create",
            "report.template.update",
        ):
            with self.subTest(operation_id=operation_id):
                source = json.loads((CONTRACT_ROOT / f"{operation_id}.json").read_text(encoding="utf-8"))
                assert_probe_read_semantics(source)


if __name__ == "__main__":
    unittest.main()
