"""Current-account permission facts assembled from three stable reads."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from . import runtime
from .composite_batch import (
    annotate_result,
    composite_envelope,
    enforce_composite_item_budget,
    normalize_identifier,
    ordered_results,
    parent_required_result,
    validate_composite_bounds,
)
from .composite_catalog import stable_operation


SCHEMA_VERSION = "gravity-insight.account-permission-profile.v1"
DEFAULT_CONCURRENCY = 3
MAX_CONCURRENCY = 24
_MENU_LIST = stable_operation("app", "permission_menu", action="list")
_ROLE_LIST = stable_operation("app", "role", action="list")
_ROLE_DETAIL = stable_operation("app", "role", action="detail")
_USER_LIST = stable_operation("analysis", "account_user", action="list")
MENU_OPERATION_ID = _MENU_LIST.operation_id
ROLE_LIST_OPERATION_ID = _ROLE_LIST.operation_id
ROLE_DETAIL_OPERATION_ID = _ROLE_DETAIL.operation_id
USER_LIST_OPERATION_ID = _USER_LIST.operation_id


def account_permission_profile(
    client: Any,
    *,
    max_workers: int = DEFAULT_CONCURRENCY,
    max_pages: int = 1_000,
    max_items: int = 100_000,
) -> dict[str, Any]:
    """Expose the authenticated account's role, menus, and data-permission modules."""

    workers = _workers(max_workers)
    pages, items = validate_composite_bounds(max_pages, max_items, minimum_items=4)
    by_source = _first_sources(client, workers, pages, items)
    principal = _principal_id(client)
    role_ids = _assigned_role_ids(by_source["current_user"], principal)
    by_source["assigned_role"] = _assigned_role_result(
        client, role_ids, pages
    )
    order = ("current_user", "assigned_role", "permission_menu", "roles")
    enforce_composite_item_budget([by_source[name] for name in order], items)
    results = [
        annotate_result(by_source[name], source=name, scope="account")
        for name in order
    ]
    return composite_envelope(
        results,
        schema_version=SCHEMA_VERSION,
        extra=_envelope_extra(_facts(by_source, role_ids, principal), len(order)),
    )


def _first_sources(
    client: Any, workers: int, pages: int, items: int
) -> dict[str, Any]:
    first = (
        _request(MENU_OPERATION_ID, "permission_menu", {}, paginated=False),
        _request(
            ROLE_LIST_OPERATION_ID,
            "roles",
            {"page": 1, "page_size": 20},
            paginated=True,
        ),
        _request(
            USER_LIST_OPERATION_ID,
            "current_user",
            {"page": 1, "page_size": 100},
            paginated=True,
        ),
    )
    results = ordered_results(
        runtime.call_batch(
            client,
            first,
            concurrency=workers,
            max_pages=pages,
            max_total_items=max(3, items - 1),
        ),
        first,
        component="account permission profile",
    )
    return dict(
        zip(("permission_menu", "roles", "current_user"), results, strict=True)
    )


def _assigned_role_result(
    client: Any, role_ids: Sequence[int], pages: int
) -> dict[str, Any]:
    if not role_ids:
        return parent_required_result(
            ROLE_DETAIL_OPERATION_ID,
            "assigned_role",
            parent="role_id",
            component="account permission profile",
        )
    request = _request(
        ROLE_DETAIL_OPERATION_ID,
        "assigned_role",
        {"role_id": role_ids[0]},
        paginated=False,
    )
    return ordered_results(
        runtime.call_batch(
            client,
            [request],
            concurrency=1,
            max_pages=pages,
            max_total_items=1,
        ),
        [request],
        component="account permission profile",
    )[0]


def _envelope_extra(facts: Mapping[str, Any], source_count: int) -> dict[str, Any]:
    return {
        "source_count": source_count,
        "scopes": ["account"],
        "principal_matched": facts["principal_matched"],
        "assigned_role_count": facts["assigned_role_count"],
        "assigned_role_names": facts["assigned_role_names"],
        "assigned_role_codes": facts["assigned_role_codes"],
        "menu_count": facts["menu_count"],
        "menu_names": facts["menu_names"],
        "data_permission_modules": facts["data_permission_modules"],
        "empty_result_note": (
            "An empty data query is not a permission denial. Compare "
            "menu_names and data_permission_modules with the query family "
            "before treating empty as tenant-has-no-data."
        ),
    }


def _request(
    operation_id: str,
    request_id: str,
    inputs: Mapping[str, Any],
    *,
    paginated: bool,
) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "request_id": request_id,
        "inputs": dict(inputs),
        "read_all": paginated,
    }


def _assigned_role_ids(
    user_result: Mapping[str, Any], principal: str | None
) -> tuple[int, ...]:
    if user_result.get("ok") is not True:
        return ()
    matched = _match_principal(_list_rows(user_result), principal)
    if matched is None:
        return ()
    roles = matched.get("roles")
    if not isinstance(roles, list):
        return ()
    ids: list[int] = []
    for role in roles:
        if not isinstance(role, Mapping):
            continue
        try:
            ids.append(int(normalize_identifier(role.get("id"), field="role_id")))
        except Exception:
            continue
    return tuple(dict.fromkeys(ids))


def _principal_id(client: Any) -> str | None:
    transport = getattr(getattr(client, "_executor", None), "_transport", None)
    resolver = getattr(transport, "current_principal_id", None)
    if not callable(resolver):
        return None
    value = resolver()
    selected = str(value).strip() if value is not None else ""
    return selected or None


def _match_principal(
    rows: Sequence[Mapping[str, Any]], principal: str | None
) -> Mapping[str, Any] | None:
    if not principal:
        return None
    for row in rows:
        if str(row.get("id")) == principal or str(row.get("user_id")) == principal:
            return row
    return None


def _facts(
    by_source: Mapping[str, Mapping[str, Any]],
    role_ids: Sequence[int],
    principal: str | None,
) -> dict[str, Any]:
    user = by_source["current_user"]
    rows = _list_rows(user) if user.get("ok") is True else ()
    matched = _match_principal(rows, principal)
    assigned = by_source["assigned_role"]
    names, codes = _role_labels(assigned, matched)
    menu_names = _menu_names(by_source["permission_menu"])
    return {
        "principal_matched": matched is not None,
        "assigned_role_count": len(role_ids),
        "assigned_role_names": names,
        "assigned_role_codes": codes,
        "menu_count": len(menu_names),
        "menu_names": menu_names,
        "data_permission_modules": _data_modules(assigned),
    }


def _role_labels(
    assigned: Mapping[str, Any], matched: Mapping[str, Any] | None
) -> tuple[list[str], list[str]]:
    assigned_data = _inner_data(assigned)
    if assigned.get("ok") is True and isinstance(assigned_data, Mapping):
        return _label_pair(assigned_data)
    names: list[str] = []
    codes: list[str] = []
    for role in (matched or {}).get("roles") or []:
        if isinstance(role, Mapping):
            pair = _label_pair(role)
            names.extend(pair[0])
            codes.extend(pair[1])
    return names, codes


def _label_pair(value: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    name = value.get("name")
    code = value.get("code")
    return (
        [name] if isinstance(name, str) and name else [],
        [code] if isinstance(code, str) and code else [],
    )


def _menu_names(result: Mapping[str, Any]) -> list[str]:
    if result.get("ok") is not True:
        return []
    names: list[str] = []
    seen: set[str] = set()

    def walk(node: object) -> None:
        if not isinstance(node, Mapping):
            return
        name = node.get("name")
        if isinstance(name, str) and name and name not in seen:
            seen.add(name)
            names.append(name)
        for child in node.get("children") or []:
            walk(child)

    for item in _list_rows(result):
        walk(item)
    return names


def _data_modules(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    if result.get("ok") is not True:
        return []
    data = _inner_data(result)
    perms = data.get("data_permission") if isinstance(data, Mapping) else None
    if not isinstance(perms, list):
        return []
    modules: list[dict[str, Any]] = []
    for item in perms:
        if not isinstance(item, Mapping):
            continue
        modules.append(
            {
                "effect_module": item.get("effect_module"),
                "child_module": item.get("child_module"),
                "role_effect": item.get("role_effect"),
            }
        )
    return modules


def _list_rows(result: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    data = _inner_data(result)
    if isinstance(data, Mapping):
        rows = data.get("list")
    else:
        rows = data
    if not isinstance(rows, list):
        return ()
    return tuple(item for item in rows if isinstance(item, Mapping))


def _inner_data(result: Mapping[str, Any]) -> Any:
    envelope = result.get("data")
    if not isinstance(envelope, Mapping):
        return None
    if "data" in envelope and isinstance(envelope.get("data"), (Mapping, list)):
        return envelope.get("data")
    return envelope


def _workers(value: int) -> int:
    pages, _items = validate_composite_bounds(value, MAX_CONCURRENCY, minimum_items=1)
    return pages


__all__ = [
    "DEFAULT_CONCURRENCY",
    "MAX_CONCURRENCY",
    "MENU_OPERATION_ID",
    "ROLE_DETAIL_OPERATION_ID",
    "ROLE_LIST_OPERATION_ID",
    "SCHEMA_VERSION",
    "USER_LIST_OPERATION_ID",
    "account_permission_profile",
]
