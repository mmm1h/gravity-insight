"""One-snapshot, ordered capability discovery for multiple Agent questions."""

from __future__ import annotations

import copy
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import re
import threading
from typing import Any

from .agent import DEFAULT_LIMIT, discover_capabilities
from .agent_batch_sources import AgentSourceSnapshot, snapshot_agent_sources
from .agent_handoff import resolve_workspace_path, workspace_prefix
from .errors import ErrorCategory, ErrorDetail, exit_code_for_error


SCHEMA_VERSION = "gravity.agent-batch.v1"
NDJSON_RECORD_SCHEMA_VERSION = "gravity.agent-question.v1"
NDJSON_SUMMARY_SCHEMA_VERSION = "gravity.agent-batch-summary.v1"
MAX_QUESTIONS = 32
_QUESTION_FIELDS = frozenset({"id", "query", "domain", "platform", "limit"})
_ANALYSIS_BATCH_SCHEMA_VERSION = "gravity.analysis-query-batch.v1"
_SAFE_QUERY_ID = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


@dataclass(frozen=True)
class CapabilityQuestion:
    question_id: str
    query: str
    domain: str | None
    platform: str | None
    limit: int


class _SnapshotClient:
    """Expose cached inventory search while retaining governed describe calls."""

    def __init__(self, client: Any, sources: AgentSourceSnapshot) -> None:
        self._client = client
        self._sources = sources
        self._descriptions: dict[str, Mapping[str, Any]] = {}
        self._description_lock = threading.Lock()

    def describe(self, operation_id: str) -> Mapping[str, Any]:
        if operation_id not in self._descriptions:
            with self._description_lock:
                if operation_id not in self._descriptions:
                    self._descriptions[operation_id] = self._client.describe(operation_id)
        return self._descriptions[operation_id]

    def search_operations(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        del args
        domain = kwargs.get("domain")
        platform = kwargs.get("platform")
        stability = kwargs.get("stability", "stable")
        inventory = [
            dict(item)
            for item in self._sources.operation_inventory
            if (domain is None or item.get("domain") == domain)
            and (platform is None or item.get("platform") == platform)
            and (stability is None or item.get("stability") == stability)
        ]
        return {
            "schema_version": "gravity-insight.operation-search.v1",
            "operations": inventory,
            "continuation_token": None,
        }


def capabilities_many(
    questions: Mapping[str, Any] | Sequence[str | Mapping[str, Any]],
    *,
    client: Any,
    workspace: Any | None = None,
) -> dict[str, Any]:
    """Discover many questions from one bound workspace and operation inventory."""

    pending = validate_questions(questions)
    try:
        sources = snapshot_agent_sources(
            client,
            workspace=workspace,
            questions=pending,
        )
    except Exception:
        return snapshot_failure(pending)
    cached_client = _SnapshotClient(client, sources)
    results = [
        compact_analysis_schema(discover_one(item, cached_client, sources))
        for item in pending
    ]
    failures = [item for item in results if item["ok"] is not True]
    successes = len(results) - len(failures)
    gaps = sum(item["status"] == "capability_gap" for item in results)
    response = {
        "schema_version": SCHEMA_VERSION,
        "ok": not failures,
        "status": "success" if not failures else "partial" if successes else "error",
        "question_count": len(results),
        "success_count": successes,
        "capability_gap_count": gaps,
        "failure_count": len(failures),
        "exit_code": max((int(item["exit_code"]) for item in failures), default=0),
        "results": results,
    }
    handoff = analysis_query_batch_handoff(results, sources.workspace)
    if handoff is not None:
        response["analysis_query_batch"] = handoff
    return response


def capabilities_many_for_sdk(
    sdk: Any,
    questions: Mapping[str, Any] | Sequence[str | Mapping[str, Any]],
    *,
    workspace: Any | None = None,
) -> dict[str, Any]:
    """Thin SDK hook preserving the facade's immutable workspace selection."""

    selected_workspace = sdk.workspace if workspace is None else workspace
    return capabilities_many(
        questions,
        client=sdk.insight,
        workspace=selected_workspace,
    )


def iter_ndjson_records(value: Mapping[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield one bounded question per row plus a terminal summary.

    This is the CLI-independent integration hook for true batch NDJSON.  The
    shared CLI renderer can adopt it without teaching discovery about stdout.
    """

    if value.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("agent batch NDJSON requires a gravity.agent-batch.v1 result")
    results = value.get("results", [])
    if not isinstance(results, list):
        raise ValueError("agent batch NDJSON results must be an array")
    for item in results:
        if not isinstance(item, Mapping):
            raise ValueError("agent batch NDJSON result items must be objects")
        yield {"schema_version": NDJSON_RECORD_SCHEMA_VERSION, **dict(item)}
    summary = {
        key: item
        for key, item in value.items()
        if key not in {"results", "schema_version"}
    }
    yield {
        "_gravity_agent_batch": {
            "schema_version": NDJSON_SUMMARY_SCHEMA_VERSION,
            "payload_schema_version": SCHEMA_VERSION,
            "rows_written": len(results),
            **summary,
        }
    }


def validate_questions(
    questions: Mapping[str, Any] | Sequence[str | Mapping[str, Any]],
) -> tuple[CapabilityQuestion, ...]:
    value: Any = questions
    if isinstance(value, Mapping):
        unknown = sorted(set(value) - {"questions"})
        if unknown:
            raise ValueError("capabilities_many wrapper contains an unknown field")
        value = value.get("questions")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError("capabilities_many requires a questions array")
    if not value:
        raise ValueError("capabilities_many questions must not be empty")
    if len(value) > MAX_QUESTIONS:
        raise ValueError(f"capabilities_many supports at most {MAX_QUESTIONS} questions")
    normalized = tuple(validate_question(item, index) for index, item in enumerate(value))
    identifiers = [item.question_id for item in normalized]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("capabilities_many question ids must be unique")
    return normalized


def validate_question(value: Any, index: int) -> CapabilityQuestion:
    if isinstance(value, str):
        selected: Mapping[str, Any] = {"query": value}
    elif isinstance(value, Mapping):
        selected = value
    else:
        raise ValueError("capabilities_many questions must be strings or objects")
    if set(selected) - _QUESTION_FIELDS:
        raise ValueError("capabilities_many question contains an unknown field")
    query = selected.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("capabilities_many query must be a non-empty string")
    question_id = selected.get("id", f"question-{index + 1}")
    if not isinstance(question_id, str) or not question_id.strip():
        raise ValueError("capabilities_many id must be a non-empty string")
    domain = optional_text(selected.get("domain"), "domain")
    platform = optional_text(selected.get("platform"), "platform")
    limit = selected.get("limit", DEFAULT_LIMIT)
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError("capabilities_many limit must be between 1 and 5")
    return CapabilityQuestion(question_id, query.strip(), domain, platform, limit)


def optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"capabilities_many {field} must be a non-empty string")
    return value


def snapshot_failure(
    questions: tuple[CapabilityQuestion, ...]
) -> dict[str, Any]:
    detail = ErrorDetail.create(
        "AGENT_SOURCE_SNAPSHOT_FAILED",
        "Capability source snapshot failed locally.",
        category=ErrorCategory.LOCAL,
        next_action="Check the local workspace and operation catalog, then retry.",
    )
    exit_code = exit_code_for_error(detail)
    results = [
        {
            "question_id": item.question_id,
            "ok": False,
            "status": "error",
            "exit_code": exit_code,
            "result": None,
            "error": detail.to_dict(),
        }
        for item in questions
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": False,
        "status": "error",
        "question_count": len(results),
        "success_count": 0,
        "capability_gap_count": 0,
        "failure_count": len(results),
        "exit_code": exit_code,
        "results": results,
    }


def discover_one(
    item: CapabilityQuestion,
    client: _SnapshotClient,
    sources: AgentSourceSnapshot,
) -> dict[str, Any]:
    try:
        result = discover_capabilities(
            item.query,
            client=client,
            workspace=sources.workspace,
            domain=item.domain,
            platform=item.platform,
            limit=item.limit,
            sources=sources,
            plan_node_namespace=item.question_id,
        )
        return {
            "question_id": item.question_id,
            "ok": True,
            "status": str(result.get("status", "success")),
            "exit_code": 0,
            "result": result,
            "error": None,
        }
    except Exception:
        detail = ErrorDetail.create(
            "AGENT_DISCOVERY_FAILED",
            "Capability discovery failed locally.",
            category=ErrorCategory.LOCAL,
            next_action="Retry this question alone after checking the local catalog.",
        )
        return {
            "question_id": item.question_id,
            "ok": False,
            "status": "error",
            "exit_code": exit_code_for_error(detail),
            "result": None,
            "error": detail.to_dict(),
        }


def compact_analysis_schema(item: Mapping[str, Any]) -> dict[str, Any]:
    """Remove repeated Analysis schema bodies from one batch-only result."""

    selected = dict(item)
    raw_result = selected.get("result")
    if not isinstance(raw_result, Mapping):
        return selected
    result = dict(raw_result)
    selected["result"] = result
    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        return selected
    result["candidates"] = [
        _compact_analysis_card(card) if isinstance(card, Mapping) else card
        for card in candidates
    ]
    return selected


def analysis_query_batch_handoff(
    results: Sequence[Mapping[str, Any]], workspace: Any | None
) -> dict[str, Any] | None:
    """Build one fillable batch document from kind-specific compiler cards."""

    queries: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, item in enumerate(results):
        card = _analysis_card(item)
        if card is None:
            continue
        template = card.get("input_template")
        values = template if isinstance(template, Mapping) else {}
        kind = card.get("analysis_kind") or values.get("kind") or "<kind>"
        queries.append(
            {
                "id": _safe_query_id(str(item.get("question_id", "")), index, used),
                "kind": kind,
                "app": values.get("app", "<workspace-app-alias-or-positive-id>"),
                "spec": copy.deepcopy(
                    values.get(
                        "spec", "<gravity-insight.analysis-query-spec.v1 object>"
                    )
                ),
                "limits": {"max_items": 200},
            }
        )
    if not queries:
        return None
    return {
        "schema_version": _ANALYSIS_BATCH_SCHEMA_VERSION,
        "natural_language_auto_execute": False,
        "command": [
            *workspace_prefix(resolve_workspace_path(workspace)),
            "analysis",
            "query",
            "batch",
            "--input",
            "<queries.json>",
            "--concurrency",
            "6",
        ],
        "queries": queries,
    }


def _compact_analysis_card(card: Mapping[str, Any]) -> dict[str, Any]:
    if card.get("kind") != "analysis_query_spec":
        return dict(card)
    selected = {
        key: copy.deepcopy(value)
        for key, value in card.items()
        if key != "input_schema"
    }
    raw_schema = card.get("input_schema")
    schema = (
        {
            key: copy.deepcopy(value)
            for key, value in raw_schema.items()
            if key != "spec"
        }
        if isinstance(raw_schema, Mapping)
        else {}
    )
    raw_spec = raw_schema.get("spec") if isinstance(raw_schema, Mapping) else None
    spec = dict(raw_spec) if isinstance(raw_spec, Mapping) else {}
    next_step = selected.get("next")
    next_values = next_step if isinstance(next_step, Mapping) else {}
    compact = {
        key: copy.deepcopy(value)
        for key, value in spec.items()
        if key not in {"definitions", "variants_by_kind"}
    }
    compact["contract_ref"] = {
        "schema_version": selected.get("spec_schema_version")
        or spec.get("schema_version"),
        "selected_kind": selected.get("analysis_kind"),
        "schema_argv": copy.deepcopy(next_values.get("schema_argv")),
    }
    schema["spec"] = compact
    selected["input_schema"] = schema
    return selected


def _analysis_card(item: Mapping[str, Any]) -> Mapping[str, Any] | None:
    result = item.get("result")
    candidates = result.get("candidates") if isinstance(result, Mapping) else None
    if not isinstance(candidates, Sequence):
        return None
    return next(
        (
            card
            for card in candidates
            if isinstance(card, Mapping) and card.get("kind") == "analysis_query_spec"
        ),
        None,
    )


def _safe_query_id(value: str, index: int, used: set[str]) -> str:
    selected = value.strip()
    if not _SAFE_QUERY_ID.fullmatch(selected):
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", selected).strip(".-")
        if not stem or not stem[0].isalpha():
            stem = f"question-{index + 1}"
        selected = stem[:64]
    base = selected
    salt = 0
    while selected in used:
        digest = hashlib.sha256(
            f"{value}\0{salt}".encode("utf-8")
        ).hexdigest()[:8]
        selected = f"{base[:55]}-{digest}"
        salt += 1
    used.add(selected)
    return selected


__all__ = [
    "capabilities_many",
    "capabilities_many_for_sdk",
    "iter_ndjson_records",
    "validate_questions",
]
