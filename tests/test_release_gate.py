from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

from scripts.build_release_gate_receipt import (
    ReleaseGateError,
    build_release_gate_receipt,
)
from scripts.check_changelog import PYPROJECT_PATH, release_declaration
from scripts.check_installed_wheel_consumer import DEFAULT_REVISION
from scripts.check_release_ci import ReleaseCIError, check_release_ci
from scripts.check_release_main import ReleaseMainError, check_release_main
from scripts.run_integrated_validation import gate_specs


ROOT = Path(__file__).resolve().parents[1]
SHA = "a" * 40
TAG = "v0.3.8"


def _project_version() -> str:
    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))["project"][
        "version"
    ]


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


def _write(path: Path, value: object) -> Path:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


class ReleaseMainGateTests(unittest.TestCase):
    def test_tag_checkout_and_main_must_be_the_identical_commit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gravity-release-main-") as raw:
            root = Path(raw)
            _git(root, "init", "--quiet", "--initial-branch=main")
            _git(root, "config", "user.name", "Release Tests")
            _git(root, "config", "user.email", "release@example.invalid")
            _git(root, "commit", "--quiet", "--allow-empty", "-m", "release")
            commit = _git(root, "rev-parse", "HEAD")
            _git(root, "tag", TAG)

            receipt = check_release_main(
                root=root,
                expected_sha=commit,
                tag=TAG,
                main_ref="refs/heads/main",
                event_name="push",
                branch_metadata={
                    "name": "main",
                    "protected": True,
                    "commit": {"sha": commit},
                },
            )

            self.assertEqual(commit, receipt["main_commit"])
            _git(root, "commit", "--quiet", "--allow-empty", "-m", "main moved")
            moved = _git(root, "rev-parse", "HEAD")
            with self.assertRaisesRegex(ReleaseMainError, "not identical"):
                check_release_main(
                    root=root,
                    expected_sha=moved,
                    tag=TAG,
                    main_ref="refs/heads/main",
                    event_name="push",
                    branch_metadata={
                        "name": "main",
                        "protected": True,
                        "commit": {"sha": moved},
                    },
                )

    def test_non_push_event_is_rejected(self) -> None:
        with self.assertRaisesRegex(ReleaseMainError, "requires a push event"):
            check_release_main(
                root=ROOT,
                expected_sha="a" * 40,
                tag=TAG,
                main_ref="main",
                event_name="workflow_dispatch",
                branch_metadata={},
            )


class ReleaseCIGateTests(unittest.TestCase):
    def _run(self) -> dict[str, object]:
        return {
            "id": 42,
            "run_number": 9,
            "head_sha": SHA,
            "event": "push",
            "head_branch": "main",
            "conclusion": "success",
            "path": ".github/workflows/ci.yml",
        }

    def _jobs(self) -> dict[str, object]:
        return {"jobs": [{"id": 99, "name": "ci-required", "conclusion": "success"}]}

    def test_exact_sha_push_main_and_unique_required_job_pass(self) -> None:
        receipt = check_release_ci(
            self._run(),
            self._jobs(),
            expected_run_id=42,
            expected_sha=SHA,
            expected_event="push",
            expected_branch="main",
        )
        self.assertEqual((SHA, "ci-required"), (
            receipt["commit_sha"], receipt["required_job"]["name"]
        ))

    def test_event_or_duplicate_required_job_fails_closed(self) -> None:
        run = self._run()
        run["event"] = "pull_request"
        with self.assertRaisesRegex(ReleaseCIError, "identity mismatch"):
            check_release_ci(
                run,
                self._jobs(),
                expected_run_id=42,
                expected_sha=SHA,
                expected_event="push",
                expected_branch="main",
            )
        duplicate = self._jobs()
        duplicate["jobs"].append(
            {"id": 100, "name": "ci-required", "conclusion": "failure"}
        )
        with self.assertRaisesRegex(ReleaseCIError, "exactly one successful"):
            check_release_ci(
                self._run(),
                duplicate,
                expected_run_id=42,
                expected_sha=SHA,
                expected_event="push",
                expected_branch="main",
            )


class AggregateReleaseGateTests(unittest.TestCase):
    def _fixture(self, root: Path) -> dict[str, Path]:
        dist = root / "dist"
        sbom = root / "sbom"
        dist.mkdir()
        sbom.mkdir()
        wheel = dist / "gravity_insight-0.3.8-py3-none-any.whl"
        sdist = dist / "gravity_insight-0.3.8.tar.gz"
        wheel.write_bytes(b"wheel")
        sdist.write_bytes(b"sdist")
        wheel_sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
        sdist_sha = hashlib.sha256(sdist.read_bytes()).hexdigest()

        def sbom_document(filename: str, kind: str, digest: str) -> dict[str, object]:
            return {
                "bomFormat": "CycloneDX",
                "specVersion": "1.6",
                "metadata": {
                    "component": {
                        "hashes": [{"alg": "SHA-256", "content": digest}],
                        "properties": [
                            {"name": "gravity:distribution:filename", "value": filename},
                            {"name": "gravity:distribution:kind", "value": kind},
                            {"name": "gravity:distribution:sha256", "value": digest},
                        ],
                    }
                },
            }

        _write(sbom / "wheel.cdx.json", sbom_document(wheel.name, "wheel", wheel_sha))
        _write(sbom / "sdist.cdx.json", sbom_document(sdist.name, "sdist", sdist_sha))
        main = _write(root / "main.json", {
            "schema_version": "gravity.release-main-equivalence.v1",
            "status": "passed",
            "event_name": "push",
            "release_tag": TAG,
            "commit_sha": SHA,
            "protected_branch": "main",
            "branch_protected": True,
            "checked_out_head": SHA,
            "tag_commit": SHA,
            "main_commit": SHA,
            "branch_api_commit": SHA,
        })
        ci = _write(root / "ci.json", {
            "schema_version": "gravity.release-ci-evidence.v1",
            "status": "passed",
            "run_id": 42,
            "commit_sha": SHA,
            "event_name": "push",
            "branch": "main",
            "workflow_path": ".github/workflows/ci.yml",
            "conclusion": "success",
            "required_job": {"name": "ci-required", "conclusion": "success"},
        })
        gates = [
            {"name": item.name, "status": "pass", "passed": True, "exit_code": 0}
            for item in gate_specs(Path("python"), root / "iv")
        ]
        iv = _write(root / "iv.json", {
            "schema_version": "gravity.integrated-validation-receipt.v2",
            "commit_sha": SHA,
            "branch": "main",
            "trial": False,
            "complete_gate_set": True,
            "preconditions_before": {
                "head": SHA,
                "branch_is_main": True,
                "clean": True,
                "independent_venv": True,
            },
            "preconditions_after": {
                "head": SHA,
                "branch_is_main": True,
                "clean": True,
                "independent_venv": True,
            },
            "gates": gates,
            "skipped_gates": [],
            "integrated_validation_green": True,
            "overall": "passed",
        })
        secret = _write(root / "secret.json", {
            "status": "passed",
            "history_included": True,
            "repository_head": SHA,
            "history_commit_count": 2,
            "scanned_tracked_file_count": 3,
            "unreviewed_findings": [],
        })
        dependency = _write(root / "dependency.json", {
            "status": "passed",
            "artifact": wheel.name,
            "artifact_sha256": wheel_sha,
            "vulnerability_count": 0,
            "findings": [],
            "dependency_count": 4,
            "service": "OSV",
        })
        surface = _write(root / "surface.json", {
            "schema_version": "gravity.installed-wheel-surface-matrix.v1",
            "passed": True,
            "wheel": wheel.name,
            "wheel_sha256": wheel_sha,
            "surface_count": 5,
            "case_count": 1,
            "network_calls": 0,
            "cases": [{
                "surfaces": {name: "passed" for name in ("cli", "sdk", "plan", "agent", "mcp")}
            }],
        })
        consumer = _write(root / "consumer.json", {
            "schema_version": "gravity.installed-wheel-consumer-gate.v1",
            "status": "pass",
            "passed": True,
            "exit_code": 0,
            "strict_prerequisites": True,
            "revision": DEFAULT_REVISION,
            "check": {
                "schema_version": "gravity.installed-wheel-consumer-check.v2",
                "passed": True,
                "consumer_commit": DEFAULT_REVISION,
                "wheel": wheel.name,
                "wheel_sha256": wheel_sha,
                "network_calls": 0,
                "summary": {"ok": True, "tests_run": 2},
            },
        })
        migration = ROOT / "docs/migration/0.3.8.md"
        changelog = _write(root / "changelog.json", {
            "schema_version": "gravity.release-changelog.v1",
            "status": "passed",
            "release_version": "0.3.8",
            "project_version": "0.3.8",
            "repository_head": SHA,
            "section_state": "unreleased_target",
            "breaking_change_declaration": "declared",
            "breaking_entries": 1,
            "changelog_sha256": hashlib.sha256((ROOT / "CHANGELOG.md").read_bytes()).hexdigest(),
            "released_section_lock_sha256": hashlib.sha256((ROOT / "scripts/changelog_release_lock.json").read_bytes()).hexdigest(),
            "migration": {
                "status": "required_and_present",
                "path": "docs/migration/0.3.8.md",
                "sha256": hashlib.sha256(migration.read_bytes()).hexdigest(),
            },
        })
        return {
            "dist_dir": dist,
            "sbom_dir": sbom,
            "main_receipt": main,
            "ci_receipt": ci,
            "integrated_validation_receipt": iv,
            "secret_scan_receipt": secret,
            "dependency_audit_receipt": dependency,
            "surface_receipt": surface,
            "consumer_receipt": consumer,
            "changelog_receipt": changelog,
        }

    def test_all_items_bind_to_one_sha_and_intended_distributions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gravity-release-gate-") as raw:
            arguments = self._fixture(Path(raw))
            receipt = build_release_gate_receipt(
                expected_sha=SHA,
                release_tag=TAG,
                **arguments,
            )
        self.assertEqual("passed", receipt["status"])
        self.assertEqual(12, len(receipt["required_items"]))
        self.assertEqual("deferred_post_publish", receipt["required_items"]["provenance"]["status"])
        self.assertEqual(0, receipt["required_items"]["integrated_validation"]["skipped_gate_count"])

    def test_stale_iv_or_consumer_wheel_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gravity-release-gate-") as raw:
            arguments = self._fixture(Path(raw))
            iv_path = arguments["integrated_validation_receipt"]
            iv = json.loads(iv_path.read_text(encoding="utf-8"))
            iv["commit_sha"] = "b" * 40
            _write(iv_path, iv)
            with self.assertRaisesRegex(ReleaseGateError, "not an unqualified green"):
                build_release_gate_receipt(
                    expected_sha=SHA,
                    release_tag=TAG,
                    **arguments,
                )


class ReleaseChangelogReceiptTests(unittest.TestCase):
    def test_current_release_declaration_and_migration_agree(self) -> None:
        """Assert the invariant, not one release's contents.

        This used to pin `release_declaration("0.3.8")` to "declared" plus a
        bound migration guide, which was a snapshot of whatever the in-flight
        release happened to contain. Cutting 0.3.8 and opening an Unreleased
        0.3.9 with no breaks turned it red without anything being wrong -- the
        assertion carried a version-dependent fact with no version in it.
        What actually has to hold is that the declaration and the migration
        binding agree with the number of declared breaks, whichever it is.
        """
        version = _project_version()
        receipt = release_declaration(version)
        self.assertEqual(version, receipt["release_version"])
        migration = receipt["migration"]

        if receipt["breaking_entries"]:
            self.assertEqual("declared", receipt["breaking_change_declaration"])
            self.assertEqual("required_and_present", migration["status"])
            self.assertEqual(64, len(migration["sha256"]))
            self.assertTrue(str(migration["path"]).endswith(f"{version}.md"))
        else:
            self.assertEqual("none_declared", receipt["breaking_change_declaration"])
            self.assertEqual("not_required", migration["status"])
            self.assertIsNone(migration["sha256"])
            self.assertIsNone(migration["path"])

    def test_release_with_declared_breaks_binds_its_migration_guide(self) -> None:
        """Keep the has-breaks branch covered once the current release has none.

        `release_declaration` refuses a version other than the project version,
        so reaching that branch means presenting a pyproject that names one.
        0.3.8 is a real released section with real breaks; nothing synthetic.
        """
        source = PYPROJECT_PATH.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as raw:
            pyproject = Path(raw) / "pyproject.toml"
            pyproject.write_text(
                source.replace(
                    f'version = "{_project_version()}"', 'version = "0.3.8"', 1
                ),
                encoding="utf-8",
            )
            receipt = release_declaration("0.3.8", pyproject_path=pyproject)

        self.assertEqual("released", receipt["section_state"])
        self.assertEqual("declared", receipt["breaking_change_declaration"])
        self.assertEqual(4, receipt["breaking_entries"])
        self.assertEqual("required_and_present", receipt["migration"]["status"])
        self.assertEqual(64, len(receipt["migration"]["sha256"]))
        self.assertEqual(
            "docs/migration/0.3.8.md", receipt["migration"]["path"]
        )


if __name__ == "__main__":
    unittest.main()
