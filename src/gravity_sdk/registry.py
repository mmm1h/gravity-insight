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
from datetime import date as calendar_date, timedelta
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .errors import ManifestError, PolicyViolation, UnknownOperationError
from .fingerprints import contract_fingerprint
from .export_policy import (
    EffectRoute, ExportPolicyMixin, _AuthorizedEffectRequest,
    _consume_authorized_blob_download, _consume_authorized_effect_request,
)
from .models import OperationSpec
from .multidim import OPERATIONS as MULTIDIM_OPERATIONS, build_request_body
from .request_codecs import (
    analysis_account_user_request_parts,
    analysis_segment_request_parts,
    app_onelink_request_parts,
)


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
    "/turbo_engine/api/v2/datamanageconfig/template/share/list/",
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
_AUTHORIZATION_OWNERS: weakref.WeakKeyDictionary[_AuthorizedRequest, Any] = (
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
    return owner._consume_request(
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
            raise UnknownOperationError(f"unknown Gravity operation: {operation_id}") from exc

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


class PolicyEngine(ExportPolicyMixin):
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
    def _check_template(path: str) -> None:
        if path.startswith("/account_center/api/v1/user_login/") or not path.startswith(
            ("/account_center/api/", "/apprank/api/", "/report/api/", "/turbo_engine/api/")
        ):
            raise PolicyViolation("operation path is outside approved Gravity API namespaces")
        segments = {segment.casefold() for segment in path.split("/") if segment}
        exact_read_exception = path in _EXACT_READ_ONLY_PATH_EXCEPTIONS
        if not exact_read_exception and segments & _BLOCKED_PATH_SEGMENTS:
            raise PolicyViolation("operation path contains a blocked write or extraction segment")
        terminal = next((segment for segment in reversed(path.split("/")) if segment), "")
        terminal_tokens = {token for token in re.split(r"[_-]+", terminal.casefold()) if token}
        if (
            not exact_read_exception
            and terminal_tokens & _BLOCKED_TERMINAL_TOKENS
        ):
            raise PolicyViolation("operation path terminates in a blocked mutation action")


def _request_parts(
    operation: OperationSpec, values: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the wire payload exclusively from the manifest request codec."""

    builder = {"analysis.segment.list": analysis_segment_request_parts, "analysis.segment.evaluate_percent": _analysis_segment_rule_request_parts, "analysis.account_user.list": analysis_account_user_request_parts, "app.onelink.list": app_onelink_request_parts}.get(operation.operation_id)
    if builder: return builder(values)
    if operation.operation_id == "analysis.order_detail.list":
        return _analysis_order_detail_request_parts(values)
    if operation.operation_id == "analysis.monetization_detail.list":
        return _analysis_monetization_detail_request_parts(values)
    if operation.operation_id == "analysis.user_detail.list":
        return _analysis_user_detail_request_parts(values)
    if operation.operation_id == "analysis.user_event.list":
        return _analysis_user_event_request_parts(values)
    if operation.operation_id == "analysis.segment.uid_result.list":
        return _analysis_segment_uid_result_request_parts(values)
    if operation.operation_id == "analysis.segment.user_detail.list":
        return _analysis_segment_user_detail_request_parts(values)
    if operation.operation_id == "analysis.order_split_detail.list":
        return _analysis_order_split_detail_request_parts(values)
    if operation.operation_id == "analysis.user_postback_log.list":
        return _analysis_user_postback_log_request_parts(values)
    if operation.operation_id == "report.business.query":
        return _business_report_request_parts(values)
    if operation.operation_id == "material.report.query":
        return _material_report_request_parts(values)
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


def _analysis_segment_rule_request_parts(
    values: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile the public segment-rule contract into Gravity's frontend wire shape."""

    app_id = values.get("app_id")
    if not isinstance(app_id, str) or not app_id.isdecimal():
        raise PolicyViolation("analysis segment-rule app_id must be decimal")
    property_rules = values.get("user_property_rules", {})
    event_rules = values.get("user_event_rules", {})
    if not isinstance(property_rules, Mapping) or not isinstance(event_rules, Mapping):
        raise PolicyViolation("analysis segment rules are invalid")

    property_groups = [
        _compile_segment_property_group(group)
        for group in property_rules.get("groups", ())
    ]
    event_groups = [
        _compile_segment_event_group(group)
        for group in event_rules.get("groups", ())
    ]
    frontend_property_groups = [
        _frontend_segment_property_group(group)
        for group in property_rules.get("groups", ())
    ]
    frontend_event_groups = [
        _frontend_segment_event_group(group)
        for group in event_rules.get("groups", ())
    ]
    body = {
        "app_id": int(app_id),
        "segment_name": values.get("name"),
        "segment_remark": values.get("remark", ""),
        "update_type": values.get("update_type", "Manual"),
        "update_date_range": values.get("date_range"),
        "cond_logic": values.get("cond_logic", "AND"),
        "from_user_prop": {
            "cond_logic": property_rules.get("cond_logic", "AND"),
            "list": property_groups,
        },
        "from_event_prop": {
            "cond_logic": event_rules.get("cond_logic", "AND"),
            "list": event_groups,
        },
        "FE_CONFIG": json.dumps(
            {
                "userPropertyRules": frontend_property_groups,
                "userBehaviorRules": frontend_event_groups,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    }
    isolated = json.loads(_canonical_wire_snapshot({}, body))
    return isolated["query"], isolated["body"]


def _compile_segment_property_group(group: Any) -> dict[str, Any]:
    if not isinstance(group, Mapping):
        raise PolicyViolation("analysis segment property group is invalid")
    return {
        "cond_logic": group.get("cond_logic", "AND"),
        "list": [
            _compile_segment_condition(item)
            for item in group.get("conditions", ())
        ],
    }


def _compile_segment_event_group(group: Any) -> dict[str, Any]:
    if not isinstance(group, Mapping):
        raise PolicyViolation("analysis segment event group is invalid")
    return {
        "cond_logic": group.get("cond_logic", "AND"),
        "list": [
            _compile_segment_event(item)
            for item in group.get("conditions", ())
        ],
    }


def _compile_segment_condition(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise PolicyViolation("analysis segment condition is invalid")
    operator = str(item.get("operator", ""))
    wire: dict[str, Any] = {
        "operator": _segment_condition_operator(item),
        "field": item.get("field"),
        "type": item.get("type"),
        "value": _segment_condition_values(item),
    }
    dim_table = item.get("dim_using_table_name")
    if dim_table not in {None, ""}:
        wire["dim_using_table_name"] = dim_table
    if operator == "TRUE":
        wire["value"] = [True]
    elif operator == "FALSE":
        wire["value"] = [False]
    elif item.get("type") == "user_segment":
        wire["value"] = [True]
    return wire


def _segment_condition_operator(item: Mapping[str, Any]) -> str:
    operator = str(item.get("operator", ""))
    if operator in {"TRUE", "FALSE"}:
        return "EQUALS"
    if operator == "RELATIVE_DAY":
        return "CURRENT_DAY"
    if operator != "RELATIVELY_CURRENT_TIME":
        return operator
    relative_type = item.get("date_relative_type")
    relative_unit = item.get("date_relative_unit")
    if relative_type == "range" and relative_unit == "day":
        return "RELATIVE_DAY"
    if relative_type == "range" and relative_unit == "hour":
        return "RELATIVE_HOUR"
    if relative_type == "range" and relative_unit == "minute":
        return "RELATIVE_MINUTE"
    if relative_type == "day":
        return "RELATIVE_DAY"
    if relative_type == "week":
        return "RELATIVE_WEEK"
    if relative_type == "month":
        return "RELATIVE_MONTH"
    return operator


def _segment_condition_values(item: Mapping[str, Any]) -> list[Any]:
    raw_values = item.get("value", ())
    values = list(raw_values) if isinstance(raw_values, (list, tuple)) else []
    operator = item.get("operator")
    date_type = item.get("date_type")
    date_unit = item.get("date_unit")
    if operator == "CURRENT_DAY" and values:
        amount = values[0]
        if date_type == "past":
            return [-amount, 0] if date_unit == "within" else [-999, -amount]
        return [0, amount] if date_unit == "within" else [amount, 999]
    if operator == "RELATIVE_DAY" and len(values) >= 2:
        if date_type == "past":
            return [-values[0], -values[1]]
        return [values[0], values[1]]
    if operator == "RELATIVELY_CURRENT_TIME":
        relative_type = item.get("date_relative_type")
        if relative_type != "range":
            return ["event", "$EventCreateTime", 0, 0]
        if len(values) >= 2:
            left, right = values[:2]
            if item.get("date_relative_left") == "past":
                left = -left
            if item.get("date_relative_right") == "past":
                right = -right
            return ["event", "$EventCreateTime", left, right]
    return values


def _compile_segment_event(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise PolicyViolation("analysis segment event is invalid")
    target = item.get("target")
    did_condition = item.get("did_condition")
    if not isinstance(target, Mapping) or not isinstance(did_condition, Mapping):
        raise PolicyViolation("analysis segment event target is invalid")
    wire_target = {"name": target.get("name"), "field": target.get("field")}
    dim_table = target.get("dim_using_table_name")
    if dim_table not in {None, ""}:
        wire_target["dim_using_table_name"] = dim_table
    wire_did = {
        "operator": did_condition.get("operator"),
        "field": target.get("field"),
        "type": "event",
        "value": list(did_condition.get("value", ())),
    }
    if dim_table not in {None, ""}:
        wire_did["dim_using_table_name"] = dim_table
    return {
        "event_name": item.get("event_name"),
        "did": item.get("did"),
        "target": wire_target,
        "did_condition": wire_did,
        "time_zone": _segment_event_time_zone(item.get("date_range")),
        "cond_logic": item.get("cond_logic", "AND"),
        "conditions": [
            _compile_segment_condition(condition)
            for condition in item.get("conditions", ())
        ],
    }


def _segment_event_time_zone(value: Any) -> dict[str, list[int]]:
    if not isinstance(value, Mapping):
        raise PolicyViolation("analysis segment event date range is invalid")
    fixed: list[int] = []
    dynamic: list[int] = []
    mixed: list[int] = []
    quick_select = value.get("quick_select")
    if isinstance(quick_select, str) and quick_select:
        dynamic = list(_segment_quick_offsets(quick_select))
    elif value.get("date_type") == "static":
        raw_dates = value.get("date", ())
        if not isinstance(raw_dates, (list, tuple)) or len(raw_dates) != 2:
            raise PolicyViolation("analysis segment static date range is invalid")
        fixed = [_compact_date(item) for item in raw_dates]
    else:
        end_type = value.get("dynamic_end_type", "today")
        end_offset = 0 if end_type == "today" else -1
        if end_type == "dynamic":
            end_offset = -int(value.get("end_date_input", 0))
        if value.get("dynamic_start_type") == "static":
            mixed = [_compact_date(value.get("start_date")), end_offset]
        else:
            dynamic = [-int(value.get("start_date_input", 0)), end_offset]
    return {"fixed_date": fixed, "dynamic_date": dynamic, "mixed_date": mixed}


def _segment_quick_offsets(name: str) -> tuple[int, int]:
    fixed = {
        "yesterday": (-1, -1),
        "today": (0, 0),
        "last3day": (-3, -1),
        "recent3day": (-3, 0),
        "last7day": (-7, -1),
        "last14day": (-14, -1),
        "recent7day": (-7, 0),
        "last30day": (-30, -1),
        "recent30day": (-30, 0),
        "last90day": (-90, -1),
        "last120day": (-120, -1),
    }
    if name in fixed:
        return fixed[name]
    today = calendar_date.today()
    start_of_week = today - timedelta(days=today.weekday())
    if name == "week":
        return (-(today - start_of_week).days, 0)
    if name == "lastweek":
        previous_start = start_of_week - timedelta(days=7)
        return (-(today - previous_start).days, -(today - (start_of_week - timedelta(days=1))).days)
    start_of_month = today.replace(day=1)
    if name == "month":
        return (-(today - start_of_month).days, 0)
    if name == "lastmonth":
        previous_end = start_of_month - timedelta(days=1)
        previous_start = previous_end.replace(day=1)
        return (-(today - previous_start).days, -(today - previous_end).days)
    raise PolicyViolation("analysis segment quick date range is invalid")


def _compact_date(value: Any) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise PolicyViolation("analysis segment date is invalid")
    try:
        parsed = calendar_date.fromisoformat(value)
    except ValueError as exc:
        raise PolicyViolation("analysis segment date is invalid") from exc
    return int(parsed.strftime("%Y%m%d"))


def _frontend_segment_property_group(group: Any) -> dict[str, Any]:
    if not isinstance(group, Mapping):
        raise PolicyViolation("analysis segment property group is invalid")
    return {
        "cond_logic": group.get("cond_logic", "AND"),
        "conditions": [
            _frontend_segment_condition(item)
            for item in group.get("conditions", ())
        ],
    }


def _frontend_segment_condition(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise PolicyViolation("analysis segment condition is invalid")
    result: dict[str, Any] = {
        "filed_value": item.get("field"),
        "type": item.get("type"),
        "operator": item.get("operator"),
        "values": list(item.get("value", ())),
    }
    for key in (
        "dim_using_table_name",
        "segment_type",
        "version_id",
        "date_type",
        "date_unit",
        "date_relative_type",
        "date_relative_unit",
        "date_relative_left",
        "date_relative_right",
    ):
        if item.get(key) not in {None, ""}:
            result[key] = item[key]
    return result


def _frontend_segment_event_group(group: Any) -> dict[str, Any]:
    if not isinstance(group, Mapping):
        raise PolicyViolation("analysis segment event group is invalid")
    return {
        "cond_logic": group.get("cond_logic", "AND"),
        "conditions": [
            _frontend_segment_event(item)
            for item in group.get("conditions", ())
        ],
    }


def _frontend_segment_event(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise PolicyViolation("analysis segment event is invalid")
    target = item.get("target")
    did_condition = item.get("did_condition")
    date_range = item.get("date_range")
    if not all(isinstance(value, Mapping) for value in (target, did_condition, date_range)):
        raise PolicyViolation("analysis segment event is invalid")
    target_values = [target.get("field")]
    if target.get("name") != target.get("field"):
        target_values.append(target.get("name"))
    return {
        "eventValue": item.get("event_name"),
        "is_did": item.get("did"),
        "targetValue": target_values,
        "operator": did_condition.get("operator"),
        "values": list(did_condition.get("value", ())),
        "dateRangeInfo": {
            "resultDate": _segment_event_result_dates(date_range),
            "extra_data": _frontend_segment_date_range(date_range),
        },
        "cond_logic": item.get("cond_logic", "AND"),
        "filters": [
            _frontend_segment_condition(condition)
            for condition in item.get("conditions", ())
        ],
    }


def _frontend_segment_date_range(value: Mapping[str, Any]) -> dict[str, Any]:
    key_map = {
        "date_type": "dateType",
        "date": "date",
        "quick_select": "quickSelect",
        "start_date": "startDate",
        "dynamic_start_type": "dynamicStartType",
        "dynamic_end_type": "dynamicEndType",
        "start_date_input": "startDateInput",
        "end_date_input": "endDateInput",
    }
    result: dict[str, Any] = {}
    for source, target in key_map.items():
        item = value.get(source)
        if item is None or item == "":
            continue
        result[target] = list(item) if isinstance(item, tuple) else item
    return result


def _segment_event_result_dates(value: Mapping[str, Any]) -> list[str]:
    if value.get("date_type") == "static":
        raw = value.get("date", ())
        return list(raw) if isinstance(raw, (list, tuple)) else []
    if isinstance(value.get("quick_select"), str):
        start, end = _segment_quick_offsets(str(value["quick_select"]))
        today = calendar_date.today()
        return [
            (today + timedelta(days=start)).isoformat(),
            (today + timedelta(days=end)).isoformat(),
        ]
    end_type = value.get("dynamic_end_type", "today")
    today = calendar_date.today()
    end_offset = 0 if end_type == "today" else -1
    if end_type == "dynamic":
        end_offset = -int(value.get("end_date_input", 0))
    if value.get("dynamic_start_type") == "static":
        start = str(value.get("start_date"))
    else:
        start = (today - timedelta(days=int(value.get("start_date_input", 0)))).isoformat()
    return [start, (today + timedelta(days=end_offset)).isoformat()]


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


def _isolated_wire(
    query: Mapping[str, Any], body: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    isolated = json.loads(_canonical_wire_snapshot(query, body))
    return isolated["query"], isolated["body"]


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


def _canonical_wire_snapshot(
    query: Mapping[str, Any], body: Mapping[str, Any]
) -> str:
    try:
        return json.dumps(
            {"query": _plain_json(query), "body": _plain_json(body)},
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise PolicyViolation("request payload is not a canonical JSON value") from exc


def _plain_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_json(item) for item in value]
    return value


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
