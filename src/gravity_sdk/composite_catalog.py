"""Catalog selectors used by stable composites without duplicating operation IDs."""

from __future__ import annotations

from collections.abc import Callable

from .domain_catalog import CatalogOperation
from .domains import COMPILED_CATALOG_OPERATIONS


def stable_operation(
    domain: str,
    resource: str,
    *,
    action: str | None = None,
    predicate: Callable[[CatalogOperation], bool] | None = None,
) -> CatalogOperation:
    matches = [
        operation
        for operation in COMPILED_CATALOG_OPERATIONS
        if operation.domain == domain
        and operation.resource == resource
        and operation.stability == "stable"
        and operation.executable
        and (action is None or operation.action == action)
        and (predicate is None or predicate(operation))
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "composite catalog selector must resolve exactly one stable operation: "
            f"{domain=}, {resource=}, {action=}"
        )
    return matches[0]


def identity_contains(segment: str) -> Callable[[CatalogOperation], bool]:
    return lambda operation: segment in operation.operation_id.split(".")


def identity_excludes(segment: str) -> Callable[[CatalogOperation], bool]:
    return lambda operation: segment not in operation.operation_id.split(".")


__all__ = ["identity_contains", "identity_excludes", "stable_operation"]
