from __future__ import annotations

import io, json, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gravity_insight.adaptive_governor_contract import GovernorRequestError
from gravity_insight.census.cli import _coverage_summary, _exception_failure, build_parser, main, run
from gravity_insight.census.coverage import build_coverage
from gravity_insight.census.diffing import CensusFailureClass, diff_routes
from gravity_insight.census.fetcher import StaticFetcher, _FetchError, _looks_like_vite_chunk, check_upstream
from gravity_insight.census.impact import locate_route_impacts; from gravity_insight.census.io import json_bytes, sha256_bytes, stable_bundle_id
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
            "source": {"bundle_id": "old", "bundle_complete": True},
            "routes": [
                {"method": "GET", "path": "/api/v1/same/"},
                {"method": "GET", "path": "/api/v1/method/"},
                {"method": "POST", "path": "/api/v1/item/detail/"},
                {"method": "GET", "path": "/api/v1/removed/"},
            ],
        }
        new = {
            "source": {"bundle_id": "new", "bundle_complete": True},
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
            "source": {"bundle_complete": True},
            "routes": [
                {"method": "GET", "path": "/api/v1/team/a/items/"},
                {"method": "GET", "path": "/api/v1/team/b/items/"},
            ]
        }
        new = {
            "source": {"bundle_complete": True},
            "routes": [{"method": "GET", "path": "/api/v1/team/a2/items/"}]
        }

        result = diff_routes(old, new)

        self.assertEqual(1, result["summary"]["path_changed"])
        self.assertEqual(1, result["summary"]["removed"])
        self.assertEqual("/api/v1/team/a/items/", result["path_changes"][0]["old_path"])


class GravityCensusCircuitFailureTests(unittest.TestCase):
    def test_fetch_parser_accepts_sanitized_failure_output(self) -> None:
        args = build_parser().parse_args(
            ["fetch", "--failure-output", "tmp/census-failure.json"]
        )
        self.assertEqual(
            REPO_ROOT / "tmp" / "census-failure.json", args.failure_output
        )

    def test_classifies_upstream_capacity_from_http_429(self) -> None:
        payload = _exception_failure(
            _FetchError(
                "rate limited",
                url="https://example.test/a.js",
                status_code=429,
                status_class="rate_limited",
            )
        )
        self.assertEqual(
            CensusFailureClass.UPSTREAM_CAPACITY.value, payload["failure_class"]
        )

    def test_classifies_local_governor_capacity_without_upstream_disguise(self) -> None:
        error = GovernorRequestError(
            "local queue full",
            code="GOVERNOR_BACKPRESSURE",
            diagnostics={
                "failure_class": "local_governor_capacity",
                "classification_reason": "process_governor_capacity_denied_before_network",
                "source_code": "GOVERNOR_BACKPRESSURE",
            },
        )
        payload = _exception_failure(error)
        self.assertEqual(
            CensusFailureClass.LOCAL_GOVERNOR_CAPACITY.value,
            payload["failure_class"],
        )
        self.assertEqual("local", payload["category"])
        self.assertNotEqual("upstream", payload["category"])
        self.assertNotEqual("upstream_capacity", payload["failure_class"])

    def test_classifies_request_budget_exhausted(self) -> None:
        payload = _exception_failure(
            _FetchError(
                "budget exhausted",
                url="https://example.test/a.js",
                status_class="request_budget_exhausted",
                request_attempts=12,
                request_limit=12,
            )
        )
        self.assertEqual(
            CensusFailureClass.REQUEST_BUDGET_EXHAUSTED.value,
            payload["failure_class"],
        )
        self.assertEqual(
            {"used": 12, "limit": 12, "remaining": 0},
            payload["request_budget"],
        )

    def test_classifies_transport_failure(self) -> None:
        payload = _exception_failure(
            _FetchError(
                "transport failed",
                url="https://example.test/a.js",
                status_class="transport_error",
                exception_type="ConnectTimeout",
            )
        )
        self.assertEqual(
            CensusFailureClass.TRANSPORT_FAILURE.value, payload["failure_class"]
        )

    def test_classifies_http_client_error(self) -> None:
        payload = _exception_failure(
            _FetchError(
                "client error",
                url="https://example.test/a.js",
                status_code=403,
                status_class="client_error",
            )
        )
        self.assertEqual(
            CensusFailureClass.HTTP_CLIENT_ERROR.value, payload["failure_class"]
        )

    def test_classifies_http_server_error(self) -> None:
        payload = _exception_failure(
            _FetchError(
                "server error",
                url="https://example.test/a.js",
                status_code=503,
                status_class="server_error",
            )
        )
        self.assertEqual(
            CensusFailureClass.HTTP_SERVER_ERROR.value, payload["failure_class"]
        )

    def test_classifies_content_incomplete(self) -> None:
        payload = _exception_failure(
            _FetchError(
                "content incomplete",
                url="https://example.test/a.js",
                status_class="content_incomplete",
            )
        )
        self.assertEqual(
            CensusFailureClass.CONTENT_INCOMPLETE.value, payload["failure_class"]
        )

    def test_classifies_unclassified_with_diagnostics(self) -> None:
        payload = _exception_failure(RuntimeError("raw detail is not rendered"))
        self.assertEqual(
            CensusFailureClass.UNCLASSIFIED.value, payload["failure_class"]
        )
        self.assertEqual(
            "exception_has_no_known_status_class_mapping",
            payload["classification"]["reason"],
        )
        self.assertEqual("RuntimeError", payload["classification"]["exception_type"])
        self.assertEqual("unknown", payload["classification"]["source_status_class"])

    def test_rate_limit_response_consumes_the_three_attempt_retry_budget(self) -> None:
        request_globals = StaticFetcher.__dict__["_get"].__globals__
        requests_module = request_globals["requests"]
        response = SimpleNamespace(status_code=429)

        def reject() -> None:
            raise requests_module.HTTPError("rate limited", response=response)

        response.raise_for_status = reject
        calls: list[int] = []
        sleeps: list[float] = []

        def fake_request(*_args, **_kwargs):
            calls.append(1)
            return response

        original_request = request_globals["perform_http_request"]
        original_time = request_globals["time"]
        fetcher = StaticFetcher(max_attempts=3, max_requests=3)
        fetcher._session = lambda: SimpleNamespace(get=fake_request)
        try:
            request_globals["perform_http_request"] = fake_request
            request_globals["time"] = SimpleNamespace(sleep=sleeps.append)
            with self.assertRaises(_FetchError) as raised:
                fetcher._get("https://example.test/bundle.js?signature=private")
        finally:
            request_globals["perform_http_request"] = original_request
            request_globals["time"] = original_time

        self.assertEqual(3, len(calls))
        self.assertEqual([0.25, 0.5], sleeps)
        self.assertEqual("rate_limited", raised.exception.status_class)
        self.assertEqual(429, raised.exception.status_code)
        self.assertNotIn("signature=private", str(raised.exception))

    def test_local_capacity_has_its_own_retry_limit_and_backoff(self) -> None:
        response = SimpleNamespace(
            status_code=200,
            raise_for_status=lambda: None,
        )
        calls: list[int] = []
        sleeps: list[float] = []

        class LocalCapacityGovernor:
            def execute(self, _descriptor, function):
                calls.append(1)
                if len(calls) < 3:
                    raise GovernorRequestError(
                        "queue full",
                        code="GOVERNOR_BACKPRESSURE",
                        diagnostics={
                            "failure_class": "local_governor_capacity",
                            "classification_reason": "process_governor_capacity_denied_before_network",
                        },
                    )
                return function()

        fetcher = StaticFetcher(
            max_attempts=1,
            max_requests=1,
            local_capacity_retries=2,
        )
        fetcher._session = lambda: SimpleNamespace(get=lambda *_args, **_kwargs: response)
        with (
            patch(
                "gravity_insight.adaptive_governor.get_process_governor",
                return_value=LocalCapacityGovernor(),
            ),
            patch("gravity_insight.http_attempt.time.sleep", side_effect=sleeps.append),
        ):
            self.assertIs(response, fetcher._get("https://example.test/a.js"))

        self.assertEqual(3, len(calls))
        self.assertEqual([0.05, 0.1], sleeps)
        self.assertEqual(1, fetcher.attempts)
        self.assertEqual(2, fetcher.local_capacity_retries_used)

    def test_non_capacity_governor_error_is_not_retried_as_capacity(self) -> None:
        calls: list[int] = []
        sleeps: list[float] = []

        class CancelledGovernor:
            def execute(self, _descriptor, _function):
                calls.append(1)
                raise GovernorRequestError(
                    "cancelled",
                    code="GOVERNOR_CANCELLED",
                    diagnostics={
                        "failure_class": "unclassified",
                        "classification_reason": "non_capacity_governor_rejection",
                    },
                )

        fetcher = StaticFetcher(max_attempts=3, local_capacity_retries=2)
        with (
            patch(
                "gravity_insight.adaptive_governor.get_process_governor",
                return_value=CancelledGovernor(),
            ),
            patch("gravity_insight.http_attempt.time.sleep", side_effect=sleeps.append),
        ):
            with self.assertRaises(GovernorRequestError):
                fetcher._get("https://example.test/a.js")

        self.assertEqual(1, len(calls))
        self.assertEqual([], sleeps)
        self.assertEqual(0, fetcher.attempts)

    def test_http_200_empty_or_html_body_does_not_prove_js_content_complete(self) -> None:
        for body, content_type in (
            (b"", "application/javascript"),
            (b"<!doctype html><title>gateway</title>", "text/html"),
        ):
            with self.subTest(content_type=content_type, size=len(body)):
                with self.assertRaises(_FetchError) as raised:
                    StaticFetcher._validate_js_content(
                        body, "https://example.test/a.js", content_type
                    )
                self.assertEqual("content_incomplete", raised.exception.status_class)

    def test_incomplete_failure_classification_is_capacity_only_when_all_causes_are(self) -> None:
        private_query = "QUERY_VALUE_SENTINEL_81"
        result = {
            "summary": {
                "complete": False,
                "request_attempts": 3,
                "pending_js": 1,
                "failed_js": 1,
            },
            "discovery": {
                "failures": [
                    {
                        "url": f"https://example.test/a.js?token={private_query}",
                        "host": "example.test",
                        "status_class": "rate_limited",
                        "status_code": 429,
                        "exception_type": None,
                        "error": private_query,
                    }
                ]
            },
        }
        classify = run.__globals__["_incomplete_fetch_failure"]
        capacity = classify(result)
        self.assertEqual("upstream_capacity", capacity["failure_class"])
        self.assertEqual("CENSUS_UPSTREAM_CAPACITY", capacity["code"])
        self.assertTrue(capacity["retryable"])
        self.assertNotIn(private_query, str(capacity))

        result["discovery"]["failures"].append(
            {
                "host": "example.test",
                "status_class": "client_error",
                "status_code": 404,
            }
        )
        incomplete = classify(result)
        self.assertEqual("unclassified", incomplete["failure_class"])
        self.assertFalse(incomplete["retryable"])
        self.assertIn(
            "mixed_failure_classes",
            incomplete["classification"]["reason"],
        )

    def test_partial_routes_withhold_diff_impact_and_probe_plan(self) -> None:
        old = {
            "source": {"bundle_id": "old", "bundle_complete": True},
            "routes": [{"method": "GET", "path": "/api/v1/a/"}],
        }
        partial = {
            "source": {"bundle_id": "partial", "bundle_complete": False},
            "routes": [],
        }
        route_diff = diff_routes(old, partial)
        self.assertFalse(route_diff["drift_conclusion_available"])
        self.assertEqual("content_incomplete", route_diff["failure_class"])
        self.assertEqual([], route_diff["removed"])
        self.assertIsNone(route_diff["summary"]["removed"])

        impact = locate_route_impacts(
            route_diff,
            {},
            REPO_ROOT / "src" / "gravity_insight" / "contracts",
            census_complete=True,
        )
        self.assertFalse(impact["impact_conclusion_available"])
        self.assertEqual([], impact["operations"])
        self.assertEqual("withheld", impact["probe_plan"]["status"])
        self.assertEqual([], impact["probe_plan"]["commands"])

    def test_fetch_failure_path_always_writes_parseable_step_output(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "tmp") as temporary:
            root = Path(temporary)
            step_output = root / "step-output.json"
            failure_output = root / "failure.json"
            fake_stderr = SimpleNamespace(buffer=io.BytesIO())
            with (
                patch(
                    "gravity_insight.census.cli.StaticFetcher.fetch",
                    side_effect=RuntimeError("boom"),
                ),
                patch("gravity_insight.cli_stdio.configure_utf8_stdio"),
                patch("gravity_insight.census.cli.sys.stderr", fake_stderr),
            ):
                exit_code = main(
                    [
                        "fetch",
                        "--raw-dir",
                        str(root / "raw"),
                        "--output",
                        str(root / "snapshot.json"),
                        "--require-complete",
                        "--failure-output",
                        str(failure_output),
                        "--step-output",
                        str(step_output),
                    ]
                )

            self.assertNotEqual(0, exit_code)
            step = json.loads(step_output.read_text(encoding="utf-8"))
            failure = json.loads(failure_output.read_text(encoding="utf-8"))
            self.assertEqual("gravity-census.step-output.v1", step["schema_version"])
            self.assertEqual("error", step["status"])
            self.assertFalse(step["complete"])
            self.assertEqual("unclassified", step["failure_class"])
            self.assertEqual(failure, step["failure"])

    def test_success_step_output_binds_snapshot_time_and_bundle(self) -> None:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "tmp") as temporary:
            target = Path(temporary) / "step-output.json"
            snapshot = {
                "fetched_at": "2026-09-03T01:16:26+00:00",
                "bundle_id": "1" * 64,
                "summary": {
                    "complete": True,
                    "request_attempts": 513,
                    "request_limit": 800,
                },
            }
            run.__globals__["_write_fetch_step"](
                SimpleNamespace(step_output=target), snapshot, None
            )
            step = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(snapshot["fetched_at"], step["observed_at"])
        self.assertEqual(snapshot["bundle_id"], step["bundle_id"])
        self.assertEqual(snapshot["summary"], step["summary"])

    def test_governor_exception_renders_machine_decidable_census_error(self) -> None:
        error = RuntimeError("safe circuit error")
        error.code = "GOVERNOR_CIRCUIT_OPEN"
        error.next_action = "Wait 30000 ms, then retry the same host once."
        error.diagnostics = {
            "failure_class": "http_server_error",
            "classification_reason": "circuit_opened_by_http_5xx",
            "lane": {"host": "example.test"},
            "failures": [
                {"status_class": "server_error", "http_status": 503}
            ],
            "cooldown_remaining_ms": 30_000,
        }
        payload = run.__globals__["_exception_failure"](error)
        self.assertEqual("CENSUS_HTTP_SERVER_ERROR", payload["code"])
        self.assertEqual("http_server_error", payload["failure_class"])
        self.assertEqual(
            "GOVERNOR_CIRCUIT_OPEN", payload["classification"]["source_code"]
        )
        self.assertEqual("example.test", payload["lane"]["host"])
        self.assertEqual(503, payload["failures"][0]["http_status"])
        self.assertIn("retry the same host once", payload["next_action"])

    def test_hourly_workflow_retries_capacity_and_fails_closed_other_causes(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "upstream-census.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("$attemptLimit = 3", workflow)
        self.assertIn(
            "--max-attempts 1 --local-capacity-retries 2", workflow
        )
        self.assertIn("--step-output $stepResult", workflow)
        self.assertIn("gravity-census.step-output.v1", workflow)
        self.assertIn('cron: "47 1 * * *"', workflow)
        self.assertIn("full_required=", workflow)
        self.assertIn("Verify current scoring evidence", workflow)
        self.assertIn("max_age_seconds -ne 93600", workflow)
        self.assertIn("gravity-census-current-${{ github.run_id }}", workflow)
        self.assertIn(
            "workflow_attempt_started_without_terminal_cli_output", workflow
        )
        self.assertIn("ConvertFrom-Json -ErrorAction Stop", workflow)
        self.assertIn("Start-Sleep -Seconds $delaySeconds", workflow)
        self.assertIn(
            "steps.upstream.outputs.full_required == 'true'", workflow
        )
        self.assertIn(
            "steps.fetch.outputs.failure_class != 'upstream_capacity'", workflow
        )
        self.assertIn("No route-drift conclusion was made", workflow)
        self.assertNotIn("--concurrency 5", workflow)


if __name__ == "__main__":
    unittest.main()
