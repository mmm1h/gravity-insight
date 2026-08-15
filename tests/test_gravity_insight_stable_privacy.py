from __future__ import annotations

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


def test_stable_registry_accepts_authorized_personal_fields() -> None:
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


def test_member_name_context_does_not_flag_business_object_names() -> None:
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


def test_every_new_stable_projection_field_requires_registration() -> None:
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


def test_credential_fields_cannot_become_response_contracts() -> None:
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


def test_surface_registry_tracks_nested_dynamic_and_opaque_exposure() -> None:
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


def test_repository_stable_privacy_baseline_is_zero() -> None:
    assert inspect_stable_response_privacy(ROOT) == []
