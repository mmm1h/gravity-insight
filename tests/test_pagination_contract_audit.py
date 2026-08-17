from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gravity_sdk.pagination_contract_audit import (
    OPERATIONS_ROOT,
    current_operation_pagination,
    load_pagination_audit,
    reconcile_pagination_audit,
)


class PaginationContractAuditTests(unittest.TestCase):
    def test_snapshot_is_a_historical_verdict_joined_to_current_contracts(self) -> None:
        audit = load_pagination_audit()
        records = audit["records"]
        operation_ids = {
            json.loads(path.read_text(encoding="utf-8"))["operation"]["operation_id"]
            for path in OPERATIONS_ROOT.glob("*.json")
        }
        current = current_operation_pagination()
        reconciled = reconcile_pagination_audit(audit, current)

        self.assertEqual("historical_verdict", audit["relationship"]["kind"])
        self.assertEqual(len(current), len(records))
        self.assertEqual(operation_ids, {item["operation_id"] for item in records})
        self.assertEqual(
            {"page_info": 120, "none": 115},
            audit["summary"]["audit_baseline_declared_kinds"],
        )
        self.assertNotIn("declared_kinds", audit["summary"])
        self.assertEqual({"A": 60, "B": 1, "unknown": 59}, audit["summary"]["page_info_shapes"])
        self.assertTrue(all(item["evidence_sources"] for item in records))
        by_id = {item["operation_id"]: item for item in records}
        self.assertEqual("B", by_id["report.multidim.query"]["observed_shape"])
        self.assertEqual("page_info", by_id["report.multidim.query"]["declared_kind"])
        self.assertEqual("none", current["report.multidim.query"]["kind"])
        self.assertEqual(
            "repaired",
            by_id["report.multidim.query"]["declared_kind_disposition"]["status"],
        )
        self.assertEqual(
            "manual_empty_page_protocol",
            by_id["analysis.user_event.list"]["review_status"],
        )
        self.assertEqual(
            "wire_pagination_signal",
            by_id["candidate.promotion_object.click_url.list"]["review_status"],
        )
        self.assertEqual([], reconciled["unexpected_kind_drift"])
        self.assertEqual([], reconciled["coverage"]["missing_from_audit"])
        self.assertEqual([], reconciled["coverage"]["missing_from_contracts"])
        self.assertEqual(
            dict(sorted(Counter(item["kind"] for item in current.values()).items())),
            reconciled["current_declared_kinds"],
        )
        self.assertEqual("none", next(
            item["current_declared_kind"]
            for item in reconciled["records"]
            if item["operation_id"] == "report.multidim.query"
        ))
        self.assertEqual(
            audit["summary"]["page_info_evidence_levels"]["template_default"],
            len(reconciled["unproven_page_info"]),
        )
        self.assertTrue(
            all(
                current[item]["kind"] == "page_info"
                and by_id[item]["evidence_level"] == "template_default"
                for item in reconciled["unproven_page_info"]
            )
        )
        shape_a = [
            item for item in reconciled["records"]
            if item["observed_shape"] == "A" and item["current_declared_kind"] == "page_info"
        ]
        self.assertEqual(60, len(shape_a))
        self.assertTrue(all(item["current_total_page_field"] == "total_page" for item in shape_a))

    def test_undeclared_kind_change_is_unexpected_drift(self) -> None:
        audit = load_pagination_audit()
        current = current_operation_pagination()
        current["analysis.account_user.list"] = {
            **current["analysis.account_user.list"],
            "kind": "none",
        }
        reconciled = reconcile_pagination_audit(audit, current)
        drifted = reconciled["unexpected_kind_drift"]
        self.assertEqual(["analysis.account_user.list"], [item["operation_id"] for item in drifted])
        self.assertEqual("page_info", drifted[0]["declared_kind"])
        self.assertEqual("none", drifted[0]["current_declared_kind"])

    def test_current_loader_reads_live_contract_kind(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "analysis.account_user.list.json"
            source = OPERATIONS_ROOT / "analysis.account_user.list.json"
            document = json.loads(source.read_text(encoding="utf-8"))
            document["operation"]["pagination"]["kind"] = "none"
            path.write_text(json.dumps(document), encoding="utf-8")
            with patch(
                "gravity_sdk.pagination_contract_audit.OPERATIONS_ROOT",
                Path(directory),
            ):
                current = current_operation_pagination()
        self.assertEqual("none", current["analysis.account_user.list"]["kind"])
