"""Machine contract for response-bound material binary sources."""

from __future__ import annotations

from functools import lru_cache
import json
from typing import Any, Mapping, Sequence

from .errors import ContractChangedError, InputValidationError
from .paths import CONTRACT_ROOT


SCHEMA_VERSION = "gravity.material-asset-contract.v1"


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
            (CONTRACT_ROOT / "material-asset-v1.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError) as exc:
        raise ContractChangedError(
            "material asset contract could not be loaded"
        ) from exc
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("accepts_caller_url") is not False
        or not isinstance(value.get("sources"), Mapping)
    ):
        raise ContractChangedError("material asset contract shape changed")
    return value


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
