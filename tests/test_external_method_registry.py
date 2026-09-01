from __future__ import annotations

import copy
from pathlib import Path
import unittest

from gravity_insight.agent_runtime_contracts import canonical_digest
from gravity_insight.external_method_registry import (
    ExternalMethodRegistryError,
    REGISTRY_PATH,
    SOURCE_REF_PREFIX,
    load_source_registry,
    opaque_source_id,
    source_ref,
    validate_source_registry,
)


ROOT = Path(__file__).resolve().parents[1]


def _resign(value: dict) -> dict:
    selected = copy.deepcopy(value)
    selected.pop("registry_sha256", None)
    selected["registry_sha256"] = canonical_digest(selected)
    return selected


class ExternalMethodRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = load_source_registry()

    def test_default_registry_is_isolated_and_complete(self) -> None:
        self.assertEqual(REGISTRY_PATH, ROOT / "skills" / "sources" / "registry.json")
        self.assertFalse(self.registry["agent_default_visible"])
        self.assertEqual(55, self.registry["item_count"])
        self.assertEqual(self.registry["item_count"], len(self.registry["items"]))

    def test_registry_digest_is_canonical(self) -> None:
        selected = copy.deepcopy(self.registry)
        digest = selected.pop("registry_sha256")
        self.assertEqual(digest, canonical_digest(selected))

    def test_registry_digest_tampering_fails_closed(self) -> None:
        selected = copy.deepcopy(self.registry)
        selected["observed_at"] = "2026-08-25T00:00:00.000Z"
        with self.assertRaisesRegex(ExternalMethodRegistryError, "EXTERNAL_METHOD_SOURCE_CHANGED"):
            validate_source_registry(selected)

    def test_schema_tampering_fails_closed(self) -> None:
        selected = copy.deepcopy(self.registry)
        del selected["agent_default_visible"]
        selected = _resign(selected)
        with self.assertRaisesRegex(ExternalMethodRegistryError, "EXTERNAL_METHOD_REGISTRY_INVALID"):
            validate_source_registry(selected)

    def test_opaque_source_ids_are_stable_and_nonsemantic(self) -> None:
        for item in self.registry["items"]:
            with self.subTest(item=item["opaque_id"]):
                self.assertEqual(item["opaque_id"], opaque_source_id(item["source_locator"]))
                self.assertRegex(item["opaque_id"], r"^[0-9a-f]{16}$")
                self.assertEqual(
                    source_ref(item["source_locator"]),
                    SOURCE_REF_PREFIX + item["opaque_id"],
                )

    def test_duplicate_opaque_id_fails_closed(self) -> None:
        selected = copy.deepcopy(self.registry)
        selected["items"][1]["opaque_id"] = selected["items"][0]["opaque_id"]
        selected = _resign(selected)
        with self.assertRaisesRegex(ExternalMethodRegistryError, "EXTERNAL_METHOD_REGISTRY_INVALID"):
            validate_source_registry(selected)

    def test_registry_order_drift_fails_closed(self) -> None:
        selected = copy.deepcopy(self.registry)
        selected["items"][0], selected["items"][1] = selected["items"][1], selected["items"][0]
        selected = _resign(selected)
        with self.assertRaisesRegex(ExternalMethodRegistryError, "EXTERNAL_METHOD_REGISTRY_INVALID"):
            validate_source_registry(selected)

    def test_future_skill_requires_authorship_and_license_evidence(self) -> None:
        selected = copy.deepcopy(self.registry)
        item = next(item for item in selected["items"] if item["mapping_kind"] == "future_skill")
        item["authorship_evidence"] = "not_applicable"
        selected = _resign(selected)
        with self.assertRaisesRegex(ExternalMethodRegistryError, "EXTERNAL_METHOD_REGISTRY_INVALID"):
            validate_source_registry(selected)

    def test_vendor_specific_alternative_uses_neutral_reason(self) -> None:
        alternatives = [
            item for item in self.registry["items"]
            if item["mapping_kind"] == "out_of_scope_alternative"
        ]
        self.assertEqual(12, len(alternatives))
        self.assertEqual(
            43,
            sum(
                item["mapping_kind"] == "future_skill"
                for item in self.registry["items"]
            ),
        )
        self.assertTrue(all(item["reason_code"] == "VENDOR_SPECIFIC_CAPABILITY" for item in alternatives))
        self.assertTrue(all(item["future_skill_uri"] is None for item in alternatives))

    def test_source_content_is_never_distributable(self) -> None:
        self.assertTrue(
            all(item["source_distribution_allowed"] is False for item in self.registry["items"])
        )


if __name__ == "__main__":
    unittest.main()
