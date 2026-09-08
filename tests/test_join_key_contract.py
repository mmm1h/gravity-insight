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


@pytest.mark.parametrize(
    ("mapping_id", "subtype", "source_name", "pointer"),
    [
        ("bytedance.material", None, "targeted-summary", "/material_mid_union"),
        ("bytedance.project", None, "targeted-summary", "/project_id_comparisons/1"),
        ("bytedance.promotion", None, "research-summary", "/mapping_rows/2"),
        ("bytedance.advertiser", None, "research-summary", "/mapping_rows/4"),
        ("kuaishou.material", None, "research-summary", "/mapping_rows/5"),
        ("kuaishou.unit", None, "research-summary", "/mapping_rows/7"),
        ("kuaishou.campaign", None, "research-summary", "/mapping_rows/8"),
        ("kuaishou.advertiser", None, "research-summary", "/mapping_rows/9"),
        ("tencent.material", None, "research-summary", "/mapping_rows/10"),
        ("tencent.creative", None, "research-summary", "/mapping_rows/11"),
        ("tencent.adgroup", None, "research-summary", "/mapping_rows/12"),
        ("tencent.advertiser", None, "research-summary", "/mapping_rows/14"),
        ("bytedance.material", "image", "research-summary", "/mid_summary/0"),
        ("bytedance.material", "video", "research-summary", "/mid_summary/2"),
        *[
            (f"bytedance.material.candidate.mid{i}", None, "research-summary", f"/mid_summary/{i - 1}")
            for i in (2, 4, 5, 6, 7, 8)
        ],
    ],
)
def test_join_evidence_counts_and_denominator_match_source(
    mapping_id: str, subtype: str | None, source_name: str, pointer: str,
) -> None:
    # Reviewed aggregate projections retain original JSON pointers and file hashes;
    # no private tmp files or probe execution are needed to reproduce this check.
    sources = json.loads(
        (ROOT / "tests/fixtures/join_key_evidence_sources.json").read_text(encoding="utf-8")
    )
    source = sources[source_name]
    row = source["excerpts"][pointer]
    mapping = next(m for m in join_key_registry()["mappings"] if m["mapping_id"] == mapping_id)
    fields = mapping["right"]["fields"]
    selected = next(f for f in fields if f["object_subtype"] == subtype) if subtype else fields[0]
    evidence = selected["candidate_evidence"] if subtype else mapping["evidence"]
    right_name = selected["reference"]["path"].removeprefix("data.list[].")
    if "material_intersection" in row:
        assert right_name == row["field"]
        comparison = row["material_intersection"]
        denominator = row["shape"]["sample_rows"]
        assert denominator == source["user_sample_rows"][mapping["platform"]]
    elif "evidence" in row:
        assert mapping["platform"] == row["platform"]
        left = mapping["left"]
        assert f'{left["operation_id"]}.{left["path"].removeprefix("data.list[].")}' == row["delivery_field"]
        assert f'{selected["reference"]["operation_id"]}.{right_name}' == row["user_field"]
        comparison = row["evidence"]
        denominator = row["right_shape"]["sample_rows"]
        assert denominator == source["user_sample_rows"][mapping["platform"]]
    else:
        comparison = row
        denominator = source["sample_rows"]["users"]
        if "user_field" in row:
            assert right_name == row["user_field"]
        else:
            assert {f["reference"]["path"] for f in fields} == {
                "data.list[].bytedanceMid1", "data.list[].bytedanceMid3",
            }
    expected = {
        "source": f"issue://mmm1h/gravity-insight/154#joinkey-research-{source_name}",
        "request_count": source["production_http_requests_this_run"],
        "observation_scope": "field_candidate" if "material_intersection" in row else "platform_object",
        "user_row_count": denominator,
        "left_distinct_count": comparison["left_unique"],
        "right_distinct_count": comparison["right_unique"],
        "intersection_distinct_count": comparison["intersection"],
    }
    assert {key: evidence[key] for key in expected} == expected


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
