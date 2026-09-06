from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Mapping

from gravity_insight import GravityInsightClient
from gravity_insight.transport import TransportResponse


ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = "promotion.kuaishou.account.list"
AD_UNIT = "promotion.kuaishou.ad_unit.list"
ADVERTISER = "promotion.kuaishou.advertiser.list"

SCALAR_ITEM_VALUES: dict[str, dict[str, Any]] = {
    ACCOUNT: {
        "account_role": "role",
        "ad_platform": "kuaishou",
        "advertiser_sort": "sort",
        "agent_id": 1,
        "balance": 1.5,
        "budget": 2.5,
        "budget_mode": "mode",
        "cid": 2,
        "company": "company",
        "create_time": "2026-09-05 00:00:00",
        "create_user_id": 3,
        "create_user_name": "creator",
        "develop_app_id": 4,
        "first_industry_id": 5,
        "first_industry_name": "first industry",
        "grant_source": "source",
        "grant_type": 6,
        "modify_time": "2026-09-05 01:00:00",
        "operator_id": 7,
        "operator_name": "operator",
        "put_status": 8,
        "put_status_modify_time": "2026-09-05 02:00:00",
        "remark": "remark",
        "second_industry_id": 9,
        "second_industry_name": "second industry",
        "update_user_id": 10,
        "update_user_name": "updater",
    },
    AD_UNIT: {
        "adgroup_put_status": 1,
        "adgroup_status": 2,
        "advertiser_balance": 1.5,
        "advertiser_budget": "2.5",
        "advertiser_budget_mode": "mode",
        "advertiser_remark": "remark",
        "advertiser_system_status": "enabled",
        "begin_time": "2026-09-05 00:00:00",
        "bid": "3.5",
        "bid_type": 3,
        "charge": "4.5",
        "company": "company",
        "compensate_status": 4,
        "day_budget": "5.5",
        "deep_conversion_type": 5,
        "deep_conversion_type_str": "conversion",
        "end_time": "2026-09-05 23:59:59",
        "ocpx_action_type": 6,
        "ocpx_action_type_str": "action",
        "operator_id": 7,
        "operator_name": "operator",
        "roi_ratio": 1.25,
        "scene_id": "scene",
        "schedule_time": "schedule",
        "study_status": 8,
        "unit_id": "unit-1",
        "unit_name": "unit",
    },
    ADVERTISER: {
        "advertiser_balance": 1.5,
        "advertiser_budget": "2.5",
        "advertiser_budget_mode": "mode",
        "advertiser_remark": "remark",
        "advertiser_system_status": "enabled",
        "charge": "3.5",
        "company": "company",
        "operator_id": 1,
        "operator_name": "operator",
    },
}

OPAQUE_ITEM_VALUES = {
    AD_UNIT: {"project_list": [{"uncontracted_shape": [1, None, True]}]},
    ADVERTISER: {"project_list": [{"uncontracted_shape": [1, None, True]}]},
}
OMITTED_ITEM_VALUES = {ACCOUNT: {"access_token": "must-not-be-projected"}}
DATA_ITEM_VALUES = {
    AD_UNIT: {"charge": "4.5"},
    ADVERTISER: {"charge": "3.5"},
}
INPUTS = {
    ACCOUNT: {"page": 1, "page_size": 1},
    AD_UNIT: {
        "date_list": ["2026-09-05", "2026-09-05"],
        "page": 1,
        "page_size": 1,
    },
    ADVERTISER: {
        "date_list": ["2026-09-05", "2026-09-05"],
        "page": 1,
        "page_size": 1,
    },
}


def _contract(operation_id: str) -> dict[str, Any]:
    path = (
        ROOT
        / "src"
        / "gravity_insight"
        / "contracts"
        / "operations"
        / f"{operation_id}.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))["operation"]


class StaticTransport:
    is_test_transport = True

    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload

    def request(self, method: str, path: str, **kwargs: Any) -> TransportResponse:
        return TransportResponse(200, self.payload, "2026-09-05T00:00:00Z")


def _client(operation_id: str, payload: Mapping[str, Any]) -> GravityInsightClient:
    return GravityInsightClient._from_manifest_for_tests(
        {"manifest_version": 1, "operations": [_contract(operation_id)]},
        transport=StaticTransport(payload),
    )


def _payload(operation_id: str, row: Mapping[str, Any]) -> dict[str, Any]:
    data: dict[str, Any] = {
        "list": [dict(row)],
        "page_info": {
            "page": 1,
            "page_size": 1,
            "total_number": 1,
            "total_page": 1,
        },
    }
    if operation_id in DATA_ITEM_VALUES:
        data["total"] = [DATA_ITEM_VALUES[operation_id]]
    return {"code": 0, "data": data}


class KuaishouResponseContractTests(unittest.TestCase):
    def test_every_observed_field_has_an_explicit_projection_verdict(self) -> None:
        observed_count = sum(len(values) for values in SCALAR_ITEM_VALUES.values())
        observed_count += sum(len(values) for values in OPAQUE_ITEM_VALUES.values())
        observed_count += sum(len(values) for values in OMITTED_ITEM_VALUES.values())
        observed_count += sum(len(values) for values in DATA_ITEM_VALUES.values())
        self.assertEqual(68, observed_count)

        for operation_id in (ACCOUNT, AD_UNIT, ADVERTISER):
            with self.subTest(operation_id=operation_id):
                projection = _contract(operation_id)["response_projection"]
                item_keys = set(projection["item_keys"])
                scalar_keys = set(SCALAR_ITEM_VALUES[operation_id])
                opaque_keys = set(OPAQUE_ITEM_VALUES.get(operation_id, {}))
                omitted_keys = set(OMITTED_ITEM_VALUES.get(operation_id, {}))

                self.assertLessEqual(scalar_keys | opaque_keys, item_keys)
                self.assertLessEqual(
                    opaque_keys, set(projection.get("opaque_json_item_keys", []))
                )
                self.assertLessEqual(
                    omitted_keys, set(projection.get("known_omitted_item_keys", []))
                )
                self.assertTrue(omitted_keys.isdisjoint(item_keys))
                self.assertLessEqual(
                    set(DATA_ITEM_VALUES.get(operation_id, {})),
                    set(projection.get("data_item_keys", {}).get("total", [])),
                )

    def test_observed_fields_project_cleanly_and_access_token_stays_omitted(
        self,
    ) -> None:
        for operation_id in (ACCOUNT, AD_UNIT, ADVERTISER):
            with self.subTest(operation_id=operation_id):
                row = {
                    **SCALAR_ITEM_VALUES[operation_id],
                    **OPAQUE_ITEM_VALUES.get(operation_id, {}),
                    **OMITTED_ITEM_VALUES.get(operation_id, {}),
                }
                result = _client(operation_id, _payload(operation_id, row)).read(
                    operation_id, INPUTS[operation_id]
                )
                expected_row = {
                    **SCALAR_ITEM_VALUES[operation_id],
                    **OPAQUE_ITEM_VALUES.get(operation_id, {}),
                }

                self.assertEqual("success", result["status"])
                self.assertEqual(expected_row, result["data"]["list"][0])
                self.assertNotIn("access_token", result["data"]["list"][0])
                self.assertNotIn("response_drift", result["result_audit"])
                if operation_id in DATA_ITEM_VALUES:
                    self.assertEqual(
                        [DATA_ITEM_VALUES[operation_id]], result["data"]["total"]
                    )

    def test_opaque_project_list_still_rejects_non_json_values(self) -> None:
        invalid_row = {
            **SCALAR_ITEM_VALUES[AD_UNIT],
            "project_list": [{1: "JSON object keys must be strings"}],
        }
        result = _client(AD_UNIT, _payload(AD_UNIT, invalid_row)).read(
            AD_UNIT, INPUTS[AD_UNIT]
        )

        self.assertFalse(result["ok"])
        self.assertEqual("contract_changed", result["status"])
        self.assertEqual("CONTRACT_CHANGED", result["error"]["code"])
        self.assertNotIn("project_list", result["data"]["list"][0])


if __name__ == "__main__":
    unittest.main()
