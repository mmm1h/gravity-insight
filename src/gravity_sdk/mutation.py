"""Exact, one-shot mutation execution over the existing Insight runtime.

The read executor remains read-only.  This module is deliberately a separate
path so a caller cannot turn a POST read into a mutation by changing metadata
at runtime.  Only a stable ``effect=mutation`` operation can mint the receipt
consumed by :meth:`Transport.mutate`.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Callable

from .actionable_error_values import actual_value
from .errors import (
    ConcurrentModificationError,
    InputValidationError,
    ObjectAlreadyExistsError,
    ObjectReferencedError,
    QuotaExceededError,
    SemanticRejectedError,
    UpstreamError,
)
from .models import OperationSpec
from .receipt import capture_http_receipt_references
from .registry import PolicyEngine, Registry
from .result_audit import add_result_audit, bind_error_receipts
from .semantic_status import (
    SEMANTIC_EXPLICIT_EMPTY,
    enforce_semantic_rules as _enforce_semantic_rules,
)
from .transport import Transport


MUTATION_SCHEMA_VERSION = "gravity-insight.mutation.v1"
_SUCCESS_CODES = frozenset({None, 0, 200})


class MutationExecutor:
    """Preview or execute exact registered mutations with no automatic replay."""

    def __init__(
        self, registry: Registry, policy: PolicyEngine, transport: Transport
    ) -> None:
        self._registry = registry
        self._policy = policy
        self._transport = transport
        self._call_guard: Callable[[str], Mapping[str, Any]] | None = None

    def bind_call_guard(
        self, guard: Callable[[str], Mapping[str, Any]]
    ) -> None:
        if not callable(guard):
            raise TypeError("mutation executor call guard must be callable")
        if self._call_guard is not None:
            raise RuntimeError("mutation executor call guard is already bound")
        self._call_guard = guard

    def preview(
        self, operation_id: str, inputs: Mapping[str, Any]
    ) -> dict[str, Any]:
        operation, values, path, query, body = (
            self._policy.preview_mutation_request(operation_id, inputs)
        )
        return {
            "schema_version": MUTATION_SCHEMA_VERSION,
            "ok": True,
            "status": "preview",
            "operation_id": operation.operation_id,
            "effect": "mutation",
            "offline": True,
            "network_called": False,
            "request": {
                "method": operation.upstream_method,
                "path": path,
                "query": copy.deepcopy(query),
                "body": copy.deepcopy(body),
            },
            "normalized_input": _safe_inputs(operation, values),
            "attempts": 0,
        }

    def execute(
        self, operation_id: str, inputs: Mapping[str, Any]
    ) -> dict[str, Any]:
        if self._call_guard is None:
            raise RuntimeError("mutation executor is not bound to the client catalog")
        self._call_guard(operation_id)
        authorization = self._policy._prepare_mutation_request(
            operation_id, inputs
        )
        operation = authorization.operation
        with capture_http_receipt_references() as http_receipts:
            response = self._transport.mutate(
                authorization.method,
                authorization.path,
                operation=operation,
                query=authorization.query,
                body=authorization.body,
                authorization=authorization,
            )
        try:
            semantic_status = _enforce_semantic_rules(
                operation, response.payload, http_receipts
            )
        except SemanticRejectedError:
            try:
                _raise_semantic_rejection(response.payload)
            except Exception as exc:
                bind_error_receipts(exc, http_receipts)
                raise
            raise
        explicit_empty = (
            getattr(response, "status_code", 200) == 204
            or semantic_status == SEMANTIC_EXPLICIT_EMPTY
        )
        response_data = response.payload.get("data") if not explicit_empty else None
        result = {
            "schema_version": MUTATION_SCHEMA_VERSION,
            "ok": True,
            "status": "empty" if explicit_empty else "success",
            "operation_id": operation.operation_id,
            "effect": "mutation",
            "offline": False,
            "network_called": True,
            "attempts": 1,
            "fetched_at": response.fetched_at,
            "contract_fingerprint": self._registry.fingerprint(operation_id),
            "data": {} if explicit_empty else _project_response(operation, response_data),
            "response_shape": _shape(response_data),
            "error": None,
        }
        return add_result_audit(result, http_receipts)


def _safe_inputs(
    operation: OperationSpec, values: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        name: "[REDACTED]" if operation.fields[name].sensitive else copy.deepcopy(value)
        for name, value in values.items()
        if name in operation.fields
    }


def _project_response(operation: OperationSpec, value: Any) -> Any:
    projection = operation.response_projection
    if projection.data_shape == "list":
        if not isinstance(value, list):
            return []
        return [
            {
                key: copy.deepcopy(item[key])
                for key in projection.item_keys
                if isinstance(item, Mapping) and key in item
            }
            for item in value
            if isinstance(item, Mapping)
        ]
    if not isinstance(value, Mapping):
        return {}
    return {
        key: copy.deepcopy(value[key])
        for key in projection.data_keys
        if key in value
    }


def _shape(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "list"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return "unknown"


def _raise_semantic_rejection(payload: Mapping[str, Any]) -> None:
    code = payload.get("code")
    extra = payload.get("extra")
    extra_error = extra.get("error") if isinstance(extra, Mapping) else None
    if code in _SUCCESS_CODES and not extra_error:
        return
    message = _rejection_message(payload, extra_error)
    lowered = message.casefold()
    if any(token in lowered for token in ("已存在", "重复", "同名", "exist", "duplicate")):
        raise ObjectAlreadyExistsError(
            f"actual value: {actual_value(message)}; allowed mutation input: values accepted by the reviewed dry-run contract",
            field="name",
            next_action="Choose a unique segment name, or reuse the existing SDK-owned segment returned by marker lookup.",
        )
    if any(token in lowered for token in ("引用", "使用中", "referenc", "in use")):
        raise ObjectReferencedError(
            f"actual value: {actual_value(message)}; allowed delete target: a segment with no upstream references",
            field="segment_id",
            next_action="Remove the analyses or SDK-owned segments that reference this segment, then retry the delete once.",
        )
    if any(token in lowered for token in ("配额", "限额", "上限", "quota", "limit exceeded")):
        raise QuotaExceededError(
            f"actual value: {actual_value(message)}; allowed create state: workspace segment usage below its quota",
            field="segment",
            next_action="Delete an unused SDK-owned segment or ask the workspace owner to raise the segment quota, then retry once.",
        )
    if any(token in lowered for token in ("并发", "已修改", "版本冲突", "concurrent", "modified", "version conflict")):
        raise ConcurrentModificationError(
            f"actual value: {actual_value(message)}; allowed update state: the reviewed preimage is still current",
            field="segment_id",
            next_action="Read the segment again, review the current state, and issue a new explicit write; the SDK will not replay the old write.",
        )
    if message:
        raise InputValidationError(
            f"actual value: {actual_value(message)}; allowed mutation input: values accepted by the reviewed dry-run contract",
            field="mutation",
            next_action="Review the dry-run request and current target state, correct the caller-owned input, then issue a new explicit write.",
        )
    raise UpstreamError(
        "Gravity rejected the mutation without a classified error",
        next_action="Read the target state before deciding whether to issue another explicit write.",
    )


def _rejection_message(payload: Mapping[str, Any], extra_error: Any) -> str:
    for value in (
        extra_error,
        payload.get("message"),
        payload.get("msg"),
        payload.get("error"),
    ):
        if isinstance(value, str) and value.strip():
            return " ".join(value.splitlines()).strip()[:500]
        if isinstance(value, Mapping):
            for key in ("message", "msg", "error"):
                nested = value.get(key)
                if isinstance(nested, str) and nested.strip():
                    return " ".join(nested.splitlines()).strip()[:500]
    return ""


__all__ = ["MUTATION_SCHEMA_VERSION", "MutationExecutor"]
