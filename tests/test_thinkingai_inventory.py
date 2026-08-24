from __future__ import annotations

import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

from gravity_sdk.agent_runtime_contracts import canonical_digest
from gravity_sdk.thinkingai_inventory import (
    ThinkingAIInventoryError,
    build_source_observation,
    compile_inventory_diff,
    compile_inventory_snapshot,
    load_inventory_diff,
    load_inventory_snapshot,
    load_source_observation,
    validate_inventory_diff,
    validate_inventory_snapshot,
    validate_source_observation,
    verify_inventory_diff,
)


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "src" / "gravity_sdk" / "contracts" / "thinkingai"
OBSERVATION = next((ARTIFACT_ROOT / "observations").glob("*.json"))
SNAPSHOT = next((ARTIFACT_ROOT / "snapshots").glob("*.json"))
DIFF = next((ARTIFACT_ROOT / "diffs").glob("*.json"))


def raw_observation(value: dict) -> dict:
    return {
        "observed_at": value["observed_at"],
        "root_url": value["scope"]["root_url"],
        "robots_status": value["scope"]["robots_status"],
        "category_counts": copy.deepcopy(value["category_counts"]),
        "pagination_urls": copy.deepcopy(value["closure"]["pagination_urls"]),
        "sitemap_skill_count": value["closure"]["sitemap_skill_count"],
        "sitemap_orphans": copy.deepcopy(value["closure"]["sitemap_orphans"]),
        "missing_from_sitemap": copy.deepcopy(
            value["closure"]["missing_from_sitemap"]
        ),
        "items": copy.deepcopy(value["items"]),
    }


def redigest(value: dict, field: str) -> dict:
    selected = copy.deepcopy(value)
    selected.pop(field, None)
    selected[field] = canonical_digest(selected)
    return selected


def synthetic_snapshot(base: dict, items: list[dict], observed_at: str) -> dict:
    selected = copy.deepcopy(base)
    selected["source_observation"] = {
        "observed_at": observed_at,
        "observation_sha256": canonical_digest({"observed_at": observed_at}),
    }
    selected["items"] = sorted(copy.deepcopy(items), key=lambda item: item["source_id"])
    selected["item_count"] = len(items)
    counts = {category: 0 for category in selected["category_counts"]}
    for item in items:
        for category in item["source_categories"]:
            counts[category] += 1
    selected["category_counts"] = counts
    return validate_inventory_snapshot(redigest(selected, "snapshot_sha256"))


class ThinkingAIInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.observation = load_source_observation(OBSERVATION)
        cls.snapshot = load_inventory_snapshot(SNAPSHOT)
        cls.difference = load_inventory_diff(DIFF)

    def assert_reason(self, reason_code: str, function, *args, **kwargs) -> None:
        with self.assertRaises(ThinkingAIInventoryError) as raised:
            function(*args, **kwargs)
        self.assertEqual(reason_code, raised.exception.reason_code)

    def test_current_artifacts_close_catalog_mapping_and_initial_diff(self) -> None:
        self.assertEqual(55, self.observation["item_count"])
        self.assertEqual(55, self.snapshot["item_count"])
        self.assertEqual(
            {
                "added": 55,
                "changed": 0,
                "removed": 0,
                "redirect": 0,
                "unchanged": 0,
                "total": 55,
            },
            self.difference["counts"],
        )
        self.assertEqual(
            self.snapshot,
            compile_inventory_snapshot(copy.deepcopy(self.observation)),
        )
        self.assertEqual(
            self.difference,
            compile_inventory_diff(None, copy.deepcopy(self.snapshot)),
        )
        self.assertEqual(
            self.difference,
            verify_inventory_diff(self.difference, None, self.snapshot),
        )
        self.assertEqual(
            {
                "付费分析": 14,
                "游戏分析": 4,
                "用户分析": 3,
                "数据分析": 13,
                "异常诊断": 13,
                "舆情分析": 5,
                "数据工程": 8,
                "数据采集": 8,
                "运营分析": 5,
                "Agent": 3,
                "知识库管理": 3,
            },
            self.snapshot["category_counts"],
        )

    def test_mapping_license_and_authorship_are_explicit_for_every_item(self) -> None:
        items = {item["source_id"]: item for item in self.snapshot["items"]}
        self.assertEqual(55, len(items))
        self.assertEqual(
            40, sum(item["mapping_kind"] == "future_skill" for item in items.values())
        )
        self.assertEqual(
            14, sum(item["license_review"] == "blocked" for item in items.values())
        )
        self.assertTrue(all(item["distribution_allowed"] is False for item in items.values()))
        for source_id, item in items.items():
            with self.subTest(source_id=source_id):
                if source_id.startswith(("ae-", "te-")):
                    self.assertEqual("out_of_scope_alternative", item["mapping_kind"])
                    self.assertEqual(
                        "THINKINGAI_VENDOR_SPECIFIC_OPERATION",
                        item["alternative_reason_code"],
                    )
                    self.assertIsNone(item["future_skill_uri"])
                    self.assertEqual("blocked", item["license_review"])
                    self.assertEqual("not_applicable", item["independent_authorship"])
                elif source_id == "generate-sql-query":
                    self.assertEqual("out_of_scope_alternative", item["mapping_kind"])
                    self.assertEqual(
                        "AUTOMATIC_TEXT_TO_SQL_OUT_OF_SCOPE",
                        item["alternative_reason_code"],
                    )
                    self.assertIsNone(item["future_skill_uri"])
                    self.assertEqual("approved", item["license_review"])
                    self.assertEqual("required", item["independent_authorship"])
                else:
                    self.assertEqual(
                        f"skill://gravity.game/{source_id}@1.0.0",
                        item["future_skill_uri"],
                    )
                    self.assertEqual("approved", item["license_review"])
                    self.assertEqual("required", item["independent_authorship"])

    def test_diff_classifies_added_changed_removed_redirect_and_unchanged(self) -> None:
        items = {item["source_id"]: item for item in self.snapshot["items"]}
        removed = items["ad-delivery-analysis"]
        changed = items["analysis-metric-definition-alignment"]
        redirected = items["app-device-performance-analysis"]
        unchanged = items["channel-quality-analysis"]
        added = items["churn-user-identification-persona"]
        previous = synthetic_snapshot(
            self.snapshot,
            [removed, changed, redirected, unchanged],
            "2026-08-24T11:00:00Z",
        )
        changed_now = copy.deepcopy(changed)
        changed_now["source_content_sha256"] = "f" * 64
        redirected_now = copy.deepcopy(redirected)
        redirected_now["source_url"] = (
            "https://www.thinkingai.cn/skills/app-device-performance-analysis-renamed/"
        )
        current = synthetic_snapshot(
            self.snapshot,
            [changed_now, redirected_now, unchanged, added],
            "2026-08-24T12:00:00Z",
        )

        difference = compile_inventory_diff(previous, current)
        self.assertEqual(
            {
                "added": 1,
                "changed": 1,
                "removed": 1,
                "redirect": 1,
                "unchanged": 1,
                "total": 5,
            },
            difference["counts"],
        )
        states = {item["source_id"]: item for item in difference["changes"]}
        self.assertEqual("removed", states[removed["source_id"]]["state"])
        self.assertEqual("changed", states[changed["source_id"]]["state"])
        self.assertEqual(
            ["source_content_sha256"], states[changed["source_id"]]["changed_fields"]
        )
        self.assertEqual("redirect", states[redirected["source_id"]]["state"])
        self.assertEqual(
            ["source_url"], states[redirected["source_id"]]["changed_fields"]
        )
        self.assertEqual("unchanged", states[unchanged["source_id"]]["state"])
        self.assertEqual("added", states[added["source_id"]]["state"])
        self.assertEqual(difference, verify_inventory_diff(difference, previous, current))

    def test_duplicate_orphan_unknown_category_and_unmapped_page_fail_closed(self) -> None:
        duplicate = raw_observation(self.observation)
        copied = copy.deepcopy(duplicate["items"][0])
        duplicate["items"].append(copied)
        duplicate["sitemap_skill_count"] += 1
        for category in copied["source_categories"]:
            duplicate["category_counts"][category] += 1
        self.assert_reason(
            "THINKINGAI_ITEM_DUPLICATE", build_source_observation, duplicate
        )

        orphan = raw_observation(self.observation)
        orphan["sitemap_orphans"] = [orphan["items"][0]["canonical_url"]]
        self.assert_reason(
            "THINKINGAI_LINK_CLOSURE_INVALID", build_source_observation, orphan
        )

        unknown_category = raw_observation(self.observation)
        unknown_category["items"][0]["source_categories"] = ["未审查分类"]
        self.assert_reason(
            "THINKINGAI_CATEGORY_UNKNOWN",
            build_source_observation,
            unknown_category,
        )

        unmapped = raw_observation(self.observation)
        item = unmapped["items"][0]
        item["source_id"] = "new-unreviewed-topic"
        item["canonical_url"] = "https://www.thinkingai.cn/skills/new-unreviewed-topic/"
        item["final_url"] = item["canonical_url"]
        item["declared_canonical_url"] = item["canonical_url"]
        source = build_source_observation(unmapped)
        self.assert_reason(
            "THINKINGAI_ITEM_UNMAPPED", compile_inventory_snapshot, source
        )

    def test_digest_mapping_and_distribution_tampering_fail(self) -> None:
        observation = copy.deepcopy(self.observation)
        observation["items"][0]["title"] = "tampered"
        self.assert_reason(
            "THINKINGAI_OBSERVATION_DIGEST_INVALID",
            validate_source_observation,
            observation,
        )

        mapping = copy.deepcopy(self.snapshot)
        vendor = next(
            item for item in mapping["items"] if item["source_id"].startswith("ae-")
        )
        vendor["mapping_kind"] = "future_skill"
        vendor["future_skill_uri"] = (
            f"skill://gravity.game/{vendor['source_id']}@1.0.0"
        )
        vendor["alternative_reason_code"] = None
        mapping = redigest(mapping, "snapshot_sha256")
        self.assert_reason(
            "THINKINGAI_MAPPING_INVALID", validate_inventory_snapshot, mapping
        )

        distribution = copy.deepcopy(self.snapshot)
        distribution["items"][0]["distribution_allowed"] = True
        distribution = redigest(distribution, "snapshot_sha256")
        self.assert_reason(
            "THINKINGAI_SNAPSHOT_SCHEMA_INVALID",
            validate_inventory_snapshot,
            distribution,
        )

        difference = copy.deepcopy(self.difference)
        difference["counts"]["added"] -= 1
        difference = redigest(difference, "diff_sha256")
        self.assert_reason(
            "THINKINGAI_DIFF_COUNT_INVALID", validate_inventory_diff, difference
        )

    def test_protected_source_content_cannot_enter_artifacts(self) -> None:
        raw = raw_observation(self.observation)
        raw["items"][0]["description"] = "customer result improved by 30 percent"
        self.assert_reason(
            "THINKINGAI_PROTECTED_CONTENT_PRESENT", build_source_observation, raw
        )
        rendered = json.dumps(
            [self.observation, self.snapshot, self.difference],
            ensure_ascii=False,
            sort_keys=True,
        )
        for forbidden in (
            '"description"',
            '"body"',
            '"html"',
            '"examples"',
            '"images"',
            '"charts"',
            '"customers"',
            "customer result improved by 30 percent",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_generator_check_is_offline_and_current(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "generate_thinkingai_inventory.py"),
                "--check",
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("artifacts are current", completed.stdout)

    def test_maintainer_adapter_is_bounded_and_never_returns_source_body(self) -> None:
        adapter = (
            ROOT / "scripts" / "thinkingai_public_catalog_dom_v1.js"
        ).read_text(encoding="utf-8")
        self.assertIn("await page.waitForTimeout(250)", adapter)
        self.assertIn("catalog.length > 1000", adapter)
        self.assertIn('crypto.subtle.digest(', adapter)
        self.assertNotIn("innerHTML", adapter)
        for returned_field in (
            "description:",
            "body:",
            "html:",
            "examples:",
            "images:",
            "charts:",
            "customers:",
        ):
            self.assertNotIn(returned_field, adapter)


if __name__ == "__main__":
    unittest.main()
