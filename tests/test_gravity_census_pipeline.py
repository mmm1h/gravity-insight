from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk.census.coverage import build_coverage
from gravity_sdk.census.diffing import diff_routes
from gravity_sdk.census.fetcher import StaticFetcher, _looks_like_vite_chunk, check_upstream
from gravity_sdk.census.io import json_bytes, sha256_bytes, stable_bundle_id
from gravity_sdk.census.normalize import comparison_path, normalize_path
from gravity_sdk.census.parser import build_routes, parse_text


REPO_ROOT = Path(__file__).resolve().parents[1]


class GravityCensusNormalizationTests(unittest.TestCase):
    def test_normalizes_template_colon_host_and_query(self) -> None:
        self.assertEqual(
            normalize_path("https://example.test/api/v1/app/${state.app_id}/detail?x=1"),
            "/api/v1/app/{app_id}/detail",
        )
        self.assertEqual(normalize_path("/api/v1/app/:id/detail/"), "/api/v1/app/{id}/detail/")
        self.assertEqual(comparison_path("/API/v1/app/{id}/detail/"), "/api/v1/app/{}/detail")


class GravityCensusParserTests(unittest.TestCase):
    def test_extracts_minified_calls_and_context(self) -> None:
        source = (
            'const getApp=id=>client.get(`/api/v1/app/${id}/detail`);'
            'const list=p=>req({url:"/api/v1/items/list/",method:"POST",data:p});'
            'const save=p=>req({method:"post",url:"/api/v1/items/save/",data:p});'
            'const label="保存项目";const joined=id=>client.get("/api/v1/app/"+id+"/owner/");'
        )
        rows = parse_text(source, file_info={"local_path": "raw/chunk.js", "url": "https://x/chunk.js"})
        pairs = {(item["method"], item["path"]) for item in rows}
        self.assertIn(("GET", "/api/v1/app/{id}/detail"), pairs)
        self.assertIn(("POST", "/api/v1/items/list/"), pairs)
        self.assertIn(("POST", "/api/v1/items/save/"), pairs)
        self.assertIn(("GET", "/api/v1/app/{id}/owner/"), pairs)
        self.assertTrue(any("保存项目" in item["ui_texts"] for item in rows))

    def test_labels_proxy_target_without_guessing_outer_post_method(self) -> None:
        source = 'proxy({body:{query_api:"/open_api/2/tools/list/",advertiser_id:id}})'
        rows = parse_text(source, file_info={"local_path": "raw/chunk.js", "url": "https://x/chunk.js"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["method"], "UNKNOWN")
        self.assertEqual(rows[0]["route_evidence_kind"], "proxy_query_api_value")

    def test_same_bundle_is_byte_deterministic(self) -> None:
        source = b'const q=p=>request({url:"/api/v1/search/list/",method:"POST",data:p});'
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "tmp") as temp:
            raw_dir = Path(temp)
            local = Path("raw/example.test/assets/chunk.js")
            target = raw_dir / local
            target.parent.mkdir(parents=True)
            target.write_bytes(source)
            files = [
                {
                    "url": "https://example.test/assets/chunk.js",
                    "local_path": local.as_posix(),
                    "sha256": sha256_bytes(source),
                    "size": len(source),
                    "references": [],
                }
            ]
            snapshot = {
                "site_url": "https://example.test/",
                "bundle_id": stable_bundle_id(files),
                "files": files,
                "summary": {"bundle_files": 1, "complete": True},
            }
            first = json_bytes(build_routes(snapshot, raw_dir))
            second = json_bytes(build_routes(snapshot, raw_dir))
            self.assertEqual(first, second)

    def test_resolves_esm_exported_base_url_and_type_method(self) -> None:
        api_source = (
            b'const host="https://api.example.test",base=`${host}/turbo_engine/api/v1`;'
            b'export{base as Vt};'
        )
        chunk_source = (
            b'import{Vt as B}from"./api-HASH.js";'
            b'const list=p=>request("/demo/list/",{type:"post",baseURL:B,body:p});'
        )
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "tmp") as temp:
            raw_dir = Path(temp)
            specs = [
                ("api-HASH.js", api_source),
                ("chunk-HASH.js", chunk_source),
            ]
            files = []
            for name, content in specs:
                local = Path("raw/example.test/assets") / name
                target = raw_dir / local
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                files.append(
                    {
                        "url": f"https://example.test/assets/{name}",
                        "local_path": local.as_posix(),
                        "sha256": sha256_bytes(content),
                        "size": len(content),
                        "references": [],
                    }
                )
            snapshot = {
                "site_url": "https://example.test/",
                "bundle_id": stable_bundle_id(files),
                "files": files,
                "summary": {"bundle_files": 2, "complete": True},
            }
            result = build_routes(snapshot, raw_dir)
            self.assertIn(
                ("POST", "/turbo_engine/api/v1/demo/list/"),
                {(item["method"], item["path"]) for item in result["routes"]},
            )


class GravityCensusCoverageTests(unittest.TestCase):
    def test_reconciles_stable_and_preserves_semantic_uncertainty(self) -> None:
        routes = {
            "source": {"bundle_id": "fixture", "bundle_complete": True},
            "routes": [
                {"method": "GET", "path": "/api/v1/apps/", "method_certainty": "high"},
                {"method": "POST", "path": "/api/v1/search/list/", "method_certainty": "medium"},
                {"method": "POST", "path": "/api/v1/item/save/", "method_certainty": "medium"},
                {"method": "POST", "path": "/api/v1/item/shared_to_me/list/", "method_certainty": "medium"},
                {"method": "POST", "path": "/api/v1/job/kill_query/", "method_certainty": "medium"},
                {"method": "POST", "path": "/api/v1/opaque/", "method_certainty": "low"},
                {"method": "GET", "path": "/api/v1/legacy/", "method_certainty": "high"},
            ],
        }
        operations = [
            {
                "operation_id": "app.list",
                "method": "GET",
                "path": "/api/v1/apps",
                "stability": "stable",
                "domain": "app",
                "platform": "",
                "manifest_file": "fixture.json",
            },
            {
                "operation_id": "legacy.get",
                "method": "GET",
                "path": "/api/v1/legacy/",
                "stability": "deprecated",
                "domain": "other",
                "platform": "",
                "manifest_file": "fixture.json",
            },
        ]
        result = build_coverage(routes, operations)
        by_path = {item["path"]: item for item in result["routes"]}
        self.assertEqual(by_path["/api/v1/apps/"]["status"], "covered")
        self.assertEqual(
            by_path["/api/v1/apps/"]["manifest_match_kind"], "normalization_equivalent_stable"
        )
        self.assertEqual(by_path["/api/v1/search/list/"]["status"], "uncovered_read")
        self.assertEqual(by_path["/api/v1/item/save/"]["status"], "uncovered_write")
        self.assertEqual(by_path["/api/v1/item/shared_to_me/list/"]["status"], "uncovered_read")
        self.assertEqual(by_path["/api/v1/job/kill_query/"]["status"], "uncovered_write")
        self.assertEqual(by_path["/api/v1/opaque/"]["status"], "unclassified")
        self.assertEqual(by_path["/api/v1/legacy/"]["manifest_match_kind"], "exact_nonstable")
        self.assertNotEqual(by_path["/api/v1/legacy/"]["status"], "covered")

    def test_reconciles_previous_chunk_normalization_and_absent_categories(self) -> None:
        baseline = {
            "routes": [{"method": "GET", "path": "/api/v1/already/"}],
        }
        routes = {
            "source": {"bundle_complete": True},
            "routes": [
                {"method": "GET", "path": "/api/v1/already/"},
                {"method": "GET", "path": "/api/v1/new/"},
                {"method": "GET", "path": "/api/v1/item/{item_id}/"},
            ],
        }
        operations = [
            {"operation_id": "already", "method": "GET", "path": "/api/v1/already/", "stability": "stable", "domain": "", "platform": "", "manifest_file": "x.json"},
            {"operation_id": "new", "method": "GET", "path": "/api/v1/new/", "stability": "stable", "domain": "", "platform": "", "manifest_file": "x.json"},
            {"operation_id": "normalized", "method": "GET", "path": "/api/v1/item/{id}", "stability": "stable", "domain": "", "platform": "", "manifest_file": "x.json"},
            {"operation_id": "absent", "method": "GET", "path": "/api/v1/absent/", "stability": "stable", "domain": "", "platform": "", "manifest_file": "x.json"},
        ]
        result = build_coverage(routes, operations, baseline)
        self.assertEqual(
            result["manifest_reconciliation"]["previously_missing_breakdown"],
            {
                "a_previously_unfetched_chunk": 1,
                "b_normalization_false_gap_fixed": 1,
                "c_manifest_route_absent_from_frontend": 1,
            },
        )

    def test_assigns_cross_platform_family_and_cost(self) -> None:
        routes = {
            "source": {"bundle_complete": True},
            "routes": [
                {"method": "POST", "path": "/turbo_engine/api/v1/tencent/report/campaign/list/"},
                {"method": "POST", "path": "/turbo_engine/api/v1/kuaishou/report/campaign/list/"},
            ],
        }
        result = build_coverage(routes, [])
        self.assertEqual(result["family_summary"]["uncovered_read_routes_with_family"], 2)
        self.assertEqual(result["family_summary"]["families"], 1)
        self.assertTrue(all(item["contract_family"] for item in result["routes"]))
        self.assertTrue(all(item["estimated_implementation_cost"] == "高" for item in result["routes"]))


class GravityCensusFetcherTests(unittest.TestCase):
    def test_budget_and_concurrency_allow_full_crawl_but_cap_workers(self) -> None:
        fetcher = StaticFetcher(max_requests=800, concurrency=4)
        self.assertEqual(fetcher.max_requests, 800)
        with self.assertRaises(ValueError):
            StaticFetcher(max_requests=800, concurrency=5)

    def test_distinguishes_vite_hash_chunk_from_package_source_literal(self) -> None:
        self.assertTrue(_looks_like_vite_chunk("https://example.test/assets/Account-BPRwXRfe.js"))
        self.assertFalse(_looks_like_vite_chunk("https://example.test/assets/core-js/modules/es.promise.js"))

    def test_lightweight_upstream_check_gets_html_once_and_records_cache_headers(self) -> None:
        html = b'<script type="module" src="/assets/index-NEW.js"></script>'
        response = SimpleNamespace(
            content=html,
            encoding="utf-8",
            url="https://example.test/",
            headers={"ETag": '"entry-v2"', "Last-Modified": "Sun, 09 Aug 2026 00:00:00 GMT"},
        )

        def fake_get(fetcher, url):
            self.assertEqual("https://example.test/", url)
            fetcher.attempts += 1
            return response

        with patch.object(StaticFetcher, "_get", fake_get):
            result = check_upstream(
                "https://example.test/",
                {
                    "entry_urls": ["https://example.test/assets/index-OLD.js"],
                    "html": {"sha256": "0" * 64},
                },
            )

        self.assertEqual(1, result["request_attempts"])
        self.assertTrue(result["upstream_changed"])
        self.assertEqual('"entry-v2"', result["etag"])
        self.assertEqual("Sun, 09 Aug 2026 00:00:00 GMT", result["last_modified"])


class GravityCensusDiffTests(unittest.TestCase):
    def test_route_diff_detects_method_and_path_changes(self) -> None:
        old = {
            "source": {"bundle_id": "old"},
            "routes": [
                {"method": "GET", "path": "/api/v1/same/"},
                {"method": "GET", "path": "/api/v1/method/"},
                {"method": "POST", "path": "/api/v1/item/detail/"},
                {"method": "GET", "path": "/api/v1/removed/"},
            ],
        }
        new = {
            "source": {"bundle_id": "new"},
            "routes": [
                {"method": "GET", "path": "/api/v1/same/"},
                {"method": "POST", "path": "/api/v1/method/"},
                {"method": "POST", "path": "/api/v2/item/detail/"},
                {"method": "GET", "path": "/api/v1/added/"},
            ],
        }
        result = diff_routes(old, new)
        self.assertEqual(result["summary"], {"added": 1, "removed": 1, "method_changed": 1, "path_changed": 1})
        self.assertEqual(result["method_changes"][0]["path"], "/api/v1/method/")
        self.assertEqual(result["path_changes"][0]["new_path"], "/api/v2/item/detail/")


if __name__ == "__main__":
    unittest.main()
