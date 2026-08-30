"""Metadata-template convenience methods for the unified SDK facade."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class MetadataTemplateSdkMixin:
    @staticmethod
    def metadata_template_mutation_schema() -> dict[str, Any]:
        from .metadata_template_mutation import metadata_template_mutation_schema

        return metadata_template_mutation_schema()

    def metadata_template_mutation(
        self, action: str, inputs: Mapping[str, Any], *, execute: bool = False
    ) -> dict[str, Any]:
        from .metadata_template_mutation import run_metadata_template_mutation

        return run_metadata_template_mutation(
            self.insight, action, inputs, execute=execute
        )

    def create_metadata_template(self, **options: Any) -> dict[str, Any]:
        from .metadata_template_mutation import create_metadata_template

        return create_metadata_template(self.insight, **options)

    def append_metadata_template_members(self, **options: Any) -> dict[str, Any]:
        from .metadata_template_mutation import append_metadata_template_members

        return append_metadata_template_members(self.insight, **options)

    def remove_metadata_template_members(self, **options: Any) -> dict[str, Any]:
        from .metadata_template_mutation import remove_metadata_template_members

        return remove_metadata_template_members(self.insight, **options)

    def delete_metadata_template(
        self, template_id: int, *, execute: bool = False
    ) -> dict[str, Any]:
        from .metadata_template_mutation import delete_metadata_template

        return delete_metadata_template(
            self.insight, template_id=template_id, execute=execute
        )


__all__ = ["MetadataTemplateSdkMixin"]
