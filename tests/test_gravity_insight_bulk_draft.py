from __future__ import annotations

import unittest
import tempfile

import json
import re
from pathlib import Path

from gravity_insight.prober.model import build_draft, create_bulk_drafts
from gravity_insight.prober.drafts import validate_source
from gravity_insight.prober.batch import classify_drafts


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _route(
    path: str,
    *,
    method: str = "POST",
    certainty: str = "high",
    module: str = "推广平台",
    platform: str | None = "xiaomi",
    status: str = "uncovered_read",
) -> dict[str, object]:
    return {
        "business_module": module,
        "callers": ["loadRows"],
        "cost_reason": "flat list/detail lookup with no evident parent dependency",
        "first_occurrence": {"file": "raw/example.js", "offset": 10},
        "manifest_operations": [],
        "method": method,
        "method_certainty": certainty,
        "method_evidence": ["same_request_options"],
        "path": path,
        "promotion_platform": platform,
        "semantic_evidence": ["read_action_path_token"],
        "status": status,
        "ui_texts": ["列表"],
    }



class GravityInsightBulkDraftTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.tmp_path = Path(self._temporary_directory.name)

    def test_bulk_draft_is_conservative_unique_and_auditable(self):
        stable_route = _route("/turbo_engine/api/v1/xiaomi/stable/list/")
        routes = [
            _route("/turbo_engine/api/v1/xiaomi/report/campaign/list/"),
            _route("/turbo_engine/api/v1/xiaomi/report_v4/campaign/list/"),
            _route(
                "/turbo_engine/api/v1/{e}/report/group/list/",
                module="报表",
                platform=None,
            ),
            _route("/account_center/api/v1/", method="GET", module="App 与账号", platform=None),
            stable_route,
            _route(
                "/turbo_engine/api/v1/medium/list/",
                certainty="medium",
                module="其它",
                platform=None,
            ),
            _route(
                "/turbo_engine/api/v1/unsafe/query/",
                module="其它",
                platform=None,
                status="unsafe_unknown",
            ),
        ]
        coverage_path = self.tmp_path / "coverage.json"
        draft_root = self.tmp_path / "drafts"
        operation_root = self.tmp_path / "operations"
        report_root = self.tmp_path / "reports"
        _write_json(coverage_path, {"routes": routes})
        _write_json(
            operation_root / "stable.list.json",
            {
                "operation": {
                    "operation_id": "promotion.xiaomi.stable.list",
                    "upstream_method": stable_route["method"],
                    "path_template": stable_route["path"],
                }
            },
        )

        summary = create_bulk_drafts(
            coverage_path=coverage_path,
            draft_root=draft_root,
            operation_root=operation_root,
            report_root=report_root,
            limit=10,
        )

        assert summary["attempted"] == 5
        assert summary["successful"] == 3
        assert summary["rejected"] == 2
        assert summary["excluded_certainty_counts"] == {"medium": 1}
        draft_rows = json.loads((report_root / "drafts.json").read_text(encoding="utf-8"))[
            "drafts"
        ]
        assert len({row["operation_id"] for row in draft_rows}) == 3
        assert all(row["path"] != "/turbo_engine/api/v1/unsafe/query/" for row in draft_rows)
        campaign_ids = {
            row["operation_id"] for row in draft_rows if "/campaign/list/" in row["path"]
        }
        assert len(campaign_ids) == 2
        dynamic = next(row for row in draft_rows if "{e}" in row["path"])
        source = json.loads(
            (draft_root / f"{dynamic['operation_id']}.json").read_text(encoding="utf-8")
        )
        assert source["operation"]["input_fields"] == {
            "e": {"required": True, "type": "any"}
        }
        assert source["operation"]["request"]["path_fields"] == ["e"]
        assert source["operation"]["request"]["query_fields"] == []
        assert source["operation"]["request"]["body_fields"] == []
        assert source["operation"]["pagination"]["kind"] == "unverified"
        assert source["operation"]["response_projection"]["item_keys"] == []
        assert source["draft"]["coverage_reference"]["json_pointer"] == "/routes/2"
        assert "path_parameter_type_unverified" in {
            blocker["code"] for blocker in source["draft"]["blockers"]
        }


    def test_bulk_draft_preserves_existing_probe_evidence(self):
        route = _route(
            "/turbo_engine/api/v1/tencent/manager/account/by_company/",
            method="GET",
            platform="tencent",
        )
        coverage_path = self.tmp_path / "coverage.json"
        draft_root = self.tmp_path / "drafts"
        _write_json(coverage_path, {"routes": [route]})
        source = build_draft(route, set())
        source["draft"]["probe_evidence"] = [
            {
                "path": "evidence/example.yaml",
                "probed_at": "2026-08-09T00:00:00Z",
                "conclusion": "inconclusive",
                "successful": False,
                "pagination_verified": False,
                "raw_schema_fingerprint": "a" * 64,
            }
        ]
        operation_id = source["operation"]["operation_id"]
        _write_json(draft_root / f"{operation_id}.json", source)

        summary = create_bulk_drafts(
            coverage_path=coverage_path,
            draft_root=draft_root,
            operation_root=self.tmp_path / "operations",
            report_root=self.tmp_path / "reports",
            limit=1,
        )

        assert summary["updated_existing"] == 1
        updated = json.loads(
            (draft_root / f"{operation_id}.json").read_text(encoding="utf-8")
        )
        assert updated["draft"]["probe_evidence"] == source["draft"]["probe_evidence"]
        assert updated["draft"]["coverage_reference"]["route_index"] == 0
        assert "probe_inconclusive" in {
            blocker["code"] for blocker in updated["draft"]["blockers"]
        }


    def test_repository_drafts_satisfy_bulk_quality_gate(self):
        contract_root = ROOT / "src" / "gravity_insight" / "contracts"
        operation_routes = set()
        for path in (contract_root / "operations").glob("*.json"):
            operation = json.loads(path.read_text(encoding="utf-8"))["operation"]
            operation_routes.add(
                (operation["upstream_method"], operation["path_template"])
            )
        draft_paths = sorted((contract_root / "drafts").glob("*.json"))
        assert draft_paths
        operation_ids: set[str] = set()
        draft_routes: set[tuple[str, str]] = set()
        for path in draft_paths:
            source = json.loads(path.read_text(encoding="utf-8"))
            validate_source(source)
            operation = source["operation"]
            assert operation["stability"] == "experimental"
            assert operation["executable"] is False
            assert "unknown" not in (
                operation["domain"],
                operation["resource"],
                operation["action"],
            )
            assert operation["operation_id"] not in operation_ids
            operation_ids.add(operation["operation_id"])
            route = (operation["upstream_method"], operation["path_template"])
            assert route not in operation_routes
            assert route not in draft_routes
            draft_routes.add(route)
            placeholders = set(
                re.findall(r"\{([A-Za-z][A-Za-z0-9_]*)\}", operation["path_template"])
            )
            assert placeholders == set(operation["request"]["path_fields"])
            assert placeholders <= set(operation["input_fields"])
            assert source["draft"]["coverage_reference"]["json_pointer"].startswith(
                "/routes/"
            )
            assert source["draft"]["blockers"]


    def test_repository_drafts_have_complete_availability_tiers(self):
        rows = classify_drafts()

        assert rows
        assert {row["tier"] for row in rows} == {1, 2, 3, 4, 5}
        assert len({row["operation_id"] for row in rows}) == len(rows)
        assert all(row["method"] in {"GET", "POST"} for row in rows)
