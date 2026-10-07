from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from gravity_insight.contracts.user_platform_discriminator import (
    UserPlatformDiscriminatorError,
    inspect_user_platform_discriminator_contract,
    require_proven_user_platform_binding,
    user_platform_discriminator_registry,
    validate_user_platform_discriminator_registry,
)


ROOT = Path(__file__).resolve().parents[1]
SAMPLED_ON = "2026-10-07"


def test_checked_in_registry_matches_reviewed_aggregate_evidence() -> None:
    evidence = json.loads(
        (ROOT / "tests/fixtures/user_platform_discriminator_evidence.json").read_text(
            encoding="utf-8"
        )
    )
    registry = user_platform_discriminator_registry()

    assert inspect_user_platform_discriminator_contract(ROOT) == []
    assert registry["schema_version"] == "gravity.user-platform-discriminator-registry.v1"
    for binding in registry["bindings"]:
        run = evidence["runs"][binding["platform"]]
        assert binding["evidence"]["source"] == evidence["source"]
        assert binding["evidence"]["sampled_on"] == evidence["sampled_on"]
        assert binding["evidence"]["request_count"] == run["request_count"]
        assert binding["evidence"]["source_row_count"] == run["source_row_count"]
        assert binding["evidence"]["observations"] == run["observations"]


def test_only_reviewed_exact_platform_values_resolve() -> None:
    for platform in ("bytedance", "kuaishou"):
        binding = require_proven_user_platform_binding(platform, as_of=SAMPLED_ON)
        assert binding.accepted_value == platform
        assert binding.field_path == "data.list[].AdPlatform"

    with pytest.raises(UserPlatformDiscriminatorError, match="not proven"):
        require_proven_user_platform_binding("tencent", as_of=SAMPLED_ON)


def test_tampering_and_stale_evidence_fail_closed() -> None:
    registry = copy.deepcopy(user_platform_discriminator_registry())
    registry["bindings"][0]["accepted_value"] = "kuaishou"
    with pytest.raises(UserPlatformDiscriminatorError, match="contradicts"):
        validate_user_platform_discriminator_registry(registry)

    registry = copy.deepcopy(user_platform_discriminator_registry())
    registry["bindings"][0]["evidence"]["observations"][0]["observed_values"] = [
        "bytedance",
        "unknown",
    ]
    with pytest.raises(UserPlatformDiscriminatorError, match="unaccepted"):
        validate_user_platform_discriminator_registry(registry)

    with pytest.raises(UserPlatformDiscriminatorError, match="not current"):
        require_proven_user_platform_binding("bytedance", as_of="2027-01-07")
