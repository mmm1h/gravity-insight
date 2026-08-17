"""CLI registration and Plan adapter for governed Analysis template replay."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any, Callable

from . import runtime
from .agent_intent_text import affirmative_intent_text
from .dashboard_artifact import validate_dashboard_window
from .domains import ANALYSIS_QUERY_OPERATIONS
from .errors import (
    ContractChangedError,
    ErrorCode,
    ErrorDetail,
    InputValidationError,
    exit_code_for_error,
)
from .plan import AdapterContext
from .plan_adapter_support import (
    input_error,
    validate_exact_targets,
    validate_selected_fields,
)
from .saved_analysis_result import saved_result_item_count
from ._field_policy_operations import (
    ANALYSIS_EVENT,
    ANALYSIS_EVENT_INFO,
    ANALYSIS_EVENT_PROPERTY,
    ANALYSIS_SEGMENT,
    ANALYSIS_SEGMENT_HISTORY,
    ANALYSIS_USER_PROPERTY,
)
from .saved_analysis_support import RESULT_STATUSES, bounds, safe_query_envelope, workers
from .result_source import GOVERNED_PRODUCT, result_source
from .template_replay import (
    PREVIEW_SCHEMA_VERSION,
    REPLAY_SCHEMA_VERSION,
    list_analysis_templates,
    prepare_analysis_template,
    run_analysis_template,
)
from .workspace import load_workspace
from .actionable_error_values import actual_value


ANALYSIS_TEMPLATE_NAME = "analysis_template"
_SCOPES = ("own", "share", "internal")
_MODES = frozenset({"prepare", "run"})
ANALYSIS_TEMPLATE_CAPABILITY: Mapping[str, Any] = {
    "name": ANALYSIS_TEMPLATE_NAME,
    "domain": "analysis",
    "accepted_domains": ("analysis", "report"),
    "aliases": (
        "run analysis template by exact reference",
        "inspect chart template replay eligibility",
        "按精确引用运行分析模板",
        "检查图表模板回放能力",
    ),
    "description": (
        "列举并按 scope 与精确引用解析分析模板；只对 compact Analysis Spec v1 "
        "或已证明的 Dashboard Web artifact 执行，其他 config 逐字段隔离报告；"
        "用于 template scope + template reference，不接受保存分析 ID/名称。"
    ),
    "required_inputs": ("scope", "app", "ref", "start", "end"),
    "input_schema": {
        "scope": {"type": "string", "required": True, "enum": list(_SCOPES)},
        "app": {"type": "string|integer", "required": True, "nullable": False},
        "ref": {"type": "string|integer", "required": True, "nullable": False},
        "start": {"type": "string", "format": "date", "required": True},
        "end": {"type": "string", "format": "date", "required": True},
        "mode": {"type": "string", "enum": ["prepare", "run"], "default": "run"},
    },
}
OUTPUT_FIELDS = frozenset(
    {
        "artifact_mode", "components", "date_range", "items", "kind",
        "limitations", "operation_id", "quarantine", "result", "template",
        "validation",
    }
)
_REQUEST_FIELDS = frozenset({"name", "scope", "app", "ref", "mode", "start", "end"})
_TOP_FIELDS = frozenset(
    {
        "schema_version", "result_source", "ok", "status", "exit_code", "network_called",
        "definition_network_called", "query_executed", "template",
        "artifact_mode", "kind", "operation_id", "date_range",
        "date_override_applied", "limitations", "validation", "quarantine",
        "result", "next_action",
    }
)
_TEMPLATE_FIELDS = frozenset(
    {
        "scope", "id", "name", "template_type", "sub_type", "modify_time",
        "replay_supported", "app_id",
    }
)
_ARTIFACT_MODES = frozenset({"compact_spec", "web_artifact", "origin_params", "unknown"})
_KINDS = frozenset(ANALYSIS_QUERY_OPERATIONS)
_OPERATIONS = frozenset(ANALYSIS_QUERY_OPERATIONS.values())
_LIMITATIONS = frozenset(
    {
        "dashboard conditions are not applied by the stable event contract",
        "property analysis has no date window in its stable contract",
        "dashboard conditions are not applied",
        "dashboard conditions are not applied by the stable retention contract",
        "dashboard conditions are not applied by the stable funnel contract",
        "dashboard conditions are not applied by the stable scatter contract",
    }
)
_REASONS = frozenset(
    {
        "privacy_review_required", "structure_unknown",
        "unregistered_template_sub_type", "stable_validation_failed",
        "unregistered_or_invalid_analysis_semantics",
        "filter_shape_not_registered", "formula_token_semantics_unproven",
        "group_mapping_unproven", "time_group_mapping_unproven",
        "condition_combination_semantics_unproven",
        "split_event_mapping_unproven", "split_event_auxiliary_mapping_unproven",
        "period_compare_owned_by_separate_capability",
        "replaced_by_explicit_window_but_shape_not_forwarded",
        "metadata_only_not_query_semantics", "structure_not_proven_executable",
    }
)


class TemplateSdkMixin:
    """Thin SDK facade methods for Analysis template catalogs and replay."""

    def analysis_templates(
        self, *, scope: str | None = None, max_pages: int = 1_000,
        max_items: int = 100_000, max_workers: int = 6,
    ) -> dict[str, Any]:
        bounds(max_pages, max_items)
        workers(max_workers)
        return list_analysis_templates(
            self.insight, scope=scope, max_pages=max_pages,
            max_items=max_items, max_workers=max_workers,
        )

    def prepare_analysis_template(
        self, app: str | int | None, reference: str | int | Mapping[str, Any],
        *, scope: str, start: str, end: str, max_pages: int = 1_000,
        max_items: int = 100_000, max_workers: int = 6,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        return self._template_replay(
            prepare_analysis_template, app, reference, scope, start, end,
            max_pages, max_items, max_workers, workspace,
        )

    def run_analysis_template(
        self, app: str | int | None, reference: str | int | Mapping[str, Any],
        *, scope: str, start: str, end: str, max_pages: int = 1_000,
        max_items: int = 100_000, max_workers: int = 6,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        return self._template_replay(
            run_analysis_template, app, reference, scope, start, end,
            max_pages, max_items, max_workers, workspace,
        )

    def _template_replay(
        self, function: Any, app: Any, reference: Any, scope: str,
        start: str, end: str, max_pages: int, max_items: int,
        max_workers: int, workspace: Any,
    ) -> dict[str, Any]:
        validate_dashboard_window(start, end)
        bounds(max_pages, max_items)
        workers(max_workers)
        selected = self._select_workspace(workspace)
        app_id = self._resolve_app(selected, app)
        return function(
            self.insight, scope=scope, reference=reference, app=app_id,
            start=start, end=end, workspace=selected, max_pages=max_pages,
            max_items=max_items, max_workers=max_workers,
        )


def add_template_commands(
    analysis_commands: Any,
    positive_int: Callable[[str], int],
) -> None:
    template = analysis_commands.add_parser(
        "template", help="List, inspect, or strictly replay Analysis templates."
    )
    commands = template.add_subparsers(dest="template_command", required=True)
    listing = commands.add_parser("list", help="List safe template identities.")
    listing.add_argument("--scope", choices=_SCOPES)
    for name in ("prepare", "run"):
        parser = commands.add_parser(name)
        parser.add_argument("--scope", required=True, choices=_SCOPES)
        parser.add_argument("--app", required=True)
        parser.add_argument("--ref", required=True)
        parser.add_argument("--start", required=True)
        parser.add_argument("--end", required=True)
    for parser in commands.choices.values():
        parser.add_argument("--max-pages", type=positive_int, default=1_000)
        parser.add_argument("--max-items", type=positive_int, default=100_000)
        parser.add_argument("--concurrency", type=positive_int, default=6)
        parser.add_argument("--output")
        parser.add_argument("--format", choices=("json", "ndjson"), default="json")
        parser.set_defaults(_gravity_handler=dispatch_template)


def dispatch_template(args: Any, _object_input: Any = None) -> dict[str, Any]:
    pages, items = bounds(args.max_pages, args.max_items)
    page_workers = workers(args.concurrency)
    if args.template_command == "list":
        return list_analysis_templates(
            runtime.build_client(), scope=args.scope, max_pages=pages,
            max_items=items, max_workers=page_workers,
        )
    validate_dashboard_window(args.start, args.end)
    workspace = load_workspace()
    options = {
        "scope": args.scope,
        "reference": args.ref,
        "app": args.app,
        "start": args.start,
        "end": args.end,
        "workspace": workspace,
        "max_pages": pages,
        "max_items": items,
        "max_workers": page_workers,
    }
    function = (
        prepare_analysis_template
        if args.template_command == "prepare"
        else run_analysis_template
    )
    return function(runtime.build_client(), **options)


def validate_template_plan(
    request: Mapping[str, Any], context: AdapterContext, workspace: Any
) -> None:
    if set(request) - _REQUEST_FIELDS:
        raise input_error("analysis_template request contains unknown fields", "request")
    if request.get("name") != ANALYSIS_TEMPLATE_NAME:
        raise input_error("analysis_template name is invalid", "name")
    validate_exact_targets(context, frozenset({"/app"}))
    if "/app" not in context.dynamic_targets:
        try:
            workspace.resolve_app(request.get("app"))
        except (KeyError, TypeError, ValueError):
            raise input_error("analysis_template app is invalid", "app") from None
    if request.get("scope") not in _SCOPES:
        raise input_error("analysis_template scope is invalid", "scope")
    _validate_reference(request.get("ref"))
    if request.get("mode", "run") not in _MODES:
        raise input_error(f"actual value: {actual_value(request)}; " + ("analysis_template mode must be prepare or run"), "mode")
    _validate_window(request.get("start"), request.get("end"))
    validate_selected_fields(context.output_fields, OUTPUT_FIELDS, "output_fields")


def execute_template_plan(
    sdk: Any, request: Mapping[str, Any], context: AdapterContext
) -> dict[str, Any]:
    options = {
        "scope": request.get("scope"),
        "start": request.get("start"),
        "end": request.get("end"),
        "workspace": context.workspace,
        "max_pages": context.max_pages,
        "max_items": context.max_items,
        "max_workers": 1,
    }
    method = (
        sdk.prepare_analysis_template
        if request.get("mode", "run") == "prepare"
        else sdk.run_analysis_template
    )
    value = method(request.get("app"), request.get("ref"), **options)
    safe = safe_template_result(value)
    if not _matches_request(safe, request, context):
        return _contract_failure()
    result = safe.get("result")
    operation_id = safe.get("operation_id")
    if (
        safe.get("ok") is True
        and isinstance(operation_id, str)
        and saved_result_item_count(operation_id, result) > context.max_items
    ):
        raise input_error("analysis_template result exceeds max_items", "limits.max_items")
    return safe


def safe_template_result(value: Any) -> dict[str, Any]:
    if not _valid_top(value):
        return _contract_failure()
    template = _safe_template(value.get("template"))
    date_range = _safe_date_range(value.get("date_range"))
    limitations = _safe_limitations(value.get("limitations"))
    validation = _safe_validation(value.get("validation"))
    quarantine = _safe_quarantine(value.get("quarantine"))
    if None in (template, date_range, limitations, quarantine):
        return _contract_failure()
    if not _valid_state(value, validation, quarantine):
        return _contract_failure()
    selected = {
        "schema_version": value["schema_version"],
        "result_source": result_source(GOVERNED_PRODUCT), "ok": value["ok"],
        "status": value["status"], "exit_code": value["exit_code"],
        "network_called": True, "definition_network_called": True,
        "query_executed": value["query_executed"], "template": template,
        "artifact_mode": value["artifact_mode"], "kind": value["kind"],
        "operation_id": value["operation_id"], "date_range": date_range,
        "date_override_applied": value["date_override_applied"],
        "limitations": limitations, "validation": validation,
        "quarantine": quarantine,
        "next_action": (
            "Consume the governed Analysis result."
            if value["query_executed"] and value["ok"] else
            "Keep the template non-executable until every quarantine reason is proven."
            if quarantine else "Run this template through governed replay."
        ),
    }
    if "result" in value:
        try:
            selected["result"] = safe_query_envelope(value["result"])
        except (ContractChangedError, InputValidationError, RuntimeError):
            return _contract_failure()
    return selected


def _valid_top(value: Any) -> bool:
    return isinstance(value, Mapping) and not set(value) - _TOP_FIELDS


def _valid_state(value: Mapping[str, Any], validation: Any, quarantine: list[Any]) -> bool:
    schema, status = value.get("schema_version"), value.get("status")
    if not _valid_state_fields(value):
        return False
    if schema == PREVIEW_SCHEMA_VERSION:
        return status in {"compiled", "capability_gap"} and not value["query_executed"]
    if value["query_executed"]:
        return status in RESULT_STATUSES and not quarantine and validation is not None
    return status == "capability_gap" and value.get("ok") is False and bool(quarantine)


def _valid_state_fields(value: Mapping[str, Any]) -> bool:
    typed = (
        ("ok", bool), ("exit_code", int), ("query_executed", bool),
        ("date_override_applied", bool),
    )
    return (
        all(type(value.get(field)) is expected for field, expected in typed)
        and 0 <= value["exit_code"] <= 4
        and value.get("network_called") is True
        and value.get("definition_network_called") is True
        and value.get("artifact_mode") in _ARTIFACT_MODES
        and value.get("kind") in (_KINDS | {None})
        and value.get("operation_id") in (_OPERATIONS | {None})
    )


def _safe_template(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != _TEMPLATE_FIELDS:
        return None
    if (
        value.get("scope") not in _SCOPES
        or not all(isinstance(value.get(key), str) and value[key] for key in ("id", "name", "app_id"))
        or type(value.get("replay_supported")) is not bool
        or any(value.get(key) is not None and not isinstance(value[key], str)
               for key in ("template_type", "sub_type", "modify_time"))
    ):
        return None
    return {key: copy.deepcopy(value[key]) for key in _TEMPLATE_FIELDS}


def _safe_date_range(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or set(value) != {"start", "end", "inclusive"}:
        return None
    if value.get("inclusive") is not True:
        return None
    try:
        validate_dashboard_window(value.get("start"), value.get("end"))
    except InputValidationError:
        return None
    return {"start": value["start"], "end": value["end"], "inclusive": True}


def _safe_limitations(value: Any) -> list[str] | None:
    if not isinstance(value, list) or any(item not in _LIMITATIONS for item in value):
        return None
    return list(value)


def _safe_validation(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"status", "live_metadata_dependencies"}:
        return None
    dependencies = value.get("live_metadata_dependencies")
    allowed = {
        ANALYSIS_EVENT,
        ANALYSIS_EVENT_INFO,
        ANALYSIS_EVENT_PROPERTY,
        ANALYSIS_SEGMENT,
        ANALYSIS_SEGMENT_HISTORY,
        ANALYSIS_USER_PROPERTY,
    }
    if (
        value.get("status") not in {"valid_offline", "needs_live_metadata"}
        or not isinstance(dependencies, list)
        or any(item not in allowed for item in dependencies)
        or len(dependencies) != len(set(dependencies))
    ):
        return None
    return {
        "status": value["status"],
        "live_metadata_dependencies": list(dependencies),
    }


def is_template_result(value: Any) -> bool:
    return isinstance(value, Mapping) and value.get("schema_version") in {
        PREVIEW_SCHEMA_VERSION, REPLAY_SCHEMA_VERSION,
    }


def project_template_result(
    result: Any, fields: tuple[str, ...], _context: AdapterContext
) -> dict[str, Any]:
    safe = safe_template_result(result)
    if not fields:
        return safe
    structural = {
        "schema_version", "result_source", "ok", "status", "exit_code", "network_called",
        "definition_network_called", "query_executed", "next_action",
    }
    return {
        key: copy.deepcopy(item) for key, item in safe.items()
        if key in structural or key in fields
    }


def _matches_request(
    value: Mapping[str, Any], request: Mapping[str, Any], context: AdapterContext
) -> bool:
    template = value.get("template")
    date_range = value.get("date_range")
    if not isinstance(template, Mapping) or not isinstance(date_range, Mapping):
        return False
    try:
        app_id = str(context.workspace.resolve_app(request.get("app")))
    except (KeyError, TypeError, ValueError):
        return False
    reference = str(request.get("ref")).strip()
    expected_schema = (
        PREVIEW_SCHEMA_VERSION
        if request.get("mode", "run") == "prepare" else REPLAY_SCHEMA_VERSION
    )
    return (
        value.get("schema_version") == expected_schema
        and template.get("app_id") == app_id
        and template.get("scope") == request.get("scope")
        and reference in {str(template.get("id")), str(template.get("name"))}
        and date_range.get("start") == request.get("start")
        and date_range.get("end") == request.get("end")
    )


def _safe_quarantine(value: Any) -> list[dict[str, str]] | None:
    if not isinstance(value, list) or not all(
        isinstance(item, Mapping)
        and set(item) == {"field", "disposition", "reason"}
        and item.get("disposition") == "quarantined"
        and isinstance(item.get("field"), str)
        and item["field"].startswith("config")
        and item.get("reason") in _REASONS
        for item in value
    ):
        return None
    return [dict(item) for item in value]


def _contract_failure() -> dict[str, Any]:
    detail = ErrorDetail.create(
        ErrorCode.CONTRACT_CHANGED,
        "Analysis template result contract changed.",
    )
    return {
        "schema_version": REPLAY_SCHEMA_VERSION,
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": "contract_changed",
        "exit_code": exit_code_for_error(detail),
        "error": {
            "code": ErrorCode.CONTRACT_CHANGED.value,
            "category": "upstream",
            "message": "Analysis template result contract changed.",
        },
    }


def _validate_reference(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise input_error("analysis_template ref is invalid", "ref")
    if not str(value).strip() or len(str(value)) > 256:
        raise input_error("analysis_template ref is invalid", "ref")


def _validate_window(start: Any, end: Any) -> None:
    if not isinstance(start, str) or not isinstance(end, str):
        raise input_error(f"actual value: {actual_value(start)}; " + ("analysis_template requires start and end"), "start/end")
    try:
        validate_dashboard_window(start, end)
    except InputValidationError as exc:
        raise input_error(str(exc), "start/end") from None


def analysis_template_query(query: str) -> bool:
    selected = affirmative_intent_text(query)
    full = " ".join(query.strip().casefold().split())
    if selected in {ANALYSIS_TEMPLATE_NAME, f"composite:{ANALYSIS_TEMPLATE_NAME}"}:
        return True
    blocked = ("saved", "dashboard", "create", "update", "delete", "share",
               "subscribe", "layout", "permission", "保存", "看板", "创建",
               "修改", "删除", "分享", "订阅", "布局", "权限")
    actions = ("run", "replay", "prepare", "inspect", "understand", "execute",
               "运行", "重放", "准备", "检查", "理解", "执行")
    return (
        ("analysis template" in selected or "chart template" in selected
         or "分析模板" in selected or "图表模板" in selected
         or any(term in selected for term in ("运行模板", "重放模板"))
         and any(term in full for term in ("分析", "图表", "保存分析")))
        and any(action in selected for action in actions)
        and not any(term in selected for term in blocked)
    )


def analysis_template_plan_request(card: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": ANALYSIS_TEMPLATE_NAME,
        "scope": card.get("scope", "<own|share|internal>"),
        "app": card.get("app", "<workspace-app-alias-or-positive-id>"),
        "ref": card.get("ref", "<analysis-template-id-or-exact-name>"),
        "start": card.get("start", "<start:YYYY-MM-DD>"),
        "end": card.get("end", "<end:YYYY-MM-DD>"),
        "mode": card.get("mode", "run"),
    }


__all__ = [
    "ANALYSIS_TEMPLATE_CAPABILITY", "ANALYSIS_TEMPLATE_NAME", "OUTPUT_FIELDS",
    "add_template_commands", "analysis_template_plan_request",
    "analysis_template_query", "dispatch_template", "execute_template_plan",
    "is_template_result", "project_template_result", "safe_template_result",
    "TemplateSdkMixin", "validate_template_plan",
]
