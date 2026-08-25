"""Generate the reviewed R17 disposition ledger from the current repository."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

try:
    from .audit_agent_module_references import (
        GOVERNANCE_EXCLUSION_RULE,
        Finding,
        canonical_sha256,
        scan_repository,
        source_key,
    )
except ImportError:
    from audit_agent_module_references import (  # type: ignore[no-redef]
        GOVERNANCE_EXCLUSION_RULE,
        Finding,
        canonical_sha256,
        scan_repository,
        source_key,
    )


ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "scripts/audit_agent_module_references.py"
GENERATOR = ROOT / "scripts/generate_agent_module_reference_dispositions.py"
PUBLIC_EXPORTS = ROOT / "tests/fixtures/public_api_exports.json"
OUTPUT = ROOT / "tests/fixtures/agent_module_reference_dispositions.json"

EXPECTED_AUDIT_CATEGORIES = {
    "agent_prefix_template": 2,
    "bare_agent_string": 101,
    "dynamic_import": 11,
    "module_owner_receiver": 7,
    "non_string_patch_expression": 117,
}
EXPECTED_DISPOSITIONS = {
    "no_migration_effect": 219,
    "rewrite_consolidated_reference": 3,
    "rewrite_reference": 15,
    "rewrite_selector_data": 1,
}
ACTIVE_BARE_FILES = {
    "AGENTS.md",
    "docs/maintainers/technical-debt.md",
    "specs/agent-runtime/architecture-source.md",
    "specs/agent-runtime/index.json",
    "specs/agent-runtime/index.md",
}
RETAINED_MODULE = "gravity_sdk.agent_runtime_contracts"
PAGINATION_MODULE = "gravity_sdk.agent_pagination"
PAGINATION_TARGET = "gravity_sdk.pagination_completeness"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _audit_category(row: Finding) -> str:
    if row.form == "bare text module string":
        return "bare_agent_string"
    if row.form in {"__module__", "__qualname__"}:
        return "module_owner_receiver"
    if row.details == "dynamic import expression is not compile-time constant":
        return "dynamic_import"
    if row.details == "patch target expression is not compile-time constant":
        return "non_string_patch_expression"
    if (
        row.file == "tests/agent_migration_characterization.py"
        and row.form == "python string literal"
        and row.old_value == "gravity_sdk.agent_"
    ):
        return "agent_prefix_template"
    raise ValueError(f"unrecognized audit row: {source_key(row)}")


def _module_universe(
    mappings: tuple[Any, ...],
) -> tuple[list[dict[str, str]], dict[str, str]]:
    if len(mappings) != 83 or len({row.old_module for row in mappings}) != 83:
        raise ValueError("the repository scan must find 83 unique agent modules")
    moves: list[dict[str, str]] = []
    mapping: dict[str, str] = {}
    for row in mappings:
        old = row.old_module
        if old in {PAGINATION_MODULE, RETAINED_MODULE}:
            continue
        moves.append({"old_module": old, "new_module": row.new_module})
        mapping[old] = row.new_module
    moves.sort(key=lambda item: item["old_module"])
    if len(moves) != 81:
        raise ValueError("current R17 scope must contain 81 one-to-one moves")
    return moves, mapping


def _reference_snippets(references: tuple[Finding, ...]) -> dict[tuple[str, ...], str]:
    result: dict[tuple[str, ...], str] = {}
    for row in references:
        key = (
            row.file,
            str(row.line),
            str(row.column),
            row.form,
            row.old_value,
            row.new_value,
        )
        result[key] = row.details
    return result


def _selector_rewrites(move_mapping: dict[str, str]) -> list[dict[str, str]]:
    exports = json.loads(PUBLIC_EXPORTS.read_text(encoding="utf-8"))
    rewrites: list[dict[str, str]] = []
    for symbol, (owner, attribute) in exports.items():
        old_module = f"gravity_sdk{owner}"
        if old_module not in move_mapping:
            continue
        new_module = move_mapping[old_module]
        rewrites.append(
            {
                "symbol": symbol,
                "attribute": attribute,
                "old_value": owner,
                "new_value": new_module.removeprefix("gravity_sdk"),
                "old_module": old_module,
                "new_module": new_module,
            }
        )
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


def _module_reference(old_module: str, move_mapping: dict[str, str]) -> dict[str, str]:
    result = {"old_module": old_module}
    if old_module in move_mapping:
        result["candidate_new_module"] = move_mapping[old_module]
    elif old_module == PAGINATION_MODULE:
        result["candidate_new_module"] = PAGINATION_TARGET
    return result


def _replacement_texts(row: Finding, snippet: str, new_module: str) -> tuple[str, str]:
    old_short = row.old_value
    short = new_module.rsplit(".", 1)[1]
    full_source = f"src/gravity_sdk/{old_short}.py"
    if full_source in snippet:
        return full_source, "src/" + new_module.replace(".", "/") + ".py"
    if f"{old_short}.py" in snippet:
        return f"{old_short}.py", f"{short}.py"
    return old_short, new_module.removeprefix("gravity_sdk.")


def _classify_bare(
    row: Finding,
    snippet: str,
    move_mapping: dict[str, str],
) -> dict[str, Any]:
    old_module = f"gravity_sdk.{row.old_value}"
    if row.file.startswith("docs/archive/"):
        item = _none(
            "frozen_historical_text",
            "The occurrence is in docs/archive, which AGENTS.md defines as "
            "non-normative history rather than a current interface or consumer.",
            "repository_policy",
        )
        item["module_reference"] = _module_reference(old_module, move_mapping)
        return item
    if row.file not in ACTIVE_BARE_FILES:
        raise ValueError(f"unreviewed active bare string: {source_key(row)}")
    if old_module == RETAINED_MODULE:
        item = _none(
            "retained_module_reference",
            "R17 explicitly retains gravity_sdk.agent_runtime_contracts at the root; "
            "this active governance reference names that unchanged terminal owner.",
            "r17_scope_contract",
        )
        item["module_reference"] = _module_reference(old_module, move_mapping)
        return item
    if old_module == PAGINATION_MODULE:
        old_text, new_text = _replacement_texts(row, snippet, PAGINATION_TARGET)
        return {
            "disposition": "rewrite_consolidated_reference",
            "reason_code": "pagination_consolidation_reference",
            "migration_action": {
                "kind": "replace_module",
                "old_text": old_text,
                "new_text": new_text,
                "old_module": PAGINATION_MODULE,
                "new_module": PAGINATION_TARGET,
            },
            "basis": "The active governance source names the module that R17 "
            "consolidates into pagination_completeness and deletes.",
            "evidence_kind": "r17_scope_contract",
        }
    if old_module not in move_mapping:
        raise ValueError(f"active bare string is not an R17 move: {source_key(row)}")
    old_text, new_text = _replacement_texts(row, snippet, move_mapping[old_module])
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
        "basis": "The active governance source names a physical/shared-spine owner, "
        "so the reference must follow the one-to-one package move.",
        "evidence_kind": "audited_source_context",
    }


def _classify_dynamic(
    row: Finding, selector_rewrites: list[dict[str, str]]
) -> dict[str, Any]:
    if row.file == "src/gravity_sdk/__init__.py":
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
            "All _sdk_module call sites pass export_policy, registry, blob, "
            "export_models, or export_privacy; none is an agent module.",
        ),
        "src/gravity_sdk/prober/transport.py": (
            "fixed_non_agent_suffix",
            "The six expressions append fixed root-module suffixes outside R17.",
        ),
        "tests/test_gravity_material_performance.py": (
            "fixed_non_agent_test_domain",
            "The local module tuple and separately imported directory module are "
            "all outside the R17 module set.",
        ),
    }
    try:
        reason, basis = basis_by_file[row.file]
    except KeyError as exc:
        raise ValueError(f"unreviewed dynamic import: {source_key(row)}") from exc
    return _none(reason, basis, "finite_input_dataflow")


def _classify_patch(row: Finding) -> dict[str, Any]:
    if row.form in {"patch.object", "mock.patch.object"}:
        return _none(
            "direct_object_patch",
            f"{row.form} receives runtime object expression {row.old_value!r}; the "
            "API does not resolve a dotted module string.",
            "patch_api_semantics",
        )
    if row.form == "monkeypatch.setattr":
        return _none(
            "direct_object_monkeypatch",
            f"The reviewed first argument {row.old_value!r} is a bound object and the "
            "call supplies a separate attribute name.",
            "binding_and_patch_api_semantics",
        )
    if row.old_value == "target" and row.file in {
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
        (
            "src/gravity_sdk/sql/credentials.py",
            'f"{__name__}.restrict_local_secret"',
        ): "__name__ is gravity_sdk.sql.credentials.",
        (
            "tests/test_gravity_insight_core.py",
            'f"{_atomic_update_env.__module__}._restrict_secret_file"',
        ): "_atomic_update_env is owned by gravity_sdk.credentials.",
        (
            "tests/test_gravity_order_trace_surface.py",
            'f"gravity_sdk.{module}.runtime.build_client"',
        ): "module ranges only over order_trace_cli and order_directory_cli.",
        (
            "tests/test_http_receipt_durability.py",
            'f"gravity_sdk.executor.{stage}"',
        ): "stage ranges only over _project and _enforce_semantic_rules.",
        (
            "tests/test_sql_products.py",
            'f"gravity_sdk.sql.__main__.{patch_target}"',
        ): "patch_target ranges only over verify_all and credentials.pull.",
    }
    key = (row.file, row.old_value)
    if key not in fixed_non_agent:
        raise ValueError(f"unreviewed string-producing patch: {source_key(row)}")
    return _none(
        "fixed_non_agent_patch_path",
        fixed_non_agent[key] + " The target is outside the R17 module set.",
        "finite_input_dataflow",
    )


def _classify_owner(row: Finding) -> dict[str, Any]:
    if row.file in {
        "src/gravity_sdk/error_mapping.py",
        "src/gravity_sdk/error_models.py",
        "src/gravity_sdk/error_sql.py",
        "src/gravity_sdk/error_types.py",
    }:
        return _none(
            "compatibility_owner_assignment",
            "The receiver is a locally enumerated error compatibility symbol whose "
            "owner is normalized to gravity_sdk.errors.",
            "receiver_binding_census",
        )
    basis_by_file = {
        "tests/test_error_import_compatibility.py":
            "error_type is selected from gravity_sdk.errors.",
        "tests/test_execution_variant.py":
            "ExecutionVariantService is imported from gravity_sdk.execution_variant.",
        "tests/test_gravity_insight_core.py":
            "_atomic_update_env is imported from gravity_sdk.credentials.",
    }
    if row.file not in basis_by_file:
        raise ValueError(f"unreviewed owner receiver: {source_key(row)}")
    return _none(
        "receiver_owner_outside_r17",
        basis_by_file[row.file] + " That owner is outside the R17 move set.",
        "receiver_binding_census",
    )


def _classify_prefix(row: Finding) -> dict[str, Any]:
    return _none(
        "legacy_prefix_migration_sentinel",
        "The characterization helper intentionally recognizes both the legacy "
        "gravity_sdk.agent_ prefix and the target gravity_sdk.agents package so its "
        "terminal-state checks detect any stale old owner. It does not import or "
        "select a runtime module.",
        "migration_characterization_contract",
    )


def build_document() -> dict[str, Any]:
    audit = scan_repository(ROOT)
    manual = list(audit.manual_review)
    if len({source_key(row) for row in manual}) != len(manual):
        raise ValueError("manual-review source keys are not unique")
    moves, move_mapping = _module_universe(audit.mappings)
    snippets = _reference_snippets(audit.references)
    selector_rewrites = _selector_rewrites(move_mapping)
    sites: list[dict[str, Any]] = []
    for row in manual:
        category = _audit_category(row)
        source = {
            "file": row.file,
            "line": row.line,
            "column": row.column,
            "form": row.form,
            "old_value": row.old_value,
            "audit_proposed_value": row.new_value,
        }
        if category == "bare_agent_string":
            reference_key = (
                row.file,
                str(row.line),
                str(row.column),
                row.form,
                row.old_value,
                row.new_value,
            )
            if reference_key not in snippets:
                raise ValueError(f"missing reference evidence: {source_key(row)}")
            source["audit_snippet"] = snippets[reference_key]
            disposition = _classify_bare(
                row,
                snippets[reference_key],
                move_mapping,
            )
        elif category == "dynamic_import":
            disposition = _classify_dynamic(row, selector_rewrites)
        elif category == "non_string_patch_expression":
            disposition = _classify_patch(row)
        elif category == "module_owner_receiver":
            disposition = _classify_owner(row)
        else:
            disposition = _classify_prefix(row)
        sites.append(
            {
                "source_key": source_key(row),
                "audit_category": category,
                "source": source,
                **disposition,
            }
        )
    sites.sort(key=lambda item: item["source_key"])
    categories = Counter(item["audit_category"] for item in sites)
    dispositions = Counter(item["disposition"] for item in sites)
    if dict(categories) != EXPECTED_AUDIT_CATEGORIES:
        raise ValueError(f"audit category drift: {dict(categories)}")
    if dict(dispositions) != EXPECTED_DISPOSITIONS:
        raise ValueError(f"disposition drift: {dict(dispositions)}")
    sites_sha256 = hashlib.sha256(
        json.dumps(
            sites,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "gravity.agent-module-reference-dispositions.v2",
        "source_audit": {
            "method": "direct repository scan",
            "command": (
                ".venv/Scripts/python.exe "
                "scripts/generate_agent_module_reference_dispositions.py --check"
            ),
            "file_universe": "git ls-files --cached --others --exclude-standard",
            "scanner_path": SCANNER.relative_to(ROOT).as_posix(),
            "scanner_sha256": _sha256(SCANNER),
            "generator_path": GENERATOR.relative_to(ROOT).as_posix(),
            "generator_sha256": _sha256(GENERATOR),
            "candidate_map_sha256": canonical_sha256(audit.mappings),
            "reference_evidence_sha256": canonical_sha256(audit.references),
            "manual_review_sha256": canonical_sha256(audit.manual_review),
            "version_controlled_file_count": audit.version_controlled_file_count,
            "scanned_file_count": audit.scanned_file_count,
            "excluded_files": list(audit.excluded_files),
            "governance_exclusion_rule": GOVERNANCE_EXCLUSION_RULE,
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
        },
        "taxonomy": {
            "rewrite_reference": "Replace the exact active source text with its one-to-one moved owner.",
            "rewrite_selector_data": "Keep the dynamic import expression but rewrite all six exact lazy-owner selector values.",
            "rewrite_consolidated_reference": "Replace agent_pagination with pagination_completeness before deleting the old module.",
            "no_migration_effect": "Make no edit; the recorded basis proves the site is historical, object-bound, deliberately retained, or outside the R17 selector domain.",
            "runtime_verification_required": "Run the bounded verification before migration; failure becomes a blocker.",
            "blocker": "Do not start R17 until the ownership or selector proposition is resolved.",
        },
        "classification_method": {
            "bare_agent_string": "Classify frozen archive text, retained/consolidated owners, and every active governance path separately.",
            "agent_prefix_template": "Retain only the two migration-characterization sentinels that deliberately detect both legacy and target owners.",
            "non_string_patch_expression": "Separate object APIs from dotted-string APIs and inspect every finite producer/call domain.",
            "dynamic_import": "Trace each expression to finite inputs; rewrite the root lazy selector and reject unknown domains.",
            "module_owner_receiver": "Trace every receiver binding and retain only owners outside the R17 move set.",
        },
        "summary": {
            "site_count": len(sites),
            "unique_source_keys": len({item["source_key"] for item in sites}),
            "unclassified_sites": 0,
            "blocker_count": dispositions["blocker"],
            "audit_categories": dict(sorted(categories.items())),
            "dispositions": dict(sorted(dispositions.items())),
            "sites_sha256": sites_sha256,
        },
        "blockers": [],
        "sites": sites,
    }


def render_document(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args not in ([], ["--check"]):
        raise SystemExit(
            "usage: generate_agent_module_reference_dispositions.py [--check]"
        )
    rendered = render_document(build_document())
    if args == ["--check"]:
        if not OUTPUT.exists() or OUTPUT.read_bytes() != rendered:
            print(f"stale generated ledger: {OUTPUT.relative_to(ROOT)}", file=sys.stderr)
            return 1
        print(hashlib.sha256(rendered).hexdigest())
        return 0
    OUTPUT.write_bytes(rendered)
    print(hashlib.sha256(rendered).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
