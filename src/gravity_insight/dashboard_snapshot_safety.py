"""Fail-closed source projections for Dashboard Snapshot."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .errors import ContractChangedError


def safe_source_data(source: str, data: Any) -> Any:
    if not isinstance(data, Mapping):
        raise ContractChangedError("dashboard snapshot source data is not an object")
    projectors = {
        "detail": _detail,
        "members": _members,
        "space_members": _members,
        "favourites": _favourites,
        "default_favourite": _default,
    }
    projector = projectors.get(source)
    if projector is None:
        raise ContractChangedError("dashboard snapshot source is not registered")
    return projector(data)


def _detail(data: Mapping[str, Any]) -> dict[str, Any]:
    if _text(data.get("id")) is None:
        raise ContractChangedError("dashboard detail omitted its stable identity")
    reports, shared = data.get("even_report"), data.get("share_members")
    _optional_list(reports, "dashboard reports")
    _optional_list(shared, "dashboard members")
    return {
        key: rendered
        for key in ("id", "name", "app_id", "space_id", "authority")
        if (rendered := _text(data.get(key))) is not None
    } | {
        "report_count": len(reports) if isinstance(reports, list) else 0,
        "shared_member_count": len(shared) if isinstance(shared, list) else 0,
    }


def _members(data: Mapping[str, Any]) -> dict[str, Any]:
    creator, users = data.get("creator"), data.get("authUsers")
    if not isinstance(creator, (Mapping, list)) or not isinstance(users, list):
        raise ContractChangedError("dashboard member source changed shape")
    return {
        "creator_count": len(creator) if isinstance(creator, list) else 1,
        "authorized_member_count": len(users),
        "authorities": _authorities(users),
    }


def _favourites(data: Mapping[str, Any]) -> dict[str, Any]:
    rows = data.get("list")
    if not isinstance(rows, list):
        raise ContractChangedError("dashboard favourites omitted their list")
    return {"count": len(rows), "page_info": _page_info(data.get("page_info"))}


def _default(data: Mapping[str, Any]) -> dict[str, bool]:
    value = data.get("object")
    if "object" not in data or value is not None and not isinstance(value, Mapping):
        raise ContractChangedError("dashboard default favourite changed shape")
    return {"exists": isinstance(value, Mapping)}


def _authorities(value: list[Any]) -> list[str | int]:
    selected: set[str | int] = set()
    for row in value:
        if not isinstance(row, Mapping):
            raise ContractChangedError("dashboard authority row changed shape")
        authority = row.get("authority")
        if authority is None:
            continue
        if isinstance(authority, bool) or not isinstance(authority, (str, int)):
            raise ContractChangedError("dashboard authority changed type")
        selected.add(authority)
    return sorted(selected, key=str)


def _page_info(value: Any) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ContractChangedError("dashboard favourites page info changed shape")
    selected: dict[str, int] = {}
    for key in ("page", "page_size", "total_page", "total_number", "total"):
        item = value.get(key)
        if item is None:
            continue
        if type(item) is not int or item < 0:
            raise ContractChangedError("dashboard favourites page info changed type")
        selected[key] = item
    return selected


def _optional_list(value: Any, field: str) -> None:
    if value is not None and not isinstance(value, list):
        raise ContractChangedError(f"{field} changed shape")


def _text(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    rendered = str(value).strip()
    return rendered if 0 < len(rendered) <= 256 else None


__all__ = ["safe_source_data"]
