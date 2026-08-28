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

import gravity_sdk
from scripts.verify_release_provenance import (
    MAX_ATTEMPTS,
    PUBLISH_PREDICATE_TYPE,
    RETRY_DELAY_SECONDS,
    ProvenanceVerificationError,
    validate_release_provenance,
    verify_pypi_release,
)


ROOT = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
TAG_GATE = ROOT / "scripts" / "check_release_tag.py"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
PROVENANCE_FIXTURES = ROOT / "tests" / "fixtures" / "release_provenance"


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, text=True, capture_output=True, check=False
    )


class ReleaseVersionTests(unittest.TestCase):
    def test_project_import_and_distribution_versions_are_identical(self) -> None:
        project_version = PROJECT["project"]["version"]
        self.assertEqual(project_version, gravity_sdk.__version__)
        self.assertEqual(project_version, metadata.version("gravity-insight"))

    def test_uninstalled_source_checkout_derives_version_from_pyproject(self) -> None:
        probe = (
            "import sys; "
            f"sys.path.insert(0, {str(ROOT / 'src')!r}); "
            "import gravity_sdk; print(gravity_sdk.__version__)"
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
            ["git", "config", "user.name", "Gravity SDK Tests"],
            ["git", "config", "user.email", "gravity-sdk-tests@example.invalid"],
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

    def test_no_version_tag_is_a_passing_development_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gravity-release-tag-") as raw:
            completed = self._gate(self._repository(Path(raw)))
        self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
        self.assertIn("HEAD has no v* tag", completed.stdout)

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
        cls.workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")

    def _job(self, name: str) -> str:
        matched = re.search(
            rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)",
            self.workflow,
        )
        self.assertIsNotNone(matched, name)
        return matched.group(0) if matched is not None else ""

    def test_every_release_action_is_pinned_to_a_full_commit_sha(self) -> None:
        uses = re.findall(r"(?m)^\s+- uses: ([^\s]+)$", self.workflow)
        self.assertTrue(uses)
        self.assertEqual(
            [],
            [value for value in uses if re.fullmatch(r"[^@]+@[0-9a-f]{40}", value) is None],
        )

    def test_build_is_read_only_and_publishes_one_checked_artifact(self) -> None:
        build = self._job("build")
        self.assertIn("contents: read", build)
        self.assertNotIn("contents: write", build)
        self.assertIn("name: python-distributions", build)
        self.assertIn("path: dist/", build)
        self.assertNotIn("gh release create", build)

    def test_oidc_publish_precedes_the_only_github_release_job(self) -> None:
        publish = self._job("publish")
        release_provenance = self._job("release-provenance")
        github_release = self._job("github-release")
        self.assertIn("needs: build", publish)
        self.assertIn("id-token: write", publish)
        self.assertIn("name: python-distributions", publish)
        self.assertIn("gh-action-pypi-publish@", publish)
        self.assertIn("attestations: true", publish)
        self.assertNotIn("gh release create", publish)
        self.assertIn("needs: publish", release_provenance)
        self.assertIn("timeout-minutes: 10", release_provenance)
        self.assertIn("scripts/verify_release_provenance.py", release_provenance)
        self.assertNotRegex(release_provenance, r"\b(?:delete|yank)\b")
        self.assertIn("needs: publish", github_release)
        self.assertIn("contents: write", github_release)
        self.assertIn("name: python-distributions", github_release)
        self.assertIn("gh release create", github_release)
        self.assertEqual(1, self.workflow.count("gh release create"))


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


if __name__ == "__main__":
    unittest.main()
