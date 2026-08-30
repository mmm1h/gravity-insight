from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gravity_insight.census.cli import _coverage_summary, build_parser, run
from gravity_insight.census.coverage import build_coverage
from gravity_insight.census.diffing import diff_routes
from gravity_insight.census.fetcher import StaticFetcher, _FetchError, _looks_like_vite_chunk, check_upstream
from gravity_insight.census.io import json_bytes, sha256_bytes, stable_bundle_id
from gravity_insight.census.normalize import comparison_path, normalize_path
from gravity_insight.census.parser import build_routes, parse_text


REPO_ROOT = Path(__file__).resolve().parents[1]


class GravityCensusCliTests(unittest.TestCase):
    def test_nested_help_keeps_the_copyable_census_prefix(self) -> None:
        parser = build_parser()
        self.assertTrue(parser.format_usage().startswith("usage: gravity census"))
        coverage = parser.parse_args(["coverage"])
        self.assertEqual("coverage", coverage.command)
        summary = _coverage_summary({"summary": {"total_routes": 987}, "source": {"coverage_scope": "same_origin_static_js_graph_discoverable_from_site_entry", "platform_complete": False, "known_excluded_origins": ["rank.gravity-engine.com"]}})
        self.assertEqual((summary["total_routes"], summary["coverage_scope"], summary["platform_complete"], summary["known_excluded_origins"]), (987, "same_origin_static_js_graph_discoverable_from_site_entry", False, ["rank.gravity-engine.com"]))

    def test_run_dispatches_to_the_selected_command_handler(self) -> None:
        expected = ({"unique_method_path": 2}, 0)
        args = SimpleNamespace(smoke=False, command="parse")
        with patch("gravity_insight.census.cli._run_parse", return_value=expected) as handler:
            self.assertEqual(expected, run(args))
        handler.assert_called_once_with(args)


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
            first = json_bytes(first_document := build_routes(snapshot, raw_dir))
            second = json_bytes(build_routes(snapshot, raw_dir))
            self.assertEqual(first, second)
            source = first_document["source"]
            self.assertEqual((source["coverage_scope"], source["platform_complete"], source["known_excluded_origins"]), ("same_origin_static_js_graph_discoverable_from_site_entry", False, ["rank.gravity-engine.com"]))

    def test_build_routes_records_missing_bundle_files_without_aborting(self) -> None:
        snapshot = {
            "site_url": "https://example.test/",
            "bundle_id": "missing-fixture",
            "files": [
                {
                    "url": "https://example.test/assets/missing.js",
                    "local_path": "raw/example.test/assets/missing.js",
                }
            ],
            "summary": {"bundle_files": 1, "complete": False},
        }
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "tmp") as temp:
            result = build_routes(snapshot, Path(temp))

        self.assertEqual([], result["routes"])
        self.assertEqual(
            ["raw/example.test/assets/missing.js"],
            result["source"]["missing_local_files"],
        )

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
                {"method": "UNKNOWN", "path": "/api/v1/lookup/list/", "method_certainty": "low"},
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
        confirmed = {("POST", "/api/v1/item/shared_to_me/list/")}
        result = build_coverage(
            routes, operations, confirmed_read_routes=confirmed
        )
        by_path = {item["path"]: item for item in result["routes"]}
        self.assertEqual(by_path["/api/v1/apps/"]["status"], "covered")
        self.assertEqual(
            by_path["/api/v1/apps/"]["manifest_match_kind"], "normalization_equivalent_stable"
        )
        self.assertEqual(by_path["/api/v1/search/list/"]["status"], "unsafe_unknown")
        self.assertEqual(
            by_path["/api/v1/search/list/"]["route_accounting"],
            "accounted_unsafe_unknown",
        )
        self.assertEqual(by_path["/api/v1/item/save/"]["status"], "uncovered_write")
        self.assertEqual(by_path["/api/v1/item/shared_to_me/list/"]["status"], "uncovered_read")
        self.assertIn(
            "probe_read_confirmation",
            by_path["/api/v1/item/shared_to_me/list/"]["semantic_evidence"],
        )
        self.assertEqual(by_path["/api/v1/job/kill_query/"]["status"], "uncovered_write")
        self.assertEqual(
            by_path["/api/v1/lookup/list/"]["status"], "static_read_candidate"
        )
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
        confirmed = {
            ("POST", "/turbo_engine/api/v1/tencent/report/campaign/list/"),
            ("POST", "/turbo_engine/api/v1/kuaishou/report/campaign/list/"),
        }
        result = build_coverage(routes, [], confirmed_read_routes=confirmed)
        self.assertEqual(result["family_summary"]["uncovered_read_routes_with_family"], 2)
        self.assertEqual(result["family_summary"]["families"], 1)
        self.assertTrue(all(item["contract_family"] for item in result["routes"]))
        self.assertTrue(all(item["estimated_implementation_cost"] == "高" for item in result["routes"]))

    def test_wechat_video_report_is_classified_as_a_promotion_platform(self) -> None:
        routes = {
            "source": {"bundle_complete": True},
            "routes": [
                {
                    "method": "POST",
                    "path": "/turbo_engine/api/v1/wechat_video/report/list/",
                }
            ],
        }

        result = build_coverage(routes, [])

        route = result["routes"][0]
        self.assertEqual("推广平台", route["business_module"])
        self.assertEqual("wechat_video", route["promotion_platform"])
        self.assertEqual("报表", route["promotion_level"])


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

    def test_fetch_crawls_manifest_and_recursive_references_without_network(self) -> None:
        html = (
            b'<link rel="manifest" href="/manifest.json">'
            b'<script type="module" src="/assets/index-ABCDEFGH.js"></script>'
        )
        responses = {
            "https://example.test/": SimpleNamespace(
                content=html, encoding="utf-8", url="https://example.test/", headers={}
            ),
            "https://example.test/manifest.json": SimpleNamespace(
                content=b"{}", encoding="utf-8", url="https://example.test/manifest.json",
                headers={"Content-Type": "application/json"},
                json=lambda: {"entry": {"file": "assets/manifest-ABCDEFGH.js"}},
            ),
            "https://example.test/assets/index-ABCDEFGH.js": SimpleNamespace(
                content=(b'import "./chunk-ABCDEFGH.js";import "./core-js/modules/es.promise.js";'
                         b'import "https://cdn.test/external-ABCDEFGH.js";'),
                encoding="utf-8", url="https://example.test/assets/index-ABCDEFGH.js",
            ),
            "https://example.test/assets/chunk-ABCDEFGH.js": SimpleNamespace(
                content=b"export const value=1", encoding="utf-8",
                url="https://example.test/assets/chunk-ABCDEFGH.js",
            ),
            "https://example.test/assets/manifest-ABCDEFGH.js": SimpleNamespace(
                content=b"export const manifest=1", encoding="utf-8",
                url="https://example.test/assets/manifest-ABCDEFGH.js",
            ),
        }

        class FakeFetcher(StaticFetcher):
            def _get(self, url):
                self._reserve_attempt()
                if url.endswith("/core-js/modules/es.promise.js"):
                    raise _FetchError("missing lexical candidate", url=url, status_code=404)
                return responses[url]

        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "tmp") as temp:
            root = Path(temp)
            fetcher = FakeFetcher(max_requests=20, concurrency=2)
            result = fetcher.fetch(
                site_url="https://example.test", raw_dir=root,
                snapshot_path=root / "snapshot.json", probe_manifests=False,
            )
            self.assertTrue(result["summary"]["complete"])
            self.assertEqual(3, result["summary"]["bundle_files"])
            self.assertEqual(1, result["summary"]["rejected_non_resource_candidates"])
            self.assertEqual(
                ["https://cdn.test/external-ABCDEFGH.js"],
                result["discovery"]["ignored_cross_origin_js"],
            )
            self.assertTrue((root / "snapshot.json").is_file())

    def test_fetch_marks_snapshot_incomplete_when_entry_changes(self) -> None:
        initial = b'<script type="module" src="/assets/index-ABCDEFGH.js"></script>'
        changed = b'<script type="module" src="/assets/index-IJKLMNOP.js"></script>'
        entry_calls = 0

        class ChangingEntryFetcher(StaticFetcher):
            def _get(self, url):
                nonlocal entry_calls
                self._reserve_attempt()
                if url == "https://example.test/":
                    entry_calls += 1
                    content = initial if entry_calls == 1 else changed
                    return SimpleNamespace(
                        content=content, encoding="utf-8", url=url, headers={}
                    )
                return SimpleNamespace(content=b"export{}", encoding="utf-8", url=url)

        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "tmp") as temp:
            root = Path(temp)
            result = ChangingEntryFetcher(max_requests=10).fetch(
                site_url="https://example.test/", raw_dir=root,
                snapshot_path=root / "snapshot.json", probe_manifests=False,
            )
        self.assertFalse(result["summary"]["complete"])
        self.assertEqual(
            "entry HTML changed while static graph was being fetched",
            result["discovery"]["failures"][0]["error"],
        )


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

    def test_path_change_matching_uses_each_route_at_most_once(self) -> None:
        old = {
            "routes": [
                {"method": "GET", "path": "/api/v1/team/a/items/"},
                {"method": "GET", "path": "/api/v1/team/b/items/"},
            ]
        }
        new = {
            "routes": [{"method": "GET", "path": "/api/v1/team/a2/items/"}]
        }

        result = diff_routes(old, new)

        self.assertEqual(1, result["summary"]["path_changed"])
        self.assertEqual(1, result["summary"]["removed"])
        self.assertEqual("/api/v1/team/a/items/", result["path_changes"][0]["old_path"])


if __name__ == "__main__":
    unittest.main()
