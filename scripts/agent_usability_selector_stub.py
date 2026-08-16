"""Deterministic catalog-name selector used only to verify evaluator wiring."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from typing import Any, Mapping


def main() -> int:
    request = json.load(sys.stdin)
    request_sha256 = hashlib.sha256(json.dumps(
        request, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    capabilities = request.get("catalog", {}).get("capabilities", [])
    questions = request.get("questions", [])
    results = [
        _select(question, capabilities)
        for question in questions
        if isinstance(question, Mapping)
    ]
    json.dump({
        "schema_version": "gravity.agent-external-selector-response.v1",
        "results": results,
        "metadata": {
            "selector": "deterministic_catalog_name_stub.v1",
            "network_called": False,
            "meaningful_accuracy_evidence": False,
            "request_sha256": request_sha256,
            "stdin_encoding": sys.stdin.encoding,
        },
    }, sys.stdout, ensure_ascii=False, sort_keys=True)
    return 0


def _select(
    question: Mapping[str, Any], capabilities: list[Any]
) -> dict[str, Any]:
    query_words = _words(str(question.get("query", "")))
    selectors = []
    for capability in capabilities:
        if not isinstance(capability, Mapping) or capability.get("source") != "composite":
            continue
        name_words = _words(str(capability.get("name", "")))
        if name_words and name_words <= query_words:
            selectors.append(str(capability["selector"]))
    return {
        "id": str(question.get("id", "")),
        "selectors": selectors[:5],
        "reason": (
            "catalog name tokens matched"
            if selectors
            else "stub abstains unless every catalog name token is explicit"
        ),
    }


def _words(value: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", value.casefold().replace("_", " ")))


if __name__ == "__main__":
    raise SystemExit(main())
