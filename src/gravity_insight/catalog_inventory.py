"""Complete offline catalog inventory facade, including non-callable drafts."""

from __future__ import annotations

from typing import Any


class CatalogInventoryMixin:
    def operation_inventory(
        self,
        *,
        domain: str | None = None,
        platform: str | None = None,
        stability: str | None = None,
    ) -> list[dict[str, Any]]:
        catalog = self._operation_catalog
        operations = list(catalog._operations.values())
        filters = (("domain", domain), ("platform", platform), ("stability", stability))
        for key, expected in filters:
            if expected is not None:
                operations = [item for item in operations if item.get(key) == expected]
        ordered = sorted(operations, key=lambda item: str(item.get("operation_id", "")))
        return catalog.merge(ordered)


__all__ = ["CatalogInventoryMixin"]
