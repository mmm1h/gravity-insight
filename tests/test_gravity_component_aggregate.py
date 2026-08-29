from __future__ import annotations

import copy
import json
from collections import UserDict
from types import MappingProxyType
import unittest

from gravity_sdk.material_performance_result import (
    MATERIAL_REPORT_OPERATION,
    _safe_rows as safe_material_rows,
    contract_component as material_contract_component,
    product_envelope as material_envelope,
)
from gravity_sdk.promotion_performance_result import (
    PROMOTION_PLATFORM_OPERATIONS,
    contract_component as promotion_contract_component,
    product_envelope as promotion_envelope,
)
from gravity_sdk.promotion_performance_rows import (
    MAX_JSON_INTEGER_BITS,
    MAX_JSON_STRING_LENGTH,
    MAX_OPAQUE_JSON_BYTES,
    MAX_OPAQUE_JSON_DEPTH,
    MAX_OPAQUE_JSON_ELEMENTS,
    safe_promotion_rows,
)


class _StringKey(str):
    pass


class _IntegerScalar(int):
    pass


class _FloatScalar(float):
    pass


def _success(status: str = "success") -> dict[str, object]:
    return {
        "platform": "tencent",
        "ok": True,
        "status": status,
        "error": None,
    }


def _failure(
    status: str, code: str, category: str
) -> dict[str, object]:
    return {
        "platform": "tencent",
        "ok": False,
        "status": status,
        "error": {
            "code": code,
            "category": category,
            "message": f"controlled {category} failure",
        },
    }


def _material(results: list[dict[str, object]]) -> dict[str, object]:
    return material_envelope(
        copy.deepcopy(results),
        app_count=1,
        window=("2026-08-01", "2026-08-02"),
        platforms=("tencent",),
        max_pages=2,
        max_items=10,
        max_workers=1,
        returned_items=0,
    )


def _promotion(results: list[dict[str, object]]) -> dict[str, object]:
    return promotion_envelope(
        copy.deepcopy(results),
        app_id="test-app",
        window=("2026-08-01", "2026-08-02"),
        platforms=("tencent",),
        metric_count=1,
        max_pages=2,
        max_items=10,
        max_workers=1,
        returned_items=0,
    )


def _promotion_rows(
    value: object, *, opaque_fields: frozenset[str] = frozenset()
) -> tuple[list[dict[str, object]] | None, tuple[str, str] | None]:
    return safe_promotion_rows(
        value,
        allowed_fields=frozenset({"cost", "payload"}),
        opaque_fields=opaque_fields,
    )


class ComponentAggregateCharacterizationTests(unittest.TestCase):
    def test_row_collection_and_mapping_boundaries_are_equivalent(self):
        source = MappingProxyType({"cost": 1})
        material = safe_material_rows([source])
        promotion, failure = _promotion_rows([source])
        self.assertEqual([{"cost": 1}], material)
        self.assertEqual((material, None), (promotion, failure))
        self.assertIs(type(material[0]), dict)
        self.assertIs(type(promotion[0]), dict)
        empty_material = safe_material_rows([MappingProxyType({})])
        empty_promotion, empty_failure = _promotion_rows([MappingProxyType({})])
        self.assertEqual(([{}], None), (empty_material, empty_failure))
        self.assertEqual(empty_material, empty_promotion)

        for label, value, expected_failure in (
            ("mapping collection", source, "row_collection_type"),
            ("tuple collection", (source,), "row_collection_type"),
            ("non-mapping row", [["cost", 1]], "row_type"),
        ):
            with self.subTest(label=label):
                material = safe_material_rows(value)
                promotion, failure = _promotion_rows(value)
                self.assertIsNone(material)
                self.assertIsNone(promotion)
                self.assertEqual(expected_failure, failure[0])

    def test_row_key_boundaries_preserve_the_owner_specific_normalization(self):
        for label, row, expected_failure in (
            ("unregistered string", {"unknown": 1}, "row_field_registration"),
            ("non-string", {1: 1}, "row_field_name"),
        ):
            with self.subTest(label=label):
                material = safe_material_rows([row])
                promotion, failure = _promotion_rows([row])
                self.assertIsNone(material)
                self.assertIsNone(promotion)
                self.assertEqual(expected_failure, failure[0])

        key = _StringKey("cost")
        material = safe_material_rows([{key: 1}])
        promotion, failure = _promotion_rows([{key: 1}])
        self.assertIsNone(failure)
        self.assertIs(type(next(iter(material[0]))), str)
        self.assertIs(type(next(iter(promotion[0]))), _StringKey)

    def test_shared_scalar_domain_is_equivalent_at_type_and_size_boundaries(self):
        cases = (
            ("null", None, True),
            ("boolean", False, True),
            ("string limit", "x" * MAX_JSON_STRING_LENGTH, True),
            ("string subclass", _StringKey("value"), True),
            ("string over limit", "x" * (MAX_JSON_STRING_LENGTH + 1), False),
            ("integer limit", (1 << MAX_JSON_INTEGER_BITS) - 1, True),
            ("integer over limit", 1 << MAX_JSON_INTEGER_BITS, False),
            ("integer subclass", _IntegerScalar(1), False),
            ("finite float", 1.5, True),
            ("finite float subclass", _FloatScalar(1.5), True),
            ("nan", float("nan"), False),
            ("infinity", float("inf"), False),
            ("list", [], False),
            ("mapping", {}, False),
            ("bytes", b"value", False),
        )
        for label, value, accepted in cases:
            with self.subTest(label=label):
                material = safe_material_rows([{"cost": value}])
                promotion, failure = _promotion_rows([{"cost": value}])
                self.assertEqual(accepted, material is not None)
                self.assertEqual(accepted, promotion is not None)
                self.assertEqual(
                    None if accepted else "row_field_scalar_rule",
                    None if failure is None else failure[0],
                )

    def test_promotion_opaque_json_accepts_each_exact_boundary(self):
        max_depth = 0
        for _ in range(MAX_OPAQUE_JSON_DEPTH):
            max_depth = [max_depth]
        max_elements = [0] * (MAX_OPAQUE_JSON_ELEMENTS - 1)
        final_string_length = (
            MAX_OPAQUE_JSON_BYTES - (3 * MAX_JSON_STRING_LENGTH) - 13
        )
        max_bytes = [
            "x" * MAX_JSON_STRING_LENGTH,
            "x" * MAX_JSON_STRING_LENGTH,
            "x" * MAX_JSON_STRING_LENGTH,
            "x" * final_string_length,
        ]
        self.assertEqual(
            MAX_OPAQUE_JSON_BYTES,
            len(json.dumps(max_bytes, separators=(",", ":")).encode("utf-8")),
        )
        max_key = {"k" * MAX_JSON_STRING_LENGTH: 0}
        mapping = MappingProxyType(
            {"nested": (None, False, 1, 1.5, "value")}
        )
        for label, value in (
            ("mapping and tuple normalization", mapping),
            ("depth", max_depth),
            ("elements", max_elements),
            ("encoded bytes", max_bytes),
            ("mapping key length", max_key),
        ):
            with self.subTest(label=label):
                rows, failure = _promotion_rows(
                    [{"payload": value}], opaque_fields=frozenset({"payload"})
                )
                self.assertIsNone(failure)
                self.assertIsNotNone(rows)
        rows, _ = _promotion_rows(
            [{"payload": mapping}], opaque_fields=frozenset({"payload"})
        )
        self.assertEqual(
            {"nested": [None, False, 1, 1.5, "value"]}, rows[0]["payload"]
        )

    def test_promotion_opaque_json_rejects_each_boundary_overrun(self):
        too_deep = 0
        for _ in range(MAX_OPAQUE_JSON_DEPTH + 1):
            too_deep = [too_deep]
        too_many_elements = [0] * MAX_OPAQUE_JSON_ELEMENTS
        too_many_bytes = [
            "x" * MAX_JSON_STRING_LENGTH,
            "x" * MAX_JSON_STRING_LENGTH,
            "x" * MAX_JSON_STRING_LENGTH,
            "x" * (
                MAX_OPAQUE_JSON_BYTES - (3 * MAX_JSON_STRING_LENGTH) - 12
            ),
        ]
        cases = (
            ("depth", too_deep, "row_field_opaque_json_bounds"),
            ("elements", too_many_elements, "row_field_opaque_json_bounds"),
            ("encoded bytes", too_many_bytes, "row_field_opaque_json_bounds"),
            (
                "mapping key length",
                {"k" * (MAX_JSON_STRING_LENGTH + 1): 0},
                "row_field_opaque_json_bounds",
            ),
            ("non-string mapping key", {1: "private"}, "row_field_opaque_json_rule"),
            ("non-json value", object(), "row_field_opaque_json_rule"),
            ("unencodable string", "\ud800", "row_field_opaque_json_rule"),
        )
        for label, value, expected_failure in cases:
            with self.subTest(label=label):
                rows, failure = _promotion_rows(
                    [{"payload": value}], opaque_fields=frozenset({"payload"})
                )
                self.assertIsNone(rows)
                self.assertEqual(
                    (expected_failure, "$.data.data.list[0].payload"), failure
                )

    def test_material_and_promotion_aggregate_statuses_are_equivalent(self):
        cases = (
            ([], "empty"),
            ([_success()], "success"),
            ([_success("empty")], "empty"),
            ([_success("empty"), _success()], "success"),
            ([_failure("error", "UPSTREAM_UNAVAILABLE", "upstream")], "error"),
            (
                [_success(), _failure("error", "UPSTREAM_UNAVAILABLE", "upstream")],
                "partial",
            ),
            (
                [_success(), _failure("contract_changed", "CONTRACT_CHANGED", "local")],
                "contract_changed",
            ),
        )
        aggregate_fields = (
            "ok",
            "status",
            "exit_code",
            "total_count",
            "success_count",
            "failure_count",
        )
        for results, expected_status in cases:
            with self.subTest(expected_status=expected_status, results=results):
                material = _material(results)
                promotion = _promotion(results)
                self.assertEqual(expected_status, material["status"])
                self.assertEqual(
                    {field: material[field] for field in aggregate_fields},
                    {field: promotion[field] for field in aggregate_fields},
                )

    def test_material_and_promotion_choose_the_same_highest_exit_error(self):
        results = [
            _failure("error", "INPUT_INVALID", "caller"),
            _failure("error", "UPSTREAM_UNAVAILABLE", "upstream"),
            _failure("error", "LOCAL_IO_ERROR", "local"),
        ]
        material = _material(results)
        promotion = _promotion(results)
        self.assertEqual((4, "LOCAL_IO_ERROR"), (
            material["exit_code"], material["error"]["code"]
        ))
        self.assertEqual(
            (material["exit_code"], material["error"]),
            (promotion["exit_code"], promotion["error"]),
        )

    def test_primary_error_accepts_any_mapping_and_copies_it(self):
        error = UserDict(
            {
                "code": "UPSTREAM_UNAVAILABLE",
                "category": "upstream",
                "message": "controlled failure",
            }
        )
        failure = {
            "platform": "tencent",
            "ok": False,
            "status": "error",
            "error": error,
        }
        material = _material([failure])
        promotion = _promotion([failure])
        self.assertEqual(dict(error), material["error"])
        self.assertEqual(material["error"], promotion["error"])
        self.assertIs(type(material["error"]), dict)
        self.assertIs(type(promotion["error"]), dict)
        self.assertIsNot(material["error"], material["results"][0]["error"])
        self.assertIsNot(promotion["error"], promotion["results"][0]["error"])

        empty_error = dict(failure, error=UserDict())
        self.assertEqual({}, _material([empty_error])["error"])
        self.assertEqual({}, _promotion([empty_error])["error"])

    def test_malformed_primary_errors_use_owner_fallbacks(self):
        missing = {"platform": "tencent", "ok": False, "status": "error"}
        for label, failure in (
            ("missing", missing),
            ("null", dict(missing, error=None)),
            ("non-mapping", dict(missing, error=[])),
        ):
            with self.subTest(label=label):
                material = _material([failure])
                promotion = _promotion([failure])
                self.assertEqual(
                    material_contract_component("tencent")["error"],
                    material["error"],
                )
                self.assertEqual(
                    promotion_contract_component("tencent")["error"],
                    promotion["error"],
                )

        unknown = {"ok": False, "status": "error", "error": None}
        self.assertIn("for unknown.", _material([unknown])["error"]["message"])
        self.assertIn("for unknown.", _promotion([unknown])["error"]["message"])
        self.assertEqual(
            MATERIAL_REPORT_OPERATION,
            material_contract_component("tencent")["operation_id"],
        )
        self.assertEqual(
            PROMOTION_PLATFORM_OPERATIONS["tencent"],
            promotion_contract_component("tencent")["operation_id"],
        )


if __name__ == "__main__":
    unittest.main()
