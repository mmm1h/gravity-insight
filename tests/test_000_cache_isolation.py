"""Assert the test package keeps private cache paths isolated."""

from __future__ import annotations

import unittest
from pathlib import Path
from tests import _cache_root


class CacheIsolationTests(unittest.TestCase):
    def test_default_cache_paths_stay_under_the_test_directory(self) -> None:
        from gravity_insight.find_metadata import _default_catalog_path
        from gravity_insight.metadata_sync import default_catalog_path
        from gravity_insight.workspace import user_cache_root
        from gravity_insight import GravityInsightClient

        catalog = _default_catalog_path()

        self.assertEqual(_cache_root, user_cache_root())
        self.assertEqual(catalog, default_catalog_path())
        self.assertEqual(_cache_root / "GravityInsight", catalog.parents[2])
        self.assertEqual(
            catalog.parents[1] / "operation-catalog.json",
            GravityInsightClient.from_env()._operation_catalog._state_path,
        )

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
