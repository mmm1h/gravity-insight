from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "evidence/forensics/20260817_pagination_contract_audit.json"
OPERATIONS = ROOT / "src/gravity_sdk/contracts/operations"


class PaginationContractAuditTests(unittest.TestCase):
    def test_snapshot_covers_every_baseline_operation_and_preserves_verdicts(self) -> None:
        audit = json.loads(AUDIT.read_text(encoding="utf-8"))
        records = audit["records"]
        operation_ids = {
            json.loads(path.read_text(encoding="utf-8"))["operation"]["operation_id"]
            for path in OPERATIONS.glob("*.json")
        }

        self.assertEqual(232, len(records))
        self.assertEqual(operation_ids, {item["operation_id"] for item in records})
        self.assertEqual({"page_info": 119, "none": 113}, audit["summary"]["declared_kinds"])
        self.assertEqual({"A": 59, "B": 1, "unknown": 59}, audit["summary"]["page_info_shapes"])
        self.assertTrue(all(item["evidence_sources"] for item in records))
        by_id = {item["operation_id"]: item for item in records}
        self.assertEqual("B", by_id["report.multidim.query"]["observed_shape"])
        self.assertEqual(
            "manual_empty_page_protocol",
            by_id["analysis.user_event.list"]["review_status"],
        )
        self.assertEqual(
            "wire_pagination_signal",
            by_id["candidate.promotion_object.click_url.list"]["review_status"],
        )
