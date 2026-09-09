"""Discovery reads registered SQL contracts, never query/verification execution."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch

from gravity_insight.sql import catalog, products
from gravity_insight.sql.time_window import EvidenceFormatError
from gravity_insight.workspace import WorkspaceError, WorkspaceNotConfiguredError, load_workspace


ROOT = Path(__file__).resolve().parents[1]


class SqlCatalogTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workspace = load_workspace(ROOT / "examples/workspace/gravity.toml")

    def test_ast_catalog_cannot_reach_execution_or_discovery_facades(self) -> None:
        from gravity_insight.governance.module_graph import (
            PACKAGE_ROOT, module_graph_adjacency, module_graph_definition,
        )

        graph = module_graph_adjacency(PACKAGE_ROOT, module_graph_definition(), "ast-only")["edges"]
        pending = ["gravity_insight.sql.catalog"]
        visited: set[str] = set()
        while pending:
            module = pending.pop()
            if module not in visited:
                visited.add(module)
                pending.extend(graph[module])
        self.assertEqual(set(), visited & {
            "gravity_insight.agent", "gravity_insight.find", "gravity_insight.sql",
            "gravity_insight.sql.products", "gravity_insight.sql.query",
            "gravity_insight.sql.verification",
        })

    def test_description_is_a_detached_safe_projection_of_explicit_workspace(self) -> None:
        original = copy.deepcopy(self.workspace.products)
        with (
            patch.object(catalog, "load_workspace", side_effect=AssertionError("ambient workspace")),
            patch.object(products, "product_names", side_effect=AssertionError("execution owner")),
        ):
            described = catalog.describe_products(self.workspace)
            cards, warnings = catalog.search_product_cards(
                "daily event summary", workspace=self.workspace, limit=1,
            )
        self.assertEqual(["daily-event-summary"], [item["name"] for item in described])
        self.assertEqual([], warnings)
        self.assertEqual("sql:daily-event-summary", cards[0]["selector"])
        self.assertEqual(
            {"name", "kind", "datasource", "app_ids", "privacy", "output_fields",
             "output_semantics", "max_rows", "measurement", "forbidden_claims"},
            set(described[0]),
        )
        self.assertEqual([1001], described[0]["app_ids"])
        for field in ("app_ids", "output_fields", "output_semantics", "forbidden_claims"):
            described[0][field].clear()
        self.assertEqual(original, self.workspace.products)

    def test_error_identity_and_catalog_fallback_are_preserved(self) -> None:
        with self.assertRaises(EvidenceFormatError) as caught:
            catalog.product_definition("missing", self.workspace)
        self.assertIs(type(caught.exception.__cause__), WorkspaceError)
        self.assertEqual("unknown SQL product: missing", str(caught.exception))
        empty = replace(self.workspace, products={})
        with self.assertRaises(WorkspaceNotConfiguredError):
            catalog.describe_products(empty)
        self.assertEqual(([], []), catalog.search_product_cards("anything", workspace=empty, limit=1))
        invalid = replace(self.workspace, apps={})
        with self.assertRaises(WorkspaceError):
            catalog.product_apps("daily-event-summary", invalid)
        self.assertEqual(
            ([], ["The workspace SQL product catalog is invalid; run `gravity sql --dry-run`."]),
            catalog.search_product_cards("daily event summary", workspace=invalid, limit=1),
        )
