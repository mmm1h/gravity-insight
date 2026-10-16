"""Keep every package-qualified test run independent from private caches."""

from __future__ import annotations

import atexit
import os
import sys
import tempfile
import unittest
from pathlib import Path


_temporary_cache = tempfile.TemporaryDirectory(prefix="gravity-insight-tests-")
_cache_root = Path(_temporary_cache.name).resolve()
_home_root = _cache_root / "home"
_home_root.mkdir()
# Capture private locations before redirecting them. Audit accesses, rather than
# checking directory contents at the start/end of a particular test: a writer
# may run later, remove its output, or swallow an advisory persistence error.
_private_cache_roots = {Path.home() / ".cache" / "gravity-insight"}
if configured := os.environ.get("GRAVITY_CACHE_HOME", "").strip():
    _private_cache_roots.add(Path(configured).expanduser())
for variable in ("LOCALAPPDATA", "XDG_CACHE_HOME"):
    if base := os.environ.get(variable, "").strip():
        _private_cache_roots.update(Path(base).expanduser() / name for name in (
            "GravityInsight", "gravity-insight"
        ))
_private_cache_prefixes = tuple(
    os.path.normcase(str(root.resolve())) for root in _private_cache_roots
)
_cache_violations: list[str] = []
_ISOLATED_ENVIRONMENT = {
    "GRAVITY_CACHE_HOME": str(_cache_root),
    "LOCALAPPDATA": str(_cache_root),
    "XDG_CACHE_HOME": str(_cache_root),
    "HOME": str(_home_root),
    "USERPROFILE": str(_home_root),
    "HOMEDRIVE": _home_root.drive,
    "HOMEPATH": str(_home_root)[len(_home_root.drive):],
    "GRAVITY_INSIGHT_AUTO_UPGRADE": "0",
    "GRAVITY_INSIGHT_AUTO_SKILLS": "0",
}
# Applied to os.environ directly rather than through patch.dict(...).start().
# A started patch joins mock's process-wide registry, so any test that calls
# patch.stopall() -- the usual addCleanup idiom for a setUp that starts one
# patcher -- ends this one too. Isolation then disappears for the rest of that
# worker without anything failing at the point of damage: the later tests read
# and write the developer's real cache root and still pass. Ownership of this
# environment does not belong to a library whose teardown any test can trigger.
_previous_environment = {name: os.environ.get(name) for name in _ISOLATED_ENVIRONMENT}
os.environ.update(_ISOLATED_ENVIRONMENT)
_suite_depth = 0
_restored = False
_original_suite_run = unittest.TestSuite.run


def _guard_private_cache(event: str, args: tuple) -> None:
    if _restored:
        return
    if event in {"open", "os.mkdir", "os.listdir", "os.scandir", "os.remove", "os.rmdir", "sqlite3.connect"}:
        paths = args[:1]
    elif event == "os.rename":
        paths = args[:2]
    else:
        return
    for value in paths:
        if not isinstance(value, (str, bytes, os.PathLike)):
            continue
        path = os.path.normcase(os.path.realpath(os.fsdecode(value)))
        if any(path == root or path.startswith(root + os.sep) for root in _private_cache_prefixes):
            message = f"outside test cache isolation: {event} {path}"
            _cache_violations.append(message)
            # Runtime writers intentionally swallow OSError; this must fail loud.
            raise AssertionError(message)


sys.addaudithook(_guard_private_cache)


def _restore_environment() -> None:
    global _restored
    if _restored:
        return
    _restored = True
    try:
        unittest.TestSuite.run = _original_suite_run
        for name, value in _previous_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
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
