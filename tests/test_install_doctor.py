from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from gravity_sdk.install_doctor import assess_install_consistency


class InstallDoctorTests(unittest.TestCase):
    def test_consistent_editable_install_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / "src" / "gravity_sdk"
            package.mkdir(parents=True)
            result = assess_install_consistency(
                [{
                    "version": "0.3.0", "editable": True,
                    "project_root": str(root), "direct_url_valid": True,
                }],
                {
                    "version": "0.3.0", "project_root": str(root),
                    "origin": "working_directory",
                },
                {"version": "0.3.0", "path": str(package / "__init__.py")},
            )
        self.assertEqual("pass", result["status"])
        self.assertEqual("INSTALL_CONSISTENT", result["reason_code"])
        self.assertFalse(result["network_called"])

    def test_version_and_import_root_mismatches_are_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "current"
            other = Path(temporary) / "stale"
            (root / "src" / "gravity_sdk").mkdir(parents=True)
            (other / "src" / "gravity_sdk").mkdir(parents=True)
            result = assess_install_consistency(
                [{
                    "version": "0.2.0", "editable": True,
                    "project_root": str(other), "direct_url_valid": True,
                }],
                {
                    "version": "0.3.0", "project_root": str(root),
                    "origin": "working_directory",
                },
                {
                    "version": "0.2.0",
                    "path": str(other / "src" / "gravity_sdk" / "__init__.py"),
                },
            )
        self.assertEqual("fail", result["status"])
        self.assertEqual("INSTALL_METADATA_VERSION_MISMATCH", result["reason_code"])
        self.assertIn("INSTALL_EDITABLE_ROOT_MISMATCH", result["mismatches"])
        self.assertIn("INSTALL_IMPORT_ROOT_MISMATCH", result["mismatches"])
        self.assertEqual(3, len(result["reinstall_commands"]))
        self.assertEqual(
            "python -m pip uninstall gravity-insight -y",
            result["reinstall_commands"][0],
        )
