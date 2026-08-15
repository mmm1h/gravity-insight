"""Complete live input catalogs for explicit Agent input resolution."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from typing import Any

from ._field_policy_operations import PROMOTION_METRIC
from ._field_policy_shared import promotion_metadata_inputs
from .dashboard_snapshot import (
    TREE_OPERATION,
    _dashboard_identities,
    _read_tree,
)
from .domains import MULTIDIM_METADATA_OPERATIONS
from .errors import ContractChangedError, InputValidationError, UpstreamError
from .promotion_performance_request import normalize_promotion_platforms
from .runtime import call_batch, call_read
from .saved_analysis_catalog import LIST_OPERATION_ID, list_saved_analyses
from .saved_analysis_support import selected_workspace
from .segment_snapshot import LIST_OPERATION as SEGMENT_LIST_OPERATION
from .template_replay import list_analysis_templates
from .workspace_app import resolve_workspace_app


SCHEMA_VERSION = "gravity.agent-input-catalog.v1"
MAX_CATALOG_ITEMS = 100_000
MAX_CATALOG_PAGES = 1_000
_SUCCESS = {"success", "empty", "contract_changed_additive"}
_REFERENCE_COMPOSITES = {
    "dashboard_analysis",
    "dashboard_snapshot",
    "saved_analysis",
    "segment_snapshot",
    "analysis_template",
}


def live_catalog_for_card(
    card: Mapping[str, Any],
    *,
    client: Any,
    workspace: Any | None,
    known_inputs: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Read one complete governed catalog without selecting an input value."""

    composite = str(card.get("composite", ""))
    if composite in {"dashboard_analysis", "dashboard_snapshot"}:
        catalogs = [_dashboard_catalog(client, workspace, _required_app(known_inputs))]
    elif composite == "saved_analysis":
        catalogs = [_saved_catalog(client, workspace, _required_app(known_inputs))]
    elif composite == "segment_snapshot":
        catalogs = [_segment_catalog(client, workspace, _required_app(known_inputs))]
    elif composite == "analysis_template":
        catalogs = [_template_catalog(client)]
    elif composite == "multidim":
        catalogs = _multidim_catalogs(client)
    elif composite == "promotion_performance":
        catalogs = _promotion_catalogs(client, _required_platforms(known_inputs))
    else:
        return None
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": "success",
        "complete": True,
        "observed": "live",
        "selection": "caller_exact",
        "execution_revalidates": True,
        "catalogs": catalogs,
    }
    if composite in _REFERENCE_COMPOSITES:
        result["stale_reference_policy"] = (
            "select_returned_stable_id_then_revalidate_live"
        )
    else:
        result["stale_physical_input_policy"] = "revalidate_against_live_metadata"
    return result


def resolvable_scenario(card: Mapping[str, Any]) -> str | None:
    composite = str(card.get("composite", ""))
    if composite in _REFERENCE_COMPOSITES:
        return "unknown_reference"
    if composite in {"multidim", "promotion_performance"}:
        return "unknown_physical_inputs"
    return None


def _dashboard_catalog(client: Any, workspace: Any, app: Any) -> dict[str, Any]:
    app_id = _app_id(workspace, app)
    envelope = _read_tree(client, app_id)
    identities, _ = _dashboard_identities(envelope, max_nodes=MAX_CATALOG_ITEMS)
    return _component(
        TREE_OPERATION,
        [item.to_dict() for item in identities],
        scope="app",
        selection_fields=("id",),
    )


def _saved_catalog(client: Any, workspace: Any, app: Any) -> dict[str, Any]:
    value = list_saved_analyses(
        client,
        app,
        workspace=selected_workspace(workspace),
        max_pages=MAX_CATALOG_PAGES,
        max_items=MAX_CATALOG_ITEMS,
    )
    _require_catalog_envelope(value, "saved Analysis")
    return _component(
        LIST_OPERATION_ID,
        _mapping_items(value.get("items")),
        scope="app",
        selection_fields=("id",),
    )


def _template_catalog(client: Any) -> dict[str, Any]:
    value = list_analysis_templates(
        client,
        scope=None,
        max_pages=MAX_CATALOG_PAGES,
        max_items=MAX_CATALOG_ITEMS,
    )
    _require_catalog_envelope(value, "Analysis template")
    return _component(
        "analysis.template.catalog",
        _mapping_items(value.get("items")),
        selection_fields=("scope", "id"),
    )


def _segment_catalog(client: Any, workspace: Any, app: Any) -> dict[str, Any]:
    app_id = _app_id(workspace, app)
    value = call_read(
        client,
        SEGMENT_LIST_OPERATION,
        {"app_id": app_id, "page": 1, "page_size": 100},
        read_all=True,
        max_pages=MAX_CATALOG_PAGES,
        max_items=MAX_CATALOG_ITEMS,
        max_workers=6,
    )
    rows = _result_rows(value, SEGMENT_LIST_OPERATION)
    items, seen = [], set()
    for row in rows:
        identifier = _identifier(row, ("segment_id", "id", "cid"), "segment id")
        name = _identifier(row, ("segment_name",), "segment name")
        if identifier in seen:
            raise ContractChangedError("segment catalog returned a duplicate identity")
        seen.add(identifier)
        row_app = row.get("app_id")
        if row_app is not None and str(row_app) != app_id:
            raise ContractChangedError("segment catalog returned an App identity mismatch")
        items.append({"id": identifier, "name": name})
    return _component(
        SEGMENT_LIST_OPERATION,
        items,
        scope="app",
        selection_fields=("id",),
    )


def _multidim_catalogs(client: Any) -> list[dict[str, Any]]:
    requests = [
        {"operation_id": operation_id, "inputs": {}, "read_all": True}
        for operation_id in MULTIDIM_METADATA_OPERATIONS
    ]
    results = call_batch(
        client,
        requests,
        concurrency=min(6, len(requests)),
        max_pages=MAX_CATALOG_PAGES,
        max_total_items=MAX_CATALOG_ITEMS,
    )
    return _batch_components(requests, results)


def _promotion_catalogs(client: Any, platforms: Sequence[str]) -> list[dict[str, Any]]:
    requests = []
    for platform in normalize_promotion_platforms(platforms):
        profile = promotion_metadata_inputs(SimpleNamespace(platform=platform), {})
        requests.append({
            "operation_id": PROMOTION_METRIC,
            "request_id": platform,
            "inputs": profile,
            "read_all": True,
        })
    results = call_batch(
        client,
        requests,
        concurrency=min(6, len(requests)),
        max_pages=MAX_CATALOG_PAGES,
        max_total_items=MAX_CATALOG_ITEMS,
    )
    return _batch_components(requests, results, request_scope="request_id")


def _batch_components(
    requests: Sequence[Mapping[str, Any]],
    results: Any,
    *,
    request_scope: str | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
        raise UpstreamError("input catalog batch returned an invalid result collection")
    if len(results) != len(requests):
        raise UpstreamError("input catalog batch returned an incomplete result collection")
    components, total = [], 0
    for request, result in zip(requests, results, strict=True):
        selector = str(request["operation_id"])
        rows = _result_rows(result, selector)
        total += len(rows)
        if total > MAX_CATALOG_ITEMS:
            raise UpstreamError("combined input catalogs exceeded their item bound")
        scope = str(request[request_scope]) if request_scope else None
        components.append(_component(selector, rows, scope=scope))
    return components


def _result_rows(value: Any, selector: str) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping):
        raise UpstreamError(f"{selector} returned an invalid catalog envelope")
    status = str(value.get("status", "error"))
    if value.get("ok") is not True or status not in _SUCCESS:
        raise UpstreamError(f"{selector} input catalog was unavailable")
    if value.get("truncated") is True or value.get("next_page_input") not in (None, {}):
        raise UpstreamError(f"{selector} input catalog was incomplete")
    rows = _catalog_rows(value.get("data"), selector)
    if len(rows) > MAX_CATALOG_ITEMS:
        raise UpstreamError(f"{selector} input catalog exceeded its item bound")
    return rows


def _catalog_rows(value: Any, selector: str) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return _mapping_rows(value, selector)
    if not isinstance(value, Mapping):
        raise ContractChangedError(f"{selector} input catalog changed shape")
    direct = value.get("list", value.get("items"))
    if direct is not None:
        return _mapping_rows(direct, selector)
    return _nested_catalog_rows(value, selector)


def _mapping_rows(value: Any, selector: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, Mapping) for row in value):
        raise ContractChangedError(f"{selector} input catalog changed shape")
    return [copy.deepcopy(dict(row)) for row in value]


def _nested_catalog_rows(value: Mapping[str, Any], selector: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    stack = [((), value)]
    while stack:
        path, node = stack.pop()
        for key, child in reversed(tuple(node.items())):
            selected_path = (*path, str(key))
            if isinstance(child, Mapping):
                stack.append((selected_path, child))
                continue
            selected = _mapping_rows(child, selector)
            for row in selected:
                if "catalog_path" in row:
                    raise ContractChangedError(
                        f"{selector} input catalog reused the catalog_path field"
                    )
                rows.append({"catalog_path": ".".join(selected_path), **row})
    return rows


def _component(
    selector: str,
    items: list[dict[str, Any]],
    *,
    scope: str | None = None,
    selection_fields: Sequence[str] = (),
) -> dict[str, Any]:
    for field in selection_fields:
        if any(item.get(field) in (None, "") for item in items):
            raise ContractChangedError(
                f"{selector} input catalog omitted stable selection field {field}"
            )
    result = {
        "selector": selector,
        "status": "empty" if not items else "success",
        "count": len(items),
        "items": items,
    }
    if scope is not None:
        result["scope"] = scope
    if selection_fields:
        result["two_call_selection_fields"] = list(selection_fields)
    return result


def _require_catalog_envelope(value: Mapping[str, Any], label: str) -> None:
    if value.get("ok") is not True or value.get("status") not in {"success", "empty"}:
        raise UpstreamError(f"{label} input catalog was unavailable")


def _mapping_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise ContractChangedError("input catalog items changed shape")
    return [copy.deepcopy(dict(item)) for item in value]


def _required_app(value: Mapping[str, Any]) -> Any:
    if "app" not in value:
        raise InputValidationError(
            "online input resolution requires known_inputs.app for this catalog",
            field="known_inputs.app",
        )
    return value["app"]


def _required_platforms(value: Mapping[str, Any]) -> Sequence[str]:
    platforms = value.get("platforms")
    if not isinstance(platforms, Sequence) or isinstance(platforms, (str, bytes)):
        raise InputValidationError(
            "online input resolution requires known_inputs.platforms",
            field="known_inputs.platforms",
        )
    return platforms


def _app_id(workspace: Any, app: Any) -> str:
    return str(resolve_workspace_app(selected_workspace(workspace), app))


def _identifier(row: Mapping[str, Any], fields: Sequence[str], label: str) -> str:
    value = next((row.get(field) for field in fields if row.get(field) is not None), None)
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ContractChangedError(f"segment catalog omitted {label}")
    rendered = str(value).strip()
    if not rendered or len(rendered) > 512:
        raise ContractChangedError(f"segment catalog returned an invalid {label}")
    return rendered


__all__ = ["SCHEMA_VERSION", "live_catalog_for_card", "resolvable_scenario"]
