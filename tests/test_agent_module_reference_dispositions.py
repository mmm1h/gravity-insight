"""Validate the reviewed R17 dynamic-reference disposition ledger."""

from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
from typing import Any
import unittest


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "tests/fixtures/agent_module_reference_dispositions.json"
LEDGER_SHA256 = "6bd35c5d914e751a048d138e1e6770244a68273761528acaa9be5d4d41716661"
SOURCE_AUDIT_SHA256 = "6116564ed625feb969f0838ece2aa12b4c92cd82b76b1da51fc67add128c713c"
REFERENCE_EVIDENCE_SHA256 = "356287b9a245d609185ed1dcf89385af13435a3c4b0d8efed87303cb97c01e53"
CANDIDATE_MAP_SHA256 = "8c59fea70e6ff78d156fbf33216fa1a31459b2881cd7aba21efd77d2230b655a"
EXPECTED_CATEGORIES = {
    "bare_agent_string": 92,
    "dynamic_import": 11,
    "module_owner_receiver": 7,
    "non_string_patch_expression": 117,
}
EXPECTED_DISPOSITIONS = {
    "no_migration_effect": 213,
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


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _canonical_sites_sha256(sites: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(
        sites, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()


def validate_ledger(document: dict[str, Any]) -> None:
    _require(
        document.get("schema_version")
        == "gravity.agent-module-reference-dispositions.v1",
        "invalid disposition-ledger schema",
    )
    source = document.get("source_audit", {})
    _require(source.get("sha256") == SOURCE_AUDIT_SHA256, "source audit is not bound")
    _require(
        source.get("reference_evidence_sha256") == REFERENCE_EVIDENCE_SHA256,
        "reference evidence is not bound",
    )
    _require(
        source.get("candidate_map_sha256") == CANDIDATE_MAP_SHA256,
        "candidate map is not bound",
    )

    scope = document.get("scope", {})
    moves = scope.get("one_to_one_moves", [])
    _require(len(moves) == 81, "R17 must have exactly 81 one-to-one targets")
    old_targets = {item.get("old_module") for item in moves}
    new_targets = {item.get("new_module") for item in moves}
    move_mapping = {item.get("old_module"): item.get("new_module") for item in moves}
    _require(len(old_targets) == len(new_targets) == 81, "move targets must be unique")
    for item in moves:
        old = item.get("old_module")
        new = item.get("new_module")
        _require(
            isinstance(old, str) and old.startswith("gravity_sdk.agent_"),
            f"invalid old move target: {old!r}",
        )
        _require(
            new == f"gravity_sdk.agents.{old.removeprefix('gravity_sdk.agent_')}",
            f"move target is not a one-to-one R17 path: {old!r} -> {new!r}",
        )
    _require(PAGINATION_MODULE not in old_targets, "pagination cannot be a one-to-one move")
    _require(RETAINED_MODULE not in old_targets, "retained contracts cannot move")
    _require(
        scope.get("consolidate_delete") == {
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
    _require(isinstance(sites, list) and len(sites) == 227, "ledger must contain 227 sites")
    keys = [site.get("source_key") for site in sites]
    _require(len(set(keys)) == 227, "ledger source keys must be unique")

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
            _require(action == {"kind": "none"}, f"no-effect row has an action at {key}")
        elif disposition == "rewrite_reference":
            _require(action.get("kind") == "replace_text", f"invalid text action at {key}")
            _require(action.get("new_module") in new_targets, f"illegal move target at {key}")
            _require(
                action.get("old_module") in old_targets,
                f"unknown old move target at {key}",
            )
            _require(
                move_mapping[action["old_module"]] == action["new_module"],
                f"mismatched move pair at {key}",
            )
            _require(
                action.get("old_text") and action.get("new_text")
                and action["old_text"] != action["new_text"],
                f"non-exact text replacement at {key}",
            )
        elif disposition == "rewrite_selector_data":
            _require(
                action.get("kind") == "replace_selector_values",
                f"invalid selector action at {key}",
            )
            rewrites = action.get("rewrites", [])
            _require(
                len(rewrites) == 6
                and len({rewrite.get("symbol") for rewrite in rewrites}) == 6,
                f"root selector must have six unique owner rewrites at {key}",
            )
            for rewrite in rewrites:
                _require(
                    rewrite.get("new_module") in new_targets,
                    f"illegal selector target at {key}",
                )
                _require(
                    rewrite.get("old_module") in old_targets,
                    f"unknown selector source at {key}",
                )
                _require(
                    move_mapping[rewrite["old_module"]] == rewrite["new_module"],
                    f"mismatched selector pair at {key}",
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
        if reference.get("candidate_new_module") is not None:
            _require(
                move_mapping.get(reference.get("old_module"))
                == reference.get("candidate_new_module"),
                f"invalid no-effect candidate mapping at {key}",
            )
        audited_value = str(source_site.get("old_value", ""))
        if reference.get("old_module") == RETAINED_MODULE:
            _require(
                disposition == "no_migration_effect",
                f"retained contracts reference cannot migrate at {key}",
            )
        if "agent_runtime_contracts" in audited_value:
            _require(
                disposition == "no_migration_effect",
                f"audited retained contracts reference cannot migrate at {key}",
            )
        if reference.get("old_module") == PAGINATION_MODULE:
            _require(
                disposition in {"rewrite_consolidated_reference", "blocker"},
                f"pagination reference must rewrite or block at {key}",
            )
        if "agent_pagination" in audited_value:
            _require(
                disposition in {"rewrite_consolidated_reference", "blocker"},
                f"audited pagination reference must rewrite or block at {key}",
            )

    _require(dict(categories) == EXPECTED_CATEGORIES, "audit-category denominator changed")
    _require(dict(dispositions) == EXPECTED_DISPOSITIONS, "disposition distribution changed")
    summary = document.get("summary", {})
    _require(summary.get("site_count") == len(sites), "declared site count differs")
    _require(summary.get("unique_source_keys") == len(set(keys)), "declared key count differs")
    _require(summary.get("unclassified_sites") == 0, "ledger has unclassified sites")
    actual_blockers = dispositions["blocker"]
    _require(summary.get("blocker_count") == actual_blockers, "blocker count differs")
    _require(actual_blockers == 0, "R17 ledger blockers must be resolved before ready")
    _require(document.get("blockers") == [], "blocker list differs from zero count")
    _require(summary.get("audit_categories") == EXPECTED_CATEGORIES, "category summary differs")
    _require(summary.get("dispositions") == EXPECTED_DISPOSITIONS, "disposition summary differs")
    _require(
        summary.get("sites_sha256") == _canonical_sites_sha256(sites),
        "canonical site digest differs",
    )


class AgentModuleReferenceDispositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = LEDGER.read_bytes()
        cls.document = json.loads(cls.raw)

    def test_reviewed_fixture_sha256_is_bound(self) -> None:
        self.assertEqual(LEDGER_SHA256, hashlib.sha256(self.raw).hexdigest())

    def test_current_ledger_satisfies_the_machine_contract(self) -> None:
        validate_ledger(self.document)

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
            site for site in illegal_target["sites"]
            if site["disposition"] == "rewrite_reference"
        )
        rewrite["migration_action"]["new_module"] = "gravity_sdk.agents.pagination"
        mutations["illegal new target"] = illegal_target

        for label, document in mutations.items():
            with self.subTest(label=label), self.assertRaises(AssertionError):
                validate_ledger(document)


if __name__ == "__main__":
    unittest.main()
