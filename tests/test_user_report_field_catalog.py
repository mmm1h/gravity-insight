from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator

from gravity_insight import GravitySDK, InputValidationError, PlanValidationError, cli
from gravity_insight._field_policy_detail import validate_analysis_detail
from gravity_insight._field_policy_operations import (
    ANALYSIS_EVENT_PROPERTY,
    ANALYSIS_SEGMENT,
    ANALYSIS_USER_PROPERTY,
)
from gravity_insight.find import metadata_capability_cards
from gravity_insight.find_metadata import search_metadata
from gravity_insight.metadata_sync import _create_schema
from gravity_insight.models import load_operation_manifest
from gravity_insight.user_report_fields import (
    CATALOG_ID,
    CATALOG_VERSION,
    GROUPS,
    SCHEMA_VERSION,
    catalog_document,
    catalog_metadata,
    catalog_rows,
)


ROOT = Path(__file__).resolve().parents[1]


def _user_detail_operation():
    operations = load_operation_manifest(
        ROOT / "src" / "gravity_insight" / "manifests" / "analysis.json"
    )
    return next(
        item for item in operations if item.operation_id == "analysis.user_detail.list"
    )


class UserReportFieldCatalogTests(unittest.TestCase):
    def test_catalog_is_versioned_valid_and_matches_reviewed_selection_boundary(self) -> None:
        document = dict(catalog_document())
        schema = json.loads(
            (
                ROOT
                / "src"
                / "gravity_insight"
                / "contracts"
                / "schema"
                / "user-report-field-catalog-v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        Draft202012Validator(schema).validate(document)

        rows = [dict(row) for row in catalog_rows()]
        names = [row["name"] for row in rows]
        self.assertEqual(
            (SCHEMA_VERSION, CATALOG_ID, CATALOG_VERSION, list(GROUPS)),
            (
                document["schema_version"],
                document["catalog_id"],
                document["catalog_version"],
                document["groups"],
            ),
        )
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(22, sum(row["default"] for row in rows))
        self.assertEqual(
            {
                "base": 16,
                "pay": 6,
                "ad_revenue": 42,
                "profile": 10,
                "attribution": 5,
                "re_attribute": 1,
                "device": 1,
            },
            Counter(row["group"] for row in rows),
        )
        self.assertEqual(
            {"static_projection": 80, "live_metadata": 1},
            Counter(row["selection"] for row in rows),
        )
        self.assertEqual(
            ["user$os_version"],
            [row["name"] for row in rows if row["selection"] == "live_metadata"],
        )
        self.assertEqual(len(rows), catalog_metadata()["field_count"])

    def test_runtime_search_is_database_free_typed_and_paginated(self) -> None:
        result = search_metadata(
            "OS_VERSION",
            database="definitely-missing.sqlite3",
            kind="user_report_field",
            group="profile",
            limit=1,
            offset=0,
        )
        row = result["results"][0]
        self.assertEqual(
            (True, "runtime", "profile", "user$os_version", "live_metadata"),
            (
                result["offline"],
                result["scope"],
                result["group"],
                row["name"],
                row["payload"]["selection"],
            ),
        )
        page = search_metadata(
            "",
            kind="user_report_field",
            group="profile",
            limit=2,
            offset=1,
        )
        self.assertEqual((2, 10, 1), (page["count"], page["total"], page["offset"]))
        with self.assertRaises(InputValidationError):
            search_metadata("", kind="user_report_field", group="unknown")
        with self.assertRaises(InputValidationError):
            search_metadata("", kind="metric", group="profile")
        with self.assertRaises(InputValidationError):
            search_metadata("", kind="user_report_field", app_id="7")

    def test_metric_search_retains_preset_personal_and_shared_identity(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
            database = Path(temporary) / "metadata.sqlite3"
            with sqlite3.connect(database) as connection:
                _create_schema(connection)
                connection.execute(
                    "INSERT INTO catalog_metadata(key, value) VALUES (?, ?)",
                    ("analysis_vocabulary_observed", "true"),
                )
                rows = (
                    (
                        "report_metrics",
                        "report.multidim.metric.list",
                        "metric",
                        "Cost",
                        "Spend",
                        {"name": "Cost", "cname": "Spend", "tip": "preset", "exclusion_dims": ["country"]},
                    ),
                    (
                        "custom_metrics",
                        "report.multidim.custom_metric.list",
                        "custom_metric",
                        "Cost",
                        "Personal cost",
                        {"name": "Cost", "cname": "Personal cost", "tip": "mine", "exclusion_dims": []},
                    ),
                    (
                        "shared_custom_metrics",
                        "report.multidim.shared_custom_metric.list",
                        "custom_metric",
                        "Cost",
                        "Shared cost",
                        {"name": "Cost", "cname": "Shared cost", "tip": "shared", "exclusion_dims": ["channel"]},
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO analysis_vocabulary_rows(
                        source, operation_id, kind, row_index, name, cname,
                        payload_json, synced_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            source,
                            operation_id,
                            kind,
                            index,
                            name,
                            cname,
                            json.dumps(payload),
                            "2026-10-15T00:00:00Z",
                        )
                        for index, (source, operation_id, kind, name, cname, payload)
                        in enumerate(rows)
                    ],
                )
                connection.commit()

            preset = search_metadata("cOsT", database=database, kind="metric")
            custom = search_metadata("COST", database=database, kind="custom_metric")

        self.assertEqual(["report_metrics"], [row["source"] for row in preset["results"]])
        self.assertEqual(
            {"custom_metrics", "shared_custom_metrics"},
            {row["source"] for row in custom["results"]},
        )
        self.assertEqual(
            {"mine", "shared"},
            {row["payload"]["tip"] for row in custom["results"]},
        )
        self.assertEqual(
            {(), ("channel",)},
            {tuple(row["payload"]["exclusion_dims"]) for row in custom["results"]},
        )

    def test_agent_merges_runtime_fields_when_a_legacy_catalog_search_succeeds(self) -> None:
        with patch(
            "gravity_insight.find.search_metadata", return_value={"results": []}
        ):
            cards, warnings = metadata_capability_cards("country", limit=2)

        self.assertEqual([], warnings)
        self.assertEqual(["user$country"], [card["name"] for card in cards])

    def test_field_policy_keeps_os_version_live_metadata_gated(self) -> None:
        operation = _user_detail_operation()

        validate_analysis_detail(
            operation,
            {"app_id": "7", "date": "2026-10-13", "fields": ["ClientID"]},
            lambda *_args: self.fail("static projection must not load metadata"),
        )

        def live_loader(operation_id, _inputs):
            if operation_id == ANALYSIS_USER_PROPERTY:
                return {"status": "success", "data": {"list": [{"name": "$os_version"}]}}
            if operation_id in {ANALYSIS_EVENT_PROPERTY, ANALYSIS_SEGMENT}:
                return {"status": "empty", "data": {"list": []}}
            raise AssertionError(operation_id)

        validate_analysis_detail(
            operation,
            {"app_id": "7", "date": "2026-10-13", "fields": ["user$os_version"]},
            live_loader,
        )
        with self.assertRaisesRegex(InputValidationError, "absent from live metadata"):
            validate_analysis_detail(
                operation,
                {"app_id": "7", "date": "2026-10-13", "fields": ["user$os_version"]},
                lambda _operation_id, _inputs: {"status": "empty", "data": {"list": []}},
            )

    def test_cli_sdk_plan_and_agent_share_the_runtime_catalog(self) -> None:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = cli.main(
                [
                    "metadata",
                    "vocabulary",
                    "country",
                    "--kind",
                    "user_report_field",
                    "--group",
                    "profile",
                ]
            )
        cli_result = json.loads(stdout.getvalue())
        self.assertEqual((0, "user$country"), (exit_code, cli_result["results"][0]["name"]))

        sdk = GravitySDK(insight_factory=lambda: self.fail("catalog must stay offline"))
        sdk_result = sdk.analysis_vocabulary(
            "country", kind="user_report_field", group="profile"
        )
        self.assertEqual("user$country", sdk_result["results"][0]["name"])

        plan = {
            "schema_version": "gravity.plan.v1",
            "nodes": [
                {
                    "id": "field",
                    "kind": "metadata_search",
                    "request": {
                        "query": "country",
                        "kind": "user_report_field",
                        "group": "profile",
                        "limit": 1,
                    },
                    "limits": {"max_items": 1},
                }
            ],
        }
        plan_result = sdk.execute_plan(plan, workspace=object())["results"][0]["result"]
        self.assertEqual("user$country", plan_result["results"][0]["name"])
        plan["nodes"][0]["request"].update(kind="metric", group="profile")
        with self.assertRaises(PlanValidationError):
            sdk.validate_plan(plan)

        original_search = search_metadata

        def missing_workspace_catalog(query="", **options):
            if options.get("kind") == "user_report_field":
                return original_search(query, **options)
            raise InputValidationError("metadata catalog does not exist", field="database")

        with patch("gravity_insight.find.search_metadata", side_effect=missing_workspace_catalog):
            cards, warnings = metadata_capability_cards("country", limit=2)
        card = cards[0]
        self.assertEqual([], warnings)
        self.assertEqual(
            ("runtime", "profile", True, {"fields": ["user$country"]}),
            (
                card["scope"],
                card["group"],
                card["execution_ready"],
                card["request_fragment"],
            ),
        )

        with patch("gravity_insight.find.search_metadata", side_effect=missing_workspace_catalog):
            live_cards, warnings = metadata_capability_cards("os_version", limit=2)
        live = live_cards[0]
        self.assertEqual([], warnings)
        self.assertFalse(live["execution_ready"])
        self.assertNotIn("request_fragment", live)
        self.assertIn("live user-property metadata", live["next_action"])


if __name__ == "__main__":
    unittest.main()
