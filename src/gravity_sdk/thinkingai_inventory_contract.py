"""Offline compiler for metadata-only ThinkingAI source inventory artifacts."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    load_json_object,
    validate_schema,
)
from .thinkingai_inventory_policy import (
    CATEGORY_POSITION as _CATEGORY_POSITION,
    MAPPED_SOURCE_IDS as _MAPPED_SOURCE_IDS,
    PROTECTED_SOURCE_FIELDS as _PROTECTED_SOURCE_FIELDS,
    RAW_ITEM_FIELDS as _RAW_ITEM_FIELDS,
    RAW_ROOT_FIELDS as _RAW_ROOT_FIELDS,
    SOURCE_CATEGORY_ORDER as _SOURCE_CATEGORY_ORDER,
    TAXONOMY as _TAXONOMY,
    mapping_decision as _policy_mapping_decision,
)


OBSERVATION_SCHEMA_VERSION = "gravity.thinkingai-source-observation.v1"
SNAPSHOT_SCHEMA_VERSION = "gravity.thinkingai-inventory-snapshot.v1"
SOURCE_ADAPTER = {"adapter_id": "thinkingai-public-catalog-dom", "version": 1}

_OBSERVATION_SCHEMA = "thinkingai-source-observation-v1.schema.json"
_SNAPSHOT_SCHEMA = "thinkingai-inventory-snapshot-v1.schema.json"
_ROOT_URL = "https://www.thinkingai.cn/skills/"
_SCOPE = {
    "root_url": _ROOT_URL,
    "robots_url": "https://www.thinkingai.cn/robots.txt",
    "robots_status": "allowed_except_backend_and_cj_booth",
    "sitemap_url": "https://www.thinkingai.cn/sitemap.xml",
    "catalog_language": "zh-CN",
    "detail_route_pattern": "https://www.thinkingai.cn/skills/<source-id>/",
}


class ThinkingAIInventoryError(AgentRuntimeContractError):
    """A source observation or compiled inventory fails a closed CT01 gate."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def build_source_observation(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize one browser-returned metadata object without retaining page body."""

    selected = _raw_mapping(raw, _RAW_ROOT_FIELDS, "source observation")
    items_value = selected.get("items")
    if isinstance(items_value, (str, bytes)) or not isinstance(items_value, Sequence):
        _invalid("THINKINGAI_OBSERVATION_SCHEMA_INVALID", "items must be an array")
    items = [_normalize_raw_item(item) for item in items_value]
    items.sort(key=lambda item: item["source_id"])
    payload = {
        "artifact_kind": "thinkingai_source_observation",
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "source_adapter": dict(SOURCE_ADAPTER),
        "observed_at": selected.get("observed_at"),
        "scope": dict(_SCOPE),
        "closure": {
            "pagination_urls": _sorted_strings(selected.get("pagination_urls")),
            "sitemap_skill_count": selected.get("sitemap_skill_count"),
            "sitemap_orphans": _sorted_strings(selected.get("sitemap_orphans")),
            "missing_from_sitemap": _sorted_strings(
                selected.get("missing_from_sitemap")
            ),
        },
        "category_counts": copy.deepcopy(selected.get("category_counts")),
        "item_count": len(items),
        "items": items,
        "network_called": True,
    }
    if selected.get("root_url") != _ROOT_URL or selected.get(
        "robots_status"
    ) != _SCOPE["robots_status"]:
        _invalid(
            "THINKINGAI_LINK_CLOSURE_INVALID",
            "the public source scope does not match the approved adapter",
        )
    payload["observation_sha256"] = canonical_digest(payload)
    return validate_source_observation(payload)


def validate_source_observation(value: Mapping[str, Any]) -> dict[str, Any]:
    selected = _schema_copy(
        value,
        _OBSERVATION_SCHEMA,
        "THINKINGAI_OBSERVATION_SCHEMA_INVALID",
        "ThinkingAI source observation",
    )
    _validate_digest(
        selected,
        "observation_sha256",
        "THINKINGAI_OBSERVATION_DIGEST_INVALID",
    )
    if selected["source_adapter"] != SOURCE_ADAPTER or selected["scope"] != _SCOPE:
        _invalid(
            "THINKINGAI_LINK_CLOSURE_INVALID",
            "source adapter or crawl scope changed",
        )
    items = selected["items"]
    source_ids = [item["source_id"] for item in items]
    if source_ids != sorted(source_ids):
        _invalid("THINKINGAI_ITEM_ORDER_INVALID", "source items are not sorted")
    if len(source_ids) != len(set(source_ids)):
        _invalid("THINKINGAI_ITEM_DUPLICATE", "source IDs are not unique")
    if selected["item_count"] != len(items):
        _invalid("THINKINGAI_COUNT_INVALID", "item count is not derived from items")
    expected_counts = _category_counts(items)
    if selected["category_counts"] != expected_counts:
        _invalid(
            "THINKINGAI_COUNT_INVALID",
            "category counts are not derived from source items",
        )
    for item in items:
        _validate_observation_item(item)
    closure = selected["closure"]
    if (
        closure["pagination_urls"]
        or closure["sitemap_orphans"]
        or closure["missing_from_sitemap"]
        or closure["sitemap_skill_count"] != len(items)
    ):
        _invalid(
            "THINKINGAI_LINK_CLOSURE_INVALID",
            "catalog, pagination, and sitemap links are not closed",
        )
    return selected


def compile_inventory_snapshot(
    observation: Mapping[str, Any],
) -> dict[str, Any]:
    source = validate_source_observation(observation)
    items = [_compile_inventory_item(item) for item in source["items"]]
    snapshot = {
        "artifact_kind": "thinkingai_inventory_snapshot",
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "source_adapter": dict(SOURCE_ADAPTER),
        "source_observation": {
            "observed_at": source["observed_at"],
            "observation_sha256": source["observation_sha256"],
        },
        "crawl_scope": copy.deepcopy(source["scope"]),
        "category_counts": copy.deepcopy(source["category_counts"]),
        "item_count": len(items),
        "items": items,
        "network_called": False,
    }
    snapshot["snapshot_sha256"] = canonical_digest(snapshot)
    return validate_inventory_snapshot(snapshot, observation=source)


def validate_inventory_snapshot(
    value: Mapping[str, Any],
    *,
    observation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    selected = _schema_copy(
        value,
        _SNAPSHOT_SCHEMA,
        "THINKINGAI_SNAPSHOT_SCHEMA_INVALID",
        "ThinkingAI inventory snapshot",
    )
    _validate_digest(
        selected,
        "snapshot_sha256",
        "THINKINGAI_SNAPSHOT_DIGEST_INVALID",
    )
    if selected["source_adapter"] != SOURCE_ADAPTER or selected["crawl_scope"] != _SCOPE:
        _invalid(
            "THINKINGAI_SNAPSHOT_SOURCE_INVALID",
            "snapshot source adapter or crawl scope changed",
        )
    items = selected["items"]
    source_ids = [item["source_id"] for item in items]
    if source_ids != sorted(source_ids):
        _invalid("THINKINGAI_ITEM_ORDER_INVALID", "inventory items are not sorted")
    if len(source_ids) != len(set(source_ids)):
        _invalid("THINKINGAI_ITEM_DUPLICATE", "inventory source IDs are not unique")
    if selected["item_count"] != len(items):
        _invalid("THINKINGAI_COUNT_INVALID", "snapshot item count is not derived")
    if selected["category_counts"] != _category_counts(items):
        _invalid("THINKINGAI_COUNT_INVALID", "snapshot category counts are not derived")
    for item in items:
        _validate_inventory_item(item)
    if observation is not None:
        _verify_snapshot_observation(selected, validate_source_observation(observation))
    return selected


def load_source_observation(path: str | Path) -> dict[str, Any]:
    selected = Path(path)
    return validate_source_observation(
        load_json_object(selected, "ThinkingAI source observation")
    )


def load_inventory_snapshot(path: str | Path) -> dict[str, Any]:
    selected = Path(path)
    return validate_inventory_snapshot(
        load_json_object(selected, "ThinkingAI inventory snapshot")
    )


def _normalize_raw_item(value: Any) -> dict[str, Any]:
    selected = _raw_mapping(value, _RAW_ITEM_FIELDS, "source item")
    categories = selected.get("source_categories")
    if isinstance(categories, (str, bytes)) or not isinstance(categories, Sequence):
        _invalid(
            "THINKINGAI_OBSERVATION_SCHEMA_INVALID",
            "source item categories must be an array",
        )
    unknown = [category for category in categories if category not in _TAXONOMY]
    if unknown:
        _invalid(
            "THINKINGAI_CATEGORY_UNKNOWN",
            "source item contains an unreviewed category",
        )
    normalized_categories = sorted(
        list(categories), key=lambda category: _CATEGORY_POSITION[category]
    )
    return {
        "source_id": selected.get("source_id"),
        "canonical_url": selected.get("canonical_url"),
        "title": selected.get("title"),
        "source_categories": normalized_categories,
        "http_status": selected.get("http_status"),
        "final_url": selected.get("final_url"),
        "declared_canonical_url": selected.get("declared_canonical_url"),
        "h1": selected.get("h1"),
        "content_sha256": selected.get("content_sha256"),
    }


def _validate_observation_item(item: Mapping[str, Any]) -> None:
    expected_categories = sorted(
        item["source_categories"], key=lambda category: _CATEGORY_POSITION[category]
    )
    if item["source_categories"] != expected_categories:
        _invalid("THINKINGAI_ITEM_ORDER_INVALID", "source categories are not sorted")
    expected_url = f"{_ROOT_URL}{item['source_id']}/"
    if (
        item["http_status"] != 200
        or item["canonical_url"] != expected_url
        or item["final_url"] != expected_url
        or item["declared_canonical_url"] != expected_url
        or item["h1"] != item["title"]
    ):
        _invalid(
            "THINKINGAI_LINK_CLOSURE_INVALID",
            "detail status, URL, canonical, or H1 does not close",
        )
    title = item["title"]
    if title != title.strip() or any(character in title for character in "\r\n\x00"):
        _invalid(
            "THINKINGAI_PROTECTED_CONTENT_PRESENT",
            "source title is not normalized bounded metadata",
        )


def _compile_inventory_item(source: Mapping[str, Any]) -> dict[str, Any]:
    source_id = source["source_id"]
    decision = _mapping_decision(source_id)
    return {
        "source_id": source_id,
        "source_url": source["canonical_url"],
        "source_title": source["title"],
        "source_categories": copy.deepcopy(source["source_categories"]),
        "gravity_taxonomy_ids": [
            _TAXONOMY[category] for category in source["source_categories"]
        ],
        "source_content_sha256": source["content_sha256"],
        "specification_state": "catalogued",
        **decision,
        "distribution_allowed": False,
    }


def _mapping_decision(source_id: str) -> dict[str, Any]:
    decision = _policy_mapping_decision(source_id)
    if decision is None:
        _invalid(
            "THINKINGAI_ITEM_UNMAPPED",
            "source identity has no explicit migration and license decision",
        )
    return decision


def _validate_inventory_item(item: Mapping[str, Any]) -> None:
    source_id = item["source_id"]
    if source_id not in _MAPPED_SOURCE_IDS:
        _invalid(
            "THINKINGAI_ITEM_UNMAPPED",
            "inventory source identity is not in the reviewed decision set",
        )
    expected_taxonomy = [_TAXONOMY[category] for category in item["source_categories"]]
    if item["gravity_taxonomy_ids"] != expected_taxonomy:
        _invalid(
            "THINKINGAI_TAXONOMY_INVALID",
            "Gravity taxonomy is not the closed source-category projection",
        )
    expected = _mapping_decision(source_id)
    if any(item[field] != expected[field] for field in expected):
        _invalid(
            "THINKINGAI_MAPPING_INVALID",
            "migration, license, or independent-authorship decision changed",
        )
    if item["distribution_allowed"] is not False:
        _invalid(
            "THINKINGAI_DISTRIBUTION_FORBIDDEN",
            "CT01 inventory items cannot be distributed as Skill content",
        )
    if item["license_review"] in {"blocked", "needs_review"} and item[
        "distribution_allowed"
    ]:
        _invalid(
            "THINKINGAI_DISTRIBUTION_FORBIDDEN",
            "unapproved source material cannot become distributable content",
        )


def _verify_snapshot_observation(
    snapshot: Mapping[str, Any], observation: Mapping[str, Any]
) -> None:
    reference = snapshot["source_observation"]
    if reference != {
        "observed_at": observation["observed_at"],
        "observation_sha256": observation["observation_sha256"],
    }:
        _invalid(
            "THINKINGAI_SNAPSHOT_SOURCE_INVALID",
            "snapshot does not bind the source observation",
        )
    if snapshot["crawl_scope"] != observation["scope"]:
        _invalid(
            "THINKINGAI_SNAPSHOT_SOURCE_INVALID", "snapshot crawl scope changed"
        )
    expected_items = [_compile_inventory_item(item) for item in observation["items"]]
    if snapshot["items"] != expected_items:
        _invalid(
            "THINKINGAI_SNAPSHOT_SOURCE_INVALID",
            "snapshot metadata or migration matrix changed from its observation",
        )


def _category_counts(items: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {category: 0 for category in _SOURCE_CATEGORY_ORDER}
    for item in items:
        for category in item["source_categories"]:
            if category not in counts:
                _invalid(
                    "THINKINGAI_CATEGORY_UNKNOWN",
                    "source item contains an unreviewed category",
                )
            counts[category] += 1
    return counts


def _raw_mapping(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _invalid(
            "THINKINGAI_OBSERVATION_SCHEMA_INVALID", f"{label} must be an object"
        )
    selected = copy.deepcopy(dict(value))
    unknown = set(selected) - fields
    if unknown & _PROTECTED_SOURCE_FIELDS:
        _invalid(
            "THINKINGAI_PROTECTED_CONTENT_PRESENT",
            f"{label} contains protected source content",
        )
    if set(selected) != fields:
        _invalid(
            "THINKINGAI_OBSERVATION_SCHEMA_INVALID",
            f"{label} fields do not match the metadata-only adapter",
        )
    return selected


def _sorted_strings(value: Any) -> list[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        _invalid(
            "THINKINGAI_OBSERVATION_SCHEMA_INVALID",
            "source closure values must be arrays",
        )
    return sorted(copy.deepcopy(list(value)))


def _schema_copy(
    value: Mapping[str, Any], schema: str, reason_code: str, label: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _invalid(reason_code, f"{label} must be an object")
    selected = copy.deepcopy(dict(value))
    try:
        validate_schema(selected, schema, label)
    except AgentRuntimeContractError as exc:
        raise ThinkingAIInventoryError(reason_code, f"{label} is invalid") from exc
    return selected


def _validate_digest(value: dict[str, Any], field: str, reason_code: str) -> None:
    digest = value.pop(field)
    expected = canonical_digest(value)
    value[field] = digest
    if digest != expected:
        _invalid(reason_code, "artifact digest does not match canonical JSON")


def _invalid(reason_code: str, message: str) -> None:
    raise ThinkingAIInventoryError(reason_code, message)


__all__ = [
    "OBSERVATION_SCHEMA_VERSION",
    "SNAPSHOT_SCHEMA_VERSION",
    "SOURCE_ADAPTER",
    "ThinkingAIInventoryError",
    "build_source_observation",
    "compile_inventory_snapshot",
    "load_inventory_snapshot",
    "load_source_observation",
    "validate_inventory_snapshot",
    "validate_source_observation",
]
