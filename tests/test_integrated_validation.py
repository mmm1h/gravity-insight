from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.check_installed_wheel_consumer import (
    ConsumerCheckError,
    _require_revision_on_main,
    check_installed_wheel_consumer,
)
from scripts.run_integrated_validation import (
    POST_RELEASE_GATES,
    _display_path,
    _summary,
    gate_specs,
    integrated_green,
)


ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "specs/agent-runtime/index.json"


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
        contract = json.loads(INDEX.read_text(encoding="utf-8"))[
            "integrated_validation"
        ]
        gates = gate_specs(ROOT / ".venv/Scripts/python.exe", ROOT / "tmp/test")
        names = [gate.name for gate in gates]
        self.assertEqual(contract["included_gates"], names)
        self.assertEqual(len(names), len(set(names)))

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

    def test_live_pypi_provenance_is_only_a_post_release_exclusion(self) -> None:
        contract = json.loads(INDEX.read_text(encoding="utf-8"))[
            "integrated_validation"
        ]
        self.assertEqual("release_provenance_live_pypi", POST_RELEASE_GATES[0]["name"])
        self.assertEqual(
            ["release_provenance_live_pypi"],
            [item["name"] for item in contract["excluded_post_release_gates"]],
        )
        self.assertIn("release_provenance_offline_fixture", contract["included_gates"])

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
