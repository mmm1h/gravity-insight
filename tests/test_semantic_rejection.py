from __future__ import annotations

import unittest

from gravity_sdk.domains import ANALYSIS_QUERY_OPERATIONS
from gravity_sdk.semantic_rejection import (
    classify_read_rejection,
    raise_read_rejection,
)
from gravity_sdk.errors import SemanticRejectedError


class SemanticRejectionTests(unittest.TestCase):
    def test_unreviewed_upstream_text_stays_out_of_caller_fields(self) -> None:
        payload = {"code": 0, "extra": {"error": "private upstream detail"}}
        field, message, next_action = classify_read_rejection(
            payload,
            operation_id=ANALYSIS_QUERY_OPERATIONS["retention"],
            request_inputs={"app_id": "29034827", "group_by_list": []},
        )
        self.assertEqual("group_by_list", field)
        self.assertEqual("Gravity rejected the read operation", message)
        self.assertIn("sent_keys", next_action)
        self.assertIn("group_by_list[0]", next_action)
        self.assertIn("create_time/day", next_action)
        self.assertNotIn("private upstream detail", message)
        self.assertNotIn("private upstream detail", next_action)
        self.assertNotIn("private upstream detail", field)

    def test_user_property_group_points_at_wire_type(self) -> None:
        field, message, next_action = classify_read_rejection(
            {"extra": {"error": "secret-upstream"}},
            operation_id=ANALYSIS_QUERY_OPERATIONS["funnel"],
            request_inputs={
                "app_id": "29034827",
                "group_by_list": [{"type": "user_property", "field": "$os"}],
            },
        )
        self.assertEqual("group_by_list[].type", field)
        self.assertEqual("Gravity rejected the read operation", message)
        self.assertIn("type=user", next_action)
        self.assertNotIn("secret-upstream", next_action)

    def test_reviewed_mapping_never_echoes_raw_sentence(self) -> None:
        field, message, next_action = classify_read_rejection(
            {"extra": {"error": "groupBy类型(user_property)不合法"}},
            operation_id=ANALYSIS_QUERY_OPERATIONS["event"],
            request_inputs={"group_by_list": [{"type": "user_property"}]},
        )
        self.assertEqual("group_by_list[].type", field)
        self.assertIn("classified extra.error=", message)
        self.assertNotIn("groupBy", message)
        self.assertNotIn("不合法", next_action)
        self.assertIn("type=user", next_action)

    def test_reviewed_prefix_does_not_echo_embedded_payload(self) -> None:
        embedded = "入参错误：group_by_list缺失create_time [{'field': '$os'}]"
        field, message, next_action = classify_read_rejection(
            {"extra": {"error": embedded}},
            operation_id=ANALYSIS_QUERY_OPERATIONS["retention"],
            request_inputs={"group_by_list": [{"type": "user", "field": "$os"}]},
        )
        self.assertEqual("group_by_list", field)
        self.assertIn("classified extra.error=", message)
        self.assertNotIn("$os", message)
        self.assertNotIn("$os", next_action)
        self.assertNotIn(embedded, message)
        self.assertIn("create_time/day", next_action)

    def test_raise_site_is_grade_a(self) -> None:
        with self.assertRaises(SemanticRejectedError) as caught:
            raise_read_rejection(
                {"extra": {"error": "hidden"}},
                operation_id=ANALYSIS_QUERY_OPERATIONS["retention"],
                request_inputs={"group_by_list": []},
            )
        error = caught.exception
        self.assertEqual("group_by_list", error.field)
        self.assertIn("actual value:", str(error))
        self.assertIn("actual value:", error.next_action)
        self.assertNotIn("hidden", str(error))
        self.assertNotIn("hidden", error.next_action or "")
