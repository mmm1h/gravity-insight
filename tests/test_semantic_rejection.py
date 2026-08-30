from __future__ import annotations

import unittest

from gravity_insight.domains import ANALYSIS_QUERY_OPERATIONS
from gravity_insight.semantic_rejection import (
    classify_read_rejection,
    raise_read_rejection,
)
from gravity_insight.errors import SemanticRejectedError, UpstreamContradictedRequestError


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
        self.assertEqual("upstream", error.category)
        self.assertTrue(error.retryable)
        self.assertIn("actual value:", str(error))
        self.assertIn("actual value:", error.next_action)
        self.assertIn("--concurrency 1", error.next_action)
        self.assertIn("same-shape scalar request succeeded", error.next_action)
        self.assertNotIn("hidden", str(error))
        self.assertNotIn("hidden", error.next_action or "")

    def test_non_analysis_unreviewed_rejection_keeps_existing_classification(self) -> None:
        with self.assertRaises(SemanticRejectedError) as caught:
            raise_read_rejection(
                {"extra": {"error": "hidden"}},
                operation_id="example.items.list",
                request_inputs={"page": 1},
            )
        self.assertEqual("caller", caught.exception.category)
        self.assertFalse(caught.exception.retryable)


class ContradictedGroupClaimTests(unittest.TestCase):
    """Issue #23: upstream blamed a grouping the compiler generated correctly."""

    _MISSING = {"extra": {"error": "入参错误：group_by_list缺失create_time"}}
    _GENERATED = [{"type": "default_event", "field": "create_time", "group_by": "day"}]

    def test_remedy_does_not_ask_for_the_group_already_sent(self) -> None:
        _, _, next_action = classify_read_rejection(
            self._MISSING,
            operation_id=ANALYSIS_QUERY_OPERATIONS["event"],
            request_inputs={"group_by_list": list(self._GENERATED)},
        )

        self.assertNotIn("add create_time/day", next_action)
        self.assertIn("already", next_action)
        self.assertIn("issue #23", next_action)

    def test_contradicted_claim_is_upstream_and_retryable(self) -> None:
        """Acceptance 2: a self-contradicting rejection is not a caller error."""

        with self.assertRaises(SemanticRejectedError) as caught:
            raise_read_rejection(
                self._MISSING,
                operation_id=ANALYSIS_QUERY_OPERATIONS["event"],
                request_inputs={"group_by_list": list(self._GENERATED)},
            )
        error = caught.exception
        self.assertEqual("upstream", error.category)
        self.assertTrue(error.retryable)

    def test_a_genuinely_missing_group_stays_a_caller_error(self) -> None:
        """Acceptance 4: the real caller mistake must keep its old classification."""

        with self.assertRaises(SemanticRejectedError) as caught:
            raise_read_rejection(
                self._MISSING,
                operation_id=ANALYSIS_QUERY_OPERATIONS["retention"],
                request_inputs={"group_by_list": [{"type": "user", "field": "$os"}]},
            )
        error = caught.exception
        self.assertEqual("caller", error.category)
        self.assertFalse(error.retryable)
        self.assertIn("add create_time/day", error.next_action)

    def test_retention_property_condition_is_the_observed_boundary(self) -> None:
        condition = {
            "field": "first_pay_time",
            "operator": "RANGE_IN",
            "type": "user",
            "value": ["private-start", "private-end"],
        }
        with self.assertRaises(UpstreamContradictedRequestError) as caught:
            raise_read_rejection(
                self._MISSING,
                operation_id=ANALYSIS_QUERY_OPERATIONS["retention"],
                request_inputs={
                    "group_by_list": list(self._GENERATED),
                    "property_condition": [condition],
                },
            )

        error = caught.exception
        self.assertEqual(("property_condition", "upstream", True), (
            error.field,
            error.category,
            error.retryable,
        ))
        self.assertIn("issues #21/#29", error.next_action)
        self.assertIn("metadata data_type", error.next_action)
        self.assertNotIn("private-start", str(error))
        self.assertNotIn("private-start", error.next_action)

    def test_unreviewed_retention_condition_does_not_get_batch_advice(self) -> None:
        with self.assertRaises(UpstreamContradictedRequestError) as caught:
            raise_read_rejection(
                {"extra": {"error": "private unreviewed rejection"}},
                operation_id=ANALYSIS_QUERY_OPERATIONS["retention"],
                request_inputs={
                    "group_by_list": list(self._GENERATED),
                    "property_condition": [{
                        "field": "first_pay_time",
                        "operator": "RANGE_IN",
                        "type": "user_property",
                        "value": [1, 2],
                    }],
                },
            )

        error = caught.exception
        self.assertEqual("property_condition", error.field)
        self.assertIn("unresolved Retention property-condition contract", error.next_action)
        self.assertIn("paired current-main probe", error.next_action)
        self.assertNotIn("--concurrency 1", error.next_action)
        self.assertNotIn("scalar entry", error.next_action)
        self.assertNotIn("private unreviewed rejection", str(error))

    def test_unclassified_rejection_stops_guessing_group_by_list(self) -> None:
        """Nothing in an event request points at a group; do not invent one."""

        field, _, _ = classify_read_rejection(
            {"extra": {"error": "private upstream detail"}},
            operation_id=ANALYSIS_QUERY_OPERATIONS["event"],
            request_inputs={"app_id": "1", "group_by_list": list(self._GENERATED)},
        )

        self.assertNotEqual("group_by_list", field)
