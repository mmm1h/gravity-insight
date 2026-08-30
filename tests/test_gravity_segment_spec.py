from __future__ import annotations

import unittest
from copy import deepcopy
from typing import Any, Mapping

from gravity_insight.errors import InputValidationError
from gravity_insight.segment_spec import (
    compile_segment_spec,
    prepare_segment_spec,
    validate_segment_spec,
)
from gravity_insight.segment_spec_schema import segment_rule_spec_schema


def minimal_spec() -> dict[str, Any]:
    return {"name": "buyers", "start": "2026-08-01"}


def rich_spec() -> dict[str, Any]:
    return {
        **minimal_spec(),
        "end": "2026-08-08",
        "logic": "OR",
        "property_rules": {
            "logic": "OR",
            "groups": [{
                "rules": [{
                    "field": "region",
                    "source": "user",
                    "operator": "EQUALS",
                    "values": ["north"],
                }]
            }],
        },
        "event_rules": {
            "groups": [{
                "rules": [{
                    "event": "purchase",
                    "did": True,
                    "target": {
                        "field": "PresetAllCount",
                        "aggregation": "PresetAllCount",
                    },
                    "did_condition": {"operator": "GTE", "values": [1]},
                    "date_range": {
                        "type": "static",
                        "start": "2026-08-01",
                        "end": "2026-08-07",
                    },
                }]
            }],
        },
    }


class FakeClient:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    def validate(self, operation_id: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
        self.calls.append((operation_id, inputs))
        if not self.ok:
            return {
                "ok": False,
                "error": {"message": "unknown event", "field": "event_rules"},
            }
        return {
            "ok": True,
            "status": "needs_live_metadata",
            "live_metadata_dependencies": ["analysis.event.list"],
        }


class SegmentRuleSpecTests(unittest.TestCase):
    def test_schema_is_closed_standard_and_keeps_empty_rules_short(self) -> None:
        schema = segment_rule_spec_schema()
        self.assertEqual("analysis.segment.evaluate_percent", schema["operation_id"])
        self.assertEqual(["name", "start"], schema["spec_schema"]["required"])
        self.assertNotIn("app", schema["spec_schema"]["properties"])
        self.assertFalse(schema["spec_schema"]["additionalProperties"])
        self.assertEqual(2, len(schema["definitions"]["condition"]["oneOf"]))
        dynamic = schema["definitions"]["event_date_range"]["oneOf"][2]
        self.assertEqual(2, len(dynamic["allOf"]))
        self.assertEqual(
            {"$MPShow", "$PayEvent"}, set(schema["event_support"]["events"])
        )
        self.assertEqual({"unsupported"}, {item["status"] for item in schema["event_support"]["events"].values()})
        allowed = {"array", "boolean", "integer", "null", "number", "object", "string"}

        def inspect(value: Any) -> None:
            if isinstance(value, Mapping):
                declared = value.get("type")
                if isinstance(declared, str):
                    self.assertIn(declared, allowed)
                elif isinstance(declared, list):
                    self.assertTrue(set(declared) <= allowed)
                for child in value.values():
                    inspect(child)
            elif isinstance(value, list):
                for child in value:
                    inspect(child)

        inspect(schema)
        compiled = compile_segment_spec(minimal_spec(), app=101)
        self.assertEqual([], compiled.inputs["user_property_rules"]["groups"])
        self.assertEqual([], compiled.inputs["user_event_rules"]["groups"])
        self.assertIsNone(compiled.inputs["date_range"]["end_date"])

    def test_rich_spec_compiles_to_the_stable_operation_shape(self) -> None:
        compiled = compile_segment_spec(rich_spec(), app=101)
        self.assertEqual("analysis.segment.evaluate_percent", compiled.operation_id)
        self.assertEqual("101", compiled.inputs["app_id"])
        self.assertEqual("OR", compiled.inputs["cond_logic"])
        condition = compiled.inputs["user_property_rules"]["groups"][0]["conditions"][0]
        self.assertEqual(
            {"field": "region", "type": "user", "operator": "EQUALS", "value": ["north"]},
            condition,
        )
        event = compiled.inputs["user_event_rules"]["groups"][0]["conditions"][0]
        self.assertEqual("purchase", event["event_name"])
        self.assertEqual(
            {"date_type": "static", "date": ["2026-08-01", "2026-08-07"]},
            event["date_range"],
        )
        self.assertFalse(hasattr(compiled, "plan_node"))

    def test_local_whitelists_and_semantics_fail_before_client_validation(self) -> None:
        cases: list[tuple[str, dict[str, Any], str]] = []
        for label, mutate, message in (
            ("embedded app", lambda value: value.update({"app": 101}), "allowed fields"),
            ("unknown top-level", lambda value: value.update({"FE_CONFIG": "{}"}), "allowed fields"),
            ("reversed dates", lambda value: value.update({"end": "2026-07-31"}), "allowed range"),
            ("bad logic", lambda value: value.update({"logic": "XOR"}), "allowed values"),
            ("raw group key", lambda value: value.update({"property_rules": {"groups": [], "sql": "x"}}), "allowed fields"),
            ("sensitive property", lambda value: value.update({"property_rules": {"groups": [{"rules": [{"field": "password", "source": "user", "operator": "EQUALS", "values": ["x"]}]}]}}), "blocked"),
            ("unsupported did operator", lambda value: value.update({"event_rules": {"groups": [{"rules": [{"event": "purchase", "did": True, "target": {"field": "PresetAllCount", "aggregation": "PresetAllCount"}, "did_condition": {"operator": "TRUE"}, "date_range": {"type": "quick", "range": "last7day"}}]}]}}), "allowed values"),
        ):
            candidate = deepcopy(minimal_spec())
            mutate(candidate)
            cases.append((label, candidate, message))
        for label, candidate, message in cases:
            with self.subTest(label=label), self.assertRaisesRegex(InputValidationError, message) as caught:
                compile_segment_spec(candidate, app=101)
            if label != "sensitive property":
                self.assertIn("actual value", str(caught.exception))

    def test_known_unsupported_preset_events_fail_with_public_field_path(self) -> None:
        for event_name in ("$MPShow", "$PayEvent"):
            candidate = rich_spec()
            candidate["event_rules"]["groups"][0]["rules"][0]["event"] = event_name
            with self.subTest(event=event_name), self.assertRaises(InputValidationError) as caught:
                compile_segment_spec(candidate, app=101)
            self.assertEqual("event_rules.groups[0].rules[0].event", caught.exception.field)
            self.assertIn("actual value", str(caught.exception))
            self.assertIn(event_name, str(caught.exception))
            self.assertIn("gravity metadata events", str(caught.exception.next_action))
            self.assertIn("do not retry", str(caught.exception.next_action))

    def test_validation_delegates_metadata_and_preview_redacts_values(self) -> None:
        client = FakeClient()
        compiled, validation = validate_segment_spec(client, rich_spec(), app=101)
        self.assertEqual("needs_live_metadata", validation["status"])
        self.assertEqual([(compiled.operation_id, compiled.inputs)], client.calls)
        preview = prepare_segment_spec(client, rich_spec(), app=101)
        self.assertTrue(preview["input_values_redacted"])
        self.assertEqual("<redacted>", preview["compiled_input"]["name"])
        self.assertEqual(["<redacted>"], preview["compiled_input"]["user_property_rules"]["groups"][0]["conditions"][0]["value"])
        self.assertNotIn("north", repr(preview))
        self.assertIsNone(preview["plan_node"])
        with self.assertRaisesRegex(InputValidationError, "unknown event"):
            validate_segment_spec(FakeClient(ok=False), rich_spec(), app=101)


if __name__ == "__main__":
    unittest.main()
