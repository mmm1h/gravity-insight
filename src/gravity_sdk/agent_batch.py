"""One-snapshot, ordered capability discovery for multiple Agent questions."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
import threading
from typing import Any

from .agent import DEFAULT_LIMIT, discover_capabilities
from .agent_batch_sources import AgentSourceSnapshot, snapshot_agent_sources
from .errors import ErrorCategory, ErrorDetail


SCHEMA_VERSION = "gravity.agent-batch.v1"
NDJSON_RECORD_SCHEMA_VERSION = "gravity.agent-question.v1"
NDJSON_SUMMARY_SCHEMA_VERSION = "gravity.agent-batch-summary.v1"
MAX_QUESTIONS = 32
_QUESTION_FIELDS = frozenset({"id", "query", "domain", "platform", "limit"})


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
    results = [discover_one(item, cached_client, sources) for item in pending]
    failures = [item for item in results if item["ok"] is not True]
    successes = len(results) - len(failures)
    gaps = sum(item["status"] == "capability_gap" for item in results)
    return {
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
    ).to_dict()
    results = [
        {
            "question_id": item.question_id,
            "ok": False,
            "status": "error",
            "exit_code": 4,
            "result": None,
            "error": detail,
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
        "exit_code": 4,
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
            "exit_code": 4,
            "result": None,
            "error": detail.to_dict(),
        }


__all__ = [
    "capabilities_many",
    "capabilities_many_for_sdk",
    "iter_ndjson_records",
    "validate_questions",
]
