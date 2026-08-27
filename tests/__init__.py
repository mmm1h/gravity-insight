"""Keep every package-qualified test run independent from private caches."""

from __future__ import annotations

import atexit
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


_temporary_cache = tempfile.TemporaryDirectory(prefix="gravity-sdk-tests-")
_cache_root = Path(_temporary_cache.name).resolve()
_cache_environment = patch.dict(
    os.environ,
    {
        "GRAVITY_CACHE_HOME": str(_cache_root),
        "LOCALAPPDATA": str(_cache_root),
        "XDG_CACHE_HOME": str(_cache_root),
        "GRAVITY_SDK_AUTO_UPGRADE": "0",
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
