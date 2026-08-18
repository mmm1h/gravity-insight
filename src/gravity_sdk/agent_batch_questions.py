"""Validate the capabilities-many document accepted by ``gravity agent --input``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .actionable_error_values import actual_value
from .agent import DEFAULT_LIMIT
from .errors import InputValidationError


MAX_QUESTIONS = 32
_QUESTION_FIELDS = frozenset({"id", "query", "domain", "platform", "limit"})
_BATCH_SHAPE = (
    '{"questions":[{"id":"<stable-id>","query":"<text>","domain":"<optional>",'
    '"platform":"<optional>","limit":3}]} or a non-empty questions array of '
    "those objects or query strings"
)
_QUESTION_SHAPE = (
    '{"id":"<stable-id>","query":"<text>","domain":"<optional>",'
    '"platform":"<optional>","limit":3} or a non-empty query string'
)


@dataclass(frozen=True)
class CapabilityQuestion:
    question_id: str
    query: str
    domain: str | None
    platform: str | None
    limit: int


def _batch_input_error(
    message: str, *, field: str, next_action: str
) -> InputValidationError:
    return InputValidationError(message, field=field, next_action=next_action)


def validate_questions(
    questions: Mapping[str, Any] | Sequence[str | Mapping[str, Any]],
) -> tuple[CapabilityQuestion, ...]:
    value: Any = questions
    if isinstance(value, Mapping):
        unknown = sorted(set(value) - {"questions"})
        if unknown:
            raise _batch_input_error(
                f"actual value: {actual_value(unknown)}; allowed value: wrapper "
                "key questions only; pass a questions array, not a single "
                f"query object; legal shape: {_BATCH_SHAPE}",
                field="input",
                next_action=(
                    "Replace the document with "
                    '{"questions":[{"id":"q1","query":"<text>"}]} or a JSON '
                    "array of query strings, then retry `gravity agent --input`."
                ),
            )
        value = value.get("questions")
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _batch_input_error(
            f"actual value: {actual_value(type(questions).__name__)}; allowed "
            f"value: {_BATCH_SHAPE}",
            field="input",
            next_action=(
                "Pass {\"questions\":[...]} or a non-empty JSON array, then "
                "retry `gravity agent --input`."
            ),
        )
    if not value:
        raise _batch_input_error(
            f"actual value: {actual_value(value)}; allowed value: a non-empty "
            f"questions array; legal shape: {_BATCH_SHAPE}",
            field="input.questions",
            next_action="Add at least one question object or query string, then retry.",
        )
    if len(value) > MAX_QUESTIONS:
        raise _batch_input_error(
            f"actual value: {actual_value(len(value))}; allowed value: at most "
            f"{MAX_QUESTIONS} questions; legal shape: {_BATCH_SHAPE}",
            field="input.questions",
            next_action=(
                "Split the batch so each --input document has at most "
                f"{MAX_QUESTIONS} questions."
            ),
        )
    normalized = tuple(validate_question(item, index) for index, item in enumerate(value))
    identifiers = [item.question_id for item in normalized]
    if len(set(identifiers)) != len(identifiers):
        raise _batch_input_error(
            f"actual value: {actual_value(identifiers)}; allowed value: unique "
            f"non-empty question ids; legal shape: {_QUESTION_SHAPE}",
            field="input.questions[].id",
            next_action="Give each question a unique id, then retry.",
        )
    return normalized


def validate_question(value: Any, index: int) -> CapabilityQuestion:
    if isinstance(value, str):
        selected: Mapping[str, Any] = {"query": value}
    elif isinstance(value, Mapping):
        selected = value
    else:
        raise _batch_input_error(
            f"actual value: {actual_value(type(value).__name__)}; allowed "
            f"value: {_QUESTION_SHAPE}",
            field=f"input.questions[{index}]",
            next_action="Use a query string or a question object with a query field, then retry.",
        )
    unknown = sorted(set(selected) - _QUESTION_FIELDS)
    if unknown:
        raise _batch_input_error(
            f"actual value: {actual_value(unknown)}; allowed value: question "
            f"keys {sorted(_QUESTION_FIELDS)}; legal shape: {_QUESTION_SHAPE}",
            field=f"input.questions[{index}]",
            next_action=(
                "Keep only id, query, domain, platform, and limit on each "
                "question; wrap a single query as "
                '{"questions":[{"id":"q1","query":"<text>"}]}.'
            ),
        )
    query = selected.get("query")
    if not isinstance(query, str) or not query.strip():
        raise _batch_input_error(
            f"actual value: {actual_value(query)}; allowed value: a non-empty "
            f"query string; legal shape: {_QUESTION_SHAPE}",
            field=f"input.questions[{index}].query",
            next_action="Set query to the analyst question text, then retry.",
        )
    question_id = selected.get("id", f"question-{index + 1}")
    if not isinstance(question_id, str) or not question_id.strip():
        raise _batch_input_error(
            f"actual value: {actual_value(question_id)}; allowed value: a "
            f"non-empty string; legal shape: {_QUESTION_SHAPE}",
            field=f"input.questions[{index}].id",
            next_action="Set id to a unique non-empty string, then retry.",
        )
    domain = optional_text(selected.get("domain"), "domain", index)
    platform = optional_text(selected.get("platform"), "platform", index)
    limit = selected.get("limit", DEFAULT_LIMIT)
    if type(limit) is not int or not 1 <= limit <= 5:
        raise _batch_input_error(
            f"actual value: {actual_value(limit)}; allowed value: an integer "
            f"between 1 and 5; legal shape: {_QUESTION_SHAPE}",
            field=f"input.questions[{index}].limit",
            next_action="Set limit to an integer from 1 to 5, or omit it.",
        )
    return CapabilityQuestion(question_id, query.strip(), domain, platform, limit)


def optional_text(value: Any, field: str, index: int = 0) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _batch_input_error(
            f"actual value: {actual_value(value)}; allowed value: a non-empty "
            f"string; legal shape: {_QUESTION_SHAPE}",
            field=f"input.questions[{index}].{field}",
            next_action=f"Set {field} to a non-empty string, or omit it.",
        )
    return value


__all__ = [
    "CapabilityQuestion",
    "MAX_QUESTIONS",
    "optional_text",
    "validate_question",
    "validate_questions",
]
