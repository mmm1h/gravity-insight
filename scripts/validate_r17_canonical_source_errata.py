"""Validate the R17 errata and later exact canonical-source amendments."""

from __future__ import annotations

import difflib
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DIRECTIVE_PATH = ROOT / "specs/agent-runtime/directive.json"
LEDGER_PATH = ROOT / "tests/fixtures/agent_module_reference_dispositions.json"

REVIEWED_AT_REVISION = "f2e8eec1f3c0567e20ab8c0be6465cc4e2c52e59"
CANONICAL_FROM_GIT_REVISION = "24f16c667d80107e4149cf76742eab4ada564197"
CANONICAL_FROM_SHA256 = "54b5759bde4addbceab0e63853c7e228b1d6643d5d369321c92d0468fb1b6b2c"
REVIEWED_LEDGER_GIT_BLOB = "0fcfa6c85e07c7cc901530ed8c2fe7516203e986"
REVIEWED_LEDGER_SHA256 = "9d5b4d197cd84a0da4bb644256c9df7670ec89b7258e710434ab1ac8fed8be20"
POST_PROGRAM_FROM_GIT_REVISION = "6d72d26dace534ec9b56c316746578cdd76c812c"
POST_PROGRAM_FROM_SHA256 = "0ba1cd5069d397bc067d88d21dea76b196f5c33404adba7a6f2322e926abd2ec"
POST_PROGRAM_REPLACEMENTS_SHA256 = (
    "044ec663d6ae674525d56442acea97a69e1e48076548af5e7435663683312dce"
)
NAMING_FROM_GIT_REVISION = "d83c4509f253e748fd43221430a154b89c243066"
NAMING_FROM_SHA256 = "9a6725dd6b4bf52b46fae60cc17df600ab8bc0b760c00d4b5bd8526688486ffb"
NAMING_REPLACEMENTS_SHA256 = (
    "5fd7037f1e995fe01b013db4393450c3e01d1c3278940f3f71e324780319e896"
)

EXPECTED_ERRATA_KEYS = {
    "rule",
    "requirement_id",
    "authorized_by",
    "owner_review",
    "transition",
    "one_shot",
    "allowed_source_replacements",
    "allowed_version_metadata_changes",
    "requires",
    "does_not_authorize",
}
EXPECTED_DERIVATION_KEYS = {
    "derivation",
    "ledger_role",
    "ledger_repository_path",
    "ledger_git_blob",
    "ledger_sha256",
    "ledger_schema_version",
    "source_file",
    "disposition",
    "required_action_kind",
    "required_count",
    "reviewed_at_revision",
}
EXPECTED_REQUIRES = [
    "full_source_bytes_equal_v9_2_baseline_after_exact_allowlist",
    "update_version_supersedes_digest_and_self_references_atomically",
    "transition_one_shot_state_from_unconsumed_to_consumed",
]
EXPECTED_FORBIDDEN = [
    "reuse_for_any_other_requirement_or_version_transition",
    "any_source_change_outside_the_exact_allowlist",
    "architectural_semantic_changes",
    "a_claim_of_new_or_owner_approval",
    "implementation_before_the_requirement_is_ready",
    "release_or_main_promotion",
]
EXPECTED_VERSION_METADATA_CHANGES = [
    {
        "operation": "insert_before",
        "anchor": "## v9.2 修订摘要",
        "text": (
            "## v9.3 修订摘要\n\n"
            "four physical path corrections; no architectural semantic change\n\n"
        ),
        "count": 1,
    },
    {
        "old": "gravity-agent-runtime / v9.2",
        "new": "gravity-agent-runtime / v9.3",
        "count": 1,
    },
    {
        "old": "唯一架构总纲 v9.2（repository canonical source）",
        "new": "唯一架构总纲 v9.3（repository canonical source）",
        "count": 1,
    },
]
EXPECTED_AMENDMENT_KEYS = {
    "rule",
    "authorized_by",
    "authorized_at",
    "scope",
    "transition",
    "allowed_source_replacements",
    "requires",
    "does_not_authorize",
}
EXPECTED_AMENDMENT_REQUIRES = [
    "v9_3_bytes_from_git_baseline",
    "exact_source_allowlist_only",
    "directive_and_source_digest_updated_atomically",
]
EXPECTED_AMENDMENT_FORBIDDEN = [
    "rewrite_historical_requirement_evidence",
    "weaken_main_branch_protection",
    "allow_non_main_integrated_validation_green",
]
EXPECTED_NAMING_REQUIRES = [
    "v9_4_bytes_from_git_baseline",
    "exact_source_allowlist_only",
    "r17_immutable_ledger_projection_without_mutation",
    "directive_and_source_digest_updated_atomically",
]
EXPECTED_NAMING_FORBIDDEN = [
    "modify_r17_immutable_ledger",
    "create_gravity_sdk_compatibility_package",
    "rename_github_repository",
    "rename_gravity_cli",
    "change_stable_contract_identifiers_without_separate_decision",
]
EXPECTED_MAIN_INTEGRATION = {
    "status": "completed",
    "development_target": "main",
    "change_path": "short_lived_branch_pull_request_to_protected_main",
    "completed_promotion_requires": [
        "all_index_requirements_fixed_dev",
        "integrated_validation_green",
        "explicit_new_user_approval",
    ],
    "ongoing_merge_requires": [
        "required_test_status_check",
        "pull_request",
        "protected_main",
    ],
}


class ErrataValidationError(AssertionError):
    """Raised when the R17 errata declaration or final source does not bind."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ErrataValidationError(message)


def _repository_path(value: Any, *, field: str) -> str:
    _require(isinstance(value, str) and bool(value), f"{field} must be a path")
    path = PurePosixPath(value)
    _require(
        not path.is_absolute() and ".." not in path.parts,
        f"{field} must be repository-relative: {value!r}",
    )
    return path.as_posix()


def load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(document, dict), f"JSON document must be an object: {path}")
    return document


def _canonical_json_sha256(value: Any) -> str:
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _post_program_amendment(directive: dict[str, Any]) -> dict[str, Any]:
    amendment = directive.get("canonical_source_amendment")
    _require(isinstance(amendment, dict), "canonical_source_amendment must be an object")
    _require(
        set(amendment) == EXPECTED_AMENDMENT_KEYS,
        "canonical source amendment has missing or additional authority fields",
    )
    _require(
        amendment.get("rule") == "post_program_v9_3_to_v9_4_exact_allowlist",
        "canonical source amendment rule changed",
    )
    _require(amendment.get("authorized_by") == "user", "amendment authority changed")
    _require(
        amendment.get("authorized_at") == "2026-08-30",
        "amendment authorization date changed",
    )
    _require(
        amendment.get("scope")
        == "completed_program_trunk_on_main_governance_migration",
        "amendment scope changed",
    )
    transition = amendment.get("transition")
    _require(
        transition
        == {
            "from_version": "v9.3",
            "from_sha256": POST_PROGRAM_FROM_SHA256,
            "from_git_revision": POST_PROGRAM_FROM_GIT_REVISION,
            "to_version": "v9.4",
        },
        "post-program transition must remain the reviewed v9.3 to v9.4 baseline",
    )
    replacements = amendment.get("allowed_source_replacements")
    _require(
        isinstance(replacements, list)
        and len(replacements) == 15
        and _canonical_json_sha256(replacements)
        == POST_PROGRAM_REPLACEMENTS_SHA256,
        "post-program source allowlist changed from the exact reviewed operations",
    )
    _require(
        amendment.get("requires") == EXPECTED_AMENDMENT_REQUIRES,
        "post-program amendment requirements changed",
    )
    _require(
        amendment.get("does_not_authorize") == EXPECTED_AMENDMENT_FORBIDDEN,
        "post-program amendment forbidden-action list changed",
    )
    return amendment


def _naming_amendment(directive: dict[str, Any]) -> dict[str, Any]:
    amendment = directive.get("canonical_source_naming_amendment")
    _require(
        isinstance(amendment, dict),
        "canonical_source_naming_amendment must be an object",
    )
    _require(
        set(amendment) == EXPECTED_AMENDMENT_KEYS,
        "canonical source naming amendment has missing or additional authority fields",
    )
    _require(
        amendment.get("rule") == "package_root_v9_4_to_v9_5_exact_allowlist",
        "canonical source naming amendment rule changed",
    )
    _require(
        amendment.get("authorized_by") == "user",
        "naming amendment authority changed",
    )
    _require(
        amendment.get("authorized_at") == "2026-08-30",
        "naming amendment authorization date changed",
    )
    _require(
        amendment.get("scope")
        == "repository_distribution_and_python_import_identity_unification",
        "naming amendment scope changed",
    )
    _require(
        amendment.get("transition")
        == {
            "from_version": "v9.4",
            "from_sha256": NAMING_FROM_SHA256,
            "from_git_revision": NAMING_FROM_GIT_REVISION,
            "to_version": "v9.5",
        },
        "naming transition must remain the reviewed v9.4 to v9.5 baseline",
    )
    replacements = amendment.get("allowed_source_replacements")
    _require(
        isinstance(replacements, list)
        and len(replacements) == 17
        and _canonical_json_sha256(replacements) == NAMING_REPLACEMENTS_SHA256,
        "naming source allowlist changed from the exact user-authorized operations",
    )
    _require(
        amendment.get("requires") == EXPECTED_NAMING_REQUIRES,
        "naming amendment requirements changed",
    )
    _require(
        amendment.get("does_not_authorize") == EXPECTED_NAMING_FORBIDDEN,
        "naming amendment forbidden-action list changed",
    )
    return amendment


def _errata(directive: dict[str, Any]) -> dict[str, Any]:
    errata = directive.get("canonical_source_errata")
    _require(isinstance(errata, dict), "canonical_source_errata must be an object")
    _require(
        set(errata) == EXPECTED_ERRATA_KEYS,
        "errata object has missing or additional authority fields",
    )
    _require(
        errata.get("rule") == "r17_v9_2_to_v9_3_one_shot_allowlist",
        "errata rule changed",
    )
    _require(errata.get("requirement_id") == "R17", "errata requirement changed")
    _require(
        errata.get("authorized_by") == "agent_under_standing_owner_delegation",
        "errata authorization provenance changed",
    )
    _require(
        errata.get("owner_review") == "pending",
        "errata owner review must remain pending",
    )
    _require(errata.get("requires") == EXPECTED_REQUIRES, "errata requirements changed")
    _require(
        errata.get("does_not_authorize") == EXPECTED_FORBIDDEN,
        "errata forbidden-action list changed",
    )
    return errata


def _canonical_source_file(directive: dict[str, Any]) -> str:
    canonical = directive.get("canonical_source")
    _require(isinstance(canonical, dict), "canonical_source must be an object")
    relative = _repository_path(
        canonical.get("repository_path"),
        field="canonical_source.repository_path",
    )
    directive_relative = DIRECTIVE_PATH.relative_to(ROOT).parent
    return (directive_relative / PurePosixPath(relative)).as_posix()


def source_replacement_derivation(
    directive: dict[str, Any],
) -> dict[str, Any]:
    errata = _errata(directive)
    derivation = errata.get("allowed_source_replacements")
    _require(
        isinstance(derivation, dict),
        "allowed_source_replacements must be a ledger derivation",
    )
    _require(
        set(derivation) == EXPECTED_DERIVATION_KEYS,
        "source-replacement derivation has missing or additional fields",
    )
    _require(
        derivation.get("derivation")
        == "ledger_rewrite_actions_at_exact_source_coordinates",
        "source replacements are not coordinate-derived from the ledger",
    )
    _require(
        derivation.get("ledger_schema_version")
        == "gravity.agent-module-reference-dispositions.v2",
        "source-replacement ledger schema changed",
    )
    _require(
        derivation.get("ledger_role") == "r17_checked_in_governance_evidence",
        "source replacements must use the R17 checked-in governance evidence",
    )
    ledger_path = _repository_path(
        derivation.get("ledger_repository_path"),
        field="ledger_repository_path",
    )
    _require(
        ledger_path == LEDGER_PATH.relative_to(ROOT).as_posix(),
        "errata derivation must bind the R17 disposition ledger path",
    )
    ledger_blob = derivation.get("ledger_git_blob")
    _require(
        isinstance(ledger_blob, str)
        and re.fullmatch(r"[0-9a-f]{40}", ledger_blob) is not None,
        "errata ledger blob must be a full Git object ID",
    )
    _require(
        ledger_blob == REVIEWED_LEDGER_GIT_BLOB,
        "errata ledger blob changed from the reviewed object",
    )
    ledger_sha256 = derivation.get("ledger_sha256")
    _require(
        isinstance(ledger_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", ledger_sha256) is not None,
        "errata ledger SHA-256 must be a lowercase digest",
    )
    _require(
        ledger_sha256 == REVIEWED_LEDGER_SHA256,
        "errata ledger SHA-256 changed from the reviewed bytes",
    )
    reviewed_at_revision = derivation.get("reviewed_at_revision")
    _require(
        reviewed_at_revision == REVIEWED_AT_REVISION,
        "errata ledger review revision changed from the fifth-review input",
    )
    source_file = _repository_path(
        derivation.get("source_file"), field="source_file"
    )
    _require(
        source_file == _canonical_source_file(directive),
        "errata derivation does not target the canonical source",
    )
    _require(
        derivation.get("disposition") == "rewrite_reference",
        "errata derivation must select rewrite_reference rows",
    )
    _require(
        derivation.get("required_action_kind") == "replace_text",
        "errata derivation must require replace_text actions",
    )
    _require(
        derivation.get("required_count") == 4,
        "R17 canonical-source errata must derive exactly four replacements",
    )
    return derivation


def _git_blob_bytes(blob: str) -> bytes:
    completed = subprocess.run(
        ["git", "cat-file", "blob", blob],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def _tree_blob_at_revision(revision: str, repository_path: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", f"{revision}:{repository_path}"],
        cwd=ROOT,
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout.strip()


def _git_file_bytes(revision: str, repository_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{revision}:{repository_path}"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def _current_tree_blob(repository_path: str) -> str:
    return _tree_blob_at_revision("HEAD", repository_path)


def _render_ledger(ledger: dict[str, Any]) -> bytes:
    return (json.dumps(ledger, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def validate_bound_ledger(
    directive: dict[str, Any],
    ledger: dict[str, Any],
    *,
    ledger_bytes: bytes | None = None,
) -> bytes:
    """Require the exact ledger object named by the directive's immutable binding."""

    derivation = source_replacement_derivation(directive)
    ledger_blob = derivation["ledger_git_blob"]
    repository_path = derivation["ledger_repository_path"]
    _require(
        _tree_blob_at_revision(derivation["reviewed_at_revision"], repository_path)
        == ledger_blob,
        "errata ledger blob is not the object at the fixed review revision path",
    )
    _require(
        _current_tree_blob(repository_path) == ledger_blob,
        "current commit changed the reviewed errata ledger bytes",
    )
    bound = _git_blob_bytes(ledger_blob)
    expected_sha = derivation["ledger_sha256"]
    _require(
        hashlib.sha256(bound).hexdigest() == expected_sha,
        "Git-bound ledger SHA-256 differs from the errata declaration",
    )
    supplied = _render_ledger(ledger) if ledger_bytes is None else ledger_bytes
    _require(
        hashlib.sha256(supplied).hexdigest() == expected_sha and supplied == bound,
        "supplied ledger bytes differ from the directive-bound ledger object",
    )
    _require(
        _render_ledger(ledger) == bound,
        "parsed ledger semantics differ from the directive-bound ledger object",
    )
    return bound


def _ledger_move_mapping(ledger: dict[str, Any]) -> dict[str, str]:
    scope = ledger.get("scope")
    _require(isinstance(scope, dict), "bound ledger scope must be an object")
    moves = scope.get("one_to_one_moves")
    _require(
        isinstance(moves, list) and len(moves) == 82,
        "bound ledger scope must contain exactly 82 one-to-one moves",
    )
    mapping: dict[str, str] = {}
    targets: set[str] = set()
    for move in moves:
        _require(isinstance(move, dict), "bound ledger move must be an object")
        old = move.get("old_module")
        new = move.get("new_module")
        old_parts = old.split(".") if isinstance(old, str) else []
        old_name = old_parts[1] if len(old_parts) == 2 else ""
        if old_name.startswith("agent_"):
            responsibility = old_name.removeprefix("agent_")
        elif old_name.endswith("_agent"):
            responsibility = old_name.removesuffix("_agent")
        else:
            responsibility = ""
        _require(
            isinstance(old, str)
            and old_parts[0] == "gravity_sdk"
            and bool(responsibility)
            and new == f"gravity_sdk.agents.{responsibility}",
            f"bound ledger contains an illegal move: {old!r} -> {new!r}",
        )
        _require(old not in mapping and new not in targets, "bound ledger moves repeat")
        mapping[old] = new
        targets.add(new)
    consolidation = scope.get("consolidate_delete")
    _require(
        isinstance(consolidation, dict)
        and consolidation.get("old_module", "").rsplit(".", 1)[-1]
        == "agent" + "_pagination"
        and consolidation.get("new_module")
        == "gravity_sdk.pagination_completeness"
        and consolidation.get("symbol") == "compact_pagination",
        "bound ledger pagination consolidation changed",
    )
    retained = scope.get("retained_modules")
    _require(
        isinstance(retained, list)
        and len(retained) == 1
        and retained[0].rsplit(".", 1)[-1]
        == "agent" + "_runtime_contracts",
        "bound ledger retained owner changed",
    )
    return mapping


def canonical_source_path(directive: dict[str, Any]) -> Path:
    return ROOT / _canonical_source_file(directive)


def derive_source_replacements(
    directive: dict[str, Any], ledger: dict[str, Any]
) -> tuple[dict[str, Any], ...]:
    """Select every canonical-source rewrite and bind its exact coordinates."""

    derivation = source_replacement_derivation(directive)
    validate_bound_ledger(directive, ledger)
    move_mapping = _ledger_move_mapping(ledger)
    _require(
        ledger.get("schema_version") == derivation["ledger_schema_version"],
        "ledger schema differs from the errata derivation",
    )
    sites = ledger.get("sites")
    _require(isinstance(sites, list), "ledger sites must be a list")
    selected = [
        site
        for site in sites
        if isinstance(site, dict)
        and site.get("disposition") == derivation["disposition"]
        and isinstance(site.get("source"), dict)
        and site["source"].get("file") == derivation["source_file"]
    ]
    _require(
        len(selected) == derivation["required_count"],
        "canonical-source ledger selection must contain exactly "
        f"{derivation['required_count']} rows; found {len(selected)}",
    )

    replacements: list[dict[str, Any]] = []
    source_keys: set[str] = set()
    coordinates: set[tuple[int, int]] = set()
    for site in selected:
        source = site["source"]
        line = source.get("line")
        column = source.get("column")
        _require(
            isinstance(line, int) and line > 0 and isinstance(column, int) and column > 0,
            "ledger replacement has invalid source coordinates",
        )
        expected_key = (
            f"{source.get('file')}:{line}:{column}:{source.get('form')}"
        )
        source_key = site.get("source_key")
        _require(source_key == expected_key, "ledger replacement source key drifted")
        _require(source_key not in source_keys, "duplicate ledger replacement source key")
        coordinate = (line, column)
        _require(coordinate not in coordinates, "duplicate ledger replacement coordinate")
        source_keys.add(source_key)
        coordinates.add(coordinate)

        action = site.get("migration_action")
        _require(isinstance(action, dict), f"missing migration action at {source_key}")
        _require(
            set(action)
            == {"kind", "old_text", "new_text", "old_module", "new_module"},
            f"unexpected migration action shape at {source_key}",
        )
        _require(
            action.get("kind") == derivation["required_action_kind"],
            f"unexpected migration action kind at {source_key}",
        )
        old_text = action.get("old_text")
        new_text = action.get("new_text")
        old_module = action.get("old_module")
        new_module = action.get("new_module")
        _require(
            isinstance(old_text, str)
            and bool(old_text)
            and isinstance(new_text, str)
            and bool(new_text),
            f"empty source replacement at {source_key}",
        )
        _require(old_text != new_text, f"self-loop source replacement at {source_key}")
        _require(
            isinstance(old_module, str)
            and bool(old_module)
            and isinstance(new_module, str)
            and bool(new_module)
            and old_module != new_module,
            f"invalid module move at {source_key}",
        )
        _require(
            move_mapping.get(old_module) == new_module,
            f"module move is outside the bound R17 mapping at {source_key}",
        )
        old_short = old_module.removeprefix("gravity_sdk.")
        new_short = new_module.removeprefix("gravity_sdk.")
        if old_text.endswith(".py"):
            expected_old_text = (
                f"src/gravity_sdk/{old_short}.py"
                if old_text.startswith("src/gravity_sdk/")
                else f"{old_short}.py"
            )
            expected_new_text = (
                "src/" + new_module.replace(".", "/") + ".py"
                if old_text.startswith("src/gravity_sdk/")
                else new_short.replace(".", "/") + ".py"
            )
        else:
            expected_old_text = old_short
            expected_new_text = new_short
        _require(
            old_text == expected_old_text and new_text == expected_new_text,
            f"replacement text does not match the module move at {source_key}",
        )
        old_value = source.get("old_value")
        _require(
            isinstance(old_value, str) and old_text.startswith(old_value),
            f"replacement text does not bind the audited value at {source_key}",
        )
        replacements.append(
            {
                "source_key": source_key,
                "line": line,
                "column": column,
                "old_text": old_text,
                "new_text": new_text,
            }
        )
    return tuple(
        sorted(replacements, key=lambda row: (row["line"], row["column"]))
    )


def apply_coordinate_replacements(
    source: str, replacements: tuple[dict[str, Any], ...]
) -> str:
    lines = source.splitlines(keepends=True)
    starts: list[int] = []
    cursor = 0
    for line in lines:
        starts.append(cursor)
        cursor += len(line)

    edits: list[tuple[int, int, str, str]] = []
    for replacement in replacements:
        line = replacement["line"]
        column = replacement["column"]
        _require(line <= len(lines), f"replacement line is outside source: {replacement}")
        offset = starts[line - 1] + column - 1
        old_text = replacement["old_text"]
        actual = source[offset:offset + len(old_text)]
        _require(
            actual == old_text,
            "Git-bound source differs at ledger coordinate "
            f"{replacement['source_key']}: expected {old_text!r}, found {actual!r}",
        )
        edits.append(
            (
                offset,
                offset + len(old_text),
                replacement["new_text"],
                replacement["source_key"],
            )
        )

    ordered = sorted(edits)
    for previous, current in zip(ordered, ordered[1:]):
        _require(
            previous[1] <= current[0],
            f"overlapping ledger replacements: {previous[3]} and {current[3]}",
        )
    expected = source
    for start, end, new_text, _ in reversed(ordered):
        expected = expected[:start] + new_text + expected[end:]
    return expected


def _apply_exact_text_changes(source: str, changes: Any) -> str:
    expected = source
    for index, change in enumerate(changes):
        _require(isinstance(change, dict), f"metadata change {index} must be an object")
        count = change.get("count")
        _require(isinstance(count, int) and count > 0, f"invalid metadata count at {index}")
        if change.get("operation") == "insert_before":
            _require(
                set(change) == {"operation", "anchor", "text", "count"},
                f"invalid insert metadata shape at {index}",
            )
            anchor = change.get("anchor")
            text = change.get("text")
            _require(
                isinstance(anchor, str)
                and bool(anchor)
                and isinstance(text, str)
                and bool(text),
                f"invalid insert metadata at {index}",
            )
            _require(
                expected.count(anchor) == count,
                f"metadata anchor cardinality mismatch at {index}",
            )
            expected = expected.replace(anchor, text + anchor, count)
            continue
        _require(
            set(change) == {"old", "new", "count"},
            f"invalid replace metadata shape at {index}",
        )
        old = change.get("old")
        new = change.get("new")
        _require(
            isinstance(old, str)
            and bool(old)
            and isinstance(new, str)
            and bool(new)
            and old != new,
            f"invalid or self-loop metadata replacement at {index}",
        )
        _require(
            expected.count(old) == count,
            f"metadata replacement cardinality mismatch at {index}",
        )
        expected = expected.replace(old, new, count)
    return expected


def apply_version_metadata_changes(source: str, changes: Any) -> str:
    _require(
        changes == EXPECTED_VERSION_METADATA_CHANGES,
        "R17 version metadata allowlist changed from the exact three literals",
    )
    return _apply_exact_text_changes(source, changes)


def load_git_baseline(directive: dict[str, Any]) -> bytes:
    errata = _errata(directive)
    transition = errata.get("transition")
    _require(isinstance(transition, dict), "errata transition must be an object")
    revision = transition.get("from_git_revision")
    _require(
        revision == CANONICAL_FROM_GIT_REVISION,
        "errata canonical from_git_revision changed from the reviewed v9.2 source",
    )
    source_file = _canonical_source_file(directive)
    return _git_file_bytes(revision, source_file)


def build_expected_source(
    directive: dict[str, Any], ledger: dict[str, Any], baseline_bytes: bytes
) -> bytes:
    errata = _errata(directive)
    transition = errata.get("transition")
    _require(
        isinstance(transition, dict)
        and set(transition)
        == {"from_version", "from_sha256", "from_git_revision", "to_version"},
        "errata transition shape changed",
    )
    _require(
        transition.get("from_version") == "v9.2"
        and transition.get("to_version") == "v9.3",
        "errata transition must remain v9.2 to v9.3",
    )
    _require(
        transition.get("from_git_revision") == CANONICAL_FROM_GIT_REVISION,
        "errata canonical from_git_revision changed from the reviewed v9.2 source",
    )
    _require(
        transition.get("from_sha256") == CANONICAL_FROM_SHA256,
        "errata canonical from_sha256 changed from the reviewed v9.2 bytes",
    )
    baseline_sha = hashlib.sha256(baseline_bytes).hexdigest()
    _require(
        baseline_sha == transition.get("from_sha256"),
        "Git-bound v9.2 source SHA differs from the errata transition",
    )
    baseline = baseline_bytes.decode("utf-8")
    replacements = derive_source_replacements(directive, ledger)
    expected = apply_coordinate_replacements(baseline, replacements)
    expected = apply_version_metadata_changes(
        expected, errata.get("allowed_version_metadata_changes")
    )
    return expected.encode("utf-8")


def _reviewed_phase1_directive_bytes() -> bytes:
    relative = DIRECTIVE_PATH.relative_to(ROOT).as_posix()
    reviewed = _git_file_bytes(REVIEWED_AT_REVISION, relative)
    needle = b'      "required_count": 4\n'
    replacement = (
        b'      "required_count": 4,\n'
        b'      "reviewed_at_revision": "'
        + REVIEWED_AT_REVISION.encode("ascii")
        + b'"\n'
    )
    _require(
        reviewed.count(needle) == 1,
        "reviewed directive cannot derive the Phase 1 anchor field exactly once",
    )
    return reviewed.replace(needle, replacement, 1)


def _reviewed_phase1_directive() -> dict[str, Any]:
    directive = json.loads(_reviewed_phase1_directive_bytes())
    _require(isinstance(directive, dict), "reviewed directive must be an object")
    return directive


def _json_field_path(parent: str, field: Any) -> str:
    if isinstance(field, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", field):
        return f"{parent}.{field}" if parent else field
    rendered = json.dumps(field, ensure_ascii=False, sort_keys=True)
    return f"{parent}[{rendered}]" if parent else f"[{rendered}]"


def _directive_mismatch_paths(
    actual: Any, expected: Any, *, path: str = ""
) -> list[str]:
    if type(actual) is not type(expected):
        return [path or "$directive"]
    if isinstance(expected, dict):
        mismatches: list[str] = []
        fields = sorted(set(actual) | set(expected), key=str)
        for field in fields:
            field_path = _json_field_path(path, field)
            if field not in actual or field not in expected:
                mismatches.append(field_path)
                continue
            mismatches.extend(
                _directive_mismatch_paths(
                    actual[field], expected[field], path=field_path
                )
            )
        return mismatches
    if isinstance(expected, list):
        mismatches = []
        for index in range(max(len(actual), len(expected))):
            item_path = f"{path}[{index}]"
            if index >= len(actual) or index >= len(expected):
                mismatches.append(item_path)
                continue
            mismatches.extend(
                _directive_mismatch_paths(
                    actual[index], expected[index], path=item_path
                )
            )
        return mismatches
    return [] if actual == expected else [path or "$directive"]


def _expected_final_directive(expected_source_sha256: str) -> dict[str, Any]:
    expected = _reviewed_phase1_directive()
    errata = expected["canonical_source_errata"]
    transition = errata["transition"]
    expected["version"] = transition["to_version"]
    expected["supersedes"] = {
        "version": transition["from_version"],
        "sha256": transition["from_sha256"],
    }
    expected["canonical_source"]["sha256"] = expected_source_sha256
    one_shot = errata["one_shot"]
    one_shot["state"] = "consumed"
    one_shot["consumed_by"] = "R17"
    one_shot["consumed_at_checkpoint"] = "R17-phase-2-core"
    return expected


def validate_phase1_reviewed_state(
    directive: dict[str, Any],
    directive_bytes: bytes,
    source_bytes: bytes,
) -> dict[str, Any]:
    """Reject any canonical or errata-authority change at the Phase 1 checkpoint."""

    source_replacement_derivation(directive)
    transition = _errata(directive).get("transition", {})
    _require(
        transition.get("from_git_revision") == CANONICAL_FROM_GIT_REVISION
        and transition.get("from_sha256") == CANONICAL_FROM_SHA256,
        "Phase 1 changed the canonical transition baseline",
    )
    expected_directive = _reviewed_phase1_directive_bytes()
    _require(
        directive_bytes == expected_directive,
        "Phase 1 canonical directive differs from the reviewed baseline",
    )
    source_file = _canonical_source_file(directive)
    reviewed_source = _git_file_bytes(REVIEWED_AT_REVISION, source_file)
    _require(
        source_bytes == reviewed_source,
        "Phase 1 canonical source differs from the reviewed baseline",
    )
    _require(
        hashlib.sha256(source_bytes).hexdigest() == CANONICAL_FROM_SHA256,
        "Phase 1 canonical source digest differs from the reviewed v9.2 bytes",
    )
    return {
        "checkpoint": "phase-1",
        "canonical_source": "reviewed-bytes-unchanged",
        "canonical_directive": "reviewed-bytes-unchanged",
        "reviewed_at_revision": REVIEWED_AT_REVISION,
    }


def validate_final_state(
    directive: dict[str, Any],
    ledger: dict[str, Any],
    source_bytes: bytes,
    baseline_bytes: bytes,
) -> dict[str, Any]:
    reviewed_directive = _reviewed_phase1_directive()
    expected = build_expected_source(reviewed_directive, ledger, baseline_bytes)
    expected_sha = hashlib.sha256(expected).hexdigest()
    expected_directive = _expected_final_directive(expected_sha)
    mismatch_paths = _directive_mismatch_paths(directive, expected_directive)
    if mismatch_paths:
        message = (
            "terminal directive differs from the reviewed Phase 1 baseline at "
            "field path(s): " + ", ".join(mismatch_paths)
        )
        if any(
            path.startswith("canonical_source_errata.one_shot")
            for path in mismatch_paths
        ):
            message += (
                "; errata is not consumed exactly once by R17 at the core checkpoint"
            )
        if any(
            path.startswith("canonical_source_errata.transition")
            for path in mismatch_paths
        ):
            message += "; errata transition must remain v9.2 to v9.3"
        raise ErrataValidationError(message)

    errata = expected_directive["canonical_source_errata"]
    transition = errata["transition"]
    if source_bytes != expected:
        expected_text = expected.decode("utf-8")
        source_text = source_bytes.decode("utf-8")
        delta = "".join(
            difflib.unified_diff(
                expected_text.splitlines(True),
                source_text.splitlines(True),
                fromfile="ledger-derived-v9.3",
                tofile="actual-v9.3",
                n=2,
            )
        )
        raise ErrataValidationError(
            "canonical v9.2 to v9.3 diff exceeds the ledger-derived errata:\n"
            + delta[:8000]
        )

    actual_sha = hashlib.sha256(source_bytes).hexdigest()
    _require(actual_sha == expected_sha, "canonical source SHA mismatch")
    replacements = derive_source_replacements(reviewed_directive, ledger)
    return {
        "transition": f"{transition['from_version']}->{transition['to_version']}",
        "source_replacements": len(replacements),
        "metadata_changes": len(errata["allowed_version_metadata_changes"]),
        "one_shot": "consumed",
        "sha256": actual_sha,
    }


def load_post_program_baseline_directive() -> dict[str, Any]:
    relative = DIRECTIVE_PATH.relative_to(ROOT).as_posix()
    baseline = json.loads(
        _git_file_bytes(POST_PROGRAM_FROM_GIT_REVISION, relative).decode("utf-8")
    )
    _require(isinstance(baseline, dict), "v9.3 baseline directive must be an object")
    expected = _expected_final_directive(POST_PROGRAM_FROM_SHA256)
    mismatch_paths = _directive_mismatch_paths(baseline, expected)
    _require(
        not mismatch_paths,
        "post-program directive baseline is not the terminal R17 v9.3 state at: "
        + ", ".join(mismatch_paths),
    )
    return baseline


def build_post_program_source(directive: dict[str, Any]) -> bytes:
    amendment = _post_program_amendment(directive)
    source_file = _canonical_source_file(directive)
    baseline = _git_file_bytes(POST_PROGRAM_FROM_GIT_REVISION, source_file)
    _require(
        hashlib.sha256(baseline).hexdigest() == POST_PROGRAM_FROM_SHA256,
        "Git-bound v9.3 source SHA differs from the post-program transition",
    )
    expected = _apply_exact_text_changes(
        baseline.decode("utf-8"), amendment["allowed_source_replacements"]
    )
    return expected.encode("utf-8")


def _expected_post_program_directive(
    directive: dict[str, Any], expected_source_sha256: str
) -> dict[str, Any]:
    amendment = _post_program_amendment(directive)
    expected = copy.deepcopy(load_post_program_baseline_directive())
    transition = amendment["transition"]
    expected["version"] = transition["to_version"]
    expected["supersedes"] = {
        "version": transition["from_version"],
        "sha256": transition["from_sha256"],
    }
    expected["canonical_source"]["sha256"] = expected_source_sha256
    expected["canonical_source_amendment"] = copy.deepcopy(amendment)
    expected["review_baseline"] = {
        "branch": "main",
        "sha": POST_PROGRAM_FROM_GIT_REVISION,
    }
    expected["main_integration"] = copy.deepcopy(EXPECTED_MAIN_INTEGRATION)
    return expected


def validate_post_program_state(
    directive: dict[str, Any], ledger: dict[str, Any], source_bytes: bytes
) -> dict[str, Any]:
    """Prove R17 before applying the exact v9.3 to v9.4 owner amendment."""

    baseline_directive = load_post_program_baseline_directive()
    source_file = _canonical_source_file(baseline_directive)
    v93_source = _git_file_bytes(POST_PROGRAM_FROM_GIT_REVISION, source_file)
    r17_baseline = load_git_baseline(baseline_directive)
    prior = validate_final_state(
        baseline_directive,
        ledger,
        v93_source,
        r17_baseline,
    )
    expected_source = build_post_program_source(directive)
    expected_sha = hashlib.sha256(expected_source).hexdigest()
    expected_directive = _expected_post_program_directive(directive, expected_sha)
    mismatch_paths = _directive_mismatch_paths(directive, expected_directive)
    _require(
        not mismatch_paths,
        "current directive exceeds the post-program amendment at field path(s): "
        + ", ".join(mismatch_paths),
    )
    if source_bytes != expected_source:
        delta = "".join(
            difflib.unified_diff(
                expected_source.decode("utf-8").splitlines(True),
                source_bytes.decode("utf-8").splitlines(True),
                fromfile="allowlist-derived-v9.4",
                tofile="actual-v9.4",
                n=2,
            )
        )
        raise ErrataValidationError(
            "canonical v9.3 to v9.4 diff exceeds the exact amendment:\n"
            + delta[:8000]
        )
    actual_sha = hashlib.sha256(source_bytes).hexdigest()
    _require(actual_sha == expected_sha, "current canonical source SHA mismatch")
    return {
        "transition": "v9.3->v9.4",
        "prior_transition": prior["transition"],
        "source_replacements": len(
            directive["canonical_source_amendment"]["allowed_source_replacements"]
        ),
        "sha256": actual_sha,
    }


def load_naming_baseline_directive() -> dict[str, Any]:
    relative = DIRECTIVE_PATH.relative_to(ROOT).as_posix()
    baseline = json.loads(
        _git_file_bytes(NAMING_FROM_GIT_REVISION, relative).decode("utf-8")
    )
    _require(isinstance(baseline, dict), "v9.4 baseline directive must be an object")
    expected = _expected_post_program_directive(baseline, NAMING_FROM_SHA256)
    mismatch_paths = _directive_mismatch_paths(baseline, expected)
    _require(
        not mismatch_paths,
        "naming directive baseline is not the terminal v9.4 state at: "
        + ", ".join(mismatch_paths),
    )
    return baseline


def build_naming_source(directive: dict[str, Any]) -> bytes:
    amendment = _naming_amendment(directive)
    source_file = _canonical_source_file(directive)
    baseline = _git_file_bytes(NAMING_FROM_GIT_REVISION, source_file)
    _require(
        hashlib.sha256(baseline).hexdigest() == NAMING_FROM_SHA256,
        "Git-bound v9.4 source SHA differs from the naming transition",
    )
    expected = _apply_exact_text_changes(
        baseline.decode("utf-8"), amendment["allowed_source_replacements"]
    )
    return expected.encode("utf-8")


def _expected_naming_directive(
    directive: dict[str, Any], expected_source_sha256: str
) -> dict[str, Any]:
    amendment = _naming_amendment(directive)
    expected = copy.deepcopy(load_naming_baseline_directive())
    transition = amendment["transition"]
    expected["version"] = transition["to_version"]
    expected["supersedes"] = {
        "version": transition["from_version"],
        "sha256": transition["from_sha256"],
    }
    expected["canonical_source"]["sha256"] = expected_source_sha256
    expected["canonical_source_naming_amendment"] = copy.deepcopy(amendment)
    expected["review_baseline"] = {
        "branch": "main",
        "sha": NAMING_FROM_GIT_REVISION,
    }
    return expected


def validate_current_state(
    directive: dict[str, Any], ledger: dict[str, Any], source_bytes: bytes
) -> dict[str, Any]:
    """Prove the full immutable-R17, v9.4, and v9.5 amendment chain."""

    baseline_directive = load_naming_baseline_directive()
    source_file = _canonical_source_file(baseline_directive)
    v94_source = _git_file_bytes(NAMING_FROM_GIT_REVISION, source_file)
    prior = validate_post_program_state(baseline_directive, ledger, v94_source)
    expected_source = build_naming_source(directive)
    expected_sha = hashlib.sha256(expected_source).hexdigest()
    expected_directive = _expected_naming_directive(directive, expected_sha)
    mismatch_paths = _directive_mismatch_paths(directive, expected_directive)
    _require(
        not mismatch_paths,
        "current directive exceeds the naming amendment at field path(s): "
        + ", ".join(mismatch_paths),
    )
    if source_bytes != expected_source:
        delta = "".join(
            difflib.unified_diff(
                expected_source.decode("utf-8").splitlines(True),
                source_bytes.decode("utf-8").splitlines(True),
                fromfile="allowlist-derived-v9.5",
                tofile="actual-v9.5",
                n=2,
            )
        )
        raise ErrataValidationError(
            "canonical v9.4 to v9.5 diff exceeds the exact naming amendment:\n"
            + delta[:8000]
        )
    actual_sha = hashlib.sha256(source_bytes).hexdigest()
    _require(actual_sha == expected_sha, "current canonical source SHA mismatch")
    return {
        "transition": "v9.4->v9.5",
        "prior_transition": prior["transition"],
        "r17_transition": prior["prior_transition"],
        "source_replacements": len(
            directive["canonical_source_naming_amendment"][
                "allowed_source_replacements"
            ]
        ),
        "sha256": actual_sha,
    }


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        directive = load_json(DIRECTIVE_PATH)
        ledger = load_json(LEDGER_PATH)
        if arguments == ["--phase-1"]:
            validate_bound_ledger(
                directive,
                ledger,
                ledger_bytes=LEDGER_PATH.read_bytes(),
            )
            source_bytes = canonical_source_path(directive).read_bytes()
            result = validate_phase1_reviewed_state(
                directive,
                DIRECTIVE_PATH.read_bytes(),
                source_bytes,
            )
        else:
            _require(not arguments, f"unknown arguments: {arguments}")
            reviewed_directive = _reviewed_phase1_directive()
            validate_bound_ledger(
                reviewed_directive,
                ledger,
                ledger_bytes=LEDGER_PATH.read_bytes(),
            )
            source_bytes = canonical_source_path(directive).read_bytes()
            result = validate_current_state(directive, ledger, source_bytes)
    except (
        ErrataValidationError,
        json.JSONDecodeError,
        OSError,
        subprocess.CalledProcessError,
    ) as exc:
        print(f"R17 canonical source errata validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
