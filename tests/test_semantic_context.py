from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from gravity_sdk.agent import discover_capabilities
from gravity_sdk.agent_batch_sources import AgentSourceSnapshot
from gravity_sdk.agent_capabilities import composite_capability_inventory
from gravity_sdk.errors import error_detail_from_exception, exit_code_for_error
from gravity_sdk.workspace import load_workspace
from gravity_sdk.workspace_semantic_context import SemanticContextError


class EmptyClient:
    def operations(self, **_options):
        return []

    def search_operations(self, *_args, **_options):
        return {"operations": [], "continuation_token": None}


def workspace_text(semantic: str = "") -> str:
    return f'''schema_version = 1
[apps]
demo = 1001
[defaults]
app = "demo"
timezone = "Asia/Shanghai"
time_window = "latest-safe-day"
[datasources]
[products]
{semantic}
'''


def semantic_workspace(tmp_path: Path, extra: str = ""):
    path = tmp_path / "gravity.toml"
    path.write_text(
        workspace_text(
            '''[semantic_context]
schema_version = "gravity.semantic-context.v1"
instructions = "Keep the fictional mapping literal."
[[semantic_context.terms]]
name = "nebula-rollup"
phrases = ["nebula rollup"]
description = "Fictional overview mapping."
target = { kind = "product", ref = "composite:business_pulse" }
[[semantic_context.exclusions]]
name = "archived-nebula"
when = ["archived nebula"]
reason = "The fictional archived shape is excluded."
target = { kind = "product", ref = "composite:business_pulse" }
[[semantic_context.verified_queries]]
name = "orion-app-list"
question = "show the orion applications"
description = "Fictional verified call."
operation = "app.list"
input = { page = 1, page_size = 20 }
'''
            + extra
        ),
        encoding="utf-8",
    )
    return load_workspace(path, environ={}, cache_root=tmp_path / "cache")


class SemanticContextTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp_path = Path(temporary.name)

    def test_workspace_without_semantics_preserves_canonical_agent_bytes(self) -> None:
        workspace = load_workspace(
            None, start=self.tmp_path, environ={}, cache_root=self.tmp_path / "cache"
        )
        result = discover_capabilities(
            "composite:business_pulse", client=None, workspace=workspace, domain="report"
        )
        payload = json.dumps(
            result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "4d485b8fe48e67ced8a6ca662080b99e33090deecbf703c1c9304159cae3a063",
        )

    def test_term_is_reachable_but_does_not_exist_without_context(self) -> None:
        workspace = semantic_workspace(self.tmp_path)
        hit = discover_capabilities("nebula rollup", client=None, workspace=workspace)
        card = hit["candidates"][0]
        self.assertEqual(
            (card["selector"], card["description_origin"]),
            ("composite:business_pulse", "caller_workspace"),
        )
        self.assertEqual(card["result_source"]["tier"], "caller_defined")
        self.assertEqual(
            hit["semantic_context"]["matches"][0]["declaration"], "nebula-rollup"
        )

        plain_path = self.tmp_path / "plain.toml"
        plain_path.write_text(workspace_text(), encoding="utf-8")
        plain = load_workspace(
            plain_path, environ={}, cache_root=self.tmp_path / "cache"
        )
        miss = discover_capabilities("nebula rollup", client=EmptyClient(), workspace=plain)
        self.assertEqual((miss["status"], miss["candidates"]), ("capability_gap", []))
        self.assertNotIn("semantic_context", miss)

    def test_term_can_select_an_exact_registered_event(self) -> None:
        workspace = semantic_workspace(
            self.tmp_path,
        '''[[semantic_context.terms]]
name = "quasar-arrival"
phrases = ["quasar arrival"]
target = { kind = "event", ref = "FictionalOpened", app = "demo" }
''',
        )
        sources = AgentSourceSnapshot(
            workspace=workspace,
            operation_inventory=(),
            recipe_inventory=(),
            product_inventory=(),
            metadata_inventory=(
                {
                    "kind": "event",
                    "name": "FictionalOpened",
                    "cname": "Fictional opened event",
                    "app_id": "1001",
                    "operation_id": "event.list",
                },
            ),
            composite_inventory=composite_capability_inventory(),
            warnings=(),
            workspace_fingerprint="0" * 64,
            metadata_catalog_available=True,
        )
        result = discover_capabilities("quasar arrival", client=None, sources=sources)
        card = result["candidates"][0]
        self.assertEqual(
            (card["selector"], card["description_origin"]),
            ("metadata:event:1001:FictionalOpened", "caller_workspace"),
        )
        self.assertEqual(card["result_source"]["tier"], "caller_defined")

    def test_verified_query_copies_only_declared_input_into_run_handoff(self) -> None:
        result = discover_capabilities(
            "show the orion applications",
            client=None,
            workspace=semantic_workspace(self.tmp_path),
        )
        card = result["candidates"][0]
        self.assertEqual(card["semantic_context"]["match_kind"], "verified_query")
        self.assertEqual(card["missing_inputs"], [])
        self.assertEqual(
            card["plan_node"]["request"],
            {"selector": "app.list", "input": {"page": 1, "page_size": 20}},
        )
        self.assertEqual(
            card["result_source"]["semantic_verification"], "caller_responsible"
        )

    def test_verified_query_is_exact_but_cannot_bypass_existing_multiple_intents(self) -> None:
        hard_bound = discover_capabilities(
            "show the orion applications",
            client=None,
            workspace=semantic_workspace(
                self.tmp_path,
                '''[[semantic_context.terms]]
name = "orion-phrase"
phrases = ["orion applications"]
target = { kind = "product", ref = "composite:business_pulse" }
''',
            ),
        )
        self.assertEqual(hard_bound["candidates"][0]["selector"], "app.list")

        guarded = discover_capabilities(
            "event analysis analysis context",
            client=None,
            workspace=semantic_workspace(
                self.tmp_path,
                '''[[semantic_context.verified_queries]]
name = "ambiguous-orion-call"
question = "event analysis analysis context"
operation = "app.list"
input = { page = 1, page_size = 20 }
''',
            ),
        )
        self.assertEqual(guarded["capability_gaps"][0]["code"], "MULTIPLE_INTENTS")
        self.assertEqual(guarded["candidates"], [])

    def test_semantics_cannot_bypass_ambiguity_negative_terms_or_exclusions(self) -> None:
        workspace = semantic_workspace(self.tmp_path)
        ambiguous = discover_capabilities(
            "nebula rollup event analysis", client=None, workspace=workspace
        )
        rejected = discover_capabilities(
            "nebula rollup users", client=None, workspace=workspace
        )
        excluded = discover_capabilities(
            "archived nebula rollup", client=None, workspace=workspace
        )
        self.assertEqual(ambiguous["capability_gaps"][0]["code"], "MULTIPLE_INTENTS")
        self.assertEqual(
            rejected["capability_gaps"][0]["code"], "SEMANTIC_CONTEXT_TARGET_REJECTED"
        )
        self.assertEqual(
            excluded["capability_gaps"][0]["code"], "SEMANTIC_CONTEXT_EXCLUDED"
        )
        self.assertFalse(
            ambiguous["candidates"] or rejected["candidates"] or excluded["candidates"]
        )

    def _assert_unknown_static_semantic_reference(
        self, target: str, preflight: bool
    ) -> None:
        with self.subTest(target=target, preflight=preflight):
            path = self.tmp_path / "gravity.toml"
            semantic = f'''[semantic_context]
schema_version = "gravity.semantic-context.v1"
[[semantic_context.terms]]
name = "fictional-missing"
phrases = ["fictional missing"]
target = {target}
'''
            path.write_text(workspace_text(semantic), encoding="utf-8")
            with self.assertRaises(SemanticContextError) as raised:
                workspace = load_workspace(
                    path, environ={}, cache_root=self.tmp_path / "cache"
                )
                if preflight:
                    discover_capabilities(
                        "fictional missing", client=None, workspace=workspace
                    )
            detail = error_detail_from_exception(raised.exception)
            self.assertEqual(
                (detail.code, detail.category, exit_code_for_error(raised.exception)),
                ("SEMANTIC_CONTEXT_INVALID", "local", 4),
            )

    def test_unknown_product_static_semantic_reference_is_local_exit_four(self) -> None:
        self._assert_unknown_static_semantic_reference(
            '{ kind = "product", ref = "composite:missing" }', True
        )

    def test_unknown_operation_static_semantic_reference_is_local_exit_four(self) -> None:
        self._assert_unknown_static_semantic_reference(
            '{ kind = "operation", ref = "missing.operation" }', False
        )

    def _assert_unknown_metadata_reference_fails_closed(
        self, kind: str, metadata_catalog_available: bool
    ) -> None:
        with self.subTest(
            kind=kind, metadata_catalog_available=metadata_catalog_available
        ):
            app = (
                ', app = "demo"'
                if kind in {"event", "event_property", "user_property"}
                else ""
            )
            semantic = f'''[semantic_context]
schema_version = "gravity.semantic-context.v1"
[[semantic_context.terms]]
name = "fictional-metadata"
phrases = ["fictional metadata"]
target = {{ kind = "{kind}", ref = "FictionalMissing"{app} }}
'''
            path = self.tmp_path / "gravity.toml"
            path.write_text(workspace_text(semantic), encoding="utf-8")
            workspace = load_workspace(
                path, environ={}, cache_root=self.tmp_path / "cache"
            )
            sources = AgentSourceSnapshot(
                workspace=workspace,
                operation_inventory=(),
                recipe_inventory=(),
                product_inventory=(),
                metadata_inventory=(),
                composite_inventory=composite_capability_inventory(),
                warnings=(),
                workspace_fingerprint="0" * 64,
                metadata_catalog_available=metadata_catalog_available,
            )
            with self.assertRaises(SemanticContextError) as raised:
                discover_capabilities("fictional metadata", client=None, sources=sources)
            self.assertEqual(exit_code_for_error(raised.exception), 4)

    def test_unknown_event_metadata_reference_fails_closed_with_catalog(self) -> None:
        self._assert_unknown_metadata_reference_fails_closed("event", True)

    def test_unknown_event_metadata_reference_fails_closed_without_catalog(self) -> None:
        self._assert_unknown_metadata_reference_fails_closed("event", False)

    def test_unknown_event_property_metadata_reference_fails_closed_with_catalog(self) -> None:
        self._assert_unknown_metadata_reference_fails_closed("event_property", True)

    def test_unknown_event_property_metadata_reference_fails_closed_without_catalog(self) -> None:
        self._assert_unknown_metadata_reference_fails_closed("event_property", False)

    def test_unknown_user_property_metadata_reference_fails_closed_with_catalog(self) -> None:
        self._assert_unknown_metadata_reference_fails_closed("user_property", True)

    def test_unknown_user_property_metadata_reference_fails_closed_without_catalog(self) -> None:
        self._assert_unknown_metadata_reference_fails_closed("user_property", False)

    def test_unknown_metric_metadata_reference_fails_closed_with_catalog(self) -> None:
        self._assert_unknown_metadata_reference_fails_closed("metric", True)

    def test_unknown_metric_metadata_reference_fails_closed_without_catalog(self) -> None:
        self._assert_unknown_metadata_reference_fails_closed("metric", False)
