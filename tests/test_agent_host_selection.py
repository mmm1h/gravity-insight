from __future__ import annotations

import copy
import unittest

from unittest.mock import patch

from gravity_insight.agent import discover_capabilities, run_agent_command
from gravity_insight.agents.host_catalog import (
    SELECTION_SCHEMA_VERSION,
    host_product_catalog,
    validate_host_catalog_projection,
)
from gravity_insight.agents.host_selection import (
    EMPTY_SELECTION_GAP,
    DEFAULT_ROUTING_MODE,
    assess_host_product_selection,
    compile_host_product_selection,
    resolve_host_product_selection,
)
from gravity_insight.agents.product_inventory import canonical_capability_cards
from gravity_insight.agents.unavailable import registered_unavailable_gaps
from gravity_insight.cli import build_parser
from gravity_insight.client import GravityInsightClient
from gravity_insight.errors import InputValidationError


class _NoNetwork:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, *_args, **_kwargs):
        self.calls += 1
        raise AssertionError("host selection must not request Gravity")


class HostProductSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = GravityInsightClient.from_env()
        cls.catalog = host_product_catalog(cls.client)

    def response(self, *refs: str, decision: str | None = None) -> dict:
        count = len(refs)
        return {
            "schema_version": SELECTION_SCHEMA_VERSION,
            "catalog_sha256": self.catalog["catalog_sha256"],
            "query": "compare this week with last week using one analysis definition",
            "decision": decision or (
                "abstained" if not count else "selected" if count == 1 else "multiple_intents"
            ),
            "reason": {"summary": "catalog boundaries checked", "needs_clarification": not refs},
            "candidates": [
                {
                    "catalog_ref": ref,
                    "reason": {"goal_match": "requested result", "boundary_check": "neighbor excluded"},
                }
                for ref in refs
            ],
        }

    def test_host_catalog_is_exact_card_gap_projection_without_raw_operations(self) -> None:
        """Eleven registered gaps plus 98 products yield 109 host identities."""

        cards = canonical_capability_cards(self.client)
        gaps = registered_unavailable_gaps()
        refs = {item["catalog_ref"] for item in self.catalog["entries"]}
        self.assertEqual(109, len(refs))
        self.assertEqual(
            {card["selector"] for card in cards} | {f"gap:{gap['code']}" for gap in gaps},
            refs,
        )
        self.assertNotIn("analysis.event.list", refs)
        validate_host_catalog_projection(self.catalog, product_cards=cards, gaps=gaps)
        drifted = copy.deepcopy(self.catalog)
        drifted["entries"][0]["does_and_returns"] = "forged"
        with self.assertRaisesRegex(RuntimeError, "owner projection drift"):
            validate_host_catalog_projection(drifted, product_cards=cards, gaps=gaps)

    def test_zero_and_multiple_candidates_have_deterministic_canonical_gaps(self) -> None:
        query = self.response()["query"]
        empty = resolve_host_product_selection(query, self.response(), self.client)
        self.assertEqual(EMPTY_SELECTION_GAP, empty["capability_gaps"][0]["code"])
        self.assertNotIn("operation_id", empty["capability_gaps"][0])
        self.assertEqual(
            ["gravity", "agent-catalog", "categories"],
            empty["capability_gaps"][0]["next"]["argv"],
        )

        multiple = resolve_host_product_selection(
            query,
            self.response("composite:derived_metrics", "analysis.query.spec"),
            self.client,
        )
        gap = multiple["capability_gaps"][0]
        self.assertEqual("MULTIPLE_INTENTS", gap["code"])
        self.assertEqual(
            ["analysis.query.spec", "composite:derived_metrics"],
            gap["candidate_selectors"],
        )

    def test_malformed_forged_product_and_direct_operation_fail_closed(self) -> None:
        query = self.response()["query"]
        malformed = self.response("analysis.query.spec")
        malformed["candidates"][0]["reason"].pop("boundary_check")
        with self.assertRaisesRegex(InputValidationError, "HOST_SELECTION_REASON_INVALID"):
            compile_host_product_selection(query, malformed, self.client)

        for forged in ("product:not-registered", "analysis.event.list"):
            with self.subTest(forged=forged):
                report = assess_host_product_selection(
                    query, self.response(forged), self.client
                )
                self.assertFalse(report["allowed"])
                self.assertIn(
                    "HOST_PRODUCT_IDENTITY_MISMATCH",
                    {item["code"] for item in report["violations"]},
                )
        direct = self.response("analysis.query.spec")
        direct["candidates"][0]["operation"] = "analysis.event.list"
        self.assertFalse(assess_host_product_selection(query, direct, self.client)["allowed"])

    def test_single_product_is_repository_described_and_sdk_source_bound(self) -> None:
        query = self.response()["query"]
        result = resolve_host_product_selection(
            query, self.response("analysis.query.spec"), self.client
        )
        self.assertEqual("analysis.query.spec", result["candidates"][0]["selector"])
        self.assertEqual("host_catalog", result["routing_mode"])
        self.assertEqual("host_catalog", result["routing"]["mode"])
        self.assertFalse(result["routing"]["floor"])
        self.assertNotIn("upgrade", result["routing"])
        self.assertEqual("host_catalog", result["candidates"][0]["match"]["confidence"])
        self.assertEqual(
            "gravity.host-source.v1 sdk_contract/instruction",
            result["selection_receipt"]["source_boundary"],
        )
        self.assertIn("plan_node", result["candidates"][0])

    def test_selecting_a_mutation_product_has_no_write_effect(self) -> None:
        query = self.response()["query"]
        transport = _NoNetwork()
        with patch.object(self.client._executor._transport, "request", transport.request):
            result = resolve_host_product_selection(
                query, self.response("analysis.segment.mutation:delete"), self.client
            )
        card = result["candidates"][0]
        self.assertEqual(0, transport.calls)
        self.assertEqual("mutation", card["effect"])
        self.assertFalse(card["natural_language_auto_execute"])
        self.assertFalse(card["next"]["ready_without_input"])

    def test_cli_default_and_unspecified_behavior_remain_recognizer(self) -> None:
        import inspect
        from gravity_insight.agents.host_selection import RECOGNIZER_ROUTING_MODE

        args = build_parser().parse_args(["agent", "event analysis"])
        self.assertEqual(RECOGNIZER_ROUTING_MODE, DEFAULT_ROUTING_MODE)
        self.assertIsNone(args.routing)
        self.assertIsNone(
            inspect.signature(discover_capabilities).parameters["routing"].default
        )
        self.assertIsNone(args.host_selection)
        result = run_agent_command(args, self.client)
        self.assertEqual("discover_and_describe", result["mode"])
        self.assertEqual(DEFAULT_ROUTING_MODE, result["routing_mode"])
        self.assertEqual(DEFAULT_ROUTING_MODE, result["routing"]["mode"])
        self.assertTrue(result["routing"]["floor"])
        self.assertIn("host_catalog", result["routing"]["upgrade"]["next"]["then_argv"])
        self.assertIn(
            "Prefer a recipe",
            result["next_action"],
        )
        self.assertNotIn("routing", result["next_action"])
        self.assertEqual("analysis.query.spec:event", result["candidates"][0]["selector"])

    def test_cli_selection_implies_host_without_weakening_explicit_arms(self) -> None:
        import json
        from gravity_insight.agents.host_selection import (
            HOST_ROUTING_MODE,
            RECOGNIZER_ROUTING_MODE,
        )

        query = self.response()["query"]
        selection = self.response("analysis.query.spec")
        selection_json = json.dumps(selection)
        parser = build_parser()

        implied = run_agent_command(
            parser.parse_args(["agent", query, "--host-selection", selection_json]),
            self.client,
        )
        explicit = run_agent_command(
            parser.parse_args([
                "agent", query, "--routing", HOST_ROUTING_MODE,
                "--host-selection", selection_json,
            ]),
            self.client,
        )
        self.assertEqual(
            [HOST_ROUTING_MODE, HOST_ROUTING_MODE],
            [implied["routing_mode"], explicit["routing_mode"]],
        )

        from gravity_insight.find_input import load_json_input

        with patch(
            "gravity_insight.find_input.load_json_input", wraps=load_json_input
        ) as load:
            with self.assertRaisesRegex(ValueError, "--input is required"):
                run_agent_command(
                    parser.parse_args([
                        "agent", query, "--routing", HOST_ROUTING_MODE,
                    ]),
                    self.client,
                )
        load.assert_called_once_with(None, required=True)

        with self.assertRaises(InputValidationError) as caught:
            run_agent_command(
                parser.parse_args([
                    "agent", query, "--routing", RECOGNIZER_ROUTING_MODE,
                    "--host-selection", selection_json,
                ]),
                self.client,
            )
        self.assertEqual("routing", caught.exception.field)
        self.assertIn("invalid Agent routing inputs", str(caught.exception))
        self.assertIn("explicitly set to host_catalog", caught.exception.next_action)

    def test_discover_capabilities_routes_from_selection_presence(self) -> None:
        from gravity_insight.agents.host_selection import (
            HOST_ROUTING_MODE,
            RECOGNIZER_ROUTING_MODE,
        )

        query = self.response()["query"]
        selection = self.response("analysis.query.spec")
        floor = discover_capabilities(query, client=self.client)
        selected = discover_capabilities(
            query, client=self.client, host_selection=selection
        )
        for label, result, mode, is_floor in (
            ("without-selection", floor, RECOGNIZER_ROUTING_MODE, True),
            ("with-selection", selected, HOST_ROUTING_MODE, False),
        ):
            with self.subTest(selection=label):
                self.assertEqual(mode, result["routing"]["mode"])
                self.assertEqual(is_floor, result["routing"]["floor"])
        with self.assertRaises(InputValidationError):
            discover_capabilities(
                query,
                client=self.client,
                routing=RECOGNIZER_ROUTING_MODE,
                host_selection=selection,
            )

    def test_batch_and_cli_input_route_each_question_from_its_selection(self) -> None:
        import json
        from gravity_insight.agents.batch import capabilities_many
        from gravity_insight.agents.host_selection import (
            HOST_ROUTING_MODE,
            RECOGNIZER_ROUTING_MODE,
        )

        query = self.response()["query"]
        selection = self.response("analysis.query.spec")
        questions = [
            {"id": "floor", "query": "event analysis"},
            {"id": "host", "query": query, "host_selection": selection},
        ]
        core = capabilities_many(questions, client=self.client)
        cli = run_agent_command(
            build_parser().parse_args([
                "agent", "--input", json.dumps({"questions": questions}),
            ]),
            self.client,
        )
        for surface, result in (("core", core), ("cli-input", cli)):
            with self.subTest(surface=surface):
                self.assertEqual(
                    [RECOGNIZER_ROUTING_MODE, HOST_ROUTING_MODE],
                    [item["result"]["routing_mode"] for item in result["results"]],
                )
                self.assertEqual([True, False], [
                    item["result"]["routing"]["floor"] for item in result["results"]
                ])

        explicit_recognizer = run_agent_command(
            build_parser().parse_args([
                "agent", "--routing", RECOGNIZER_ROUTING_MODE,
                "--input", json.dumps({"questions": [questions[1]]}),
            ]),
            self.client,
        )
        self.assertFalse(explicit_recognizer["ok"])
        self.assertIsNone(explicit_recognizer["results"][0]["result"])
        self.assertEqual(
            "AGENT_DISCOVERY_FAILED",
            explicit_recognizer["results"][0]["error"]["code"],
        )

    def test_gravity_facade_routes_from_selection_presence(self) -> None:
        from gravity_insight import GravitySDK
        from gravity_insight.agents.host_selection import (
            HOST_ROUTING_MODE,
            RECOGNIZER_ROUTING_MODE,
        )

        query = self.response()["query"]
        selection = self.response("analysis.query.spec")
        sdk = GravitySDK(insight=self.client)
        floor = sdk.capabilities(query)
        selected = sdk.capabilities(query, host_selection=selection)
        for label, result, mode, is_floor in (
            ("without-selection", floor, RECOGNIZER_ROUTING_MODE, True),
            ("with-selection", selected, HOST_ROUTING_MODE, False),
        ):
            with self.subTest(selection=label):
                self.assertEqual(mode, result["routing_mode"])
                self.assertEqual(is_floor, result["routing"]["floor"])

    def test_no_selection_still_needs_one_discovery_call(self) -> None:
        from gravity_insight.agents.host_selection import RECOGNIZER_ROUTING_MODE

        parser = build_parser()
        with patch(
            "gravity_insight.agent.discover_capabilities",
            wraps=discover_capabilities,
        ) as discovery, patch(
            "gravity_insight.agents.host_selection.resolve_host_product_selection"
        ) as host:
            result = run_agent_command(
                parser.parse_args(["agent", "event analysis"]), self.client
            )
        self.assertEqual(1, discovery.call_count)
        host.assert_not_called()
        self.assertGreater(result["count"], 0)
        self.assertEqual(RECOGNIZER_ROUTING_MODE, result["routing_mode"])

    def test_routing_arm_set_does_not_depend_on_the_default_policy(self) -> None:
        # The arm identities say which arms exist; DEFAULT_ROUTING_MODE only says
        # which one is the fallback when a caller sends no selection. Rebuilding
        # the module with a different fallback must leave the arm set untouched.
        # Without this, collapsing the two names back into one constant is silent:
        # every routing test still passes while the arm set degrades to a pair of
        # duplicates the moment anyone changes the fallback.
        import ast
        import types
        from pathlib import Path

        source_path = Path(resolve_host_product_selection.__code__.co_filename)
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "DEFAULT_ROUTING_MODE"
                for target in node.targets
            ):
                node.value = ast.copy_location(ast.Constant(value="host_catalog"), node.value)
                break
        else:
            self.fail("host selection has no default routing assignment")
        ast.fix_missing_locations(tree)
        rebound = types.ModuleType("gravity_insight.agents._host_selection_rebound_default")
        rebound.__file__ = str(source_path)
        rebound.__package__ = "gravity_insight.agents"
        exec(compile(tree, str(source_path), "exec"), rebound.__dict__)

        self.assertEqual(("recognizer", "host_catalog"), rebound.ROUTING_MODES)
        self.assertEqual("recognizer", rebound.RECOGNIZER_ROUTING_MODE)
        self.assertEqual("host_catalog", rebound.DEFAULT_ROUTING_MODE)

    def test_recognizer_upgrade_carries_selection_schema_and_copyable_example(self) -> None:
        result = run_agent_command(
            build_parser().parse_args(["agent", "event analysis"]),
            self.client,
        )
        upgrade = result["routing"]["upgrade"]
        required = {
            "schema_version", "catalog_sha256", "query", "decision",
            "reason", "candidates",
        }
        self.assertEqual(SELECTION_SCHEMA_VERSION, upgrade["selection_schema_version"])
        self.assertEqual(required, set(upgrade["selection_schema"]["required"]))
        example = upgrade["selection_example"]
        self.assertEqual(required, set(example))
        self.assertEqual("event analysis", example["query"])
        self.assertEqual(SELECTION_SCHEMA_VERSION, example["schema_version"])
        self.assertEqual(["gravity", "agent-catalog", "host"], upgrade["next"]["argv"])
        self.assertEqual(
            [
                "gravity", "agent", "event analysis", "--routing", "host_catalog",
                "--host-selection", "<gravity.host-product-selection.v1>",
            ],
            upgrade["next"]["then_argv"],
        )
        self.assertIn("catalog_sha256", upgrade["next_action"])

    def test_host_catalog_exposes_copyable_selection_template(self) -> None:
        template = self.catalog["selection_template"]
        required = set(self.catalog["response_schema"]["required"])
        self.assertEqual(required, set(template))
        self.assertEqual(SELECTION_SCHEMA_VERSION, template["schema_version"])
        self.assertEqual(self.catalog["catalog_sha256"], template["catalog_sha256"])
        self.assertEqual(
            [item["catalog_ref"] for item in self.catalog["entries"]],
            self.catalog["catalog_refs"],
        )

    def test_malformed_selection_names_the_broken_field(self) -> None:
        query = self.response()["query"]
        malformed = self.response("analysis.query.spec")
        malformed["candidates"][0]["reason"].pop("boundary_check")
        with self.assertRaises(InputValidationError) as caught:
            compile_host_product_selection(query, malformed, self.client)
        self.assertEqual("host_selection.candidates[0].reason", caught.exception.field)
        self.assertIn("host_selection.candidates[0].reason", caught.exception.next_action)
        self.assertIn("HOST_SELECTION_REASON_INVALID", str(caught.exception))

    def test_agent_input_rejects_single_query_object_with_legal_shape(self) -> None:
        from gravity_insight.agents.batch import validate_questions

        with self.assertRaises(InputValidationError) as caught:
            validate_questions({"query": "event trend"})
        self.assertEqual("input", caught.exception.field)
        self.assertIn('{"questions"', str(caught.exception))
        self.assertIn("query", str(caught.exception))
        with self.assertRaises(InputValidationError) as unknown:
            validate_questions({"questions": [{"id": "q1", "text": "event trend"}]})
        self.assertEqual("input.questions[0]", unknown.exception.field)
        self.assertIn("id", str(unknown.exception))
        self.assertIn("query", str(unknown.exception))
        rows = validate_questions({"questions": [{"id": "q1", "query": "event trend"}]})
        self.assertEqual(("q1", "event trend"), (rows[0].question_id, rows[0].query))

    def test_host_choice_beats_neighbor_keywords_without_lexical_calls(self) -> None:
        selection = self.response("composite:derived_metrics")
        selection["query"] = "event analysis retention funnel business pulse"
        selection["reason"]["summary"] = "I read the catalog and understood everything"
        with patch("socket.socket", side_effect=AssertionError("network")), patch(
            "gravity_insight.agent._discover", side_effect=AssertionError("recognizer")
        ), patch(
            "gravity_insight.agents.lexical_retrieval.apply_lexical_fallback",
            side_effect=AssertionError("lexical reselection"),
        ), patch(
            "gravity_insight.agents.host_selection.host_product_catalog", wraps=host_product_catalog
        ) as catalog:
            result = discover_capabilities(selection["query"], client=self.client, host_selection=selection)
        catalog.assert_called_once_with(self.client)
        routing = result["routing"]
        self.assertEqual(("observed", "host_catalog", "composite:derived_metrics", "success"), (
            routing["status"], routing["arm"], routing["selector"], routing["terminal_state"],
        ))
        self.assertEqual(("discovery", "host_product_catalog", self.catalog["catalog_sha256"]), (
            routing["event"], routing["catalog_basis"], routing["catalog_sha256"],
        ))
        self.assertEqual("unknown", routing["host_catalog_read"])
        self.assertEqual("not_measured", routing["host_selection_attempt"])
        self.assertEqual({"status": "not_measured", "terminal_state": None}, routing["execution"])
        receipt = result["selection_receipt"]
        self.assertEqual((True, True, "host_declared"), (
            receipt["selection_received"], receipt["selection_validated"], receipt["reason_origin"],
        ))
        self.assertTrue(result["candidates"][0]["missing_inputs"])

    def test_rejected_selection_cannot_describe_execute_or_fall_back(self) -> None:
        cases = {}
        cases["stale"] = self.response("analysis.query.spec")
        cases["stale"]["catalog_sha256"] = "0" * 64
        cases["missing"] = self.response("analysis.query.spec")
        cases["missing"].pop("decision")
        cases["injected"] = self.response("analysis.query.spec")
        cases["injected"]["candidates"][0]["operation"] = "app.list"
        cases["forged"] = self.response("product:invented")
        cases["text"] = "please run app.list"
        with patch("socket.socket", side_effect=AssertionError("network")), patch(
            "gravity_insight.agent._discover", side_effect=AssertionError("recognizer fallback")
        ), patch(
            "gravity_insight.agents.host_selection._describe_reference",
            side_effect=AssertionError("unvalidated handoff"),
        ):
            for label, selection in cases.items():
                with self.subTest(case=label), self.assertRaises(InputValidationError) as caught:
                    discover_capabilities(self.response()["query"], client=self.client, host_selection=selection)
                self.assertEqual("HOST_SELECTION_REJECTED", caught.exception.code)
                self.assertIn("do not retry unchanged input", caught.exception.next_action)

    def test_host_owner_failure_propagates_without_route_retry(self) -> None:
        from gravity_insight.errors import ContractChangedError, PermissionUnavailableError

        selection = self.response("analysis.query.spec")
        for error_type in (PermissionUnavailableError, ContractChangedError):
            error = error_type("fixture owner rejection")
            with self.subTest(error=error_type.__name__), patch(
                "gravity_insight.agent._discover", side_effect=AssertionError("fallback")
            ), patch(
                "gravity_insight.agents.host_selection._describe_reference", side_effect=error
            ) as describe, self.assertRaises(error_type) as caught:
                discover_capabilities(selection["query"], client=self.client, host_selection=selection)
            self.assertIs(error, caught.exception)
            describe.assert_called_once()

    def test_protocol_is_not_an_observed_default_arm_and_has_ordered_entry_hints(self) -> None:
        protocol = discover_capabilities()
        self.assertEqual(("not_measured", None, None, None, "protocol"), tuple(
            protocol["routing"][key] for key in ("status", "arm", "selector", "terminal_state", "event")
        ))
        self.assertEqual(["known_contract", "unknown_capability", "selection_floor", "execute"], [
            item["step"] for item in protocol["workflow"]
        ])
        self.assertEqual(self.catalog["workflow_ref"], protocol["workflow_ref"])
        self.assertIn("docs/agent-workflow.md", protocol["workflow_ref"])

    def test_floor_and_gap_observations_do_not_infer_host_failure_or_execution(self) -> None:
        floor = discover_capabilities("analysis.query.spec:event", client=self.client)
        weak = discover_capabilities("utterly unrelated quantum weather", client=self.client)
        empty = resolve_host_product_selection(self.response()["query"], self.response(), self.client)
        multiple = resolve_host_product_selection(
            self.response()["query"], self.response("analysis.query.spec", "composite:derived_metrics"), self.client
        )
        self.assertEqual("analysis.query.spec:event", floor["routing"]["selector"])
        self.assertEqual("workspace_catalog", floor["routing"]["catalog_basis"])
        self.assertEqual([], weak["candidates"])
        for result in (floor, weak, empty, multiple):
            with self.subTest(mode=result["mode"], status=result["status"]):
                self.assertEqual(result["routing_mode"], result["routing"]["arm"])
                self.assertEqual(result["status"], result["routing"]["terminal_state"])
                self.assertIsNone(result["routing"]["fallback_reason"])
                self.assertEqual("not_measured", result["routing"]["execution"]["status"])
        for result in (weak, empty, multiple):
            self.assertIsNone(result["routing"]["selector"])

    def test_recognizer_page_is_not_a_final_single_selection(self) -> None:
        result = discover_capabilities("event analysis", client=self.client, limit=1)
        self.assertGreater(result["total"], 1)
        self.assertEqual(1, len(result["candidates"]))
        self.assertIsNone(result["routing"]["selector"])

    def test_legacy_boundary_gap_without_code_keeps_refusal_and_diagnostics(self) -> None:
        for query in ("write promotion performance", "export order directory", "write monetization details"):
            with self.subTest(query=query), patch("socket.socket", side_effect=AssertionError("network")):
                result = discover_capabilities(query, client=self.client)
            self.assertEqual([], result["candidates"])
            self.assertEqual("capability_gap", result["routing"]["terminal_state"])
            self.assertEqual(("incomplete", ["DISCOVERY_GAP_REPORTED"]), (
                result["obligations"]["diagnostic_evidence"]["state"],
                result["obligations"]["diagnostic_evidence"]["evidence_codes"],
            ))
            self.assertTrue(result["capability_gaps"][0]["reason"])

    def test_skipped_workspace_catalog_has_no_observed_fingerprint(self) -> None:
        from pathlib import Path
        from gravity_insight.workspace import Workspace, WorkspaceDefaults
        from gravity_insight.agents.sources import workspace_catalog_fingerprint

        workspace = Workspace(
            path=None, root=Path("."), state_root=Path("tmp"), apps={},
            defaults=WorkspaceDefaults(None, "UTC", None), datasources={},
            products={"fictional": {"description": "fixture product"}}, recipes={},
        )
        self.assertNotEqual(workspace_catalog_fingerprint(None), workspace_catalog_fingerprint(workspace))
        with patch("gravity_insight.agent.catalog_cards", side_effect=AssertionError("catalog reread")):
            result = discover_capabilities(
                "composite:derived_metrics", client=self.client, workspace=workspace, domain="analysis"
            )
        self.assertIsNone(result["routing"]["catalog_sha256"])
        self.assertIsNone(result["routing"]["catalog_basis"])


if __name__ == "__main__":
    unittest.main()
