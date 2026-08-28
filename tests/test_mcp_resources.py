from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from gravity_sdk.mcp.resources import (
    ResourceAccessPolicy,
    ResourceCatalog,
    ResourceError,
    ScopedResourceCache,
)


class Trust:
    def trust(self, *_args):
        return {"status": "unknown"}


class Journeys:
    def list(self):
        return {"schema_version": "journeys.v1", "status": "success"}


class FakeSDK:
    def __init__(self, owner: str = "one", workspace_id: str = "shared") -> None:
        self.owner = owner
        self.workspace = SimpleNamespace(
            root=Path.cwd(),
            state_root=Path("tmp/mcp-resource-state") / workspace_id,
            apps={"demo": 7, "hidden": 8},
        )
        self.capability_trust = Trust()
        self.journeys = Journeys()
        self.calls: list[str] = []

    def capabilities(self, **_options):
        self.calls.append("capabilities")
        return {"schema_version": "capabilities.v1", "status": "success"}

    def describe_sql_products(self):
        self.calls.append("sql")
        return [{"name": "registered"}]

    def list_http_receipts(self, **_options):
        self.calls.append("receipts")
        return {"schema_version": "receipts.v1", "status": "success"}

    def saved_analyses(self, app, **_options):
        self.calls.append(f"saved:{app}")
        return {"schema_version": "saved.v1", "status": "success", "owner": self.owner}

    def table_lineage(self, query, **_options):
        self.calls.append(f"lineage:{query}")
        return {"schema_version": "lineage.v1", "status": "success", "query": query}

    def analysis_vocabulary(self, query, **_options):
        self.calls.append(f"vocabulary:{query}")
        return {"schema_version": "vocabulary.v1", "status": "success", "query": query}


class MCPResourceTests(unittest.TestCase):
    def catalog(self, sdk=None, **options) -> ResourceCatalog:
        return ResourceCatalog(
            sdk or FakeSDK(),
            metadata=lambda: {"schema_version": "metadata.v1", "status": "success"},
            **options,
        )

    def test_resource_listing_is_complete_paginated_and_stably_sorted(self) -> None:
        catalog = self.catalog(page_size=2)
        cursor = None
        rows = []
        while True:
            page = catalog.list(cursor)
            rows.extend(page["resources"])
            cursor = page.get("nextCursor")
            if cursor is None:
                break

        uris = [item["uri"] for item in rows]
        self.assertEqual(sorted(uris), uris)
        self.assertEqual(len(uris), len(set(uris)))
        self.assertIn("gravity://catalog/capabilities", uris)
        self.assertIn("gravity://apps/demo/saved-analyses", uris)
        self.assertEqual(3, len(catalog.templates()["resourceTemplates"]))
        with self.assertRaises(ResourceError):
            catalog.list("malformed")

    def test_access_filtering_happens_before_cache_or_sdk_access(self) -> None:
        sdk = FakeSDK()
        access = ResourceAccessPolicy(
            uri_filter=lambda uri: uri != "gravity://receipts",
            app_filter=lambda alias: alias != "hidden",
        )
        catalog = self.catalog(sdk, access=access)
        uris = []
        cursor = None
        while True:
            page = catalog.list(cursor)
            uris.extend(item["uri"] for item in page["resources"])
            cursor = page.get("nextCursor")
            if cursor is None:
                break

        self.assertNotIn("gravity://receipts", uris)
        self.assertNotIn("gravity://apps/hidden/saved-analyses", uris)
        with self.assertRaises(ResourceError):
            catalog.read("gravity://receipts")
        with self.assertRaises(ResourceError):
            catalog.read("gravity://apps/hidden/saved-analyses")
        with self.assertRaises(ResourceError):
            catalog.read("gravity://apps/not-configured/saved-analyses")
        self.assertEqual([], sdk.calls)

    def test_directory_cache_is_isolated_by_principal_and_workspace_scope(self) -> None:
        cache = ScopedResourceCache()
        first_sdk, second_sdk = FakeSDK("first"), FakeSDK("second")
        first = self.catalog(first_sdk, cache=cache, principal_scope="principal-a")
        second = self.catalog(second_sdk, cache=cache, principal_scope="principal-b")
        uri = "gravity://apps/demo/saved-analyses"

        first_value = first.read(uri)
        first_again = first.read(uri)
        second_value = second.read(uri)

        self.assertEqual("first", first_value["value"]["owner"])
        self.assertEqual(first_value, first_again)
        self.assertEqual("second", second_value["value"]["owner"])
        self.assertEqual(["saved:demo"], first_sdk.calls)
        self.assertEqual(["saved:demo"], second_sdk.calls)

        third_sdk = FakeSDK("third", workspace_id="other")
        third = self.catalog(
            third_sdk, cache=cache, principal_scope="principal-a"
        )
        third_value = third.read(uri)

        self.assertEqual("third", third_value["value"]["owner"])
        self.assertEqual(["saved:demo"], third_sdk.calls)

    def test_current_offline_and_dynamic_resource_owners_are_preserved(self) -> None:
        sdk = FakeSDK()
        catalog = self.catalog(sdk)

        apps = catalog.read("gravity://workspace/apps")
        lineage = catalog.read("gravity://metadata/table-lineage/publish")
        vocabulary = catalog.read("gravity://workspace/analysis-vocabulary/event")

        self.assertEqual(2, apps["value"]["count"])
        self.assertFalse(apps["value"]["network_called"])
        self.assertEqual("publish", lineage["value"]["query"])
        self.assertEqual("event", vocabulary["value"]["query"])
        self.assertEqual(["lineage:publish", "vocabulary:event"], sdk.calls)

    def test_resource_byte_budget_fails_closed(self) -> None:
        sdk = FakeSDK()
        sdk.capabilities = lambda **_options: {
            "schema_version": "capabilities.v1",
            "status": "success",
            "payload": "x" * 100_001,
        }
        with self.assertRaises(ResourceError):
            self.catalog(sdk).read("gravity://catalog/capabilities")


if __name__ == "__main__":
    unittest.main()
