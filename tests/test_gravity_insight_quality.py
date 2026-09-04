from __future__ import annotations

import ast
from contextlib import redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pytest

from gravity_insight.quality import (
    COMPLEXITY_LIMIT,
    FILE_SLOC_LIMIT,
    FUNCTION_SLOC_LIMIT,
    FunctionMetric,
    LiteralOccurrence,
    QualityProfile,
    compare_baselines,
    count_ast_nodes,
    count_sloc,
    cyclomatic_complexity,
    debt_snapshot,
    evaluate_ratchet,
    evaluate_slope,
    hardcoded_exit_code_errors,
    inspect_repository as _inspect_repository,
    main as quality_main,
    migration_source_errors,
    validate as _validate,
)
from gravity_insight.governance.privacy_consistency import (
    exposed_field_names,
    inspect_privacy_classification_consistency,
)
from tests.repository_tree_gate import repository_tree_read


ROOT = Path(__file__).resolve().parents[1]


_RepositoryInputKey = tuple[Path, tuple[tuple[str, str], ...]]
_REPOSITORY_PROFILE_CACHE: dict[_RepositoryInputKey, QualityProfile] = {}


def _repository_input_key(root: Path) -> _RepositoryInputKey:
    resolved = root.resolve()
    inputs: list[tuple[str, str]] = []
    for path in sorted((resolved / "src").rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        inputs.append(
            (
                path.relative_to(resolved).as_posix(),
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        )
    return resolved, tuple(inputs)


def _repository_profile(root: Path = ROOT, *, fresh: bool = False) -> QualityProfile:
    resolved = root.resolve()
    with repository_tree_read(
        root=resolved,
        purpose="quality repository profile scan",
    ):
        if fresh or resolved != ROOT.resolve():
            return _inspect_repository(resolved)
        key = _repository_input_key(resolved)
        profile = _REPOSITORY_PROFILE_CACHE.get(key)
        if profile is None:
            profile = _inspect_repository(resolved)
            _REPOSITORY_PROFILE_CACHE[key] = profile
        return profile


def _validate_repository(
    root: Path, *, base_ref: str | None = None
) -> list[str]:
    resolved = root.resolve()
    if resolved != ROOT.resolve():
        return _validate(resolved, base_ref=base_ref)
    profile = _repository_profile(resolved)
    with mock.patch("gravity_insight.quality.inspect_repository", return_value=profile):
        return _validate(resolved, base_ref=base_ref)


def _profile(
    *,
    file_sloc: int = FILE_SLOC_LIMIT,
    ast_nodes: int = 100,
    file_lines: int | None = None,
    function_sloc: int = FUNCTION_SLOC_LIMIT,
    complexity: int = COMPLEXITY_LIMIT,
    literals: int = 0,
) -> QualityProfile:
    occurrences = tuple(
        LiteralOccurrence("src/gravity_insight/sample.py", line + 1, "app.list")
        for line in range(literals)
    )
    return QualityProfile(
        file_sloc={"src/gravity_insight/sample.py": file_sloc},
        file_ast_nodes={"src/gravity_insight/sample.py": ast_nodes},
        file_lines={"src/gravity_insight/sample.py": file_lines or file_sloc},
        functions=(
            FunctionMetric(
                "src/gravity_insight/sample.py",
                "sample",
                1,
                function_sloc,
                complexity,
            ),
        ),
        operation_literals=occurrences,
        operation_ids=("app.list",),
        src_python_sloc=file_sloc,
        provenance_covered=1,
        compiler_check="PASS",
    )


class GravityInsightQualityTests(unittest.TestCase):
    def test_exit_code_guard_rejects_direct_and_local_classifier_literals(self) -> None:
        source = '''
def product_result(truncated):
    return {"exit_code": 3 if truncated else 0}

def _component_exit_code(error):
    return {"caller": 2, "upstream": 3, "local": 4}[error["category"]]
'''
        errors = hardcoded_exit_code_errors("src/gravity_insight/sample.py", source, ast.parse(source))
        self.assertEqual(2, len(errors), errors)
        self.assertTrue(all("shared error classification" in item for item in errors))

    def test_exit_code_guard_accepts_shared_classification_and_success_zero(self) -> None:
        source = '''
def product_result(detail):
    return {"exit_code": exit_code_for_error(detail)}

def success_result():
    return {"exit_code": 0}
'''
        self.assertEqual(
            [],
            hardcoded_exit_code_errors("src/gravity_insight/sample.py", source, ast.parse(source)),
        )

    def test_exit_code_guard_requires_an_exemption_reason(self) -> None:
        allowed = '''
def capability_gap():
    # exit-code-guard: allow - caller selection status has no ErrorDetail
    return {"exit_code": 2}
'''
        missing_reason = allowed.replace(
            "allow - caller selection status has no ErrorDetail", "allow - "
        )
        self.assertEqual(
            [], hardcoded_exit_code_errors("sample.py", allowed, ast.parse(allowed))
        )
        self.assertIn(
            "requires a reason",
            hardcoded_exit_code_errors(
                "sample.py", missing_reason, ast.parse(missing_reason)
            )[0],
        )

    def test_privacy_consistency_covers_full_exposure_matrix(self) -> None:
        self.assertIn("value", exposed_field_names({"numeric_paths": ["list.[].value"]}))
        self.assertEqual(
            {"common", "name"},
            exposed_field_names(
                {"data_path_item_keys": {"properties.common": ["name"]}}
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            operations = root / "src/gravity_insight/contracts/operations"
            drafts = root / "src/gravity_insight/contracts/drafts"
            operations.mkdir(parents=True)
            drafts.mkdir(parents=True)
            stable = {
                "operation": {
                    "operation_id": "stable.example",
                    "stability": "stable",
                    "response_projection": {
                        "item_keys": ["allowed", "opaque", "order"],
                        "numeric_paths": ["list.[].value"],
                    },
                    "privacy_policy": {
                        "redact_fields": ["secret", "target", "undecided"]
                    },
                }
            }
            draft = {
                "operation": {"operation_id": "draft.example"},
                "draft": {
                    "candidate_fields": [
                        {
                            "path": "data.list[].value",
                            "privacy_classification": "manual_review",
                        },
                        {
                            "path": "data.list[].target",
                            "privacy_classification": "non_sensitive",
                        },
                        {
                            "path": "data.list[].order",
                            "privacy_classification": "sensitive",
                        },
                        {
                            "path": "data.list[].allowed",
                            "privacy_classification": "non_sensitive",
                        },
                        {
                            "path": "data.list[].undecided",
                            "privacy_classification": "manual_review",
                        },
                        {
                            "path": "data.list[].secret",
                            "privacy_classification": "sensitive",
                        },
                        {
                            "path": "data.list[].opaque",
                            "types": ["unknown"],
                            "privacy_classification": "manual_review",
                            "classification_reason": "frontend_static_consumer_unreviewed",
                            "expose": False,
                        },
                    ]
                },
            }
            (operations / "stable.example.json").write_text(
                json.dumps(stable), encoding="utf-8"
            )
            draft_path = drafts / "draft.example.json"
            draft_path.write_text(json.dumps(draft), encoding="utf-8")

            before = inspect_privacy_classification_consistency(root)
            self.assertTrue(any("field 'target' is redacted" in item for item in before))
            self.assertFalse(any("field 'value' is exposed" in item for item in before))
            self.assertFalse(any("field 'order' is exposed" in item for item in before))
            self.assertFalse(any("field 'allowed'" in item for item in before))
            self.assertFalse(any("field 'undecided'" in item for item in before))
            self.assertFalse(any("field 'secret'" in item for item in before))
            self.assertFalse(any("field 'opaque'" in item for item in before))

            draft["draft"]["candidate_fields"][0][
                "privacy_classification"
            ] = "non_sensitive"
            draft["draft"]["candidate_fields"][1][
                "privacy_classification"
            ] = "sensitive"
            draft["draft"]["candidate_fields"][2][
                "privacy_classification"
            ] = "non_sensitive"
            draft_path.write_text(json.dumps(draft), encoding="utf-8")
            self.assertEqual([], inspect_privacy_classification_consistency(root))

    def test_privacy_consistency_does_not_treat_draft_labels_as_access_control(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            operations = root / "src/gravity_insight/contracts/operations"
            drafts = root / "src/gravity_insight/contracts/drafts"
            operations.mkdir(parents=True)
            drafts.mkdir(parents=True)
            (operations / "stable.report.list.json").write_text(
                json.dumps(
                    {
                        "operation": {
                            "operation_id": "stable.report.list",
                            "stability": "stable",
                            "response_projection": {"item_keys": ["remark"]},
                        }
                    }
                ),
                encoding="utf-8",
            )
            (drafts / "draft.report.list.json").write_text(
                json.dumps(
                    {
                        "operation": {"operation_id": "draft.report.list"},
                        "draft": {
                            "candidate_fields": [
                                {
                                    "path": "data.list[].remark",
                                    "types": ["string"],
                                    "privacy_classification": "sensitive",
                                    "classification_reason": "free_text_field_review",
                                    "expose": False,
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual([], inspect_privacy_classification_consistency(root))

    def test_privacy_consistency_ignores_non_stable_operations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            operations = root / "src/gravity_insight/contracts/operations"
            drafts = root / "src/gravity_insight/contracts/drafts"
            operations.mkdir(parents=True)
            drafts.mkdir(parents=True)
            (operations / "experimental.example.json").write_text(
                json.dumps(
                    {
                        "operation": {
                            "operation_id": "experimental.example",
                            "stability": "experimental",
                            "response_projection": {"item_keys": ["private_value"]},
                            "privacy_policy": {"redact_fields": []},
                        }
                    }
                ),
                encoding="utf-8",
            )
            (drafts / "draft.example.json").write_text(
                json.dumps(
                    {
                        "operation": {"operation_id": "draft.example"},
                        "draft": {
                            "candidate_fields": [
                                {
                                    "path": "data.list[].private_value",
                                    "privacy_classification": "sensitive",
                                }
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            self.assertEqual([], inspect_privacy_classification_consistency(root))

    def test_sloc_ignores_blank_and_comment_only_lines(self) -> None:
        source = """# comment

def sample(value):
    # another comment
    return (
        value
        + 1
    )
"""
        self.assertEqual(5, count_sloc(source))

    def test_complexity_counts_decisions_but_not_nested_function(self) -> None:
        tree = ast.parse(
            """def sample(a, b):
    if a and b:
        return [item for item in a if item]
    def nested():
        if a:
            return a
    return None
""",
            feature_version=(3, 11),
        )
        self.assertEqual(5, cyclomatic_complexity(tree.body[0]))

    def test_ratchet_accepts_exact_debt_and_rejects_growth(self) -> None:
        baseline_profile = _profile(file_sloc=550, function_sloc=90, complexity=18, literals=2)
        baseline = debt_snapshot(baseline_profile)
        self.assertEqual([], evaluate_ratchet(baseline_profile, baseline))

        errors = evaluate_ratchet(
            _profile(file_sloc=551, function_sloc=91, complexity=19, literals=3), baseline
        )
        self.assertTrue(any("file SLOC current=551" in error for error in errors), errors)
        self.assertTrue(any("function SLOC current=91" in error for error in errors), errors)
        self.assertTrue(any("cyclomatic complexity current=19" in error for error in errors), errors)
        self.assertTrue(any("operation ID literal count current=3" in error for error in errors), errors)

    def test_new_debt_is_rejected_at_absolute_thresholds(self) -> None:
        baseline = debt_snapshot(_profile())
        errors = evaluate_ratchet(
            _profile(file_sloc=501, function_sloc=81, complexity=16, literals=1), baseline
        )
        self.assertTrue(any("file SLOC current=501, threshold=500" in item for item in errors))
        self.assertTrue(any("function SLOC current=81, threshold=80" in item for item in errors))
        self.assertTrue(any("cyclomatic complexity current=16, threshold=15" in item for item in errors))
        self.assertTrue(any("operation ID literal count current=1, threshold=0" in item for item in errors))

    def test_ast_improvement_requires_baseline_tightening(self) -> None:
        baseline = debt_snapshot(_profile(file_sloc=550, ast_nodes=100))
        errors = evaluate_ratchet(_profile(file_sloc=540, ast_nodes=99), baseline)
        self.assertTrue(any("AST nodes improved current=99" in error for error in errors), errors)

    def test_base_baseline_cannot_be_relaxed_or_gain_debt(self) -> None:
        base = debt_snapshot(_profile(file_sloc=550))
        relaxed = debt_snapshot(_profile(file_sloc=551, literals=1))
        errors = compare_baselines(relaxed, base)
        self.assertTrue(any("immutable sloc_hard_limit relaxation rejected" in item for item in errors))
        self.assertTrue(any("baseline relaxation rejected for operation ID" in item for item in errors))

    def test_semicolon_packing_has_no_ast_ratchet_benefit(self) -> None:
        expanded = "first = 1\nsecond = 2\n"
        packed = "first = 1; second = 2\n"
        self.assertEqual(2, count_sloc(expanded))
        self.assertEqual(1, count_sloc(packed))
        self.assertEqual(count_ast_nodes(expanded), count_ast_nodes(packed))
        baseline = debt_snapshot(
            _profile(file_sloc=550, ast_nodes=count_ast_nodes(expanded))
        )
        packed_profile = _profile(file_sloc=550, ast_nodes=count_ast_nodes(packed))
        self.assertEqual([], evaluate_ratchet(packed_profile, baseline))

    def test_fifty_added_code_lines_exceed_legacy_ast_hard_limit(self) -> None:
        original = "value = 0\n"
        added = original + "".join(f"value_{index} = {index}\n" for index in range(50))
        baseline = debt_snapshot(
            _profile(
                file_sloc=550,
                file_lines=600,
                ast_nodes=count_ast_nodes(original),
            )
        )
        errors = evaluate_ratchet(
            _profile(
                file_sloc=600,
                file_lines=600,
                ast_nodes=count_ast_nodes(added),
            ),
            baseline,
        )
        self.assertTrue(any("AST nodes current=" in item and "hard limit=" in item for item in errors))

    def test_ast_improvement_cannot_rebound_with_a_growth_reason(self) -> None:
        path = "src/gravity_insight/sample.py"
        base_profile = _profile(file_sloc=550, ast_nodes=100)
        base = debt_snapshot(base_profile)
        improved = debt_snapshot(_profile(file_sloc=550, ast_nodes=60), base)
        self.assertEqual(60, improved["legacy_files"][path]["ast_hard_limit"])
        self.assertEqual([], compare_baselines(improved, base))

        with self.assertRaisesRegex(ValueError, "AST growth reasons are no longer supported"):
            debt_snapshot(
                _profile(file_sloc=550, ast_nodes=140),
                improved,
                {path: "rebound inside the old hard limit"},
            )
        with self.assertRaisesRegex(ValueError, "AST nodes exceed"):
            debt_snapshot(_profile(file_sloc=550, ast_nodes=140), improved)

    def test_sloc_hard_limit_uses_sloc_and_tightens_after_improvement(self) -> None:
        path = "src/gravity_insight/sample.py"
        base = debt_snapshot(_profile(file_sloc=550, file_lines=600))
        self.assertEqual(550, base["legacy_files"][path]["sloc_hard_limit"])

        improved = debt_snapshot(_profile(file_sloc=525, file_lines=600), base)
        self.assertEqual(525, improved["legacy_files"][path]["sloc_hard_limit"])
        self.assertEqual([], compare_baselines(improved, base))
        with self.assertRaisesRegex(ValueError, "SLOC exceeds"):
            debt_snapshot(_profile(file_sloc=526, file_lines=600), improved)

    def test_v2_migration_replaces_physical_limit_with_current_sloc(self) -> None:
        path = "src/gravity_insight/sample.py"
        v2 = debt_snapshot(_profile(file_sloc=550, file_lines=600, ast_nodes=100))
        v2["baseline_version"] = 2
        v2["legacy_files"][path].update(
            ast_hard_limit=150,
            sloc_hard_limit=600,
        )

        migrated = debt_snapshot(_profile(file_sloc=550, file_lines=600, ast_nodes=90), v2)
        entry = migrated["legacy_files"][path]
        self.assertEqual(550, entry["sloc_hard_limit"])
        self.assertEqual(90, entry["ast_hard_limit"])
        self.assertEqual([], compare_baselines(migrated, v2))

    def test_v3_historical_growth_ledger_is_immutable(self) -> None:
        base = debt_snapshot(_profile(file_sloc=550, ast_nodes=100))
        proposed = json.loads(json.dumps(base))
        proposed["growth_ledger"].append(
            {
                "path": "src/gravity_insight/sample.py",
                "from": 100,
                "to": 101,
                "reason": "attempted rebound",
            }
        )
        errors = compare_baselines(proposed, base)
        self.assertTrue(any("historical growth ledger is immutable" in item for item in errors))

    def test_migration_hard_limits_are_derived_from_base_source(self) -> None:
        path = "src/gravity_insight/sample.py"
        source = "# formatting reserve\n" * 50 + "value = 1\n" * 550
        baseline = debt_snapshot(
            _profile(
                file_sloc=550,
                file_lines=600,
                ast_nodes=count_ast_nodes(source),
            )
        )
        self.assertEqual([], migration_source_errors(baseline, {path: source}))
        baseline["legacy_files"][path]["sloc_hard_limit"] += 1
        self.assertTrue(migration_source_errors(baseline, {path: source}))

    def test_green_cli_output_reports_outstanding_debt(self) -> None:
        profile = _profile(file_sloc=550, function_sloc=90, complexity=18, literals=2)
        output = io.StringIO()
        with (
            mock.patch("gravity_insight.quality.validate", return_value=[]),
            mock.patch("gravity_insight.quality.inspect_repository", return_value=profile),
            redirect_stdout(output),
        ):
            exit_code = quality_main(["--root", str(ROOT), "check"])
        self.assertEqual(0, exit_code)
        self.assertIn(
            "debt_files=1 (+50 SLOC), debt_functions=1 (+10 SLOC), "
            "debt_complexity=1 (+3), debt_operation_literals=2",
            output.getvalue(),
        )

    def test_contract_expansion_requires_zero_src_python_slope(self) -> None:
        profile = replace(
            _profile(),
            operation_ids=("app.list", "analysis.event.list"),
            src_python_sloc=101,
            provenance_covered=2,
        )
        with mock.patch(
            "gravity_insight.quality._base_quality_snapshot",
            return_value=({"app.list"}, 100),
        ):
            errors = evaluate_slope(profile, ROOT, "base")
            self.assertTrue(any("src_python_sloc_delta=1" in item for item in errors), errors)
            self.assertEqual([], evaluate_slope(replace(profile, src_python_sloc=100), ROOT, "base"))

    def test_repository_quality_source_parses_as_python_311(self) -> None:
        source = (ROOT / "src/gravity_insight/quality.py").read_text(encoding="utf-8")
        ast.parse(source, filename="quality.py", feature_version=(3, 11))

    @pytest.mark.full_gate
    def test_repository_gate_passes_checked_in_baseline(self) -> None:
        errors = _validate_repository(ROOT, base_ref=None)
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
