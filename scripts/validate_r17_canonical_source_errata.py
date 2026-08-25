"""Validate the one-shot R17 canonical-source errata from its disposition ledger."""

from __future__ import annotations

import difflib
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
    "ledger_git_revision",
    "ledger_sha256",
    "ledger_schema_version",
    "source_file",
    "disposition",
    "required_action_kind",
    "required_count",
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
    ledger_revision = derivation.get("ledger_git_revision")
    _require(
        isinstance(ledger_revision, str)
        and re.fullmatch(r"[0-9a-f]{40}", ledger_revision) is not None,
        "errata ledger revision must be a full Git SHA",
    )
    ledger_sha256 = derivation.get("ledger_sha256")
    _require(
        isinstance(ledger_sha256, str)
        and re.fullmatch(r"[0-9a-f]{64}", ledger_sha256) is not None,
        "errata ledger SHA-256 must be a lowercase digest",
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


def _git_object_bytes(revision: str, repository_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{revision}:{repository_path}"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


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
    bound = _git_object_bytes(
        derivation["ledger_git_revision"], derivation["ledger_repository_path"]
    )
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
        isinstance(moves, list) and len(moves) == 81,
        "bound ledger scope must contain exactly 81 one-to-one moves",
    )
    mapping: dict[str, str] = {}
    targets: set[str] = set()
    for move in moves:
        _require(isinstance(move, dict), "bound ledger move must be an object")
        old = move.get("old_module")
        new = move.get("new_module")
        old_parts = old.split(".") if isinstance(old, str) else []
        old_name = old_parts[1] if len(old_parts) == 2 else ""
        _require(
            isinstance(old, str)
            and old_parts[0] == "gravity_sdk"
            and old_name.startswith("agent" + "_")
            and new
            == f"gravity_sdk.agents.{old_name.removeprefix('agent' + '_')}",
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


def apply_version_metadata_changes(source: str, changes: Any) -> str:
    _require(
        isinstance(changes, list) and len(changes) == 3,
        "R17 must retain exactly three inline version metadata changes",
    )
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


def load_git_baseline(directive: dict[str, Any]) -> bytes:
    errata = _errata(directive)
    transition = errata.get("transition")
    _require(isinstance(transition, dict), "errata transition must be an object")
    revision = transition.get("from_git_revision")
    _require(
        isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision) is not None,
        "errata baseline revision must be a full Git SHA",
    )
    source_file = _canonical_source_file(directive)
    completed = subprocess.run(
        ["git", "show", f"{revision}:{source_file}"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


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


def validate_final_state(
    directive: dict[str, Any],
    ledger: dict[str, Any],
    source_bytes: bytes,
    baseline_bytes: bytes,
) -> dict[str, Any]:
    errata = _errata(directive)
    transition = errata["transition"]
    expected_one_shot = {
        "state": "consumed",
        "reusable": False,
        "consumed_by": "R17",
        "consumed_at_checkpoint": "R17-phase-2-core",
    }
    _require(
        errata.get("one_shot") == expected_one_shot,
        "errata is not consumed exactly once by R17 at the core checkpoint",
    )
    expected = build_expected_source(directive, ledger, baseline_bytes)
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
    canonical = directive.get("canonical_source", {})
    _require(actual_sha == canonical.get("sha256"), "canonical source SHA mismatch")
    _require(
        directive.get("version") == transition["to_version"],
        "directive version does not match the errata target",
    )
    _require(
        directive.get("supersedes")
        == {
            "version": transition["from_version"],
            "sha256": transition["from_sha256"],
        },
        "directive supersedes binding changed",
    )
    replacements = derive_source_replacements(directive, ledger)
    return {
        "transition": f"{transition['from_version']}->{transition['to_version']}",
        "source_replacements": len(replacements),
        "metadata_changes": len(errata["allowed_version_metadata_changes"]),
        "one_shot": "consumed",
        "sha256": actual_sha,
    }


def main() -> int:
    try:
        directive = load_json(DIRECTIVE_PATH)
        ledger = load_json(LEDGER_PATH)
        validate_bound_ledger(
            directive,
            ledger,
            ledger_bytes=LEDGER_PATH.read_bytes(),
        )
        source_bytes = canonical_source_path(directive).read_bytes()
        baseline_bytes = load_git_baseline(directive)
        result = validate_final_state(directive, ledger, source_bytes, baseline_bytes)
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
