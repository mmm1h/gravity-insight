"""Context Provider, Item, Requirement, and Pack contract primitives."""

from __future__ import annotations

import copy
import hashlib
import re
from datetime import date, datetime, timezone
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    load_json_object,
    validate_schema,
)


PROVIDER_SCHEMA_VERSION = "gravity.context-provider.v1"
ITEM_SCHEMA_VERSION = "gravity.context-item.v1"
REQUIREMENT_SCHEMA_VERSION = "gravity.context-requirement.v1"
PACK_SCHEMA_VERSION = "gravity.context-pack.v1"
PROJECT_REPO_PROVIDER_URI = "context-provider://gravity/project-repo@1"
_PROVIDER_SCHEMA = "context-provider-v1.schema.json"
_ITEM_SCHEMA = "context-item-v1.schema.json"
_REQUIREMENT_SCHEMA = "context-requirement-v1.schema.json"
_PACK_SCHEMA = "context-pack-v1.schema.json"
_ITEM_REFERENCE_SCHEMA = "context-item-reference-v1.schema.json"
_PROVIDER_ROOT = Path(__file__).resolve().parent / "contracts" / "context-providers"
_PROVIDER_URI = re.compile(
    r"^context-provider://[a-z0-9.-]+/[a-z0-9./-]+@(?P<version>[1-9][0-9]*)$"
)
AUTHORITY_ORDER = (
    "project_authoritative",
    "canonical",
    "supporting",
    "declared_intent",
    "unverified",
)


class ContextContractError(AgentRuntimeContractError):
    """A Context contract is invalid or internally contradictory."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def clamp_context_authority(authority: str, ceiling: str) -> str:
    """Return the weaker of an Item's claim and its locked Provider ceiling."""

    return AUTHORITY_ORDER[
        max(AUTHORITY_ORDER.index(authority), AUTHORITY_ORDER.index(ceiling))
    ]


def compile_context_provider(value: Mapping[str, Any]) -> dict[str, Any]:
    contract = _object(value, "CONTEXT_PROVIDER_INVALID", "Context Provider")
    _schema(contract, _PROVIDER_SCHEMA, "CONTEXT_PROVIDER_INVALID", "Context Provider")
    match = _PROVIDER_URI.fullmatch(str(contract["uri"]))
    if match is None or int(match.group("version")) != contract["version"]:
        raise ContextContractError(
            "CONTEXT_PROVIDER_INVALID", "Provider URI and version disagree"
        )
    normalized = copy.deepcopy(contract)
    for field in ("effects", "resource_types", "supports"):
        normalized[field] = sorted(normalized[field])
    return {"contract": normalized, "digest": canonical_digest(normalized)}


@lru_cache(maxsize=1)
def _cached_project_repo_provider() -> dict[str, Any]:
    path = _PROVIDER_ROOT / "project-repo.v1.json"
    return compile_context_provider(load_json_object(path, "Project Repo Provider"))


def project_repo_provider_artifact() -> dict[str, Any]:
    return copy.deepcopy(_cached_project_repo_provider())


def compile_context_requirement(value: Mapping[str, Any]) -> dict[str, Any]:
    contract = _object(value, "CONTEXT_REQUIREMENT_INVALID", "Context Requirement")
    _schema(
        contract,
        _REQUIREMENT_SCHEMA,
        "CONTEXT_REQUIREMENT_INVALID",
        "Context Requirement",
    )
    if contract["provider_uri"] != PROJECT_REPO_PROVIDER_URI:
        raise ContextContractError(
            "CONTEXT_PROVIDER_UNSUPPORTED", "Requirement Provider is not installed"
        )
    _unique(contract["items"], "item_id", "Context item IDs")
    _unique(contract["items"], "path", "Context item paths")
    for item in contract["items"]:
        _normalized_path(item["path"])
        _time_range(item["valid_time"], "valid_time")
        _date_range(item["effective_range"], "effective_range")
        if item["authority"] in {"declared_intent", "unverified"} and item["required"]:
            raise ContextContractError(
                "CONTEXT_REQUIREMENT_INVALID",
                "Required Context cannot use hypothesis-only or unverified authority",
            )
    freshness = contract["freshness_policy"]
    if freshness["as_of"] is not None:
        _day(freshness["as_of"], "freshness_policy.as_of")
    authority = contract["authority_policy"]
    if "unverified" in authority["required"] or (
        "supporting" in authority["required"] and not authority["allow_supporting"]
    ):
        raise ContextContractError(
            "CONTEXT_REQUIREMENT_INVALID",
            "Required claim authority contradicts the Context authority policy",
        )
    normalized = copy.deepcopy(contract)
    normalized["subject_entities"] = sorted(normalized["subject_entities"])
    normalized["required_windows"] = sorted(normalized["required_windows"])
    normalized["authority_policy"]["required"] = sorted(
        normalized["authority_policy"]["required"]
    )
    normalized["allowed_sensitivity"] = sorted(normalized["allowed_sensitivity"])
    normalized["items"] = sorted(normalized["items"], key=lambda item: item["item_id"])
    for item in normalized["items"]:
        item["entity_refs"] = sorted(item["entity_refs"])
        item["supersedes"] = sorted(item["supersedes"])
    return {"contract": normalized, "digest": canonical_digest(normalized)}


def validate_context_item(value: Mapping[str, Any]) -> dict[str, Any]:
    item = _object(value, "CONTEXT_ITEM_INVALID", "Context Item")
    _schema(item, _ITEM_SCHEMA, "CONTEXT_ITEM_INVALID", "Context Item")
    _time_range(item["valid_time"], "valid_time")
    _date_range(item["effective_range"], "effective_range")
    _observed_at(item["observed_at"])
    if item["citation"]["line_start"] > item["citation"]["line_end"]:
        raise ContextContractError(
            "CONTEXT_CITATION_INVALID", "Context citation line range is reversed"
        )
    if item["uri"] in item["supersedes"]:
        raise ContextContractError(
            "CONTEXT_SUPERSESSION_INVALID", "Context Item cannot supersede itself"
        )
    normalized = copy.deepcopy(item)
    normalized["entity_refs"] = sorted(normalized["entity_refs"])
    normalized["resolved_entity_refs"] = sorted(normalized["resolved_entity_refs"])
    normalized["supersedes"] = sorted(normalized["supersedes"])
    _validate_item_content(normalized)
    return normalized


def validate_context_pack(value: Mapping[str, Any]) -> dict[str, Any]:
    pack = _object(value, "CONTEXT_PACK_INVALID", "Context Pack")
    _schema(pack, _PACK_SCHEMA, "CONTEXT_PACK_INVALID", "Context Pack")
    items = [validate_context_item(item) for item in pack["items"]]
    if items != pack["items"]:
        raise ContextContractError(
            "CONTEXT_PACK_INVALID", "Context Pack item normalization changed"
        )
    _unique(items, "item_id", "Context Pack item IDs", reason="CONTEXT_PACK_INVALID")
    _unique(items, "uri", "Context Pack item URIs", reason="CONTEXT_PACK_INVALID")
    if items != sorted(items, key=lambda item: item["item_id"]):
        raise ContextContractError(
            "CONTEXT_PACK_INVALID", "Context Pack items are not deterministic"
        )
    if any(item["provider_uri"] != pack["provider"].get("uri") for item in items):
        raise ContextContractError(
            "CONTEXT_PACK_INVALID", "Context Pack item Provider identities disagree"
        )
    if any(
        item["source_revision"] != pack["provider"].get("source_revision")
        for item in items
    ):
        raise ContextContractError(
            "CONTEXT_PACK_INVALID", "Context Pack item revisions disagree"
        )
    if pack["alignment"].get("matched") != sorted(item["uri"] for item in items):
        raise ContextContractError(
            "CONTEXT_PACK_INVALID", "Context Pack matched alignment changed"
        )
    _validate_pack_metadata(pack, items)
    expected = context_pack_digest(pack)
    if pack["pack_digest"] != expected:
        raise ContextContractError(
            "CONTEXT_PACK_DIGEST_MISMATCH", "Context Pack digest changed"
        )
    return copy.deepcopy(pack)


def _validate_pack_metadata(
    pack: Mapping[str, Any], items: Sequence[Mapping[str, Any]]
) -> None:
    audit_fields = {
        "provider_rpc_called",
        "provider_internal_io_controlled",
        "provider_internal_network",
    }
    present = audit_fields.intersection(pack)
    if present and present != audit_fields:
        raise ContextContractError(
            "CONTEXT_PACK_INVALID", "Context Pack Provider audit fields are incomplete"
        )
    _validate_requested_time(pack["requested_time"])
    _validate_pack_order(pack)
    expected_status, expected_claims = _expected_pack_readiness(pack, items)
    if pack["status"] != expected_status or pack["claims"] != expected_claims:
        raise ContextContractError(
            "CONTEXT_PACK_INVALID", "Context Pack readiness or claims changed"
        )
    _validate_pack_budget(pack["budget"], items)


def _validate_requested_time(value: Mapping[str, Any]) -> None:
    if len(value) > 8 or any(
        re.fullmatch(r"[a-z][a-z0-9_]*", name) is None for name in value
    ):
        raise ContextContractError(
            "CONTEXT_PACK_INVALID", "Context Pack requested windows are invalid"
        )
    for window in value.values():
        _time_range(window, "requested_time")


def _validate_pack_order(pack: Mapping[str, Any]) -> None:
    for field in ("subject_entities", "resolved_entities"):
        if pack[field] != sorted(pack[field]):
            raise ContextContractError(
                "CONTEXT_PACK_INVALID", f"Context Pack {field} is not deterministic"
            )
    _ordered_unique(pack["required_status"], "item_id", "required status")
    _ordered_unique(pack["conflicts"], "fact_id", "conflicts")
    _ordered_unique(pack["gaps"], "item_id", "gaps")
    _ordered_unique(pack["alignment"]["excluded"], "item_id", "excluded items")
    _ordered_unique(
        pack["alignment"]["superseded"], "item_id", "superseded items"
    )


def _expected_pack_readiness(
    pack: Mapping[str, Any], items: Sequence[Mapping[str, Any]]
) -> tuple[str, dict[str, Any]]:
    required_gaps = [gap for gap in pack["gaps"] if gap["required"]]
    optional_gaps = [gap for gap in pack["gaps"] if not gap["required"]]
    expected_status = (
        "blocked" if required_gaps else "partial" if optional_gaps else "available"
    )
    authorities = {item["authority"] for item in items}
    ceiling = next(
        (
            name
            for name in AUTHORITY_ORDER
            if name in authorities
        ),
        "none",
    )
    required = set(pack["authority_policy"]["required"])
    expected_claims = {
        "confirmed_claims_allowed": not required_gaps and bool(authorities & required),
        "optional_context_complete": not optional_gaps,
        "authority_ceiling": ceiling,
    }
    return expected_status, expected_claims


def _ordered_unique(
    values: Sequence[Mapping[str, Any]], key: str, label: str
) -> None:
    identities = [item[key] for item in values]
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise ContextContractError(
            "CONTEXT_PACK_INVALID", f"Context Pack {label} is not deterministic"
        )


def _validate_pack_budget(
    budget: Mapping[str, Any], items: Sequence[Mapping[str, Any]]
) -> None:
    minimum_bytes = sum(len(item["content"].encode("utf-8")) for item in items)
    minimum_lines = sum(max(1, len(item["content"].splitlines())) for item in items)
    invalid = (
        budget["used_files"] < len(items)
        or budget["used_bytes"] < minimum_bytes
        or budget["used_lines"] < minimum_lines
        or budget["used_files"] > budget["max_files"]
        or budget["used_bytes"] > budget["max_total_bytes"]
        or budget["used_lines"] > budget["max_total_lines"]
    )
    if invalid:
        raise ContextContractError(
            "CONTEXT_PACK_INVALID", "Context Pack budget accounting changed"
        )


def _validate_item_content(item: Mapping[str, Any]) -> None:
    encoded = item["content"].encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != item["content_hash"]:
        raise ContextContractError(
            "CONTEXT_ITEM_HASH_MISMATCH", "Context Item content hash changed"
        )
    citation = item["citation"]
    _normalized_path(citation["path"])
    cited_lines = citation["line_end"] - citation["line_start"] + 1
    if cited_lines != max(1, len(item["content"].splitlines())):
        raise ContextContractError(
            "CONTEXT_CITATION_INVALID", "Context citation does not cover its content"
        )


def context_pack_digest(pack: Mapping[str, Any]) -> str:
    selected = copy.deepcopy(dict(pack))
    selected.pop("pack_digest", None)
    selected["items"] = [context_item_reference(item) for item in selected["items"]]
    return canonical_digest(selected)


def context_item_reference(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(item[key])
        for key in (
            "schema_version",
            "uri",
            "provider_uri",
            "item_id",
            "fact_id",
            "resource_type",
            "title",
            "entity_refs",
            "resolved_entity_refs",
            "valid_time",
            "effective_range",
            "observed_at",
            "authority",
            "source_revision",
            "content_hash",
            "freshness",
            "source_trust",
            "supersedes",
            "sensitivity",
            "role",
            "citation",
        )
    }


def public_context_reference(pack: Mapping[str, Any]) -> dict[str, Any]:
    selected = validate_context_pack(pack)
    selected["items"] = [context_item_reference(item) for item in selected["items"]]
    return validate_public_context_pack(selected)


def validate_public_context_pack(value: Mapping[str, Any]) -> dict[str, Any]:
    pack = _object(value, "CONTEXT_PACK_INVALID", "Public Context Pack")
    _schema(pack, _PACK_SCHEMA, "CONTEXT_PACK_INVALID", "Public Context Pack")
    _validate_public_items(pack)
    _validate_public_pack_metadata(pack)
    return copy.deepcopy(pack)


def _validate_public_items(pack: Mapping[str, Any]) -> None:
    for item in pack["items"]:
        _validate_public_item(item, pack["provider"])
    _unique(pack["items"], "item_id", "Context Pack item IDs", reason="CONTEXT_PACK_INVALID")
    _unique(pack["items"], "uri", "Context Pack item URIs", reason="CONTEXT_PACK_INVALID")
    if pack["items"] != sorted(pack["items"], key=lambda item: item["item_id"]):
        raise ContextContractError(
            "CONTEXT_PACK_INVALID", "Context Pack items are not deterministic"
        )
    if pack["alignment"]["matched"] != sorted(item["uri"] for item in pack["items"]):
        raise ContextContractError(
            "CONTEXT_PACK_INVALID", "Context Pack matched alignment changed"
        )


def _validate_public_item(
    item: Mapping[str, Any], provider: Mapping[str, Any]
) -> None:
    _schema(
        item,
        _ITEM_REFERENCE_SCHEMA,
        "CONTEXT_PACK_INVALID",
        "Context Item reference",
    )
    checks = (
        item["entity_refs"] == sorted(item["entity_refs"]),
        item["resolved_entity_refs"] == sorted(item["resolved_entity_refs"]),
        item["supersedes"] == sorted(item["supersedes"]),
        item["provider_uri"] == provider["uri"],
        item["source_revision"] == provider["source_revision"],
        item["citation"]["line_start"] <= item["citation"]["line_end"],
    )
    if not all(checks):
        raise ContextContractError(
            "CONTEXT_PACK_INVALID", "Context Item reference changed"
        )


def _validate_public_pack_metadata(pack: Mapping[str, Any]) -> None:
    _validate_requested_time(pack["requested_time"])
    _validate_pack_order(pack)
    expected_status, expected_claims = _expected_pack_readiness(pack, pack["items"])
    if pack["status"] != expected_status or pack["claims"] != expected_claims:
        raise ContextContractError(
            "CONTEXT_PACK_INVALID", "Context Pack readiness or claims changed"
        )
    if (
        pack["budget"]["used_files"] < len(pack["items"])
        or pack["budget"]["used_files"] > pack["budget"]["max_files"]
        or pack["budget"]["used_bytes"] > pack["budget"]["max_total_bytes"]
        or pack["budget"]["used_lines"] > pack["budget"]["max_total_lines"]
        or pack["pack_digest"] != context_pack_digest(pack)
    ):
        raise ContextContractError(
            "CONTEXT_PACK_DIGEST_MISMATCH", "Public Context Pack digest changed"
        )


def date_range_contains(
    value: Mapping[str, Any], start: date, end: date
) -> bool:
    selected_start, selected_end = _date_range(value, "date range")
    return (selected_start is None or selected_start <= start) and (
        selected_end is None or end <= selected_end
    )


def time_range_contains(
    value: Mapping[str, Any], start: date, end: date, timezone_name: str
) -> bool:
    selected_start, selected_end, selected_timezone = _time_range(value, "time range")
    return (
        selected_timezone == timezone_name
        and (selected_start is None or selected_start <= start)
        and (selected_end is None or end <= selected_end)
    )


def observed_date(value: str) -> date:
    return _observed_at(value).date()


def normalized_requirement_path(value: str) -> str:
    return _normalized_path(value)


def _schema(
    value: Mapping[str, Any], schema: str, reason: str, label: str
) -> None:
    try:
        validate_schema(value, schema, label)
    except AgentRuntimeContractError as exc:
        raise ContextContractError(reason, str(exc)) from exc


def _time_range(
    value: Mapping[str, Any], label: str
) -> tuple[date | None, date | None, str]:
    start, end = _date_range(value, label)
    timezone_name = str(value["timezone"])
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ContextContractError(
            "CONTEXT_TIME_INVALID", f"{label} timezone is unknown"
        ) from exc
    return start, end, timezone_name


def _date_range(
    value: Mapping[str, Any], label: str
) -> tuple[date | None, date | None]:
    start = _day(value["start"], f"{label}.start") if value["start"] is not None else None
    end = _day(value["end"], f"{label}.end") if value["end"] is not None else None
    if start is not None and end is not None and start > end:
        raise ContextContractError(
            "CONTEXT_TIME_INVALID", f"{label} range is reversed"
        )
    return start, end


def _day(value: Any, label: str) -> date:
    try:
        selected = date.fromisoformat(value)
    except (TypeError, ValueError):
        selected = None
    if selected is None or selected.isoformat() != value:
        raise ContextContractError(
            "CONTEXT_TIME_INVALID", f"{label} must be canonical YYYY-MM-DD"
        )
    return selected


def _observed_at(value: Any) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ContextContractError(
            "CONTEXT_OBSERVED_AT_INVALID", "observed_at must be canonical UTC"
        )
    try:
        selected = datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise ContextContractError(
            "CONTEXT_OBSERVED_AT_INVALID", "observed_at must be canonical UTC"
        ) from exc
    rendered = selected.isoformat(timespec="seconds").replace("+00:00", "Z")
    if rendered != value:
        raise ContextContractError(
            "CONTEXT_OBSERVED_AT_INVALID", "observed_at must use second precision"
        )
    return selected


def _normalized_path(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ContextContractError(
            "CONTEXT_PATH_INVALID", "Context path must be normalized"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ContextContractError(
            "CONTEXT_PATH_INVALID", "Context path escapes the project"
        )
    if path.as_posix() != value:
        raise ContextContractError(
            "CONTEXT_PATH_INVALID", "Context path is not canonical"
        )
    return value


def _unique(
    values: Sequence[Mapping[str, Any]],
    key: str,
    label: str,
    *,
    reason: str = "CONTEXT_REQUIREMENT_INVALID",
) -> None:
    identities = [item[key] for item in values]
    if len(identities) != len(set(identities)):
        raise ContextContractError(
            reason, f"{label} are duplicated"
        )


def _object(value: Any, reason: str, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContextContractError(reason, f"{label} must be an object")
    return copy.deepcopy(dict(value))


__all__ = [
    "AUTHORITY_ORDER",
    "ContextContractError",
    "ITEM_SCHEMA_VERSION",
    "PACK_SCHEMA_VERSION",
    "PROJECT_REPO_PROVIDER_URI",
    "PROVIDER_SCHEMA_VERSION",
    "REQUIREMENT_SCHEMA_VERSION",
    "compile_context_provider",
    "compile_context_requirement",
    "clamp_context_authority",
    "context_item_reference",
    "context_pack_digest",
    "date_range_contains",
    "normalized_requirement_path",
    "observed_date",
    "project_repo_provider_artifact",
    "public_context_reference",
    "time_range_contains",
    "validate_context_item",
    "validate_context_pack",
    "validate_public_context_pack",
]
