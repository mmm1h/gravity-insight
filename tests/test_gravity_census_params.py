from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gravity_sdk.census.io import json_bytes, sha256_bytes, stable_bundle_id
from gravity_sdk.census.params import build_route_params
from gravity_sdk.census.parser import _tokenize, build_routes


REPO_ROOT = Path(__file__).resolve().parents[1]


class GravityCensusParameterTests(unittest.TestCase):
    def _build(self, source: bytes) -> dict:
        with tempfile.TemporaryDirectory(dir=REPO_ROOT / "tmp") as directory:
            raw_dir = Path(directory)
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
            routes = build_routes(snapshot, raw_dir)
            return build_route_params(snapshot, routes, raw_dir, repo_root=REPO_ROOT)

    def test_extracts_body_query_nested_array_defaults_and_conditional_fields(self) -> None:
        result = self._build(
            b'const{load:list}=request("/api/v1/items/list/",{type:"post"});'
            b'function run(e,flag){return list({query:{page:e.page||1},body:{app_id:e.id,'
            b'nested:{mode:"active",rows:[{id:1,label:"first"}]},'
            b'...(flag?{cursor:e.cursor}:{})}})}'
        )
        route = result["routes"][0]
        self.assertEqual("extracted", route["status"])
        query = {item["name"]: item for item in route["query_parameters"]}
        body = {item["name"]: item for item in route["body_parameters"]}
        self.assertEqual(1, query["page"]["default"])
        self.assertEqual("observed_always", query["page"]["required"])
        self.assertEqual("observed_conditional", body["cursor"]["required"])
        self.assertIn("conditional_spread", body["cursor"]["evidence"])
        nested = {item["name"]: item for item in body["nested"]["properties"]}
        self.assertEqual("active", nested["mode"]["default"])
        rows = nested["rows"]["items"]
        self.assertEqual(["object"], rows["types"])
        self.assertEqual(
            ["id", "label"],
            [item["name"] for item in rows["properties"]],
        )

    def test_maps_get_body_to_query_and_preserves_path_parameter(self) -> None:
        result = self._build(
            b'const{load:get}=request(`/api/v1/app/${appId}/detail/`,{type:"get"});'
            b'get({body:{company_id:companyId,enabled:!0}});'
        )
        route = result["routes"][0]
        self.assertEqual(["appId"], [item["name"] for item in route["path_parameters"]])
        query = {item["name"]: item for item in route["query_parameters"]}
        self.assertEqual({"company_id", "enabled"}, set(query))
        self.assertIs(query["enabled"]["default"], True)
        self.assertEqual([], route["body_parameters"])

    def test_query_template_is_not_misclassified_as_path_parameter(self) -> None:
        result = self._build(
            b'const{load:get}=request(`/api/v1/static/?origin=${origin}`,{type:"get"});get();'
        )
        route = result["routes"][0]
        self.assertEqual([], route["path_parameters"])
        self.assertEqual(["origin"], [item["name"] for item in route["query_parameters"]])

    def test_does_not_guess_keys_for_opaque_runtime_payload(self) -> None:
        result = self._build(
            b'const{load:list}=request("/api/v1/opaque/list/",{type:"post"});'
            b'const invoke=payload=>list({body:payload});'
        )
        route = result["routes"][0]
        self.assertEqual("unknown", route["status"])
        self.assertEqual([], route["body_parameters"])
        self.assertGreater(route["analysis"]["unresolved_calls"], 0)

    def test_follows_conditional_loader_alias_at_medium_confidence(self) -> None:
        result = self._build(
            b'const{load:left}=request("/api/v1/left/",{type:"post"}),'
            b'{load:right}=request("/api/v1/right/",{type:"post"});'
            b'function run(flag){let selected=flag?left:right;selected({body:{page:1,filters:[]}})}'
        )
        for route in result["routes"]:
            body = {item["name"]: item for item in route["body_parameters"]}
            self.assertEqual({"filters", "page"}, set(body))
            self.assertTrue(all(item["confidence"] == "medium" for item in body.values()))

    def test_variable_inference_selects_member_instead_of_whole_object(self) -> None:
        result = self._build(
            b'const state=reactive({page:1,nested:{id:"fixture"}}),'
            b'{load:list}=request("/api/v1/member/list/",{type:"post"});'
            b'list({body:{page:state.page,id:state.nested.id}});'
        )
        body = {item["name"]: item for item in result["routes"][0]["body_parameters"]}
        self.assertEqual(["integer"], body["page"]["types"])
        self.assertEqual(["string"], body["id"]["types"])
        self.assertNotIn("properties", body["page"])
        self.assertNotIn("properties", body["id"])

    def test_infers_conversion_array_method_signed_literal_and_void(self) -> None:
        result = self._build(
            b'const{load:list}=request("/api/v1/types/list/",{type:"post"});'
            b'list({body:{count:Number(raw),ratio:parseFloat(raw),label:String(raw),'
            b'ids:rows.map(x=>x.id),offset:-2,missing:void 0}});'
        )
        body = {item["name"]: item for item in result["routes"][0]["body_parameters"]}
        self.assertEqual(["integer"], body["count"]["types"])
        self.assertEqual(["number"], body["ratio"]["types"])
        self.assertEqual(["string"], body["label"]["types"])
        self.assertEqual(["array"], body["ids"]["types"])
        self.assertEqual(-2, body["offset"]["default"])
        self.assertEqual(["unknown"], body["missing"]["types"])

    def test_parameter_document_is_byte_deterministic(self) -> None:
        source = (
            b'const{load:list}=request("/api/v1/search/list/",{type:"post"});'
            b'list({body:{page:1,page_size:20,filters:[]}});'
        )
        first = json_bytes(self._build(source))
        second = json_bytes(self._build(source))
        self.assertEqual(first, second)

    def test_lexer_keeps_nested_templates_offsets_and_pairs(self) -> None:
        source = '/* ignored */ call?.(`${outer({key: "}"})}`, 0x10, value ?? fallback)'
        lexed = _tokenize(source)
        self.assertEqual(
            ["call", "?.", "(", '${outer({key: "}"})}', ",", "0x10", ",", "value", "??", "fallback", ")"],
            [token.value for token in lexed.tokens],
        )
        open_index = next(index for index, token in enumerate(lexed.tokens) if token.value == "(")
        self.assertEqual(")", lexed.tokens[lexed.pairs[open_index]].value)
        template_offset = source.index("`${")
        self.assertEqual(3, lexed.token_at_offset(template_offset))


if __name__ == "__main__":
    unittest.main()
