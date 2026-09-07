from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from gravity_insight._field_policy_shared import ANALYSIS_FIXED_USER_FIELDS
from gravity_insight.governance.stable_privacy import suspected_personal_reason
from gravity_insight.contracts.join_key import (
    JoinKeyContractError,
    inspect_join_key_contract,
    join_key_registry,
    normalize_join_value,
    require_proven_join_key,
    resolve_proven_join_key,
    validate_join_key_registry,
)
from gravity_insight.prober.privacy import classify_candidate_field


ROOT = Path(__file__).resolve().parents[1]
SAMPLED_ON = "2026-09-07"


def test_checked_in_join_key_registry_is_schema_valid_and_reviewed() -> None:
    registry = join_key_registry()

    assert registry["schema_version"] == "gravity.join-key-registry.v1"
    assert {item["namespace_status"] for item in registry["mappings"]} == {
        "proven",
        "disproven",
        "insufficient_evidence",
    }
    assert inspect_join_key_contract(ROOT) == []


def test_schema_and_semantics_reject_an_unknown_adjudication() -> None:
    registry = copy.deepcopy(join_key_registry())
    registry["mappings"][0]["namespace_status"] = "unchecked"

    with pytest.raises(JoinKeyContractError, match="does not match"):
        validate_join_key_registry(registry)


def test_insufficient_and_disproven_candidates_cannot_be_consumed_as_proven() -> None:
    with pytest.raises(JoinKeyContractError, match="not proven"):
        require_proven_join_key(
            "kuaishou.creative.candidate", as_of=SAMPLED_ON
        )
    with pytest.raises(JoinKeyContractError, match="insufficient_evidence"):
        resolve_proven_join_key("kuaishou", "creative", as_of=SAMPLED_ON)
    with pytest.raises(JoinKeyContractError, match="not proven"):
        require_proven_join_key(
            "bytedance.material.candidate.mid2", as_of=SAMPLED_ON
        )


def test_insufficient_candidate_cannot_be_relabelled_without_positive_evidence() -> None:
    registry = copy.deepcopy(join_key_registry())
    candidate = next(
        item
        for item in registry["mappings"]
        if item["mapping_id"] == "kuaishou.creative.candidate"
    )
    candidate["namespace_status"] = "proven"

    with pytest.raises(JoinKeyContractError, match="non-zero intersection"):
        validate_join_key_registry(registry)


def test_same_user_field_resolves_to_platform_specific_object_levels() -> None:
    byte = resolve_proven_join_key(
        "bytedance", "promotion", as_of=SAMPLED_ON
    )
    quick = resolve_proven_join_key("kuaishou", "unit", as_of=SAMPLED_ON)
    social = resolve_proven_join_key("tencent", "adgroup", as_of=SAMPLED_ON)

    assert {byte["right"]["path"], quick["right"]["path"], social["right"]["path"]} == {
        "data.list[].AdAid"
    }
    assert {byte["object_type"], quick["object_type"], social["object_type"]} == {
        "promotion",
        "unit",
        "adgroup",
    }
    assert len({byte["left"]["path"], quick["left"]["path"], social["left"]["path"]}) == 3


def test_bytedance_material_requires_subtype_specific_slot_selection() -> None:
    with pytest.raises(JoinKeyContractError, match="object_subtype is required"):
        resolve_proven_join_key("bytedance", "material", as_of=SAMPLED_ON)

    image = resolve_proven_join_key(
        "bytedance", "material", object_subtype="image", as_of=SAMPLED_ON
    )
    video = resolve_proven_join_key(
        "bytedance", "material", object_subtype="video", as_of=SAMPLED_ON
    )

    assert image["right"]["path"] == "data.list[].bytedanceMid1"
    assert video["right"]["path"] == "data.list[].bytedanceMid3"


def test_stale_proof_fails_closed_and_tencent_normalization_is_explicit() -> None:
    with pytest.raises(JoinKeyContractError, match="not current"):
        require_proven_join_key("tencent.creative", as_of="2026-12-07")

    assert normalize_join_value(
        "tencent.creative", 42, side="left", as_of=SAMPLED_ON
    ) == "42"
    assert normalize_join_value(
        "tencent.creative", "42", side="right", as_of=SAMPLED_ON
    ) == "42"
    with pytest.raises(JoinKeyContractError, match="integer JSON value"):
        normalize_join_value(
            "tencent.creative", True, side="left", as_of=SAMPLED_ON
        )


def test_material_name_fields_pass_existing_privacy_criteria_without_fixed_exemption() -> None:
    source = json.loads(
        (
            ROOT
            / "src/gravity_insight/contracts/operations/analysis.user_detail.list.json"
        ).read_text(encoding="utf-8")
    )["operation"]
    fields = [f"bytedanceMid{index}_name" for index in range(1, 9)]

    assert set(fields).isdisjoint(ANALYSIS_FIXED_USER_FIELDS)
    assert set(fields) <= set(source["response_projection"]["item_keys"])
    for field in fields:
        path = f"data.list[].{field}"
        assert classify_candidate_field(
            path, operation_id="analysis.user_detail.list"
        ) == ("non_sensitive", "business_metadata_name_pattern")
        assert suspected_personal_reason(source, path) is None
