from __future__ import annotations

import json
import re
import subprocess
import unittest
from collections import Counter
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from gravity_insight.pagination_contract_audit import (
    OPERATIONS_ROOT,
    _response_scalar_only,
    current_operation_pagination,
    load_pagination_audit,
    reconcile_pagination_audit,
)


PAGINATION_EVIDENCE_PLAN = (
    Path(__file__).parents[1] / "docs" / "maintainers" / "pagination-evidence-plan.md"
)


def _planned_production_evidence_targets() -> set[str]:
    """The collectable targets the plan actually lists, excluding permanent unknown."""
    plan = PAGINATION_EVIDENCE_PLAN.read_text(encoding="utf-8")
    collectable = plan.split("## 永久 unknown", maxsplit=1)[0]
    return set(re.findall(r"^\| `([^`]+)` \|", collectable, re.MULTILINE))


def _reproducible_evidence_source(root: Path, source: str) -> bool:
    path = source.split("#", 1)[0]
    if not path.startswith("git:"):
        return (root / path).is_file()
    match = re.fullmatch(r"git:([0-9a-f]{40}):([^:]+)", path)
    if match is None or ".." in Path(match.group(2)).parts:
        return False
    return subprocess.run(
        ["git", "cat-file", "-e", f"{match.group(1)}:{match.group(2)}"],
        cwd=root,
        check=False,
        capture_output=True,
    ).returncode == 0


class PaginationContractAuditTests(unittest.TestCase):
    def test_response_scalar_only_rejects_all_missed_collection_capabilities(
        self,
    ) -> None:
        scalar_projection = {
            "data_keys": ["a"],
            "required_data_keys": ["a"],
            "numeric_paths": ["a"],
        }
        missed_capabilities = {
            "data_path_item_keys": {"a.items": ["id"]},
            "known_omitted_data_keys": ["omitted"],
            "known_omitted_item_keys": ["omitted"],
            "known_omitted_nested_item_keys": {"item": ["omitted"]},
            "known_omitted_data_item_keys": {"a": ["omitted"]},
            "opaque_json_item_keys": ["payload"],
            "unreliable_item_keys": {
                "value": {"reason": "unstable", "use_instead": "stable_value"}
            },
            "scalar_list_item_types": {"values": "number"},
        }

        self.assertTrue(_response_scalar_only(scalar_projection))
        for field, capability in missed_capabilities.items():
            with self.subTest(field=field):
                self.assertFalse(
                    _response_scalar_only(
                        {**scalar_projection, field: capability}
                    )
                )

    def test_response_scalar_only_fails_closed_for_invalid_or_unknown_shape(
        self,
    ) -> None:
        scalar_projection = {
            "data_keys": ["a"],
            "required_data_keys": ["a"],
            "numeric_paths": ["a"],
        }
        invalid_projections = {
            "invalid data shape": {**scalar_projection, "data_shape": "array"},
            "unknown model field": {
                **scalar_projection,
                "future_collection_capability": ["item"],
            },
            "non-string field": {
                "data_keys": [1],
                "required_data_keys": [1],
                "numeric_paths": [1],
            },
            "duplicate field": {
                "data_keys": ["a", "a"],
                "required_data_keys": ["a", "a"],
                "numeric_paths": ["a", "a"],
            },
        }

        for case, projection in invalid_projections.items():
            with self.subTest(case=case):
                self.assertFalse(_response_scalar_only(projection))

    def test_only_current_scalar_only_contract_is_segment_evaluate_percent(
        self,
    ) -> None:
        current = current_operation_pagination()

        self.assertEqual(
            ["analysis.segment.evaluate_percent"],
            sorted(
                operation_id
                for operation_id, pagination in current.items()
                if pagination["_evidence_context"]["response_scalar_only"]
            ),
        )

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
            {"page_info": 120, "none": 117},
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
        self.assertEqual({"complete": 60, "unknown": 177}, reconciled["current_completeness"])
        self.assertEqual(
            {
                "collect_production_or_wire": 84,
                "not_scheduled_non_stable": 9,
                "not_scheduled_without_new_signal": 84,
            },
            reconciled["unknown_evidence_actions"],
        )
        # Set equality against the plan, not a bare count: swapping one target
        # for another keeps len() at 84 while silently changing the debt scope.
        planned_targets = _planned_production_evidence_targets()
        self.assertEqual(84, len(planned_targets))
        self.assertEqual(planned_targets, set(reconciled["production_evidence_targets"]))
        self.assertEqual(84, len(reconciled["permanent_unknown"]))
        self.assertEqual(
            {
                "no_falsifiable_completeness_signal": 37,
                "not_collection_semantics": 47,
            },
            reconciled["permanent_unknown_dispositions"],
        )
        self.assertEqual(
            {"production": 98, "template": 130, "wire": 9},
            reconciled["current_pagination_evidence"],
        )
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

    def test_permanent_unknown_requires_a_narrow_reproducible_reason(self) -> None:
        audit = load_pagination_audit()
        current = current_operation_pagination()
        reconciled = reconcile_pagination_audit(audit, current)
        by_id = {item["operation_id"]: item for item in reconciled["records"]}

        self.assertEqual(
            "no_falsifiable_completeness_signal",
            by_id["analysis.dashboard.tree"]["unknown_evidence_disposition"],
        )
        self.assertEqual(
            "not_collection_semantics",
            by_id["analysis.dashboard.detail"]["unknown_evidence_disposition"],
        )
        self.assertEqual(
            "not_collection_semantics",
            by_id["analysis.segment.evaluate_percent"][
                "unknown_evidence_disposition"
            ],
        )
        self.assertEqual(
            "no_falsifiable_completeness_signal",
            by_id["analysis.default_val.list"]["unknown_evidence_disposition"],
        )
        self.assertEqual(
            "no_falsifiable_completeness_signal",
            by_id["analysis.event.query"]["unknown_evidence_disposition"],
        )
        self.assertEqual(
            "production",
            current["analysis.event.query"]["pagination_evidence"],
        )
        root = Path(__file__).resolve().parents[1]
        for item in by_id.values():
            if (
                item["unknown_evidence_disposition"]
                == "no_falsifiable_completeness_signal"
                and item["review_status"]
                in {"no_page_info_in_observed_response", "shape_verified"}
            ):
                self.assertEqual("production", item["evidence_level"])
                self.assertTrue(
                    all(
                        _reproducible_evidence_source(root, source)
                        for source in item["evidence_sources"]
                    )
                )

        weakened_audit = deepcopy(audit)
        default_value = next(
            item for item in weakened_audit["records"]
            if item["operation_id"] == "analysis.default_val.list"
        )
        default_value["evidence_level"] = "template_default"
        weakened = reconcile_pagination_audit(weakened_audit, current)
        weakened_by_id = {item["operation_id"]: item for item in weakened["records"]}
        self.assertIsNone(
            weakened_by_id["analysis.default_val.list"]["unknown_evidence_disposition"]
        )

        pageable_tree = deepcopy(current)
        pageable_tree["analysis.dashboard.tree"]["_evidence_context"][
            "request_fields"
        ].append("page")
        changed = reconcile_pagination_audit(audit, pageable_tree)
        changed_by_id = {item["operation_id"]: item for item in changed["records"]}
        self.assertIsNone(
            changed_by_id["analysis.dashboard.tree"]["unknown_evidence_disposition"]
        )

        collection_evaluation = deepcopy(current)
        collection_evaluation["analysis.segment.evaluate_percent"][
            "_evidence_context"
        ]["response_scalar_only"] = False
        changed = reconcile_pagination_audit(audit, collection_evaluation)
        changed_by_id = {item["operation_id"]: item for item in changed["records"]}
        self.assertIsNone(
            changed_by_id["analysis.segment.evaluate_percent"][
                "unknown_evidence_disposition"
            ]
        )

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
                "gravity_insight.pagination_contract_audit.OPERATIONS_ROOT",
                Path(directory),
            ):
                current = current_operation_pagination()
        self.assertEqual("none", current["analysis.account_user.list"]["kind"])
