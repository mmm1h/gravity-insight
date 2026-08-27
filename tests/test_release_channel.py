from __future__ import annotations

import subprocess
import sys
import tempfile
import tomllib
import unittest
from importlib import metadata
from pathlib import Path

import gravity_sdk


ROOT = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
TAG_GATE = ROOT / "scripts" / "check_release_tag.py"


def _run(command: list[str], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command, cwd=cwd, text=True, capture_output=True, check=False
    )


class ReleaseVersionTests(unittest.TestCase):
    def test_project_import_and_distribution_versions_are_identical(self) -> None:
        project_version = PROJECT["project"]["version"]
        self.assertEqual(project_version, gravity_sdk.__version__)
        self.assertEqual(project_version, metadata.version("gravity-sdk"))

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


if __name__ == "__main__":
    unittest.main()
