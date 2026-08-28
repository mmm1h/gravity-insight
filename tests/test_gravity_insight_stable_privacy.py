from __future__ import annotations

import unittest

import json
import tempfile
from pathlib import Path

from gravity_sdk.governance.stable_privacy import (
    REGISTRY_PATH,
    inspect_stable_response_privacy,
    operation_exposure_paths,
    render_registry,
)


ROOT = Path(__file__).resolve().parents[1]


def _operation(
    operation_id: str,
    *,
    resource: str,
    item_keys: list[str],
    redact_fields: list[str] | None = None,
) -> dict[str, object]:
    return {
        "operation_id": operation_id,
        "resource": resource,
        "stability": "stable",
        "pagination": {"list_path": "data.list"},
        "privacy_policy": {
            "classification": "user_level",
            "redact_fields": redact_fields or [],
        },
        "response_projection": {
            "data_keys": ["list"],
            "item_keys": item_keys,
        },
    }


def _write_operation(root: Path, operation: dict[str, object]) -> Path:
    path = (
        root
        / "src/gravity_sdk/contracts/operations"
        / f"{operation['operation_id']}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"operation": operation}), encoding="utf-8")
    return path


def _write_registry(root: Path) -> None:
    path = root / REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_registry(root), encoding="utf-8")



class GravityInsightStablePrivacyTests(unittest.TestCase):
    def test_stable_registry_accepts_authorized_personal_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_operation(
                root,
                _operation(
                    "analysis.member.list",
                    resource="member",
                    item_keys=["id", "email"],
                ),
            )
            _write_registry(root)

            errors = inspect_stable_response_privacy(root)

        assert errors == []


    def test_member_name_context_does_not_flag_business_object_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_operation(
                root,
                _operation(
                    "analysis.account_user.list",
                    resource="account_user",
                    item_keys=["name"],
                ),
            )
            _write_operation(
                root,
                _operation(
                    "promotion.campaign.list",
                    resource="campaign",
                    item_keys=[
                        "campaign_name",
                        "name",
                        "phone_brand",
                        "phone_model",
                        "wechat_app_id",
                        "wechat_origin_id",
                    ],
                ),
            )
            _write_registry(root)

            errors = inspect_stable_response_privacy(root)

        assert errors == []


    def test_every_new_stable_projection_field_requires_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            operation = _operation(
                "promotion.campaign.list",
                resource="campaign",
                item_keys=["campaign_id"],
            )
            path = _write_operation(root, operation)
            _write_registry(root)
            operation["response_projection"]["item_keys"].append("budget")  # type: ignore[index]
            path.write_text(json.dumps({"operation": operation}), encoding="utf-8")

            errors = inspect_stable_response_privacy(root)

        assert errors == [
            "stable-response-privacy: promotion.campaign.list exposes unreviewed field "
            "'data.list[].budget'; review its contract and update the stable registry"
        ]


    def test_credential_fields_cannot_become_response_contracts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_operation(
                root,
                _operation(
                    "analysis.member.list",
                    resource="member",
                    item_keys=["access_token"],
                    redact_fields=["access_token"],
                ),
            )
            _write_registry(root)

            assert inspect_stable_response_privacy(root) == [
                "stable-response-privacy: analysis.member.list exposes credential field "
                "'data.list[].access_token'"
            ]


    def test_explicit_sensitive_projection_approval_is_exact_and_reviewed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _write_operation(
                root,
                _operation("analysis.member.list", resource="member", item_keys=["email"]),
            )
            _write_registry(root)
            path = root / REGISTRY_PATH
            registry = json.loads(path.read_text(encoding="utf-8"))
            registry["approved_sensitive_exposures"] = {
                "analysis.member.list": {
                    "data.list[].email": "Explicit upstream-authorization review."
                }
            }
            path.write_text(json.dumps(registry), encoding="utf-8")

            assert inspect_stable_response_privacy(root) == []


    def test_surface_registry_tracks_nested_dynamic_and_opaque_exposure(self):
        operation = _operation(
            "analysis.example.list",
            resource="example",
            item_keys=["config", "member"],
        )
        projection = operation["response_projection"]
        projection["nested_item_keys"] = {"member": ["id", "name"]}  # type: ignore[index]
        projection["dynamic_item_fields"] = ["fields"]  # type: ignore[index]
        projection["opaque_json_item_keys"] = ["config"]  # type: ignore[index]

        assert operation_exposure_paths(operation) >= {
            "data.list[].member.name",
            "@dynamic:item:fields",
            "@opaque:data.list[].config",
        }


    def test_exposure_paths_characterize_every_projection_surface(self):
        operation = _operation(
            "analysis.example.list",
            resource="example",
            item_keys=["base", "config", "parent"],
        )
        projection = operation["response_projection"]
        projection.update(  # type: ignore[union-attr]
            {
                "data_keys": ["list", "summary"],
                "numeric_paths": ["totals.[].value", "data.count"],
                "data_item_keys": {"groups": ["id"]},
                "data_path_item_keys": {"outer.groups": ["name"]},
                "nested_item_keys": {
                    "parent": ["child"],
                    "child": ["leaf"],
                    "ignored": "not-a-list",
                },
                "recursive_data_item_keys": {
                    "tree": ["id"],
                    "ignored": "not-a-list",
                },
                "opaque_json_item_keys": ["config", "missing"],
                "dynamic_item_fields": ["fields"],
                "numeric_suffix_item_fields": ["metrics"],
                "data_dynamic_item_fields": {
                    "groups": ["group_fields"],
                    "ignored": "not-a-list",
                },
                "data_numeric_suffix_item_fields": {
                    "groups": ["group_metrics"],
                    "ignored": "not-a-list",
                },
            }
        )

        assert operation_exposure_paths(operation) == {
            "data.list",
            "data.summary",
            "data.list[].base",
            "data.list[].config",
            "data.list[].parent",
            "data.totals[].value",
            "data.count",
            "data.groups[].id",
            "data.outer.groups[].name",
            "data.list[].parent.child",
            "data.list[].parent.child.leaf",
            "@recursive:data.tree",
            "data.tree.**.id",
            "@recursive:data.ignored",
            "@opaque:data.list[].config",
            "@opaque:data.list[].missing",
            "@dynamic:item:fields",
            "@dynamic-numeric:item:metrics",
            "@dynamic:data:groups:group_fields",
            "@dynamic-numeric:data:groups:group_metrics",
        }


    def test_list_root_precedence_and_non_mapping_projection_are_stable(self):
        cases = (
            (
                "declared list shape",
                {"data_shape": "list", "data_keys": ["list"], "item_keys": ["id"]},
                "data[].id",
            ),
            (
                "pagination list path",
                {"data_keys": ["list"], "item_keys": ["id"]},
                "data.list[].id",
            ),
            (
                "projected list key",
                {"data_keys": ["list"], "item_keys": ["id"]},
                "data.list[].id",
            ),
            (
                "default data list",
                {"data_keys": [], "item_keys": ["id"]},
                "data[].id",
            ),
        )
        for name, projection, expected in cases:
            operation = {
                "response_projection": projection,
                "pagination": (
                    {"list_path": "data.list"}
                    if name == "pagination list path"
                    else {}
                ),
            }
            with self.subTest(rule=name):
                self.assertIn(expected, operation_exposure_paths(operation))

        self.assertEqual(set(), operation_exposure_paths({"response_projection": []}))


    def test_repository_stable_privacy_baseline_is_zero(self):
        assert inspect_stable_response_privacy(ROOT) == []
