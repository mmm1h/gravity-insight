"""Assert the test package keeps private cache paths isolated."""

from __future__ import annotations

import unittest
from pathlib import Path
from tests import _cache_root


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
