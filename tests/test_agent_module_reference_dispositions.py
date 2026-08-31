"""Validate the reproducible R17 dynamic-reference disposition ledger."""

from __future__ import annotations

import ast
from collections import Counter
from contextlib import contextmanager, redirect_stdout
import copy
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from typing import Any
import unittest
from unittest.mock import patch

import scripts.generate_agent_module_reference_dispositions as checkpoint_generator
import scripts.generate_agent_skills as agent_guides
import scripts.generate_execution_variant_characterization as execution_variant
import scripts.generate_journey_ledger as journey_ledger
import scripts.generate_skill_library as skill_library_generator
import scripts.generate_skill_packages as skill_packages
from gravity_insight.documentation_gate import (
    DocumentationGateError,
    validate_architecture_binding,
    validate_mermaid,
)
from scripts.validate_canonical_architecture import (
    validate_repository as validate_canonical_repository,
)
from scripts.run_integrated_validation import GateSpec, run_gate
from scripts.audit_agent_module_references import (
    AuditResult,
    CURRENT_PACKAGE_ROOT,
    GENERATED_GOVERNANCE_FILES,
    GOVERNANCE_EXCLUSION_RULE,
    HISTORICAL_PACKAGE_ROOT,
    PACKAGE_ROOT_MIGRATION,
    Finding,
    ReferenceScanner,
    historical_module_root,
    is_generated_governance_artifact,
    make_module_map,
    project_module_root,
    reference_module_mapping,
    scan_repository as _scan_repository,
    source_key,
    version_controlled_files,
    _frozen_module_scope,
)
from scripts.generate_agent_module_reference_dispositions import (
    ACTIVE_BARE_FILES,
    ACTIVE_REFERENCE,
    AMBIGUOUS_REFERENCE,
    DATED_DECISION_RECORD,
    DELETED_MODULE_RECORD,
    RUNTIME_CONSUMER,
    build_document as _build_document,
    checkpoint_sites,
    classify_active_bare_context as generator_classify_active_bare_context,
    _classify_reference as generator_classify_reference,
    render_document,
)
from tests.repository_tree_gate import (
    DEFAULT_TIMEOUT_SECONDS,
    RepositoryTreeGateTimeout,
    repository_tree_read,
    repository_tree_write,
)


ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
LEDGER = ROOT / "tests/fixtures/agent_module_reference_dispositions.json"
CHECKPOINT = ROOT / "tests/fixtures/agent_module_reference_checkpoint.json"
DIRECTIVE = ROOT / "specs/agent-runtime/directive.json"
CANONICAL_SOURCE = ROOT / "docs/architecture.md"
INDEX_JSON = ROOT / "specs/agent-runtime/index.json"
INDEX_MARKDOWN = ROOT / "specs/agent-runtime/index.md"
ROADMAP = ROOT / "docs/roadmap.md"
TECHNICAL_DEBT = ROOT / "docs/maintainers/technical-debt.md"
LEDGER_SHA256 = "9d5b4d197cd84a0da4bb644256c9df7670ec89b7258e710434ab1ac8fed8be20"
REVIEWED_LEDGER_GIT_BLOB = "0fcfa6c85e07c7cc901530ed8c2fe7516203e986"
REVIEWED_LEDGER_REVISION = "f2e8eec1f3c0567e20ab8c0be6465cc4e2c52e59"
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
CURRENT_PAGINATION_MODULE = project_module_root(PAGINATION_MODULE)
CURRENT_PAGINATION_TARGET = project_module_root(PAGINATION_TARGET)
CURRENT_RETAINED_MODULE = project_module_root(RETAINED_MODULE)
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


_RepositoryInputKey = tuple[Path, tuple[tuple[str, str], ...]]
_REPOSITORY_PRODUCTS_CACHE: dict[
    _RepositoryInputKey, tuple[AuditResult, dict[str, Any]]
] = {}


_DETERMINISTIC_WRITER = r"""
import sys
import tempfile
import time
from pathlib import Path

from tests.repository_tree_gate import DEFAULT_TIMEOUT_SECONDS, repository_tree_write

root = Path(sys.argv[1])
state = Path(sys.argv[2])
with repository_tree_write(
    root=root,
    purpose="deterministic R17 repository writer",
    timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
):
    with tempfile.TemporaryDirectory(
        dir=root / "tests", prefix="r17-deterministic-"
    ) as temp:
        attack = Path(temp) / "attack.py"
        attack.write_text(
            "from importlib import import_module\n"
            "owner = import_module(runtime_module_name)\n",
            encoding="utf-8",
        )
        (state / "attack.txt").write_text(
            attack.relative_to(root).as_posix(), encoding="utf-8"
        )
        (state / "ready").write_text("ready", encoding="ascii")
        deadline = time.monotonic() + 60
        while not (state / "release").exists():
            if time.monotonic() >= deadline:
                raise TimeoutError("writer timed out waiting for deterministic release")
            time.sleep(0.01)
"""


def _repository_input_key(root: Path) -> _RepositoryInputKey:
    resolved = root.resolve()
    files, _excluded = version_controlled_files(resolved)
    inputs: list[tuple[str, str]] = []
    for path in files:
        inputs.append(
            (
                path.relative_to(resolved).as_posix(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    return resolved, tuple(inputs)


def _repository_products(
    root: Path = ROOT, *, fresh: bool = False
) -> tuple[AuditResult, dict[str, Any]]:
    resolved = root.resolve()
    with repository_tree_read(
        root=resolved,
        purpose="R17 repository input inventory and reference scan",
    ):
        if fresh or resolved != ROOT.resolve():
            audit = _scan_repository(resolved)
            return audit, _build_document(root=resolved, audit=audit)
        key = _repository_input_key(resolved)
        cached = _REPOSITORY_PRODUCTS_CACHE.get(key)
        if cached is None:
            audit = _scan_repository(resolved)
            cached = (audit, _build_document(root=resolved, audit=audit))
            _REPOSITORY_PRODUCTS_CACHE[key] = cached
        return cached


def scan_repository(root: Path = ROOT, *, fresh: bool = False) -> AuditResult:
    return _repository_products(root, fresh=fresh)[0]


def build_document(
    *,
    root: Path = ROOT,
    audit: Any | None = None,
    public_exports: dict[str, Any] | None = None,
    fresh: bool = False,
) -> dict[str, Any]:
    resolved = root.resolve()
    if fresh:
        with repository_tree_read(
            root=resolved,
            purpose="fresh R17 checkpoint repository scan",
        ):
            if audit is None:
                audit = _scan_repository(resolved)
            return _build_document(
                root=resolved,
                audit=audit,
                public_exports=public_exports,
            )
    if audit is not None or public_exports is not None or resolved != ROOT.resolve():
        return _build_document(
            root=resolved,
            audit=audit,
            public_exports=public_exports,
        )
    return copy.deepcopy(_repository_products(resolved)[1])


def _assert_repository_tree_gate_orders_writer_and_scan(
    test_case: unittest.TestCase,
) -> None:
    with tempfile.TemporaryDirectory(prefix="repository-tree-gate-test-") as state_raw:
        state = Path(state_raw)
        process = subprocess.Popen(
            [sys.executable, "-c", _DETERMINISTIC_WRITER, str(ROOT), str(state)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        scan_result: list[AuditResult] = []
        scan_errors: list[BaseException] = []
        acquisition_attempted = threading.Event()
        acquisition_completed = threading.Event()
        release = state / "release"
        scanner: threading.Thread | None = None
        try:
            deadline = time.monotonic() + DEFAULT_TIMEOUT_SECONDS + 5
            while not (state / "ready").exists():
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    raise AssertionError(
                        "deterministic writer exited before ready: "
                        f"exit={process.returncode} stdout={stdout!r} stderr={stderr!r}"
                    )
                if time.monotonic() >= deadline:
                    raise AssertionError("timed out waiting for deterministic writer")
                time.sleep(0.01)
            relative = (state / "attack.txt").read_text(encoding="utf-8")

            with test_case.assertRaises(RepositoryTreeGateTimeout) as timeout:
                with repository_tree_read(
                    root=ROOT,
                    purpose="deterministic timeout negative control",
                    timeout_seconds=0.05,
                ):
                    pass
            test_case.assertIn("shared repository tree gate", str(timeout.exception))
            test_case.assertIn("deterministic timeout negative control", str(timeout.exception))

            real_repository_tree_read = repository_tree_read

            @contextmanager
            def observed_repository_tree_read(**kwargs: Any):
                acquisition_attempted.set()
                with real_repository_tree_read(**kwargs):
                    acquisition_completed.set()
                    yield

            def scan() -> None:
                try:
                    scan_result.append(scan_repository(fresh=True))
                except BaseException as exc:
                    scan_errors.append(exc)

            with patch(
                f"{__name__}.repository_tree_read", observed_repository_tree_read
            ):
                scanner = threading.Thread(target=scan)
                scanner.start()
                test_case.assertTrue(
                    acquisition_attempted.wait(10),
                    "repository scan did not attempt the shared gate",
                )
                test_case.assertTrue(scanner.is_alive())
                release.write_text("release", encoding="ascii")
                test_case.assertTrue(
                    acquisition_completed.wait(DEFAULT_TIMEOUT_SECONDS),
                    "guarded repository scan did not acquire the shared gate",
                )
                scanner.join(timeout=DEFAULT_TIMEOUT_SECONDS)
            test_case.assertFalse(
                scanner.is_alive(),
                "guarded repository scan did not finish after acquiring the shared gate",
            )
            test_case.assertEqual([], scan_errors)
            test_case.assertEqual(1, len(scan_result))
            observed = {
                key
                for key in (
                    source_key(item)
                    for item in (
                        *scan_result[0].references,
                        *scan_result[0].manual_review,
                    )
                )
                if key.startswith(relative + ":")
            }
            test_case.assertEqual(set(), observed)
        finally:
            release.write_text("release", encoding="ascii")
            if scanner is not None:
                scanner.join(timeout=DEFAULT_TIMEOUT_SECONDS)
            stdout, stderr = process.communicate(
                timeout=DEFAULT_TIMEOUT_SECONDS + 5
            )
            test_case.assertEqual(
                0,
                process.returncode,
                f"deterministic writer failed: stdout={stdout!r} stderr={stderr!r}",
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
        == "gravity.agent-module-reference-checkpoint.v2",
        "invalid checkpoint schema",
    )
    _require(
        document.get("receipt_role")
        == "live_checkpoint_scan_only; not authority for canonical errata replacements",
        "checkpoint role changed",
    )
    baseline = document.get("immutable_baseline_ledger", {})
    expected_binding = {
        "role": "errata_source_only_immutable_baseline",
        "repository_path": LEDGER.relative_to(ROOT).as_posix(),
        "git_blob": REVIEWED_LEDGER_GIT_BLOB,
        "sha256": LEDGER_SHA256,
        "schema_version": "gravity.agent-module-reference-dispositions.v2",
    }
    _require(baseline == expected_binding, "checkpoint baseline binding changed")
    reviewed_blob = subprocess.run(
        [
            "git",
            "rev-parse",
            f"{REVIEWED_LEDGER_REVISION}:{baseline['repository_path']}",
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

    package_root_migration = document.get("package_root_migration", {})
    _require(
        {
            key: package_root_migration.get(key)
            for key in PACKAGE_ROOT_MIGRATION
        }
        == PACKAGE_ROOT_MIGRATION,
        "checkpoint package-root migration changed",
    )
    _require(
        package_root_migration.get("historical_evidence_role")
        == "immutable_baseline_records_names_at_r17_delivery_time",
        "checkpoint historical evidence role changed",
    )
    _require(
        package_root_migration.get("current_validation_role")
        == "project_historical_r17_owners_before_filesystem_and_reference_checks",
        "checkpoint current projection role changed",
    )
    _require(
        package_root_migration.get("compatibility_package_present") is False,
        "checkpoint must not claim an old compatibility package",
    )
    _require(
        isinstance(package_root_migration.get("projected_scope_sha256"), str)
        and re.fullmatch(
            r"[0-9a-f]{64}", package_root_migration["projected_scope_sha256"]
        ),
        "checkpoint projected scope digest is invalid",
    )

    scope = document.get("scope", {})
    moves = scope.get("one_to_one_moves", [])
    historical_move_mapping = {
        item.get("old_module"): item.get("new_module") for item in moves
    }
    _require(len(historical_move_mapping) == 82, "checkpoint move scope changed")
    move_mapping = reference_module_mapping(historical_move_mapping)
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
                and historical_module_root(action.get("old_module", ""))
                == PAGINATION_MODULE
                and historical_module_root(action.get("new_module", ""))
                == PAGINATION_TARGET,
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
                        for old in [
                            *move_mapping,
                            PAGINATION_MODULE,
                            CURRENT_PAGINATION_MODULE,
                            RETAINED_MODULE,
                            CURRENT_RETAINED_MODULE,
                        ]
                        if old_value == "src/" + old.replace(".", "/") + ".py"
                    ),
                    old_value
                    if old_value
                    in {
                        PAGINATION_MODULE,
                        CURRENT_PAGINATION_MODULE,
                        RETAINED_MODULE,
                        CURRENT_RETAINED_MODULE,
                    }
                    else None,
                )
            sentinel = (
                file == "tests/test_agent_concept_deletions.py"
                and source.get("reference_category") == "string_reference"
            )
            historical_old_module = (
                historical_module_root(old_module) if old_module else None
            )
            if (
                file.startswith("docs/archive/")
                or sentinel
                or historical_old_module == RETAINED_MODULE
            ):
                _require(disposition == "no_migration_effect", f"frozen exact reference moved at {key}")
            elif historical_old_module == PAGINATION_MODULE:
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
        "accepted_by",
        "owner_review",
        "phase_1_commit",
        "phase_2_commit",
        "dev_integration_commit",
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
    _require("R17" not in roadmap, "roadmap still contains Program construction history")
    _require(
        "`gravity_insight.agents` 是 compact Agent interaction 的唯一实现包"
        in technical_debt,
        "technical debt lost the current Agent package owner boundary",
    )
    _require(
        "五条有意保留的 facade 依赖" in technical_debt,
        "technical debt lost the retained facade constraint",
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
    if index.get("schema_version") == "gravity.agent-runtime-components.v1":
        _require(specification == "", "released Requirement prose must be absent")
        _require(
            set(directive) == {"path", "digest", "version", "approval"},
            "directive is not minimal",
        )
        _require(directive["path"] == "docs/architecture.md", "canonical path changed")
        _require(directive["approval"] == "approved", "canonical approval changed")
        _require("requirements" not in index, "Program requirement ledger returned")
        package = next(
            item for item in index["components"] if item.get("id") == "package-facade"
        )
        ledger_path = "../../" + LEDGER.relative_to(ROOT).as_posix()
        _require(
            ledger_path in package["machine_sources"],
            "package component lost immutable ledger owner",
        )
        _require(
            "`package-facade`" in index_markdown,
            "package component missing from Markdown",
        )
        _require(
            hashlib.sha256(ledger_bytes).hexdigest() == LEDGER_SHA256,
            "immutable ledger digest changed",
        )
        baseline = checkpoint.get("immutable_baseline_ledger", {})
        _require(
            baseline.get("sha256") == LEDGER_SHA256,
            "checkpoint ledger binding changed",
        )
        _require(
            baseline.get("git_blob") == REVIEWED_LEDGER_GIT_BLOB,
            "checkpoint ledger Git blob changed",
        )
        _require(
            hashlib.sha256(checkpoint_bytes).hexdigest()
            == hashlib.sha256(CHECKPOINT.read_bytes()).hexdigest(),
            "checkpoint bytes changed during validation",
        )
        _require(ledger.get("blockers") == [], "immutable ledger has blockers")
        return
class AgentModuleReferenceDispositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = LEDGER.read_bytes()
        cls.document = json.loads(cls.raw)
        cls.checkpoint_raw = CHECKPOINT.read_bytes()
        cls.checkpoint = json.loads(cls.checkpoint_raw)
        cls.directive = json.loads(DIRECTIVE.read_text(encoding="utf-8"))
        cls.membership_registry = tomllib.loads(
            PYPROJECT.read_text(encoding="utf-8")
        )["tool"]["gravity_insight"]["agent-package-membership"]

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
        _assert_repository_tree_gate_orders_writer_and_scan(self)

    def test_new_exact_dynamic_and_alias_loader_sites_cannot_escape_disposition(self) -> None:
        with repository_tree_write(
            root=ROOT,
            purpose="R17 tracked dynamic-import attack fixture",
        ):
            with tempfile.TemporaryDirectory(
                dir=ROOT / "tests", prefix="r17-tracked-"
            ) as temp:
                attack = Path(temp) / "attack.py"
                attack.write_text(
                    "import importlib\n"
                    'dynamic = importlib.import_module("gravity_sdk.agent_sources")\n'
                    'alias = acquire("gravity_sdk.agent_sources")\n',
                    encoding="utf-8",
                )
                generated = build_document(fresh=True)
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
        with repository_tree_write(
            root=ROOT,
            purpose="R17 unknown dynamic-import blocker fixture",
        ):
            with tempfile.TemporaryDirectory(
                dir=ROOT / "tests", prefix="r17-blocker-"
            ) as temp:
                attack = Path(temp) / "attack.py"
                attack.write_text(
                    "from importlib import import_module\n"
                    "owner = import_module(runtime_module_name)\n",
                    encoding="utf-8",
                )
                generated = build_document(fresh=True)
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
            "",
            self.document,
            self.directive,
            ledger_bytes=self.raw,
            checkpoint=self.checkpoint,
            checkpoint_bytes=self.checkpoint_raw,
        )

    def test_index_and_specification_state_injections_fail_closed(self) -> None:
        index = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        index_markdown = INDEX_MARKDOWN.read_text(encoding="utf-8")
        package_missing = copy.deepcopy(index)
        package = next(
            item for item in package_missing["components"] if item.get("id") == "package-facade"
        )
        package["machine_sources"].remove(
            "../../tests/fixtures/agent_module_reference_dispositions.json"
        )
        directive_drift = copy.deepcopy(self.directive)
        directive_drift["approval"] = "pending"
        injections = {
            "package machine owner removed": (package_missing, index_markdown, "", self.directive),
            "package Markdown row removed": (
                index,
                index_markdown.replace("`package-facade`", "`package-facade-missing`", 1),
                "",
                self.directive,
            ),
            "released requirement prose returned": (index, index_markdown, "history", self.directive),
            "directive approval drift": (index, index_markdown, "", directive_drift),
        }
        for label, (injected_index, injected_markdown, injected_spec, injected_directive) in injections.items():
            with self.subTest(label=label), self.assertRaises(AssertionError):
                validate_index_and_specification_state(
                    injected_index,
                    injected_markdown,
                    injected_spec,
                    self.document,
                    injected_directive,
                    ledger_bytes=self.raw,
                    checkpoint=self.checkpoint,
                    checkpoint_bytes=self.checkpoint_raw,
                )

    def test_active_scope_owner_documents_are_in_the_consistency_set(self) -> None:
        roadmap = ROADMAP.read_text(encoding="utf-8")
        technical_debt = TECHNICAL_DEBT.read_text(encoding="utf-8")
        validate_active_scope_owner_projection(roadmap, technical_debt, self.document)
        injections = {
            "roadmap Program ID": (
                roadmap + "\nR17 construction history\n",
                technical_debt,
                "roadmap still contains Program construction history",
            ),
            "roadmap delivery status": (
                roadmap + "\nR17 fixed_dev\n",
                technical_debt,
                "roadmap still contains Program construction history",
            ),
            "technical-debt package owner": (
                roadmap,
                technical_debt.replace(
                    "`gravity_insight.agents` 是 compact Agent interaction 的唯一实现包",
                    "package owner missing",
                    1,
                ),
                "lost the current Agent package owner boundary",
            ),
            "technical-debt facade relation": (
                roadmap,
                technical_debt.replace("五条有意保留的 facade 依赖", "facade dependencies", 1),
                "lost the retained facade constraint",
            ),
            "technical-debt both owners": (
                roadmap,
                technical_debt.replace("五条有意保留的 facade 依赖", "", 1),
                "lost the retained facade constraint",
            ),
        }
        for label, (injected_roadmap, injected_debt, message) in injections.items():
            with self.subTest(label=label), self.assertRaisesRegex(AssertionError, message):
                validate_active_scope_owner_projection(
                    injected_roadmap, injected_debt, self.document
                )

    def _write_scope_tree(
        self, root: Path, *, old_count: int, pagination_old: bool
    ) -> None:
        ledger = root / "tests/fixtures/agent_module_reference_dispositions.json"
        ledger.parent.mkdir(parents=True)
        ledger.write_bytes(self.raw)
        modules = {
            move["old_module"] if index < old_count else move["new_module"]
            for index, move in enumerate(self.document["scope"]["one_to_one_moves"])
        }
        modules.update((PAGINATION_TARGET, RETAINED_MODULE))
        if pagination_old:
            modules.add(PAGINATION_MODULE)
        for module in modules:
            current_module = project_module_root(module)
            path = root / "src" / Path(*current_module.split(".")).with_suffix(".py")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

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
                self._write_scope_tree(
                    root, old_count=old_count, pagination_old=pagination_old
                )
                mappings, mapping = make_module_map(root)
                self.assertEqual(
                    {
                        **{move["old_module"]: move["new_module"] for move in moves},
                        PAGINATION_MODULE: PAGINATION_TARGET,
                        RETAINED_MODULE: RETAINED_MODULE,
                    },
                    mapping,
                )
                self.assertEqual(
                    82 - old_count,
                    sum(item.target_exists for item in mappings[:82]),
                )

    def test_frozen_scope_rejects_unreviewed_owner_states(self) -> None:
        move = self.document["scope"]["one_to_one_moves"][0]
        cases = (
            ("Phase 0 count", 81, True, None, None, "unsupported R17 frozen-owner state"),
            ("Phase 1 count", 33, False, None, None, "unsupported R17 frozen-owner state"),
            ("Phase 2 count", 1, False, None, None, "unsupported R17 frozen-owner state"),
            ("overlap", 0, False, None, move["old_module"], "exactly one old/new path"),
            ("missing move", 0, False, move["new_module"], None, "exactly one old/new path"),
            ("consolidation target", 0, False, PAGINATION_TARGET, None, "target is missing"),
            ("retained owner", 0, False, RETAINED_MODULE, None, "retained owner is missing"),
            ("extra root owner", 0, False, None, "gravity_sdk.agent_unreviewed", "unexpected root agent owner"),
        )
        for label, old_count, pagination_old, removed, added, message in cases:
            with self.subTest(case=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self._write_scope_tree(
                    root, old_count=old_count, pagination_old=pagination_old
                )
                if removed:
                    current_removed = project_module_root(removed)
                    (
                        root
                        / "src"
                        / Path(*current_removed.split(".")).with_suffix(".py")
                    ).unlink()
                if added:
                    current_added = project_module_root(added)
                    (
                        root
                        / "src"
                        / Path(*current_added.split(".")).with_suffix(".py")
                    ).write_text(
                        "", encoding="utf-8"
                    )
                with self.assertRaisesRegex(RuntimeError, message):
                    make_module_map(root)

    def test_current_agent_package_membership_is_explicitly_registered(self) -> None:
        self.assertEqual(1, self.membership_registry.get("schema-version"))
        members = self.membership_registry.get("members")
        self.assertIsInstance(members, list)
        invalid = [
            member
            for member in members
            if not isinstance(member, str)
            or Path(member).is_absolute()
            or "\\" in member
            or ".." in Path(member).parts
            or not member.endswith(".py")
            or Path(member).name == "__init__.py"
        ]
        self.assertEqual([], invalid, "registered agent members must be safe .py paths")
        self.assertEqual(
            sorted(set(members)),
            members,
            "registered agent members must be unique and sorted",
        )
        agents_root = ROOT / "src/gravity_insight/agents"
        actual = {
            path.relative_to(agents_root).as_posix()
            for path in agents_root.rglob("*.py")
            if path.name != "__init__.py"
        }
        registered = set(members)
        unregistered = sorted(actual - registered)
        registered_but_missing = sorted(registered - actual)
        self.assertEqual(
            [],
            unregistered,
            "unregistered agents module(s); register each new module in "
            "[tool.gravity_insight.agent-package-membership] in pyproject.toml: "
            f"{unregistered}",
        )
        self.assertEqual(
            [],
            registered_but_missing,
            "registered agents module(s) missing from src/gravity_insight/agents; "
            f"update the registration with the code change: {registered_but_missing}",
        )

    def test_every_frozen_move_target_remains_registered_and_present(self) -> None:
        frozen_scope = _frozen_module_scope(ROOT)[:82]
        frozen_members = {
            Path(*new_module.split(".")).with_suffix(".py")
            .relative_to(Path("gravity_sdk/agents"))
            .as_posix()
            for _, new_module in frozen_scope
        }
        registered = set(self.membership_registry["members"])
        self.assertEqual(82, len(frozen_members))
        self.assertEqual(
            [],
            sorted(frozen_members - registered),
            "frozen R17 target(s) must remain in the current agent membership registry",
        )
        missing_targets = sorted(
            new_module
            for _, new_module in frozen_scope
            if not (
                ROOT
                / "src"
                / Path(*project_module_root(new_module).split(".")).with_suffix(".py")
            ).is_file()
        )
        self.assertEqual(
            [],
            missing_targets,
            "frozen R17 target file(s) must remain present in the agents package",
        )

    def test_frozen_move_mapping_is_an_exact_bijection(self) -> None:
        moves = self.document["scope"]["one_to_one_moves"]
        expected = [(move["old_module"], move["new_module"]) for move in moves]
        self.assertEqual(expected, _frozen_module_scope(ROOT)[:82])
        mappings, _ = make_module_map(ROOT)
        self.assertEqual(expected, [(item.old_module, item.new_module) for item in mappings[:82]])
        self.assertEqual(82, len({item.old_module for item in mappings[:82]}))
        self.assertEqual(82, len({item.new_module for item in mappings[:82]}))
        duplicate = copy.deepcopy(self.document)
        duplicate["scope"]["one_to_one_moves"][1] = dict(moves[0])
        wrong_name = copy.deepcopy(self.document)
        relative_date = next(
            move for move in wrong_name["scope"]["one_to_one_moves"]
            if move["old_module"] == "gravity_sdk.relative_date_agent"
        )
        relative_date["new_module"] = "gravity_sdk.agents.relative_date_agent"
        for label, document, message in (
            ("duplicate pair", duplicate, "move owners must be unique"),
            ("redundant boundary token", wrong_name, "invalid frozen R17 move"),
        ):
            with self.subTest(case=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                ledger = root / "tests/fixtures/agent_module_reference_dispositions.json"
                ledger.parent.mkdir(parents=True)
                ledger.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, message):
                    _frozen_module_scope(root)

    def test_relative_date_target_uses_the_shared_boundary_token_rule(self) -> None:
        mappings, _ = make_module_map(ROOT)
        relative_date = next(
            item
            for item in mappings
            if item.old_module == "gravity_sdk.relative_date_agent"
        )
        self.assertEqual("gravity_sdk.agents.relative_date", relative_date.new_module)
        self.assertEqual("src/gravity_insight/agents/relative_date.py", relative_date.new_file)
        self.assertTrue(relative_date.target_exists)
        self.assertFalse((ROOT / relative_date.old_file).exists())
        self.assertFalse(relative_date.casefold_target_collision)
        self.assertFalse(relative_date.stdlib_basename_collision)
        self.assertFalse((ROOT / "src/gravity_insight/relative_date.py").exists())

    def test_governance_exclusion_is_narrow_and_explicit(self) -> None:
        for path in GENERATED_GOVERNANCE_FILES:
            self.assertTrue(is_generated_governance_artifact(path), path)
        self.assertFalse(
            is_generated_governance_artifact(
                "specs/agent-runtime/R17-agent-module-package-migration.md"
            )
        )
        self.assertTrue(is_generated_governance_artifact("tmp/codex/audit/output.csv"))
        protected = (
            "AGENTS.md",
            "docs/architecture.md",
            "specs/agent-runtime/index.json",
            "specs/agent-runtime/index.md",
            "docs/maintainers/technical-debt.md",
            "tests/agent_migration_characterization.py",
            "src/gravity_insight/agent_sources.py",
        )
        for path in protected:
            self.assertFalse(is_generated_governance_artifact(path), path)

        scanner = ReferenceScanner(
            reference_module_mapping(
                {"gravity_sdk.agent_sources": "gravity_sdk.agents.sources"}
            )
        )
        references, _ = scanner.scan_python(
            "src/gravity_insight/real_consumer.py",
            "from gravity_insight.agent_sources import snapshot_recipe_cards\n",
        )
        self.assertEqual(["static_import"], [item.category for item in references])
        pagination_scanner = ReferenceScanner(
            reference_module_mapping({PAGINATION_MODULE: PAGINATION_TARGET})
        )
        references, _ = pagination_scanner.scan_python(
            "src/gravity_insight/real_pagination_consumer.py",
            "from .agent_pagination import compact_pagination\n",
        )
        self.assertEqual(
            [
                (
                    "static_import",
                    CURRENT_PAGINATION_MODULE,
                    CURRENT_PAGINATION_TARGET,
                )
            ],
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
            f"from {HISTORICAL_PACKAGE_ROOT}.agent_pagination import compact_pagination",
            "from .agent_pagination import compact_pagination",
            f"from {HISTORICAL_PACKAGE_ROOT} import agent_pagination",
            f"import {HISTORICAL_PACKAGE_ROOT}.agent_pagination",
            f"{HISTORICAL_PACKAGE_ROOT}.agent_pagination.compact_pagination(items)",
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
            "import": f"from {HISTORICAL_PACKAGE_ROOT}.agent_batch import capabilities_many",
            "call": f"{HISTORICAL_PACKAGE_ROOT}.agent_batch.capabilities_many([])",
            "patch": f"patch('{HISTORICAL_PACKAGE_ROOT}.agent_batch.capabilities_many')",
            "attribute": f"handler = {HISTORICAL_PACKAGE_ROOT}.agent_batch.capabilities_many",
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
        consumer = (
            f"from {HISTORICAL_PACKAGE_ROOT}.agent_pagination "
            "import compact_pagination"
        )
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
            "import": f"from {HISTORICAL_PACKAGE_ROOT}.agent_batch import capabilities_many",
            "call": f"{HISTORICAL_PACKAGE_ROOT}.agent_batch.capabilities_many([])",
            "patch": f"patch('{HISTORICAL_PACKAGE_ROOT}.agent_batch.capabilities_many')",
            "attribute": f"handler = {HISTORICAL_PACKAGE_ROOT}.agent_batch.capabilities_many",
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


    def _binding_fixture(
        self,
        directory: str,
        *,
        source: str | None = None,
        directive_changes: dict[str, Any] | None = None,
    ) -> Path:
        root = Path(directory)
        canonical = root / "docs/architecture.md"
        canonical.parent.mkdir(parents=True)
        text = source or "# Gravity Agent Runtime Canonical Architecture\n\n```mermaid\nflowchart LR\n  A[Host] --> B[Runtime]\n```\n"
        canonical.write_text(text, encoding="utf-8", newline="\n")
        directive = {
            "path": "docs/architecture.md",
            "digest": hashlib.sha256(canonical.read_bytes()).hexdigest(),
            "version": "1.0.0",
            "approval": "approved",
        }
        directive.update(directive_changes or {})
        binding = root / "specs/agent-runtime/directive.json"
        binding.parent.mkdir(parents=True)
        binding.write_text(json.dumps(directive), encoding="utf-8")
        return root

    def test_canonical_errata_replacements_are_derived_only_from_ledger(self) -> None:
        result = validate_canonical_repository(ROOT)
        self.assertEqual("docs/architecture.md", result["path"])
        self.assertEqual(1, result["mermaid_blocks"])

    def test_canonical_errata_derivation_fails_closed_on_ledger_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._binding_fixture(temp)
            directive = json.loads((root / "specs/agent-runtime/directive.json").read_text())
            directive["history"] = []
            (root / "specs/agent-runtime/directive.json").write_text(json.dumps(directive))
            with self.assertRaisesRegex(DocumentationGateError, "exactly path"):
                validate_architecture_binding(root)

    def test_canonical_errata_rejects_same_commit_ledger_rebinding(self) -> None:
        forged = bytearray(self.raw)
        forged[-2] = ord(" ")
        self.assertNotEqual(LEDGER_SHA256, hashlib.sha256(forged).hexdigest())
        self.assertEqual(REVIEWED_LEDGER_GIT_BLOB, self.checkpoint["immutable_baseline_ledger"]["git_blob"])

    def test_canonical_transition_baseline_is_literal_and_not_rebindable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._binding_fixture(temp, directive_changes={"path": "../outside.md"})
            with self.assertRaisesRegex(DocumentationGateError, "repository-relative"):
                validate_architecture_binding(root)

    def test_phase1_canonical_source_and_directive_equal_reviewed_bytes(self) -> None:
        result = validate_architecture_binding(ROOT)
        self.assertEqual(self.directive["digest"], result["digest"])
        self.assertEqual(hashlib.sha256(CANONICAL_SOURCE.read_bytes()).hexdigest(), result["digest"])

    def test_phase1_acceptance_runs_m0_public_api_and_behavior_after_precondition(self) -> None:
        self.assertEqual({"path", "digest", "version", "approval"}, set(self.directive))
        self.assertEqual("approved", self.directive["approval"])
        retired_fields = (
            "schema_version",
            "directive_id",
            "status",
            "canonical_source",
            "origin",
            "supersedes",
            "canonical_source_errata",
            "canonical_source_amendment",
            "canonical_source_naming_amendment",
            "review_baseline",
            "documentation_binding",
            "reviewed_baseline",
            "requirements_index",
            "main_integration",
        )
        for field in retired_fields:
            with self.subTest(field=field):
                self.assertNotIn(field, self.directive)

    def test_canonical_errata_final_assertion_is_full_text_and_one_shot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._binding_fixture(temp)
            (root / "docs/architecture.md").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(DocumentationGateError, "digest mismatch"):
                validate_architecture_binding(root)

    def test_terminal_directive_accepts_exact_r17_consumption_changes(self) -> None:
        self.assertNotIn("supersedes", self.directive)
        self.assertNotIn("transition", self.directive)
        self.assertNotIn("amendment", " ".join(self.directive))

    def test_terminal_directive_rejects_approval_scope_drift_with_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._binding_fixture(temp, directive_changes={"approval": "pending"})
            with self.assertRaisesRegex(DocumentationGateError, "approval must be approved"):
                validate_architecture_binding(root)

    def test_terminal_directive_rejects_main_unfreeze_with_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._binding_fixture(temp, directive_changes={"version": ""})
            with self.assertRaisesRegex(DocumentationGateError, "version must be"):
                validate_architecture_binding(root)

    def test_canonical_errata_rejects_semantic_change_hidden_as_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = self._binding_fixture(temp, directive_changes={"digest": "0" * 64})
            with self.assertRaisesRegex(DocumentationGateError, "digest mismatch"):
                validate_architecture_binding(root)

    def test_phase2_checkpoint_and_immutable_errata_gate_pass_together(self) -> None:
        validate_checkpoint_receipt(self.checkpoint)
        self.assertEqual(LEDGER_SHA256, hashlib.sha256(self.raw).hexdigest())
        self.assertEqual("docs/architecture.md", validate_canonical_repository(ROOT)["path"])

    def test_canonical_errata_rejects_forged_move_with_synced_source_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = "# Canonical\n" + "line\n" * 400
            root = self._binding_fixture(temp, source=source)
            with self.assertRaisesRegex(DocumentationGateError, "401 lines"):
                validate_architecture_binding(root)

    def test_v94_baseline_matches_exact_post_program_amendment(self) -> None:
        self.assertFalse((ROOT / "scripts/validate_r17_canonical_source_errata.py").exists())
        self.assertTrue((ROOT / "scripts/validate_canonical_architecture.py").is_file())

    def test_current_canonical_source_matches_exact_v95_naming_amendment(self) -> None:
        result = validate_canonical_repository(ROOT)
        self.assertLessEqual(result["lines"], 400)
        self.assertLessEqual(result["bytes"], 30_000)

    def test_v95_naming_amendment_rejects_allowlist_or_source_drift(self) -> None:
        with self.assertRaisesRegex(DocumentationGateError, "flowchart direction"):
            validate_mermaid("```mermaid\nsequenceDiagram\n  A --> B\n```\n")

    def test_v95_naming_amendment_rejects_directive_authority_drift(self) -> None:
        with self.assertRaisesRegex(DocumentationGateError, "unterminated"):
            validate_mermaid("```mermaid\nflowchart LR\n  A --> B\n")


class GateFailureGuidanceTests(unittest.TestCase):
    def test_agent_guides_stale_message_gives_rebuild_command(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp:
            target = Path(temp) / "guide.md"
            with patch.object(agent_guides, "render_documents", return_value={target: "new"}), patch.object(
                sys, "argv", ["generate_agent_skills.py", "--check"]
            ):
                with self.assertRaises(SystemExit) as raised:
                    agent_guides.main()
        self.assertIn("do not match their current contract inputs", str(raised.exception))
        self.assertIn("python scripts/generate_agent_skills.py", str(raised.exception))

    def test_skill_package_mismatch_message_gives_rebuild_command(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp:
            target = Path(temp) / "package" / "SKILL.md"
            with patch.object(skill_packages, "render_outputs", return_value={target: b"new"}), patch.object(
                sys, "argv", ["generate_skill_packages.py", "--check"]
            ):
                with self.assertRaises(SystemExit) as raised:
                    skill_packages.main()
        self.assertIn("missing or differ", str(raised.exception))
        self.assertIn("python scripts/generate_skill_packages.py", str(raised.exception))

    def test_skill_package_extra_message_requires_manual_deletion_review(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp:
            target = Path(temp) / "package" / "SKILL.md"
            target.parent.mkdir()
            target.write_bytes(b"current")
            extra = target.parent / "unexpected.txt"
            extra.write_text("unexpected", encoding="utf-8")
            with patch.object(skill_packages, "render_outputs", return_value={target: b"current"}), patch.object(
                sys, "argv", ["generate_skill_packages.py", "--check"]
            ):
                with self.assertRaises(SystemExit) as raised:
                    skill_packages.main()
        self.assertIn("unregistered files", str(raised.exception))
        self.assertIn("will not delete", str(raised.exception))
        self.assertIn("delete only files that are not registered", str(raised.exception))

    def test_journey_ledger_stale_message_gives_rebuild_command(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp:
            target = Path(temp) / "ledger.json"
            target.write_text("old", encoding="utf-8")
            output = io.StringIO()
            with patch.object(journey_ledger, "TARGET", target), patch.object(
                journey_ledger, "rendered_snapshot", return_value="new"
            ), patch.object(sys, "argv", ["generate_journey_ledger.py", "--check"]), redirect_stdout(output):
                self.assertEqual(1, journey_ledger.main())
        self.assertIn("does not match docs/analysis-journeys.md", output.getvalue())
        self.assertIn("python scripts/generate_journey_ledger.py", output.getvalue())

    def test_skill_library_check_rejects_tracked_generated_mirrors(self) -> None:
        with patch.object(
            skill_library_generator,
            "_assert_no_tracked_mirrors",
            side_effect=SystemExit("generated Skill mirrors are tracked"),
        ):
            with self.assertRaises(SystemExit) as raised:
                skill_library_generator.main(["--check"])
        self.assertIn("generated Skill mirrors are tracked", str(raised.exception))

    def test_execution_variant_stale_message_gives_rebuild_command(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp:
            target = Path(temp) / "characterization.json"
            with patch.object(execution_variant, "TARGET", target), patch.object(
                execution_variant, "build_artifact", return_value={}
            ), patch.object(execution_variant, "_render", return_value="new"), patch.object(
                sys, "argv", ["generate_execution_variant_characterization.py", "--check"]
            ):
                with self.assertRaises(SystemExit) as raised:
                    execution_variant.main()
        self.assertIn("deterministic characterization corpus", str(raised.exception))
        self.assertIn(
            "python scripts/generate_execution_variant_characterization.py",
            str(raised.exception),
        )

    def test_package_reference_stale_receipt_requires_review_before_rebind(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as temp:
            missing_receipt = Path(temp) / "checkpoint.json"
            command = "\n".join(
                (
                    "from pathlib import Path",
                    "import scripts.generate_agent_module_reference_dispositions as checkpoint",
                    f"checkpoint.OUTPUT = Path({str(missing_receipt)!r})",
                    "raise SystemExit(checkpoint.main(['--check']))",
                )
            )
            gate = GateSpec("package_reference_checkpoint", (sys.executable, "-c", command))
            result = run_gate(gate, Path(temp), dict(os.environ))
            text = (Path(temp) / "package_reference_checkpoint.log").read_text(encoding="utf-8")
        self.assertEqual(1, result["exit_code"])
        self.assertIn("stale checkpoint receipt", text)
        self.assertIn("Do not blindly regenerate it", text)
        self.assertIn("newly added non-reference files", text)
        self.assertIn("Stop for manual package-boundary review", text)
        self.assertIn("do not modify or rebind the immutable baseline", text)


if __name__ == "__main__":
    unittest.main()
