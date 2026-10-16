"""Assert the test package keeps private cache paths isolated."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from tests import _cache_root


class CacheIsolationTests(unittest.TestCase):
    def test_guard_catches_swallowed_writes_regardless_of_test_order(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / "private-home"
            home.mkdir()
            offender = root / "test_escape.py"
            offender.write_text('''
from pathlib import Path
import os

def test_clean():
    pass

def test_escape():
    path = Path(os.environ["OUTSIDE_CACHE"]) / "operation-catalog.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")
        path.unlink()
    except AssertionError:
        pass  # A swallowed persistence failure must still fail the suite.
''', encoding="utf-8")
            for order in (("clean", "escape"), ("escape", "clean")):
                with self.subTest(order=order):
                    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home),
                           "OUTSIDE_CACHE": str(home / ".cache/gravity-insight"),
                           "HOMEDRIVE": home.drive, "HOMEPATH": str(home)[len(home.drive):]}
                    run = subprocess.run(
                        [sys.executable, "-X", "utf8", "-m", "pytest", "-q", "-n", "0",
                         "-p", "tests.conftest", *(f"{offender}::test_{name}" for name in order)],
                        env={**env, "PYTHONIOENCODING": "utf-8"},
                        capture_output=True, text=True, encoding="utf-8", timeout=60,
                    )
                    self.assertNotEqual(0, run.returncode, run.stdout + run.stderr)
                    self.assertIn("outside test cache isolation", run.stdout + run.stderr)
                    self.assertFalse((home / ".cache/gravity-insight").exists())

    def test_configured_account_probe_state_stays_isolated(self) -> None:
        from gravity_insight import GravityInsightClient

        with tempfile.TemporaryDirectory() as directory:
            account = Path(directory) / ".env.gravity.local"
            account.write_text(
                "GRAVITY_USERNAME=isolation-check@example.invalid\n"
                "GRAVITY_PASSWORD=not-a-real-password\n", encoding="utf-8",
            )
            for env_path in (None, account):
                with self.subTest(default_account=env_path is None):
                    client = GravityInsightClient.from_env(env_path=env_path)
                    path = client._operation_catalog._state_path
                    self.assertTrue(path.is_relative_to(_cache_root), path)
                    client._operation_catalog.record("app.list", status="success")
                    self.assertTrue(path.is_file())

    def test_every_legacy_cache_candidate_is_isolated(self) -> None:
        from gravity_insight.support.cache_paths import cache_roots

        for root in cache_roots():
            with self.subTest(root=root):
                self.assertTrue(root.is_relative_to(_cache_root), root)

    def test_default_cache_paths_stay_under_the_test_directory(self) -> None:
        from gravity_insight.find_metadata import _default_catalog_path
        from gravity_insight.metadata_sync import default_catalog_path
        from gravity_insight.workspace import user_cache_root
        from gravity_insight import GravityInsightClient

        catalog = _default_catalog_path()

        self.assertEqual(_cache_root, user_cache_root())
        self.assertEqual(catalog, default_catalog_path())
        self.assertEqual(_cache_root, catalog.parents[2])
        self.assertEqual(
            catalog.parents[1] / "operation-catalog.json",
            GravityInsightClient.from_env()._operation_catalog._state_path,
        )

    def test_isolation_outlives_a_process_wide_patch_stopall(self) -> None:
        """`patch.stopall()` must not be able to switch the cache back on.

        It ends every patch started anywhere in the process. While isolation was
        installed with ``patch.dict(...).start()`` it was one of them, so a
        single ``addCleanup(patch.stopall)`` in an unrelated module redirected
        every later test in that worker at the developer's real cache root --
        silently, because the tests that then read and wrote it still passed.
        The case above only catches this when test distribution happens to run
        it after the offender, which is why the regression reached main.
        """

        from unittest.mock import patch

        from gravity_insight.workspace import user_cache_root

        patch.stopall()

        self.assertEqual(_cache_root, user_cache_root())

    def test_the_default_catalog_sits_under_a_principal_scope_segment(self) -> None:
        """The segment skipped by `parents[2]` above is the isolation itself.

        Without this the test would still pass if the scope directory vanished
        and the catalog fell back to a shared path -- the exact regression the
        principal-scoped layout exists to prevent.
        """

        from gravity_insight.find_metadata import _default_catalog_path

        scope = _default_catalog_path().parents[1].name

        self.assertNotEqual("", scope)
        self.assertRegex(scope, r"^[0-9a-f]{8,}$")
