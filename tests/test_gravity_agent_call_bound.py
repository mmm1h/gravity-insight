from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk import GravitySDK
from gravity_sdk.agent import run_agent_command
from gravity_sdk.agent_analysis_task import analysis_task_cards
from gravity_sdk.agent_capabilities import composite_capability_inventory
from gravity_sdk.agent_handoff import attach_plan_node
from gravity_sdk.domains import MULTIDIM_METADATA_OPERATIONS
from gravity_sdk.plan import (
    PlanAdapter,
    PlanAdapters,
    PlanValidationError,
    execute_plan,
    validate_plan,
)


def _args(query: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        query=query, domain=None, platform=None, limit=3, continuation=None,
        input=None,
    )


class _NoOperations:
    def search_operations(self, *_args, **_options):
        return {"operations": [], "continuation_token": None}


def _card(query: str, client=None) -> dict:
    result = run_agent_command(_args(query), client)
    return result["candidates"][0]


def _scenarios(card: dict) -> dict[str, dict]:
    return {item["id"]: item for item in card["call_bound"]["scenarios"]}


class AgentCallBoundTests(unittest.TestCase):
    def test_current_nine_paths_expose_conditional_lower_bounds(self) -> None:
        references = (
            "composite:saved_analysis",
            "composite:dashboard_analysis",
            "composite:dashboard_snapshot",
            "composite:segment_snapshot",
            "composite:analysis_template",
        )
        for query in references:
            with self.subTest(query=query):
                scenarios = _scenarios(_card(query))
                self.assertEqual(3, scenarios["unknown_reference"]["minimum_calls"])
                combined = scenarios["unknown_app_and_reference"]
                self.assertEqual(4, combined["minimum_calls"])
                self.assertEqual(2, combined["discovery_calls"])
        for query in ("composite:multidim", "composite:promotion_performance"):
            with self.subTest(query=query):
                scenarios = _scenarios(_card(query))
                self.assertEqual(3, scenarios["unknown_physical_inputs"]["minimum_calls"])
                combined = scenarios["unknown_app_and_physical_inputs"]
                self.assertEqual(3, combined["minimum_calls"])
                self.assertEqual("gravity.batch.v1", combined["input_sources"][0]["selector"])
                selectors = combined["input_sources"][0]["selectors"]
                expected = (
                    ["app.list", *MULTIDIM_METADATA_OPERATIONS]
                    if query.endswith("multidim")
                    else ["app.list", "promotion.metric.list"]
                )
                self.assertEqual(expected, selectors)
        with patch("gravity_sdk.find.search_metadata", side_effect=OSError):
            analysis = _scenarios(
                _card("purchase trend", _NoOperations())
            )
        self.assertEqual(
            4, analysis["physical_inputs_catalog_unsynced"]["minimum_calls"]
        )
        self.assertEqual(
            "missing", analysis["physical_inputs_catalog_unsynced"]["catalog_status"]
        )
        app = _scenarios(_card("analysis context", _NoOperations()))["unknown_app"]
        self.assertEqual((3, "app.list"), (
            app["minimum_calls"], app["input_sources"][0]["selector"]
        ))

        available = attach_plan_node(
            analysis_task_cards("purchase trend", metadata_rows=[])[0],
            "purchase trend",
        )
        self.assertNotIn(
            "physical_inputs_catalog_unsynced", _scenarios(available)
        )

    def test_all_fixed_composite_cards_expose_the_contract_on_the_plan_node(self) -> None:
        for definition in composite_capability_inventory():
            query = f"composite:{definition['name']}"
            with self.subTest(query=query):
                card = _card(query, _NoOperations())
                self.assertEqual(query, card["selector"])
                self.assertEqual(card["call_bound"], card["plan_node"]["call_bound"])

    def test_cli_sdk_card_and_plan_node_expose_the_same_contract(self) -> None:
        query = "composite:saved_analysis"
        cli_card = _card(query)
        sdk_card = GravitySDK(
            insight_factory=lambda: self.fail("offline composite built a client")
        ).capabilities(query)["candidates"][0]
        self.assertEqual(cli_card["call_bound"], sdk_card["call_bound"])
        self.assertEqual(cli_card["call_bound"], cli_card["plan_node"]["call_bound"])
        self.assertEqual(
            "required_inputs_known",
            cli_card["call_bound"]["unknown_capability_assumes"],
        )

    def test_plan_is_backward_compatible_and_call_bound_is_advisory(self) -> None:
        card = _card("composite:saved_analysis")
        node = card["plan_node"]
        validate_plan({"schema_version": "gravity.plan.v1", "nodes": [node]})
        legacy = copy.deepcopy(node)
        legacy.pop("call_bound")
        validate_plan({"schema_version": "gravity.plan.v1", "nodes": [legacy]})

        calls: list[str] = []
        adapter = PlanAdapter(
            execute=lambda request, context: calls.append(context.node_id) or {"ok": True},
            validate=lambda request, context: None,
        )
        for selected in (legacy, node):
            execute_plan(
                {"schema_version": "gravity.plan.v1", "nodes": [selected]},
                adapters=PlanAdapters(composite=adapter),
                workspace=object(),
            )
        self.assertEqual([node["id"], node["id"]], calls)

        malformed = copy.deepcopy(node)
        malformed["call_bound"]["scenarios"][0]["minimum_calls"] = 9
        with self.assertRaises(PlanValidationError):
            validate_plan({"schema_version": "gravity.plan.v1", "nodes": [malformed]})


if __name__ == "__main__":
    unittest.main()
