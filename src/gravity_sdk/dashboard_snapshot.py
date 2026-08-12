"""Bounded control-plane snapshots for one Analysis dashboard.

The product resolves an explicit dashboard reference from the governed tree,
then composes five existing stable reads.  It intentionally does not expose
or interpret dashboard/query configuration, conditions, or user names.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import runtime
from .composite_batch import (
    annotate_result,
    composite_envelope,
    ordered_results,
    validate_composite_bounds,
)
from .composite_catalog import stable_operation
from .dashboard_snapshot_safety import safe_source_data
from .errors import (
    ContractChangedError,
    ErrorCode,
    ErrorDetail,
    GravityInsightError,
    InputValidationError,
    LocalIOError,
    PaginationError,
)


SCHEMA_VERSION = "gravity-insight.dashboard-snapshot.v1"
DEFAULT_CONCURRENCY = 5
MAX_CONCURRENCY = 24
MAX_TREE_DEPTH = 16
MIN_SNAPSHOT_ITEMS = 7  # five sources plus one root and one dashboard node
_SUCCESS_STATUSES = frozenset({"success", "empty", "contract_changed_additive"})
_BUILTIN_ERROR_CODES = frozenset(item.value for item in ErrorCode)


@dataclass(frozen=True)
class DashboardIdentity:
    dashboard_id: str
    name: str
    space_id: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.dashboard_id, "name": self.name, "space_id": self.space_id}


@dataclass(frozen=True)
class DashboardSource:
    source: str
    operation_id: str
    scope: str
    paginated: bool = False


def _source(
    source: str, resource: str, action: str, scope: str
) -> DashboardSource:
    operation = stable_operation("analysis", resource, action=action)
    return DashboardSource(
        source, operation.operation_id, scope, operation.paginated
    )


TREE_OPERATION = stable_operation("analysis", "dashboard_tree", action="tree").operation_id
DASHBOARD_SNAPSHOT_SOURCES = (
    _source("detail", "dashboard", "detail", "dashboard"),
    _source("members", "dashboard_members", "list", "dashboard"),
    _source("space_members", "dashboard_space_members", "list", "space"),
    _source("favourites", "dashboard_condition_favourite", "list", "dashboard"),
    _source("default_favourite", "dashboard_condition_favourite_default", "get", "dashboard"),
)


def dashboard_snapshot(
    client: Any,
    app_id: str | int,
    ref: str | int,
    *,
    max_workers: int = DEFAULT_CONCURRENCY,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Resolve one dashboard and return five safe, ordered source results."""

    selected_app = _positive_app_id(app_id)
    selected_ref = _reference(ref)
    workers = _workers(max_workers)
    pages, items = validate_composite_bounds(
        max_pages, max_items, minimum_items=MIN_SNAPSHOT_ITEMS
    )
    tree = _read_tree(client, selected_app)
    candidates, tree_items = _dashboard_identities(
        tree, max_nodes=items - len(DASHBOARD_SNAPSHOT_SOURCES)
    )
    dashboard = _resolve_dashboard(candidates, selected_ref)
    requests = [_request(source, selected_app, dashboard) for source in DASHBOARD_SNAPSHOT_SOURCES]
    ordered = _read_sources(
        client, requests, workers=workers, pages=pages, items=items - tree_items
    )
    safe_results = [
        annotate_result(
            _safe_result(result, source),
            source=source.source,
            scope=source.scope,
        )
        for source, result in zip(DASHBOARD_SNAPSHOT_SOURCES, ordered, strict=True)
    ]
    if _result_items(safe_results) + tree_items > items:
        raise PaginationError("dashboard snapshot exceeded the aggregate item safety bound")
    envelope = composite_envelope(
        safe_results,
        schema_version=SCHEMA_VERSION,
        extra={
            "app_id": selected_app,
            "dashboard": dashboard.to_dict(),
            "source_count": len(DASHBOARD_SNAPSHOT_SOURCES),
            "scopes": ["dashboard", "space"],
        },
    )
    if envelope["total_count"] != len(DASHBOARD_SNAPSHOT_SOURCES):
        raise RuntimeError("dashboard snapshot result count invariant failed")
    return envelope


def _request(
    source: DashboardSource, app_id: str, dashboard: DashboardIdentity
) -> dict[str, Any]:
    if source.source == "detail":
        inputs: dict[str, Any] = {
            "app_id": app_id,
            "id": dashboard.dashboard_id,
            "space_id": dashboard.space_id,
        }
    elif source.source == "space_members":
        inputs = {"app_id": app_id, "space_id": dashboard.space_id}
    elif source.source == "favourites":
        inputs = {
            "app_id": app_id,
            "page": 1,
            "page_size": 20,
            "filters": [{
                "field": "dashboard_id",
                "operator": 1,
                "values": [dashboard.dashboard_id],
            }],
        }
    else:
        inputs = {"app_id": app_id, "dashboard_id": dashboard.dashboard_id}
    return {
        "operation_id": source.operation_id,
        "request_id": source.source,
        "inputs": inputs,
        "read_all": source.paginated,
    }


def _read_tree(client: Any, app_id: str) -> Mapping[str, Any]:
    try:
        tree = client.read(TREE_OPERATION, {"app_id": app_id})
    except GravityInsightError as exc:
        raise _safe_exception(exc.to_error_detail(), "directory", TREE_OPERATION) from None
    except Exception:
        raise LocalIOError(
            "dashboard snapshot directory client failed locally",
            next_action="Inspect the local Gravity client, then retry the snapshot.",
        ) from None
    if not isinstance(tree, Mapping):
        raise ContractChangedError("dashboard tree returned an invalid envelope")
    status = _status(tree)
    if tree.get("ok") is False or status not in _SUCCESS_STATUSES:
        if status == "contract_changed":
            raise ContractChangedError("dashboard tree contract changed")
        raise _safe_exception(tree.get("error"), "directory", TREE_OPERATION)
    return tree


def _read_sources(
    client: Any,
    requests: Sequence[Mapping[str, Any]],
    *,
    workers: int,
    pages: int,
    items: int,
) -> list[dict[str, Any]]:
    try:
        raw = runtime.call_batch(
            client,
            requests,
            concurrency=workers,
            max_pages=pages,
            max_total_items=items,
        )
        return ordered_results(raw, requests, component="dashboard snapshot")
    except GravityInsightError as exc:
        raise _safe_exception(exc.to_error_detail(), "batch", None) from None
    except Exception:
        raise LocalIOError(
            "dashboard snapshot batch client failed locally",
            next_action="Inspect the local Gravity client, then retry the snapshot.",
        ) from None


def _dashboard_identities(
    tree: Mapping[str, Any], *, max_nodes: int
) -> tuple[list[DashboardIdentity], int]:
    data = _envelope_data(tree)
    if not isinstance(data, list):
        raise ContractChangedError("dashboard tree no longer returns a list")
    found: dict[str, DashboardIdentity] = {}
    count = 0
    for node, space_id, root in _walk_nodes(data):
        count += 1
        if count > max_nodes:
            raise PaginationError(
                "dashboard directory exceeded the aggregate item safety bound"
            )
        candidate = _identity(node, space_id, root=root)
        if candidate is None:
            continue
        if candidate.dashboard_id in found:
            raise ContractChangedError("dashboard tree returned a duplicate dashboard identity")
        found[candidate.dashboard_id] = candidate
    return list(found.values()), count


def _walk_nodes(value: list[Any]):
    stack = [(item, None, 0, True) for item in reversed(value)]
    while stack:
        node, inherited_space, depth, root = stack.pop()
        if not isinstance(node, Mapping):
            raise ContractChangedError("dashboard tree returned a non-object node")
        if depth > MAX_TREE_DEPTH:
            raise ContractChangedError("dashboard tree exceeded its depth contract")
        raw_space = node.get("space_id")
        own_space = _bounded_text(raw_space)
        if "space_id" in node and raw_space is not None and own_space is None:
            raise ContractChangedError("dashboard tree returned an invalid space identity")
        space_id = own_space or (_bounded_text(node.get("id")) if root else inherited_space)
        yield node, space_id, root
        children: list[Any] = []
        for key in ("folder_or_dashboard", "dashboards"):
            child = node.get(key)
            if child is None:
                continue
            if isinstance(child, Mapping):
                children.append(child)
            elif isinstance(child, list):
                children.extend(child)
            else:
                raise ContractChangedError("dashboard tree returned an invalid child container")
        stack.extend(
            (child, space_id, depth + 1, False) for child in reversed(children)
        )


def _identity(
    node: Mapping[str, Any], inherited_space_id: str | None, *, root: bool
) -> DashboardIdentity | None:
    if root:
        return None
    if node.get("is_folder") is True or node.get("folder_or_dashboard") is not None:
        return None
    if node.get("dashboards") is not None:
        return None
    dashboard_id = _bounded_text(node.get("id"))
    name = _bounded_text(node.get("name"))
    space_id = inherited_space_id
    if None in (dashboard_id, name, space_id):
        raise ContractChangedError("dashboard tree returned an incomplete dashboard identity")
    return DashboardIdentity(dashboard_id, name, space_id)


def _resolve_dashboard(
    candidates: Sequence[DashboardIdentity], ref: str
) -> DashboardIdentity:
    by_id = [item for item in candidates if item.dashboard_id == ref]
    matches = by_id or [item for item in candidates if item.name == ref]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise InputValidationError(
            "dashboard ref matches more than one exact dashboard name",
            field="ref",
            next_action="Retry with the stable dashboard id from `analysis dashboard --kind tree`.",
        )
    raise InputValidationError(
        "dashboard ref does not match an exact dashboard id or name",
        field="ref",
        next_action="Inspect the dashboard tree and retry with an exact id or name.",
    )


def _safe_result(
    result: Mapping[str, Any], source: DashboardSource
) -> dict[str, Any]:
    status = _status(result)
    if result.get("ok") is not True or status not in _SUCCESS_STATUSES:
        if status == "contract_changed":
            return _failed_result(source, ErrorCode.CONTRACT_CHANGED)
        return _failed_result(source, _safe_error(result.get("error"), source))
    envelope = result.get("data")
    if not isinstance(envelope, Mapping):
        return _failed_result(source, ErrorCode.CONTRACT_CHANGED)
    native_status = _status(envelope)
    if native_status not in _SUCCESS_STATUSES:
        code = (
            ErrorCode.CONTRACT_CHANGED
            if native_status == "contract_changed"
            else _safe_error(envelope.get("error"), source)
        )
        return _failed_result(source, code)
    try:
        projected = safe_source_data(source.source, envelope.get("data"))
    except ContractChangedError:
        return _failed_result(source, ErrorCode.CONTRACT_CHANGED)
    safe_status = (
        "contract_changed_additive"
        if "contract_changed_additive" in {status, native_status}
        else native_status
    )
    return {
        "operation_id": source.operation_id,
        "ok": True,
        "status": safe_status,
        "data": {
            "schema_version": "gravity-insight.read.v1",
            "operation_id": source.operation_id,
            "status": safe_status,
            "data": projected,
        },
        "error": None,
    }


def _safe_error(value: Any, source: DashboardSource) -> ErrorDetail:
    raw = value if isinstance(value, Mapping) else {}
    code = str(raw.get("code", "")).strip().upper()
    selected = (
        code
        if code in _BUILTIN_ERROR_CODES or code == "BATCH_RESULT_MISSING"
        else ErrorCode.LOCAL_IO_ERROR.value
    )
    retry_after = raw.get("retry_after_ms")
    return ErrorDetail.create(
        selected,
        f"Dashboard snapshot source `{source.source}` failed.",
        operation_id=source.operation_id,
        retry_after_ms=(
            retry_after
            if selected == ErrorCode.RATE_LIMITED.value
            and type(retry_after) is int
            and retry_after >= 0
            else None
        ),
    )


def _failed_result(
    source: DashboardSource, error: ErrorCode | ErrorDetail
) -> dict[str, Any]:
    detail = (
        error
        if isinstance(error, ErrorDetail)
        else ErrorDetail.create(
            error,
            f"Dashboard snapshot source `{source.source}` contract changed.",
            operation_id=source.operation_id,
        )
    )
    return {
        "operation_id": source.operation_id,
        "ok": False,
        "status": (
            "contract_changed"
            if detail.code == ErrorCode.CONTRACT_CHANGED.value
            else "error"
        ),
        "data": None,
        "error": detail.to_dict(),
    }


def _safe_exception(
    value: Any, component: str, operation_id: str | None
) -> GravityInsightError:
    raw = value.to_dict() if isinstance(value, ErrorDetail) else value
    raw = raw if isinstance(raw, Mapping) else {}
    code = str(raw.get("code", "")).strip().upper()
    selected = code if code in _BUILTIN_ERROR_CODES else ErrorCode.UPSTREAM_UNAVAILABLE.value
    retry_after = raw.get("retry_after_ms")
    detail = ErrorDetail.create(
        selected,
        f"Dashboard snapshot {component} read failed.",
        operation_id=operation_id,
        retry_after_ms=(
            retry_after
            if selected == ErrorCode.RATE_LIMITED.value
            and type(retry_after) is int
            and retry_after >= 0
            else None
        ),
    )
    return GravityInsightError(
        detail.message,
        code=detail.code,
        retry_after_ms=detail.retry_after_ms,
        next_action=detail.next_action,
    )


def _envelope_data(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return None
    data = value.get("data")
    if isinstance(data, Mapping) and "data" in data and "status" in data:
        return data.get("data")
    return data


def _status(value: Mapping[str, Any]) -> str:
    status = value.get("status")
    return status.strip().casefold() if isinstance(status, str) else ""


def _result_items(results: Sequence[Mapping[str, Any]]) -> int:
    total = len(results)
    for result in results:
        data = result.get("data")
        payload = data.get("data") if isinstance(data, Mapping) else None
        if isinstance(payload, Mapping):
            total += sum(
                value for key, value in payload.items()
                if key.endswith("_count") and type(value) is int and value >= 0
            )
            if type(payload.get("count")) is int:
                total += max(0, payload["count"])
    return total


def _positive_app_id(value: Any) -> str:
    rendered = str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    if not rendered.isascii() or not rendered.isdigit() or int(rendered) <= 0:
        raise InputValidationError("dashboard snapshot app_id must be a positive integer", field="app_id")
    return str(int(rendered))


def _reference(value: Any) -> str:
    rendered = _bounded_text(value) if not isinstance(value, bool) else None
    if rendered is None:
        raise InputValidationError("dashboard snapshot ref must be a bounded id or exact name", field="ref")
    return rendered


def _bounded_text(value: Any) -> str | None:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        return None
    rendered = str(value).strip()
    return rendered if 0 < len(rendered) <= 256 else None


def _workers(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_CONCURRENCY:
        raise InputValidationError(
            f"dashboard snapshot max_workers must be between 1 and {MAX_CONCURRENCY}",
            field="max_workers",
        )
    return value


__all__ = [
    "DASHBOARD_SNAPSHOT_SOURCES",
    "DEFAULT_CONCURRENCY",
    "MAX_CONCURRENCY",
    "MIN_SNAPSHOT_ITEMS",
    "SCHEMA_VERSION",
    "TREE_OPERATION",
    "dashboard_snapshot",
]
