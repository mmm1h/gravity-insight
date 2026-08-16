"""External selector protocol for the offline Agent usability evaluator."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
from typing import Any

from agent_usability_selector_measurements import canonical_request_text
from agent_usability_selector_measurements import self_report_measurements
from agent_usability_selector_measurements import validate_request_sha256
from agent_usability_selector_measurements import validate_selector_version_binding


REQUEST_SCHEMA = "gravity.agent-external-selector-request.v1"
RESPONSE_SCHEMA = "gravity.agent-external-selector-response.v1"
TERMINAL_OFFLINE_MEASUREMENT_REASON = (
    "selection-only harness does not execute products"
)
SELECTION_NETWORK_MEASUREMENT_REASON = (
    "network_called is plugin-reported because the external selector runs in "
    "an uninstrumented subprocess"
)


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
    production_http_requests: Callable[[], int],
) -> tuple[dict[str, Any], int, list[dict[str, Any]], dict[str, Any]]:
    """Run a selector process against one frozen local catalog and score its output."""

    if not plugin_path.is_file():
        raise ValueError("--selector-plugin must name one readable Python file")
    plugin_sha256 = hashlib.sha256(plugin_path.read_bytes()).hexdigest()
    catalog, inventory = _catalog(client)
    blind_questions, aliases, blind_receipt = _blind_questions(cases)
    states = {
        str(case["case_id"]): {
            "selection": [], "selected": [], "parameter": [], "terminal": [],
            "reasons": []
        }
        for case in cases
    }
    observations: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    for trial in range(trials):
        selected, metadata = _invoke_plugin(
            plugin_path,
            catalog,
            blind_questions,
            timeout_seconds=timeout_seconds,
        )
        selected = {
            str(case["case_id"]): selected[aliases[str(case["case_id"])]]
            for case in cases
        }
        receipts.append(metadata)
        for case in cases:
            item = selected[str(case["case_id"])]
            result = _selection_result(
                case,
                item,
                inventory,
                client,
                metadata,
                plugin_sha256=plugin_sha256,
                production_http_requests=production_http_requests,
            )
            if trial == 0:
                observations.append({"case_id": case["case_id"], "result": result})
            ok, reason, card = route_score(case, result)
            route_key = str(case["expected"]["route_key"])
            parameter, parameter_reason = (
                parameter_score(route_key, card)
                if case["expected"]["gap_code"] is None
                else (None, "gap_not_applicable")
            )
            result.update(_terminal_network_fact(production_http_requests))
            terminal, terminal_reason = terminal_score(case, result)
            state = states[str(case["case_id"])]
            state["selection"].append(ok)
            state["selected"].append(tuple(
                ["selectors", *sorted(map(str, item["selectors"]))]
            ))
            state["parameter"].append(parameter)
            state["terminal"].append(terminal)
            state["reasons"].append((reason, parameter_reason, terminal_reason))
    receipt = _external_selector_receipt(
        plugin_path, plugin_sha256, catalog, blind_receipt, receipts
    )
    return states, trials, observations, receipt


def _external_selector_receipt(
    plugin_path: Path,
    plugin_sha256: str,
    catalog: Mapping[str, Any],
    blind_receipt: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    selector_version = validate_selector_version_binding(
        receipts, plugin_path=plugin_path, plugin_sha256=plugin_sha256
    )
    known_metadata = {
        "selector", "network_called", "meaningful_accuracy_evidence",
        "request_sha256", "stdin_encoding",
    }
    return {
        "mode": "external_selector",
        "protocol": REQUEST_SCHEMA,
        "plugin_path": str(plugin_path),
        "plugin_sha256": plugin_sha256,
        "selector_identity": {
            "plugin_sha256": plugin_sha256,
            "selector_version": selector_version,
        },
        "selector_self_report_measurements": self_report_measurements(),
        "request_sha256_verified_trials": sum(
            "request_sha256" in receipt for receipt in receipts
        ),
        "additional_metadata_keys": sorted({
            str(key)
            for receipt in receipts
            for key in receipt
            if key not in known_metadata
        }),
        "catalog_capability_count": len(catalog["capabilities"]),
        "catalog_category_count": len(catalog["categories"]),
        "blind_presentation": blind_receipt,
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


def _stderr_summary(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    rendered = " ".join(str(value or "").splitlines()).strip()
    return rendered[:2_000] or "<empty>"


def _invoke_plugin(
    plugin_path: Path,
    catalog: Mapping[str, Any],
    questions: Sequence[Mapping[str, str]],
    *,
    timeout_seconds: float,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if not plugin_path.is_file():
        raise ValueError("--selector-plugin must name one readable Python file")
    request = {
        "schema_version": REQUEST_SCHEMA,
        "catalog": catalog,
        "questions": [dict(question) for question in questions],
    }
    try:
        request_text = canonical_request_text(request)
        completed = subprocess.run(
            [sys.executable, str(plugin_path)],
            input=request_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ValueError(
            "external selector stage=subprocess_execute timed out after "
            f"{timeout_seconds}s; stderr: {_stderr_summary(error.stderr)}; retry "
            "with a responsive plugin or raise --selector-timeout"
        ) from error
    if completed.returncode != 0:
        raise ValueError(
            "external selector stage=subprocess_execute failed with exit code "
            f"{completed.returncode}; stderr: {_stderr_summary(completed.stderr)}; run the plugin directly "
            f"and return one valid {RESPONSE_SCHEMA} JSON object"
        )
    try:
        response = json.loads(completed.stdout)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(
            "external selector stage=response_decode failed; stderr: "
            f"{_stderr_summary(completed.stderr)}; return one valid {RESPONSE_SCHEMA} JSON object"
        ) from error
    return _validate_response(response, request, catalog)


def _blind_questions(
    cases: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, str]], dict[str, str], dict[str, Any]]:
    """Shuffle by journey and replace case identities before selector access."""

    fingerprint = hashlib.sha256(json.dumps(
        [(str(case["case_id"]), str(case["prompt"])) for case in cases],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    rng = random.Random(int(fingerprint, 16))
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for case in cases:
        group = str(case.get("journey_id", case["case_id"]))
        groups.setdefault(group, []).append(case)
    for rows in groups.values():
        rng.shuffle(rows)
    ordered: list[Mapping[str, Any]] = []
    previous: str | None = None
    while any(groups.values()):
        active = [key for key, rows in groups.items() if rows]
        rng.shuffle(active)
        if len(active) > 1 and active[0] == previous:
            active[0], active[1] = active[1], active[0]
        for key in active:
            ordered.append(groups[key].pop())
            previous = key
    ordered_groups = [str(case.get("journey_id", case["case_id"])) for case in ordered]
    if any(left == right for left, right in zip(ordered_groups, ordered_groups[1:])):
        raise RuntimeError("blind selector order cannot place one journey adjacently")
    aliases = {
        str(case["case_id"]): f"q-{index:04d}"
        for index, case in enumerate(ordered, start=1)
    }
    questions = [
        {"id": aliases[str(case["case_id"])], "query": str(case["prompt"])}
        for case in ordered
    ]
    return questions, aliases, {
        "randomized": True,
        "journey_degrouped": True,
        "case_ids_anonymized": True,
        "order_seed_sha256": fingerprint,
        "question_count": len(questions),
    }


def _validate_response(
    response: Any,
    request: Mapping[str, Any],
    catalog: Mapping[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    if not isinstance(response, Mapping) or response.get("schema_version") != RESPONSE_SCHEMA:
        raise ValueError(f"external selector response must use {RESPONSE_SCHEMA}")
    if set(response) - {"schema_version", "results", "metadata"}:
        raise ValueError(
            "external selector response allows only schema_version, results, and "
            "metadata; remove unsupported top-level fields and rerun"
        )
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
    validate_request_sha256(metadata, request)
    validated_metadata = copy.deepcopy(dict(metadata))
    validated_metadata["selector"] = str(metadata["selector"]).strip()
    return selected, validated_metadata


def _selection_result(
    case: Mapping[str, Any],
    selected: Mapping[str, Any],
    inventory: Mapping[str, Mapping[str, Any]],
    client: Any,
    metadata: Mapping[str, Any],
    *,
    plugin_sha256: str,
    production_http_requests: Callable[[], int],
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
        item = inventory[selectors[0]]
        if item["source"] == "gap":
            gap = copy.deepcopy(dict(item["card"]))
            gap["query"] = query
            candidates = []
            gaps = [gap]
        else:
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
    terminal_network = _terminal_network_fact(production_http_requests)
    return {
        "schema_version": "gravity.agent-external-selector-result.v1",
        "ok": True,
        "status": "success" if candidates else "capability_gap",
        "offline": metadata.get("network_called") is not True,
        "network_called": metadata.get("network_called") is True,
        "selection_network_called": metadata.get("network_called") is True,
        "selection_network_measured": False,
        "selection_network_measurement_reason": (
            SELECTION_NETWORK_MEASUREMENT_REASON
        ),
        "selector_identity": {
            "plugin_sha256": plugin_sha256,
            "selector_version": str(metadata["selector"]).strip(),
        },
        "selector_self_report_measurements": self_report_measurements(),
        **terminal_network,
        "selected_selectors": selectors,
        "candidates": candidates,
        "capability_gaps": gaps,
    }


def _terminal_network_fact(
    production_http_requests: Callable[[], int],
) -> dict[str, Any]:
    """Snapshot the only production-HTTP fact available to this harness stage."""

    attempts = production_http_requests()
    return {
        "execution_http_requests": attempts,
        "execution_network_called": attempts > 0,
        "terminal_offline_measured": False,
        "terminal_offline_measurement_reason": TERMINAL_OFFLINE_MEASUREMENT_REASON,
    }


def _described_card(
    selector: str,
    inventory: Mapping[str, Mapping[str, Any]],
    client: Any,
    query: str,
) -> dict[str, Any]:
    from gravity_sdk.agent_catalog import _capability_for_item
    from gravity_sdk.agent_handoff import attach_plan_node

    item = inventory[selector]
    card = _capability_for_item(item, client)
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
    "SELECTION_NETWORK_MEASUREMENT_REASON",
    "external_selector_trials",
]
