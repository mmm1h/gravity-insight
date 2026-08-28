from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from gravity_sdk.census.diffing import diff_routes
from gravity_sdk.census.impact import assess_route_impacts


ROOT = Path(__file__).resolve().parents[1]
ROUTES_PATH = ROOT / "src" / "gravity_sdk" / "census" / "data" / "routes.json"
PROVENANCE_PATH = (
    ROOT
    / "src"
    / "gravity_sdk"
    / "contracts"
    / "generated"
    / "provenance.json"
)
CONTRACTS_ROOT = ROOT / "src" / "gravity_sdk" / "contracts"

REMOVED_OPERATION = "analysis.event.list"
REMOVED_ROUTE = "/turbo_engine/api/v2/event/event_list/"
METHOD_OPERATION = "analysis.funnel.query"
METHOD_ROUTE = "/report/api/v3/dataanalysis/funnel/"
# 静态 census 只能把操作降级到 suspect，不能直接隔离：前端路由消失不等于
# 后端下线。census 找出的 4 条「manifest 有但前端无」的路由经 probe 实测
# 全部仍然可用、无一 404，证明前端停止调用与后端下线是两回事。
# 升级为 upstream_changed 需要「前端消失 + 定向 probe 确认失败」双证据，
# 该路径由 tests/test_gravity_insight_draft_guard.py 覆盖。
SUSPECT_STATES = {
    REMOVED_OPERATION: "suspect",
    METHOD_OPERATION: "suspect",
}


class GravityCensusDriftPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.baseline = json.loads(ROUTES_PATH.read_text(encoding="utf-8"))
        cls.provenance = json.loads(PROVENANCE_PATH.read_text(encoding="utf-8"))

    def _rehearsal_diff(self):
        return diff_routes(self.baseline, self._rehearsal_routes())

    def _rehearsal_routes(self):
        current = copy.deepcopy(self.baseline)
        current["source"]["bundle_id"] = "synthetic-upstream-rehearsal"
        current["source"]["bundle_complete"] = True
        routes = []
        for route in current["routes"]:
            if route["method"] == "GET" and route["path"] == REMOVED_ROUTE:
                continue
            if route["method"] == "POST" and route["path"] == METHOD_ROUTE:
                route = {**route, "method": "GET"}
            routes.append(route)
        current["routes"] = routes
        return current

    def test_current_bundle_rehearsal_locates_operations_and_marks_suspect(self) -> None:
        route_diff = self._rehearsal_diff()

        result = assess_route_impacts(
            route_diff,
            self.provenance,
            CONTRACTS_ROOT,
        )

        self.assertEqual(1, route_diff["summary"]["removed"])
        self.assertEqual(1, route_diff["summary"]["method_changed"])
        by_id = {item["operation_id"]: item for item in result["operations"]}
        self.assertEqual({REMOVED_OPERATION, METHOD_OPERATION}, set(by_id))
        self.assertEqual(["route_removed"], by_id[REMOVED_OPERATION]["impact_types"])
        self.assertEqual(["method_changed"], by_id[METHOD_OPERATION]["impact_types"])
        for operation_id in (REMOVED_OPERATION, METHOD_OPERATION):
            self.assertEqual("P0", by_id[operation_id]["priority"])
            self.assertEqual("suspect", by_id[operation_id]["health"]["status"])
            # 完整 census 的证据必须被记录下来，供后续 probe 判定使用
            self.assertIn(
                "complete frontend census", by_id[operation_id]["health"]["reason"]
            )
            self.assertTrue(by_id[operation_id]["health"]["evidence_refs"])
            # 不误杀：suspect 阶段必须仍然允许调用。这条断言是防回退护栏——
            # 如果有人把静态 census 改回「一发现路由消失就 fail closed」，
            # 这里会立刻红。
            self.assertEqual(
                {
                    "allowed": True,
                    "error_code": None,
                    "warning": by_id[operation_id]["health"]["reason"],
                    "retry": False,
                },
                by_id[operation_id]["call_decision"],
            )
        self.assertEqual(
            [REMOVED_OPERATION, METHOD_OPERATION],
            result["probe_plan"]["direct_operation_ids"],
        )
        self.assertFalse(result["probe_plan"]["business_api_called"])
        self.assertFalse(result["source_contracts_modified"])

    def test_current_bundle_rehearsal_runs_through_the_cli_file_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline_path = root / "baseline-routes.json"
            current_path = root / "current-routes.json"
            diff_path = root / "route-diff.json"
            impact_path = root / "operation-impact.json"
            overlay_path = root / "health-overlay.json"
            baseline_path.write_text(json.dumps(self.baseline), encoding="utf-8")
            current_path.write_text(json.dumps(self._rehearsal_routes()), encoding="utf-8")

            diff_process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "gravity_sdk.census",
                    "diff",
                    str(baseline_path),
                    str(current_path),
                    "--output",
                    str(diff_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, diff_process.returncode, diff_process.stderr)
            impact_process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "gravity_sdk.census",
                    "impact",
                    str(diff_path),
                    "--output",
                    str(impact_path),
                    "--overlay-output",
                    str(overlay_path),
                    "--require-complete",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, impact_process.returncode, impact_process.stderr)

            impact = json.loads(impact_path.read_text(encoding="utf-8"))
            overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [REMOVED_OPERATION, METHOD_OPERATION],
                impact["probe_plan"]["direct_operation_ids"],
            )
            self.assertEqual(
                SUSPECT_STATES,
                {
                    operation_id: entry["status"]
                    for operation_id, entry in overlay["entries"].items()
                },
            )

    def test_same_route_diff_stays_suspect_when_census_is_incomplete(self) -> None:
        result = assess_route_impacts(
            self._rehearsal_diff(),
            self.provenance,
            CONTRACTS_ROOT,
            census_complete=False,
        )

        self.assertFalse(result["census_complete"])
        for operation in result["operations"]:
            self.assertEqual("suspect", operation["health"]["status"])
            self.assertTrue(operation["call_decision"]["allowed"])

    def test_unmapped_added_route_is_kept_for_contract_triage(self) -> None:
        route_diff = {
            "kind": "route_diff",
            "new_bundle_complete": True,
            "added": [{"method": "GET", "path": "/api/v99/new-surface/"}],
            "removed": [],
            "method_changes": [],
            "path_changes": [],
        }

        result = assess_route_impacts(route_diff, self.provenance, CONTRACTS_ROOT)

        self.assertEqual([], result["operations"])
        self.assertEqual(1, result["summary"]["unmapped_changes"])
        self.assertEqual("route_added", result["unmapped_changes"][0]["impact_type"])

    def test_path_change_maps_through_the_old_registered_route(self) -> None:
        route_diff = {
            "kind": "route_diff",
            "new_bundle_complete": True,
            "added": [],
            "removed": [],
            "method_changes": [],
            "path_changes": [
                {
                    "method": "GET",
                    "old_path": REMOVED_ROUTE,
                    "new_path": "/turbo_engine/api/v3/event/event_list/",
                }
            ],
        }

        result = assess_route_impacts(route_diff, self.provenance, CONTRACTS_ROOT)

        self.assertEqual([REMOVED_OPERATION], result["probe_plan"]["direct_operation_ids"])
        self.assertEqual(["path_changed"], result["operations"][0]["impact_types"])


if __name__ == "__main__":
    unittest.main()
