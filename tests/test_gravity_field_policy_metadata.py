from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_sdk._field_policy_detail import validate_analysis_detail
from gravity_sdk._field_policy_metadata import load_event_property_rows, load_view
from gravity_sdk._field_policy_operations import (
    ANALYSIS_EVENT,
    ANALYSIS_EVENT_INFO,
    ANALYSIS_EVENT_PROPERTY,
    ANALYSIS_SEGMENT,
    ANALYSIS_USER_EVENT,
    ANALYSIS_USER_PROPERTY,
)
from gravity_sdk.errors import InputValidationError
from gravity_sdk.models import OperationSpec, load_operation_manifest


ROOT = Path(__file__).resolve().parents[1]


def _segment_contract_change(**overrides: Any) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "schema_version": "gravity-insight.read.v1",
        "status": "contract_changed",
        "source": {
            "system": "gravity_insight",
            "contract_fingerprint": "controlled-contract-fingerprint",
        },
        "operation_id": ANALYSIS_SEGMENT,
        "data": {"list": [{"segment_id": "segment-1", "segment_name": "active"}]},
        "warnings": [
            "uncontracted nested item containers were omitted (count=6)"
        ],
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _event_info_contract_change(**overrides: Any) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "schema_version": "gravity-insight.read.v1",
        "status": "contract_changed",
        "source": {
            "system": "gravity_insight",
            "contract_fingerprint": "controlled-event-info-fingerprint",
        },
        "operation_id": ANALYSIS_EVENT_INFO,
        "data": {
            "properties": {
                "common": [],
                "custom": [
                    {"name": "order_status", "data_type": "INT"},
                    {"name": "order_id", "data_type": "STRING"},
                ],
                "preset": [],
            }
        },
        "warnings": [
            "unregistered nested response item keys were omitted (count=4)"
        ],
        "error": None,
    }
    envelope.update(overrides)
    return envelope


def _operation(operation_id: str) -> OperationSpec:
    operations = load_operation_manifest(
        ROOT / "src" / "gravity_sdk" / "manifests" / "analysis.json"
    )
    return next(item for item in operations if item.operation_id == operation_id)


class GravityFieldPolicyMetadataTests(unittest.TestCase):
    def test_segment_metadata_accepts_only_safe_projected_nested_omissions(self) -> None:
        view = load_view(
            ANALYSIS_SEGMENT,
            {"app_id": "101"},
            lambda _operation_id, _inputs: _segment_contract_change(),
        )

        self.assertEqual("contract_changed", view.status)
        self.assertEqual("segment-1", view.rows[0]["segment_id"])

    def test_safe_segment_projection_unblocks_detail_membership_loading(self) -> None:
        def loader(
            operation_id: str, _inputs: Mapping[str, Any]
        ) -> Mapping[str, Any]:
            if operation_id == ANALYSIS_SEGMENT:
                return _segment_contract_change()
            if operation_id in {
                ANALYSIS_USER_PROPERTY,
                ANALYSIS_EVENT_PROPERTY,
                ANALYSIS_EVENT,
            }:
                return {"status": "empty", "data": {"list": []}}
            raise AssertionError(f"unexpected metadata operation: {operation_id}")

        cases = (
            (
                "analysis.user_detail.list",
                {"app_id": "101", "fields": ["ClientID"]},
            ),
            (
                ANALYSIS_USER_EVENT,
                {
                    "app_id": "101",
                    "client_id": "client-1",
                    "date": "2026-08-12",
                    "fields": ["ClientID"],
                },
            ),
        )
        for operation_id, inputs in cases:
            with self.subTest(operation_id=operation_id):
                validate_analysis_detail(_operation(operation_id), inputs, loader)

    def test_user_detail_fixed_attribution_fields_are_not_custom_metadata(self) -> None:
        def loader(_operation_id: str, _inputs: Mapping[str, Any]) -> Mapping[str, Any]:
            return {"status": "empty", "data": {"list": []}}

        operation = _operation("analysis.user_detail.list")
        fields = "CreateTime AdPlatform Channel TurboPromotedObjectID AdvertiserID AdGid AdAid AdCid CSite device_info".split()
        validate_analysis_detail(
            operation, {"app_id": "101", "fields": fields}, loader
        )
        with self.assertRaisesRegex(InputValidationError, "absent from live metadata"):
            validate_analysis_detail(
                operation,
                {"app_id": "101", "fields": ["custom_user_property"]},
                loader,
            )

    def test_segment_contract_change_still_fails_closed_on_other_drift(self) -> None:
        unsafe_envelopes = (
            _segment_contract_change(
                warnings=[
                    "uncontracted nested item containers were omitted (count=6)",
                    "required response data keys are absent (count=1)",
                ]
            ),
            _segment_contract_change(error={"code": "UPSTREAM_UNAVAILABLE"}),
            _segment_contract_change(data={"list": [{"segment_name": "missing id"}]}),
            _segment_contract_change(schema_version="uncontrolled-envelope.v1"),
            _segment_contract_change(operation_id="analysis.user_property.list"),
        )
        for envelope in unsafe_envelopes:
            with self.subTest(envelope=envelope), self.assertRaises(
                InputValidationError
            ):
                load_view(
                    ANALYSIS_SEGMENT,
                    {"app_id": "101"},
                    lambda _operation_id, _inputs, value=envelope: value,
                )

    def test_other_metadata_operations_do_not_inherit_segment_exception(self) -> None:
        with self.assertRaises(InputValidationError):
            load_view(
                ANALYSIS_USER_PROPERTY,
                {"app_id": "101"},
                lambda _operation_id, _inputs: _segment_contract_change(
                    operation_id=ANALYSIS_USER_PROPERTY
                ),
            )

    def test_event_info_accepts_safe_projected_nested_key_omissions(self) -> None:
        rows = load_event_property_rows(
            ("order_status",),
            "101",
            lambda _operation_id, _inputs: _event_info_contract_change(),
        )

        self.assertEqual({"order_status", "order_id"}, {row["name"] for row in rows})

    def test_safe_event_info_projection_unblocks_exact_user_event_filter(self) -> None:
        def loader(
            operation_id: str, _inputs: Mapping[str, Any]
        ) -> Mapping[str, Any]:
            if operation_id == ANALYSIS_SEGMENT:
                return _segment_contract_change()
            if operation_id == ANALYSIS_USER_PROPERTY:
                return {"status": "empty", "data": {"list": []}}
            if operation_id == ANALYSIS_EVENT_PROPERTY:
                return {
                    "status": "success",
                    "data": {
                        "list": [
                            {"name": "order_status"},
                            {"name": "order_id"},
                        ]
                    },
                }
            if operation_id == ANALYSIS_EVENT:
                return {
                    "status": "success",
                    "data": {"list": [{"name": "order_status"}]},
                }
            if operation_id == ANALYSIS_EVENT_INFO:
                return _event_info_contract_change()
            raise AssertionError(f"unexpected metadata operation: {operation_id}")

        validate_analysis_detail(
            _operation(ANALYSIS_USER_EVENT),
            {
                "app_id": "101",
                "client_id": "client-1",
                "date": "2026-08-12",
                "event_list": ["order_status"],
                "query_item_list": [
                    {
                        "event_name": "order_status",
                        "event_label": "",
                        "conditions": [
                            {
                                "operator": "IN",
                                "field": "order_status",
                                "type": "event",
                                "value": ["2"],
                            },
                            {
                                "operator": "IN",
                                "field": "order_id",
                                "type": "event",
                                "value": ["30202"],
                            },
                        ],
                        "cond_logic": "AND",
                    }
                ],
            },
            loader,
        )

    def test_event_info_contract_change_still_fails_closed_on_other_drift(
        self,
    ) -> None:
        valid_properties = _event_info_contract_change()["data"]["properties"]
        unsafe_envelopes = (
            _event_info_contract_change(
                warnings=[
                    "unregistered nested response item keys were omitted (count=4)",
                    "required response data keys are absent (count=1)",
                ]
            ),
            _event_info_contract_change(error={"code": "UPSTREAM_UNAVAILABLE"}),
            _event_info_contract_change(
                data={
                    "properties": {
                        "common": valid_properties["common"],
                        "custom": valid_properties["custom"],
                    }
                }
            ),
            _event_info_contract_change(
                data={
                    "properties": {
                        "common": [],
                        "custom": [{"data_type": "INT"}],
                        "preset": [],
                    }
                }
            ),
            _event_info_contract_change(schema_version="uncontrolled-envelope.v1"),
            _event_info_contract_change(operation_id=ANALYSIS_EVENT_PROPERTY),
        )
        for envelope in unsafe_envelopes:
            with self.subTest(envelope=envelope), self.assertRaises(
                InputValidationError
            ):
                load_event_property_rows(
                    ("order_status",),
                    "101",
                    lambda _operation_id, _inputs, value=envelope: value,
                )


if __name__ == "__main__":
    unittest.main()
