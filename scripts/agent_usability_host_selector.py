"""Live host-model selector for the offline Agent usability evaluator.

The evaluator starts this file as a subprocess, writes one
``gravity.agent-external-selector-request.v1`` object to stdin, and expects
one ``gravity.agent-external-selector-response.v1`` object on stdout.

Call path: one Anthropic Messages request per trial against the already
configured Anthropic-compatible gateway (``ANTHROPIC_BASE_URL`` +
``ANTHROPIC_AUTH_TOKEN``). The child never talks to Gravity.

One batch call, not one call per question, so a 240-question holdout trial
fits inside ``--selector-timeout`` (default 120s; last clean arm was ~87s).
Questions share the catalog prefix only. There is no cross-trial memory and
no local answer cache.

Failure policy: missing credentials, exhausted retries, malformed model
output, missing ids, or selectors outside the supplied catalog fail the
whole trial with a non-zero exit. Silent empty rows would understate an
irreversible holdout score.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Mapping


SELECTOR_VERSION = "anthropic-compatible/claude-sonnet-4-6/host-selector.v1"
MODEL = "claude-sonnet-4-6"
ANTHROPIC_VERSION = "2023-06-01"
MAX_OUTPUT_TOKENS = 24_000
HTTP_TIMEOUT_SECONDS = 100
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (2.0, 5.0)
TOOL_NAME = "submit_catalog_selections"
RESPONSE_SCHEMA = "gravity.agent-external-selector-response.v1"
SYSTEM_PROMPT = (
    "You are the only semantic selector in a blinded routing evaluation. "
    "Use only catalog and questions from the user request. You have no "
    "repository, memory, tools besides submit_catalog_selections, expected "
    "answers, route constants, or case identities. Return one result for "
    "every anonymous question id. Choose only exact selector strings from "
    "catalog.capabilities. Prefer a product identity over a raw operation "
    "when the product covers the request. Choose an exact registered gap "
    "only when its catalog description matches an unavailable requested "
    "capability. Use an empty selector array only when no supplied product, "
    "operation, or gap matches. Return multiple selectors only for genuinely "
    "independent multi-intent questions. Do not infer hidden labels or "
    "revise earlier choices based on later questions. Set reason to an "
    "empty string for every row."
)
TOOL = {
    "name": TOOL_NAME,
    "description": "Submit catalog selectors for every anonymous question.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["results"],
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "selectors", "reason"],
                    "properties": {
                        "id": {"type": "string", "minLength": 1},
                        "selectors": {
                            "type": "array",
                            "maxItems": 5,
                            "items": {"type": "string", "minLength": 1},
                        },
                        "reason": {"type": "string"},
                    },
                },
            }
        },
    },
}


def main() -> int:
    request = json.load(sys.stdin)
    request_sha256 = _request_sha256(request)
    questions = request.get("questions")
    catalog = request.get("catalog")
    if not isinstance(questions, list) or not isinstance(catalog, Mapping):
        raise SystemExit("host selector request must include catalog and questions")
    expected_ids = _question_ids(questions)
    allowed = _allowed_selectors(catalog)
    rows = _complete(request)
    results = _normalize_results(rows, expected_ids, allowed)
    json.dump(
        {
            "schema_version": RESPONSE_SCHEMA,
            "results": results,
            "metadata": {
                "selector": SELECTOR_VERSION,
                "network_called": True,
                "meaningful_accuracy_evidence": True,
                "request_sha256": request_sha256,
                "stdin_encoding": sys.stdin.encoding,
            },
        },
        sys.stdout,
        ensure_ascii=False,
        sort_keys=True,
    )
    return 0


def _request_sha256(request: Mapping[str, Any]) -> str:
    # Re-canonicalize then encode UTF-8. This is the Windows GBK-surrogate
    # failure point the fixed stub covers; a successful hash proves stdin
    # decoded as UTF-8 and the payload is UTF-8-encodable.
    return hashlib.sha256(
        json.dumps(
            request, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def _question_ids(questions: list[Any]) -> list[str]:
    ids: list[str] = []
    for item in questions:
        if not isinstance(item, Mapping) or not str(item.get("id", "")).strip():
            raise SystemExit("host selector questions must each have an id")
        ids.append(str(item["id"]))
    if not ids or len(set(ids)) != len(ids):
        raise SystemExit("host selector questions must have unique ids")
    return ids


def _allowed_selectors(catalog: Mapping[str, Any]) -> frozenset[str]:
    capabilities = catalog.get("capabilities")
    if not isinstance(capabilities, list):
        raise SystemExit("host selector catalog.capabilities must be an array")
    selectors = [
        str(item["selector"])
        for item in capabilities
        if isinstance(item, Mapping) and item.get("selector")
    ]
    if not selectors:
        raise SystemExit("host selector catalog has no selectors")
    return frozenset(selectors)


def _complete(request: Mapping[str, Any]) -> list[Any]:
    body = json.dumps({
        "model": MODEL,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "temperature": 0,
        "system": SYSTEM_PROMPT,
        "tools": [TOOL],
        "tool_choice": {"type": "tool", "name": TOOL_NAME},
        "messages": [{
            "role": "user",
            "content": (
                "Return one submit_catalog_selections tool call covering every "
                "question id exactly once. Request JSON:\n"
                + json.dumps(
                    request, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"),
                )
            ),
        }],
    }).encode("utf-8")
    last_error = "no attempt"
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return _parse_tool_results(_post(body))
        except HostSelectorTransientError as error:
            last_error = str(error)
            if attempt == RETRY_ATTEMPTS:
                break
            time.sleep(RETRY_BACKOFF_SECONDS[attempt - 1])
    raise SystemExit(
        f"host selector failed after {RETRY_ATTEMPTS} attempts: {last_error}"
    )


def _post(body: bytes) -> Mapping[str, Any]:
    base = (os.environ.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN") or ""
    if not base or not token:
        raise SystemExit(
            "host selector requires ANTHROPIC_BASE_URL and ANTHROPIC_AUTH_TOKEN"
        )
    request = urllib.request.Request(
        f"{base}/v1/messages",
        data=body,
        method="POST",
        headers={
            "content-type": "application/json",
            "x-api-key": token,
            "anthropic-version": ANTHROPIC_VERSION,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:400]
        if error.code in {408, 409, 425, 429} or error.code >= 500:
            raise HostSelectorTransientError(f"HTTP {error.code}: {detail}") from error
        raise SystemExit(f"host selector HTTP {error.code}: {detail}") from error
    except urllib.error.URLError as error:
        raise HostSelectorTransientError(f"transport: {error.reason}") from error
    except TimeoutError as error:
        raise HostSelectorTransientError("socket timeout") from error
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise SystemExit("host selector response was not UTF-8 JSON") from error
    if not isinstance(payload, Mapping):
        raise SystemExit("host selector response must be a JSON object")
    return payload


def _parse_tool_results(payload: Mapping[str, Any]) -> list[Any]:
    stop = payload.get("stop_reason")
    if stop not in {"tool_use", "end_turn"}:
        raise SystemExit(f"host selector stopped with {stop!r}")
    blocks = payload.get("content")
    if not isinstance(blocks, list):
        raise SystemExit("host selector returned no content blocks")
    for block in blocks:
        if not isinstance(block, Mapping) or block.get("type") != "tool_use":
            continue
        if block.get("name") != TOOL_NAME:
            continue
        tool_input = block.get("input")
        if not isinstance(tool_input, Mapping):
            break
        rows = tool_input.get("results")
        if isinstance(rows, list):
            return rows
    raise SystemExit(f"host selector did not call {TOOL_NAME} with results")


def _normalize_results(
    rows: list[Any], expected_ids: list[str], allowed: frozenset[str]
) -> list[dict[str, str | list[str]]]:
    selected: dict[str, dict[str, str | list[str]]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise SystemExit("host selector result row must be an object")
        question_id = str(row.get("id", ""))
        chosen = row.get("selectors")
        if question_id not in expected_ids or question_id in selected:
            raise SystemExit(
                "host selector result ids must match each question exactly once"
            )
        if (
            not isinstance(chosen, list)
            or not all(isinstance(value, str) and value for value in chosen)
            or len(chosen) > 5
            or len(set(chosen)) != len(chosen)
        ):
            raise SystemExit(
                f"host selector question {question_id} returned a bad selector list"
            )
        unknown = [value for value in chosen if value not in allowed]
        if unknown:
            raise SystemExit(
                f"host selector question {question_id} returned unknown selectors: "
                + ", ".join(unknown)
            )
        selected[question_id] = {
            "id": question_id,
            "selectors": list(chosen),
            "reason": str(row.get("reason", "")).strip(),
        }
    if set(selected) != set(expected_ids):
        missing = [item for item in expected_ids if item not in selected]
        raise SystemExit(
            "host selector missing results for: " + ", ".join(missing[:8])
        )
    return [selected[item] for item in expected_ids]


class HostSelectorTransientError(Exception):
    """Retryable transport or provider failure for one trial."""


if __name__ == "__main__":
    raise SystemExit(main())
