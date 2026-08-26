"""Validate the reproducible R17 dynamic-reference disposition ledger."""

from __future__ import annotations

import ast
from collections import Counter
from collections import deque
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

import scripts.generate_agent_module_reference_dispositions as checkpoint_generator
import scripts.validate_r17_canonical_source_errata as errata_validator
from scripts.audit_agent_module_references import (
    GENERATED_GOVERNANCE_FILES,
    GOVERNANCE_EXCLUSION_RULE,
    Finding,
    ReferenceScanner,
    is_generated_governance_artifact,
    make_module_map,
    scan_repository,
    source_key,
)
from scripts.generate_agent_module_reference_dispositions import (
    ACTIVE_BARE_FILES,
    ACTIVE_REFERENCE,
    AMBIGUOUS_REFERENCE,
    DATED_DECISION_RECORD,
    DELETED_MODULE_RECORD,
    RUNTIME_CONSUMER,
    build_document,
    checkpoint_sites,
    classify_active_bare_context as generator_classify_active_bare_context,
    _classify_reference as generator_classify_reference,
    render_document,
)
from scripts.validate_r17_canonical_source_errata import (
    ErrataValidationError,
    build_expected_source,
    derive_source_replacements,
    load_git_baseline,
    validate_bound_ledger,
    validate_final_state,
    validate_phase1_reviewed_state,
)


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "tests/fixtures/agent_module_reference_dispositions.json"
CHECKPOINT = ROOT / "tests/fixtures/agent_module_reference_checkpoint.json"
DIRECTIVE = ROOT / "specs/agent-runtime/directive.json"
CANONICAL_SOURCE = ROOT / "specs/agent-runtime/architecture-source.md"
INDEX_JSON = ROOT / "specs/agent-runtime/index.json"
INDEX_MARKDOWN = ROOT / "specs/agent-runtime/index.md"
R17_SPECIFICATION = ROOT / "specs/agent-runtime/R17-agent-module-package-migration.md"
ROADMAP = ROOT / "docs/roadmap.md"
TECHNICAL_DEBT = ROOT / "docs/maintainers/technical-debt.md"
R17_INVENTORY_START = "<!-- R17_INDEPENDENT_INVENTORY_JSON_START -->"
R17_INVENTORY_END = "<!-- R17_INDEPENDENT_INVENTORY_JSON_END -->"
R17_INVENTORY_SCHEMA = "gravity.r17-independent-responsibility-inventory.v1"
R17_COCHANGE_BASELINE = "f2e8eec1f3c0567e20ab8c0be6465cc4e2c52e59"
R17_ROLE_MARKERS = (
    ("agent_role", r"\bagent\b"),
    ("natural_language_boundary", r"natural-language"),
    ("caller_language", r"caller-language"),
    ("agent_facing", r"agent-facing"),
    ("host_product_selection", r"product-selection"),
    ("intent_boundary", r"\bintent\b"),
    ("lexical_retrieval", r"\blexical\b"),
    ("semantic_gap_support", r"semantic gaps?"),
    ("unavailable_journey", r"unavailable .*journey"),
    ("catalog_aware_discovery", r"catalog-aware discovery"),
    ("lazy_discovery_client", r"lazy client boundary"),
)
R17_PROTOCOL_PATTERN = re.compile(r"gravity\.[a-z0-9_.-]+\.v[0-9]+")
LEDGER_SHA256 = "9d5b4d197cd84a0da4bb644256c9df7670ec89b7258e710434ab1ac8fed8be20"
EXPECTED_CATEGORIES = {
    "agent_prefix_template": 2,
    "bare_agent_string": 101,
    "dynamic_import": 11,
    "module_owner_receiver": 7,
    "non_string_patch_expression": 117,
}
EXPECTED_DISPOSITIONS = {
    "no_migration_effect": 224,
    "rewrite_reference": 13,
    "rewrite_selector_data": 1,
}
ALLOWED_DISPOSITIONS = {
    "rewrite_reference",
    "rewrite_selector_data",
    "rewrite_consolidated_reference",
    "no_migration_effect",
    "runtime_verification_required",
    "blocker",
}
PAGINATION_MODULE = "gravity_sdk.agent_pagination"
PAGINATION_TARGET = "gravity_sdk.pagination_completeness"
RETAINED_MODULE = "gravity_sdk.agent_runtime_contracts"
FROZEN_BASELINE_EXCLUSION_RULE = (
    "Exclude only tmp/**, direct specs/agent-runtime/R17-*.md migration "
    "specifications, the checked-in disposition fixture and its validator, and "
    "the two scripts that produce this audit. These paths define, generate, or "
    "validate R17 governance metadata rather than consume migrated runtime "
    "modules. Do not exclude AGENTS.md; specs/agent-runtime/architecture-source.md, "
    "index.json, or index.md; docs/maintainers/technical-debt.md; "
    "tests/agent_migration_characterization.py; or any other src, docs, specs, "
    "or tests path."
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _canonical_sites_sha256(sites: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(
            sites,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _r17_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _r17_module_id(name: str, namespace: str = "gravity_sdk") -> str:
    if name == namespace:
        return "."
    prefix = namespace + "."
    _require(name.startswith(prefix), f"module is outside {namespace}: {name}")
    return name.removeprefix(prefix)


def _r17_assigned_string(
    node: ast.Assign | ast.AnnAssign, name: str
) -> str | None:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
        return None
    value = node.value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _r17_read_modules(package_root: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for path in sorted(package_root.rglob("*.py")):
        parts = list(path.relative_to(package_root).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        name = package_root.name + ("." + ".".join(parts) if parts else "")
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        strings = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        schemas = [
            value
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            if (value := _r17_assigned_string(node, "SCHEMA_VERSION")) is not None
        ]
        commands: set[str] = set()
        response_keys: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and node.args
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_parser"
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                commands.add(node.args[0].value)
            if isinstance(node, ast.Dict):
                response_keys.update(
                    key.value
                    for key in node.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                )
        records[name] = {
            "path": path,
            "package": is_package,
            "source": source,
            "tree": tree,
            "docstring": ast.get_docstring(tree) or "",
            "protocols": tuple(sorted(
                value for value in strings if R17_PROTOCOL_PATTERN.fullmatch(value)
            )),
            "schemas": tuple(sorted(schemas)),
            "functions": frozenset(
                node.name
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ),
            "commands": tuple(sorted(commands)),
            "response_keys": frozenset(response_keys),
        }
    return records


def _r17_existing(name: str, modules: set[str]) -> str | None:
    parts = name.split(".")
    for size in range(len(parts), 0, -1):
        candidate = ".".join(parts[:size])
        if candidate in modules:
            return candidate
    return None


def _r17_import_base(source: str, package: bool, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    parts = (source if package else source.rpartition(".")[0]).split(".")
    if node.level > 1:
        parts = parts[: -(node.level - 1)]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _r17_import_graph(
    records: dict[str, dict[str, Any]],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    modules = set(records)
    graph = {name: set() for name in modules}
    for source, record in records.items():
        for node in ast.walk(record["tree"]):
            targets: list[str | None]
            if isinstance(node, ast.Import):
                targets = [_r17_existing(alias.name, modules) for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = _r17_import_base(source, record["package"], node)
                targets = [_r17_existing(base, modules)] if node.module else []
                targets.extend(
                    f"{base}.{alias.name}"
                    if f"{base}.{alias.name}" in modules
                    else None
                    for alias in node.names
                    if alias.name != "*"
                )
            else:
                continue
            graph[source].update(
                target for target in targets if target is not None and target != source
            )
    reverse = {name: set() for name in modules}
    for source, targets in graph.items():
        for target in targets:
            reverse[target].add(source)
    return graph, reverse


def _r17_closure(graph: dict[str, set[str]], start: str) -> set[str]:
    selected = {start}
    queue = deque([start])
    while queue:
        source = queue.popleft()
        for target in sorted(graph[source]):
            if target not in selected:
                selected.add(target)
                queue.append(target)
    return selected


def _r17_role_markers(docstring: str) -> tuple[str, ...]:
    return tuple(
        name
        for name, pattern in R17_ROLE_MARKERS
        if re.search(pattern, docstring, flags=re.IGNORECASE)
    )


def _r17_analyze_source(package_root: Path) -> dict[str, Any]:
    records = _r17_read_modules(package_root)
    graph, reverse = _r17_import_graph(records)
    facade_candidates = [
        name
        for name, record in records.items()
        if not record["package"]
        and "gravity.agent.v1" in record["schemas"]
        and {"add_agent_command", "discover_capabilities", "run_agent_command"}
        <= record["functions"]
        and "agent" in record["commands"]
        and {"routing_mode", "candidates", "capability_gaps"}
        <= record["response_keys"]
    ]
    _require(len(facade_candidates) == 1, f"semantic facade: {facade_candidates}")
    facade = facade_candidates[0]
    closure = _r17_closure(graph, facade)
    markers = {
        name: _r17_role_markers(record["docstring"])
        for name, record in records.items()
    }
    marked = {
        name
        for name in closure
        if not records[name]["package"] and markers[name]
    } | {facade}
    members: set[str] = set()
    decisions: list[dict[str, Any]] = []
    for name in sorted(marked):
        record = records[name]
        compact_consumers = reverse[name] & marked
        other_consumers = reverse[name] - marked
        independent_schemas = [
            value
            for value in record["schemas"]
            if not value.startswith("gravity.agent")
        ]
        agent_protocol = any(
            value.startswith("gravity.agent") for value in record["protocols"]
        )
        if name == facade:
            include, reason = True, "unique_semantic_facade"
        elif independent_schemas:
            include, reason = False, "independent_primary_protocol"
        elif "agent_role" in markers[name] and agent_protocol:
            include, reason = True, "declared_agent_protocol_surface"
        elif compact_consumers and len(compact_consumers) >= len(other_consumers):
            include, reason = True, "compact_consumer_owned"
        else:
            include, reason = False, "broader_runtime_consumer_owned"
        if include:
            members.add(name)
        decisions.append({
            "module": name,
            "include": include,
            "reason": reason,
            "role_markers": list(markers[name]),
            "compact_consumers": compact_consumers,
            "other_consumers": other_consumers,
            "source_sha256": hashlib.sha256(
                record["source"].encode("utf-8")
            ).hexdigest(),
        })
    return {
        "records": records,
        "graph": graph,
        "reverse": reverse,
        "facade": facade,
        "closure": closure,
        "marked": marked,
        "members": members,
        "decisions": decisions,
    }


def _r17_set_observation(name: str, members: set[str], **extra: Any) -> dict[str, Any]:
    selected = sorted(_r17_module_id(member) for member in members)
    return {
        "name": name,
        "member_count": len(selected),
        "members_sha256": _r17_digest(selected),
        **extra,
    }


def _r17_pagerank_sweep(
    directed: dict[str, set[str]], implementation: set[str], start: str
) -> tuple[set[str], float, int]:
    graph = {name: set() for name in implementation}
    for source in implementation:
        for target in directed[source] & implementation:
            graph[source].add(target)
            graph[target].add(source)
    damping, tolerance = 0.85, 1e-14
    nodes = sorted(graph)
    rank = dict.fromkeys(nodes, 0.0)
    rank[start] = 1.0
    iterations = 0
    for iterations in range(1, 1001):
        updated = dict.fromkeys(nodes, 0.0)
        updated[start] = 1.0 - damping
        updated[start] += damping * sum(rank[name] for name in nodes if not graph[name])
        for source in nodes:
            if graph[source]:
                share = damping * rank[source] / len(graph[source])
                for target in graph[source]:
                    updated[target] += share
        if sum(abs(updated[name] - rank[name]) for name in nodes) <= tolerance:
            rank = updated
            break
        rank = updated
    order = sorted(
        nodes,
        key=lambda name: (
            -(rank[name] / len(graph[name]) if graph[name] else rank[name]),
            name,
        ),
    )
    total_volume = sum(len(targets) for targets in graph.values())
    selected: set[str] = set()
    volume = crossing = 0
    best: tuple[float, int, tuple[str, ...]] | None = None
    for name in order[:-1]:
        crossing += len(graph[name]) - 2 * len(graph[name] & selected)
        selected.add(name)
        volume += len(graph[name])
        denominator = min(volume, total_volume - volume)
        if denominator > 0:
            candidate = (crossing / denominator, len(selected), tuple(sorted(selected)))
            if best is None or candidate[:2] < best[:2]:
                best = candidate
    _require(best is not None, "import graph has no conductance cut")
    return set(best[2]), best[0], iterations


def _r17_cochange_component(records: dict[str, dict[str, Any]], start: str) -> set[str]:
    paths = {
        record["path"].relative_to(ROOT).as_posix(): name
        for name, record in records.items()
        if not record["package"]
    }
    output = subprocess.run(
        [
            "git", "log", "--format=commit:%H", "--name-only",
            R17_COCHANGE_BASELINE, "--", "src/gravity_sdk",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    parent = {name: name for name in paths.values()}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(left: str, right: str) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    changed: list[str] = []
    for line in (*output.splitlines(), "commit:end"):
        if line.startswith("commit:"):
            if changed:
                for member in changed[1:]:
                    union(changed[0], member)
            changed = []
        elif line in paths:
            changed.append(paths[line])
    root = find(start)
    return {name for name in parent if find(name) == root}


def build_r17_responsibility_inventory(package_root: Path | None = None) -> dict[str, Any]:
    package_root = package_root or ROOT / "src/gravity_sdk"
    analysis = _r17_analyze_source(package_root)
    records = analysis["records"]
    graph = analysis["graph"]
    reverse = analysis["reverse"]
    facade = analysis["facade"]
    members = analysis["members"]
    migration = json.loads(LEDGER.read_text(encoding="utf-8"))
    scope = migration["scope"]
    moves = {row["old_module"] for row in scope["one_to_one_moves"]}
    consolidation = scope["consolidate_delete"]["old_module"]
    retained = scope["retained_modules"]
    _require(len(retained) == 1, f"one retained module required: {retained}")
    excluded = retained[0]
    find_owners = [
        name for name, record in records.items() if "gravity.find.v1" in record["schemas"]
    ]
    _require(len(find_owners) == 1, f"one Find owner required: {find_owners}")
    implementation = {
        name for name, record in records.items() if not record["package"]
    }
    reverse_graph = {name: set() for name in graph}
    for source, targets in graph.items():
        for target in targets:
            reverse_graph[target].add(source)
    scc = _r17_closure(graph, facade) & _r17_closure(reverse_graph, facade)
    scc &= implementation
    unrestricted = analysis["closure"] & implementation
    conductance, conductance_value, iterations = _r17_pagerank_sweep(
        graph, implementation, facade
    )
    cochange = _r17_cochange_component(records, facade)
    rows: list[dict[str, Any]] = []
    for decision in analysis["decisions"]:
        name = decision["module"]
        if not decision["include"]:
            disposition = "not_a_member"
        elif name == facade:
            disposition = "retain_public_facade"
        elif name == consolidation:
            disposition = "consolidate_delete"
        elif name in moves:
            disposition = "move"
        else:
            disposition = "unmapped_member"
        compact = sorted(_r17_module_id(value) for value in decision["compact_consumers"])
        other = sorted(_r17_module_id(value) for value in decision["other_consumers"])
        rows.append({
            "module": _r17_module_id(name),
            "include": decision["include"],
            "reason": decision["reason"],
            "role_markers": decision["role_markers"],
            "compact_consumer_count": len(compact),
            "compact_consumers_sha256": _r17_digest(compact),
            "other_consumer_count": len(other),
            "other_consumers_sha256": _r17_digest(other),
            "source_sha256": decision["source_sha256"],
            "r17_disposition": disposition,
        })
    selected_ids = sorted(_r17_module_id(name) for name in members)
    comparable = members - {facade, consolidation}

    def boundary(module: str, label: str) -> dict[str, Any]:
        record = records[module]
        return {
            "label": label,
            "module": _r17_module_id(module),
            "selected": module in members,
            "in_unrestricted_facade_closure": module in analysis["closure"],
            "primary_schemas": list(record["schemas"]),
            "cli_commands": list(record["commands"]),
            "direct_consumer_count": len(reverse[module]),
            "direct_member_consumers": sorted(
                _r17_module_id(name) for name in reverse[module] & members
            ),
            "direct_other_consumer_count": len(reverse[module] - members),
            "direct_imports_to_members": sorted(
                _r17_module_id(name) for name in graph[module] & members
            ),
        }

    method = {
        "candidate_universe": (
            "Parse every Python module in the package; module names and paths label "
            "results but never filter candidates."
        ),
        "semantic_facade": (
            "Select the unique non-package owner of gravity.agent.v1 that defines "
            "the three facade callables, registers the agent command, and emits the "
            "three response-shape keys."
        ),
        "dependency_scope": (
            "Build an AST import graph from every lexical depth and take the facade's "
            "unrestricted directed closure."
        ),
        "responsibility_declaration": (
            "Match module docstrings against the closed role-marker regex list."
        ),
        "ownership_decision": (
            "Include the facade; reject a non-Agent primary schema; otherwise include "
            "an Agent protocol surface or a marked owner with at least one marked "
            "consumer and no more other than marked direct consumers."
        ),
        "post_selection_comparison": (
            "Load the R17 move ledger only after classification and compute differences."
        ),
        "role_markers": [
            {"id": name, "regex": pattern, "flags": ["IGNORECASE"]}
            for name, pattern in R17_ROLE_MARKERS
        ],
        "graph_methods": {
            "facade_scc": "directed mutual reachability",
            "unrestricted_closure": "directed static-import reachability",
            "import_conductance": (
                "degree-normalized personalized PageRank; damping 0.85; tolerance "
                "1e-14; deterministic minimum-conductance sweep"
            ),
            "cochange": "fixed-baseline all-history connected component",
        },
    }
    document: dict[str, Any] = {
        "schema_version": R17_INVENTORY_SCHEMA,
        "analysis_baseline": f"dev@{R17_COCHANGE_BASELINE}",
        "module_namespace": package_root.name,
        "method": method,
        "method_sha256": _r17_digest(method),
        "source_snapshot": {
            "package_module_count": len(records),
            "implementation_module_count": len(implementation),
            "tree_sha256": _r17_digest([
                {
                    "module": _r17_module_id(name),
                    "source_sha256": hashlib.sha256(
                        record["source"].encode("utf-8")
                    ).hexdigest(),
                }
                for name, record in sorted(records.items())
            ]),
        },
        "selector_summary": {
            "semantic_facade": _r17_module_id(facade),
            "unrestricted_closure_count": len(unrestricted),
            "role_candidate_count": len(analysis["marked"]),
            "member_count": len(members),
            "rejected_role_candidate_count": sum(not row["include"] for row in rows),
        },
        "members": selected_ids,
        "members_sha256": _r17_digest(selected_ids),
        "decisions": rows,
        "r17_comparison": {
            "ledger_sha256": hashlib.sha256(LEDGER.read_bytes()).hexdigest(),
            "move_count": len(moves),
            "independent_members_not_moves": sorted(
                _r17_module_id(name) for name in members - moves
            ),
            "moves_not_independent_members": sorted(
                _r17_module_id(name) for name in moves - members
            ),
            "action_normalized_members_equal_moves": comparable == moves,
            "action_normalized_members_not_moves": sorted(
                _r17_module_id(name) for name in comparable - moves
            ),
            "moves_not_action_normalized_members": sorted(
                _r17_module_id(name) for name in moves - comparable
            ),
        },
        "boundary_cases": [
            boundary(excluded, "broader_runtime_contracts_owner"),
            boundary(find_owners[0], "independent_find_surface"),
        ],
        "graph_observations": [
            _r17_set_observation("facade_scc", scc),
            _r17_set_observation("unrestricted_facade_closure", unrestricted),
            _r17_set_observation(
                "import_graph_minimum_conductance",
                conductance,
                conductance=conductance_value,
                pagerank_iterations=iterations,
                damping=0.85,
                tolerance=1e-14,
            ),
            _r17_set_observation(
                "cochange_component", cochange, baseline=R17_COCHANGE_BASELINE
            ),
        ],
        "conclusion": {
            "boundary": "inconsistent_but_adjustable",
            "complete_agent_domain_proven": False,
            "graph_methods_converged": False,
            "r17_82_moves_supported": comparable == moves,
        },
    }
    document["payload_sha256"] = _r17_digest(document)
    return document


def load_signed_r17_responsibility_inventory() -> dict[str, Any]:
    source = R17_SPECIFICATION.read_text(encoding="utf-8")
    _require(source.count(R17_INVENTORY_START) == 1, "inventory start marker")
    _require(source.count(R17_INVENTORY_END) == 1, "inventory end marker")
    payload = source.split(R17_INVENTORY_START, 1)[1].split(R17_INVENTORY_END, 1)[0]
    match = re.fullmatch(r"\s*```json\s*\n(.*)\n```\s*", payload, flags=re.DOTALL)
    _require(match is not None, "inventory must be one fenced JSON object")
    value = json.loads(match.group(1))
    _require(isinstance(value, dict), "inventory must be a JSON object")
    return value


def _validator_has_current_path_semantics(old_module: str, context: str) -> bool:
    """Conservatively detect consumers without using the generator classifier."""

    short = re.escape(old_module.removeprefix("gravity_sdk."))
    names = rf"(?:(?:gravity_sdk\.)?{short}|\.{short})"
    checks = (
        rf"\b(?:from|import)\s+{names}(?:\s+import\b|\b)",
        rf"{names}\s*\.(?!py\b)[A-Za-z_]\w*",
        rf"{names}\s*\(",
        rf"\b(?:getattr|__import__|import_module|patch|setattr)\s*\("
        rf"[^\n)]{{0,160}}{names}",
        rf"(?:src/gravity_sdk/)?{short}\.py",
    )
    return any(re.search(check, context, re.IGNORECASE) for check in checks)


def _validator_is_dated_decision(context: str) -> bool:
    return bool(
        re.search(
            r"(?:\u7acb\u9879|decision(?:\s+record)?)\s*[\uff08(]"
            r"\d{4}-\d{2}-\d{2}[\uff09)]",
            context,
            re.IGNORECASE,
        )
    )


def _validator_is_deleted_module_fact(old_module: str, context: str) -> bool:
    short = old_module.removeprefix("gravity_sdk.")
    if '"consolidated_deleted_modules"' in context and f'"{short}"' in context:
        return True
    normalized = " ".join(context.lower().split())
    position = normalized.find(short.lower())
    if position < 0:
        return False
    window = normalized[max(0, position - 120):position + len(short) + 120]
    return any(
        marker in window
        for marker in (
            "\u5408\u5e76\u5220\u9664",
            "consolidate/delete",
            "consolidated and deleted",
            "deleted module",
            "removed module",
        )
    )


def validate_ledger(document: dict[str, Any]) -> None:
    _require(
        document.get("schema_version")
        == "gravity.agent-module-reference-dispositions.v2",
        "invalid disposition-ledger schema",
    )
    source = document.get("source_audit", {})
    _require(source.get("method") == "direct repository scan", "audit is not direct")
    _require(
        source.get("file_universe")
        == "git ls-files --cached --others --exclude-standard",
        "audit file universe changed",
    )
    _require(
        source.get("governance_exclusion_rule") == FROZEN_BASELINE_EXCLUSION_RULE,
        "governance exclusion rule changed",
    )
    _require(
        source.get("scanner_path") == "scripts/audit_agent_module_references.py",
        "scanner is not repository-owned",
    )
    _require(
        source.get("generator_path")
        == "scripts/generate_agent_module_reference_dispositions.py",
        "generator is not repository-owned",
    )
    for field, value in source.items():
        if field.endswith("_path") or field == "command":
            _require("tmp/" not in str(value).replace("\\", "/"), f"tmp input at {field}")

    scope = document.get("scope", {})
    moves = scope.get("one_to_one_moves", [])
    _require(len(moves) == 82, "R17 must have exactly 82 one-to-one targets")
    old_targets = {item.get("old_module") for item in moves}
    new_targets = {item.get("new_module") for item in moves}
    move_mapping = {item.get("old_module"): item.get("new_module") for item in moves}
    _require(len(old_targets) == len(new_targets) == 82, "move targets must be unique")
    for item in moves:
        old = item.get("old_module")
        new = item.get("new_module")
        old_name = old.removeprefix("gravity_sdk.") if isinstance(old, str) else ""
        if old_name.startswith("agent_"):
            responsibility = old_name.removeprefix("agent_")
        elif old_name.endswith("_agent"):
            responsibility = old_name.removesuffix("_agent")
        else:
            responsibility = ""
        _require(
            bool(responsibility)
            and new == f"gravity_sdk.agents.{responsibility}",
            f"invalid one-to-one move: {old!r} -> {new!r}",
        )
    _require(PAGINATION_MODULE not in old_targets, "pagination cannot be one-to-one")
    _require(RETAINED_MODULE not in old_targets, "retained contracts cannot move")
    _require(
        scope.get("consolidate_delete")
        == {
            "old_module": PAGINATION_MODULE,
            "new_module": PAGINATION_TARGET,
            "symbol": "compact_pagination",
        },
        "pagination consolidation target changed",
    )
    _require(scope.get("retained_modules") == [RETAINED_MODULE], "retained scope changed")

    taxonomy = document.get("taxonomy", {})
    _require(ALLOWED_DISPOSITIONS <= set(taxonomy), "taxonomy is incomplete")
    sites = document.get("sites")
    _require(isinstance(sites, list) and len(sites) == 238, "ledger must have 238 sites")
    keys = [site.get("source_key") for site in sites]
    _require(len(set(keys)) == 238, "ledger source keys must be unique")

    categories: Counter[str] = Counter()
    dispositions: Counter[str] = Counter()
    for site in sites:
        key = site.get("source_key")
        source_site = site.get("source", {})
        expected_key = (
            f"{source_site.get('file')}:{source_site.get('line')}:"
            f"{source_site.get('column')}:{source_site.get('form')}"
        )
        _require(key == expected_key, f"source key does not bind coordinates: {key!r}")
        category = site.get("audit_category")
        disposition = site.get("disposition")
        _require(category in EXPECTED_CATEGORIES, f"unknown audit category at {key}")
        _require(disposition in ALLOWED_DISPOSITIONS, f"unclassified disposition at {key}")
        _require(bool(site.get("basis")), f"missing classification basis at {key}")
        _require(bool(site.get("evidence_kind")), f"missing evidence kind at {key}")
        action = site.get("migration_action", {})
        categories[category] += 1
        dispositions[disposition] += 1

        if disposition == "no_migration_effect":
            _require(action == {"kind": "none"}, f"no-effect row has action at {key}")
        elif disposition == "rewrite_reference":
            _require(action.get("kind") == "replace_text", f"invalid text action at {key}")
            _require(action.get("old_module") in old_targets, f"unknown source at {key}")
            _require(action.get("new_module") in new_targets, f"illegal target at {key}")
            _require(
                move_mapping[action["old_module"]] == action["new_module"],
                f"mismatched move pair at {key}",
            )
            old_text = action.get("old_text")
            new_text = action.get("new_text")
            if isinstance(old_text, str) and old_text.endswith(".py"):
                target_name = action["new_module"].removeprefix(
                    "gravity_sdk.agents."
                )
                expected_text = (
                    f"src/gravity_sdk/agents/{target_name}.py"
                    if old_text.startswith("src/gravity_sdk/")
                    else f"agents/{target_name}.py"
                )
                _require(
                    new_text == expected_text,
                    f"file rewrite target is ambiguous at {key}: {new_text!r}",
                )
                root_peer = ROOT / "src/gravity_sdk" / f"{target_name}.py"
                root_peer_module = f"gravity_sdk.{target_name}"
                if root_peer.is_file() and root_peer_module not in old_targets:
                    _require(
                        new_text != root_peer.name,
                        f"rewrite target aliases unrelated root file at {key}",
                    )
        elif disposition == "rewrite_selector_data":
            rewrites = action.get("rewrites", [])
            _require(
                action.get("kind") == "replace_selector_values"
                and len(rewrites) == 6
                and len({rewrite.get("symbol") for rewrite in rewrites}) == 6,
                f"root selector must have six rewrites at {key}",
            )
        elif disposition == "rewrite_consolidated_reference":
            _require(
                action.get("kind") == "replace_module"
                and action.get("old_module") == PAGINATION_MODULE
                and action.get("new_module") == PAGINATION_TARGET,
                f"invalid pagination rewrite at {key}",
            )
        elif disposition == "runtime_verification_required":
            verification = site.get("verification", {})
            _require(
                action.get("kind") == "verify_before_migration"
                and bool(verification.get("method"))
                and bool(verification.get("failure_action")),
                f"runtime verification is not executable at {key}",
            )
        else:
            _require(action.get("kind") == "block", f"blocker has no stop action at {key}")

        reference = site.get("module_reference", {})
        if reference.get("candidate_new_module") in new_targets:
            _require(
                move_mapping.get(reference.get("old_module"))
                == reference.get("candidate_new_module"),
                f"invalid no-effect candidate mapping at {key}",
            )
        if reference.get("old_module") == RETAINED_MODULE:
            _require(disposition == "no_migration_effect", f"retained owner moved at {key}")

        old_value = source_site.get("old_value")
        old_module = f"gravity_sdk.{old_value}"
        if category == "bare_agent_string" and source_site.get("file") in ACTIVE_BARE_FILES:
            context = source_site.get("audit_context")
            snippet = source_site.get("audit_snippet")
            _require(isinstance(context, str) and bool(context), f"missing context at {key}")
            _require(
                isinstance(snippet, str) and snippet in context,
                f"source snippet is outside bounded context at {key}",
            )
            current_path = _validator_has_current_path_semantics(
                old_module, context
            )
            if old_module == PAGINATION_MODULE:
                if current_path:
                    _require(
                        disposition
                        in {"rewrite_consolidated_reference", "blocker"},
                        f"active consumer syntax must rewrite or block at {key}",
                    )
                elif _validator_is_deleted_module_fact(old_module, context):
                    _require(
                        disposition == "no_migration_effect"
                        and site.get("reason_code") == "deleted_module_governance_fact"
                        and reference
                        == {
                            "old_module": PAGINATION_MODULE,
                            "candidate_new_module": PAGINATION_TARGET,
                        },
                        f"deleted-module fact must remain unchanged at {key}",
                    )
                else:
                    _require(
                        disposition == "blocker",
                        f"ambiguous pagination reference must block at {key}",
                    )
            elif old_module in old_targets:
                if current_path:
                    _require(
                        disposition in {"rewrite_reference", "blocker"},
                        f"active consumer syntax must rewrite or block at {key}",
                    )
                elif site.get("reason_code") == "dated_governance_decision_evidence":
                    _require(
                        _validator_is_dated_decision(context)
                        and disposition == "no_migration_effect"
                        and reference
                        == {
                            "old_module": old_module,
                            "candidate_new_module": move_mapping[old_module],
                        },
                        f"dated decision evidence must remain unchanged at {key}",
                    )
        elif old_module == PAGINATION_MODULE:
            if str(source_site.get("file", "")).startswith("docs/archive/"):
                _require(
                    disposition == "no_migration_effect"
                    and site.get("reason_code") == "frozen_historical_text",
                    f"archived pagination evidence must remain unchanged at {key}",
                )
            else:
                _require(
                    disposition in {"rewrite_consolidated_reference", "blocker"},
                    f"pagination consumer must rewrite or block at {key}",
                )

    _require(dict(categories) == EXPECTED_CATEGORIES, "audit denominator changed")
    _require(dict(dispositions) == EXPECTED_DISPOSITIONS, "dispositions changed")
    reason_counts = Counter(site.get("reason_code") for site in sites)
    _require(
        reason_counts["deleted_module_governance_fact"] == 3,
        "deleted-module governance facts changed",
    )
    _require(
        reason_counts["dated_governance_decision_evidence"] == 2,
        "dated governance decision evidence changed",
    )
    summary = document.get("summary", {})
    _require(summary.get("site_count") == len(sites), "declared site count differs")
    _require(summary.get("unique_source_keys") == len(set(keys)), "key count differs")
    _require(summary.get("unclassified_sites") == 0, "ledger has unclassified sites")
    _require(summary.get("blocker_count") == dispositions["blocker"], "blockers differ")
    _require(document.get("blockers") == [], "blocker list is not empty")
    _require(summary.get("audit_categories") == EXPECTED_CATEGORIES, "category summary differs")
    _require(summary.get("dispositions") == EXPECTED_DISPOSITIONS, "disposition summary differs")
    _require(
        summary.get("sites_sha256") == _canonical_sites_sha256(sites),
        "canonical site digest differs",
    )


def validate_checkpoint_receipt(document: dict[str, Any]) -> None:
    _require(
        document.get("schema_version")
        == "gravity.agent-module-reference-checkpoint.v1",
        "invalid checkpoint schema",
    )
    _require(
        document.get("receipt_role")
        == "live_checkpoint_scan_only; not authority for canonical errata replacements",
        "checkpoint role changed",
    )
    baseline = document.get("immutable_baseline_ledger", {})
    directive = json.loads(DIRECTIVE.read_text(encoding="utf-8"))
    derivation = directive["canonical_source_errata"]["allowed_source_replacements"]
    expected_binding = {
        "role": "errata_source_only_immutable_baseline",
        "repository_path": derivation["ledger_repository_path"],
        "git_blob": derivation["ledger_git_blob"],
        "sha256": derivation["ledger_sha256"],
        "schema_version": derivation["ledger_schema_version"],
    }
    _require(baseline == expected_binding, "checkpoint baseline binding changed")
    reviewed_at_revision = derivation.get("reviewed_at_revision")
    _require(
        reviewed_at_revision == errata_validator.REVIEWED_AT_REVISION,
        "checkpoint ledger review revision changed",
    )
    reviewed_blob = subprocess.run(
        [
            "git",
            "rev-parse",
            f"{reviewed_at_revision}:{baseline['repository_path']}",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
    ).stdout.strip()
    _require(
        reviewed_blob == baseline["git_blob"],
        "baseline blob differs at the fixed review revision",
    )
    current_blob = subprocess.run(
        ["git", "rev-parse", f"HEAD:{baseline['repository_path']}"],
        cwd=ROOT,
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
    ).stdout.strip()
    _require(current_blob == baseline["git_blob"], "baseline blob is not current")
    bound = subprocess.run(
        [
            "git",
            "cat-file",
            "blob",
            baseline["git_blob"],
        ],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    _require(bound == LEDGER.read_bytes(), "baseline ledger is not the bound Git object")
    _require(
        hashlib.sha256(bound).hexdigest() == baseline["sha256"],
        "baseline ledger digest changed",
    )

    scope = document.get("scope", {})
    moves = scope.get("one_to_one_moves", [])
    move_mapping = {
        item.get("old_module"): item.get("new_module") for item in moves
    }
    _require(len(move_mapping) == 82, "checkpoint move scope changed")
    site_records = document.get("sites")
    _require(isinstance(site_records, list), "checkpoint sites must be a list")
    sites = checkpoint_sites(document)
    classification_basis = document.get("classification_basis")
    _require(
        isinstance(classification_basis, list) and classification_basis,
        "checkpoint classification basis is missing",
    )
    keys = [site.get("source_key") for site in sites]
    _require(len(keys) == len(set(keys)), "checkpoint source keys repeat")
    dispositions: Counter[str] = Counter()
    reference_categories: Counter[str] = Counter()
    manual_categories: Counter[str] = Counter()
    reference_count = 0
    manual_count = 0
    overlap_count = 0
    for site in sites:
        key = site.get("source_key")
        source = site.get("source", {})
        expected_key = (
            f"{source.get('file')}:{source.get('line')}:"
            f"{source.get('column')}:{source.get('form')}"
        )
        _require(key == expected_key, f"checkpoint coordinate key drifted at {key}")
        tracked = site.get("tracked_sources")
        _require(
            isinstance(tracked, list)
            and tracked
            and set(tracked) <= {"reference", "manual_review"},
            f"invalid tracked denominator at {key}",
        )
        disposition = site.get("disposition")
        _require(disposition in ALLOWED_DISPOSITIONS, f"unknown disposition at {key}")
        basis_id = site.get("basis_id")
        basis = (
            classification_basis[basis_id]
            if isinstance(basis_id, int) and 0 <= basis_id < len(classification_basis)
            else {}
        )
        _require(bool(basis.get("basis")), f"missing basis at {key}")
        _require(bool(basis.get("evidence_kind")), f"missing evidence kind at {key}")
        dispositions[disposition] += 1
        if "reference" in tracked:
            reference_count += 1
            category = source.get("reference_category")
            _require(isinstance(category, str) and bool(category), f"missing reference category at {key}")
            reference_categories[category] += 1
        if "manual_review" in tracked:
            manual_count += 1
            manual_categories[site.get("audit_category")] += 1
        if set(tracked) == {"reference", "manual_review"}:
            overlap_count += 1

        action = site.get("migration_action", {})
        if disposition == "no_migration_effect":
            _require(action == {"kind": "none"}, f"no-effect action at {key}")
        elif disposition == "rewrite_reference":
            old = action.get("old_module")
            _require(
                action.get("kind") == "replace_text"
                and move_mapping.get(old) == action.get("new_module"),
                f"invalid exact move at {key}",
            )
        elif disposition == "rewrite_consolidated_reference":
            _require(
                action.get("kind") == "replace_module"
                and action.get("old_module") == PAGINATION_MODULE
                and action.get("new_module") == PAGINATION_TARGET,
                f"invalid consolidation at {key}",
            )
        elif disposition == "rewrite_selector_data":
            _require(
                action.get("kind") == "replace_selector_values"
                and len(action.get("rewrites", [])) == 6,
                f"invalid selector rewrite at {key}",
            )
        elif disposition == "blocker":
            _require(action == {"kind": "block"}, f"invalid blocker action at {key}")

        if site.get("audit_category") == "exact_reference":
            file = str(source.get("file", ""))
            old_value = source.get("old_value")
            old_module = old_value if old_value in move_mapping else None
            if old_module is None and isinstance(old_value, str):
                old_module = next(
                    (
                        old
                        for old in [*move_mapping, PAGINATION_MODULE, RETAINED_MODULE]
                        if old_value == "src/" + old.replace(".", "/") + ".py"
                    ),
                    old_value
                    if old_value in {PAGINATION_MODULE, RETAINED_MODULE}
                    else None,
                )
            sentinel = (
                file == "tests/test_agent_concept_deletions.py"
                and source.get("reference_category") == "string_reference"
            )
            if file.startswith("docs/archive/") or sentinel or old_module == RETAINED_MODULE:
                _require(disposition == "no_migration_effect", f"frozen exact reference moved at {key}")
            elif old_module == PAGINATION_MODULE:
                if site.get("reason_code") == "deleted_module_governance_fact":
                    _require(
                        disposition == "no_migration_effect",
                        f"pagination deletion fact changed at {key}",
                    )
                else:
                    _require(
                        disposition in {"rewrite_consolidated_reference", "blocker"},
                        f"pagination exact reference escaped at {key}",
                    )
            else:
                _require(
                    old_module in move_mapping
                    and disposition in {"rewrite_reference", "blocker"},
                    f"moved exact reference escaped at {key}",
                )

    summary = document.get("summary", {})
    _require(summary.get("tracked_site_count") == len(sites), "tracked count drifted")
    _require(summary.get("reference_site_count") == reference_count, "reference denominator drifted")
    _require(summary.get("manual_review_site_count") == manual_count, "manual denominator drifted")
    _require(summary.get("reference_manual_overlap_count") == overlap_count, "overlap drifted")
    _require(summary.get("manual_only_site_count") == manual_count - overlap_count, "manual-only count drifted")
    _require(summary.get("reference_categories") == dict(sorted(reference_categories.items())), "reference categories drifted")
    _require(summary.get("manual_review_categories") == dict(sorted(manual_categories.items())), "manual categories drifted")
    _require(summary.get("dispositions") == dict(sorted(dispositions.items())), "dispositions drifted")
    _require(summary.get("unique_source_keys") == len(set(keys)), "unique key count drifted")
    _require(summary.get("unclassified_sites") == 0, "checkpoint has unclassified sites")
    _require(summary.get("sites_sha256") == _canonical_sites_sha256(site_records), "checkpoint digest drifted")
    blockers = document.get("blockers")
    _require(isinstance(blockers, list), "checkpoint blockers must be a list")
    _require(summary.get("blocker_count") == len(blockers), "checkpoint blocker count drifted")


def _text_state_projection(text: str) -> dict[str, Any]:
    scalar_names = (
        "status",
        "dynamic_import_audit_classification.satisfied",
        "schema",
        "candidate_sites",
        "classified_sites",
        "unclassified_sites",
        "blocking_sites",
        "m0_bound_implementation_baseline",
        "ledger_sha256",
        "live_checkpoint_sha256",
        "live_checkpoint_tracked_sites",
    )
    projection: dict[str, Any] = {}
    for name in scalar_names:
        values = set(
            re.findall(
                rf"(?<![A-Za-z0-9_.]){re.escape(name)}=([A-Za-z0-9._-]+)",
                text,
            )
        )
        _require(len(values) == 1, f"ambiguous {name} marker: {values}")
        projection[name] = values.pop()
    artifact_markers = re.findall(
        r"m0_bound_artifact_sha256=(\{[^`\r\n]+\})",
        text,
    )
    _require(
        len(artifact_markers) == 1,
        f"ambiguous m0 artifact marker: {artifact_markers}",
    )
    try:
        projection["m0_bound_artifact_sha256"] = json.loads(artifact_markers[0])
    except json.JSONDecodeError as exc:
        raise AssertionError("invalid m0 artifact marker JSON") from exc
    return projection


def validate_active_scope_owner_projection(
    roadmap: str,
    technical_debt: str,
    ledger: dict[str, Any],
) -> None:
    moves = ledger.get("scope", {}).get("one_to_one_moves", [])
    _require(len(moves) == 82, "scope projection requires the reviewed 82 moves")
    expected = {
        "old_paths": len(moves) + 1,
        "moves": len(moves),
        "root_py": 495,
        "agents_implementation_py": len(moves),
    }
    roadmap_match = re.search(
        r"R17 \u7ec8\u6001\u987b\u79fb\u9664\s+(\d+)\s+\u4e2a\u65e7 deep module path"
        r"\uff08(\d+)\s+\u8fc1\u79fb\s*\+\s*pagination \u5220\u9664\uff09",
        roadmap,
    )
    _require(roadmap_match is not None, "roadmap has no unique R17 scope projection")
    roadmap_projection = {
        "old_paths": int(roadmap_match.group(1)),
        "moves": int(roadmap_match.group(2)),
    }
    _require(
        roadmap_projection
        == {"old_paths": expected["old_paths"], "moves": expected["moves"]},
        "roadmap R17 scope projection differs from the reviewed ledger",
    )

    debt_match = re.search(
        r"\u6839 `\.py` \u4e3a\s*(\d+)\u3001\s*\n?\s*`agents/` \u542b\s*(\d+)\s*\u4e2a\u5b9e\u73b0\u6a21\u5757",
        technical_debt,
    )
    _require(
        debt_match is not None,
        "technical-debt has no unique R17 exit-count projection",
    )
    debt_projection = {
        "root_py": int(debt_match.group(1)),
        "agents_implementation_py": int(debt_match.group(2)),
    }
    _require(
        debt_projection
        == {
            "root_py": expected["root_py"],
            "agents_implementation_py": expected["agents_implementation_py"],
        },
        "technical-debt R17 exit projection differs from the reviewed ledger",
    )


def validate_index_and_specification_state(
    index: dict[str, Any],
    index_markdown: str,
    specification: str,
    ledger: dict[str, Any],
    directive: dict[str, Any],
    *,
    ledger_bytes: bytes,
    checkpoint: dict[str, Any],
    checkpoint_bytes: bytes,
) -> None:
    requirement = next(
        item for item in index["requirements"] if item.get("id") == "R17"
    )
    _require(requirement["status"] == "specified", "R17 status changed")
    m0 = next(
        item
        for item in requirement["ready_prerequisites"]
        if item.get("id") == "m0_characterization"
    )
    dynamic = next(
        item
        for item in requirement["ready_prerequisites"]
        if item.get("id") == "dynamic_import_audit_classification"
    )
    summary = ledger["summary"]
    actual_dynamic_evidence = (
        dynamic["required_schema_version"] == ledger["schema_version"]
        and dynamic["candidate_sites"] == len(ledger["sites"])
        and dynamic["classified_sites"]
        == len(ledger["sites"]) - summary["unclassified_sites"]
        and dynamic["unclassified_sites"] == summary["unclassified_sites"] == 0
        and dynamic["blocking_sites"] == summary["blocker_count"] == 0
        and ledger["blockers"] == []
    )
    _require(
        dynamic["satisfied"] is actual_dynamic_evidence,
        "dynamic prerequisite boolean differs from ledger evidence",
    )

    ledger_sha256 = hashlib.sha256(ledger_bytes).hexdigest()
    derivation = directive["canonical_source_errata"]["allowed_source_replacements"]
    _require(
        ledger_sha256
        == dynamic["ledger_sha256"]
        == derivation["ledger_sha256"],
        "ledger digest differs across bytes, index, and directive",
    )
    checkpoint_sha256 = hashlib.sha256(checkpoint_bytes).hexdigest()
    checkpoint_summary = checkpoint["summary"]
    _require(
        dynamic["live_checkpoint_path"]
        == CHECKPOINT.relative_to(ROOT).as_posix()
        and dynamic["live_checkpoint_schema_version"]
        == checkpoint["schema_version"]
        and dynamic["live_checkpoint_sha256"] == checkpoint_sha256
        and dynamic["live_checkpoint_tracked_sites"]
        == checkpoint_summary["tracked_site_count"]
        and dynamic["live_checkpoint_unclassified_sites"]
        == checkpoint_summary["unclassified_sites"]
        == 0
        and dynamic["live_checkpoint_blocking_sites"]
        == checkpoint_summary["blocker_count"]
        == 0,
        "live checkpoint differs from the index prerequisite",
    )
    expected_projection = {
        "status": requirement["status"],
        "dynamic_import_audit_classification.satisfied": str(
            dynamic["satisfied"]
        ).lower(),
        "schema": dynamic["required_schema_version"],
        "candidate_sites": str(dynamic["candidate_sites"]),
        "classified_sites": str(dynamic["classified_sites"]),
        "unclassified_sites": str(dynamic["unclassified_sites"]),
        "blocking_sites": str(dynamic["blocking_sites"]),
        "m0_bound_implementation_baseline": m0["bound_implementation_baseline"],
        "m0_bound_artifact_sha256": m0["bound_artifact_sha256"],
        "ledger_sha256": ledger_sha256,
        "live_checkpoint_sha256": checkpoint_sha256,
        "live_checkpoint_tracked_sites": str(checkpoint_summary["tracked_site_count"]),
    }
    for label, text in (
        ("R17 specification", specification),
        ("index markdown", index_markdown),
    ):
        _require(
            _text_state_projection(text) == expected_projection,
            f"{label} state projection differs from index JSON",
        )

    revision = m0["bound_implementation_baseline"]
    _require(
        re.fullmatch(r"[0-9a-f]{40}", revision) is not None,
        "M0 baseline is not a full Git revision",
    )
    ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            m0["ancestor_candidate_commit"],
            revision,
        ],
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _require(ancestor.returncode == 0, "M0 candidate is not an ancestor of baseline")
    for path, expected_sha256 in m0["bound_artifact_sha256"].items():
        bound = subprocess.run(
            ["git", "show", f"{revision}:{path}"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        _require(
            hashlib.sha256(bound).hexdigest() == expected_sha256,
            f"M0 artifact digest differs at {path}",
        )

    combined = "\n".join(
        (json.dumps(index, ensure_ascii=False), index_markdown, specification)
    )
    for residue in (
        "gravity.agent-module-reference-dispositions.v1",
        "candidate_sites=227",
        "classified_sites=227",
        '"candidate_sites": 227',
        '"classified_sites": 227',
        '"site_count": 227',
        "3fa8fe6c3247fd5bdbcd9cded32f89b4644e8515",
        "87bd51daac6b88f7aa31bb740a84cc14a0a0147c",
    ):
        _require(residue not in combined, f"previous state residue: {residue}")


class AgentModuleReferenceDispositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = LEDGER.read_bytes()
        cls.document = json.loads(cls.raw)
        cls.checkpoint_raw = CHECKPOINT.read_bytes()
        cls.checkpoint = json.loads(cls.checkpoint_raw)
        cls.directive = json.loads(DIRECTIVE.read_text(encoding="utf-8"))

    def test_reviewed_fixture_sha256_is_bound(self) -> None:
        self.assertEqual(LEDGER_SHA256, hashlib.sha256(self.raw).hexdigest())

    def test_current_ledger_satisfies_the_machine_contract(self) -> None:
        validate_ledger(self.document)

    def test_checkpoint_receipt_satisfies_the_machine_contract(self) -> None:
        validate_checkpoint_receipt(self.checkpoint)

    def test_repository_scan_reproduces_the_checked_in_checkpoint(self) -> None:
        self.assertEqual(self.checkpoint_raw, render_document(build_document()))

    def test_checkpoint_dispositions_cover_both_scan_denominators(self) -> None:
        audit = scan_repository()
        reference_keys = {source_key(row) for row in audit.references}
        manual_keys = {source_key(row) for row in audit.manual_review}
        checkpoint_reference_keys = {
            site["source_key"]
            for site in checkpoint_sites(self.checkpoint)
            if "reference" in site["tracked_sources"]
        }
        checkpoint_manual_keys = {
            site["source_key"]
            for site in checkpoint_sites(self.checkpoint)
            if "manual_review" in site["tracked_sources"]
        }
        self.assertEqual(reference_keys, checkpoint_reference_keys)
        self.assertEqual(manual_keys, checkpoint_manual_keys)
        summary = self.checkpoint["summary"]
        self.assertEqual(summary["reference_site_count"], len(reference_keys))
        self.assertEqual(summary["manual_review_site_count"], len(manual_keys))
        self.assertEqual(summary["reference_manual_overlap_count"], len(reference_keys & manual_keys))
        self.assertEqual(summary["tracked_site_count"], len(reference_keys | manual_keys))
        if self.checkpoint["source_audit"]["owner_state"] == "baseline":
            self.assertEqual((907, 242, 240, 909), (
                len(reference_keys),
                len(manual_keys),
                len(reference_keys & manual_keys),
                len(reference_keys | manual_keys),
            ))

    def test_new_exact_dynamic_and_alias_loader_sites_cannot_escape_disposition(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tests", prefix="r17-tracked-") as temp:
            attack = Path(temp) / "attack.py"
            attack.write_text(
                "import importlib\n"
                'dynamic = importlib.import_module("gravity_sdk.agent_sources")\n'
                'alias = acquire("gravity_sdk.agent_sources")\n',
                encoding="utf-8",
            )
            generated = build_document()
            relative = attack.relative_to(ROOT).as_posix()
            sites = [
                site
                for site in checkpoint_sites(generated)
                if site["source"]["file"] == relative
            ]
        self.assertEqual(3, len(sites))
        self.assertEqual(
            {"dynamic_import", "string_reference"},
            {site["source"]["reference_category"] for site in sites},
        )
        self.assertTrue(all(site["disposition"] == "rewrite_reference" for site in sites))
        self.assertTrue(all(site["tracked_sources"] == ["reference"] for site in sites))

    def test_unknown_dynamic_domain_remains_a_blocker_after_regeneration(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tests", prefix="r17-blocker-") as temp:
            attack = Path(temp) / "attack.py"
            attack.write_text(
                "from importlib import import_module\n"
                "owner = import_module(runtime_module_name)\n",
                encoding="utf-8",
            )
            generated = build_document()
            relative = attack.relative_to(ROOT).as_posix()
            blockers = [
                site
                for site in checkpoint_sites(generated)
                if site["source"]["file"] == relative
                and site["disposition"] == "blocker"
            ]
        self.assertEqual(1, len(blockers))
        self.assertEqual("unreviewed_dynamic_import_domain", blockers[0]["reason_code"])
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "checkpoint.json"
            output.write_bytes(render_document(generated))
            with patch.object(
                checkpoint_generator, "build_document", return_value=generated
            ), patch.object(checkpoint_generator, "OUTPUT", output):
                self.assertEqual(1, checkpoint_generator.main(["--check"]))

    def test_index_and_specification_state_agree(self) -> None:
        validate_index_and_specification_state(
            json.loads(INDEX_JSON.read_text(encoding="utf-8")),
            INDEX_MARKDOWN.read_text(encoding="utf-8"),
            R17_SPECIFICATION.read_text(encoding="utf-8"),
            self.document,
            self.directive,
            ledger_bytes=self.raw,
            checkpoint=self.checkpoint,
            checkpoint_bytes=self.checkpoint_raw,
        )

    def test_index_and_specification_state_injections_fail_closed(self) -> None:
        index = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        index_markdown = INDEX_MARKDOWN.read_text(encoding="utf-8")
        specification = R17_SPECIFICATION.read_text(encoding="utf-8")

        def mutated_index(field: str) -> dict[str, Any]:
            selected = copy.deepcopy(index)
            requirement = next(
                item for item in selected["requirements"] if item.get("id") == "R17"
            )
            prerequisite = next(
                item
                for item in requirement["ready_prerequisites"]
                if item.get("id") == field
            )
            if field == "dynamic_import_audit_classification":
                prerequisite["satisfied"] = False
            else:
                first = next(iter(prerequisite["bound_artifact_sha256"]))
                prerequisite["bound_artifact_sha256"][first] = "0" * 64
            return selected

        injections = {
            "spec dynamic marker": (
                index,
                index_markdown,
                specification.replace(
                    "dynamic_import_audit_classification.satisfied=true",
                    "dynamic_import_audit_classification.satisfied=false",
                    1,
                ),
            ),
            "index markdown dynamic marker": (
                index,
                index_markdown.replace(
                    "dynamic_import_audit_classification.satisfied=true",
                    "dynamic_import_audit_classification.satisfied=false",
                    1,
                ),
                specification,
            ),
            "index JSON boolean": (
                mutated_index("dynamic_import_audit_classification"),
                index_markdown,
                specification,
            ),
            "spec M0 revision": (
                index,
                index_markdown,
                specification.replace(
                    "m0_bound_implementation_baseline="
                    "113176a381b6d232e95a112d78d1d2f4bc5ac024",
                    "m0_bound_implementation_baseline=" + "0" * 40,
                    1,
                ),
            ),
            "index markdown M0 revision": (
                index,
                index_markdown.replace(
                    "m0_bound_implementation_baseline="
                    "113176a381b6d232e95a112d78d1d2f4bc5ac024",
                    "m0_bound_implementation_baseline=" + "0" * 40,
                    1,
                ),
                specification,
            ),
            "index JSON M0 digest": (
                mutated_index("m0_characterization"),
                index_markdown,
                specification,
            ),
            "spec M0 digest": (
                index,
                index_markdown,
                specification.replace(
                    'm0_bound_artifact_sha256={"tests/agent_migration_characterization.py":"'
                    "97b3c71842b3904213ec24667ae09f4c821df0384f6667847e3c03f6c9d9d640",
                    'm0_bound_artifact_sha256={"tests/agent_migration_characterization.py":"'
                    + "0" * 64,
                    1,
                ),
            ),
            "spec ledger digest": (
                index,
                index_markdown,
                specification.replace(
                    "ledger_sha256=" + LEDGER_SHA256,
                    "ledger_sha256=" + "0" * 64,
                    1,
                ),
            ),
            "index markdown ledger digest": (
                index,
                index_markdown.replace(
                    "ledger_sha256=" + LEDGER_SHA256,
                    "ledger_sha256=" + "0" * 64,
                    1,
                ),
                specification,
            ),
            "index JSON ledger digest": (
                copy.deepcopy(index),
                index_markdown,
                specification,
            ),
        }
        ledger_index = injections["index JSON ledger digest"][0]
        ledger_requirement = next(
            item for item in ledger_index["requirements"] if item.get("id") == "R17"
        )
        dynamic = next(
            item
            for item in ledger_requirement["ready_prerequisites"]
            if item.get("id") == "dynamic_import_audit_classification"
        )
        dynamic["ledger_sha256"] = "0" * 64
        for label, (injected_index, injected_markdown, injected_spec) in injections.items():
            with self.subTest(label=label), self.assertRaises(AssertionError):
                validate_index_and_specification_state(
                    injected_index,
                    injected_markdown,
                    injected_spec,
                    self.document,
                    self.directive,
                    ledger_bytes=self.raw,
                    checkpoint=self.checkpoint,
                    checkpoint_bytes=self.checkpoint_raw,
                )

    def test_active_scope_owner_documents_are_in_the_consistency_set(self) -> None:
        roadmap = ROADMAP.read_text(encoding="utf-8")
        technical_debt = TECHNICAL_DEBT.read_text(encoding="utf-8")
        corrected_roadmap = roadmap.replace(
            "\u79fb\u9664 82 \u4e2a\u65e7 deep module path\uff0881 \u8fc1\u79fb + pagination \u5220\u9664\uff09",
            "\u79fb\u9664 83 \u4e2a\u65e7 deep module path\uff0882 \u8fc1\u79fb + pagination \u5220\u9664\uff09",
            1,
        )
        corrected_debt = technical_debt.replace(
            "\u6839 `.py` \u4e3a 496\u3001\n  `agents/` \u542b 81 \u4e2a\u5b9e\u73b0\u6a21\u5757",
            "\u6839 `.py` \u4e3a 495\u3001\n  `agents/` \u542b 82 \u4e2a\u5b9e\u73b0\u6a21\u5757",
            1,
        )
        validate_active_scope_owner_projection(
            corrected_roadmap,
            corrected_debt,
            self.document,
        )

        injections = {
            "roadmap old-path count": (
                corrected_roadmap.replace("\u79fb\u9664 83 \u4e2a", "\u79fb\u9664 84 \u4e2a", 1),
                corrected_debt,
                "roadmap R17 scope projection differs",
            ),
            "roadmap move count": (
                corrected_roadmap.replace("\uff0882 \u8fc1\u79fb", "\uff0881 \u8fc1\u79fb", 1),
                corrected_debt,
                "roadmap R17 scope projection differs",
            ),
            "technical-debt root count": (
                corrected_roadmap,
                corrected_debt.replace("\u6839 `.py` \u4e3a 495", "\u6839 `.py` \u4e3a 496", 1),
                "technical-debt R17 exit projection differs",
            ),
            "technical-debt agents count": (
                corrected_roadmap,
                corrected_debt.replace("`agents/` \u542b 82", "`agents/` \u542b 81", 1),
                "technical-debt R17 exit projection differs",
            ),
        }
        for label, (injected_roadmap, injected_debt, message) in injections.items():
            with self.subTest(label=label), self.assertRaisesRegex(
                AssertionError, message
            ):
                validate_active_scope_owner_projection(
                    injected_roadmap,
                    injected_debt,
                    self.document,
                )

        try:
            validate_active_scope_owner_projection(
                roadmap,
                technical_debt,
                self.document,
            )
        except AssertionError:
            self.assertIn(
                "\u79fb\u9664 82 \u4e2a\u65e7 deep module path\uff0881 \u8fc1\u79fb + pagination \u5220\u9664\uff09",
                roadmap,
            )
            self.assertIn("\u6839 `.py` \u4e3a 496", technical_debt)
            self.assertIn("`agents/` \u542b 81 \u4e2a\u5b9e\u73b0\u6a21\u5757", technical_debt)

    def test_frozen_scope_supports_all_three_owner_states(self) -> None:
        moves = self.document["scope"]["one_to_one_moves"]
        states = {
            "baseline": (82, True),
            "phase_1": (34, False),
            "phase_2": (0, False),
        }
        for label, (old_count, pagination_old) in states.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                ledger = root / "tests/fixtures/agent_module_reference_dispositions.json"
                ledger.parent.mkdir(parents=True)
                ledger.write_bytes(self.raw)
                pagination_target = (
                    root / "src/gravity_sdk/pagination_completeness.py"
                )
                pagination_target.parent.mkdir(parents=True)
                pagination_target.write_text("", encoding="utf-8")
                retained = root / "src/gravity_sdk/agent_runtime_contracts.py"
                retained.write_text("", encoding="utf-8")
                if pagination_old:
                    (root / "src/gravity_sdk/agent_pagination.py").write_text(
                        "", encoding="utf-8"
                    )
                for index, move in enumerate(moves):
                    module = (
                        move["old_module"]
                        if index < old_count
                        else move["new_module"]
                    )
                    path = root / "src" / Path(*module.split(".")).with_suffix(".py")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("", encoding="utf-8")
                mappings, mapping = make_module_map(root)
                self.assertEqual(84, len(mappings))
                self.assertEqual(84, len(mapping))
                self.assertEqual(
                    82,
                    sum(
                        item.new_module.startswith("gravity_sdk.agents.")
                        for item in mappings
                    ),
                )

    def test_relative_date_target_uses_the_shared_boundary_token_rule(self) -> None:
        mappings, _ = make_module_map(ROOT)
        relative_date = next(
            item
            for item in mappings
            if item.old_module == "gravity_sdk.relative_date_agent"
        )
        self.assertEqual("gravity_sdk.agents.relative_date", relative_date.new_module)
        self.assertEqual("src/gravity_sdk/agents/relative_date.py", relative_date.new_file)
        self.assertFalse(relative_date.target_exists)
        self.assertFalse(relative_date.casefold_target_collision)
        self.assertFalse(relative_date.stdlib_basename_collision)
        self.assertFalse((ROOT / "src/gravity_sdk/relative_date.py").exists())

    def test_canonical_errata_replacements_are_derived_only_from_ledger(self) -> None:
        declaration = self.directive["canonical_source_errata"][
            "allowed_source_replacements"
        ]
        self.assertIsInstance(declaration, dict)
        self.assertNotIn("old", declaration)
        self.assertNotIn("new", declaration)
        self.assertEqual(
            "tests/fixtures/agent_module_reference_dispositions.json",
            declaration["ledger_repository_path"],
        )
        self.assertRegex(declaration["ledger_git_blob"], r"^[0-9a-f]{40}$")
        self.assertEqual(LEDGER_SHA256, declaration["ledger_sha256"])
        self.assertEqual(
            errata_validator.REVIEWED_AT_REVISION,
            declaration["reviewed_at_revision"],
        )
        replacements = derive_source_replacements(self.directive, self.document)
        selected_rows = [
            site
            for site in self.document["sites"]
            if site["disposition"] == declaration["disposition"]
            and site["source"]["file"] == declaration["source_file"]
        ]
        self.assertEqual(4, len(replacements))
        self.assertEqual(
            {site["source_key"] for site in selected_rows},
            {replacement["source_key"] for replacement in replacements},
        )
        self.assertEqual(
            {
                (
                    site["source"]["line"],
                    site["source"]["column"],
                    site["migration_action"]["old_text"],
                    site["migration_action"]["new_text"],
                )
                for site in selected_rows
            },
            {
                (
                    replacement["line"],
                    replacement["column"],
                    replacement["old_text"],
                    replacement["new_text"],
                )
                for replacement in replacements
            },
        )

    def test_canonical_errata_derivation_fails_closed_on_ledger_drift(self) -> None:
        extra = copy.deepcopy(self.document)
        extra["sites"].append(copy.deepcopy(extra["sites"][0]))
        injected = next(
            site
            for site in extra["sites"]
            if site["disposition"] == "rewrite_reference"
            and site["source"]["file"]
            == "specs/agent-runtime/architecture-source.md"
        )
        extra["sites"][-1] = copy.deepcopy(injected)
        with self.assertRaisesRegex(
            ErrataValidationError,
            "directive-bound ledger object",
        ):
            derive_source_replacements(self.directive, extra)

        missing = copy.deepcopy(self.document)
        missing["sites"].remove(
            next(
                site
                for site in missing["sites"]
                if site["disposition"] == "rewrite_reference"
                and site["source"]["file"]
                == "specs/agent-runtime/architecture-source.md"
            )
        )
        with self.assertRaisesRegex(
            ErrataValidationError,
            "directive-bound ledger object",
        ):
            derive_source_replacements(self.directive, missing)

        self_loop = copy.deepcopy(self.document)
        loop_row = next(
            site
            for site in self_loop["sites"]
            if site["disposition"] == "rewrite_reference"
            and site["source"]["file"]
            == "specs/agent-runtime/architecture-source.md"
        )
        loop_row["migration_action"]["new_text"] = loop_row["migration_action"][
            "old_text"
        ]
        with self.assertRaisesRegex(ErrataValidationError, "directive-bound ledger object"):
            derive_source_replacements(self.directive, self_loop)

    def test_canonical_errata_rejects_same_commit_ledger_rebinding(self) -> None:
        forged = copy.deepcopy(self.document)
        forged["source_audit"]["method"] = "attacker rebound the ledger"
        forged_bytes = (
            json.dumps(forged, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        forged_directive = copy.deepcopy(self.directive)
        derivation = forged_directive["canonical_source_errata"][
            "allowed_source_replacements"
        ]
        derivation["ledger_git_blob"] = "1" * 40
        derivation["ledger_sha256"] = hashlib.sha256(forged_bytes).hexdigest()
        with self.assertRaisesRegex(
            ErrataValidationError,
            "ledger blob changed from the reviewed object",
        ):
            validate_bound_ledger(
                forged_directive,
                forged,
                ledger_bytes=forged_bytes,
            )

        review_pivot = copy.deepcopy(self.directive)
        review_pivot["canonical_source_errata"]["allowed_source_replacements"][
            "reviewed_at_revision"
        ] = "0" * 40
        with self.assertRaisesRegex(
            ErrataValidationError,
            "ledger review revision changed from the fifth-review input",
        ):
            validate_bound_ledger(review_pivot, self.document, ledger_bytes=self.raw)

    def test_canonical_transition_baseline_is_literal_and_not_rebindable(self) -> None:
        revision_pivot = copy.deepcopy(self.directive)
        revision_pivot["canonical_source_errata"]["transition"][
            "from_git_revision"
        ] = "0" * 40
        with self.assertRaisesRegex(
            ErrataValidationError,
            "from_git_revision changed from the reviewed v9.2 source",
        ):
            load_git_baseline(revision_pivot)

        malicious = load_git_baseline(self.directive) + b"\nexpand execution authority\n"
        sha_pivot = copy.deepcopy(self.directive)
        sha_pivot["canonical_source_errata"]["transition"][
            "from_sha256"
        ] = hashlib.sha256(malicious).hexdigest()
        with self.assertRaisesRegex(
            ErrataValidationError,
            "from_sha256 changed from the reviewed v9.2 bytes",
        ):
            build_expected_source(sha_pivot, self.document, malicious)

        source_pivot = copy.deepcopy(self.directive)
        transition = source_pivot["canonical_source_errata"]["transition"]
        transition["from_git_revision"] = "0" * 40
        transition["from_sha256"] = hashlib.sha256(malicious).hexdigest()
        with self.assertRaisesRegex(
            ErrataValidationError,
            "from_git_revision changed from the reviewed v9.2 source",
        ):
            build_expected_source(source_pivot, self.document, malicious)

    def test_phase1_canonical_source_and_directive_equal_reviewed_bytes(self) -> None:
        source = CANONICAL_SOURCE.read_bytes()
        result = validate_phase1_reviewed_state(
            self.directive,
            DIRECTIVE.read_bytes(),
            source,
        )
        self.assertEqual("phase-1", result["checkpoint"])

        with self.assertRaisesRegex(
            ErrataValidationError,
            "canonical source differs from the reviewed baseline",
        ):
            validate_phase1_reviewed_state(
                self.directive,
                DIRECTIVE.read_bytes(),
                source + b"\nexpand execution authority\n",
            )

        changed_directive = DIRECTIVE.read_bytes().replace(
            b'"owner_review": "pending"',
            b'"owner_review": "approved"',
            1,
        )
        with self.assertRaisesRegex(
            ErrataValidationError,
            "canonical directive differs from the reviewed baseline",
        ):
            validate_phase1_reviewed_state(
                self.directive,
                changed_directive,
                source,
            )

    def test_phase1_acceptance_runs_m0_public_api_and_behavior_after_precondition(
        self,
    ) -> None:
        specification = R17_SPECIFICATION.read_text(encoding="utf-8")
        section = specification.split(
            "### Phase 1 M0 And Representative Behavior Checkpoint", 1
        )[1].split("### Phase 1 Rollback Checkpoint", 1)[0]
        required = (
            "tests/test_agent_module_migration_characterization.py",
            "tests/test_public_api_snapshot.py",
            "test_cli_all_pages_guard_and_exit_codes_are_stable",
            "test_segment_spec_sdk_and_plan_share_one_safe_execution_path",
            "test_dry_run_calls_validation_but_never_execution",
            "test_failure_isolated_sanitized_and_local_exit_wins",
            "test_all_pages_unknown_completeness_is_preserved_capability_gap",
            "test_existing_agent_protocol_is_unchanged",
            "test_unknown_category_and_selector_point_at_catalog_browse",
            "validate_r17_canonical_source_errata.py --phase-1",
        )
        for value in required:
            self.assertIn(value, section)
        not_reached = section.index("Phase 1 behavior checkpoint not reached")
        regression = section.index(
            "R17 Phase 1 behavior regression after checkpoint preconditions passed"
        )
        self.assertLess(not_reached, regression)

    def test_canonical_errata_final_assertion_is_full_text_and_one_shot(self) -> None:
        baseline = load_git_baseline(self.directive)
        expected = build_expected_source(self.directive, self.document, baseline)
        final_directive = copy.deepcopy(self.directive)
        transition = final_directive["canonical_source_errata"]["transition"]
        final_directive["version"] = transition["to_version"]
        final_directive["supersedes"] = {
            "version": transition["from_version"],
            "sha256": transition["from_sha256"],
        }
        final_directive["canonical_source"]["sha256"] = hashlib.sha256(
            expected
        ).hexdigest()
        final_directive["canonical_source_errata"]["one_shot"] = {
            "state": "consumed",
            "reusable": False,
            "consumed_by": "R17",
            "consumed_at_checkpoint": "R17-phase-2-core",
        }
        result = validate_final_state(
            final_directive, self.document, expected, baseline
        )
        self.assertEqual(4, result["source_replacements"])

        with self.assertRaisesRegex(
            ErrataValidationError,
            "diff exceeds the ledger-derived errata",
        ):
            validate_final_state(
                final_directive,
                self.document,
                expected + b"unexpected second source change\n",
                baseline,
            )

        ledger_drift = copy.deepcopy(self.document)
        drift_row = next(
            site
            for site in ledger_drift["sites"]
            if site["source"].get("old_value") == "agent_handoff"
            and site["migration_action"].get("old_text") == "agent_handoff"
        )
        drift_row["migration_action"].update(
            {
                "new_text": "agents.handoff_next",
                "new_module": "gravity_sdk.agents.handoff_next",
            }
        )
        with self.assertRaisesRegex(
            ErrataValidationError,
            "directive-bound ledger object",
        ):
            build_expected_source(
                self.directive, ledger_drift, baseline
            )

        reused = copy.deepcopy(final_directive)
        reused["canonical_source_errata"]["one_shot"]["consumed_by"] = "R18"
        with self.assertRaisesRegex(ErrataValidationError, "exactly once by R17"):
            validate_final_state(reused, self.document, expected, baseline)

        second_transition = copy.deepcopy(final_directive)
        second_transition["canonical_source_errata"]["transition"].update(
            {"from_version": "v9.3", "to_version": "v9.4"}
        )
        with self.assertRaisesRegex(
            ErrataValidationError, "must remain v9.2 to v9.3"
        ):
            validate_final_state(
                second_transition, self.document, expected, baseline
            )

    def test_canonical_errata_rejects_semantic_change_hidden_as_metadata(self) -> None:
        malicious = copy.deepcopy(self.directive)
        malicious["canonical_source_errata"]["allowed_version_metadata_changes"][0][
            "text"
        ] = "ARCHITECTURAL SEMANTIC CHANGE: widen the execution boundary.\n\n"
        with self.assertRaisesRegex(
            ErrataValidationError,
            "version metadata allowlist changed from the exact three literals",
        ):
            build_expected_source(
                malicious,
                self.document,
                load_git_baseline(malicious),
            )

    def test_phase2_checkpoint_and_immutable_errata_gate_pass_together(self) -> None:
        audit = scan_repository()
        baseline_receipt = build_document(audit=audit)
        actionable_keys = {
            site["source_key"]
            for site in checkpoint_sites(baseline_receipt)
            if site["disposition"].startswith("rewrite_")
        }

        def remains_in_terminal(row: Any) -> bool:
            return source_key(row) not in actionable_keys or (
                row.file == "src/gravity_sdk/__init__.py"
                and row.form == "import_module"
            )

        terminal_audit = replace(
            audit,
            references=tuple(row for row in audit.references if remains_in_terminal(row)),
            manual_review=tuple(
                row for row in audit.manual_review if remains_in_terminal(row)
            ),
            owner_state="phase_2",
        )
        exports = json.loads(
            (ROOT / "tests/fixtures/public_api_exports.json").read_text(encoding="utf-8")
        )
        move_mapping = {
            move["old_module"]: move["new_module"]
            for move in baseline_receipt["scope"]["one_to_one_moves"]
        }
        for value in exports.values():
            owner = f"gravity_sdk{value[0]}"
            if owner in move_mapping:
                value[0] = move_mapping[owner].removeprefix("gravity_sdk")

        terminal_receipt = build_document(
            audit=terminal_audit,
            public_exports=exports,
        )
        validate_checkpoint_receipt(terminal_receipt)
        self.assertEqual("phase_2", terminal_receipt["source_audit"]["owner_state"])
        self.assertEqual(0, terminal_receipt["summary"]["actionable_site_count"])
        self.assertEqual([], terminal_receipt["blockers"])

        with tempfile.TemporaryDirectory() as temp:
            receipt_path = Path(temp) / "checkpoint.json"
            exports_path = Path(temp) / "public_api_exports.json"
            exports_path.write_text(json.dumps(exports), encoding="utf-8")
            with patch.object(
                checkpoint_generator, "scan_repository", return_value=terminal_audit
            ), patch.object(
                checkpoint_generator, "PUBLIC_EXPORTS", exports_path
            ), patch.object(
                checkpoint_generator, "OUTPUT", receipt_path
            ):
                self.assertEqual(0, checkpoint_generator.main([]))
                self.assertEqual(0, checkpoint_generator.main(["--check"]))

        baseline = load_git_baseline(self.directive)
        expected = build_expected_source(self.directive, self.document, baseline)
        final_directive = copy.deepcopy(self.directive)
        transition = final_directive["canonical_source_errata"]["transition"]
        final_directive["version"] = transition["to_version"]
        final_directive["supersedes"] = {
            "version": transition["from_version"],
            "sha256": transition["from_sha256"],
        }
        final_directive["canonical_source"]["sha256"] = hashlib.sha256(
            expected
        ).hexdigest()
        final_directive["canonical_source_errata"]["one_shot"] = {
            "state": "consumed",
            "reusable": False,
            "consumed_by": "R17",
            "consumed_at_checkpoint": "R17-phase-2-core",
        }
        result = validate_final_state(
            final_directive,
            self.document,
            expected,
            baseline,
        )
        self.assertEqual("v9.2->v9.3", result["transition"])

    def test_canonical_errata_rejects_forged_move_with_synced_source_digest(self) -> None:
        forged = copy.deepcopy(self.document)
        row = next(
            site
            for site in forged["sites"]
            if site["source"].get("file")
            == "specs/agent-runtime/architecture-source.md"
            and site["migration_action"].get("old_module")
            == "gravity_sdk.agent_capabilities"
        )
        row["migration_action"].update(
            {
                "new_module": "gravity_sdk.agents.unrelated_owner",
                "new_text": "agents/unrelated_owner.py",
            }
        )
        forged["summary"]["sites_sha256"] = _canonical_sites_sha256(
            forged["sites"]
        )
        forged_directive = copy.deepcopy(self.directive)
        forged_bytes = (json.dumps(forged, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        forged_directive["canonical_source_errata"]["allowed_source_replacements"][
            "ledger_sha256"
        ] = hashlib.sha256(forged_bytes).hexdigest()
        baseline = load_git_baseline(self.directive)
        with self.assertRaisesRegex(
            ErrataValidationError,
            "ledger SHA-256 changed from the reviewed bytes",
        ):
            build_expected_source(forged_directive, forged, baseline)

    def test_current_canonical_source_still_matches_v92_binding(self) -> None:
        source = CANONICAL_SOURCE.read_bytes()
        self.assertEqual(load_git_baseline(self.directive), source)
        self.assertEqual(
            self.directive["canonical_source"]["sha256"],
            hashlib.sha256(source).hexdigest(),
        )

    def test_governance_exclusion_is_narrow_and_explicit(self) -> None:
        for path in GENERATED_GOVERNANCE_FILES:
            self.assertTrue(is_generated_governance_artifact(path), path)
        self.assertTrue(
            is_generated_governance_artifact(
                "specs/agent-runtime/R17-agent-module-package-migration.md"
            )
        )
        self.assertTrue(is_generated_governance_artifact("tmp/codex/audit/output.csv"))
        protected = (
            "AGENTS.md",
            "specs/agent-runtime/architecture-source.md",
            "specs/agent-runtime/index.json",
            "specs/agent-runtime/index.md",
            "docs/maintainers/technical-debt.md",
            "tests/agent_migration_characterization.py",
            "src/gravity_sdk/agent_sources.py",
        )
        for path in protected:
            self.assertFalse(is_generated_governance_artifact(path), path)

        scanner = ReferenceScanner(
            {"gravity_sdk.agent_sources": "gravity_sdk.agents.sources"}
        )
        references, _ = scanner.scan_python(
            "src/gravity_sdk/real_consumer.py",
            "from gravity_sdk.agent_sources import snapshot_recipe_cards\n",
        )
        self.assertEqual(["static_import"], [item.category for item in references])
        pagination_scanner = ReferenceScanner({PAGINATION_MODULE: PAGINATION_TARGET})
        references, _ = pagination_scanner.scan_python(
            "src/gravity_sdk/real_pagination_consumer.py",
            "from .agent_pagination import compact_pagination\n",
        )
        self.assertEqual(
            [("static_import", PAGINATION_MODULE, PAGINATION_TARGET)],
            [(item.category, item.old_value, item.new_value) for item in references],
        )

    def test_bare_context_classifier_separates_records_from_consumers(self) -> None:
        pagination_rows = [
            site
            for site in self.document["sites"]
            if site["source"].get("old_value") == "agent_pagination"
        ]
        self.assertEqual(3, len(pagination_rows))
        self.assertEqual(
            {DELETED_MODULE_RECORD},
            {
                generator_classify_active_bare_context(
                    PAGINATION_MODULE,
                    site["source"]["audit_context"],
                )
                for site in pagination_rows
            },
        )
        for context in (
            '"consolidated_deleted_modules": [\n  "agent_pagination"\n]',
            "The deleted module is `agent_pagination.py`; keep the retained owner.",
        ):
            self.assertEqual(
                DELETED_MODULE_RECORD,
                generator_classify_active_bare_context(PAGINATION_MODULE, context),
            )
        for context in (
            "from gravity_sdk.agent_pagination import compact_pagination",
            "from .agent_pagination import compact_pagination",
            "from gravity_sdk import agent_pagination",
            "import gravity_sdk.agent_pagination",
            "gravity_sdk.agent_pagination.compact_pagination(items)",
        ):
            self.assertEqual(
                RUNTIME_CONSUMER,
                generator_classify_active_bare_context(PAGINATION_MODULE, context),
            )
        self.assertEqual(
            AMBIGUOUS_REFERENCE,
            generator_classify_active_bare_context(
                PAGINATION_MODULE,
                "Review agent_pagination before R17 starts.",
            ),
        )
        dated_rows = {
            site["source"]["old_value"]: site
            for site in self.document["sites"]
            if site["source"].get("file")
            == "docs/maintainers/technical-debt.md"
            and site["source"].get("old_value")
            in {"agent_batch", "agent_input_resolution"}
        }
        self.assertEqual({"agent_batch", "agent_input_resolution"}, set(dated_rows))
        for site in dated_rows.values():
            self.assertEqual("no_migration_effect", site["disposition"])
            self.assertEqual(
                "dated_governance_decision_evidence",
                site["reason_code"],
            )
            self.assertEqual({"kind": "none"}, site["migration_action"])
        list_item_start = next(
            site["source"]
            for site in self.document["sites"]
            if str(site["source"].get("audit_snippet", "")).lstrip().startswith(
                "- **\u9000\u51fa\u6761\u4ef6**"
            )
            and site["source"].get("old_value") == "agent_runtime_contracts"
        )
        self.assertTrue(
            list_item_start["audit_context"].startswith(
                list_item_start["audit_snippet"]
            )
        )

    def test_future_exact_pagination_text_uses_bounded_context(self) -> None:
        cases = {
            "deleted qualified module": (
                "future.md",
                "The deleted module gravity_sdk.agent_pagination was consolidated "
                "and removed.",
                "no_migration_effect",
                "deleted_module_governance_fact",
            ),
            "ambiguous qualified module": (
                "future.json",
                '{\n  "note": "Review gravity_sdk.agent_pagination before R17."\n}',
                "blocker",
                "ambiguous_deleted_module_reference",
            ),
            "qualified consumer": (
                "future.md",
                "Use gravity_sdk.agent_pagination.compact_pagination(items).",
                "rewrite_consolidated_reference",
                "pagination_consolidation_reference",
            ),
            "deleted exact source path": (
                "future.md",
                "The deleted module src/gravity_sdk/agent_pagination.py was removed.",
                "no_migration_effect",
                "deleted_module_governance_fact",
            ),
        }
        mapping = {PAGINATION_MODULE: PAGINATION_TARGET}
        scanner = ReferenceScanner(mapping)
        for label, (name, content, disposition, reason) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                path = root / "docs" / name
                path.parent.mkdir(parents=True)
                path.write_text(content, encoding="utf-8")
                rows = scanner.scan_text(f"docs/{name}", content)
                exact = next(row for row in rows if row.certainty == "exact")
                result = generator_classify_reference(
                    exact,
                    {},
                    mapping,
                    root,
                )
                self.assertEqual(disposition, result["disposition"])
                self.assertEqual(reason, result["reason_code"])

        python_fact = Finding(
            "string_reference",
            "tests/future_note.py",
            1,
            1,
            "python comment module string",
            PAGINATION_MODULE,
            PAGINATION_TARGET,
            "exact",
            "# deleted module gravity_sdk.agent_pagination was removed",
        )
        result = generator_classify_reference(
            python_fact,
            {},
            mapping,
        )
        self.assertEqual("no_migration_effect", result["disposition"])
        self.assertEqual("deleted_module_governance_fact", result["reason_code"])

    def test_consumer_syntax_takes_precedence_over_dated_evidence(self) -> None:
        consumers = {
            "import": "from gravity_sdk.agent_batch import capabilities_many",
            "call": "gravity_sdk.agent_batch.capabilities_many([])",
            "patch": "patch('gravity_sdk.agent_batch.capabilities_many')",
            "attribute": "handler = gravity_sdk.agent_batch.capabilities_many",
        }
        for form, consumer in consumers.items():
            context = f"Decision record (2026-08-26)\n{consumer}"
            with self.subTest(form=form):
                self.assertEqual(
                    ACTIVE_REFERENCE,
                    generator_classify_active_bare_context(
                        "gravity_sdk.agent_batch", context
                    ),
                )

    def test_six_short_spine_rewrites_keep_the_agents_directory(self) -> None:
        paths = {"AGENTS.md", "specs/agent-runtime/architecture-source.md"}
        rows = [
            site
            for site in self.document["sites"]
            if site["source"].get("file") in paths
            and site["migration_action"].get("old_module")
            in {
                "gravity_sdk.agent_capabilities",
                "gravity_sdk.agent_composite",
                "gravity_sdk.agent_handoff",
            }
            and site["migration_action"].get("old_text", "").endswith(".py")
        ]
        self.assertEqual(6, len(rows))
        self.assertEqual(
            {
                "agents/capabilities.py",
                "agents/composite.py",
                "agents/handoff.py",
            },
            {site["migration_action"]["new_text"] for site in rows},
        )

    def test_rewrite_targets_cannot_alias_unrelated_existing_root_files(self) -> None:
        conflicts: list[str] = []
        for site in self.document["sites"]:
            action = site.get("migration_action", {})
            new_text = str(action.get("new_text", "")).replace("\\", "/")
            new_module = action.get("new_module")
            if not new_text.endswith(".py") or not isinstance(new_module, str):
                continue
            root_peer = ROOT / "src/gravity_sdk" / Path(new_text).name
            root_peer_module = f"gravity_sdk.{Path(new_text).stem}"
            related = {
                PAGINATION_TARGET,
                *{
                    move["old_module"]
                    for move in self.document["scope"]["one_to_one_moves"]
                },
                *{
                    move["new_module"]
                    for move in self.document["scope"]["one_to_one_moves"]
                },
            }
            if (
                root_peer.is_file()
                and root_peer_module not in related
                and new_text == Path(new_text).name
            ):
                conflicts.append(f"{site['source_key']} -> {new_text}")
        self.assertEqual([], conflicts, f"ambiguous root-file rewrite targets: {conflicts}")

    def test_validator_rejects_consumer_disguised_as_no_effect(self) -> None:
        injected = copy.deepcopy(self.document)
        site = next(
            item
            for item in injected["sites"]
            if item["source"].get("old_value") == "agent_pagination"
        )
        consumer = "from gravity_sdk.agent_pagination import compact_pagination"
        site["source"]["audit_snippet"] = consumer
        site["source"]["audit_context"] = consumer
        with self.assertRaisesRegex(
            AssertionError,
            "active consumer syntax must rewrite or block",
        ):
            validate_ledger(injected)

    def test_validator_independently_rejects_dated_consumer_syntax(self) -> None:
        injected = copy.deepcopy(self.document)
        site = next(
            item
            for item in injected["sites"]
            if item.get("reason_code") == "dated_governance_decision_evidence"
            and item["source"].get("old_value") == "agent_batch"
        )
        consumers = {
            "import": "from gravity_sdk.agent_batch import capabilities_many",
            "call": "gravity_sdk.agent_batch.capabilities_many([])",
            "patch": "patch('gravity_sdk.agent_batch.capabilities_many')",
            "attribute": "handler = gravity_sdk.agent_batch.capabilities_many",
        }
        for form, consumer in consumers.items():
            mutated = copy.deepcopy(injected)
            mutated_site = next(
                item
                for item in mutated["sites"]
                if item["source_key"] == site["source_key"]
            )
            mutated_site["source"]["audit_snippet"] = consumer
            mutated_site["source"]["audit_context"] = (
                f"Decision record (2026-08-26)\n{consumer}"
            )
            with self.subTest(form=form), self.assertRaisesRegex(
                AssertionError,
                "active consumer syntax must rewrite or block",
            ):
                validate_ledger(mutated)

    def test_validator_rejects_required_regressions(self) -> None:
        mutations: dict[str, Any] = {}
        missing = copy.deepcopy(self.document)
        missing["sites"].pop()
        mutations["missing row"] = missing
        duplicate = copy.deepcopy(self.document)
        duplicate["sites"][1]["source_key"] = duplicate["sites"][0]["source_key"]
        mutations["duplicate key"] = duplicate
        unclassified = copy.deepcopy(self.document)
        unclassified["sites"][0]["disposition"] = "unclassified"
        mutations["unclassified row"] = unclassified
        blocker_mismatch = copy.deepcopy(self.document)
        blocker_mismatch["summary"]["blocker_count"] = 1
        mutations["blocker count mismatch"] = blocker_mismatch
        illegal_target = copy.deepcopy(self.document)
        rewrite = next(
            site
            for site in illegal_target["sites"]
            if site["disposition"] == "rewrite_reference"
        )
        rewrite["migration_action"]["new_module"] = "gravity_sdk.agents.pagination"
        mutations["illegal target"] = illegal_target
        for label, document in mutations.items():
            with self.subTest(label=label), self.assertRaises(AssertionError):
                validate_ledger(document)


class R17ResponsibilityInventoryTests(unittest.TestCase):
    def test_signed_inventory_exactly_matches_source_recomputation(self) -> None:
        signed = load_signed_r17_responsibility_inventory()
        self.assertEqual(signed, build_r17_responsibility_inventory())
        payload = dict(signed)
        digest = payload.pop("payload_sha256")
        self.assertEqual(digest, _r17_digest(payload))

    def test_inventory_rows_and_r17_comparison_are_complete(self) -> None:
        signed = load_signed_r17_responsibility_inventory()
        decisions = signed["decisions"]
        included = [row for row in decisions if row["include"]]
        rejected = [row for row in decisions if not row["include"]]
        comparison = signed["r17_comparison"]
        self.assertEqual(84, len(signed["members"]))
        self.assertEqual(signed["members"], sorted(row["module"] for row in included))
        self.assertEqual(92, len(decisions))
        self.assertEqual(8, len(rejected))
        non_moves = sorted(
            row["module"]
            for row in included
            if row["r17_disposition"] in {
                "retain_public_facade",
                "consolidate_delete",
            }
        )
        self.assertEqual(non_moves, comparison["independent_members_not_moves"])
        self.assertEqual([], comparison["moves_not_independent_members"])
        self.assertTrue(comparison["action_normalized_members_equal_moves"])
        self.assertEqual([], comparison["action_normalized_members_not_moves"])
        self.assertEqual([], comparison["moves_not_action_normalized_members"])
        self.assertNotIn(
            "unmapped_member", {row["r17_disposition"] for row in included}
        )

    def test_boundary_cases_keep_runtime_contracts_and_find_out(self) -> None:
        cases = {
            item["label"]: item
            for item in load_signed_r17_responsibility_inventory()["boundary_cases"]
        }
        contracts = cases["broader_runtime_contracts_owner"]
        self.assertFalse(contracts["selected"])
        self.assertEqual(55, contracts["direct_consumer_count"])
        self.assertEqual([], contracts["direct_member_consumers"])
        self.assertEqual([], contracts["direct_imports_to_members"])
        find = cases["independent_find_surface"]
        self.assertFalse(find["selected"])
        self.assertEqual(["gravity.find.v1"], find["primary_schemas"])
        self.assertIn("find", find["cli_commands"])
        self.assertEqual(10, find["direct_consumer_count"])
        self.assertEqual(7, len(find["direct_member_consumers"]))
        self.assertEqual(2, len(find["direct_imports_to_members"]))

    def test_graph_methods_are_recorded_without_a_convergence_claim(self) -> None:
        signed = load_signed_r17_responsibility_inventory()
        observations = {
            item["name"]: item for item in signed["graph_observations"]
        }
        self.assertEqual(40, observations["facade_scc"]["member_count"])
        self.assertEqual(311, observations["unrestricted_facade_closure"]["member_count"])
        self.assertEqual(496, observations["import_graph_minimum_conductance"]["member_count"])
        self.assertEqual(626, observations["cochange_component"]["member_count"])
        self.assertFalse(signed["conclusion"]["graph_methods_converged"])
        self.assertFalse(signed["conclusion"]["complete_agent_domain_proven"])

    def test_docstring_drift_injection_changes_the_recomputed_inventory(self) -> None:
        package_root = ROOT / "src/gravity_sdk"
        baseline = _r17_analyze_source(package_root)
        targets = [
            name
            for name, record in baseline["records"].items()
            if record["docstring"]
            == "Fill Agent cards from a unique closed relative-date phrase."
        ]
        self.assertEqual(1, len(targets))
        with tempfile.TemporaryDirectory() as raw:
            temporary_package = Path(raw) / package_root.name
            shutil.copytree(package_root, temporary_package)
            relative = baseline["records"][targets[0]]["path"].relative_to(package_root)
            target = temporary_package / relative
            source = target.read_text(encoding="utf-8")
            old = '"""Fill Agent cards from a unique closed relative-date phrase."""'
            new = '"""Fill cards from a unique closed relative-date phrase."""'
            self.assertEqual(1, source.count(old))
            target.write_text(source.replace(old, new), encoding="utf-8")
            mutated = _r17_analyze_source(temporary_package)["members"]
        self.assertEqual({targets[0]}, baseline["members"] - mutated)

    def test_requirement_summary_binds_every_inventory_digest(self) -> None:
        signed = load_signed_r17_responsibility_inventory()
        summary = R17_SPECIFICATION.read_text(encoding="utf-8").split(
            R17_INVENTORY_START, 1
        )[0]
        for digest in (
            signed["payload_sha256"],
            signed["method_sha256"],
            signed["members_sha256"],
            signed["source_snapshot"]["tree_sha256"],
        ):
            self.assertEqual(1, summary.count(digest), digest)


if __name__ == "__main__":
    unittest.main()
