"""Purpose-built private projection for material file transfer sources."""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
import time
from typing import Any

from .errors import (
    ContractChangedError,
    GravityInsightError,
    ParentRequiredError,
    PermissionUnavailableError,
    UpstreamError,
)
from .material_asset_contract import material_asset_contract


_PRIVATE_ROWS: ContextVar[list[Mapping[str, Any]] | None] = ContextVar(
    "gravity_material_asset_private_rows", default=None
)


@contextmanager
def _capture_material_asset_source() -> Any:
    rows: list[Mapping[str, Any]] = []
    token = _PRIVATE_ROWS.set(rows)
    try:
        yield rows
    finally:
        _PRIVATE_ROWS.reset(token)


def _capture_private_material_asset_rows(
    operation_id: str, payload: Mapping[str, Any]
) -> None:
    target = _PRIVATE_ROWS.get()
    if target is not None:
        target.extend(_private_material_asset_rows(operation_id, payload))


def _read_material_asset_source(
    client: Any, operation_id: str, inputs: Mapping[str, Any] | None
) -> tuple[dict[str, Any], tuple[Mapping[str, Any], ...]]:
    from .client import _audit_read, _error_status

    started = time.monotonic()
    with _capture_material_asset_source() as private_rows:
        try:
            client._operation_catalog.guard(operation_id)
            operation = client._executor._policy.authorize_operation(operation_id)
            normalized_inputs = operation.validate_inputs(inputs)
            envelope = client._executor.execute(
                operation_id, normalized_inputs
            ).to_dict()
        except (UpstreamError, ParentRequiredError, PermissionUnavailableError) as exc:
            envelope = client._error_envelope(operation_id, exc)
        except GravityInsightError as exc:
            status = _error_status(exc)
            client._operation_catalog.record_upstream_exception(
                operation_id, exc, status=status
            )
            _audit_read(operation_id, status, started)
            raise
    client._operation_catalog.record_envelope(operation_id, envelope)
    _audit_read(
        operation_id,
        str(envelope.get("status", "success")),
        started,
        envelope,
    )
    return envelope, tuple(private_rows)


def _read_bound_material_asset_source(
    client: Any, operation_id: str, inputs: Mapping[str, Any]
) -> tuple[Mapping[str, Any], tuple[Mapping[str, Any], ...]]:
    injected = getattr(client, "_read_material_asset_source", None)
    if callable(injected):
        return injected(operation_id, inputs)
    return _read_material_asset_source(client, operation_id, inputs)


def _private_material_asset_rows(
    operation_id: str, payload: Mapping[str, Any]
) -> tuple[Mapping[str, Any], ...]:
    """Retain only transfer-bound scalars; never place them in a read envelope."""

    path, fields = _source_binding(operation_id)
    selected: Any = payload
    for part in path:
        selected = selected.get(part) if isinstance(selected, Mapping) else None
    if not isinstance(selected, list):
        return ()
    rows: list[Mapping[str, Any]] = []
    for item in selected:
        if not isinstance(item, Mapping):
            continue
        rows.append({
            field: item[field]
            for field in fields
            if field in item
            and (
                item[field] is None
                or isinstance(item[field], (str, int, float))
                and not isinstance(item[field], bool)
            )
        })
    return tuple(rows)


def _source_binding(operation_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    sources = material_asset_contract()["sources"]
    matches = [
        source
        for source in sources.values()
        if source.get("operation_id") == operation_id
    ]
    if len(matches) != 1:
        raise ContractChangedError("material asset private source operation changed")
    source = matches[0]
    fields = [*source["reference_fields"]]
    fields.extend(role["url_field"] for role in source["roles"].values())
    for name in ("declared_size_field", "declared_md5_field"):
        if isinstance(source.get(name), str):
            fields.append(source[name])
    return tuple(source["list_path"]), tuple(dict.fromkeys(fields))


__all__: list[str] = []
