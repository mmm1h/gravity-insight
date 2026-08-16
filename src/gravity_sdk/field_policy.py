"""Compatibility facade for metadata-backed field validation."""

from __future__ import annotations

from typing import Any, Mapping

from ._field_policy_analysis import (
    analysis_metadata_dependencies,
    validate_analysis_query,
    validate_analysis_segment_rule,
)
from ._field_policy_controls import (
    validate_dynamic_response_fields,
    validate_request_controls,
)
from ._field_policy_detail import validate_analysis_detail
from ._field_policy_metadata import validate_analysis_property_values
from ._field_policy_operations import operation_rule
from ._field_policy_shared import MetadataLoader
from .field_metadata_override import selected_metadata_loader
from .models import OperationSpec


class FieldPolicy:
    """Fail closed when dynamic fields are not proven by live metadata."""

    def validate(
        self,
        operation: OperationSpec,
        inputs: Mapping[str, Any],
        metadata_loader: MetadataLoader,
    ) -> None:
        metadata_loader = selected_metadata_loader(metadata_loader)
        rule = operation_rule(operation.operation_id)
        if rule.request_kind == "analysis_segment":
            validate_analysis_segment_rule(inputs, metadata_loader)
            return
        if rule.request_kind == "analysis_detail":
            validate_analysis_detail(operation, inputs, metadata_loader)
            return
        validate_request_controls(operation, inputs, metadata_loader)
        if rule.request_kind == "property_values":
            validate_analysis_property_values(
                str(rule.query_kind), inputs, metadata_loader
            )
            return
        if rule.request_kind == "analysis_query":
            validate_analysis_query(str(rule.query_kind), inputs, metadata_loader)
        if not operation.response_projection.dynamic_item_fields:
            return
        validate_dynamic_response_fields(operation, inputs, metadata_loader)

    @staticmethod
    def dependencies(
        operation: OperationSpec, inputs: Mapping[str, Any]
    ) -> tuple[str, ...]:
        rule = operation_rule(operation.operation_id)
        if rule.request_kind != "analysis_query":
            return ()
        return analysis_metadata_dependencies(str(rule.query_kind), inputs)
