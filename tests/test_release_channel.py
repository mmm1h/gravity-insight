from __future__ import annotations

import base64
import copy
import json
import re
import subprocess
import sys
import tempfile
import tomllib
import unittest
from importlib import metadata
from pathlib import Path

import gravity_insight
from gravity_insight.auto_upgrade import AUTO_UPGRADE_ENV, startup_update_enabled
from scripts.verify_release_provenance import (
    Distribution,
    MAX_ATTEMPTS,
    PUBLISH_PREDICATE_TYPE,
    RETRY_DELAY_SECONDS,
    ProvenanceVerificationError,
    ReleaseRecoveryError,
    local_release_assets,
    plan_pypi_publish,
    sync_github_release,
    validate_release_provenance,
    verify_checked_out_tag,
    verify_pypi_release,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
TAG_GATE = ROOT / "scripts" / "check_release_tag.py"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
PROVENANCE_FIXTURES = ROOT / "tests" / "fixtures" / "release_provenance"


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, text=True, encoding="utf-8", capture_output=True, check=False
    )


def _workflow_action_uses(workflow: str) -> list[str]:
    return re.findall(
        r"(?m)^\s+(?:-\s+)?uses:\s*([^\s#]+)\s*(?:#.*)?$", workflow
    )


def _unpinned_action_uses(workflow: str) -> list[str]:
    return [
        value
        for value in _workflow_action_uses(workflow)
        if re.fullmatch(r"[^@]+@[0-9a-f]{40}", value) is None
    ]


class ReleaseVersionTests(unittest.TestCase):
    def test_project_import_and_distribution_versions_are_identical(self) -> None:
        project_version = PROJECT["project"]["version"]
        self.assertEqual(project_version, gravity_insight.__version__)
        self.assertEqual(project_version, metadata.version("gravity-insight"))

    def test_uninstalled_source_checkout_derives_version_from_pyproject(self) -> None:
        probe = (
            "import sys; "
            f"sys.path.insert(0, {str(ROOT / 'src')!r}); "
            "import gravity_insight; print(gravity_insight.__version__)"
        )
        completed = _run([sys.executable, "-S", "-c", probe], cwd=ROOT.parent)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertEqual(PROJECT["project"]["version"], completed.stdout.strip())


class ReleaseTagGateTests(unittest.TestCase):
    def _repository(self, root: Path) -> Path:
        repository = root / "repository"
        repository.mkdir()
        for command in (
            ["git", "init", "--quiet"],
            ["git", "config", "user.name", "Gravity Insight Tests"],
            ["git", "config", "user.email", "gravity-insight-tests@example.invalid"],
            ["git", "commit", "--allow-empty", "--quiet", "-m", "initial"],
        ):
            completed = _run(command, cwd=repository)
            self.assertEqual(0, completed.returncode, completed.stderr)
        return repository

    def _gate(self, repository: Path) -> subprocess.CompletedProcess[str]:
        return _run(
            [sys.executable, str(TAG_GATE), "--repository", str(repository)],
            cwd=ROOT,
        )

    def test_untagged_head_passes_when_version_tag_does_not_exist(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gravity-release-tag-") as raw:
            completed = self._gate(self._repository(Path(raw)))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("does not exist locally", completed.stdout)

    def test_untagged_head_fails_when_version_tag_points_to_earlier_commit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="gravity-release-tag-") as raw:
            repository = self._repository(Path(raw))
            tag = f"v{PROJECT['project']['version']}"
            tagged = _run(
                ["git", "tag", "-a", tag, "-m", "released"], cwd=repository
            )
            self.assertEqual(0, tagged.returncode, tagged.stderr)
            advanced = _run(
                ["git", "commit", "--allow-empty", "--quiet", "-m", "development"],
                cwd=repository,
            )
            self.assertEqual(0, advanced.returncode, advanced.stderr)
            completed = self._gate(repository)
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn(f"{tag} points to", completed.stdout)
        self.assertIn("already occupied by a different commit", completed.stdout)

    def test_matching_version_tag_passes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gravity-release-tag-") as raw:
            repository = self._repository(Path(raw))
            tag = f"v{PROJECT['project']['version']}"
            tagged = _run(["git", "tag", tag], cwd=repository)
            self.assertEqual(0, tagged.returncode, tagged.stderr)
            completed = self._gate(repository)
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn(f"{tag} matches", completed.stdout)

    def test_mismatched_version_tag_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gravity-release-tag-") as raw:
            repository = self._repository(Path(raw))
            tagged = _run(["git", "tag", "v999.0.0"], cwd=repository)
            self.assertEqual(0, tagged.returncode, tagged.stderr)
            completed = self._gate(repository)
        self.assertEqual(1, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("do not match expected", completed.stdout)


class ReleaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflows = {
            path.name: path.read_text(encoding="utf-8")
            for path in (CI_WORKFLOW, RELEASE_WORKFLOW)
        }
        cls.workflow = cls.workflows[RELEASE_WORKFLOW.name]

    def _job(self, name: str) -> str:
        matched = re.search(
            rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)",
            self.workflow,
        )
        self.assertIsNotNone(matched, name)
        return matched.group(0) if matched is not None else ""

    def _step(self, workflow: str, name: str) -> str:
        matched = re.search(
            rf"(?ms)^      - name: {re.escape(name)}\n"
            r".*?(?=^      - |^  [a-z][a-z0-9_-]*:\n|\Z)",
            workflow,
        )
        self.assertIsNotNone(matched, name)
        return matched.group(0) if matched is not None else ""

    def test_every_ci_and_release_action_is_pinned_to_a_full_commit_sha(self) -> None:
        for name, workflow in self.workflows.items():
            with self.subTest(workflow=name):
                self.assertTrue(_workflow_action_uses(workflow))
                self.assertEqual([], _unpinned_action_uses(workflow))

    def test_release_pin_scan_includes_all_named_step_actions(self) -> None:
        indented = re.findall(r"(?m)^\s+uses:\s*([^\s#]+)", self.workflow)
        self.assertEqual(
            [
                "actions/download-artifact",
                "actions/upload-artifact",
                "actions/upload-artifact",
                "actions/download-artifact",
                "actions/download-artifact",
                "actions/upload-artifact",
                "actions/upload-artifact",
                "actions/download-artifact",
                "pypa/gh-action-pypi-publish",
                "actions/download-artifact",
                "actions/download-artifact",
            ],
            [value.rsplit("@", 1)[0] for value in indented],
        )
        scanned = _workflow_action_uses(self.workflow).copy()
        for value in indented:
            self.assertIn(value, scanned)
            scanned.remove(value)

    def test_pin_scan_rejects_floating_tag_in_named_step_action(self) -> None:
        mutated, replacements = re.subn(
            r"(?m)^(\s+uses:\s*pypa/gh-action-pypi-publish)@[^\s]+$",
            r"\1@v1",
            self.workflow,
        )
        self.assertEqual(1, replacements)
        self.assertEqual(
            ["pypa/gh-action-pypi-publish@v1"],
            _unpinned_action_uses(mutated),
        )

    def test_offline_cli_steps_disable_startup_upgrade(self) -> None:
        ci = self.workflows[CI_WORKFLOW.name]
        with self.subTest(workflow=CI_WORKFLOW.name):
            step = self._step(ci, "Check all CLI namespaces offline")
            env_block = re.search(
                r"(?ms)^        env:\n((?:^          .+\n?)*)", step
            )
            self.assertIsNotNone(env_block)
            configured = dict(
                re.findall(
                    r"(?m)^          ([A-Z][A-Z0-9_]*):\s*[\"']?([^\"'\s#]+)",
                    env_block.group(1) if env_block is not None else "",
                )
            )
            self.assertIn(AUTO_UPGRADE_ENV, configured)
            self.assertEqual("0", configured[AUTO_UPGRADE_ENV])
            self.assertFalse(
                startup_update_enabled(
                    ["--help"],
                    environ={AUTO_UPGRADE_ENV: configured[AUTO_UPGRADE_ENV]},
                )
            )
        with self.subTest(workflow=RELEASE_WORKFLOW.name):
            self.assertIn("Require a green exact-SHA SDK CI run", self.workflow)
            self.assertNotIn("Check all CLI namespaces offline", self.workflow)

    def test_exact_sha_ci_reuse_and_supply_chain_are_read_only(self) -> None:
        verify = self._job("verify_ci")
        build = self._job("release_supply_chain")
        for job in (verify, build):
            self.assertIn("contents: read", job)
            self.assertNotIn("contents: write", job)
        self.assertIn("actions: read", verify)
        self.assertNotIn("id-token: write", verify)
        self.assertIn("Require a green exact-SHA SDK CI run", verify)
        self.assertIn("head_sha=\"$GITHUB_SHA\"", verify)
        self.assertIn('expected_event="push"', verify)
        self.assertIn('expected_branch="main"', verify)
        self.assertIn("scripts/check_release_ci.py", verify)
        self.assertIn("--expected-sha \"$GITHUB_SHA\"", verify)
        self.assertIn("--expected-event \"$expected_event\"", verify)
        self.assertIn("--expected-branch \"$expected_branch\"", verify)
        self.assertIn("Require release tag to equal protected main", verify)
        self.assertIn("+refs/heads/main:refs/remotes/origin/main", verify)
        self.assertIn("scripts/check_release_main.py", verify)
        self.assertIn("--main-ref refs/remotes/origin/main", verify)
        self.assertIn('gh api "repos/$GITHUB_REPOSITORY/branches/main"', verify)
        self.assertIn("--branch-metadata \"$RUNNER_TEMP/main-branch.json\"", verify)
        self.assertIn("name: ci-secret-scan", verify)
        self.assertIn("run-id: ${{ steps.ci.outputs.run_id }}", verify)
        self.assertIn('receipt.get("history_included") is True', verify)
        self.assertIn('receipt.get("repository_head") == expected', verify)
        self.assertIn("name: release-secret-scan", verify)
        self.assertIn("name: release-ci-evidence", verify)
        self.assertIn("contents: read", build)
        self.assertIn("needs: verify_ci", build)
        self.assertIn("timeout-minutes: 60", build)
        self.assertIn("fetch-depth: 0", build)
        self.assertIn("name: python-distributions", build)
        self.assertIn("path: dist/", build)
        self.assertIn("name: release-supply-chain", build)
        self.assertIn("path: release-evidence/", build)
        self.assertIn("scripts/generate_release_sbom.py", build)
        self.assertIn("scripts/audit_release_dependencies.py", build)
        self.assertIn("scripts/run_integrated_validation.py", build)
        self.assertIn("--receipt release-evidence/integrated-validation.json", build)
        self.assertIn('git switch --force-create main "$GITHUB_SHA"', build)
        self.assertIn("GRAVITY_REQUIRE_CANONICAL_CONSUMER: \"1\"", build)
        self.assertIn("PYTEST_XDIST_AUTO_NUM_WORKERS: \"4\"", build)
        self.assertIn("scripts/check_installed_wheel_surface_matrix.py", build)
        self.assertIn("scripts/check_installed_wheel_consumer.py", build)
        self.assertIn("--strict-prerequisites", build)
        self.assertIn("scripts/check_changelog.py", build)
        self.assertIn("scripts/build_release_gate_receipt.py", build)
        self.assertIn("--output release-evidence/release-gate.json", build)
        for step_name in (
            "Download exact-SHA release CI evidence",
            "Download exact-SHA secret-history evidence",
            "Prepare exact-main Integrated Validation environment",
            "Run exact-tag Integrated Validation",
            "Check intended wheel surface matrix",
            "Check intended wheel canonical consumer",
            "Check release changelog and migration declaration",
        ):
            self.assertIn("if: github.event_name == 'push'", self._step(build, step_name))
        self.assertIn("if: always()", self._step(build, "Aggregate pre-publish release receipt"))
        publish_index = self.workflow.index("  publish:")
        for fragment in (
            "scripts/generate_release_sbom.py",
            "scripts/audit_release_dependencies.py",
            "Require a green exact-SHA SDK CI run",
            "Validate complete-history secret-scan receipt binding",
        ):
            self.assertLess(self.workflow.index(fragment), publish_index)
        self.assertNotIn("gh release create", verify + build)

    def test_release_workspace_outputs_are_excluded_from_checkpoint_file_universe(
        self,
    ) -> None:
        workflow_outputs = "\n".join(self.workflows.values())
        outputs = (
            (
                "path: release-evidence/secret-scan.json",
                "release-evidence/secret-scan.json",
            ),
            (
                "--output-dir tmp/agent-usability-gate",
                "tmp/agent-usability-gate/probe.json",
            ),
            ("> tmp/agent-usability-gate.log", "tmp/agent-usability-gate.log"),
            ("python -m build", "build/probe"),
            ("path: dist/", "dist/probe"),
            ("--output-dir release-evidence", "release-evidence/probe.cdx.json"),
            (
                "--receipt release-evidence/dependency-audit.json",
                "release-evidence/dependency-audit.json",
            ),
            ("path: tmp/release-input/", "tmp/release-input/probe.json"),
        )
        for workflow_fragment, output in outputs:
            with self.subTest(output=output):
                self.assertIn(workflow_fragment, workflow_outputs)
                ignored = _run(
                    ["git", "check-ignore", "--verbose", "--", output], cwd=ROOT
                )
                self.assertEqual(
                    0,
                    ignored.returncode,
                    f"{output} is a release workspace output but is not ignored; "
                    "it can enter the checkpoint file universe from "
                    "git ls-files --cached --others --exclude-standard",
                )
                self.assertRegex(ignored.stdout, r"^\.gitignore:\d+:")

    def test_oidc_publish_and_provenance_precede_github_release(self) -> None:
        publish = self._job("publish")
        finalize = self._job("finalize_release")
        self.assertIn("needs: [verify_ci, release_supply_chain]", publish)
        self.assertIn("id-token: write", publish)
        self.assertIn("name: python-distributions", publish)
        self.assertIn("scripts/verify_release_provenance.py pypi-plan", publish)
        self.assertIn("upload_required == 'true'", publish)
        self.assertIn("gh-action-pypi-publish@", publish)
        self.assertIn("attestations: true", publish)
        self.assertIn("packages-dir: ${{ runner.temp }}/pypi-upload/", publish)
        self.assertIn("needs: publish", finalize)
        self.assertIn("timeout-minutes: 10", finalize)
        self.assertIn("contents: write", finalize)
        self.assertIn("actions/checkout@", finalize)
        self.assertIn("name: release-supply-chain", finalize)
        self.assertIn("name: release-secret-scan", finalize)
        self.assertIn("path: release-evidence/", finalize)
        provenance = "python scripts/verify_release_provenance.py gravity-insight"
        recovery = "python scripts/verify_release_provenance.py recover"
        self.assertIn(provenance, finalize)
        self.assertIn(recovery, finalize)
        self.assertLess(finalize.index(provenance), finalize.index(recovery))
        self.assertIn("--extra-asset-dir release-evidence", finalize)
        self.assertNotRegex(finalize, r"\b(?:delete|yank)\b")
        self.assertNotIn("gh release create", self.workflow)

    def test_measurement_path_cannot_publish_or_mutate_a_release(self) -> None:
        measurement = self._job("measure_release")
        self.assertIn("if: inputs.measure", measurement)
        self.assertIn("contents: read", measurement)
        self.assertNotIn("contents: write", measurement)
        self.assertNotIn("id-token: write", measurement)
        self.assertNotIn("gh-action-pypi-publish", measurement)
        self.assertIn("scripts/verify_release_provenance.py pypi-plan", measurement)
        self.assertIn("scripts/verify_release_provenance.py recover", measurement)
        self.assertIn("--repository-root release-source", measurement)

    def test_manual_recovery_is_standalone_and_checks_out_requested_tag(self) -> None:
        recovery = self._job("recover_github_release")
        self.assertNotIn("needs:", recovery)
        self.assertIn("github.event_name == 'workflow_dispatch'", recovery)
        self.assertEqual(2, recovery.count("actions/checkout@"))
        self.assertIn("ref: ${{ inputs.tag }}", recovery)
        self.assertIn("path: release-source", recovery)
        self.assertIn("contents: write", recovery)
        self.assertIn("scripts/verify_release_provenance.py recover", recovery)
        self.assertIn("--repository-root release-source", recovery)
        self.assertNotIn("gh-action-pypi-publish", recovery)
        self.assertNotIn("python -m build", recovery)

    def test_public_python_support_is_exercised_by_ci(self) -> None:
        ci = self.workflows[CI_WORKFLOW.name]

        def ci_job(name: str) -> str:
            matched = re.search(
                rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-z][a-z0-9_-]*:\n|\Z)",
                ci,
            )
            self.assertIsNotNone(matched, name)
            return matched.group(0) if matched is not None else ""

        classifiers = {
            match.group(1)
            for value in PROJECT["project"]["classifiers"]
            if (match := re.fullmatch(r"Programming Language :: Python :: (\d+\.\d+)", value))
        }
        tested = set(
            re.findall(
                r'(?m)^\s+python-version:\s*["\']?(3\.\d+)', ci
            )
        )
        self.assertEqual({"3.11", "3.12"}, classifiers)
        self.assertEqual(classifiers, tested)
        # requires-python is an install gate, not a support claim. Pin its floor to the
        # lowest tested version, but never add an upper cap: a cap blocks installation on
        # newer interpreters that work fine, including the maintainer's own. Claims about
        # which versions are supported live in classifiers, bound to the CI matrix above.
        floor = min(tested, key=lambda value: tuple(int(part) for part in value.split(".")))
        self.assertEqual(f">={floor}", PROJECT["project"]["requires-python"])

        windows = ci_job("windows_tests")
        windows_audit = ci_job("windows_tests_audit")
        secret_history = ci_job("secret_history")
        linux311 = ci_job("core_linux_python311")
        linux312 = ci_job("core_linux_python312")
        wheel312 = ci_job("installed_wheel_linux_python312")
        self.assertIn("runs-on: windows-latest", windows)
        self.assertIn('python-version: "3.11"', windows)
        self.assertIn("fetch-depth: 0", windows)
        self.assertIn("Run complete Windows test shard with duration budget", windows)
        self.assertIn("shard: [1, 2, 3, 4]", windows)
        self.assertIn("--shard-count 4", windows)
        self.assertIn("--expected-shards 4", windows_audit)
        self.assertIn("Prove full Windows collection and execution conservation", windows_audit)
        self.assertIn('--history-since "$HISTORY_BASE"', secret_history)
        self.assertIn("github.event_name != 'pull_request'", secret_history)
        self.assertIn("--history --receipt", secret_history)
        for job, version in ((linux311, "3.11"), (linux312, "3.12")):
            self.assertIn("runs-on: ubuntu-latest", job)
            self.assertIn(f'python-version: "{version}"', job)
            self.assertIn("fetch-depth: 0", job)
            self.assertIn("python -m pytest -q", job)
            self.assertIn("--dist loadfile", job)
        self.assertIn("runs-on: ubuntu-latest", wheel312)
        self.assertIn('python-version: "3.12"', wheel312)
        self.assertIn("Build, install, and test an isolated wheel", wheel312)
        self.assertNotIn(' -e ".[dev]"', wheel312)

        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("Python 3.11 和 3.12", readme)
        self.assertIn("Windows 3.11", readme)
        self.assertIn("Linux 3.11 / 3.12", readme)
        self.assertNotRegex(readme, r"Python 3\.(?:13|14)")


class ReleaseProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.release = cls._load("pypi-gravity-insight-0.3.1.json")
        cls.wheel = "gravity_insight-0.3.1-py3-none-any.whl"
        cls.sdist = "gravity_insight-0.3.1.tar.gz"
        cls.provenance = {
            cls.wheel: cls._load(f"{cls.wheel}.provenance.json"),
            cls.sdist: cls._load(f"{cls.sdist}.provenance.json"),
        }

    @staticmethod
    def _load(name: str) -> dict[str, object]:
        return json.loads((PROVENANCE_FIXTURES / name).read_text(encoding="utf-8"))

    def _payloads(self) -> dict[str, dict[str, object]]:
        return copy.deepcopy(self.provenance)

    def _statement(
        self, payloads: dict[str, dict[str, object]], filename: str
    ) -> tuple[dict[str, object], dict[str, object]]:
        bundle = payloads[filename]["attestation_bundles"][0]  # type: ignore[index]
        attestation = bundle["attestations"][0]  # type: ignore[index]
        encoded = attestation["envelope"]["statement"]  # type: ignore[index]
        statement = json.loads(base64.b64decode(encoded))
        return attestation, statement

    @staticmethod
    def _replace_statement(
        attestation: dict[str, object], statement: dict[str, object]
    ) -> None:
        encoded = base64.b64encode(
            json.dumps(statement, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        attestation["envelope"]["statement"] = encoded  # type: ignore[index]

    def test_real_v031_responses_pass_offline(self) -> None:
        files = validate_release_provenance(self.release, self.provenance)
        self.assertEqual({self.wheel, self.sdist}, {item.filename for item in files})

    def test_attestation_bundles_must_exist_and_be_nonempty(self) -> None:
        for replacement in (None, []):
            with self.subTest(replacement=replacement):
                payloads = self._payloads()
                if replacement is None:
                    del payloads[self.sdist]["attestation_bundles"]
                else:
                    payloads[self.sdist]["attestation_bundles"] = replacement
                with self.assertRaisesRegex(
                    ProvenanceVerificationError, "attestation_bundles is missing or empty"
                ):
                    validate_release_provenance(self.release, payloads)

    def test_every_release_file_requires_an_integrity_response(self) -> None:
        payloads = self._payloads()
        del payloads[self.sdist]
        with self.assertRaisesRegex(
            ProvenanceVerificationError, "integrity provenance response is missing"
        ):
            validate_release_provenance(self.release, payloads)

    def test_statement_subject_must_name_the_release_file(self) -> None:
        payloads = self._payloads()
        attestation, statement = self._statement(payloads, self.wheel)
        statement["subject"][0]["name"] = "different.whl"  # type: ignore[index]
        self._replace_statement(attestation, statement)
        with self.assertRaisesRegex(ProvenanceVerificationError, "does not name"):
            validate_release_provenance(self.release, payloads)

    def test_statement_digest_must_match_pypi_release_sha256(self) -> None:
        payloads = self._payloads()
        attestation, statement = self._statement(payloads, self.wheel)
        statement["subject"][0]["digest"]["sha256"] = "0" * 64  # type: ignore[index]
        self._replace_statement(attestation, statement)
        with self.assertRaisesRegex(
            ProvenanceVerificationError, "does not match PyPI JSON SHA-256"
        ):
            validate_release_provenance(self.release, payloads)

    def test_statement_predicate_type_must_be_pypi_publish_v1(self) -> None:
        payloads = self._payloads()
        attestation, statement = self._statement(payloads, self.wheel)
        self.assertEqual(PUBLISH_PREDICATE_TYPE, statement["predicateType"])
        statement["predicateType"] = "https://example.invalid/predicate"
        self._replace_statement(attestation, statement)
        with self.assertRaisesRegex(ProvenanceVerificationError, "predicateType is not"):
            validate_release_provenance(self.release, payloads)

    def test_verification_material_must_contain_certificate(self) -> None:
        payloads = self._payloads()
        attestation, _ = self._statement(payloads, self.wheel)
        attestation["verification_material"]["certificate"] = ""  # type: ignore[index]
        with self.assertRaisesRegex(ProvenanceVerificationError, "certificate is missing"):
            validate_release_provenance(self.release, payloads)

    def test_verification_material_must_contain_transparency_entry(self) -> None:
        payloads = self._payloads()
        attestation, _ = self._statement(payloads, self.wheel)
        attestation["verification_material"]["transparency_entries"] = []  # type: ignore[index]
        with self.assertRaisesRegex(ProvenanceVerificationError, "transparency_entries is empty"):
            validate_release_provenance(self.release, payloads)

    def test_empty_verification_material_fails_closed(self) -> None:
        payloads = self._payloads()
        attestation, _ = self._statement(payloads, self.wheel)
        attestation["verification_material"] = {}
        with self.assertRaisesRegex(
            ProvenanceVerificationError, "certificate is missing.*transparency_entries is empty"
        ):
            validate_release_provenance(self.release, payloads)

    def test_release_must_include_wheel_and_sdist(self) -> None:
        release = copy.deepcopy(self.release)
        release["urls"] = [
            item for item in release["urls"] if item["packagetype"] != "sdist"  # type: ignore[index]
        ]
        with self.assertRaisesRegex(
            ProvenanceVerificationError, "missing required distribution type.*sdist"
        ):
            validate_release_provenance(release, self.provenance)

    def test_malformed_statement_fails_closed(self) -> None:
        payloads = self._payloads()
        attestation, _ = self._statement(payloads, self.wheel)
        attestation["envelope"]["statement"] = "not-base64"  # type: ignore[index]
        with self.assertRaisesRegex(ProvenanceVerificationError, "not valid base64 JSON"):
            validate_release_provenance(self.release, payloads)

    def test_retry_budget_is_fixed_and_fails_after_six_waits(self) -> None:
        fetches: list[str] = []
        sleeps: list[float] = []

        def fetcher(url: str) -> dict[str, object]:
            fetches.append(url)
            if "/pypi/" in url:
                return self.release
            return {"attestation_bundles": []}

        with self.assertRaisesRegex(
            ProvenanceVerificationError,
            rf"did not pass after {MAX_ATTEMPTS} attempts",
        ):
            verify_pypi_release(
                "gravity-insight",
                "0.3.1",
                fetcher=fetcher,
                sleeper=sleeps.append,
                output=lambda _: None,
            )
        self.assertEqual([RETRY_DELAY_SECONDS] * (MAX_ATTEMPTS - 1), sleeps)
        self.assertEqual(1 + (2 * MAX_ATTEMPTS), len(fetches))


SHA_A = "a" * 64
SHA_B = "b" * 64
WHEEL = "gravity_insight-0.3.2-py3-none-any.whl"
SDIST = "gravity_insight-0.3.2.tar.gz"


class FakeGitHubGateway:
    def __init__(self, release: dict[str, object] | None, remote_commit: str = ""):
        self.release = release
        self.remote_commit = remote_commit
        self.created: list[str] = []
        self.uploaded: list[str] = []

    def remote_tag_commit(self, tag: str) -> str:
        return self.remote_commit

    def get_release(self, tag: str) -> dict[str, object] | None:
        return self.release

    def create_release(self, tag: str) -> None:
        self.created.append(tag)
        self.release = {"tag_name": tag, "assets": []}

    def asset_sha256(self, asset: dict[str, object]) -> str:
        return str(asset["sha256"])

    def upload_asset(self, tag: str, distribution: Distribution) -> None:
        self.uploaded.append(distribution.filename)
        assert self.release is not None
        assets = self.release["assets"]
        assert isinstance(assets, list)
        assets.append({"name": distribution.filename, "sha256": distribution.sha256})


class ReleaseRecoveryStateTests(unittest.TestCase):
    def _distributions(self, root: Path) -> tuple[Distribution, Distribution]:
        wheel = root / WHEEL
        sdist = root / SDIST
        wheel.write_bytes(b"wheel")
        sdist.write_bytes(b"sdist")
        return (
            Distribution(WHEEL, SHA_A, path=wheel),
            Distribution(SDIST, SHA_B, path=sdist),
        )

    def test_pypi_identical_hashes_skip_upload(self) -> None:
        local = (Distribution(WHEEL, SHA_A), Distribution(SDIST, SHA_B))
        remote = (Distribution(WHEEL, SHA_A), Distribution(SDIST, SHA_B))

        plan = plan_pypi_publish(local, remote)

        self.assertFalse(plan.upload_required)
        self.assertEqual((), plan.missing)
        self.assertEqual({WHEEL, SDIST}, {item.filename for item in plan.identical})

    def test_pypi_hash_mismatch_hard_fails_before_upload(self) -> None:
        local = (Distribution(WHEEL, SHA_A), Distribution(SDIST, SHA_B))
        remote = (Distribution(WHEEL, SHA_B), Distribution(SDIST, SHA_B))

        with self.assertRaisesRegex(
            ReleaseRecoveryError, rf"PyPI SHA-256 mismatch for {WHEEL}.*refusing upload"
        ):
            plan_pypi_publish(local, remote)

    def test_missing_github_release_is_created_from_verified_tag(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gravity-release-state-") as raw:
            root = Path(raw)
            for command in (
                ["git", "init", "--quiet"],
                ["git", "config", "user.name", "Release Tests"],
                ["git", "config", "user.email", "release@example.invalid"],
                ["git", "commit", "--allow-empty", "--quiet", "-m", "release"],
                ["git", "tag", "v0.3.2"],
            ):
                completed = subprocess.run(
                    command, cwd=root, text=True, encoding="utf-8", capture_output=True, check=False
                )
                self.assertEqual(0, completed.returncode, completed.stderr)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=root,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=True,
            ).stdout.strip()
            gateway = FakeGitHubGateway(None, remote_commit=commit)
            distributions = self._distributions(root)

            verified = verify_checked_out_tag("v0.3.2", "0.3.2", root, gateway)
            actions = sync_github_release("v0.3.2", distributions, gateway)

        self.assertEqual(commit, verified)
        self.assertEqual(["v0.3.2"], gateway.created)
        self.assertEqual([WHEEL, SDIST], gateway.uploaded)
        self.assertIn("created-release", actions)

    def test_existing_release_uploads_only_missing_assets(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gravity-release-state-") as raw:
            distributions = self._distributions(Path(raw))
            gateway = FakeGitHubGateway(
                {"assets": [{"name": WHEEL, "sha256": SHA_A}]}
            )

            first = sync_github_release("v0.3.2", distributions, gateway)
            second = sync_github_release("v0.3.2", distributions, gateway)

        self.assertEqual([], gateway.created)
        self.assertEqual([SDIST], gateway.uploaded)
        self.assertIn(f"uploaded-asset:{SDIST}", first)
        self.assertEqual(
            {f"verified-asset:{WHEEL}", f"verified-asset:{SDIST}"}, set(second)
        )

    def test_existing_asset_hash_mismatch_hard_fails_without_uploads(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gravity-release-state-") as raw:
            distributions = self._distributions(Path(raw))
            gateway = FakeGitHubGateway(
                {"assets": [{"name": WHEEL, "sha256": SHA_B}]}
            )

            with self.assertRaisesRegex(
                ReleaseRecoveryError,
                rf"GitHub asset SHA-256 mismatch for {WHEEL}.*refusing upload",
            ):
                sync_github_release("v0.3.2", distributions, gateway)

        self.assertEqual([], gateway.created)
        self.assertEqual([], gateway.uploaded)

    def test_local_release_evidence_uses_the_idempotent_asset_reconciler(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gravity-release-evidence-") as raw:
            root = Path(raw)
            evidence = root / "dependency-audit.json"
            evidence.write_text('{"status":"passed"}\n', encoding="utf-8")
            distributions = local_release_assets((root,))
            gateway = FakeGitHubGateway({"assets": []})

            first = sync_github_release("v0.3.2", distributions, gateway)
            second = sync_github_release("v0.3.2", distributions, gateway)

        self.assertEqual([evidence.name], gateway.uploaded)
        self.assertIn(f"uploaded-asset:{evidence.name}", first)
        self.assertEqual((f"verified-asset:{evidence.name}",), second)

    def test_empty_local_release_evidence_directory_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gravity-release-evidence-") as raw:
            with self.assertRaisesRegex(
                ReleaseRecoveryError, "extra release asset directory is empty"
            ):
                local_release_assets((Path(raw),))

if __name__ == "__main__":
    unittest.main()
