"""Live host-model selector for the offline Agent usability evaluator.

The evaluator starts this file as a subprocess, writes one
``gravity.agent-external-selector-request.v1`` object to stdin, and expects
one ``gravity.agent-external-selector-response.v1`` object on stdout.

Call path: one OpenAI Responses request per trial, using GPT-6 Astra and
``OPENAI_API_KEY`` at the fixed official endpoint. The child never talks to
Gravity. Historical Claude trial receipts retain their original identity.

One batch call covers all questions. Use ``--selector-timeout 330`` to allow
three bounded 100s HTTP attempts plus backoff and subprocess overhead; actual
Astra latency must be measured on development cases. Questions share the
catalog prefix only. There is no cross-trial memory or local answer cache.

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


SELECTOR_VERSION = "openai/gpt-6-astra/low/host-selector.v2"
MODEL = "gpt-6-astra"
REASONING_EFFORT = "low"
API_URL = "https://api.openai.com/v1/responses"
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
    "type": "function",
    "name": TOOL_NAME,
    "description": "Submit catalog selectors for every anonymous question.",
    "strict": True,
    "parameters": {
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
        "reasoning": {"effort": REASONING_EFFORT},
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "instructions": SYSTEM_PROMPT,
        "store": False,
        "tools": [TOOL],
        "tool_choice": {"type": "function", "name": TOOL_NAME},
        "parallel_tool_calls": False,
        "input": [{
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
    token = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not token:
        raise SystemExit("host selector requires OPENAI_API_KEY")
    request = urllib.request.Request(
        API_URL,
        data=body,
        method="POST",
        headers={
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as error:
        # Provider bodies may echo input or credentials; report only the status.
        error.close()
        if error.code in {408, 409, 425, 429} or error.code >= 500:
            raise HostSelectorTransientError(f"HTTP {error.code}") from error
        raise SystemExit(f"host selector HTTP {error.code}") from error
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
    if (
        payload.get("status") != "completed"
        or payload.get("error") is not None
        or payload.get("incomplete_details") is not None
    ):
        raise SystemExit("host selector response did not complete successfully")
    blocks = payload.get("output")
    if not isinstance(blocks, list):
        raise SystemExit("host selector returned no output items")
    calls = []
    for block in blocks:
        if not isinstance(block, Mapping):
            raise SystemExit("host selector returned a malformed output item")
        if block.get("type") == "reasoning":
            continue
        if block.get("type") == "message":
            content = block.get("content")
            if not isinstance(content, list) or any(
                not isinstance(item, Mapping) or item.get("type") != "output_text"
                for item in content
            ):
                raise SystemExit("host selector returned a refusal or malformed message")
            continue
        if (
            block.get("type") != "function_call"
            or block.get("name") != TOOL_NAME
            or block.get("status") not in {None, "completed"}
        ):
            raise SystemExit("host selector returned an unexpected or incomplete tool call")
        calls.append(block)
    if len(calls) != 1:
        raise SystemExit(f"host selector must call {TOOL_NAME} exactly once")
    arguments = calls[0].get("arguments")
    if not isinstance(arguments, str):
        raise SystemExit("host selector tool arguments must be a JSON string")
    try:
        tool_input = json.loads(arguments)
    except json.JSONDecodeError as error:
        raise SystemExit("host selector tool arguments were not valid JSON") from error
    if not isinstance(tool_input, Mapping) or not isinstance(tool_input.get("results"), list):
        raise SystemExit("host selector tool arguments must contain results")
    return tool_input["results"]


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
