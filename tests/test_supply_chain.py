from __future__ import annotations

import json
import subprocess
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.audit_release_dependencies import audit_site_packages
from scripts.generate_release_sbom import _bind_distribution
from scripts.scan_repository_secrets import (
    SecretScanError,
    load_allowlist,
    scan_repository,
    tracked_paths,
)


ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "scripts" / "scan_repository_secrets.py"


def git(root: Path, *arguments: str) -> None:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if completed.returncode:
        raise AssertionError(completed.stderr)


def repository(root: Path) -> None:
    git(root, "init", "--quiet", "--initial-branch=main")
    git(root, "config", "user.email", "supply-chain@example.invalid")
    git(root, "config", "user.name", "Supply Chain Test")


def empty_allowlist(root: Path) -> Path:
    path = root / "allowlist.json"
    path.write_text(
        json.dumps(
            {"schema_version": "gravity.secret-scan-allowlist.v1", "entries": []}
        ),
        encoding="utf-8",
    )
    return path


class SecretScanTests(unittest.TestCase):
    def test_fake_credential_is_actually_detected(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repository(root)
            fake_key = "AKIA" + "7K4P9N2Q6R8T1V3X"
            (root / "credentials.txt").write_text(
                f'aws_access_key_id = "{fake_key}"\n', encoding="utf-8"
            )
            allowlist = empty_allowlist(root)
            git(root, "add", "credentials.txt")
            git(root, "commit", "--quiet", "-m", "synthetic credential fixture")
            completed = subprocess.run(
                (
                    sys.executable, "--",
                    str(SCANNER),
                    "--root",
                    str(root),
                    "--allowlist",
                    str(allowlist),
                ),
                cwd=ROOT,
                text=True,
                encoding="utf-8",
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                capture_output=True,
                check=False,
            )
        self.assertEqual(1, completed.returncode, completed.stdout)
        receipt = json.loads(completed.stderr)
        self.assertEqual("secrets_found", receipt["status"])
        self.assertEqual("credentials.txt", receipt["unreviewed_findings"][0]["path"])
        self.assertIn("AWS", receipt["unreviewed_findings"][0]["detector"])
        self.assertNotIn(fake_key, completed.stderr)

    def test_ignored_untracked_environment_file_is_not_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repository(root)
            (root / ".gitignore").write_text(".env.*\n", encoding="utf-8")
            (root / "safe.txt").write_text("tracked\n", encoding="utf-8")
            git(root, "add", ".gitignore", "safe.txt")
            git(root, "commit", "--quiet", "-m", "tracked files")
            fake_key = "AKIA" + "7K4P9N2Q6R8T1V3X"
            (root / ".env.gravity.local").write_text(fake_key, encoding="utf-8")
            allowlist = empty_allowlist(root)
            code, receipt = scan_repository(
                root, include_history=False, allowlist_path=allowlist
            )
        self.assertEqual(0, code)
        self.assertEqual("passed", receipt["status"])
        self.assertNotIn(".env.gravity.local", tracked_paths(root) if root.exists() else [])

    def test_history_finds_a_secret_removed_from_the_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repository(root)
            fake_key = "AKIA" + "7K4P9N2Q6R8T1V3X"
            secret = root / "removed.txt"
            secret.write_text(fake_key + "\n", encoding="utf-8")
            git(root, "add", "removed.txt")
            git(root, "commit", "--quiet", "-m", "synthetic history fixture")
            secret.unlink()
            git(root, "add", "-u")
            git(root, "commit", "--quiet", "-m", "remove fixture")
            code, receipt = scan_repository(
                root, include_history=True, allowlist_path=empty_allowlist(root)
            )
        self.assertEqual(1, code)
        self.assertEqual("history", receipt["unreviewed_findings"][0]["scope"])

    def test_incremental_history_finds_a_secret_added_then_removed_in_the_range(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repository(root)
            (root / "safe.txt").write_text("safe\n", encoding="utf-8")
            git(root, "add", "safe.txt")
            git(root, "commit", "--quiet", "-m", "safe base")
            base = subprocess.check_output(
                ("git", "rev-parse", "HEAD"), cwd=root, text=True, encoding="utf-8"
            ).strip()
            fake_key = "AKIA" + "7K4P9N2Q6R8T1V3X"
            secret = root / "removed.txt"
            secret.write_text(fake_key + "\n", encoding="utf-8")
            git(root, "add", "removed.txt")
            git(root, "commit", "--quiet", "-m", "add synthetic secret")
            secret.unlink()
            git(root, "add", "-u")
            git(root, "commit", "--quiet", "-m", "remove synthetic secret")
            code, receipt = scan_repository(
                root,
                include_history=False,
                history_since=base,
                allowlist_path=empty_allowlist(root),
            )
        self.assertEqual(1, code)
        self.assertEqual("incremental", receipt["history_scope"])
        self.assertFalse(receipt["history_included"])
        self.assertEqual(base, receipt["history_base"])
        self.assertEqual(2, receipt["history_commit_count"])
        self.assertEqual("history", receipt["unreviewed_findings"][0]["scope"])

    def test_allowlist_requires_reason_and_unexpired_review(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "allowlist.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": "gravity.secret-scan-allowlist.v1",
                        "entries": [
                            {
                                "path": "fixture.txt",
                                "detector": "Secret Keyword",
                                "value_sha1": "0" * 40,
                                "reason": "A sufficiently specific synthetic fixture reason.",
                                "review_expires": "2026-01-01",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SecretScanError, "expired"):
                load_allowlist(path, today=date(2026, 8, 31))


class DependencyAuditTests(unittest.TestCase):
    @patch("scripts.audit_release_dependencies.ensure_dependency_coverage")
    @patch("scripts.audit_release_dependencies.direct_runtime_dependencies", return_value={"requests"})
    @patch(
        "scripts.audit_release_dependencies.installed_runtime_components",
        return_value=[
            {"name": "gravity-insight", "version": "0.3.3"},
            {"name": "requests", "version": "2.33.0"},
        ],
    )
    def test_unreachable_advisory_service_is_unable_not_clean(
        self, _components: Mock, _direct: Mock, _coverage: Mock
    ) -> None:
        completed = subprocess.CompletedProcess(
            args=("pip-audit",), returncode=1, stdout="", stderr="connection refused"
        )
        code, receipt = audit_site_packages(
            Path("site-packages"),
            python=Path(sys.executable),
            osv_url="http://127.0.0.1:1/v1/query",
            timeout=1,
            runner=Mock(return_value=completed),
        )
        self.assertEqual(2, code)
        self.assertEqual("unable_to_audit", receipt["status"])
        self.assertNotEqual("passed", receipt["status"])

    @patch("scripts.audit_release_dependencies.ensure_dependency_coverage")
    @patch("scripts.audit_release_dependencies.direct_runtime_dependencies", return_value={"requests"})
    @patch(
        "scripts.audit_release_dependencies.installed_runtime_components",
        return_value=[
            {"name": "gravity-insight", "version": "0.3.3"},
            {"name": "requests", "version": "2.33.0"},
        ],
    )
    def test_real_finding_is_never_converted_to_pass(
        self, _components: Mock, _direct: Mock, _coverage: Mock
    ) -> None:
        document = {
            "dependencies": [
                {"name": "gravity-insight", "version": "0.3.3", "vulns": []},
                {
                    "name": "requests",
                    "version": "2.33.0",
                    "vulns": [{"id": "CVE-2099-0001"}],
                },
            ]
        }
        completed = subprocess.CompletedProcess(
            args=("pip-audit",), returncode=1, stdout=json.dumps(document), stderr=""
        )
        code, receipt = audit_site_packages(
            Path("site-packages"),
            python=Path(sys.executable),
            osv_url="https://api.osv.dev/v1/query",
            timeout=1,
            runner=Mock(return_value=completed),
        )
        self.assertEqual(1, code)
        self.assertEqual("vulnerabilities_found", receipt["status"])
        self.assertEqual("CVE-2099-0001", receipt["findings"][0]["id"])


class SbomTests(unittest.TestCase):
    def test_distribution_binding_records_kind_name_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            artifact = Path(raw) / "gravity_insight-0.3.3-py3-none-any.whl"
            artifact.write_bytes(b"synthetic wheel")
            document = {
                "metadata": {
                    "component": {"type": "library", "name": "gravity-insight"}
                }
            }
            selected = _bind_distribution(document, artifact, "wheel")
        component = selected["metadata"]["component"]
        properties = {item["name"]: item["value"] for item in component["properties"]}
        self.assertEqual("wheel", properties["gravity:distribution:kind"])
        self.assertEqual(64, len(component["hashes"][0]["content"]))


if __name__ == "__main__":
    unittest.main()
