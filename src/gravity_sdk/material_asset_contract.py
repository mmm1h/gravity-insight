"""Machine contract for response-bound material binary sources."""

from __future__ import annotations

from functools import lru_cache
import json
from typing import Any, Mapping, Sequence

from .errors import ContractChangedError, InputValidationError
from .paths import CONTRACT_ROOT


SCHEMA_VERSION = "gravity.material-asset-contract.v2"


def actual_value(
    field: str,
    actual: Any,
    allowed: Sequence[Any],
    next_action: str,
) -> InputValidationError:
    """Build an A-grade caller error with path, value, and exact remedy."""

    return InputValidationError(
        f"{field} has actual value {actual!r}; allowed values are {list(allowed)!r}",
        field=field,
        next_action=next_action,
    )


@lru_cache(maxsize=1)
def material_asset_contract() -> Mapping[str, Any]:
    try:
        value = json.loads(
            (CONTRACT_ROOT / "material-asset-v2.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise ContractChangedError(
            "material asset contract could not be loaded"
        ) from exc
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("accepts_caller_url") is not False
        or value.get("initial_host_policy") != "fresh_response_exact_host"
        or value.get("redirect_policy") != "same_host_only"
        or value.get("output_policy") != "root_bound_relative_atomic_no_clobber"
        or value.get("receipt_policy") != "value_free_http_references"
        or not isinstance(value.get("sources"), Mapping)
    ):
        raise ContractChangedError("material asset contract shape changed")
    _validate_sources(value["sources"])
    return value


def _validate_sources(sources: Mapping[str, Any]) -> None:
    if set(sources) != {"local", "bytedance_project"}:
        raise ContractChangedError("material asset source set changed")
    for source in sources.values():
        if not _valid_source(source):
            raise ContractChangedError("material asset source contract changed")
        for role in source["roles"].values():
            if not _valid_role(role):
                raise ContractChangedError("material asset role contract changed")


def _valid_source(source: Any) -> bool:
    return (
        isinstance(source, Mapping)
        and isinstance(source.get("operation_id"), str)
        and _valid_text_list(source.get("list_path"))
        and _valid_reference_fields(source.get("reference_fields"))
        and isinstance(source.get("roles"), Mapping)
        and set(source["roles"]) == {"file", "thumbnail"}
    )


def _valid_text_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item for item in value)
    )


def _valid_reference_fields(value: Any) -> bool:
    return (
        _valid_text_list(value)
        and all("url" not in item.casefold() for item in value)
    )


def _valid_role(role: Any) -> bool:
    if not isinstance(role, Mapping):
        return False
    media_type = role.get("observed_content_type")
    expected = {
        "image/jpeg": ({".jpg", ".jpeg"}, [{"offset": 0, "hex": "ffd8ff"}], 16 * 1024 * 1024),
        "video/mp4": ({".mp4"}, [{"offset": 4, "hex": "66747970"}], 1024 * 1024 * 1024),
    }.get(media_type)
    return (
        expected is not None
        and isinstance(role.get("url_field"), str)
        and _valid_extensions(role.get("extensions"), expected[0])
        and _valid_role_limits(role, expected[2])
        and _valid_signatures(role.get("magic_signatures"), expected[1])
    )


def _valid_extensions(value: Any, expected: set[str]) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item.startswith(".") for item in value)
        and set(value) == expected
    )


def _valid_role_limits(role: Mapping[str, Any], expected_size: int) -> bool:
    size = role.get("max_bytes")
    redirects = role.get("max_redirects")
    timeout = role.get("timeout_seconds")
    return (
        size == expected_size
        and redirects == 3
        and timeout == 120
    )


def _valid_signatures(value: Any, expected: list[dict[str, Any]]) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_valid_signature(item) for item in value)
        and value == expected
    )


def _valid_signature(value: Any) -> bool:
    if (
        not isinstance(value, Mapping)
        or not isinstance(value.get("offset"), int)
        or value["offset"] < 0
        or not isinstance(value.get("hex"), str)
        or not value["hex"]
        or len(value["hex"]) % 2
    ):
        return False
    try:
        bytes.fromhex(value["hex"])
    except ValueError:
        return False
    return True


def source_contract(source: str) -> Mapping[str, Any]:
    contract = material_asset_contract()
    sources = contract["sources"]
    selected = sources.get(source) if isinstance(source, str) else None
    if not isinstance(selected, Mapping):
        raise actual_value(
            field="source",
            actual=source,
            allowed=tuple(sources),
            next_action=(
                "Run `gravity materials fetch --help` and choose one documented "
                "response source."
            ),
        )
    return selected


__all__ = ["SCHEMA_VERSION", "material_asset_contract", "source_contract"]
