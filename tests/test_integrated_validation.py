from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_installed_wheel_consumer import (
    STRICT_PREREQUISITES_ENV,
    ConsumerCheckError,
    _project_consumer_tests,
    _require_revision_on_main,
    _resolve_consumer_revision,
    check_installed_wheel_consumer,
    run_consumer_gate,
)
from scripts.run_integrated_validation import (
    POST_RELEASE_GATES,
    GateSpec,
    _display_path,
    _summary,
    gate_specs,
    integrated_green,
    run_gate,
    summarize_gate_results,
)


ROOT = Path(__file__).resolve().parents[1]


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(arguments)} failed: {result.stdout}\n{result.stderr}"
        )
    return result.stdout.strip()


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", ".")
    _git(
        repository,
        "-c",
        "user.name=Consumer Guard Test",
        "-c",
        "user.email=consumer-guard@example.invalid",
        "commit",
        "--quiet",
        "--allow-empty",
        "-m",
        message,
    )
    return _git(repository, "rev-parse", "HEAD")


def _repository(root: Path, initial_branch: str = "main") -> tuple[Path, str]:
    repository = root / "consumer"
    repository.mkdir()
    _git(repository, "init", "--quiet", "--initial-branch", initial_branch)
    (repository / "README.md").write_text("consumer fixture\n", encoding="utf-8")
    return repository, _commit(repository, "initial consumer")


class InstalledWheelConsumerGuardTests(unittest.TestCase):
    def test_missing_consumer_directory_is_an_explicit_skip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            missing = Path(raw) / "missing-consumer"

            result = run_consumer_gate(
                missing, "missing-revision", strict_prerequisites=False
            )

        self.assertEqual("skipped", result["status"])
        self.assertFalse(result["passed"])
        self.assertEqual(0, result["exit_code"])
        self.assertEqual("consumer_repository_missing", result["reason_code"])
        self.assertIn(str(missing.resolve()), result["reason"])

    def test_existing_non_git_consumer_directory_is_an_explicit_skip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repository = Path(raw) / "consumer"
            repository.mkdir()

            result = run_consumer_gate(
                repository, "missing-revision", strict_prerequisites=False
            )

        self.assertEqual("skipped", result["status"])
        self.assertFalse(result["passed"])
        self.assertEqual("consumer_repository_not_git", result["reason_code"])

    def test_missing_consumer_revision_is_an_explicit_skip(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repository, _ = _repository(Path(raw))

            result = run_consumer_gate(
                repository, "f" * 40, strict_prerequisites=False
            )

        self.assertEqual("skipped", result["status"])
        self.assertFalse(result["passed"])
        self.assertEqual(0, result["exit_code"])
        self.assertEqual("consumer_revision_unavailable", result["reason_code"])
        self.assertIn("f" * 40, result["reason"])

    def test_strict_environment_turns_prerequisite_skip_into_failure(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch.dict(
            os.environ, {STRICT_PREREQUISITES_ENV: "1"}
        ):
            result = run_consumer_gate(Path(raw) / "missing", "missing-revision")

        self.assertEqual("fail", result["status"])
        self.assertFalse(result["passed"])
        self.assertEqual(2, result["exit_code"])
        self.assertTrue(result["strict_prerequisites"])
        self.assertEqual("consumer_repository_missing", result["reason_code"])

    def test_a_non_canonical_consumer_path_still_resolves_to_the_repository_root(
        self,
    ) -> None:
        # git reports the canonical root, so an uncanonicalised caller path must
        # be resolved before the two are compared. On a CI runner the temporary
        # directory arrives as a Windows 8.3 short name (C:\Users\RUNNER~1\...)
        # while git reports the long form; a detour through "..", which pathlib
        # also leaves unresolved, reproduces that asymmetry portably.
        with tempfile.TemporaryDirectory() as raw:
            repository, pinned = _repository(Path(raw))
            detoured = repository.parent / repository.name / ".." / repository.name

            self.assertNotEqual(repository, detoured)
            self.assertEqual(pinned, _resolve_consumer_revision(detoured, pinned))

    def test_available_prerequisites_execute_the_existing_consumer_check(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repository, pinned = _repository(Path(raw))
            self.assertEqual(pinned, _resolve_consumer_revision(repository, pinned))
            check_result = {
                "schema_version": "gravity.installed-wheel-consumer-check.v2",
                "passed": True,
                "exit_code": 0,
                "consumer_commit": pinned,
                "summary": {"tests_run": 2, "skipped": 0, "ok": True},
                "network_calls": 0,
            }
            with patch(
                "scripts.check_installed_wheel_consumer.check_installed_wheel_consumer",
                return_value=check_result,
            ) as consumer_check:
                result = run_consumer_gate(
                    repository, pinned, strict_prerequisites=False
                )

        consumer_check.assert_called_once_with(repository, pinned)
        self.assertEqual("pass", result["status"])
        self.assertTrue(result["passed"])
        self.assertEqual(0, result["exit_code"])
        self.assertIs(check_result, result["check"])

    def test_historical_consumer_tests_use_exact_package_root_projection(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tests = root / "tests"
            tests.mkdir()
            adoption = tests / "test_gravity_sdk_adoption.py"
            adoption.write_text(
                "WORK_DASHBOARD_GRAVITY_SDK_ROOT\n"
                "WORK_DASHBOARD_GRAVITY_SDK_ROOT\n"
                'ROOT.parent / "gravity-sdk"\n'
                "gravity-sdk sibling checkout or gravity executable is unavailable\n"
                "gravity_sdk gravity_sdk gravity_sdk gravity_sdk\n",
                encoding="utf-8",
            )
            r01 = tests / "test_r01_reference_journey_consumer.py"
            r01.write_text(
                "WORK_DASHBOARD_GRAVITY_SDK_ROOT\n"
                'ROOT.parent / "gravity-sdk"\n'
                "gravity-sdk source checkout is unavailable\n"
                "gravity_sdk\n",
                encoding="utf-8",
            )

            receipts = _project_consumer_tests(root, "fixture-commit")

            projected = tests / "test_gravity_insight_adoption.py"
            self.assertFalse(adoption.exists())
            self.assertTrue(projected.is_file())
            self.assertEqual(2, len(receipts))
            self.assertTrue(
                all(item["mode"] == "exact_package_root_projection" for item in receipts)
            )
            for path in (projected, r01):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("gravity_sdk", text)
                self.assertNotIn("WORK_DASHBOARD_GRAVITY_SDK_ROOT", text)

    def test_historical_consumer_projection_rejects_source_shape_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            tests = root / "tests"
            tests.mkdir()
            (tests / "test_gravity_sdk_adoption.py").write_text(
                "gravity_sdk\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ConsumerCheckError, "projection precondition drifted"
            ):
                _project_consumer_tests(root, "fixture-commit")

    def test_pinned_revision_on_main_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repository, commit = _repository(Path(raw))

            main_tip = _require_revision_on_main(repository, commit)

            self.assertEqual(commit, main_tip)

    def test_pinned_revision_on_unmerged_branch_is_rejected_before_fetch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repository, main_tip = _repository(Path(raw))
            _git(repository, "switch", "--quiet", "-c", "unmerged-consumer")
            (repository / "branch-only.txt").write_text("not merged\n", encoding="utf-8")
            pinned = _commit(repository, "unmerged consumer change")
            _git(repository, "switch", "--quiet", "main")

            with self.assertRaises(ConsumerCheckError) as caught:
                check_installed_wheel_consumer(repository, pinned)

            message = str(caught.exception)
            self.assertIn(pinned, message)
            self.assertIn("containing_branches=unmerged-consumer", message)
            self.assertIn(f"main_tip={main_tip}", message)

            gate_result = run_consumer_gate(
                repository, pinned, strict_prerequisites=False
            )
            self.assertEqual("fail", gate_result["status"])
            self.assertEqual("consumer_check_failed", gate_result["reason_code"])
            self.assertIn("revision is not on main", gate_result["reason"])

    def test_consumer_repository_without_main_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repository, pinned = _repository(Path(raw), initial_branch="trunk")

            with self.assertRaises(ConsumerCheckError) as caught:
                check_installed_wheel_consumer(repository, pinned)

            message = str(caught.exception)
            self.assertIn("main branch is unavailable", message)
            self.assertIn(pinned, message)
            self.assertIn("main_tip=<unavailable>", message)

    def test_missing_consumer_test_module_is_reported_before_tests_run(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            repository, _ = _repository(Path(raw))
            tests = repository / "tests"
            tests.mkdir()
            (tests / "test_gravity_insight_adoption.py").write_text(
                "import unittest\n\nclass AdoptionTests(unittest.TestCase):\n    pass\n",
                encoding="utf-8",
            )
            pinned = _commit(repository, "add incomplete consumer tests")

            with self.assertRaises(ConsumerCheckError) as caught:
                check_installed_wheel_consumer(repository, pinned)

            message = str(caught.exception)
            self.assertIn(pinned, message)
            self.assertIn("tests.test_r01_reference_journey_consumer", message)
            self.assertIn("tests/test_r01_reference_journey_consumer.py", message)


class IntegratedValidationTests(unittest.TestCase):
    def test_structured_skip_remains_distinct_in_gate_and_report(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as raw:
            logs = Path(raw)
            payload = {
                "schema_version": "gravity.installed-wheel-consumer-gate.v1",
                "status": "skipped",
                "passed": False,
                "exit_code": 0,
                "reason_code": "consumer_repository_missing",
                "reason": "canonical consumer repository directory is unavailable",
            }
            gate = GateSpec(
                "installed_wheel_canonical_consumer",
                (sys.executable, "-c", f"import json; print(json.dumps({payload!r}))"),
            )

            result = run_gate(gate, logs, os.environ)

        self.assertEqual("skipped", result["status"])
        self.assertFalse(result["passed"])
        report = summarize_gate_results(
            [
                {"name": "ordinary", "status": "pass"},
                result,
            ]
        )
        self.assertEqual({"pass": 1, "skipped": 1, "fail": 0}, report["gate_status_counts"])
        self.assertEqual([], report["failed_gates"])
        self.assertEqual(
            "consumer_repository_missing",
            report["skipped_gates"][0]["reason_code"],
        )

    def test_relative_custom_receipt_path_is_reported_from_root(self) -> None:
        self.assertEqual(
            "tmp/custom-receipt.json",
            _display_path(Path("tmp/custom-receipt.json")),
        )

    def test_absolute_custom_receipt_path_inside_root_is_reported_from_root(self) -> None:
        receipt_path = (ROOT / "tmp/custom-receipt.json").resolve()

        self.assertEqual("tmp/custom-receipt.json", _display_path(receipt_path))

    def test_custom_receipt_path_outside_root_is_reported_as_absolute(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            receipt_path = (Path(raw) / "receipt.json").resolve()

            self.assertEqual(receipt_path.as_posix(), _display_path(receipt_path))

    def test_gate_inventory_matches_canonical_governance(self) -> None:
        gates = gate_specs(ROOT / ".venv/Scripts/python.exe", ROOT / "tmp/test")
        names = [gate.name for gate in gates]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue(
            {
                "unittest_collector",
                "pytest_collector",
                "compiler_check",
                "quality_check",
                "runtime_component_index",
                "repository_map",
                "package_reference_checkpoint",
                "release_provenance_offline_fixture",
            }.issubset(names)
        )
        self.assertLess(names.index("repository_map"), names.index("package_reference_checkpoint"))

    def test_green_requires_clean_main_same_head_complete_zero_exit_set(self) -> None:
        before = {
            "branch_is_main": True,
            "clean": True,
            "independent_venv": True,
            "head": "a" * 40,
        }
        after = {"clean": True, "head": "a" * 40}
        gates = [{"exit_code": 0}, {"exit_code": 0}]
        self.assertTrue(
            integrated_green(before, after, gates, complete_gate_set=True)
        )
        for changed in (
            {"before": {**before, "branch_is_main": False}},
            {"before": {**before, "clean": False}},
            {"before": {**before, "independent_venv": False}},
            {"after": {**after, "clean": False}},
            {"after": {**after, "head": "b" * 40}},
            {"gates": [{"exit_code": 1}]},
            {"gates": [{"exit_code": 0, "status": "fail"}]},
            {"complete_gate_set": False},
        ):
            with self.subTest(changed=changed):
                self.assertFalse(
                    integrated_green(
                        changed.get("before", before),
                        changed.get("after", after),
                        changed.get("gates", gates),
                        complete_gate_set=changed.get("complete_gate_set", True),
                    )
                )

        skipped_gate = {
            "name": "installed_wheel_canonical_consumer",
            "exit_code": 0,
            "status": "skipped",
            "passed": False,
            "reason": "consumer repository missing",
        }
        self.assertTrue(
            integrated_green(before, after, [skipped_gate], complete_gate_set=True)
        )

    def test_live_pypi_provenance_is_only_a_post_release_exclusion(self) -> None:
        names = [
            gate.name
            for gate in gate_specs(
                ROOT / ".venv/Scripts/python.exe", ROOT / "tmp/test"
            )
        ]
        self.assertEqual("release_provenance_live_pypi", POST_RELEASE_GATES[0]["name"])
        self.assertEqual(
            ["release_provenance_live_pypi"],
            [item["name"] for item in POST_RELEASE_GATES],
        )
        self.assertNotIn("release_provenance_live_pypi", names)
        self.assertIn("release_provenance_offline_fixture", names)

    def test_log_summary_preserves_required_gate_numbers(self) -> None:
        output = "\n".join(
            [
                "2016 passed, 4754 subtests passed in 1.0s",
                "check: 237 operations, 11 manifests",
                "PASS gravity-insight-quality: debt_files=13, debt_functions=4, debt_complexity=12, debt_operation_literals=9",
                "- Cases: 336",
                "Security compliance hard gate: PASS (violations: 0)",
                "Production HTTP requests: 0",
            ]
        )
        summary = _summary(output)
        self.assertEqual((2016, 4754), (summary["passed"], summary["subtests_passed"]))
        self.assertEqual((237, 11), (summary["operations"], summary["manifests"]))
        self.assertEqual(
            {"files": 13, "functions": 4, "complexity": 12, "operation_literals": 9},
            summary["quality_debt"],
        )
        self.assertEqual((336, "PASS", 0), (
            summary["usability_cases"],
            summary["security_gate"],
            summary["production_http_requests"],
        ))


if __name__ == "__main__":
    unittest.main()
