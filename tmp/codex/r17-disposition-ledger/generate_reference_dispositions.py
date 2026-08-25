"""Generate the reviewed R17 dynamic-reference disposition ledger.

The audit deliberately over-approximated dynamic behavior. This generator
turns every one of its 227 manual-review rows into a fail-closed migration
instruction. It reads evidence only and writes the checked-in test fixture.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
AUDIT_ROOT = ROOT / "tmp/codex/dyn-audit"
MANUAL_REVIEW = AUDIT_ROOT / "dyn_audit_manual_review.csv"
REFERENCES = AUDIT_ROOT / "dyn_audit_references.csv"
MODULE_MAP = AUDIT_ROOT / "dyn_audit_module_map.csv"
PUBLIC_EXPORTS = ROOT / "tests/fixtures/public_api_exports.json"
OUTPUT = ROOT / "tests/fixtures/agent_module_reference_dispositions.json"

EXPECTED_SHA256 = {
    MANUAL_REVIEW: "6116564ed625feb969f0838ece2aa12b4c92cd82b76b1da51fc67add128c713c",
    REFERENCES: "356287b9a245d609185ed1dcf89385af13435a3c4b0d8efed87303cb97c01e53",
    MODULE_MAP: "8c59fea70e6ff78d156fbf33216fa1a31459b2881cd7aba21efd77d2230b655a",
}
EXPECTED_AUDIT_CATEGORIES = {
    "dynamic_import": 11,
    "non_string_patch_expression": 117,
    "bare_agent_string": 92,
    "module_owner_receiver": 7,
}
ACTIVE_BARE_FILES = {
    "AGENTS.md",
    "specs/agent-runtime/architecture-source.md",
    "specs/agent-runtime/index.json",
    "specs/agent-runtime/index.md",
}
RETAINED_MODULE = "gravity_sdk.agent_runtime_contracts"
PAGINATION_MODULE = "gravity_sdk.agent_pagination"
PAGINATION_TARGET = "gravity_sdk.pagination_completeness"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _source_key(row: dict[str, str]) -> str:
    return f"{row['file']}:{row['line']}:{row['column']}:{row['form']}"


def _audit_category(row: dict[str, str]) -> str:
    if row["form"] == "bare text module string":
        return "bare_agent_string"
    if row["form"] in {"__module__", "__qualname__"}:
        return "module_owner_receiver"
    if row["details"] == "dynamic import expression is not compile-time constant":
        return "dynamic_import"
    if row["details"] == "patch target expression is not compile-time constant":
        return "non_string_patch_expression"
    raise ValueError(f"unrecognized audit row: {_source_key(row)}")


def _module_universe() -> tuple[list[dict[str, str]], dict[str, str]]:
    rows = _read_csv(MODULE_MAP)
    if len(rows) != 83 or len({row["old_module"] for row in rows}) != 83:
        raise ValueError("the bound audit module universe is not 83 unique modules")
    moves: list[dict[str, str]] = []
    mapping: dict[str, str] = {}
    for row in rows:
        old = row["old_module"]
        if old in {PAGINATION_MODULE, RETAINED_MODULE}:
            continue
        short = old.removeprefix("gravity_sdk.agent_")
        new = f"gravity_sdk.agents.{short}"
        moves.append({"old_module": old, "new_module": new})
        mapping[old] = new
    moves.sort(key=lambda item: item["old_module"])
    if len(moves) != 81:
        raise ValueError("current R17 scope must contain exactly 81 one-to-one moves")
    return moves, mapping


def _reference_snippets() -> dict[tuple[str, ...], str]:
    result: dict[tuple[str, ...], str] = {}
    for row in _read_csv(REFERENCES):
        key = tuple(row[name] for name in (
            "file", "line", "column", "form", "old_value", "new_value"
        ))
        result[key] = row["details"]
    return result


def _selector_rewrites(move_mapping: dict[str, str]) -> list[dict[str, str]]:
    exports = json.loads(PUBLIC_EXPORTS.read_text(encoding="utf-8"))
    rewrites: list[dict[str, str]] = []
    for symbol, (owner, attribute) in exports.items():
        old_module = f"gravity_sdk{owner}"
        if old_module not in move_mapping:
            continue
        new_module = move_mapping[old_module]
        rewrites.append({
            "symbol": symbol,
            "attribute": attribute,
            "old_value": owner,
            "new_value": new_module.removeprefix("gravity_sdk"),
            "old_module": old_module,
            "new_module": new_module,
        })
    rewrites.sort(key=lambda item: item["symbol"])
    if len(rewrites) != 6:
        raise ValueError("the lazy selector must have exactly six moved owners")
    return rewrites


def _none(reason_code: str, basis: str, evidence_kind: str) -> dict[str, Any]:
    return {
        "disposition": "no_migration_effect",
        "reason_code": reason_code,
        "migration_action": {"kind": "none"},
        "basis": basis,
        "evidence_kind": evidence_kind,
    }


def _classify_bare(
    row: dict[str, str],
    snippet: str,
    move_mapping: dict[str, str],
) -> dict[str, Any]:
    old_short = row["old_value"]
    old_module = f"gravity_sdk.{old_short}"
    if row["file"].startswith("docs/archive/"):
        item = _none(
            "frozen_historical_text",
            "The occurrence is in docs/archive, which AGENTS.md defines as "
            "non-normative history rather than a current interface or consumer.",
            "repository_policy",
        )
        item["module_reference"] = {
            "old_module": old_module,
            "candidate_new_module": move_mapping[old_module],
        }
        return item
    if row["file"] not in ACTIVE_BARE_FILES:
        raise ValueError(f"unreviewed active bare string: {_source_key(row)}")
    if old_module not in move_mapping:
        raise ValueError(f"active bare string is not an R17 move: {_source_key(row)}")

    short = old_short.removeprefix("agent_")
    full_source = f"src/gravity_sdk/{old_short}.py"
    if full_source in snippet:
        old_text = full_source
        new_text = f"src/gravity_sdk/agents/{short}.py"
    elif f"{old_short}.py" in snippet:
        old_text = f"{old_short}.py"
        new_text = f"agents/{short}.py"
    else:
        old_text = old_short
        new_text = f"agents.{short}"
    return {
        "disposition": "rewrite_reference",
        "reason_code": "active_governance_path",
        "migration_action": {
            "kind": "replace_text",
            "old_text": old_text,
            "new_text": new_text,
            "old_module": old_module,
            "new_module": move_mapping[old_module],
        },
        "basis": "The active governance source names the physical/shared-spine "
        "owner, so the reference must follow the one-to-one package move.",
        "evidence_kind": "audited_source_context",
    }


def _classify_dynamic(
    row: dict[str, str], selector_rewrites: list[dict[str, str]]
) -> dict[str, Any]:
    if row["file"] == "src/gravity_sdk/__init__.py":
        return {
            "disposition": "rewrite_selector_data",
            "reason_code": "root_lazy_export_owner_map",
            "migration_action": {
                "kind": "replace_selector_values",
                "selector": "gravity_sdk._EXPORTS",
                "rewrites": selector_rewrites,
            },
            "basis": "__getattr__ imports only module_name values from _EXPORTS; "
            "the public export snapshot proves exactly six values select R17 moves.",
            "evidence_kind": "finite_selector_dataflow",
        }
    basis_by_file = {
        "src/gravity_sdk/runtime.py": (
            "root_package_only",
            "The loop input is the literal singleton ('gravity_sdk',), so it cannot "
            "select any deep agent module.",
        ),
        "src/gravity_sdk/prober/cli.py": (
            "fixed_non_agent_suffix",
            "sdk.__name__ is gravity_sdk and the only appended suffix is '.errors'.",
        ),
        "src/gravity_sdk/prober/export_verify.py": (
            "fixed_non_agent_call_domain",
            "All _sdk_module call sites pass one of export_policy, registry, blob, "
            "export_models, or export_privacy; none is an agent module.",
        ),
        "src/gravity_sdk/prober/transport.py": (
            "fixed_non_agent_suffix",
            "The six expressions append the fixed root-module suffixes models, "
            "registry, executor, transport, http_runtime, and credentials.",
        ),
        "tests/test_gravity_material_performance.py": (
            "fixed_non_agent_test_domain",
            "The local modules tuple contains seven non-agent result/product modules; "
            "the separately imported directory module is also non-agent.",
        ),
    }
    try:
        reason, basis = basis_by_file[row["file"]]
    except KeyError as exc:
        raise ValueError(f"unreviewed dynamic import: {_source_key(row)}") from exc
    return _none(reason, basis, "finite_input_dataflow")


def _classify_patch(row: dict[str, str]) -> dict[str, Any]:
    form = row["form"]
    if form in {"patch.object", "mock.patch.object"}:
        return _none(
            "direct_object_patch",
            f"{form} receives the runtime object expression {row['old_value']!r}; "
            "this API does not resolve a dotted module string. Any owner import moves "
            "through the separately audited static-import migration.",
            "patch_api_semantics",
        )
    if form == "monkeypatch.setattr":
        return _none(
            "direct_object_monkeypatch",
            f"The reviewed first argument {row['old_value']!r} is a bound module/object "
            "and the call supplies a separate attribute name; no dotted import target "
            "is assembled at this site.",
            "binding_and_patch_api_semantics",
        )
    if row["old_value"] == "target" and row["file"] in {
        "tests/test_gravity_insight_nonempty.py",
        "tests/test_gravity_insight_prober.py",
    }:
        return _none(
            "helper_receives_only_objects",
            "Every call to this local setattr helper passes an imported module object; "
            "the string-target mock.patch branch has no agent-module input.",
            "complete_local_call_census",
        )
    fixed_non_agent = {
        ("src/gravity_sdk/sql/credentials.py", "f\"{__name__}.restrict_local_secret\""):
            "__name__ is gravity_sdk.sql.credentials.",
        ("tests/test_gravity_insight_core.py", "f\"{_atomic_update_env.__module__}._restrict_secret_file\""):
            "_atomic_update_env is owned by gravity_sdk.credentials.",
        ("tests/test_gravity_order_trace_surface.py", "f\"gravity_sdk.{module}.runtime.build_client\""):
            "module ranges only over order_trace_cli and order_directory_cli.",
        ("tests/test_http_receipt_durability.py", "f\"gravity_sdk.executor.{stage}\""):
            "stage ranges only over _project and _enforce_semantic_rules.",
        ("tests/test_sql_products.py", "f\"gravity_sdk.sql.__main__.{patch_target}\""):
            "patch_target ranges only over verify_all and credentials.pull.",
    }
    key = (row["file"], row["old_value"])
    if key not in fixed_non_agent:
        raise ValueError(f"unreviewed string-producing patch: {_source_key(row)}")
    return _none(
        "fixed_non_agent_patch_path",
        fixed_non_agent[key] + " The resulting target is outside the R17 module set.",
        "finite_input_dataflow",
    )


def _classify_owner(row: dict[str, str]) -> dict[str, Any]:
    if row["file"] in {
        "src/gravity_sdk/error_mapping.py",
        "src/gravity_sdk/error_models.py",
        "src/gravity_sdk/error_sql.py",
        "src/gravity_sdk/error_types.py",
    }:
        return _none(
            "compatibility_owner_assignment",
            "The receiver is a locally enumerated error compatibility symbol and the "
            "assignment explicitly normalizes its owner to gravity_sdk.errors.",
            "receiver_binding_census",
        )
    basis_by_file = {
        "tests/test_error_import_compatibility.py":
            "error_type is selected from gravity_sdk.errors and asserted to retain that owner.",
        "tests/test_execution_variant.py":
            "ExecutionVariantService is statically imported from gravity_sdk.execution_variant.",
        "tests/test_gravity_insight_core.py":
            "_atomic_update_env is statically imported from gravity_sdk.credentials.",
    }
    if row["file"] not in basis_by_file:
        raise ValueError(f"unreviewed owner receiver: {_source_key(row)}")
    return _none(
        "receiver_owner_outside_r17",
        basis_by_file[row["file"]] + " That owner is outside the R17 move set.",
        "receiver_binding_census",
    )


def build_document() -> dict[str, Any]:
    for path, expected in EXPECTED_SHA256.items():
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(f"audit input changed: {path.relative_to(ROOT)} {actual}")

    manual_rows = _read_csv(MANUAL_REVIEW)
    if len(manual_rows) != 227:
        raise ValueError(f"expected 227 manual-review rows, found {len(manual_rows)}")
    keys = [_source_key(row) for row in manual_rows]
    if len(set(keys)) != 227:
        raise ValueError("manual-review source keys are not unique")

    moves, move_mapping = _module_universe()
    snippets = _reference_snippets()
    selector_rewrites = _selector_rewrites(move_mapping)
    sites: list[dict[str, Any]] = []
    for row in manual_rows:
        category = _audit_category(row)
        source = {
            "file": row["file"],
            "line": int(row["line"]),
            "column": int(row["column"]),
            "form": row["form"],
            "old_value": row["old_value"],
            "audit_proposed_value": row["new_value"],
        }
        if category == "bare_agent_string":
            reference_key = tuple(row[name] for name in (
                "file", "line", "column", "form", "old_value", "new_value"
            ))
            if reference_key not in snippets:
                raise ValueError(f"missing reference evidence: {_source_key(row)}")
            disposition = _classify_bare(row, snippets[reference_key], move_mapping)
            source["audit_snippet"] = snippets[reference_key]
        elif category == "dynamic_import":
            disposition = _classify_dynamic(row, selector_rewrites)
        elif category == "non_string_patch_expression":
            disposition = _classify_patch(row)
        else:
            disposition = _classify_owner(row)
        sites.append({
            "source_key": _source_key(row),
            "audit_category": category,
            "source": source,
            **disposition,
        })

    sites.sort(key=lambda item: item["source_key"])
    audit_counts = Counter(item["audit_category"] for item in sites)
    if dict(audit_counts) != EXPECTED_AUDIT_CATEGORIES:
        raise ValueError(f"audit category drift: {dict(audit_counts)}")
    disposition_counts = Counter(item["disposition"] for item in sites)
    blocker_count = disposition_counts["blocker"]
    unclassified = sum(
        not item.get("disposition") or item["disposition"] == "unclassified"
        for item in sites
    )
    sites_sha256 = hashlib.sha256(json.dumps(
        sites, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()

    return {
        "schema_version": "gravity.agent-module-reference-dispositions.v1",
        "source_audit": {
            "path": MANUAL_REVIEW.relative_to(ROOT).as_posix(),
            "sha256": EXPECTED_SHA256[MANUAL_REVIEW],
            "reference_evidence_path": REFERENCES.relative_to(ROOT).as_posix(),
            "reference_evidence_sha256": EXPECTED_SHA256[REFERENCES],
            "candidate_map_path": MODULE_MAP.relative_to(ROOT).as_posix(),
            "candidate_map_sha256": EXPECTED_SHA256[MODULE_MAP],
            "audit_baseline_head": "01e20b49a73f17b8e0c8e76d6a9bc17f4974322b",
            "source_key_format": "{file}:{line}:{column}:{form}",
        },
        "scope": {
            "audit_candidate_modules": 83,
            "one_to_one_moves": moves,
            "consolidate_delete": {
                "old_module": PAGINATION_MODULE,
                "new_module": PAGINATION_TARGET,
                "symbol": "compact_pagination",
            },
            "retained_modules": [RETAINED_MODULE],
            "old_mapping_difference": {
                "audit_assumption": "83 one-to-one moves",
                "current_scope": "81 one-to-one moves + agent_pagination consolidate/delete + agent_runtime_contracts retained",
                "literal_manual_review_rows_affected": {
                    PAGINATION_MODULE: 0,
                    RETAINED_MODULE: 0,
                },
            },
        },
        "taxonomy": {
            "rewrite_reference": "At migration, replace migration_action.old_text with new_text at this source site; new_module is the required owner.",
            "rewrite_selector_data": "Keep the dynamic import expression, but apply every exact selector-value rewrite before removing old module paths.",
            "rewrite_consolidated_reference": "Replace an agent_pagination selector with gravity_sdk.pagination_completeness; inability to do so is a blocker.",
            "no_migration_effect": "Make no edit at this source site; basis proves it is historical text, an object-identity patch, or a selector whose complete input domain excludes R17 modules.",
            "runtime_verification_required": "Run the row's bounded verification method before migration; a failing or unavailable result becomes blocker, never no_migration_effect.",
            "blocker": "Do not start R17 until the stated ownership or selector proposition is resolved and an exact action replaces this disposition.",
        },
        "classification_method": {
            "bare_agent_string": "Join each row to its audited source snippet. Frozen docs/archive references stay unchanged; every active governance reference receives a context-exact text replacement and an 81-target module rewrite.",
            "non_string_patch_expression": "Separate object APIs from dotted-string APIs. Object forms carry identity across a moved static import; for string-producing forms, exhaustively inspect the finite producer/call domain.",
            "dynamic_import": "Trace each expression to its finite inputs/callers. The root lazy loader has six exact owner-data rewrites; all other input domains are explicitly non-agent.",
            "module_owner_receiver": "Trace every receiver binding to its defining/imported owner and retain only owners outside the R17 move set.",
        },
        "summary": {
            "site_count": len(sites),
            "unique_source_keys": len({item["source_key"] for item in sites}),
            "unclassified_sites": unclassified,
            "blocker_count": blocker_count,
            "audit_categories": dict(sorted(audit_counts.items())),
            "dispositions": dict(sorted(disposition_counts.items())),
            "sites_sha256": sites_sha256,
        },
        "blockers": [],
        "sites": sites,
    }


def main() -> None:
    document = build_document()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(document["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
