"""Keep test discovery independent from a developer's private cache."""

from __future__ import annotations

import atexit
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


_temporary_cache = tempfile.TemporaryDirectory(prefix="gravity-sdk-tests-")
_cache_root = Path(_temporary_cache.name)
_cache_environment = patch.dict(
    os.environ,
    {
        "GRAVITY_CACHE_HOME": str(_cache_root),
        "LOCALAPPDATA": str(_cache_root),
        "XDG_CACHE_HOME": str(_cache_root),
    },
)
_cache_environment.start()
_suite_depth = 0
_restored = False
_original_suite_run = unittest.TestSuite.run


def _restore_environment() -> None:
    global _restored
    if _restored:
        return
    _restored = True
    try:
        unittest.TestSuite.run = _original_suite_run
        _cache_environment.stop()
    finally:
        _temporary_cache.cleanup()


def _run_with_isolated_cache(
    suite: unittest.TestSuite,
    result: unittest.TestResult,
    debug: bool = False,
) -> unittest.TestResult:
    global _suite_depth
    _suite_depth += 1
    try:
        return _original_suite_run(suite, result, debug)
    finally:
        _suite_depth -= 1
        if _suite_depth == 0:
            _restore_environment()


unittest.TestSuite.run = _run_with_isolated_cache
atexit.register(_restore_environment)


class CacheIsolationTests(unittest.TestCase):
    def test_default_cache_paths_stay_under_the_test_directory(self) -> None:
        from gravity_sdk.find_metadata import _default_catalog_path
        from gravity_sdk.metadata_sync import default_catalog_path
        from gravity_sdk.workspace import user_cache_root
        from gravity_sdk import GravityInsightClient

        self.assertEqual(_cache_root, user_cache_root())
        self.assertEqual(
            _cache_root / "GravityInsight" / "metadata" / "catalog.sqlite3",
            _default_catalog_path(),
        )
        self.assertEqual(_default_catalog_path(), default_catalog_path())
        self.assertEqual(
            _cache_root / "GravityInsight" / "operation-catalog.json",
            GravityInsightClient.from_env()._operation_catalog._state_path,
        )
