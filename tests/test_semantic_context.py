from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

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


def test_workspace_without_semantics_preserves_canonical_agent_bytes(tmp_path: Path) -> None:
    workspace = load_workspace(
        None, start=tmp_path, environ={}, cache_root=tmp_path / "cache"
    )
    result = discover_capabilities(
        "composite:business_pulse", client=None, workspace=workspace, domain="report"
    )
    payload = json.dumps(
        result, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert hashlib.sha256(payload).hexdigest() == (
        "22b15703ecf1604065a05aa3c8609c298eb8a73b0f67db49c126050d32bc15a6"
    )


def test_term_is_reachable_but_does_not_exist_without_context(tmp_path: Path) -> None:
    workspace = semantic_workspace(tmp_path)
    hit = discover_capabilities("nebula rollup", client=None, workspace=workspace)
    card = hit["candidates"][0]
    assert (card["selector"], card["description_origin"]) == (
        "composite:business_pulse",
        "caller_workspace",
    )
    assert card["result_source"]["tier"] == "caller_defined"
    assert hit["semantic_context"]["matches"][0]["declaration"] == "nebula-rollup"

    plain_path = tmp_path / "plain.toml"
    plain_path.write_text(workspace_text(), encoding="utf-8")
    plain = load_workspace(plain_path, environ={}, cache_root=tmp_path / "cache")
    miss = discover_capabilities("nebula rollup", client=EmptyClient(), workspace=plain)
    assert (miss["status"], miss["candidates"]) == ("capability_gap", [])
    assert "semantic_context" not in miss


def test_term_can_select_an_exact_registered_event(tmp_path: Path) -> None:
    workspace = semantic_workspace(
        tmp_path,
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
    assert (card["selector"], card["description_origin"]) == (
        "metadata:event:1001:FictionalOpened",
        "caller_workspace",
    )
    assert card["result_source"]["tier"] == "caller_defined"


def test_verified_query_copies_only_declared_input_into_run_handoff(tmp_path: Path) -> None:
    result = discover_capabilities(
        "show the orion applications",
        client=None,
        workspace=semantic_workspace(tmp_path),
    )
    card = result["candidates"][0]
    assert card["semantic_context"]["match_kind"] == "verified_query"
    assert card["missing_inputs"] == []
    assert card["plan_node"]["request"] == {
        "selector": "app.list",
        "input": {"page": 1, "page_size": 20},
    }
    assert card["result_source"]["semantic_verification"] == "caller_responsible"


def test_verified_query_is_exact_but_cannot_bypass_existing_multiple_intents(
    tmp_path: Path,
) -> None:
    hard_bound = discover_capabilities(
        "show the orion applications",
        client=None,
        workspace=semantic_workspace(
            tmp_path,
            '''[[semantic_context.terms]]
name = "orion-phrase"
phrases = ["orion applications"]
target = { kind = "product", ref = "composite:business_pulse" }
''',
        ),
    )
    assert hard_bound["candidates"][0]["selector"] == "app.list"

    guarded = discover_capabilities(
        "event analysis analysis context",
        client=None,
        workspace=semantic_workspace(
            tmp_path,
            '''[[semantic_context.verified_queries]]
name = "ambiguous-orion-call"
question = "event analysis analysis context"
operation = "app.list"
input = { page = 1, page_size = 20 }
''',
        ),
    )
    assert guarded["capability_gaps"][0]["code"] == "MULTIPLE_INTENTS"
    assert guarded["candidates"] == []


def test_semantics_cannot_bypass_ambiguity_negative_terms_or_exclusions(tmp_path: Path) -> None:
    workspace = semantic_workspace(tmp_path)
    ambiguous = discover_capabilities(
        "nebula rollup event analysis", client=None, workspace=workspace
    )
    rejected = discover_capabilities(
        "nebula rollup users", client=None, workspace=workspace
    )
    excluded = discover_capabilities(
        "archived nebula rollup", client=None, workspace=workspace
    )
    assert ambiguous["capability_gaps"][0]["code"] == "MULTIPLE_INTENTS"
    assert rejected["capability_gaps"][0]["code"] == "SEMANTIC_CONTEXT_TARGET_REJECTED"
    assert excluded["capability_gaps"][0]["code"] == "SEMANTIC_CONTEXT_EXCLUDED"
    assert not (ambiguous["candidates"] or rejected["candidates"] or excluded["candidates"])


@pytest.mark.parametrize(
    ("target", "preflight"),
    [
        ('{ kind = "product", ref = "composite:missing" }', True),
        ('{ kind = "operation", ref = "missing.operation" }', False),
    ],
)
def test_unknown_static_semantic_references_are_local_exit_four(
    tmp_path: Path, target: str, preflight: bool
) -> None:
    path = tmp_path / "gravity.toml"
    semantic = f'''[semantic_context]
schema_version = "gravity.semantic-context.v1"
[[semantic_context.terms]]
name = "fictional-missing"
phrases = ["fictional missing"]
target = {target}
'''
    path.write_text(workspace_text(semantic), encoding="utf-8")
    with pytest.raises(SemanticContextError) as raised:
        workspace = load_workspace(path, environ={}, cache_root=tmp_path / "cache")
        if preflight:
            discover_capabilities("fictional missing", client=None, workspace=workspace)
    detail = error_detail_from_exception(raised.value)
    assert (detail.code, detail.category, exit_code_for_error(raised.value)) == (
        "SEMANTIC_CONTEXT_INVALID",
        "local",
        4,
    )


@pytest.mark.parametrize("kind", ["event", "event_property", "user_property", "metric"])
@pytest.mark.parametrize("metadata_catalog_available", [True, False])
def test_unknown_metadata_references_fail_closed_in_agent_preflight(
    tmp_path: Path, kind: str, metadata_catalog_available: bool
) -> None:
    app = ', app = "demo"' if kind in {"event", "event_property", "user_property"} else ""
    semantic = f'''[semantic_context]
schema_version = "gravity.semantic-context.v1"
[[semantic_context.terms]]
name = "fictional-metadata"
phrases = ["fictional metadata"]
target = {{ kind = "{kind}", ref = "FictionalMissing"{app} }}
'''
    path = tmp_path / "gravity.toml"
    path.write_text(workspace_text(semantic), encoding="utf-8")
    workspace = load_workspace(path, environ={}, cache_root=tmp_path / "cache")
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
    with pytest.raises(SemanticContextError) as raised:
        discover_capabilities("fictional metadata", client=None, sources=sources)
    assert exit_code_for_error(raised.value) == 4
