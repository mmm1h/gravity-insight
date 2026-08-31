"""Generate the reviewed R17 disposition ledger from the current repository."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

try:
    from .audit_agent_module_references import (
        CURRENT_PACKAGE_ROOT,
        GOVERNANCE_EXCLUSION_RULE,
        HISTORICAL_PACKAGE_ROOT,
        PACKAGE_ROOT_MIGRATION,
        Finding,
        canonical_sha256,
        historical_module_root,
        project_module_root,
        projected_module_mapping,
        reference_module_mapping,
        scan_repository,
        source_key,
    )
except ImportError:
    from audit_agent_module_references import (  # type: ignore[no-redef]
        CURRENT_PACKAGE_ROOT,
        GOVERNANCE_EXCLUSION_RULE,
        HISTORICAL_PACKAGE_ROOT,
        PACKAGE_ROOT_MIGRATION,
        Finding,
        canonical_sha256,
        historical_module_root,
        project_module_root,
        projected_module_mapping,
        reference_module_mapping,
        scan_repository,
        source_key,
    )


ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "scripts/audit_agent_module_references.py"
GENERATOR = ROOT / "scripts/generate_agent_module_reference_dispositions.py"
PUBLIC_API_MANIFEST = (
    ROOT / "src/gravity_insight/governance/public-api-manifest.json"
)
BASELINE_LEDGER = ROOT / "tests/fixtures/agent_module_reference_dispositions.json"
OUTPUT = ROOT / "tests/fixtures/agent_module_reference_checkpoint.json"
REVIEWED_LEDGER_REVISION = "f2e8eec1f3c0567e20ab8c0be6465cc4e2c52e59"
REVIEWED_LEDGER_GIT_BLOB = "0fcfa6c85e07c7cc901530ed8c2fe7516203e986"
REVIEWED_LEDGER_SHA256 = "9d5b4d197cd84a0da4bb644256c9df7670ec89b7258e710434ab1ac8fed8be20"
REVIEWED_LEDGER_SCHEMA = "gravity.agent-module-reference-dispositions.v2"
ACTIVE_BARE_FILES = {
    "AGENTS.md",
    "docs/architecture.md",
    "docs/maintainers/technical-debt.md",
    "specs/agent-runtime/index.json",
    "specs/agent-runtime/index.md",
}
RETAINED_MODULE = "gravity_sdk.agent_runtime_contracts"
PAGINATION_MODULE = "gravity_sdk.agent_pagination"
PAGINATION_TARGET = "gravity_sdk.pagination_completeness"
DELETED_MODULE_RECORD = "deleted_module_governance_record"
DATED_DECISION_RECORD = "dated_governance_decision_record"
RUNTIME_CONSUMER = "runtime_consumer"
AMBIGUOUS_REFERENCE = "ambiguous_reference"
ACTIVE_REFERENCE = "active_reference"
CHECKPOINT_SITE_FIELDS = (
    "source_key",
    "tracked_sources",
    "audit_category",
    "old_value",
    "audit_proposed_value",
    "reference_category",
    "reference_certainty",
    "disposition",
    "reason_code",
    "basis_id",
    "migration_action",
)

_MARKDOWN_RECORD_START = re.compile(r"^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|```)")
_JSON_MEMBER_START = re.compile(r'^(?P<indent>\s*)"[^"]+"\s*:')
_DATED_DECISION_PATTERN = re.compile(
    r"(?:\u7acb\u9879|decision(?:\s+record)?)\s*[\uff08(]"
    r"\d{4}-\d{2}-\d{2}[\uff09)]",
    re.IGNORECASE,
)


def _has_current_path_semantics(old_module: str, context: str) -> bool:
    """Recognize executable/current-path syntax before historical evidence."""

    package_root, _, module_suffix = old_module.partition(".")
    short = re.escape(module_suffix)
    qualified = rf"(?:(?:{re.escape(package_root)}\.)?{short}|\.{short})"
    patterns = (
        rf"\bfrom\s+{qualified}\s+import\b",
        rf"\bimport\s+{qualified}\b",
        rf"{qualified}\s*\.(?!py\b)[A-Za-z_]\w*",
        rf"{qualified}\s*\(",
        rf"(?:import_module|__import__|patch(?:\.object)?|monkeypatch\.setattr|"
        rf"getattr)\s*\([^\n)]{{0,160}}{qualified}",
        rf"\b(?:consumer|caller|call|invoke|use|import|patch)\b"
        rf"[^\n]{{0,120}}{qualified}",
        rf"(?:src/{re.escape(package_root)}/)?{short}\.py",
    )
    return any(re.search(pattern, context, re.IGNORECASE) for pattern in patterns)
_PACKAGE_ROOT_PATTERN = rf"(?:{HISTORICAL_PACKAGE_ROOT}|{CURRENT_PACKAGE_ROOT})"
_PAGINATION_CONSUMER_PATTERN = re.compile(
    rf"(?:\bfrom\s+(?:(?:{_PACKAGE_ROOT_PATTERN}\.)?\.?agent_pagination\s+import\b"
    rf"|{_PACKAGE_ROOT_PATTERN}\s+import\s+agent_pagination\b)"
    rf"|\bimport\s+(?:{_PACKAGE_ROOT_PATTERN}\.)?agent_pagination\b"
    rf"|(?:{_PACKAGE_ROOT_PATTERN}\.)?agent_pagination\s*\.(?!py\b)[A-Za-z_]"
    r"|(?:import_module|__import__|patch(?:\.object)?|monkeypatch\.setattr)"
    r"\s*\([^\n)]*agent_pagination"
    r"|\b(?:consumer|caller|call|invoke|use|import|patch)\b"
    r"[^\n]{0,80}\bagent_pagination\b"
    r"|(?:\u8c03\u7528|\u5bfc\u5165)\s*`?"
    rf"(?:{_PACKAGE_ROOT_PATTERN}\.)?agent_pagination(?![A-Za-z0-9_]))",
    re.IGNORECASE,
)
_PAGINATION_DELETION_PATTERNS = (
    re.compile(
        r'"consolidated_deleted_modules"\s*:\s*\[[^\]]*'
        r'"agent_pagination"',
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"agent_pagination[\s\S]{0,120}"
        r"(?:\u5408\u5e76\u5220\u9664|consolidat(?:e[sd]?|ion)"
        r"[\s\S]{0,40}(?:delet|remov)|\b(?:deleted|removed)\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:\u5408\u5e76\u5220\u9664|consolidat(?:e[sd]?|ion)"
        r"[\s\S]{0,40}(?:delet|remov)|\b(?:deleted|removed)\s+modules?\b)"
        r"[\s\S]{0,120}agent_pagination",
        re.IGNORECASE,
    ),
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reviewed_generator_sha256() -> str:
    relative = GENERATOR.relative_to(ROOT).as_posix()
    reviewed = subprocess.run(
        ["git", "show", f"{REVIEWED_LEDGER_REVISION}:{relative}"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    return hashlib.sha256(reviewed).hexdigest()


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
        and row.old_value
        in {
            f"{HISTORICAL_PACKAGE_ROOT}.agent_",
            f"{CURRENT_PACKAGE_ROOT}.agent_",
        }
    ):
        return "agent_prefix_template"
    raise ValueError(f"unrecognized audit row: {source_key(row)}")


def _module_universe(
    mappings: tuple[Any, ...],
) -> tuple[list[dict[str, str]], dict[str, str]]:
    if len(mappings) != 84 or len({row.old_module for row in mappings}) != 84:
        raise ValueError("the repository scan must find 84 unique reviewed modules")
    moves: list[dict[str, str]] = []
    mapping: dict[str, str] = {}
    for row in mappings:
        old = row.old_module
        if old in {PAGINATION_MODULE, RETAINED_MODULE}:
            continue
        moves.append({"old_module": old, "new_module": row.new_module})
        mapping[old] = row.new_module
    moves.sort(key=lambda item: item["old_module"])
    if len(moves) != 82:
        raise ValueError("current R17 scope must contain 82 one-to-one moves")
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


def _projected_public_exports() -> dict[str, Any]:
    document = json.loads(PUBLIC_API_MANIFEST.read_text(encoding="utf-8"))
    rows = document.get("exports") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise ValueError("stable public API manifest exports must be a list")
    exports: dict[str, list[str]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != {"name", "module", "attribute"}:
            raise ValueError(f"stable public API manifest export {index} is invalid")
        symbol = row["name"]
        if symbol in exports:
            raise ValueError(f"stable public API manifest repeats {symbol!r}")
        exports[symbol] = [row["module"], row["attribute"]]
    return exports


def _selector_rewrites(
    move_mapping: dict[str, str], exports: dict[str, Any] | None = None
) -> tuple[str, list[dict[str, str]]]:
    exports = _projected_public_exports() if exports is None else exports
    rewrites: list[dict[str, str]] = []
    owner_states: set[str] = set()
    reverse_mapping = {new: old for old, new in move_mapping.items()}
    for symbol, (owner, attribute) in exports.items():
        current_module = f"{CURRENT_PACKAGE_ROOT}{owner}"
        if current_module in move_mapping:
            old_module = current_module
            owner_states.add("legacy")
        elif current_module in reverse_mapping:
            old_module = reverse_mapping[current_module]
            owner_states.add("migrated")
        else:
            continue
        new_module = move_mapping[old_module]
        rewrites.append(
            {
                "symbol": symbol,
                "attribute": attribute,
                "old_value": owner,
                "new_value": new_module.removeprefix(CURRENT_PACKAGE_ROOT),
                "old_module": old_module,
                "new_module": new_module,
            }
        )
    rewrites.sort(key=lambda item: item["symbol"])
    if len(rewrites) != 6:
        raise ValueError("the lazy selector must have exactly six moved owners")
    state = next(iter(owner_states)) if len(owner_states) == 1 else "mixed"
    return state, rewrites


def _none(reason_code: str, basis: str, evidence_kind: str) -> dict[str, Any]:
    return {
        "disposition": "no_migration_effect",
        "reason_code": reason_code,
        "migration_action": {"kind": "none"},
        "basis": basis,
        "evidence_kind": evidence_kind,
    }


def _blocker(reason_code: str, basis: str, evidence_kind: str) -> dict[str, Any]:
    return {
        "disposition": "blocker",
        "reason_code": reason_code,
        "migration_action": {"kind": "block"},
        "basis": basis,
        "evidence_kind": evidence_kind,
    }


def _module_reference(old_module: str, move_mapping: dict[str, str]) -> dict[str, str]:
    result = {"old_module": old_module}
    if old_module in move_mapping:
        result["candidate_new_module"] = move_mapping[old_module]
    elif historical_module_root(old_module) == PAGINATION_MODULE:
        result["candidate_new_module"] = (
            project_module_root(PAGINATION_TARGET)
            if old_module.startswith(CURRENT_PACKAGE_ROOT + ".")
            else PAGINATION_TARGET
        )
    return result


def _replacement_texts(row: Finding, snippet: str, new_module: str) -> tuple[str, str]:
    old_short = row.old_value
    short = new_module.rsplit(".", 1)[1]
    package_root = new_module.split(".", 1)[0]
    full_source = f"src/{package_root}/{old_short}.py"
    if full_source in snippet:
        return full_source, "src/" + new_module.replace(".", "/") + ".py"
    if f"{old_short}.py" in snippet:
        return f"{old_short}.py", f"agents/{short}.py"
    return old_short, new_module.removeprefix(package_root + ".")


def _logical_source_context(row: Finding, root: Path = ROOT) -> str:
    """Return the bounded governance record containing a bare module name."""

    lines = (root / row.file).read_text(encoding="utf-8").splitlines()
    index = row.line - 1
    if index < 0 or index >= len(lines):
        raise ValueError(f"source line is outside file: {source_key(row)}")
    if Path(row.file).suffix == ".json":
        start = index
        while start > 0 and not _JSON_MEMBER_START.match(lines[start]):
            start -= 1
        member = _JSON_MEMBER_START.match(lines[start])
        if member is None:
            raise ValueError(f"JSON reference has no containing member: {source_key(row)}")
        indent = len(member.group("indent"))
        end = start + 1
        while end < len(lines):
            following = _JSON_MEMBER_START.match(lines[end])
            if following is not None and len(following.group("indent")) <= indent:
                break
            end += 1
        return "\n".join(lines[start:end])

    start = index
    if not _MARKDOWN_RECORD_START.match(lines[start]):
        while start > 0 and lines[start - 1].strip():
            start -= 1
            if _MARKDOWN_RECORD_START.match(lines[start]):
                break
    end = index + 1
    while end < len(lines) and lines[end].strip():
        if _MARKDOWN_RECORD_START.match(lines[end]):
            break
        end += 1
    return "\n".join(lines[start:end])


def classify_active_bare_context(old_module: str, context: str) -> str:
    """Classify an active governance mention without relying on coordinates."""

    if historical_module_root(old_module) == PAGINATION_MODULE:
        if _PAGINATION_CONSUMER_PATTERN.search(context):
            return RUNTIME_CONSUMER
        if any(pattern.search(context) for pattern in _PAGINATION_DELETION_PATTERNS):
            return DELETED_MODULE_RECORD
        return AMBIGUOUS_REFERENCE
    if _has_current_path_semantics(old_module, context):
        return ACTIVE_REFERENCE
    if _DATED_DECISION_PATTERN.search(context):
        return DATED_DECISION_RECORD
    return ACTIVE_REFERENCE


def _classify_bare(
    row: Finding,
    snippet: str,
    context: str,
    move_mapping: dict[str, str],
) -> dict[str, Any]:
    package_root = (
        HISTORICAL_PACKAGE_ROOT
        if row.file.startswith("docs/archive/")
        else CURRENT_PACKAGE_ROOT
    )
    old_module = f"{package_root}.{row.old_value}"
    historical_old_module = historical_module_root(old_module)
    if row.file.startswith("docs/archive/"):
        item = _none(
            "frozen_historical_exact_reference",
            "The occurrence is in docs/archive, which AGENTS.md defines as "
            "non-normative history rather than a current interface or consumer.",
            "repository_policy",
        )
        item["module_reference"] = _module_reference(old_module, move_mapping)
        return item
    if row.file not in ACTIVE_BARE_FILES:
        return _blocker(
            "unreviewed_active_bare_reference",
            "This active bare module reference is outside the reviewed governance "
            "record set and has no safe migration interpretation.",
            "unresolved_source_context",
        )
    if historical_old_module == RETAINED_MODULE:
        item = _none(
            "retained_exact_reference",
            "R17 retained the historical gravity_sdk.agent_runtime_contracts owner; "
            "the package-root migration projects it to the current root without "
            "changing the R17 disposition.",
            "r17_scope_contract",
        )
        item["module_reference"] = _module_reference(old_module, move_mapping)
        return item
    context_kind = classify_active_bare_context(old_module, context)
    if historical_old_module == PAGINATION_MODULE:
        if context_kind == DELETED_MODULE_RECORD:
            item = _none(
                "deleted_module_governance_fact",
                "The bounded governance record identifies agent_pagination as the "
                "module consolidated and deleted. Replacing it with the retained "
                "pagination_completeness owner would invert the recorded fact.",
                "governance_record_semantics",
            )
            item["module_reference"] = _module_reference(old_module, move_mapping)
            return item
        if context_kind == AMBIGUOUS_REFERENCE:
            return {
                "disposition": "blocker",
                "reason_code": "ambiguous_deleted_module_reference",
                "migration_action": {"kind": "block"},
                "basis": "The active reference names the deleted module but its "
                "bounded record proves neither a deletion fact nor runtime consumer "
                "syntax; R17 must stop for classification.",
                "evidence_kind": "audited_source_context",
            }
        pagination_target = (
            project_module_root(PAGINATION_TARGET)
            if package_root == CURRENT_PACKAGE_ROOT
            else PAGINATION_TARGET
        )
        old_text, new_text = _replacement_texts(row, snippet, pagination_target)
        return {
            "disposition": "rewrite_consolidated_reference",
            "reason_code": "pagination_consolidation_exact_reference",
            "migration_action": {
                "kind": "replace_module",
                "old_text": old_text,
                "new_text": new_text,
                "old_module": old_module,
                "new_module": pagination_target,
            },
            "basis": "The active governance source names the module that R17 "
            "consolidates into pagination_completeness and deletes.",
            "evidence_kind": "r17_scope_contract",
        }
    if old_module not in move_mapping:
        return _blocker(
            "bare_reference_outside_frozen_scope",
            "The active bare module reference is neither retained, consolidated, "
            "nor present in the exact 82-move scope.",
            "frozen_scope_mismatch",
        )
    if context_kind == DATED_DECISION_RECORD:
        item = _none(
            "dated_governance_decision_evidence",
            "The dated establishment record preserves the baseline graph-node name "
            "used by its recorded inbound-edge measurement; it is evidence rather "
            "than an executable or current path.",
            "governance_record_semantics",
        )
        item["module_reference"] = _module_reference(old_module, move_mapping)
        return item
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
    row: Finding, selector_state: str, selector_rewrites: list[dict[str, str]]
) -> dict[str, Any]:
    if row.file == "src/gravity_insight/__init__.py":
        if selector_state == "migrated":
            return _none(
                "root_lazy_export_owner_map_migrated",
                "All six finite _EXPORTS owner values already name their terminal "
                "gravity_insight.agents owners.",
                "finite_selector_dataflow",
            )
        if selector_state != "legacy":
            return _blocker(
                "mixed_root_lazy_export_owner_map",
                "The six finite _EXPORTS owner values mix legacy and terminal "
                "owners; the selector must transition atomically.",
                "finite_selector_dataflow",
            )
        return {
            "disposition": "rewrite_selector_data",
            "reason_code": "root_lazy_export_owner_map",
            "migration_action": {
                "kind": "replace_selector_values",
                "selector": "gravity_insight._EXPORTS",
                "rewrites": selector_rewrites,
            },
            "basis": "__getattr__ imports only module_name values from _EXPORTS; "
            "the public export snapshot proves exactly six values select R17 moves.",
            "evidence_kind": "finite_selector_dataflow",
        }
    basis_by_file = {
        "src/gravity_insight/runtime.py": (
            "root_package_only",
            "The loop input is the literal singleton ('gravity_insight',), so it cannot "
            "select any deep agent module.",
        ),
        "src/gravity_insight/prober/cli.py": (
            "fixed_non_agent_suffix",
            "sdk.__name__ is gravity_insight and the only appended suffix is '.errors'.",
        ),
        "src/gravity_insight/prober/export_verify.py": (
            "fixed_non_agent_call_domain",
            "All _sdk_module call sites pass export_policy, registry, blob, "
            "export_models, or export_privacy; none is an agent module.",
        ),
        "src/gravity_insight/prober/transport.py": (
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
    except KeyError:
        return _blocker(
            "unreviewed_dynamic_import_domain",
            "The dynamic import producer has no finite, reviewed input domain; "
            "R17 cannot prove that it excludes a moved or deleted owner.",
            "unresolved_dynamic_dataflow",
        )
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
            "src/gravity_insight/sql/credentials.py",
            'f"{__name__}.restrict_local_secret"',
        ): "__name__ is gravity_insight.sql.credentials.",
        (
            "tests/test_gravity_insight_core.py",
            'f"{_atomic_update_env.__module__}._restrict_secret_file"',
        ): "_atomic_update_env is owned by gravity_insight.credentials.",
        (
            "tests/test_gravity_order_trace_surface.py",
            'f"gravity_insight.{module}.runtime.build_client"',
        ): "module ranges only over order_trace_cli and order_directory_cli.",
        (
            "tests/test_http_receipt_durability.py",
            'f"gravity_insight.executor.{stage}"',
        ): "stage ranges only over _project and _enforce_semantic_rules.",
        (
            "tests/test_sql_products.py",
            'f"gravity_insight.sql.__main__.{patch_target}"',
        ): "patch_target ranges only over verify_all and credentials.pull.",
    }
    key = (row.file, row.old_value)
    if key not in fixed_non_agent:
        return _blocker(
            "unreviewed_patch_target_domain",
            "The string-producing patch target has no finite, reviewed producer "
            "domain; migration ownership is not statically provable.",
            "unresolved_dynamic_dataflow",
        )
    return _none(
        "fixed_non_agent_patch_path",
        fixed_non_agent[key] + " The target is outside the R17 module set.",
        "finite_input_dataflow",
    )


def _classify_owner(row: Finding) -> dict[str, Any]:
    if row.file in {
        "src/gravity_insight/error_mapping.py",
        "src/gravity_insight/error_models.py",
        "src/gravity_insight/error_sql.py",
        "src/gravity_insight/error_types.py",
    }:
        return _none(
            "compatibility_owner_assignment",
            "The receiver is a locally enumerated error compatibility symbol whose "
            "owner is normalized to gravity_insight.errors.",
            "receiver_binding_census",
        )
    basis_by_file = {
        "tests/test_error_import_compatibility.py":
            "error_type is selected from gravity_insight.errors.",
        "tests/test_execution_variant.py":
            "ExecutionVariantService is imported from gravity_insight.execution_variant.",
        "tests/test_gravity_insight_core.py":
            "_atomic_update_env is imported from gravity_insight.credentials.",
    }
    if row.file not in basis_by_file:
        return _blocker(
            "unreviewed_owner_receiver",
            "The __module__/__qualname__ receiver owner is not in the reviewed "
            "binding census.",
            "unresolved_receiver_binding",
        )
    return _none(
        "receiver_owner_outside_r17",
        basis_by_file[row.file] + " That owner is outside the R17 move set.",
        "receiver_binding_census",
    )


def _classify_prefix(row: Finding) -> dict[str, Any]:
    return _none(
        "legacy_prefix_migration_sentinel",
        "The characterization helper uses the legacy prefix only to classify deep "
        "path references and validate ledger row shape. SCC membership comes from "
        "the exact 82 move rows plus pagination consolidation, not this prefix.",
        "migration_characterization_contract",
    )


def _finding_identity(row: Finding) -> tuple[str, int, int, str, str, str]:
    return (
        row.file,
        row.line,
        row.column,
        row.form,
        row.old_value,
        row.new_value,
    )


def _old_module_for_reference(
    row: Finding, complete_mapping: dict[str, str]
) -> str | None:
    if row.old_value in complete_mapping:
        return row.old_value
    for old_module in complete_mapping:
        if row.old_value == "src/" + old_module.replace(".", "/") + ".py":
            return old_module
    return None


def _classify_reference(
    row: Finding,
    move_mapping: dict[str, str],
    complete_mapping: dict[str, str],
    root: Path = ROOT,
) -> dict[str, Any]:
    old_module = _old_module_for_reference(row, complete_mapping)
    if row.certainty not in {"exact", "constant-folded"} or old_module is None:
        return _blocker(
            "unreviewed_reference_evidence",
            "The scanner emitted a reference without an exact owner mapping or a "
            "manual-review disposition.",
            "reference_denominator",
        )
    historical_old_module = historical_module_root(old_module)
    if row.file.startswith("docs/archive/"):
        item = _none(
            "frozen_historical_text",
            "The exact reference is in docs/archive, which is non-normative history "
            "and must preserve the recorded path.",
            "repository_policy",
        )
        item["module_reference"] = _module_reference(old_module, move_mapping)
        return item
    if (
        row.file == "tests/test_agent_concept_deletions.py"
        and row.category == "string_reference"
    ):
        item = _none(
            "phase_state_contract_sentinel",
            "The concept-deletion gate intentionally names old and terminal owners "
            "to validate baseline, Phase 1, and Phase 2 states from one test.",
            "three_state_gate_contract",
        )
        item["module_reference"] = _module_reference(old_module, move_mapping)
        return item
    if historical_old_module == RETAINED_MODULE:
        item = _none(
            "retained_module_reference",
            "R17 retains the historical gravity_sdk.agent_runtime_contracts owner; "
            "the current package-root projection preserves that disposition.",
            "r17_scope_contract",
        )
        item["module_reference"] = _module_reference(old_module, move_mapping)
        return item
    if historical_old_module == PAGINATION_MODULE:
        textual_categories = {
            "documentation_spec",
            "entrypoint_config",
            "test_fixture",
            "string_reference",
        }
        if row.category in textual_categories:
            context = (
                row.details
                if row.category == "string_reference"
                else _logical_source_context(row, root)
            )
            context_kind = classify_active_bare_context(old_module, context)
            if context_kind == DELETED_MODULE_RECORD:
                item = _none(
                    "deleted_module_governance_fact",
                    "The bounded record identifies gravity_sdk.agent_pagination as "
                    "the module consolidated and deleted. Replacing it with the "
                    "retained owner would invert the recorded fact.",
                    "governance_record_semantics",
                )
                item["module_reference"] = _module_reference(
                    old_module, move_mapping
                )
                return item
            if context_kind == AMBIGUOUS_REFERENCE:
                return _blocker(
                    "ambiguous_deleted_module_reference",
                    "The exact textual reference names the deleted module but its "
                    "bounded record proves neither a deletion fact nor consumer "
                    "syntax; R17 must stop for classification.",
                    "audited_source_context",
                )
        pagination_target = (
            project_module_root(PAGINATION_TARGET)
            if old_module.startswith(CURRENT_PACKAGE_ROOT + ".")
            else PAGINATION_TARGET
        )
        return {
            "disposition": "rewrite_consolidated_reference",
            "reason_code": "pagination_consolidation_reference",
            "migration_action": {
                "kind": "replace_module",
                "old_text": row.old_value,
                "new_text": row.new_value,
                "old_module": old_module,
                "new_module": pagination_target,
            },
            "basis": "The exact reference names the owner R17 consolidates into "
            "pagination_completeness and deletes.",
            "evidence_kind": "exact_reference_mapping",
        }
    if old_module not in move_mapping:
        return _blocker(
            "reference_outside_frozen_scope",
            "The exact reference is neither retained, consolidated, nor present in "
            "the immutable 82-move scope.",
            "frozen_scope_mismatch",
        )
    return {
        "disposition": "rewrite_reference",
        "reason_code": "exact_owner_reference",
        "migration_action": {
            "kind": "replace_text",
            "old_text": row.old_value,
            "new_text": row.new_value,
            "old_module": old_module,
            "new_module": move_mapping[old_module],
        },
        "basis": "The scanner resolved this exact reference to one immutable R17 "
        "move pair; the reference must follow that owner.",
        "evidence_kind": "exact_reference_mapping",
    }


def _classify_manual(
    row: Finding,
    source: dict[str, Any],
    snippets: dict[tuple[str, ...], str],
    selector_state: str,
    selector_rewrites: list[dict[str, str]],
    move_mapping: dict[str, str],
    root: Path,
) -> tuple[str, dict[str, Any]]:
    category = _audit_category(row)
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
            return category, _blocker(
                "missing_reference_evidence",
                "The manual-review row has no corresponding scanner reference.",
                "reference_denominator",
            )
        source["audit_snippet"] = snippets[reference_key]
        context = snippets[reference_key]
        if row.file in ACTIVE_BARE_FILES:
            context = _logical_source_context(row, root)
            source["audit_context"] = context
        return category, _classify_bare(
            row, snippets[reference_key], context, move_mapping
        )
    if category == "dynamic_import":
        return category, _classify_dynamic(row, selector_state, selector_rewrites)
    if category == "non_string_patch_expression":
        return category, _classify_patch(row)
    if category == "module_owner_receiver":
        return category, _classify_owner(row)
    return category, _classify_prefix(row)


def _immutable_baseline_binding() -> dict[str, Any]:
    repository_path = BASELINE_LEDGER.relative_to(ROOT).as_posix()
    reviewed_blob = subprocess.run(
        ["git", "rev-parse", f"{REVIEWED_LEDGER_REVISION}:{repository_path}"],
        cwd=ROOT,
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()
    if reviewed_blob != REVIEWED_LEDGER_GIT_BLOB:
        raise ValueError("immutable baseline blob differs at the review revision path")
    current_blob = subprocess.run(
        ["git", "rev-parse", f"HEAD:{repository_path}"],
        cwd=ROOT,
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()
    if current_blob != reviewed_blob:
        raise ValueError("current commit changed the reviewed baseline ledger")
    completed = subprocess.run(
        ["git", "cat-file", "blob", REVIEWED_LEDGER_GIT_BLOB],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    bound = completed.stdout
    if hashlib.sha256(bound).hexdigest() != REVIEWED_LEDGER_SHA256:
        raise ValueError("immutable baseline Git object differs from reviewed digest")
    if BASELINE_LEDGER.read_bytes() != bound:
        raise ValueError("working-tree baseline ledger differs from immutable Git object")
    return {
        "role": "errata_source_only_immutable_baseline",
        "repository_path": repository_path,
        "git_blob": REVIEWED_LEDGER_GIT_BLOB,
        "sha256": REVIEWED_LEDGER_SHA256,
        "schema_version": REVIEWED_LEDGER_SCHEMA,
    }


def checkpoint_sites(document: dict[str, Any]) -> list[dict[str, Any]]:
    if tuple(document.get("site_fields", ())) != CHECKPOINT_SITE_FIELDS:
        raise ValueError("checkpoint site field schema changed")
    tracked_sources = {
        "r": ["reference"],
        "m": ["manual_review"],
        "rm": ["reference", "manual_review"],
    }
    result: list[dict[str, Any]] = []
    for record in document.get("sites", []):
        if not isinstance(record, list) or len(record) != len(CHECKPOINT_SITE_FIELDS):
            raise ValueError("invalid checkpoint site record")
        values = dict(zip(CHECKPOINT_SITE_FIELDS, record))
        key = values["source_key"]
        if not isinstance(key, str):
            raise ValueError("checkpoint source key must be a string")
        file, line, column, form = key.split(":", 3)
        source = {
            "file": file,
            "line": int(line),
            "column": int(column),
            "form": form,
            "old_value": values["old_value"],
            "audit_proposed_value": values["audit_proposed_value"],
        }
        if values["reference_category"] is not None:
            source["reference_category"] = values["reference_category"]
            source["reference_certainty"] = values["reference_certainty"]
        result.append(
            {
                "source_key": key,
                "tracked_sources": tracked_sources[values["tracked_sources"]],
                "audit_category": values["audit_category"],
                "source": source,
                "disposition": values["disposition"],
                "reason_code": values["reason_code"],
                "basis_id": values["basis_id"],
                "migration_action": values["migration_action"],
            }
        )
    return result


def build_document(
    *,
    root: Path = ROOT,
    audit: Any | None = None,
    public_exports: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit = scan_repository(root) if audit is None else audit
    references = {_finding_identity(row): row for row in audit.references}
    manual = {_finding_identity(row): row for row in audit.manual_review}
    if len(references) != len(audit.references):
        raise ValueError("reference source keys are not unique")
    if len(manual) != len(audit.manual_review):
        raise ValueError("manual-review source keys are not unique")
    moves, historical_move_mapping = _module_universe(audit.mappings)
    move_mapping = reference_module_mapping(historical_move_mapping)
    complete_mapping = reference_module_mapping(
        {row.old_module: row.new_module for row in audit.mappings}
    )
    snippets = _reference_snippets(audit.references)
    selector_state, selector_rewrites = _selector_rewrites(
        projected_module_mapping(historical_move_mapping), public_exports
    )
    sites: list[dict[str, Any]] = []
    for identity in sorted(set(references) | set(manual)):
        reference_row = references.get(identity)
        manual_row = manual.get(identity)
        row = reference_row or manual_row
        assert row is not None
        source = {
            "file": row.file,
            "line": row.line,
            "column": row.column,
            "form": row.form,
            "old_value": row.old_value,
            "audit_proposed_value": row.new_value,
        }
        tracked_sources: list[str] = []
        if reference_row is not None:
            tracked_sources.append("reference")
            source["reference_category"] = reference_row.category
            source["reference_certainty"] = reference_row.certainty
            source["audit_snippet"] = reference_row.details
        if manual_row is not None:
            tracked_sources.append("manual_review")
            audit_category, disposition = _classify_manual(
                manual_row,
                source,
                snippets,
                selector_state,
                selector_rewrites,
                move_mapping,
                root,
            )
        else:
            audit_category = "exact_reference"
            assert reference_row is not None
            disposition = _classify_reference(
                reference_row, move_mapping, complete_mapping, root
            )
        sites.append(
            {
                "source_key": source_key(row),
                "tracked_sources": tracked_sources,
                "audit_category": audit_category,
                "source": source,
                **disposition,
            }
        )
    sites.sort(key=lambda item: item["source_key"])
    manual_categories = Counter(
        item["audit_category"]
        for item in sites
        if "manual_review" in item["tracked_sources"]
    )
    reference_categories = Counter(row.category for row in audit.references)
    dispositions = Counter(item["disposition"] for item in sites)
    actionable = sum(
        disposition.startswith("rewrite_") for disposition in dispositions.elements()
    )
    blockers = [
        {
            "source_key": item["source_key"],
            "reason_code": item["reason_code"],
            "basis": item["basis"],
        }
        for item in sites
        if item["disposition"] == "blocker"
    ]
    if audit.owner_state == "phase_2" and actionable:
        blockers.append(
            {
                "source_key": None,
                "reason_code": "phase_2_actionable_reference_residue",
                "basis": f"Phase 2 still has {actionable} rewrite dispositions.",
            }
        )
    classification_basis_by_key: dict[str, dict[str, str]] = {}
    for site in sites:
        reason_code = site["reason_code"]
        basis = {
            "basis": site.pop("basis"),
            "evidence_kind": site.pop("evidence_kind"),
        }
        basis_key = reason_code + ":" + hashlib.sha256(
            json.dumps(basis, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:12]
        site["basis_id"] = basis_key
        classification_basis_by_key.setdefault(basis_key, basis)
        source = site["source"]
        source.pop("audit_snippet", None)
        source.pop("audit_context", None)
        action = site["migration_action"]
        if site["audit_category"] == "exact_reference" and action.get("kind") in {
            "replace_text",
            "replace_module",
        }:
            action.pop("old_text", None)
            action.pop("new_text", None)
        site.pop("module_reference", None)
    basis_keys = sorted(classification_basis_by_key)
    basis_ids = {key: index for index, key in enumerate(basis_keys)}
    for site in sites:
        site["basis_id"] = basis_ids[site["basis_id"]]
    site_records = [
        [
            site["source_key"],
            "rm"
            if set(site["tracked_sources"]) == {"reference", "manual_review"}
            else "r"
            if site["tracked_sources"] == ["reference"]
            else "m",
            site["audit_category"],
            site["source"]["old_value"],
            site["source"]["audit_proposed_value"],
            site["source"].get("reference_category"),
            site["source"].get("reference_certainty"),
            site["disposition"],
            site["reason_code"],
            site["basis_id"],
            site["migration_action"],
        ]
        for site in sites
    ]
    sites_sha256 = hashlib.sha256(
        json.dumps(
            site_records,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": "gravity.agent-module-reference-checkpoint.v2",
        "receipt_role": (
            "live_checkpoint_scan_only; not authority for canonical errata replacements"
        ),
        "immutable_baseline_ledger": _immutable_baseline_binding(),
        "package_root_migration": {
            **PACKAGE_ROOT_MIGRATION,
            "historical_evidence_role": (
                "immutable_baseline_records_names_at_r17_delivery_time"
            ),
            "current_validation_role": (
                "project_historical_r17_owners_before_filesystem_and_reference_checks"
            ),
            "compatibility_package_present": False,
            "projected_scope_sha256": hashlib.sha256(
                json.dumps(
                    [
                        {
                            "old_module": project_module_root(row["old_module"]),
                            "new_module": project_module_root(row["new_module"]),
                        }
                        for row in moves
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        },
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
            # The checkpoint bytes are index-bound; this identifies the fixed
            # reviewed generator while current logic still recomputes every site.
            "generator_sha256": _reviewed_generator_sha256(),
            "candidate_map_sha256": canonical_sha256(audit.mappings),
            "reference_evidence_sha256": canonical_sha256(audit.references),
            "manual_review_sha256": canonical_sha256(audit.manual_review),
            "owner_state": audit.owner_state,
            "version_controlled_file_count": audit.version_controlled_file_count,
            "scanned_file_count": audit.scanned_file_count,
            "excluded_files": list(audit.excluded_files),
            "governance_exclusion_rule": GOVERNANCE_EXCLUSION_RULE,
            "source_key_format": "{file}:{line}:{column}:{form}",
        },
        "scope": {
            "audit_candidate_modules": 84,
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
            "no_migration_effect": "Make no edit; the recorded basis proves the site is historical, a governance fact/evidence record, object-bound, deliberately retained, or outside the R17 selector domain.",
            "runtime_verification_required": "Run the bounded verification before migration; failure becomes a blocker.",
            "blocker": "Do not start R17 until the ownership or selector proposition is resolved.",
        },
        "classification_method": {
            "exact_reference": "Every scanner reference receives a coordinate-bound disposition. Exact moved owners rewrite, the retained owner remains, pagination consolidates, archive evidence remains frozen, and unknown mappings block.",
            "bare_agent_string": "Classify each bounded Markdown record or JSON field: recognize consumer/current-path syntax before considering dated evidence, freeze only non-consumer dated decisions and explicit consolidated/deleted-module facts, rewrite active one-to-one paths, and block ambiguous deleted-module mentions.",
            "agent_prefix_template": "Retain only the two characterization uses that classify legacy deep paths and validate old-module ledger shape; SCC membership is ledger-defined.",
            "non_string_patch_expression": "Separate object APIs from dotted-string APIs and inspect every finite producer/call domain.",
            "dynamic_import": "Trace each expression to finite inputs; rewrite the root lazy selector and reject unknown domains.",
            "module_owner_receiver": "Trace every receiver binding and retain only owners outside the R17 move set.",
        },
        "classification_basis": [
            classification_basis_by_key[key] for key in basis_keys
        ],
        "summary": {
            "tracked_site_count": len(sites),
            "reference_site_count": len(references),
            "manual_review_site_count": len(manual),
            "reference_manual_overlap_count": len(set(references) & set(manual)),
            "manual_only_site_count": len(set(manual) - set(references)),
            "unique_source_keys": len({item["source_key"] for item in sites}),
            "unclassified_sites": 0,
            "blocker_count": len(blockers),
            "site_blocker_count": dispositions["blocker"],
            "actionable_site_count": actionable,
            "reference_categories": dict(sorted(reference_categories.items())),
            "manual_review_categories": dict(sorted(manual_categories.items())),
            "dispositions": dict(sorted(dispositions.items())),
            "sites_sha256": sites_sha256,
        },
        "blockers": blockers,
        "site_fields": list(CHECKPOINT_SITE_FIELDS),
        "sites": site_records,
    }


def render_document(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if args not in ([], ["--check"]):
        raise SystemExit(
            "usage: generate_agent_module_reference_dispositions.py [--check]"
        )
    try:
        document = build_document()
        rendered = render_document(document)
    except (KeyError, OSError, RuntimeError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"R17 checkpoint generation failed: {exc}", file=sys.stderr)
        return 1
    if args == ["--check"]:
        if not OUTPUT.exists() or OUTPUT.read_bytes() != rendered:
            print(f"stale checkpoint receipt: {OUTPUT.relative_to(ROOT)}", file=sys.stderr)
            return 1
        if document["blockers"]:
            print(
                "checkpoint blockers: "
                + json.dumps(document["blockers"], ensure_ascii=False),
                file=sys.stderr,
            )
            return 1
        print(hashlib.sha256(rendered).hexdigest())
        return 0
    OUTPUT.write_bytes(rendered)
    print(hashlib.sha256(rendered).hexdigest())
    if document["blockers"]:
        print(
            "checkpoint blockers: "
            + json.dumps(document["blockers"], ensure_ascii=False),
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
