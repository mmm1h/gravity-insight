"""One-shot policy receipts for exact, registered mutation contracts."""

from __future__ import annotations

import json
import secrets
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from .errors import PolicyViolation
from .models import OperationSpec
from .mutation_validation import validate_mutation_inputs


class MutationPolicyMixin:
    """Keep mutation authority separate from the read-only policy surface."""

    def _initialize_mutation_policy(self) -> None:
        self._pending_mutation_authorizations: dict[str, tuple[str, str]] = {}

    def authorize_mutation_operation(self, operation_id: str) -> OperationSpec:
        operation = self.registry.get(operation_id)
        if not operation.executable or operation.stability != "stable":
            raise PolicyViolation("mutation operation is not a stable executable contract")
        if operation.effect != "mutation":
            raise PolicyViolation("operation effect is not mutation")
        if operation.auth_profile != "gravity_authorization":
            raise PolicyViolation("operation uses an unsupported authentication profile")
        self._check_template(operation.path_template, allow_mutation=True)
        return operation

    def authorize_mutation_request(
        self, operation: OperationSpec, method: str, path: str
    ) -> None:
        registered = self.authorize_mutation_operation(operation.operation_id)
        if registered != operation:
            raise PolicyViolation("mutation contract is not owned by this registry")
        if method.upper() != operation.upstream_method or not operation.matches_path(path):
            raise PolicyViolation("mutation request does not match the operation allowlist")
        self._check_template(path, allow_mutation=True)

    def preview_mutation_request(
        self,
        operation_id: str,
        inputs: Mapping[str, Any] | None,
    ) -> tuple[OperationSpec, dict[str, Any], str, dict[str, Any], dict[str, Any]]:
        """Compile a mutation wire without minting authority or using transport."""

        from .registry import _request_parts

        operation = self.authorize_mutation_operation(operation_id)
        values = operation.validate_inputs(inputs)
        validate_mutation_inputs(operation_id, values)
        path = operation.render_path(values)
        self.authorize_mutation_request(operation, operation.upstream_method, path)
        query, body = _request_parts(operation, values)
        return operation, values, path, query, body

    def _prepare_mutation_request(
        self,
        operation_id: str,
        inputs: Mapping[str, Any] | None,
    ) -> Any:
        from .registry import (
            _AuthorizedRequest,
            _canonical_wire_snapshot,
            _register_authorized_request,
            _request_digest,
        )

        operation, _values, path, query, body = self.preview_mutation_request(
            operation_id, inputs
        )
        wire_snapshot = _canonical_wire_snapshot(query, body)
        isolated_wire = json.loads(wire_snapshot)
        query, body = isolated_wire["query"], isolated_wire["body"]
        nonce = secrets.token_urlsafe(32)
        digest = _request_digest(
            operation, operation.upstream_method, path, query, body
        )
        with self._authorization_lock:
            self._pending_mutation_authorizations[nonce] = (digest, wire_snapshot)
        authorization = _AuthorizedRequest(
            nonce=nonce,
            operation=operation,
            method=operation.upstream_method,
            path=path,
            query=MappingProxyType(query),
            body=MappingProxyType(body),
        )
        _register_authorized_request(authorization, self)
        return authorization

    def _consume_mutation_request(
        self,
        authorization: object,
        *,
        operation: OperationSpec,
        method: str,
        path: str,
        query: Mapping[str, Any] | None,
        body: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        from .registry import _AuthorizedRequest, _request_digest

        if not isinstance(authorization, _AuthorizedRequest):
            raise PolicyViolation("transport requires a mutation authorization")
        supplied_query, supplied_body = dict(query or {}), dict(body or {})
        digest = _request_digest(
            operation, method, path, supplied_query, supplied_body
        )
        expected_object = (
            authorization.operation == operation
            and authorization.method == method.upper()
            and authorization.path == path
            and dict(authorization.query) == supplied_query
            and dict(authorization.body) == supplied_body
        )
        with self._authorization_lock:
            pending = self._pending_mutation_authorizations.pop(
                authorization.nonce, None
            )
        if pending is None:
            raise PolicyViolation(
                "transport mutation authorization is invalid or already consumed"
            )
        expected_digest, wire_snapshot = pending
        if not expected_object or expected_digest != digest:
            raise PolicyViolation(
                "transport mutation authorization is invalid or already consumed"
            )
        self.authorize_mutation_request(operation, method, path)
        isolated_wire = json.loads(wire_snapshot)
        isolated_query, isolated_body = (
            isolated_wire.get("query"), isolated_wire.get("body")
        )
        if not isinstance(isolated_query, dict) or not isinstance(isolated_body, dict):
            raise PolicyViolation("transport mutation request snapshot is invalid")
        return isolated_query, isolated_body


__all__ = ["MutationPolicyMixin"]
