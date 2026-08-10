from __future__ import annotations

from gravity_sdk.prober.cli import build_parser
from gravity_sdk.prober.verdict_probe import (
    MATERIAL_USER_OPERATION,
    profile_verdict_payload,
)


def test_material_user_variation_resolves_as_personnel_permission() -> None:
    result = profile_verdict_payload(
        MATERIAL_USER_OPERATION,
        {"data": {"list": [{"is_superuser": False}, {"is_superuser": True}]}},
    )

    assert result["status"] == "resolved_by_probe"
    assert result["decision"] == "sensitive_personnel_permission"
    assert result["field_profiles"]["is_superuser"]["distribution"] == {
        "false": 1,
        "true": 1,
        "null": 0,
        "other_type": 0,
    }
    assert result["field_profiles"]["is_superuser"]["distinct_boolean_count"] == 2


def test_material_user_single_value_narrows_question() -> None:
    result = profile_verdict_payload(
        MATERIAL_USER_OPERATION,
        {"data": {"list": [{"is_superuser": False}, {"is_superuser": False}]}},
    )

    assert result["status"] == "narrowed"
    assert "逐行表示对应用户" in result["remaining_question"]
    assert "true=0、false=2" in result["remaining_question"]


def test_empty_sample_stays_blocked() -> None:
    result = profile_verdict_payload(
        MATERIAL_USER_OPERATION, {"data": {"list": []}}
    )

    assert result["status"] == "still_blocked"
    assert result["row_count"] == 0


def test_cli_exposes_bounded_verdict_probe_command() -> None:
    args = build_parser().parse_args(
        ["verdict-probe", MATERIAL_USER_OPERATION, "--request-limit", "3"]
    )

    assert args.command == "verdict-probe"
    assert args.request_limit == 3
