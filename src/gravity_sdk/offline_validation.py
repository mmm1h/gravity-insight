"""Network-free metadata dependency collection for public validation."""

from __future__ import annotations

from typing import Any, Mapping

from .errors import GravityInsightError


class OfflineMetadataRequired(Exception):
    """Stop membership checks before a metadata transport can be reached."""


class OfflineMetadataLoader:
    def __init__(
        self,
        field_policy: Any,
        operation: Any,
        inputs: Mapping[str, Any],
        dependencies: list[str],
    ) -> None:
        self._dependencies = dependencies
        try:
            dependencies.extend(field_policy.dependencies(operation, inputs))
        except GravityInsightError:
            pass

    def __call__(
        self, operation_id: str, _inputs: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        if operation_id not in self._dependencies:
            self._dependencies.append(operation_id)
        raise OfflineMetadataRequired(operation_id)


__all__ = ["OfflineMetadataLoader", "OfflineMetadataRequired"]
