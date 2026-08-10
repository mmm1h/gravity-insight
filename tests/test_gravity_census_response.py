from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gravity_sdk.census.io import json_bytes, read_json, sha256_bytes, write_json
from gravity_sdk.census.parser import build_routes
from gravity_sdk.census.response import (
    apply_response_fields_to_drafts,
    build_route_response_fields,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _bundle(raw_dir: Path, source: bytes) -> dict:
    local = Path("raw/example.test/assets/fixture-HASH.js")
    target = raw_dir / local
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source)
    return {
        "site_url": "https://example.test/",
        "bundle_id": "fixture",
        "files": [
            {
                "url": "https://example.test/assets/fixture-HASH.js",
                "local_path": local.as_posix(),
                "sha256": sha256_bytes(source),
                "size": len(source),
                "references": [],
            }
        ],
        "summary": {"bundle_files": 1, "complete": True},
    }


class GravityCensusResponseTests(unittest.TestCase):
    def test_extracts_only_fields_bound_to_exact_route_without_literal_values(self) -> None:
        source = (
            b'const marker="DO_NOT_PERSIST_VALUE";'
            b'function setup(){'
            b'let{load:run,data:response}=use("/api/v1/items/list/",{type:"get"});'
            b'const rows=response.value?.list.map(item=>({id:item.id,name:item.name}));'
            b'const pages=response.value?.page_info?.total_page;'
            b'return{rows,pages,run}}'
        )
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "tmp") as temp:
            raw_dir = Path(temp)
            snapshot = _bundle(raw_dir, source)
            routes = build_routes(snapshot, raw_dir)

            result = build_route_response_fields(snapshot, routes, raw_dir)

        route = next(
            item for item in result["routes"] if item["path"] == "/api/v1/items/list/"
        )
        by_path = {item["path"]: item for item in route["fields"]}
        self.assertEqual(
            set(by_path),
            {
                "data.list",
                "data.list[].id",
                "data.list[].name",
                "data.page_info.total_page",
            },
        )
        self.assertEqual(by_path["data.list"]["confidence"], "high")
        self.assertEqual(by_path["data.list[].id"]["confidence"], "medium")
        self.assertEqual(
            by_path["data.list[].id"]["evidence"][0]["consumer_kind"],
            "iterated_item_member",
        )
        self.assertNotIn(b"DO_NOT_PERSIST_VALUE", json_bytes(result))
        self.assertFalse(result["extractor"]["literal_values_persisted"])

    def test_does_not_mix_response_bindings_from_two_routes_in_one_scope(self) -> None:
        source = (
            b'function setup(){'
            b'let{data:firstResponse}=use("/api/v1/first/",{type:"get"});'
            b'let{data:secondResponse}=use("/api/v1/second/",{type:"get"});'
            b'const first=firstResponse.value?.list.map(row=>row.first_id);'
            b'const second=secondResponse.value?.list.map(row=>row.second_id);'
            b'return{first,second}}'
        )
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "tmp") as temp:
            raw_dir = Path(temp)
            snapshot = _bundle(raw_dir, source)
            routes = build_routes(snapshot, raw_dir)

            result = build_route_response_fields(snapshot, routes, raw_dir)

        by_route = {
            item["path"]: {field["path"] for field in item["fields"]}
            for item in result["routes"]
        }
        self.assertIn("data.list[].first_id", by_route["/api/v1/first/"])
        self.assertNotIn("data.list[].second_id", by_route["/api/v1/first/"])
        self.assertIn("data.list[].second_id", by_route["/api/v1/second/"])
        self.assertNotIn("data.list[].first_id", by_route["/api/v1/second/"])

    def test_apply_is_fail_closed_and_preserves_probe_candidates_and_projection(self) -> None:
        response_document = {
        "routes": [
            {
                "method": "GET",
                "path": "/api/v1/items/",
                "fields": [
                    {"path": "data.list", "confidence": "high", "evidence": []},
                    {"path": "data.list[].id", "confidence": "medium", "evidence": []},
                    {"path": "data.list[].name", "confidence": "medium", "evidence": []},
                ],
            }
        ]
    }
        draft = {
        "operation": {
            "operation_id": "fixture.list",
            "upstream_method": "GET",
            "path_template": "/api/v1/items/",
            "response_projection": {"item_keys": [], "data_keys": []},
        },
        "draft": {
            "candidate_fields": [
                {
                    "path": "data.list[].id",
                    "types": ["integer"],
                    "presence": "observed",
                    "privacy_classification": "non_sensitive",
                    "classification_reason": "probe",
                    "expose": True,
                }
            ],
            "blockers": [
                {
                    "code": "response_schema_unverified",
                    "status": "open",
                    "detail": "unverified",
                    "evidence": "probe.json",
                }
            ],
        },
    }
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "tmp") as temp:
            drafts_root = Path(temp)
            draft_path = drafts_root / "fixture.list.json"
            write_json(draft_path, draft)

            summary = apply_response_fields_to_drafts(response_document, drafts_root)
            updated = read_json(draft_path)
            second_summary = apply_response_fields_to_drafts(
                response_document, drafts_root
            )

        candidates = {
            item["path"]: item for item in updated["draft"]["candidate_fields"]
        }
        self.assertEqual(candidates["data.list[].id"]["types"], ["integer"])
        self.assertTrue(candidates["data.list[].id"]["expose"])
        self.assertEqual(
            candidates["data.list[].name"],
            {
                "path": "data.list[].name",
                "types": ["unknown"],
                "presence": "unknown",
                "privacy_classification": "manual_review",
                "classification_reason": "frontend_static_consumer_unreviewed",
                "expose": False,
            },
        )
        self.assertNotIn("data.list", candidates)
        self.assertEqual(
            updated["operation"]["response_projection"],
            {"item_keys": [], "data_keys": []},
        )
        self.assertEqual(updated["draft"]["blockers"][0]["status"], "open")
        self.assertTrue(
            updated["draft"]["blockers"][0]["evidence"].endswith("#/routes/0")
        )
        self.assertEqual(summary["blockers_advanced_by_static_plus_probe"], 0)
        self.assertEqual(second_summary["files_changed"], 0)
        self.assertEqual(second_summary["candidate_fields_added"], 0)


if __name__ == "__main__":
    unittest.main()
