from __future__ import annotations

import json
import unittest
import unittest.mock
from pathlib import Path

from gravity_sdk.analysis_projection_contract import (
    ANALYSIS_GROUP_SHAPE_OPENINGS,
    allowed_analysis_response_key,
    analysis_group_shape,
    operation_uses_dynamic_aggregate,
    validate_group_identity_invariant,
)
from gravity_sdk.errors import ManifestError
from gravity_sdk.executor import _project as project_response
from gravity_sdk.models import InputField, OperationSpec, ResponseProjection, load_operation_manifest


ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = ROOT / "src" / "gravity_sdk" / "contracts" / "operations"
MANIFESTS = ROOT / "src" / "gravity_sdk" / "manifests"


def _projection(**overrides: object) -> ResponseProjection:
    payload = {
        "data_keys": ["items"],
        "item_keys": ["id"],
        "dynamic_item_fields": [],
    }
    payload.update(overrides)
    return ResponseProjection.from_dict(payload)


def _axis(
    name: str,
    *,
    item_type: str | None = "string",
    item_enum: tuple[str, ...] = (),
    max_items: int | None = 4,
) -> InputField:
    return InputField(
        name=name,
        type="array",
        item_type=item_type,
        item_enum=item_enum,
        max_items=max_items,
    )


def _minimal_operation(
    *,
    operation_id: str,
    group_by_max: int | None,
    data_keys: tuple[str, ...],
) -> dict[str, object]:
    group_by: dict[str, object] = {
        "type": "array",
        "item_type": "object",
        "default": [],
    }
    if group_by_max is not None:
        group_by["max_items"] = group_by_max
    return {
        "operation_id": operation_id,
        "domain": "analysis",
        "resource": "future",
        "action": "query",
        "contract_version": 1,
        "upstream_method": "POST",
        "path_template": "/report/api/v3/dataanalysis/future_query/",
        "auth_profile": "gravity_authorization",
        "stability": "experimental",
        "input_fields": {
            "app_id": {"type": "string", "required": True},
            "group_by_list": group_by,
        },
        "request": {
            "path_fields": [],
            "query_fields": [],
            "body_fields": ["app_id", "group_by_list"],
            "defaults": {"group_by_list": []},
            "fixed_query": {},
            "fixed_body": {},
        },
        "response_projection": {
            "data_keys": list(data_keys),
            "item_keys": [],
            "dynamic_item_fields": [],
        },
        "pagination": {
            "kind": "none",
            "page_field": "",
            "page_size_field": "",
            "list_path": "",
            "page_info_path": "",
            "total_page_field": "",
        },
        "semantic_error_rules": [],
        "privacy_policy": {
            "classification": "user_level",
            "redact_keys": ["authorization"],
        },
        "required_parent": [],
        "live_probe": {"enabled": False, "input": {}},
        "effect": "read",
        "executable": True,
    }


class ResponseGroupIdentityInvariantTests(unittest.TestCase):
    def test_unknown_groupable_analysis_shape_is_rejected(self) -> None:
        fields = (
            InputField(
                name="group_by_list",
                type="array",
                item_type="object",
                max_items=20,
            ),
        )
        with self.assertRaisesRegex(ManifestError, "known aggregate"):
            validate_group_identity_invariant(fields, _projection(data_keys=["items"]))

    def test_unbound_dimension_axis_is_rejected(self) -> None:
        with self.assertRaisesRegex(ManifestError, "dimension axis"):
            validate_group_identity_invariant(
                (_axis("dims_list", item_enum=("date", "ad_platform")),),
                _projection(item_keys=["id"]),
            )

    def test_unverified_draft_may_declare_unbound_dimension_axis(self) -> None:
        validate_group_identity_invariant(
            (_axis("data_dims"),),
            _projection(item_keys=[]),
            executable=False,
            effect="read",
        )

    def test_gravity_alias_without_real_identifier_is_rejected(self) -> None:
        with self.assertRaisesRegex(ManifestError, "real identifier"):
            validate_group_identity_invariant(
                (),
                _projection(item_keys=["gravity_material_id", "file_name"]),
            )

    def test_catalog_operations_satisfy_the_invariant(self) -> None:
        loaded: list[OperationSpec] = []
        for path in sorted(MANIFESTS.glob("*.json")):
            loaded.extend(load_operation_manifest(json.loads(path.read_text(encoding="utf-8"))))
        self.assertGreaterEqual(len(loaded), 200)
        for operation in loaded:
            validate_group_identity_invariant(
                operation.input_fields, operation.response_projection
            )

    def test_new_event_shaped_route_uses_dynamic_aggregate_without_id_registration(
        self,
    ) -> None:
        operation = OperationSpec.from_dict(
            _minimal_operation(
                operation_id="analysis.future.query",
                group_by_max=20,
                data_keys=("list", "target_list", "date_list"),
            )
        )
        self.assertEqual("event", analysis_group_shape(operation.response_projection))
        self.assertTrue(operation_uses_dynamic_aggregate(operation))
        data, _warnings, _drift, _audit = project_response(
            operation,
            {
                "code": 0,
                "data": {
                    "list": [
                        [
                            {
                                "list": [{"用户.设备类型": "iOS", "uid": "x"}],
                                "event_index": 0,
                            }
                        ]
                    ],
                    "target_list": ["purchase"],
                    "date_list": [],
                },
            },
            {
                "group_by_list": [
                    {"type": "user", "field": "$os", "group_by": "$os"},
                ]
            },
        )
        self.assertEqual("iOS", data["list"][0][0]["list"][0].get("用户.设备类型"))
        self.assertNotIn("uid", json.dumps(data))

    def test_registered_shape_without_opening_is_rejected(self) -> None:
        fields = (
            InputField(
                name="group_by_list",
                type="array",
                item_type="object",
                max_items=20,
            ),
        )
        projection = _projection(data_keys=["list", "target_list"])
        with unittest.mock.patch.dict(
            ANALYSIS_GROUP_SHAPE_OPENINGS,
            {"event": (("list", "[]", "[]", "list", "[]"), "not-a-group-label")},
        ):
            with self.assertRaisesRegex(ManifestError, "no group-label opening"):
                validate_group_identity_invariant(fields, projection)

    def test_fail_closed_keys_stay_blocked(self) -> None:
        self.assertFalse(
            allowed_analysis_response_key(
                "uid", set(), ("list", "[]", "[]", "list", "[]")
            )
        )
        self.assertFalse(
            allowed_analysis_response_key("group_cols", set(), ("aggregate_date", "group"))
        )
        self.assertFalse(
            allowed_analysis_response_key("union_groups", set(), ("list",))
        )

    def test_source_contracts_do_not_need_a_hand_list(self) -> None:
        groupable = []
        for path in sorted(OPERATIONS.glob("*.json")):
            operation = json.loads(path.read_text(encoding="utf-8"))["operation"]
            spec = OperationSpec.from_dict(operation)
            if operation_uses_dynamic_aggregate(spec):
                groupable.append(spec.operation_id)
        self.assertEqual(
            [
                "analysis.event.query",
                "analysis.funnel.query",
                "analysis.property.query",
                "analysis.retention.query",
                "analysis.scatter.query",
            ],
            groupable,
        )
