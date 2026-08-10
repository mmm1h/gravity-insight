from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from gravity_sdk.census.coverage import (
    build_coverage,
    load_manifest_operations,
    load_route_classifications,
    load_write_reservations,
)
from gravity_sdk.compiler import ContractCompiler

try:
    from gravity_sdk import GravityInsightClient
except ModuleNotFoundError:
    from gravity_sdk import GravityInsightClient


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "src" / "gravity_sdk" / "contracts"
RESERVATION_ROOT = CONTRACT_ROOT / "reservations"
ROUTE_REGISTRY = CONTRACT_ROOT / "routes" / "registry.json"
COVERAGE_PATH = ROOT / "src" / "gravity_sdk" / "census" / "data" / "coverage.json"
MANIFEST_ROOT = ROOT / "src" / "gravity_sdk" / "manifests"


class _NoNetworkTransport:
    is_test_transport = True

    def __init__(self) -> None:
        self.calls: list[object] = []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("blocked_write validation must not invoke transport")


class GravityInsightWriteRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.coverage = json.loads(COVERAGE_PATH.read_text(encoding="utf-8"))
        cls.reservations = load_write_reservations(RESERVATION_ROOT)
        cls.classifications = load_route_classifications(ROUTE_REGISTRY)

    def test_all_target_write_routes_have_unique_blocked_reservations(self) -> None:
        source_routes = {
            (item["method"], item["path"])
            for item in self.coverage["routes"]
            if item["status"] == "uncovered_write"
            and item.get("route_classification") is None
        }
        reserved_routes = {
            (item["method"], item["path"])
            for item in self.reservations
        }
        self.assertEqual(362, len(source_routes))
        self.assertTrue(source_routes <= reserved_routes)
        self.assertEqual(414, len(self.reservations))
        self.assertEqual(
            len(self.reservations),
            len({item["operation_id"] for item in self.reservations}),
        )

        compiler = ContractCompiler(CONTRACT_ROOT, MANIFEST_ROOT)
        for path in sorted(RESERVATION_ROOT.glob("*.json")):
            with self.subTest(path=path.name):
                source = json.loads(path.read_text(encoding="utf-8"))
                compiler.operation_schema.validate(source)
                operation = source["operation"]
                metadata = source["reservation"]
                self.assertEqual("mutation", operation["effect"])
                self.assertEqual("blocked_write", operation["stability"])
                self.assertFalse(operation["executable"])
                self.assertEqual(
                    "mutation_sdk_not_implemented", operation["block_reason"]
                )
                self.assertEqual(
                    "mutation_sdk_not_implemented", metadata["block_reason"]
                )

    def test_semantic_and_risk_dimensions_are_complete(self) -> None:
        kinds = Counter()
        risk_counts = Counter()
        for path in RESERVATION_ROOT.glob("*.json"):
            source = json.loads(path.read_text(encoding="utf-8"))
            semantics = source["reservation"]["mutation_semantics"]
            kinds[semantics["kind"]] += 1
            risk_counts[("reversibility", semantics["reversibility"])] += 1
            risk_counts[("scope", semantics["scope"])] += 1
            risk_counts[("delivery", semantics["affects_live_delivery"])] += 1
            self.assertTrue(semantics["evidence"])
            self.assertIn(
                semantics["idempotency"],
                {"idempotent", "non_idempotent", "conditional", "unknown"},
            )
        self.assertEqual(414, sum(kinds.values()))
        self.assertGreater(kinds["create"], 0)
        self.assertGreater(kinds["update"], 0)
        self.assertGreater(kinds["delete"], 0)
        self.assertGreater(kinds["batch"], 0)
        self.assertGreater(risk_counts[("scope", "batch")], 0)

    def test_auth_proxy_and_unclassified_routes_are_exhaustively_registered(self) -> None:
        source_targets = {
            (item["method"], item["path"])
            for item in self.coverage["routes"]
            if item.get("route_classification") is not None
        }
        registered = {(item["method"], item["path"]) for item in self.classifications}
        self.assertEqual(110, len(source_targets))
        self.assertEqual(source_targets, registered)
        counts = Counter(item["source_status"] for item in self.classifications)
        self.assertEqual(30, counts["uncovered_auth_or_proxy"])
        self.assertEqual(80, counts["unclassified"])
        self.assertTrue(
            all(
                item["disposition"] == "unsupported"
                for item in self.classifications
                if item["source_status"] == "uncovered_auth_or_proxy"
            )
        )

    def test_repository_census_is_fully_accounted_without_inflating_callability(self) -> None:
        rebuilt = build_coverage(
            {"source": self.coverage["source"], "routes": self.coverage["routes"]},
            load_manifest_operations(MANIFEST_ROOT),
            reservations=self.reservations,
            route_classifications=self.classifications,
        )
        self.assertEqual(987, rebuilt["summary"]["accounted"])
        self.assertEqual(0, rebuilt["summary"]["unaccounted"])
        # callable_covered 随已验证 stable 操作数增长：write-registry 分支
        # 写作时 120，batch-probe 升 10 条、gi-reprobe 升 1 条；本趟再由
        # report.company_amount.query 与 report.overview.query 升至 133；
        # cid 租户标识复评再解锁 promotion.bytedance.app.list，升至 134；
        # 本趟隐私复评再解锁三条成功 probe，升至 137；巨量标题素材
        # 两条分页读取验证后升至 139；腾讯广告组配置复验后升至 140；
        # AI 托管与两条数据表配置读取复验后升至 143。
        # 本测试的保证不是「这个数不变」，而是「它远小于 accounted，且
        # blocked_write 绝不被计入可调用」——即下面两条 414 断言。
        self.assertEqual(143, rebuilt["summary"]["callable_covered"])
        self.assertEqual(414, rebuilt["accounting_summary"]["accounted_blocked_write"])
        self.assertEqual(414, rebuilt["callability_summary"]["contract_only"])

    def test_new_unclassified_route_fails_the_cli_accounting_gate(self) -> None:
        routes = {
            "source": {"bundle_complete": True, "bundle_id": "synthetic"},
            "routes": [
                {
                    "method": "POST",
                    "path": "/future/api/v1/opaque/",
                    "method_certainty": "low",
                }
            ],
        }
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as directory:
            temp = Path(directory)
            routes_path = temp / "routes.json"
            output_path = temp / "coverage.json"
            report_path = temp / "coverage.md"
            routes_path.write_text(json.dumps(routes), encoding="utf-8")
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "gravity_sdk.census",
                    "coverage",
                    "--routes",
                    str(routes_path),
                    "--output",
                    str(output_path),
                    "--report",
                    str(report_path),
                    "--require-accounted",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(4, process.returncode, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(1, result["unaccounted"])
        self.assertFalse(result["accounting_complete"])

    def test_blocked_write_validate_returns_not_implemented_without_network(self) -> None:
        source_path = next(
            path
            for path in sorted(RESERVATION_ROOT.glob("*.json"))
            if json.loads(path.read_text(encoding="utf-8"))["operation"]["upstream_method"]
            == "POST"
        )
        source = json.loads(source_path.read_text(encoding="utf-8"))
        runtime_operation = ContractCompiler._source_to_runtime(source["operation"])
        transport = _NoNetworkTransport()
        client = GravityInsightClient._from_manifest_for_tests(
            {"manifest_version": 1, "operations": [runtime_operation]},
            transport=transport,
        )
        result = client.validate(source["operation"]["operation_id"], {})
        self.assertFalse(result["ok"])
        self.assertEqual("NOT_IMPLEMENTED", result["error"]["code"])
        self.assertFalse(result["network_called"])
        self.assertEqual([], transport.calls)


if __name__ == "__main__":
    unittest.main()
