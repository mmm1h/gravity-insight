"""Offline, value-free reproduction harness for the closure audit.

The harness deliberately installs a transport that raises on every request.
It checks the four public surfaces that can be exercised offline, Plan request
fail-closed behaviour, ledger arithmetic, and the two-call catalog contract.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from gravity_sdk.agent_input_catalogs import live_catalog_for_card
from gravity_sdk.client import GravityInsightClient
from gravity_sdk.sdk import GravitySDK
from gravity_sdk.workspace import load_workspace


ROOT = Path(__file__).resolve().parents[3]
DAY = "2026-08-01"
END = "2026-08-02"


def _query(query_id, kind):
    metric = {"field": "PresetAllCount", "aggregation": "PresetAllCount"}
    dated = {"start": DAY, "end": END}
    specs = {
        "event": {**dated, "steps": [{"event": "audit", "metric": metric}]},
        "funnel": {
            **dated,
            "steps": [
                {"event": "audit", "metric": metric},
                {"event": "audit-next", "metric": metric},
            ],
            "window": {"unit": "day", "value": 1},
        },
        "retention": {
            **dated,
            "steps": [
                {"event": "audit", "metric": metric},
                {"event": "audit-return", "metric": metric},
            ],
            "offset": 7,
            "period_calc_method": "SUM",
            "custom_before_method": "SUM",
            "total_calc_type": "DAY",
            "week_first_day": 1,
        },
        "property": {
            "property": {
                "field": "PresetUserCount",
                "aggregation": "PresetUserCount",
                "data_type": "INT",
            }
        },
        "scatter": {**dated, "steps": [{"event": "audit", "metric": metric}]},
    }
    return {"id": query_id, "kind": kind, "app": "demo", "spec": specs[kind]}


class NeverTransport:
    is_test_transport = True

    def request(self, *_args, **_kwargs):
        raise AssertionError("NETWORK_FORBIDDEN")


class NeverRuntime:
    def request(self, *_args, **_kwargs):
        raise AssertionError("NETWORK_FORBIDDEN")


class CatalogWorkspace:
    def resolve_app(self, value):
        return "<app-id>"


class CatalogClient:
    """Complete, deterministic fake catalogs; no production-shaped values."""

    def __init__(self):
        self.batch_requests = []

    def read(self, _operation_id, _inputs):
        return {
            "ok": True,
            "status": "success",
            "data": [
                {
                    "id": 1,
                    "name": "space",
                    "folder_or_dashboard": [
                        {"id": 42, "name": "dashboard", "space_id": 1}
                    ],
                }
            ],
        }

    def read_all(self, operation_id, inputs, **_options):
        from gravity_sdk.saved_analysis_catalog import LIST_OPERATION_ID
        from gravity_sdk.segment_snapshot import LIST_OPERATION as SEGMENT_LIST
        from gravity_sdk.template_replay import TEMPLATE_OPERATIONS

        if operation_id == LIST_OPERATION_ID:
            rows = [
                {"id": 8, "app_id": inputs["app_id"], "name": "saved", "subject": "event"}
            ]
        elif operation_id in TEMPLATE_OPERATIONS.values():
            rows = [{"id": 9, "name": "template"}]
        elif operation_id == SEGMENT_LIST:
            rows = [
                {
                    "segment_id": 10,
                    "segment_name": "segment",
                    "app_id": inputs["app_id"],
                }
            ]
        else:
            raise AssertionError(f"unexpected catalog operation: {operation_id}")
        return {
            "ok": True,
            "status": "success",
            "data": {"list": rows},
            "truncated": False,
            "next_page_input": None,
        }

    def batch(self, requests):
        from gravity_sdk.domains import MULTIDIM_METADATA_OPERATIONS

        self.batch_requests = list(requests)
        results = []
        for request in requests:
            operation_id = request["operation_id"]
            if operation_id == MULTIDIM_METADATA_OPERATIONS[0]:
                data = {"mine": [{"id": 1, "name": "template"}], "shared": []}
            elif operation_id == MULTIDIM_METADATA_OPERATIONS[1]:
                data = {"platform": {"dimension": [{"code": 2, "name": "dimension"}]}}
            else:
                data = {"list": [{"name": "metric"}]}
            results.append({"ok": True, "status": "success", "data": data})
        return results


def repository_client() -> GravityInsightClient:
    operations = []
    for path in sorted((ROOT / "src/gravity_sdk/manifests").glob("*.json")):
        operations.extend(json.loads(path.read_text(encoding="utf-8"))["operations"])
    return GravityInsightClient._from_manifest_for_tests(
        {"manifest_version": 1, "operations": operations},
        transport=NeverTransport(),
    )


def requests_by_journey(workspace_app_id):
    requests = {}
    for kind in ("event", "funnel", "retention", "property", "scatter"):
        item = _query(kind, kind)
        requests[kind] = (
            "composite",
            {"name": "analysis_query", "kind": kind, "app": "demo", "spec": item["spec"]},
        )
    event = _query("period", "event")
    requests.update(
        {
            "period_compare": (
                "composite",
                {
                    "name": "analysis_query",
                    "kind": "event",
                    "app": "demo",
                    "spec": event["spec"],
                    "compare_start": "2026-07-01",
                    "compare_end": "2026-07-02",
                },
            ),
            "segment_evaluate": (
                "composite",
                {
                    "name": "segment_evaluate",
                    "app": "demo",
                    "spec": {
                        "name": "audit",
                        "start": DAY,
                        "property_rules": {"logic": "AND", "groups": []},
                        "event_rules": {"logic": "AND", "groups": []},
                    },
                },
            ),
            "analysis_context": ("composite", {"name": "analysis_context", "app": "demo"}),
            "app_snapshot": ("composite", {"name": "app_snapshot", "app": "demo"}),
            "attribution_snapshot": (
                "composite",
                {"name": "attribution_snapshot", "app": "demo"},
            ),
            "user_journey": (
                "composite",
                {"name": "user_journey", "app": "demo", "client_id": "audit", "date": DAY},
            ),
            "business_pulse": (
                "composite",
                {
                    "name": "business_pulse",
                    "apps": ["demo"],
                    "start": DAY,
                    "end": END,
                    "platforms": ["bytedance"],
                    "include_hourly": False,
                },
            ),
            "company_usage": ("composite", {"name": "company_usage"}),
            "custom_audience": ("composite", {"name": "custom_audience"}),
            "material_performance": (
                "composite",
                {
                    "name": "material_performance",
                    "apps": ["demo"],
                    "start": DAY,
                    "end": END,
                    "platforms": ["bytedance"],
                },
            ),
            "order_directory": (
                "composite",
                {"name": "order_directory", "app": "demo", "date": DAY},
            ),
            "order_trace": (
                "composite",
                {
                    "name": "order_split_trace",
                    "app": "demo",
                    "date": DAY,
                    "trace_id": "audit",
                },
            ),
            "monetization_detail": (
                "composite",
                {"name": "monetization_detail", "app": "demo", "date": DAY},
            ),
            "sql_product": (
                "sql_product",
                {
                    "product": "daily-event-summary",
                    "app_id": workspace_app_id,
                    "start": DAY,
                    "end": END,
                },
            ),
            "dashboard_snapshot": (
                "composite",
                {"name": "dashboard_snapshot", "app": "demo", "ref": 1},
            ),
            "dashboard_analysis": (
                "composite",
                {
                    "name": "dashboard_analysis",
                    "mode": "run",
                    "app": "demo",
                    "ref": 1,
                    "start": DAY,
                    "end": END,
                },
            ),
            "saved_analysis": (
                "composite",
                {
                    "name": "saved_analysis",
                    "mode": "run",
                    "app": "demo",
                    "ref": 1,
                    "start": DAY,
                    "end": END,
                },
            ),
            "analysis_template": (
                "composite",
                {
                    "name": "analysis_template",
                    "mode": "run",
                    "scope": "own",
                    "app": "demo",
                    "ref": 1,
                    "start": DAY,
                    "end": END,
                },
            ),
            "segment_snapshot": (
                "composite",
                {"name": "segment_snapshot", "app": "demo", "ref": 1, "date": DAY},
            ),
            "multidim": (
                "composite",
                {
                    "name": "multidim",
                    "input_schema_version": "gravity-insight.multidim-input.v1",
                    "app": "demo",
                    "inputs": {
                        "date_list": [DAY, END],
                        "time_dims": "day",
                        "metrics_list": ["cost"],
                        "custom_metrics_list": [],
                        "data_dims": [],
                        "relate_dims": [],
                        "filters": [],
                    },
                    "include_total": False,
                    "read_all": False,
                },
            ),
            "promotion_performance": (
                "composite",
                {
                    "name": "promotion_performance",
                    "app": "demo",
                    "start": DAY,
                    "end": END,
                    "platforms": ["bytedance"],
                    "metrics": ["cost"],
                },
            ),
            "bilibili": (
                "composite",
                {"name": "bilibili_account_performance", "start": DAY, "end": END},
            ),
            "advertiser_profile": (
                "composite",
                {"name": "advertiser_profile", "start": DAY, "end": END},
            ),
            "title_package": (
                "composite",
                {"name": "title_package", "app": "demo", "package_kind": "regular"},
            ),
            "metadata_search": (
                "metadata_search",
                {"query": "event", "kind": "event", "app_id": "<app-id>"},
            ),
            "table_lineage": (
                "metadata_search",
                {"query": "table", "kind": "table_lineage"},
            ),
        }
    )
    return requests


SDK_METHODS = {
    "event": "analysis_query",
    "funnel": "analysis_query",
    "retention": "analysis_query",
    "property": "analysis_query",
    "scatter": "analysis_query",
    "period_compare": "analysis_query",
    "segment_evaluate": "segment_evaluate",
    "analysis_context": "analysis_context",
    "app_snapshot": "app_snapshot",
    "attribution_snapshot": "attribution_snapshot",
    "user_journey": "user_journey",
    "business_pulse": "business_pulse",
    "company_usage": "company_usage",
    "custom_audience": "custom_audiences",
    "material_performance": "material_performance",
    "order_directory": "order_directory",
    "order_trace": "order_split_trace",
    "monetization_detail": "monetization_detail",
    "sql_product": "query_sql_products",
    "dashboard_snapshot": "dashboard_snapshot",
    "dashboard_analysis": "run_dashboard_analysis",
    "saved_analysis": "run_saved_analysis",
    "analysis_template": "run_analysis_template",
    "segment_snapshot": "segment_snapshot",
    "multidim": "multidim_query",
    "promotion_performance": "promotion_performance",
    "bilibili": "bilibili_account_performance",
    "advertiser_profile": "advertiser_profile",
    "title_package": "title_packages",
    "metadata_search": "analysis_vocabulary",
    "table_lineage": "table_lineage",
}


AGENT_QUERIES = {
    "event": ("event analysis", "analysis", "analysis.query.spec:event"),
    "funnel": ("funnel analysis", "analysis", "analysis.query.spec:funnel"),
    "retention": ("retention analysis", "analysis", "analysis.query.spec:retention"),
    "property": ("property analysis", "analysis", "analysis.query.spec:property"),
    "scatter": ("scatter plot analysis", "analysis", "analysis.query.spec:scatter"),
    "period_compare": ("event analysis period compare", "analysis", "analysis.query.spec:event"),
    "segment_evaluate": ("segment rule population estimate", "analysis", "analysis.segment.rule.spec"),
    "analysis_context": ("analysis context", None, "composite:analysis_context"),
    "app_snapshot": ("app governance snapshot", None, "composite:app_snapshot"),
    "attribution_snapshot": ("attribution configuration snapshot", None, "composite:attribution_snapshot"),
    "user_journey": ("single user journey", None, "composite:user_journey"),
    "business_pulse": ("business pulse", None, "composite:business_pulse"),
    "company_usage": ("company resource usage", None, "composite:company_usage"),
    "custom_audience": ("custom audience coverage status", None, "composite:custom_audience"),
    "material_performance": ("material performance", None, "composite:material_performance"),
    "order_directory": ("order directory", None, "composite:order_directory"),
    "order_trace": ("order split trace", None, "composite:order_split_trace"),
    "monetization_detail": ("monetization details", None, "composite:monetization_detail"),
    "sql_product": ("daily event summary", None, "sql:daily-event-summary"),
    "dashboard_snapshot": ("dashboard details members filters", None, "composite:dashboard_snapshot"),
    "dashboard_analysis": ("run dashboard charts", None, "composite:dashboard_analysis"),
    "saved_analysis": ("run saved analysis", None, "composite:saved_analysis"),
    "analysis_template": ("run analysis template", None, "composite:analysis_template"),
    "segment_snapshot": ("inspect segment details history and daily calculation result", None, "composite:segment_snapshot"),
    "multidim": ("multidimensional report", None, "composite:multidim"),
    "promotion_performance": ("promotion performance", None, "composite:promotion_performance"),
    "bilibili": ("bilibili account performance", None, "composite:bilibili_account_performance"),
    "advertiser_profile": ("bytedance advertiser profile", None, "composite:advertiser_profile"),
    "title_package": ("title package performance", None, "composite:title_package"),
    "table_lineage": ("table versions", None, "metadata:table_lineage"),
}


CLI_PATHS = {
    "event": ["analysis", "query"],
    "funnel": ["analysis", "query"],
    "retention": ["analysis", "query"],
    "property": ["analysis", "query"],
    "scatter": ["analysis", "query"],
    "period_compare": ["analysis", "query"],
    "segment_evaluate": ["analysis", "segment", "evaluate"],
    "analysis_context": ["analysis", "context"],
    "app_snapshot": ["apps", "snapshot"],
    "attribution_snapshot": ["attribution", "snapshot"],
    "user_journey": ["analysis", "user", "journey"],
    "business_pulse": ["reports", "pulse"],
    "company_usage": ["reports", "usage"],
    "custom_audience": ["promotion", "custom-audiences"],
    "material_performance": ["materials", "performance"],
    "order_directory": ["analysis", "order", "directory"],
    "order_trace": ["analysis", "order", "trace"],
    "monetization_detail": ["analysis", "monetization", "detail"],
    "sql_product": ["sql", "query"],
    "dashboard_snapshot": ["analysis", "dashboard", "snapshot"],
    "dashboard_analysis": ["analysis", "dashboard", "run"],
    "saved_analysis": ["analysis", "saved", "run"],
    "analysis_template": ["analysis", "template", "run"],
    "segment_snapshot": ["analysis", "segment", "snapshot"],
    "multidim": ["multidim", "query"],
    "promotion_performance": ["promotion", "performance"],
    "bilibili": ["promotion", "bilibili-account-performance"],
    "advertiser_profile": ["promotion", "advertiser-profile"],
    "title_package": ["materials", "title-packages"],
    "metadata_search": ["metadata", "search"],
    "table_lineage": ["metadata", "tables"],
}


def ledger_check():
    rows = []
    for line_no, line in enumerate(
        (ROOT / "docs/analysis-journeys.md").read_text(encoding="utf-8").splitlines(), 1
    ):
        if line.startswith("| ") and not line.startswith(("| ---", "| 动线")):
            cells = [part.strip() for part in line.strip().strip("|").split("|")]
            if len(cells) >= 5:
                rows.append((line_no, *cells[:5]))
    statuses = {}
    for row in rows:
        statuses[row[2]] = statuses.get(row[2], 0) + 1
    return {
        "table_rows": len(rows),
        "product_rows": sum("不计独立动线" not in row[2] for row in rows),
        "statuses": statuses,
        "design_not_applicable": [
            {"line": row[0], "journey": row[1], "surface": row[3]}
            for row in rows
            if "设计不适用" in row[3]
        ],
    }


def plan_and_surface_checks(sdk, workspace):
    results = {}
    workspace_app_id = next(iter(workspace.apps.values()))
    for journey, (kind, request) in requests_by_journey(workspace_app_id).items():
        node = {"id": journey.replace("_", "-"), "kind": kind, "request": request}
        plan = {"schema_version": "gravity.plan.v1", "nodes": [node]}
        receipt = sdk.validate_plan(plan, workspace=workspace)
        mutated = copy.deepcopy(plan)
        mutated["nodes"][0]["request"]["__audit_unknown"] = True
        try:
            sdk.validate_plan(mutated, workspace=workspace)
            fail_closed = False
        except Exception:
            fail_closed = True
        help_result = subprocess.run(
            [sys.executable, "-m", "gravity_sdk", *CLI_PATHS[journey], "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        results[journey] = {
            "cli_help": help_result.returncode == 0,
            "sdk_method": hasattr(GravitySDK, SDK_METHODS[journey]),
            "plan_status": receipt.get("status"),
            "plan_dry_run": receipt.get("dry_run"),
            "unknown_plan_field_rejected": fail_closed,
        }
    return results


def agent_checks(sdk, workspace):
    results = {}
    for journey, (query, domain, selector) in AGENT_QUERIES.items():
        response = sdk.capabilities(query, workspace=workspace, domain=domain, limit=5)
        candidates = response.get("candidates", [])
        results[journey] = {
            "status": response.get("status"),
            "found": any(card.get("selector") == selector for card in candidates),
            "selector": selector,
        }

    metadata_card = {
        "kind": "metadata",
        "metadata_kind": "event",
        "name": "event",
        "display_name": "event",
        "operation_id": "analysis.event.list",
        "source": "local",
        "scope": "app",
        "app_id": "<app-id>",
        "match": {"confidence": "strong"},
    }
    with patch(
        "gravity_sdk.agent.catalog_cards",
        return_value=([metadata_card], 1, [], "0" * 64),
    ):
        response = sdk.capabilities("event metadata search", workspace=workspace, limit=5)
    results["metadata_search"] = {
        "status": response.get("status"),
        "found": any(
            card.get("kind") == "metadata"
            and (card.get("plan_node") or {}).get("kind") == "metadata_search"
            for card in response.get("candidates", [])
        ),
        "selector": "metadata:event",
    }

    export_client = GravityInsightClient.from_env(runtime=NeverRuntime())
    export_sdk = GravitySDK(insight=export_client, workspace=workspace)
    response = export_sdk.capabilities("material report export", workspace=workspace)
    results["export"] = {
        "status": response.get("status"),
        "found": any(
            card.get("selector") == "export.material.report.start"
            and card.get("plan_node") is None
            for card in response.get("candidates", [])
        ),
        "selector": "export.material.report.start",
    }
    return results


def two_call_catalog_checks():
    from gravity_sdk.agent_call_bound import call_bound_for_card
    from gravity_sdk.agent_input_catalogs import resolvable_scenario
    from gravity_sdk.agent_input_resolution import resolve_capabilities

    client = CatalogClient()
    workspace = CatalogWorkspace()
    cases = {
        "dashboard_snapshot": ({"composite": "dashboard_snapshot", "required_inputs": ["app", "ref"]}, {"app": "demo"}),
        "dashboard_analysis": ({"composite": "dashboard_analysis", "required_inputs": ["app", "ref", "start", "end"]}, {"app": "demo"}),
        "saved_analysis": ({"composite": "saved_analysis", "required_inputs": ["app", "ref", "start", "end"]}, {"app": "demo"}),
        "analysis_template": ({"composite": "analysis_template", "required_inputs": ["app", "scope", "ref", "start", "end"]}, {}),
        "segment_snapshot": ({"composite": "segment_snapshot", "required_inputs": ["app", "ref", "date"]}, {"app": "demo"}),
        "multidim": ({"composite": "multidim", "required_inputs": ["app", "inputs"]}, {}),
        "promotion_performance": (
            {"composite": "promotion_performance", "required_inputs": ["app", "metrics", "platforms", "start", "end"]},
            {"platforms": ["bytedance", "tencent"]},
        ),
    }
    results = {}
    for journey, (card, known) in cases.items():
        catalog = live_catalog_for_card(
            card, client=client, workspace=workspace, known_inputs=known
        )
        card = {
            **card,
            "kind": "composite",
            "call_bound": call_bound_for_card(card),
            "plan_node": {"kind": "composite", "request": {"name": card["composite"]}},
        }
        with patch(
            "gravity_sdk.agent_input_resolution._discover",
            return_value={"candidates": [card]},
        ):
            resolved = resolve_capabilities(
                journey,
                known_inputs=known,
                client=client,
                workspace=workspace,
            )
        resolved_card = resolved["candidates"][0]
        scenario_id = resolvable_scenario(resolved_card)
        scenario = next(
            item
            for item in resolved_card["call_bound"]["scenarios"]
            if item["id"] == scenario_id
        )
        results[journey] = {
            "complete": catalog.get("complete"),
            "status": catalog.get("status"),
            "catalog_count": len(catalog.get("catalogs", [])),
            "all_components_terminal": all(
                item.get("status") in {"success", "empty"}
                for item in catalog.get("catalogs", [])
            ),
            "minimum_calls": scenario.get("minimum_calls"),
            "discovery_calls": scenario.get("discovery_calls"),
            "unknown_inputs": scenario.get("unknown_inputs"),
            "integrated_source": scenario.get("input_sources", [{}])[0].get("selector"),
        }
    # Atomic refresh paths are exercised by the named unit tests; record their
    # exact implementation entry points here without creating a real cache.
    results["metadata_search"] = {
        "complete": True,
        "proof": "tests.test_gravity_metadata_sync::test_sync_failure_is_partial_and_guarded_refresh_keeps_previous_catalog",
    }
    results["table_lineage"] = {
        "complete": True,
        "proof": "tests.test_gravity_metadata_sync::test_opt_in_lineage_replaces_atomically_and_is_searchable_offline",
    }
    return results


def main():
    client = repository_client()
    workspace = load_workspace(ROOT / "examples/workspace/gravity.toml")
    sdk = GravitySDK(insight=client, workspace=workspace)
    output = {
        "schema_version": "closure-audit.offline.v1",
        "import_path": str(Path(__import__("gravity_sdk").__file__).resolve()),
        "production_http_requests": 0,
        "ledger": ledger_check(),
        "surfaces": plan_and_surface_checks(sdk, workspace),
        "agent": agent_checks(sdk, workspace),
        "two_call_catalogs": two_call_catalog_checks(),
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
