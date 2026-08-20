"""Manifest model for pagination contracts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .errors import ManifestError
from .pagination_completeness import contract_dimensions


@dataclass(frozen=True)
class PaginationSpec:
    kind: str = "none"
    completeness: str = "unknown"
    pagination_evidence: str = "none"
    page_field: str = "page"
    page_size_field: str = "page_size"
    items_field: str = "list"
    page_info_field: str = "page_info"
    total_page_field: str = "total_page"
    list_path: str = "data.list"
    page_info_path: str = "data.page_info"
    default_page_size: int | None = None
    max_page_size: int | None = None

    @classmethod
    def from_dict(cls, value: Any) -> "PaginationSpec":
        if value in (None, False):
            return cls()
        if not isinstance(value, Mapping):
            raise ManifestError("pagination must be an object")
        completeness, pagination_evidence = contract_dimensions(value)
        kind = str(value.get("kind", "none")).strip().lower()
        if kind not in {"none", "page_info"}:
            raise ManifestError("pagination.kind must be none or page_info")
        default_size = value.get("default_page_size")
        max_size = value.get("max_page_size")
        for label, item in (
            ("default_page_size", default_size),
            ("max_page_size", max_size),
        ):
            if item is not None and (
                not isinstance(item, int) or isinstance(item, bool) or item <= 0
            ):
                raise ManifestError(f"pagination.{label} must be a positive integer")
        if default_size and max_size and default_size > max_size:
            raise ManifestError("pagination.default_page_size exceeds max_page_size")
        return cls(
            kind=kind,
            completeness=completeness,
            pagination_evidence=pagination_evidence,
            page_field=str(value.get("page_field", "page")),
            page_size_field=str(value.get("page_size_field", "page_size")),
            items_field=str(value.get("items_field", "list")),
            page_info_field=str(value.get("page_info_field", "page_info")),
            total_page_field=str(value.get("total_page_field", "total_page")),
            list_path=str(value.get("list_path", "data.list")),
            page_info_path=str(value.get("page_info_path", "data.page_info")),
            default_page_size=default_size,
            max_page_size=max_size,
        )


__all__ = ["PaginationSpec"]
