"""Catalog-derived identities for report reads and mutations."""

from __future__ import annotations

from .composite_catalog import identity_contains, stable_operation


def _operation(resource: str, action: str, *, identity: str | None = None) -> str:
    predicate = identity_contains(identity) if identity is not None else None
    return stable_operation(
        "report", resource, action=action, predicate=predicate
    ).operation_id


REPORT_LIST = _operation("report", "list")
REPORT_DETAIL = _operation("report", "detail")
REPORT_UPDATE = _operation("report", "update")
SUBSCRIBE_LIST = _operation("subscribe", "list")
SUBSCRIBE_CREATE = _operation("subscribe", "create")
SUBSCRIBE_DELETE = _operation("subscribe", "delete")
TEMPLATE_LIST = _operation("template", "list", identity="mine")
TEMPLATE_DETAIL = _operation("my_template", "detail")
TEMPLATE_CREATE = _operation("template", "create")
TEMPLATE_UPDATE = _operation("template", "update")


__all__ = [
    "REPORT_DETAIL", "REPORT_LIST", "REPORT_UPDATE", "SUBSCRIBE_CREATE",
    "SUBSCRIBE_DELETE", "SUBSCRIBE_LIST", "TEMPLATE_CREATE",
    "TEMPLATE_DETAIL", "TEMPLATE_LIST", "TEMPLATE_UPDATE",
]
