"""Exact operation registry and read-only policy enforcement."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import threading
import time
import weakref
from dataclasses import dataclass
from datetime import date as calendar_date
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .errors import ManifestError, PolicyViolation, UnknownOperationError
from .fingerprints import contract_fingerprint
from .export_policy import (
    EffectRoute, ExportPolicyMixin, _AuthorizedEffectRequest,
    _consume_authorized_blob_download, _consume_authorized_effect_request,
)
from .models import OperationSpec
from .mutation_policy import MutationPolicyMixin
from .segment_rule_wire import (
    _analysis_segment_rule_request_parts,
    segment_mutation_request_builder,
)
from .wire import (
    canonical_wire_snapshot as _canonical_wire_snapshot,
    isolated_wire as _isolated_wire,
)
from .multidim import OPERATIONS as MULTIDIM_OPERATIONS, build_request_body
from .request_codecs import (
    analysis_account_user_request_parts,
    analysis_segment_request_parts,
    app_onelink_request_parts,
)
_RUNTIME_BINDINGS_PATH = (
    Path(__file__).resolve().parent / "contracts" / "runtime-operation-bindings.json"
)


def _load_request_builder_names(
    path: Path = _RUNTIME_BINDINGS_PATH,
) -> dict[str, str]:
    try:
        return dict(json.loads(path.read_text(encoding="utf-8"))["request_builders"])
    except (KeyError, OSError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestError("could not load runtime operation bindings") from exc


_REQUEST_BUILDER_NAMES = _load_request_builder_names()
_READ_ACTIONS = frozenset(
    {"get", "list", "read", "query", "detail", "tree", "status", "metadata", "schema", "calc_total"})
_BLOCKED_STABILITY = frozenset({"permission_unavailable", "blocked_privacy", "blocked_write"})
_BLOCKED_PATH_SEGMENTS = frozenset(
    {
        "authorization",
        "authorize",
        "approve",
        "bind",
        "create",
        "delete",
        "disable",
        "download",
        "edit",
        "enable",
        "export",
        "grant",
        "import",
        "publish",
        "reject",
        "remove",
        "save",
        "share",
        "start",
        "stop",
        "submit",
        "subscribe",
        "switch",
        "unbind",
        "undelete",
        "upload",
        "update",
    }
)
_BLOCKED_TERMINAL_TOKENS = _BLOCKED_PATH_SEGMENTS | frozenset(
    {
        "add", "apply", "archive", "cancel", "collect", "confirm", "copy",
        "execute", "manage", "modify", "move", "mutate", "one", "push",
        "reset", "restore", "revoke", "run", "set", "sync", "trigger",
    }
)
_EXACT_READ_ONLY_PATH_EXCEPTIONS = frozenset({
    "/turbo_engine/api/v2/event/in_report/hide_or_delete_prop/",
    "/turbo_engine/api/v2/datamanageconfig/template/subject/share/list/",
    "/turbo_engine/api/v2/datamanageconfig/template/share/list/", "/turbo_engine/api/v3/subscribe/list/",
})
_MATERIAL_REPORT_METRICS: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "bytedance": ("stat_cost", "ctr", "convert_rate"),
        "tencent": ("cost", "ctr", "conversions_rate"),
        "kuaishou": ("charge", "action_ratio", "conversion_ratio"),
        "bilibili": ("cost", "click_rate"),
    }
)

@dataclass(frozen=True, eq=False)
class _AuthorizedRequest:
    """One-shot wire request minted from a validated registry operation.

    This deliberately stays private.  Transport accepts network work only when
    the exact object was minted by its own PolicyEngine, so callers cannot skip
    input codecs and inject arbitrary query/body fields.
    """

    nonce: str
    operation: OperationSpec
    method: str
    path: str
    query: Mapping[str, Any]
    body: Mapping[str, Any]


_AUTHORIZATION_BROKER_LOCK = threading.Lock()
_AUTHORIZATION_OWNERS: weakref.WeakKeyDictionary[Any, Any] = (
    weakref.WeakKeyDictionary()
)


def _register_authorized_request(
    authorization: _AuthorizedRequest,
    owner: Any,
) -> None:
    """Register the exact receipt identity at the final network gate.

    A nonce or a dataclass-shaped value is insufficient: callers can import
    private Python names and construct lookalikes.  The broker records the
    identity of each receipt minted by its PolicyEngine, and the runtime claims
    that identity exactly once immediately before any network I/O.
    """

    with _AUTHORIZATION_BROKER_LOCK:
        _AUTHORIZATION_OWNERS[authorization] = owner


def _consume_authorized_request(
    authorization: object,
    *,
    method: str,
    path: str,
    query: Mapping[str, Any] | None,
    body: Mapping[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Atomically claim and validate a PolicyEngine-minted wire receipt."""

    if isinstance(authorization, _AuthorizedEffectRequest):
        return _consume_authorized_effect_request(
            authorization,
            method=method,
            path=path,
            query=query,
            body=body,
        )
    if not isinstance(authorization, _AuthorizedRequest):
        raise PolicyViolation("Insight runtime requires a policy authorization")
    with _AUTHORIZATION_BROKER_LOCK:
        owner = _AUTHORIZATION_OWNERS.pop(authorization, None)
    if not isinstance(owner, PolicyEngine):
        raise PolicyViolation(
            "transport request authorization is invalid or already consumed"
        )
    consume = (
        owner._consume_mutation_request
        if authorization.operation.effect == "mutation"
        else owner._consume_request
    )
    return consume(
        authorization,
        operation=authorization.operation,
        method=method,
        path=path,
        query=query,
        body=body,
    )
class Registry:
    def __init__(self, operations: Iterable[OperationSpec]) -> None:
        by_id: dict[str, OperationSpec] = {}
        requests: set[tuple[str, str]] = set()
        for operation in operations:
            if operation.operation_id in by_id:
                raise ManifestError(f"duplicate operation_id: {operation.operation_id}")
            request_key = (operation.upstream_method, operation.path_template)
            if request_key in requests:
                raise ManifestError("multiple operations cannot own the same method and path template")
            by_id[operation.operation_id] = operation
            requests.add(request_key)
        if not by_id:
            raise ManifestError("operation registry must not be empty")
        _validate_parent_graph(by_id)
        self._operations: Mapping[str, OperationSpec] = MappingProxyType(by_id)

    def get(self, operation_id: str) -> OperationSpec:
        try:
            return self._operations[operation_id]
        except KeyError as exc:
            raise UnknownOperationError(f"unknown Gravity operation: {operation_id}; run `gravity insight operations search <query>` and retry with a listed operation_id", field="operation_id") from exc

    def all(self) -> tuple[OperationSpec, ...]:
        return tuple(self._operations[key] for key in sorted(self._operations))

    def operations(
        self,
        *,
        domain: str | None = None,
        platform: str | None = None,
        stability: str | None = "stable",
    ) -> list[dict[str, object]]:
        operations = self.all()
        if domain is not None:
            operations = tuple(item for item in operations if item.domain == domain)
        if platform is not None:
            operations = tuple(item for item in operations if item.platform == platform)
        if stability is not None:
            operations = tuple(item for item in operations if item.stability == stability)
        return [operation.operation_summary() for operation in operations]

    def schema(self, operation_id: str | None = None) -> dict[str, object]:
        if operation_id is not None:
            return self.get(operation_id).schema()
        return {operation.operation_id: operation.schema() for operation in self.all()}

    def fingerprint(self, operation_id: str) -> str:
        return contract_fingerprint(self.get(operation_id))


class PolicyEngine(MutationPolicyMixin, ExportPolicyMixin):
    """Fail closed unless an exact manifest operation authorizes the request."""

    def __init__(
        self,
        registry: Registry,
        *,
        allow_experimental: bool = False,
        effect_routes: Iterable[EffectRoute] = (),
    ) -> None:
        self.registry = registry
        self.allow_experimental = allow_experimental
        self._authorization_lock = threading.Lock()
        self._pending_authorizations: dict[str, tuple[str, str]] = {}
        self._initialize_mutation_policy()
        self._initialize_effect_policy(effect_routes)

    def authorize_operation(self, operation_id: str) -> OperationSpec:
        operation = self.registry.get(operation_id)
        if not operation.executable:
            raise PolicyViolation(
                f"operation is catalog-only: {operation.block_reason or 'not executable'}"
            )
        if operation.stability in _BLOCKED_STABILITY or operation.stability == "deprecated":
            raise PolicyViolation(f"operation is unavailable by policy: {operation.stability}")
        if operation.stability == "experimental" and not self.allow_experimental:
            raise PolicyViolation("experimental operation requires explicit opt-in")
        if operation.stability not in {"stable", "experimental"}:
            raise PolicyViolation(f"unsupported operation stability: {operation.stability}")
        if operation.effect != "read":
            raise PolicyViolation("operation effect is not read-only")
        if operation.action.casefold() not in _READ_ACTIONS:
            raise PolicyViolation("operation action is not read-only")
        if operation.auth_profile != "gravity_authorization":
            raise PolicyViolation("operation uses an unsupported authentication profile")
        self._check_template(operation.path_template)
        return operation

    def authorize_request(self, operation: OperationSpec, method: str, path: str) -> None:
        registered = self.registry.get(operation.operation_id)
        if registered != operation:
            raise PolicyViolation("operation contract is not owned by this registry")
        if method.upper() != operation.upstream_method or not operation.matches_path(path):
            raise PolicyViolation("request does not match the operation allowlist")
        self._check_template(path)

    def _prepare_request(
        self,
        operation_id: str,
        inputs: Mapping[str, Any] | None,
    ) -> _AuthorizedRequest:
        """Validate inputs and deterministically mint one exact wire request."""

        operation = self.authorize_operation(operation_id)
        values = operation.validate_inputs(inputs)
        path = operation.render_path(values)
        self.authorize_request(operation, operation.upstream_method, path)
        query, body = _request_parts(operation, values)
        wire_snapshot = _canonical_wire_snapshot(query, body)
        isolated_wire = json.loads(wire_snapshot)
        query = isolated_wire["query"]
        body = isolated_wire["body"]
        nonce = secrets.token_urlsafe(32)
        digest = _request_digest(operation, operation.upstream_method, path, query, body)
        with self._authorization_lock:
            self._pending_authorizations[nonce] = (digest, wire_snapshot)
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

    def _consume_request(
        self,
        authorization: object,
        *,
        operation: OperationSpec,
        method: str,
        path: str,
        query: Mapping[str, Any] | None,
        body: Mapping[str, Any] | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Consume authorization and return the immutable validated wire snapshot."""

        if not isinstance(authorization, _AuthorizedRequest):
            raise PolicyViolation("transport requires an executor-authorized request")
        supplied_query = dict(query or {})
        supplied_body = dict(body or {})
        digest = _request_digest(operation, method, path, supplied_query, supplied_body)
        expected_object = (
            authorization.operation == operation
            and authorization.method == method.upper()
            and authorization.path == path
            and dict(authorization.query) == supplied_query
            and dict(authorization.body) == supplied_body
        )
        with self._authorization_lock:
            pending = self._pending_authorizations.pop(authorization.nonce, None)
        if pending is None:
            raise PolicyViolation("transport request authorization is invalid or already consumed")
        expected_digest, wire_snapshot = pending
        if not expected_object or expected_digest != digest:
            raise PolicyViolation("transport request authorization is invalid or already consumed")
        self.authorize_request(operation, method, path)
        isolated_wire = json.loads(wire_snapshot)
        isolated_query = isolated_wire.get("query")
        isolated_body = isolated_wire.get("body")
        if not isinstance(isolated_query, dict) or not isinstance(isolated_body, dict):
            raise PolicyViolation("transport request snapshot is invalid")
        return isolated_query, isolated_body

    @staticmethod
    def _check_template(path: str, *, allow_mutation: bool = False) -> None:
        if path.startswith("/account_center/api/v1/user_login/") or not path.startswith(
            ("/account_center/api/", "/apprank/api/", "/report/api/", "/turbo_engine/api/")
        ):
            raise PolicyViolation("operation path is outside approved Gravity API namespaces")
        segments = {segment.casefold() for segment in path.split("/") if segment}
        exact_read_exception = path in _EXACT_READ_ONLY_PATH_EXCEPTIONS
        if (
            not allow_mutation
            and not exact_read_exception
            and segments & _BLOCKED_PATH_SEGMENTS
        ):
            raise PolicyViolation("operation path contains a blocked write or extraction segment")
        terminal = next((segment for segment in reversed(path.split("/")) if segment), "")
        terminal_tokens = {token for token in re.split(r"[_-]+", terminal.casefold()) if token}
        if (
            not allow_mutation
            and not exact_read_exception
            and terminal_tokens & _BLOCKED_TERMINAL_TOKENS
        ):
            raise PolicyViolation("operation path terminates in a blocked mutation action")


def _request_parts(
    operation: OperationSpec, values: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the wire payload exclusively from the manifest request codec."""

    builder = segment_mutation_request_builder(
        operation.operation_id
    )
    builder_name = _REQUEST_BUILDER_NAMES.get(operation.operation_id)
    if builder is None and builder_name is not None:
        builder = globals().get(builder_name)
        if not callable(builder):
            raise ManifestError("runtime operation binding names an unavailable builder")
    if builder:
        return builder(values)
    if operation.operation_id in MULTIDIM_OPERATIONS:
        return _isolated_wire({}, build_request_body(operation.operation_id, values))

    path_fields = set(operation.path_fields)
    query: dict[str, Any] = {}
    body: dict[str, Any] = {}
    if operation.request.query_fields or operation.request.body_fields:
        for name in operation.request.query_fields:
            if name in values:
                query[name] = values[name]
        for name in operation.request.body_fields:
            if name in values:
                body[name] = values[name]
    else:
        target = body if operation.request.location == "body" else query
        target.update({key: value for key, value in values.items() if key not in path_fields})
    # Fixed values are applied last and can never be caller-controlled.
    query.update(operation.request.fixed_query)
    body.update(operation.request.fixed_body)
    declared = set(operation.request.query_fields) | set(operation.request.body_fields) | path_fields
    if declared:
        unused = set(values) - declared - set(operation.request.defaults)
        unused |= set(operation.request.defaults) - declared
        if unused:
            raise PolicyViolation(
                "operation contract contains validated inputs not bound to the request codec"
            )
    isolated = json.loads(_canonical_wire_snapshot(query, body))
    return isolated["query"], isolated["body"]


def _analysis_order_detail_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    conditions = _analysis_conditions_with_optional_day(
        values, default_field="create_time", default_type="event"
    )
    fields = values.get("fields") or (
        "ClientID",
        "AdPlatform",
        "Amount",
        "BackAmount",
        "PayCount",
        "PostbackStatus",
        "PostBackCode",
        "PassStatus",
        "Status",
        "event$pay_method",
        "event$pay_reason",
    )
    body = {
        "query_id": _analysis_query_id(),
        "app_id": _wire_identifier(values.get("app_id"), "app_id"),
        "page": values.get("page", 1),
        "page_size": values.get("page_size", 20),
        "order_by_list": values.get("order_by_list", []),
        "global_conditions": conditions,
        "order_conditions": values.get("order_conditions", []),
        "user_cond_logic": values.get("user_cond_logic", "AND"),
        "order_cond_logic": values.get("order_cond_logic", "AND"),
        "field_map": list(fields),
    }
    return _isolated_wire({}, body)


_MONETIZATION_BASE_FIELDS = (
    "CreateTime",
    "AdEventTime",
    "AdPlatform",
    "AdvertiserID",
    "AdAid",
    "TurboPromotedObjectID",
    "event$ad_type",
    "event$adn_type",
    "event$ad_unit_id",
    "event$ad_through",
    "event$ad_source_id",
    "event$ad_placement_id",
    "event$ecpm",
    "samount",
    "re_attribute_info",
)


def _analysis_monetization_detail_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    conditions = _analysis_conditions_with_optional_day(
        values, default_field="create_time", default_type="event"
    )
    fields = values.get("fields") or _MONETIZATION_BASE_FIELDS
    body = {
        "query_id": _analysis_query_id(),
        "app_id": _wire_identifier(values.get("app_id"), "app_id"),
        "page": values.get("page", 1),
        "page_size": values.get("page_size", 20),
        "order_by_list": values.get("order_by_list", []),
        "global_conditions": conditions,
        "local_conditions": values.get("local_conditions", []),
        "field_map": list(fields),
    }
    return _isolated_wire({}, body)


def _analysis_user_detail_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    conditions = _analysis_conditions_with_optional_day(
        values, default_field="create_date_list", default_type="default_user"
    )
    client_id = values.get("client_id")
    if client_id not in (None, ""):
        conditions.append(
            {
                "operator": "IN",
                "field": "client_id_list",
                "type": "default_user",
                "value": [
                    _wire_identifier(client_id, "client_id", coerce_int=False)
                ],
            }
        )
    fields = values.get("fields") or (
        "CreateTime",
        "ClientID",
        "AdPlatform",
        "Channel",
        "Version",
        "TurboPromotedObjectID",
        "AdvertiserID",
        "AdAid",
    )
    body = {
        "query_id": _analysis_query_id(),
        "app_id": _wire_identifier(values.get("app_id"), "app_id"),
        "page": values.get("page", 1),
        "page_size": values.get("page_size", 20),
        "order_by_list": values.get("order_by_list", []),
        "global_conditions": conditions,
        "postback_conditions": values.get("postback_conditions", []),
        "user_cond_logic": values.get("user_cond_logic", "AND"),
        "postback_cond_logic": values.get("postback_cond_logic", "AND"),
        "field_map": list(fields),
    }
    return _isolated_wire({}, body)


def _analysis_user_event_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    supplied_range = values.get("date_list")
    if supplied_range not in (None, (), []):
        if not isinstance(supplied_range, (list, tuple)) or len(supplied_range) != 2:
            raise PolicyViolation("analysis date_list must contain start and end dates")
        date_list = [_analysis_day(item) for item in supplied_range]
        if date_list[0] > date_list[1]:
            raise PolicyViolation("analysis date_list is reversed")
    else:
        day = _analysis_day(values.get("date"))
        date_list = [day, day]
    body = {
        "app_id": _wire_identifier(values.get("app_id"), "app_id"),
        "client_id": _wire_identifier(
            values.get("client_id"), "client_id", coerce_int=False
        ),
        "desc": values.get("desc", True),
        "group_by": values.get("group_by", "day"),
        "event_list": values.get("event_list", []),
        "date_list": date_list,
        "page_info": {
            "page": values.get("page", 1),
            "page_size": values.get("page_size", 20),
        },
        "query_item_list": values.get("query_item_list", []),
    }
    return _isolated_wire({}, body)


def _analysis_segment_uid_result_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    start, end = _analysis_day_bounds(values.get("date"))
    query = {
        "page": values.get("page", 1),
        "page_size": values.get("page_size", 100),
        "start_time": start,
        "end_time": end,
        "segment_id": _wire_identifier(values.get("segment_id"), "segment_id"),
    }
    return _isolated_wire(query, {})


def _analysis_segment_user_detail_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    segment_id = _wire_identifier(values.get("segment_id"), "segment_id")
    body: dict[str, Any] = {
        "tmp_segment_id": segment_id,
        "app_id": _wire_identifier(values.get("app_id"), "app_id"),
        "segment_id": segment_id,
        "to_update_segment": False,
    }
    version = values.get("segment_version_id")
    if version not in (None, ""):
        body["segment_version_id"] = _wire_identifier(
            version, "segment_version_id", coerce_int=False
        )
    return _isolated_wire({}, body)


def _analysis_order_split_detail_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    pay_event_time = values.get("pay_event_time")
    if not isinstance(pay_event_time, str) or not 1 <= len(pay_event_time.strip()) <= 64:
        raise PolicyViolation("analysis pay_event_time is invalid")
    split_ids = values.get("split_trace_ids", [])
    if not isinstance(split_ids, (list, tuple)) or len(split_ids) > 100:
        raise PolicyViolation("analysis split_trace_ids is invalid")
    safe_split_ids = [
        _wire_identifier(item, "split_trace_ids", coerce_int=False)
        for item in split_ids
    ]
    body = {
        "app_id": _wire_identifier(values.get("app_id"), "app_id"),
        "PayEventTime": pay_event_time.strip(),
        "TraceID": _wire_identifier(
            values.get("trace_id"), "trace_id", coerce_int=False
        ),
        "ClientID": _wire_identifier(
            values.get("client_id"), "client_id", coerce_int=False
        ),
        "$split_trace_id_list": safe_split_ids,
    }
    return _isolated_wire({}, body)


def _analysis_user_postback_log_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    body = {
        "app_id": _wire_identifier(values.get("app_id"), "app_id"),
        "client_id": _wire_identifier(
            values.get("client_id"), "client_id", coerce_int=False
        ),
    }
    return _isolated_wire({}, body)


def _analysis_query_id() -> str:
    milliseconds = f"{int(time.time() * 1_000):013d}"[-13:]
    return milliseconds + secrets.token_hex(10)[:19]


def _analysis_day(value: Any) -> str:
    if not isinstance(value, str):
        raise PolicyViolation("analysis date must be an ISO calendar date")
    try:
        parsed = calendar_date.fromisoformat(value)
    except ValueError as exc:
        raise PolicyViolation("analysis date must be an ISO calendar date") from exc
    normalized = parsed.isoformat()
    if normalized != value:
        raise PolicyViolation("analysis date must be a canonical ISO calendar date")
    return normalized


def _analysis_day_bounds(value: Any) -> tuple[str, str]:
    day = _analysis_day(value)
    return f"{day} 00:00:00", f"{day} 23:59:59"


def _analysis_conditions_with_optional_day(
    values: Mapping[str, Any],
    *,
    default_field: str,
    default_type: str,
) -> list[Any]:
    supplied = values.get("global_conditions", [])
    if not isinstance(supplied, (list, tuple)):
        raise PolicyViolation("analysis global_conditions is invalid")
    conditions = list(supplied)
    day = values.get("date")
    if day not in (None, ""):
        start, end = _analysis_day_bounds(day)
        conditions.append(
            {
                "operator": "RANGE_IN",
                "field": default_field,
                "type": default_type,
                "value": [start, end],
            }
        )
    return conditions


def _wire_identifier(
    value: Any,
    name: str,
    *,
    coerce_int: bool = True,
) -> str | int:
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise PolicyViolation(f"analysis {name} is invalid")
    text = str(value).strip()
    if not text or len(text) > 256:
        raise PolicyViolation(f"analysis {name} is invalid")
    return int(text) if coerce_int and text.isdecimal() else text


def _business_report_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Encode the public platform allowlist into the manager-report filter."""

    body = {
        "page": values.get("page", 1),
        "page_size": values.get("page_size", 20),
        "date_list": values.get("date_list"),
        "app_list": values.get("app_list"),
        "metrics_list": values.get("metrics_list"),
        "dims_list": values.get("dims_list"),
        "filtering": {"ad_platform_list": values.get("ad_platform_list")},
    }
    if values.get("need_ratio") is True:
        body["need_ratio"] = True
    if values.get("calc_diff") is True:
        body["calc_diff"] = True
    isolated = json.loads(_canonical_wire_snapshot({}, body))
    return isolated["query"], isolated["body"]


def _material_report_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a platform-specific aggregate without personnel dimensions."""

    platform = values.get("platform")
    metrics = _MATERIAL_REPORT_METRICS.get(platform)
    if metrics is None:
        raise PolicyViolation("material report platform is outside the codec allowlist")
    body = {
        "data_dims": ["material"],
        "date_dims": "total",
        "metrics_list": list(metrics),
        "gravity_metrics_list": [
            "AppRealRegisterCnt",
            "AppGamePayUserCntStandardAtv",
        ],
        "stat_list": [],
        "filters": [
            {"field": "ad_platform", "operator": "EQUALS", "values": [platform]},
            {
                "field": "app_id",
                "operator": "IN",
                "values": values.get("app_list"),
            },
        ],
        "date_list": values.get("date_list"),
        "relate_dims": [],
        "order_by": [],
        "page": values.get("page", 1),
        "page_size": values.get("page_size", 10),
    }
    isolated = json.loads(_canonical_wire_snapshot({}, body))
    return isolated["query"], isolated["body"]


def _request_digest(
    operation: OperationSpec,
    method: str,
    path: str,
    query: Mapping[str, Any],
    body: Mapping[str, Any],
) -> str:
    try:
        encoded = json.dumps(
            {
                "operation_id": operation.operation_id,
                "contract_version": operation.contract_version,
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


def _validate_parent_graph(operations: Mapping[str, OperationSpec]) -> None:
    graph: dict[str, tuple[str, ...]] = {}
    for operation_id, operation in operations.items():
        parents = tuple(
            parent.operation_id
            for parent in operation.required_parent
            if parent.operation_id is not None
        )
        missing = [parent for parent in parents if parent not in operations]
        if missing:
            raise ManifestError(
                f"required_parent references an unknown operation: {operation_id}"
            )
        if operation_id in parents:
            raise ManifestError("required_parent cannot reference its own operation")
        graph[operation_id] = parents

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(operation_id: str) -> None:
        if operation_id in visiting:
            raise ManifestError("required_parent graph contains a cycle")
        if operation_id in visited:
            return
        visiting.add(operation_id)
        for parent_id in graph[operation_id]:
            visit(parent_id)
        visiting.remove(operation_id)
        visited.add(operation_id)

    for operation_id in graph:
        visit(operation_id)
