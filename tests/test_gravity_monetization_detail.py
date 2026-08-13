from __future__ import annotations

import copy
import unittest
from pathlib import Path

from gravity_sdk._field_policy_detail import validate_analysis_detail
from gravity_sdk.monetization_detail import (
    OPERATION_ID,
    SAFE_ROW_FIELDS,
    monetization_detail,
    sanitize_monetization_detail_result,
)
from gravity_sdk.models import load_operation_manifest


DAY = "2026-08-08"
SAFE = {
    "CreateTime": "2026-08-08 12:00:00",
    "AdEventTime": "2026-08-08T12:00:01",
    "AdPlatform": "demo-platform",
    "event$ecpm": 12.5,
    "samount": 3,
    "re_attribute_info": {
        "ReAttributeAdPlatform": "demo-platform",
        "ReAttributeAdAid": "ad-safe",
    },
}
EXCLUDED = {
    "user_id": "user-secret",
    "event_user_id": "event-user-secret",
    "device_id": "device-secret",
    "ClientID": "client-secret",
    "TraceID": "trace-secret",
    "device_info": {"Phone_Model": "fingerprint-secret"},
    "user$ad_count": 99,
    "user$ad_avg_ecpm": 88,
    "user$ad_ltv": 77,
    "Name": "name-secret",
    "WXOpenID": "openid-secret",
}


def _read(row, *, workers=2):
    rows = [] if row is None else [copy.deepcopy(row)]
    return {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": OPERATION_ID,
        "status": "empty" if not rows else "success",
        "error": None,
        "data": {"list": rows, "total": {**EXCLUDED, "samount": 3}},
        "page": {
            "number": 1,
            "size": 100,
            "item_count": len(rows),
            "total_pages": 1,
            "total_items": len(rows),
            "has_more": False,
            "pages_fetched": 1,
            "fetch_strategy": "single_page",
            "max_workers": workers,
        },
    }


class Client:
    def __init__(self, value):
        self.value, self.calls = value, []

    def read_all(self, operation_id, inputs=None, **options):
        self.calls.append((operation_id, copy.deepcopy(inputs), options))
        if isinstance(self.value, BaseException):
            raise self.value
        return copy.deepcopy(self.value)


class MonetizationDetailTests(unittest.TestCase):
    def test_happy_path_uses_fixed_fields_and_rebuilds_safe_rows(self):
        raw = {**SAFE, **EXCLUDED, "future_user_metric": "future-secret"}
        raw["re_attribute_info"] = {
            **SAFE["re_attribute_info"], "FutureUserKey": "nested-secret"
        }
        client = Client(_read(raw))
        result = monetization_detail(
            client, "007", DAY, max_workers=2, max_pages=5, max_items=10
        )
        self.assertEqual(("success", "7", [SAFE]),
                         (result["status"], result["app_id"], result["data"]["list"]))
        operation, inputs, options = client.calls[0]
        self.assertEqual((OPERATION_ID, list(SAFE_ROW_FIELDS), 1, 100),
                         (operation, inputs["fields"], inputs["page"], inputs["page_size"]))
        self.assertEqual({"max_workers": 2, "max_pages": 5, "max_items": 10}, options)
        self.assertEqual(1, result["page"]["pages_fetched"])

    def test_projection_fails_closed_and_never_exposes_excluded_values(self):
        secrets = tuple(str(value) for value in EXCLUDED.values()) + (
            "future-secret", "nested-secret", "exception-secret", "error-secret"
        )
        results = [
            monetization_detail(Client(_read(EXCLUDED)), 7, DAY, max_workers=2),
            monetization_detail(Client(RuntimeError("exception-secret")), 7, DAY, max_workers=2),
            monetization_detail(Client({
                "status": "permission_unavailable",
                "error": {"code": "PERMISSION_UNAVAILABLE", "message": "error-secret"},
            }), 7, DAY, max_workers=2),
        ]
        self.assertEqual(["contract_changed", "error", "error"],
                         [result["status"] for result in results])
        rendered = repr(results)
        self.assertFalse(any(secret in rendered for secret in secrets))

    def test_request_bound_sanitizer_rejects_identity_receipt_and_public_extras(self):
        result = monetization_detail(
            Client(_read(SAFE, workers=1)), 7, DAY,
            max_workers=1, max_pages=5, max_items=10,
        )
        mutations = []
        for path, value in (
            (("app_id",), "8"),
            (("limits", "max_items"), 11),
            (("page", "pages_fetched"), 2),
            (("data", "list", 0, "TraceID"), "public-secret"),
        ):
            forged = copy.deepcopy(result)
            target = forged
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            mutations.append(forged)
        for forged in mutations:
            rebuilt = sanitize_monetization_detail_result(
                forged, 7, DAY, max_workers=1, max_pages=5, max_items=10
            )
            self.assertEqual("contract_changed", rebuilt["status"])
            self.assertNotIn("public-secret", repr(rebuilt))

    def test_field_policy_fast_path_requires_the_exact_static_profile(self):
        root = Path(__file__).resolve().parents[1]
        operation = next(
            item for item in load_operation_manifest(
                root / "src" / "gravity_sdk" / "manifests" / "analysis.json"
            ) if item.operation_id == OPERATION_ID
        )
        calls = []
        base = {"app_id": "7", "date": DAY, "page": 1, "page_size": 100}
        validate_analysis_detail(
            operation, {**base, "fields": list(SAFE_ROW_FIELDS)},
            lambda *args: calls.append(args),
        )
        self.assertEqual([], calls)
        for fields in (SAFE_ROW_FIELDS[:-1], (*SAFE_ROW_FIELDS, "TraceID")):
            validate_analysis_detail(
                operation, {**base, "fields": list(fields)},
                lambda *args: calls.append(args) or {"status": "empty", "data": {"list": []}},
            )
        self.assertTrue(calls)


if __name__ == "__main__":
    unittest.main()
