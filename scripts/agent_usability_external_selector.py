"""External selector protocol for the offline Agent usability evaluator."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


REQUEST_SCHEMA = "gravity.agent-external-selector-request.v1"
RESPONSE_SCHEMA = "gravity.agent-external-selector-response.v1"


def external_selector_trials(
    cases: Sequence[Mapping[str, Any]],
    client: Any,
    trials: int,
    *,
    plugin_path: Path,
    timeout_seconds: float,
    route_score: Any,
    parameter_score: Any,
    terminal_score: Any,
) -> tuple[dict[str, Any], int, list[dict[str, Any]], dict[str, Any]]:
    """Run a selector process against one frozen local catalog and score its output."""

    catalog, inventory = _catalog(client)
    states = {
        str(case["case_id"]): {
            "selection": [], "parameter": [], "terminal": [], "reasons": []
        }
        for case in cases
    }
    observations: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for trial in range(trials):
        selected, metadata = _invoke_plugin(
            plugin_path,
            catalog,
            cases,
            timeout_seconds=timeout_seconds,
        )
        receipts.append(metadata)
        for case in cases:
            item = selected[str(case["case_id"])]
            result = _selection_result(case, item, inventory, client, metadata)
            if trial == 0:
                observations.append({"case_id": case["case_id"], "result": result})
            ok, reason, card = route_score(case, result)
            route_key = str(case["expected"]["route_key"])
            parameter, parameter_reason = (
                parameter_score(route_key, card)
                if case["expected"]["gap_code"] is None
                else (None, "gap_not_applicable")
            )
            terminal, terminal_reason = terminal_score(case, result)
            state = states[str(case["case_id"])]
            state["selection"].append(ok)
            state["parameter"].append(parameter)
            state["terminal"].append(terminal)
            state["reasons"].append((reason, parameter_reason, terminal_reason))
    return states, trials, observations, {
        "mode": "external_selector",
        "protocol": REQUEST_SCHEMA,
        "plugin_path": str(plugin_path),
        "plugin_sha256": hashlib.sha256(plugin_path.read_bytes()).hexdigest(),
        "catalog_capability_count": len(catalog["capabilities"]),
        "catalog_category_count": len(catalog["categories"]),
        "trial_receipts": receipts,
    }


def _catalog(client: Any) -> tuple[dict[str, Any], dict[str, Mapping[str, Any]]]:
    from gravity_sdk.agent_catalog import _categories, _inventory, _summary

    items = _inventory(client)
    return {
        "schema_version": "gravity.agent-external-selector-catalog.v1",
        "categories": _categories(items),
        "capabilities": [_summary(item) for item in items],
    }, {str(item["selector"]): item for item in items}


def _invoke_plugin(
    plugin_path: Path,
    catalog: Mapping[str, Any],
    cases: Sequence[Mapping[str, Any]],
    *,
    timeout_seconds: float,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if not plugin_path.is_file():
        raise ValueError("--selector-plugin must name one readable Python file")
    request = {
        "schema_version": REQUEST_SCHEMA,
        "catalog": catalog,
        "questions": [
            {"id": str(case["case_id"]), "query": str(case["prompt"])}
            for case in cases
        ],
    }
    try:
        completed = subprocess.run(
            [sys.executable, str(plugin_path)],
            input=json.dumps(request, ensure_ascii=False, sort_keys=True),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError(
            "external selector timed out; retry with a responsive plugin or raise "
            "--selector-timeout"
        ) from error
    if completed.returncode != 0:
        raise ValueError(
            "external selector failed; run the plugin directly and return one valid "
            f"{RESPONSE_SCHEMA} JSON object"
        )
    try:
        response = json.loads(completed.stdout)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(
            f"external selector must return one valid {RESPONSE_SCHEMA} JSON object"
        ) from error
    return _validate_response(response, request, catalog)


def _validate_response(
    response: Any,
    request: Mapping[str, Any],
    catalog: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if not isinstance(response, Mapping) or response.get("schema_version") != RESPONSE_SCHEMA:
        raise ValueError(f"external selector response must use {RESPONSE_SCHEMA}")
    rows = response.get("results")
    if not isinstance(rows, list):
        raise ValueError("external selector response results must be an array")
    expected_ids = [str(item["id"]) for item in request["questions"]]
    selectors = {
        str(item["selector"])
        for item in catalog["capabilities"]
        if isinstance(item, Mapping)
    }
    selected: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or set(row) - {"id", "selectors", "reason"}:
            raise ValueError(
                "external selector result rows allow only id, selectors, and reason"
            )
        question_id = str(row.get("id", ""))
        chosen = row.get("selectors")
        if question_id not in expected_ids or question_id in selected:
            raise ValueError("external selector result ids must match each question exactly once")
        if (
            not isinstance(chosen, list)
            or not all(isinstance(value, str) for value in chosen)
            or len(chosen) > 5
            or len(set(chosen)) != len(chosen)
        ):
            raise ValueError("external selector selectors must be a unique array of at most five strings")
        if set(chosen) - selectors:
            raise ValueError("external selector returned a selector outside the supplied catalog")
        selected[question_id] = {
            "selectors": list(chosen),
            "reason": str(row.get("reason", "")).strip(),
        }
    if set(selected) != set(expected_ids):
        raise ValueError("external selector must return exactly one result for every question")
    metadata = response.get("metadata", {})
    if not isinstance(metadata, Mapping):
        raise ValueError("external selector metadata must be an object")
    if not isinstance(metadata.get("selector"), str) or not str(
        metadata["selector"]
    ).strip():
        raise ValueError("external selector metadata.selector must name the selector version")
    if not isinstance(metadata.get("network_called"), bool):
        raise ValueError("external selector metadata.network_called must be boolean")
    return selected, copy.deepcopy(dict(metadata))


def _selection_result(
    case: Mapping[str, Any],
    selected: Mapping[str, Any],
    inventory: Mapping[str, Mapping[str, Any]],
    client: Any,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    selectors = list(selected["selectors"])
    query = str(case["prompt"])
    if len(selectors) > 1:
        from gravity_sdk.agent_intent_routing import product_selection_gap

        gaps = [product_selection_gap(
            query,
            selectors,
            reason="the external selector returned multiple registered products",
        )]
        candidates: list[dict[str, Any]] = []
    elif len(selectors) == 1:
        candidates = [_described_card(selectors[0], inventory, client, query)]
        gaps = []
    else:
        candidates = []
        gaps = [{
            "kind": "capability_gap",
            "code": "EXTERNAL_SELECTOR_ABSTAINED",
            "query": query,
            "reason": selected.get("reason") or "the external selector abstained",
            "next_action": (
                "Refine the question or inspect gravity agent-catalog categories; "
                "do not execute an unselected capability."
            ),
            "weak_matches": [],
        }]
    return {
        "schema_version": "gravity.agent-external-selector-result.v1",
        "ok": True,
        "status": "success" if candidates else "capability_gap",
        "offline": metadata.get("network_called") is not True,
        "network_called": metadata.get("network_called") is True,
        "candidates": candidates,
        "capability_gaps": gaps,
    }


def _described_card(
    selector: str,
    inventory: Mapping[str, Mapping[str, Any]],
    client: Any,
    query: str,
) -> dict[str, Any]:
    from gravity_sdk.agent_capabilities import composite_capability_cards
    from gravity_sdk.agent_handoff import attach_plan_node
    from gravity_sdk.agent_sources import describe_operation_cards

    item = inventory[selector]
    if item["source"] == "composite":
        cards = composite_capability_cards(
            selector, domain=None, platform=None
        )
        card = next(value for value in cards if value.get("selector") == selector)
    else:
        card = describe_operation_cards(client, [item["operation"]])[0]
    card = copy.deepcopy(dict(card))
    card["match"] = {
        "confidence": "external_selector",
        "coverage": None,
        "matched_terms": [],
        "missing_terms": [],
        "exact_selector": False,
    }
    return attach_plan_node(card, query)


__all__ = [
    "REQUEST_SCHEMA",
    "RESPONSE_SCHEMA",
    "external_selector_trials",
]
