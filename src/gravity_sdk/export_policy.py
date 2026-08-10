"""Effect-specific policy receipts for governed exports."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import secrets
import threading
from types import MappingProxyType
from typing import Any, Iterable, Mapping
import weakref

from .errors import (
    InputValidationError,
    ManifestError,
    PolicyViolation,
    UnknownOperationError,
)


_EXPORT_EFFECTS = frozenset(
    {"export_job_create", "export_status", "export_download", "export_cancel"}
)


@dataclass(frozen=True)
class EffectRoute:
    """Exact non-read route owned by the export contract registry."""

    operation_id: str
    effect: str
    method: str
    path: str
    request_location: str
    allowed_fields: frozenset[str]
    required_fields: frozenset[str] = frozenset()
    fixed_fields: Mapping[str, Any] = field(default_factory=dict)
    executable: bool = False
    contract_status: str = "unverified"
    block_reason: str | None = None

    def __post_init__(self) -> None:
        method = self.method.upper()
        if self.effect not in _EXPORT_EFFECTS:
            raise ManifestError(f"unsupported export effect: {self.effect}")
        if method not in {"GET", "POST", "UNKNOWN"}:
            raise ManifestError(f"unsupported export method: {self.method}")
        if self.request_location not in {"query", "body", "none"}:
            raise ManifestError("export request_location must be query, body, or none")
        if not self.path.startswith("/") or "//" in self.path:
            raise ManifestError("export route path must be normalized and absolute")
        if not self.required_fields.issubset(self.allowed_fields):
            raise ManifestError("required export fields must be allowed")
        if not set(self.fixed_fields).issubset(self.allowed_fields):
            raise ManifestError("fixed export fields must be allowed")
        if self.executable and (
            self.contract_status != "verified" or method == "UNKNOWN"
        ):
            raise ManifestError(
                "only verified export routes with a known method are executable"
            )
        object.__setattr__(self, "method", method)
        object.__setattr__(
            self,
            "fixed_fields",
            MappingProxyType(dict(self.fixed_fields)),
        )


@dataclass(frozen=True, eq=False)
class _AuthorizedEffectRequest:
    nonce: str
    route: EffectRoute
    method: str
    path: str
    query: Mapping[str, Any]
    body: Mapping[str, Any]


@dataclass(frozen=True, eq=False)
class _AuthorizedBlobDownload:
    nonce: str
    job_id: str
    url: str
    declared_path: str
    expires_at: datetime
    authorization_scope: str


_BROKER_LOCK = threading.Lock()
_EFFECT_OWNERS: weakref.WeakKeyDictionary[_AuthorizedEffectRequest, Any] = (
    weakref.WeakKeyDictionary()
)
_BLOB_OWNERS: weakref.WeakKeyDictionary[_AuthorizedBlobDownload, Any] = (
    weakref.WeakKeyDictionary()
)


def _consume_authorized_effect_request(
    receipt: _AuthorizedEffectRequest,
    *,
    method: str,
    path: str,
    query: Mapping[str, Any] | None,
    body: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    with _BROKER_LOCK:
        owner = _EFFECT_OWNERS.pop(receipt, None)
    if not isinstance(owner, ExportPolicyMixin):
        raise PolicyViolation(
            "transport request authorization is invalid or already consumed"
        )
    return owner._consume_effect_request(
        receipt,
        method=method,
        path=path,
        query=query,
        body=body,
    )


def _consume_authorized_blob_download(
    receipt: object,
    *,
    source: Any,
) -> None:
    if not isinstance(receipt, _AuthorizedBlobDownload):
        raise PolicyViolation("export download requires a policy authorization")
    with _BROKER_LOCK:
        owner = _BLOB_OWNERS.pop(receipt, None)
    if not isinstance(owner, ExportPolicyMixin):
        raise PolicyViolation(
            "export download authorization is invalid or already consumed"
        )
    owner._consume_blob_download(receipt, source=source)


class ExportPolicyMixin:
    """Export effect authorization mixed into the read PolicyEngine."""

    def _initialize_effect_policy(
        self,
        effect_routes: Iterable[EffectRoute],
    ) -> None:
        routes: dict[str, EffectRoute] = {}
        route_keys: set[tuple[str, str]] = set()
        for route in effect_routes:
            if not isinstance(route, EffectRoute):
                raise ManifestError("effect registry accepts only EffectRoute values")
            if route.operation_id in routes:
                raise ManifestError(f"duplicate effect operation_id: {route.operation_id}")
            route_key = (route.method, route.path)
            if route.method != "UNKNOWN" and route_key in route_keys:
                raise ManifestError("multiple effects cannot own the same method and path")
            routes[route.operation_id] = route
            route_keys.add(route_key)
        self._effect_routes: Mapping[str, EffectRoute] = MappingProxyType(routes)
        self._pending_effect_authorizations: dict[str, tuple[str, str]] = {}
        self._consumed_status_authorizations: set[str] = set()
        self._pending_blob_authorizations: dict[str, tuple[Any, ...]] = {}

    def effect_routes(self) -> tuple[EffectRoute, ...]:
        return tuple(self._effect_routes[key] for key in sorted(self._effect_routes))

    def authorize_effect_operation(
        self,
        operation_id: str,
        *,
        expected_effect: str | None = None,
    ) -> EffectRoute:
        try:
            route = self._effect_routes[operation_id]
        except KeyError as exc:
            raise UnknownOperationError(
                f"unknown Gravity export operation: {operation_id}",
                field="operation_id",
                next_action=(
                    "Run `python -m gravity_sdk export list-capabilities` "
                    "and use an operation_id from the results."
                ),
            ) from exc
        if expected_effect is not None and route.effect != expected_effect:
            raise PolicyViolation(
                "export operation effect does not match this stage",
                field="operation_id",
                next_action=(
                    "Run `python -m gravity_sdk export describe "
                    f"{operation_id}` and use the documented workflow."
                ),
            )
        if not route.executable:
            raise PolicyViolation(
                f"export operation is catalog-only: {route.block_reason or 'unverified'}",
                field="operation_id",
                next_action=(
                    "Run `python -m gravity_sdk export describe "
                    f"{operation_id}` and select a currently_callable alternative."
                ),
            )
        if route.contract_status != "verified" or route.method == "UNKNOWN":
            raise PolicyViolation(
                "export operation has no verified wire contract",
                field="operation_id",
                next_action=(
                    "Run `python -m gravity_sdk export describe "
                    f"{operation_id}` and select a currently_callable alternative."
                ),
            )
        return route

    def _prepare_effect_request(
        self,
        operation_id: str,
        effect: str,
        payload: Mapping[str, Any] | None,
    ) -> _AuthorizedEffectRequest:
        route = self.authorize_effect_operation(
            operation_id,
            expected_effect=effect,
        )
        if effect not in _EXPORT_EFFECTS:
            raise PolicyViolation("unsupported export operation effect")
        values = _validated_effect_values(route, payload)
        query = values if route.request_location == "query" else {}
        body = values if route.request_location == "body" else {}
        wire_snapshot = _wire_snapshot(query, body)
        isolated_wire = json.loads(wire_snapshot)
        nonce = secrets.token_urlsafe(32)
        digest = _effect_request_digest(
            route,
            route.method,
            route.path,
            isolated_wire["query"],
            isolated_wire["body"],
        )
        with self._authorization_lock:
            self._pending_effect_authorizations[nonce] = (digest, wire_snapshot)
        receipt = _AuthorizedEffectRequest(
            nonce=nonce,
            route=route,
            method=route.method,
            path=route.path,
            query=MappingProxyType(isolated_wire["query"]),
            body=MappingProxyType(isolated_wire["body"]),
        )
        with _BROKER_LOCK:
            _EFFECT_OWNERS[receipt] = self
        return receipt

    def _consume_effect_request(
        self,
        receipt: _AuthorizedEffectRequest,
        *,
        method: str,
        path: str,
        query: Mapping[str, Any] | None,
        body: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        supplied_query = dict(query or {})
        supplied_body = dict(body or {})
        digest = _effect_request_digest(
            receipt.route,
            method,
            path,
            supplied_query,
            supplied_body,
        )
        expected_object = (
            receipt.method == method.upper()
            and receipt.path == path
            and dict(receipt.query) == supplied_query
            and dict(receipt.body) == supplied_body
        )
        with self._authorization_lock:
            pending = self._pending_effect_authorizations.pop(
                receipt.nonce,
                None,
            )
        if pending is None or not expected_object or pending[0] != digest:
            raise PolicyViolation(
                "transport request authorization is invalid or already consumed"
            )
        registered = self._effect_routes.get(receipt.route.operation_id)
        if registered != receipt.route or not registered.executable:
            raise PolicyViolation("export route is not owned by this policy")
        if receipt.route.effect == "export_status":
            with self._authorization_lock:
                self._consumed_status_authorizations.add(receipt.nonce)
        isolated_wire = json.loads(pending[1])
        return isolated_wire["query"], isolated_wire["body"]

    def authorize_blob_download(
        self,
        status_authorization: object,
        *,
        job_id: str,
        url: str,
        declared_path: str,
        expires_at: datetime,
        authorization_scope: str,
    ) -> object:
        if not isinstance(status_authorization, _AuthorizedEffectRequest):
            raise PolicyViolation("blob authorization requires a consumed status receipt")
        if status_authorization.route.effect != "export_status":
            raise PolicyViolation("blob authorization requires an export_status receipt")
        with self._authorization_lock:
            if status_authorization.nonce not in self._consumed_status_authorizations:
                raise PolicyViolation(
                    "status receipt is invalid, unconsumed, or already used for a download"
                )
            self._consumed_status_authorizations.remove(status_authorization.nonce)
        if not job_id.strip() or not url.strip() or not declared_path.startswith("/"):
            raise PolicyViolation("blob authorization metadata is invalid")
        nonce = secrets.token_urlsafe(32)
        receipt = _AuthorizedBlobDownload(
            nonce=nonce,
            job_id=job_id,
            url=url,
            declared_path=declared_path,
            expires_at=expires_at,
            authorization_scope=authorization_scope,
        )
        expected = (job_id, url, declared_path, expires_at, authorization_scope)
        with self._authorization_lock:
            self._pending_blob_authorizations[nonce] = expected
        with _BROKER_LOCK:
            _BLOB_OWNERS[receipt] = self
        return receipt

    def _consume_blob_download(
        self,
        receipt: _AuthorizedBlobDownload,
        *,
        source: Any,
    ) -> None:
        with self._authorization_lock:
            pending = self._pending_blob_authorizations.pop(
                receipt.nonce,
                None,
            )
        expected = (
            receipt.job_id,
            receipt.url,
            receipt.declared_path,
            receipt.expires_at,
            receipt.authorization_scope,
        )
        actual = (
            getattr(source, "job_id", None),
            getattr(source, "url", None),
            getattr(source, "declared_path", None),
            getattr(source, "expires_at", None),
            getattr(source, "authorization_scope", None),
        )
        if pending is None or pending != expected or actual != expected:
            raise PolicyViolation(
                "export download authorization is invalid or already consumed"
            )


def _validated_effect_values(
    route: EffectRoute,
    payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if payload is not None and not isinstance(payload, Mapping):
        raise PolicyViolation("export request payload must be an object")
    values = dict(payload or {})
    unknown = sorted(set(values) - set(route.allowed_fields))
    missing = sorted(set(route.required_fields) - set(values))
    fixed_mismatch = sorted(
        key
        for key, value in route.fixed_fields.items()
        if key in values and values[key] != value
    )
    if unknown or missing or fixed_mismatch:
        if unknown:
            field = unknown[0]
            message = (
                "unknown export input fields: "
                + ", ".join(unknown)
                + "; allowed fields: "
                + ", ".join(sorted(route.allowed_fields))
            )
        elif missing:
            field = missing[0]
            message = "missing required export input fields: " + ", ".join(missing)
        else:
            field = fixed_mismatch[0]
            message = "export fixed input fields do not match: " + ", ".join(
                fixed_mismatch
            )
        raise InputValidationError(
            message,
            field=field,
            next_action=(
                "Run `python -m gravity_sdk export describe "
                f"{route.operation_id}` and retry with the documented input."
            ),
        )
    values.update(route.fixed_fields)
    return values


def _wire_snapshot(query: Mapping[str, Any], body: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            {"query": query, "body": body},
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise PolicyViolation("request payload is not a canonical JSON value") from exc


def _effect_request_digest(
    route: EffectRoute,
    method: str,
    path: str,
    query: Mapping[str, Any],
    body: Mapping[str, Any],
) -> str:
    try:
        encoded = json.dumps(
            {
                "operation_id": route.operation_id,
                "effect": route.effect,
                "method": method.upper(),
                "path": path,
                "query": query,
                "body": body,
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PolicyViolation("request payload is not a canonical JSON value") from exc
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "EffectRoute",
    "ExportPolicyMixin",
    "_AuthorizedEffectRequest",
    "_consume_authorized_blob_download",
    "_consume_authorized_effect_request",
]
