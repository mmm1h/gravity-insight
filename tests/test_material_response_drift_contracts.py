from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from gravity_insight.drift import ProjectionDrift, projection_drift_status
from gravity_insight.executor import _project
from gravity_insight.models import OperationSpec, load_operation_manifest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "src" / "gravity_insight" / "contracts" / "operations"
MANIFEST_ROOT = ROOT / "src" / "gravity_insight" / "manifests"

OBSERVED_DRIFT = {
    "material.album.tree": {
        "/data/tree/*/album_authority": "object",
        "/data/tree/*/children/*/album_authority": "object",
        "/data/tree/*/children/*/children/*/album_authority": "object",
        "/data/tree/*/children/*/children/*/children/*/album_authority": "object",
        "/data/tree/*/children/*/children/*/children/*/create_user_id": "integer",
        "/data/tree/*/children/*/children/*/create_user_id": "integer",
        "/data/tree/*/children/*/create_user_id": "integer",
        "/data/tree/*/create_user_id": "integer",
    },
    "material.bytedance.list": {
        "/data/list/*/capture_user_id": "array",
        "/data/list/*/create_user_id": "integer",
        "/data/list/*/create_user_name": "string",
        "/data/list/*/creative_user_id": "integer",
        "/data/list/*/creative_user_name": "string",
        "/data/list/*/designer_id": "integer",
        "/data/list/*/designer_name": "string",
        "/data/list/*/dub_user_id": "array",
        "/data/list/*/file_url": "string",
        "/data/list/*/performer_user_id": "array",
        "/data/list/*/thumbnail_url": "string",
        "/data/list/*/transcribe_user_id": "array",
        "/data/list/*/video_cover_list": "array",
    },
    "material.local.list": {
        "/data/list/*/file_sub_type": "string",
        "/data/list/*/video_cover_list": "null",
    },
    "material.tag.list": {
        "/data/list/*/create_user_id": "integer",
        "/data/list/*/create_user_name": "string",
        "/data/list/*/update_user_id": "integer",
        "/data/list/*/update_user_name": "string",
    },
    "material.tencent.list": {
        "/data/list/*/capture_user_id": "array",
        "/data/list/*/dub_user_id": "array",
        "/data/list/*/performer_user_id": "array",
        "/data/list/*/transcribe_user_id": "array",
        "/data/list/*/video_cover_list": "array",
    },
}


def _source_projection(operation_id: str) -> dict[str, Any]:
    document = json.loads(
        (CONTRACT_ROOT / f"{operation_id}.json").read_text(encoding="utf-8")
    )
    return document["operation"]["response_projection"]


def _repository_operations() -> dict[str, OperationSpec]:
    wanted = set(OBSERVED_DRIFT)
    found: dict[str, OperationSpec] = {}
    for path in sorted(MANIFEST_ROOT.glob("*.json")):
        for operation in load_operation_manifest(path):
            if operation.operation_id in wanted:
                found[operation.operation_id] = operation
    if set(found) != wanted:
        raise AssertionError("material-rest operations are absent from manifests")
    return found


def _page_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": 0,
        "data": {
            "list": [row],
            "page_info": {"page": 1, "page_size": 1, "total_page": 1},
        },
    }


class MaterialResponseDriftContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.operations = _repository_operations()

    def test_source_contracts_declare_every_observed_field(self) -> None:
        for operation_id, fields in OBSERVED_DRIFT.items():
            projection = _source_projection(operation_id)
            item_keys = set(projection.get("item_keys", []))
            opaque = set(projection.get("opaque_json_item_keys", []))
            omitted = set(projection.get("known_omitted_item_keys", []))
            for path, observed_type in fields.items():
                with self.subTest(
                    operation_id=operation_id,
                    path=path,
                    observed_type=observed_type,
                ):
                    field = path.rsplit("/", 1)[-1]
                    if operation_id == "material.album.tree":
                        segments = path.strip("/").split("/")
                        allowed = set(projection["data_item_keys"]["tree"])
                        for index in range(3, len(segments) - 1, 2):
                            self.assertEqual("children", segments[index])
                            self.assertIn("children", allowed)
                            allowed = set(projection["nested_item_keys"]["children"])
                        self.assertIn(field, allowed)
                    else:
                        self.assertIn(field, item_keys)
                        self.assertNotIn(field, omitted)

                    if observed_type in {"array", "object"}:
                        self.assertIn(field, opaque)
                    else:
                        self.assertNotIn(field, opaque)
                        self.assertNotIn(
                            field, projection.get("scalar_list_item_types", {})
                        )

    def test_projects_all_observed_fields_without_drift(self) -> None:
        rows = {
            "material.bytedance.list": {
                "capture_user_id": [1, {"opaque": None}],
                "create_user_id": 2,
                "create_user_name": "creator",
                "creative_user_id": 3,
                "creative_user_name": "creative",
                "designer_id": 4,
                "designer_name": "designer",
                "dub_user_id": [],
                "file_url": "https://example.invalid/material",
                "performer_user_id": [5],
                "thumbnail_url": "https://example.invalid/thumbnail",
                "transcribe_user_id": [6],
                "video_cover_list": [{"opaque": "cover"}],
            },
            "material.local.list": {
                "file_sub_type": "video",
                "video_cover_list": None,
            },
            "material.tag.list": {
                "create_user_id": 7,
                "create_user_name": "creator",
                "update_user_id": 8,
                "update_user_name": "updater",
            },
            "material.tencent.list": {
                "capture_user_id": [9],
                "dub_user_id": [10],
                "performer_user_id": [],
                "transcribe_user_id": [{"opaque": 11}],
                "video_cover_list": [None, {"opaque": "cover"}],
            },
        }
        for operation_id, row in rows.items():
            with self.subTest(operation_id=operation_id):
                projected, warnings, drift, response_drift = _project(
                    self.operations[operation_id], _page_payload(row), {}
                )
                self.assertEqual(row, projected["list"][0])
                self.assertEqual((), warnings)
                self.assertIs(ProjectionDrift.NONE, drift)
                self.assertIsNone(response_drift)

        def node(level: int) -> dict[str, Any]:
            result = {
                "id": level,
                "label": f"level-{level}",
                "parent_id": level - 1,
                "root_id": 0,
                "has_alum": True,
                "album_authority": {"opaque": [level, None]},
                "create_user_id": 100 + level,
                "children": [],
            }
            if level < 3:
                result["children"] = [node(level + 1)]
            return result

        album_data = {"tree": [node(0)], "image_size": 1, "video_size": 2}
        projected, warnings, drift, response_drift = _project(
            self.operations["material.album.tree"],
            {"code": 0, "data": album_data},
            {},
        )
        self.assertEqual(album_data, projected)
        self.assertEqual((), warnings)
        self.assertIs(ProjectionDrift.NONE, drift)
        self.assertIsNone(response_drift)

    def test_opaque_fields_reject_non_json_values_as_contract_changed(self) -> None:
        projected, warnings, drift, _ = _project(
            self.operations["material.bytedance.list"],
            _page_payload({"capture_user_id": [{"invalid": object()}]}),
            {},
        )

        self.assertEqual({}, projected["list"][0])
        self.assertIs(ProjectionDrift.BREAKING, drift)
        self.assertEqual("contract_changed", projection_drift_status(drift))
        self.assertTrue(
            any("uncontracted nested item containers" in warning for warning in warnings)
        )


if __name__ == "__main__":
    unittest.main()
