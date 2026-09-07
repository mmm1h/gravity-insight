"""Keep the production recertification receipt honest without live requests."""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from gravity_insight.capability_validation import validate_capability_validation
from gravity_insight.capability_contract import capability_contract
from gravity_insight.pagination_completeness import page_completeness

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "evidence/forensics/20260907_operation_recertification.json"


class OperationRecertificationEvidenceTests(unittest.TestCase):
    def test_scoped_collection_accounts_for_every_operation_and_request(self):
        evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        for stage, count in (("171", 22), ("170", 53)):
            with self.subTest(stage=stage):
                rows = evidence["records"][stage]
                self.assertEqual(count, len(rows))
                self.assertEqual(set(evidence["scope"][stage]), {r["selector"] for r in rows})
                self.assertTrue(all(r["reason"] for r in rows))
        ledger = evidence["request_ledger"]
        self.assertEqual(list(range(1, len(ledger) + 1)), [r["request_number"] for r in ledger])
        self.assertEqual(len(ledger), evidence["production_requests"])
        self.assertEqual(len(ledger), sum(evidence["production_requests_by_stage"].values()))
        self.assertEqual(len(ledger), len(evidence["schema_observations"]))
        self.assertEqual(any(r["http_status"] == 429 for r in ledger), evidence["encountered_429"])

    def test_promotions_require_explicit_typed_echo_and_exact_total(self):
        evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        promoted = [r for r in evidence["records"]["170"] if r["conclusion"] == "complete"]
        self.assertEqual(evidence["promoted_count"], len(promoted))
        for row in promoted:
            with self.subTest(operation=row["selector"]):
                self.assertEqual({True}, set(row["evidence"].values()))
                pages = row["pages"]
                total = pages[0]["page_fields"]["total_number"]["value"]
                total_pages = pages[0]["page_fields"]["total_page"]["value"]
                self.assertEqual(set(range(1, total_pages + 1)), {p["requested_page"] for p in pages})
                for page in pages:
                    for field in ("page", "page_size", "total_page", "total_number"):
                        scalar = page["page_fields"][field]
                        self.assertTrue(scalar["present"])
                        self.assertIs(type(scalar["value"]), int)
                    self.assertEqual(page["requested_page"], page["page_fields"]["page"]["value"])
                    self.assertEqual(total, page["page_fields"]["total_number"]["value"])
                    self.assertEqual(total_pages, page["page_fields"]["total_page"]["value"])
                    self.assertEqual(page["returned_items"], page["sdk_page"]["item_count"])
                last = next(p for p in pages if p["requested_page"] == total_pages)
                self.assertIs(last["sdk_page"]["has_more"], False)
                self.assertEqual(total, sum(p["returned_items"] for p in pages))
                merged = {**last["sdk_page"], "item_count": total}
                self.assertEqual("complete", page_completeness("complete", merged, all_pages=True))
                merged["item_count"] += 1
                self.assertEqual("prefix", page_completeness("complete", merged, all_pages=True))

    def test_validation_evidence_references_resolve_to_successful_http_receipts(self):
        evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
        receipts = {r["receipt_id"]: r for r in evidence["http_receipts"]}
        expected = set(evidence["scope"]["171"]) - {
            "analysis.default_val.list", "material.local.list", "material.report.query",
        }
        actual = {r["selector"] for r in evidence["records"]["171"] if r.get("current_validation")}
        self.assertEqual(19, evidence["stage_171_current_validations"])
        self.assertEqual(expected, actual)
        for row in evidence["records"]["171"]:
            validation = row.get("current_validation")
            if validation is None:
                continue
            with self.subTest(operation=row["selector"]):
                validate_capability_validation(validation)
                current = capability_contract("operation", row["selector"])
                self.assertEqual(current["digest"], validation["contract_digest"])
                self.assertEqual(current["contract"]["provider"]["fingerprint"], validation["provider_fingerprint"])
                self.assertEqual(row["outcome"]["contract_digest"], validation["contract_digest"])
                self.assertEqual(row["outcome"]["provider_fingerprint"], validation["provider_fingerprint"])
                for reference in validation["evidence_references"]:
                    receipt = receipts[reference["reference"].removeprefix("receipt:")]
                    self.assertEqual(row["selector"], receipt["operation_id"])
                    self.assertTrue(200 <= receipt["http_status"] < 300)

    def test_drift_paths_do_not_preserve_business_date_bucket_values(self):
        def check(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == "path" and isinstance(item, str):
                        self.assertIsNone(re.search(r"(?:^|/)\d{4}-\d{2}-\d{2}(?:/|$)", item))
                    check(item)
            elif isinstance(value, list):
                for item in value:
                    check(item)
        check(json.loads(EVIDENCE.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
