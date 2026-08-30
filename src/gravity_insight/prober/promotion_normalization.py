"""Decision-completeness normalization for promoted contracts."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .drafts import DEFAULT_REDACT_FIELDS


def complete_privacy_redactions(operation: dict[str, Any]) -> None:
    privacy = operation["privacy_policy"]
    privacy["redact_fields"] = list(
        dict.fromkeys([*DEFAULT_REDACT_FIELDS, *privacy.get("redact_fields", [])])
    )


_SUPPORTED_PLACEHOLDERS = frozenset(
    {
        "$today", "$yesterday", "$analysis_query_id", "$first_app_id",
        "$first_event_name", "$first_user_property_name",
        "$first_event_property_name", "$first_segment_id",
        "$first_report_config_id", "$first_dashboard_id",
        "$first_dashboard_space_id", "$first_client_id",
        "$first_bytedance_advertiser_id", "$first_tencent_advertiser_id",
        "$first_kuaishou_advertiser_id", "$first_preset_template_id",
        "$first_preset_template_category",
    }
)


def _placeholder_supported(value: Any) -> bool:
    if isinstance(value, str):
        return (
            not value.startswith("$") or value in _SUPPORTED_PLACEHOLDERS
            or value.startswith("$first_order_") or value.startswith("$parent:")
        )
    if isinstance(value, Mapping):
        return all(_placeholder_supported(item) for item in value.values())
    if isinstance(value, list):
        return all(_placeholder_supported(item) for item in value)
    return True


def _projection_missing(operation: Mapping[str, Any]) -> list[str]:
    projection = operation.get("response_projection")
    if not isinstance(projection, Mapping):
        return ["response_projection"]
    exposed = (
        len(projection.get("item_keys", []))
        + len(set(projection.get("data_keys", [])) - {"list", "page_info"})
        + len(projection.get("data_scalar_list_types", {}))
    )
    return [] if exposed else ["response_projection"]


def _privacy_missing(
    draft: Mapping[str, Any], operation: Mapping[str, Any],
    exposes: Callable[[str, Mapping[str, Any]], bool],
) -> list[str]:
    candidates = draft.get("candidate_fields")
    if not isinstance(candidates, list):
        return ["privacy_classification"]
    projection = operation.get("response_projection")
    manual_review = any(
        isinstance(item, Mapping)
        and item.get("privacy_classification") == "manual_review"
        for item in candidates
    )
    unsafe_exposed = any(
        isinstance(item, Mapping)
        and item.get("privacy_classification") != "non_sensitive"
        and isinstance(projection, Mapping)
        and exposes(str(item.get("path", "")), projection)
        for item in candidates
    )
    missing = ["field_review_required"] if manual_review else []
    if unsafe_exposed:
        missing.append("unclassified_or_sensitive_field_exposed")
    return missing


def _runtime_missing(
    draft: Mapping[str, Any], operation: Mapping[str, Any], latest: Mapping[str, Any]
) -> list[str]:
    missing: list[str] = []
    pagination = operation.get("pagination")
    if (
        isinstance(pagination, Mapping) and pagination.get("kind") != "none"
        and not bool(latest.get("pagination_verified"))
    ):
        missing.append("pagination_unverified")
    live_probe = operation.get("live_probe")
    live_inputs = live_probe.get("inputs") if isinstance(live_probe, Mapping) else None
    if not _placeholder_supported(live_inputs):
        missing.append("runtime_probe_placeholder_unsupported")
    blockers = draft.get("blockers")
    if isinstance(blockers, list):
        missing.extend(
            str(item.get("code")) for item in blockers
            if isinstance(item, Mapping) and item.get("code") != "promotion_pending"
        )
    return missing


def evaluate_gate(
    source: Mapping[str, Any],
    exposes: Callable[[str, Mapping[str, Any]], bool],
) -> dict[str, Any]:
    draft = source.get("draft") if isinstance(source, Mapping) else None
    operation = source.get("operation") if isinstance(source, Mapping) else None
    if not isinstance(draft, Mapping) or not isinstance(operation, Mapping):
        return {"eligible": False, "missing": ["draft_metadata"]}
    evidence = draft.get("probe_evidence")
    latest = evidence[-1] if isinstance(evidence, list) and evidence else {}
    latest = latest if isinstance(latest, Mapping) else {}
    missing = [] if bool(latest.get("successful")) else ["successful_probe"]
    missing.extend(_projection_missing(operation))
    missing.extend(_privacy_missing(draft, operation, exposes))
    missing.extend(_runtime_missing(draft, operation, latest))
    if str(operation.get("path_template", "")).startswith("/openapi/"):
        missing.append("stable_runtime_route_unsupported")
    if operation.get("auth_profile") == "gravity_openapi_signature":
        missing.append("openapi_developer_credentials_unavailable")
    return {"eligible": not missing, "missing": sorted(set(missing))}


def _candidate_field_reasons(
    draft: Mapping[str, Any], operation: Mapping[str, Any],
    exposes: Callable[[str, Mapping[str, Any]], bool],
) -> list[str]:
    fields = draft.get("candidate_fields", [])
    if not isinstance(fields, list):
        return ["candidate_fields_missing", "no_sensitive_fields"]
    sensitive = [
        item for item in fields if isinstance(item, Mapping)
        and item.get("privacy_classification") == "sensitive"
    ]
    manual = any(
        isinstance(item, Mapping)
        and item.get("privacy_classification") == "manual_review" for item in fields
    )
    projection = operation.get("response_projection", {})
    reasons = [] if sensitive else ["no_sensitive_fields"]
    if manual:
        reasons.append("manual_review_required")
    if not isinstance(projection, Mapping) or any(
        exposes(str(item.get("path", "")), projection) for item in sensitive
    ):
        reasons.append("sensitive_field_exposed")
    return reasons


def _discovery_observation(
    evidence: Mapping[str, Any], operation_id: str
) -> Mapping[str, Any] | None:
    observations = evidence.get("http", [])
    if not isinstance(observations, list):
        return None
    discovery = [
        item for item in observations if isinstance(item, Mapping)
        and item.get("operation_id") == operation_id
        and item.get("purpose") == "discovery"
    ]
    return discovery[-1] if discovery else None


def _data_shape_observed(paths: Any) -> bool:
    if not isinstance(paths, list):
        return False
    return any(
        isinstance(item, Mapping) and (
            str(item.get("path")).startswith("$.data.")
            or str(item.get("path")).startswith("$.data[]")
        ) for item in paths
    )


def _discovery_reasons(
    evidence: Mapping[str, Any], primary: Mapping[str, Any] | None,
    fingerprint: Callable[[Any], str],
) -> list[str]:
    status = primary.get("http_status") if primary is not None else None
    sketch = primary.get("response_schema_sketch") if primary is not None else None
    paths = sketch.get("paths", []) if isinstance(sketch, Mapping) else []
    reasons = [] if isinstance(status, int) and 200 <= status < 300 else [
        "successful_http_discovery_unproven"
    ]
    if not _data_shape_observed(paths):
        reasons.append("nonempty_data_shape_unproven")
    if not isinstance(sketch, Mapping) or evidence.get("raw_schema_fingerprint") != fingerprint(sketch):
        reasons.append("raw_schema_fingerprint_mismatch")
    request_stats = evidence.get("request_stats", {})
    if not isinstance(request_stats, Mapping) or int(request_stats.get("failed", 0)) != 0:
        reasons.append("failed_request_observed")
    return reasons


def legacy_privacy_evidence_reusable(
    source: Mapping[str, Any], evidence: Mapping[str, Any],
    exposes: Callable[[str, Mapping[str, Any]], bool],
    fingerprint: Callable[[Any], str],
) -> tuple[bool, list[str]]:
    operation = source.get("operation", {})
    draft = source.get("draft", {})
    operation_id = str(operation.get("operation_id", ""))
    reasons: list[str] = []
    if evidence.get("conclusion") != "privacy_review_required":
        reasons.append("not_legacy_privacy_short_circuit")
    if str(evidence.get("operation_id", "")) != operation_id:
        reasons.append("operation_id_mismatch")
    reasons.extend(_candidate_field_reasons(draft, operation, exposes))
    reasons.extend(_discovery_reasons(
        evidence, _discovery_observation(evidence, operation_id), fingerprint
    ))
    return not reasons, sorted(set(reasons))
