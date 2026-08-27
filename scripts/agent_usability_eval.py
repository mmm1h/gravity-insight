"""Repeatable, production-network-free Agent usability measurement."""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from time import perf_counter
from typing import Any, Mapping, Sequence
from unittest.mock import patch


os.environ["GRAVITY_SDK_AUTO_UPGRADE"] = "0"

ROOT = Path(__file__).resolve().parents[1]
SUITE_ROOT = ROOT / "evals" / "agent_usability"
LEDGER_PATH = SUITE_ROOT / "query-ledger.jsonl"
SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from agent_usability_governance import (
    PROTECTED_SPLITS,
    append_query_record,
    ensure_query_allowed,
    security_compliance_score,
)
from agent_usability_expectations import (
    LEDGER_PATH as JOURNEY_LEDGER_PATH,
    TARGETS_PATH as JOURNEY_TARGETS_PATH,
    derive_cases,
)
from agent_usability_external_selector import external_selector_trials
from agent_usability_external_selector import SELECTION_NETWORK_MEASUREMENT_REASON
from agent_usability_external_selector import TERMINAL_OFFLINE_MEASUREMENT_REASON

SCHEMA_VERSION = "gravity.agent-usability-result.v1"
COMPARE_SCHEMA_VERSION = "gravity.agent-usability-compare.v1"
CHUNK_SIZE = 32
WORKSPACE_SQL_GAP = "WORKSPACE_SQL_PRODUCT_NOT_CONFIGURED"

ROUTES: dict[str, dict[str, str]] = {
    "event": {"kind": "analysis_query_spec", "analysis_kind": "event"},
    "funnel": {"kind": "analysis_query_spec", "analysis_kind": "funnel"},
    "retention": {"kind": "analysis_query_spec", "analysis_kind": "retention"},
    "property": {"kind": "analysis_query_spec", "analysis_kind": "property"},
    "scatter": {"kind": "analysis_query_spec", "analysis_kind": "scatter"},
    "period_compare": {"kind": "analysis_query_spec", "selector": "analysis.query.spec"},
    "segment_evaluate": {"kind": "segment_rule_spec", "composite": "segment_evaluate"},
    "analysis_context": {"kind": "composite", "composite": "analysis_context"},
    "app_governance": {"kind": "composite", "composite": "app_snapshot"},
    "attribution_settings": {"kind": "composite", "composite": "attribution_snapshot"},
    "user_journey": {"kind": "composite", "composite": "user_journey"},
    "business_pulse": {"kind": "composite", "composite": "business_pulse"},
    "company_usage": {"kind": "composite", "composite": "company_usage"},
    "custom_audience": {"kind": "composite", "composite": "custom_audience"},
    "material_performance": {"kind": "composite", "composite": "material_performance"},
    "order_directory": {"kind": "composite", "composite": "order_directory"},
    "order_split_trace": {"kind": "composite", "composite": "order_split_trace"},
    "monetization_detail": {"kind": "composite", "composite": "monetization_detail"},
    "workspace_sql": {"kind": "sql_product"},
    "dashboard_snapshot": {"kind": "composite", "composite": "dashboard_snapshot"},
    "dashboard_analysis": {"kind": "composite", "composite": "dashboard_analysis"},
    "saved_analysis": {"kind": "composite", "composite": "saved_analysis"},
    "analysis_template": {"kind": "composite", "composite": "analysis_template"},
    "segment_snapshot": {"kind": "composite", "composite": "segment_snapshot"},
    "segment_members": {"kind": "composite", "composite": "segment_members"},
    "multidim": {"kind": "composite", "composite": "multidim"},
    "promotion_performance": {"kind": "composite", "composite": "promotion_performance"},
    "bilibili_performance": {"kind": "composite", "composite": "bilibili_account_performance"},
    "advertiser_profile": {"kind": "composite", "composite": "advertiser_profile"},
    "title_package": {"kind": "composite", "composite": "title_package"},
    "metadata_search": {"kind": "metadata", "metadata_kind": "all"},
    "table_lineage": {"kind": "metadata", "metadata_kind": "table_lineage"},
    "material_export": {"kind": "export", "operation_id": "export.material.report.start"},
    "analysis_default_dictionary": {
        "kind": "composite", "composite": "analysis_default_dictionary",
    },
    "realtime_event_catalog": {
        "kind": "composite", "composite": "realtime_event_catalog",
    },
    "app_catalog": {"kind": "operation", "selector": "app.list"},
    "app_public_info": {"kind": "operation", "selector": "app.app_info.get"},
    "monetization_aggregate": {"kind": "operation", "selector": "report.get.query"},
    "report_directory": {"selector": "composite:report_directory"},
    "report_subscriptions": {"selector": "composite:report_subscriptions"},
    "attribution_performance": {
        "kind": "composite", "composite": "attribution_performance",
    },
    "attribution_user_detail": {
        "kind": "composite", "composite": "attribution_user_detail",
    },
    "material_asset": {"kind": "material_asset", "selector": "material.asset.fetch"},
}

CATALOG_INPUTS: dict[str, tuple[str, ...]] = {
    key: ("app",) for key in (
        "event", "funnel", "retention", "property", "scatter", "period_compare",
        "segment_evaluate", "analysis_context", "app_governance", "attribution_settings",
        "user_journey", "order_directory", "order_split_trace", "monetization_detail",
        "title_package", "attribution_performance", "attribution_user_detail",
    )
}
CATALOG_INPUTS.update({
    "business_pulse": ("apps",), "material_performance": ("apps",),
    "dashboard_snapshot": ("app", "ref"), "dashboard_analysis": ("app", "ref"),
    "saved_analysis": ("app", "ref"), "analysis_template": ("app", "scope", "ref"),
    "segment_snapshot": ("app", "ref"), "segment_members": ("app", "ref"),
    "multidim": ("app", "inputs"), "promotion_performance": ("app", "metrics"),
})


class BlockedTransport:
    """Inventory-capable client seam that fails before any HTTP request."""

    _runtime = object()

    def __init__(self) -> None:
        self.attempts = 0

    def request(self, *_args: Any, **_kwargs: Any) -> Any:
        self.attempts += 1
        raise RuntimeError("production HTTP is disabled by the Agent evaluator")


class NetworkGuard:
    def __init__(self) -> None:
        self.attempts = 0

    def block(self, *_args: Any, **_kwargs: Any) -> Any:
        self.attempts += 1
        raise RuntimeError("network access is disabled by the Agent evaluator")


def _json_bytes(value: Any, *, pretty: bool = False) -> bytes:
    indent = 2 if pretty else None
    separators = None if pretty else (",", ":")
    return (json.dumps(value, ensure_ascii=False, indent=indent, sort_keys=True,
                       separators=separators) + "\n").encode("utf-8")


def _manifest() -> dict[str, Any]:
    return json.loads((SUITE_ROOT / "suite.json").read_text(encoding="utf-8"))


def _development_cases(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    payload = (SUITE_ROOT / "cases" / "development.jsonl").read_bytes()
    if hashlib.sha256(payload).hexdigest() != manifest["development_sha256"]:
        raise ValueError("development suite hash does not match suite.json")
    return [json.loads(line) for line in payload.splitlines()]


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    selected = bytearray()
    for counter in range((length + 31) // 32):
        selected.extend(hmac.new(
            key, b"stream\0" + nonce + counter.to_bytes(8, "big"), hashlib.sha256
        ).digest())
    return bytes(selected[:length])


def _holdout_cases(manifest: Mapping[str, Any], key_path: Path) -> list[dict[str, Any]]:
    sealed = (SUITE_ROOT / "cases" / "holdout.sealed.json").read_bytes()
    if hashlib.sha256(sealed).hexdigest() != manifest["holdout_sealed_sha256"]:
        raise ValueError("sealed holdout hash does not match suite.json")
    key = key_path.read_bytes()
    if len(key) != 32:
        raise ValueError("holdout key must contain exactly 32 bytes")
    envelope = json.loads(sealed)
    nonce = base64.b64decode(envelope["nonce"], validate=True)
    ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
    observed = base64.b64decode(envelope["tag"], validate=True)
    expected = hmac.new(key, b"tag\0" + nonce + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(observed, expected):
        raise ValueError("holdout authentication failed")
    stream = _keystream(key, nonce, len(ciphertext))
    plaintext = bytes(left ^ right for left, right in zip(ciphertext, stream))
    if hashlib.sha256(plaintext).hexdigest() != manifest["holdout_plaintext_sha256"]:
        raise ValueError("holdout plaintext hash does not match suite.json")
    return [json.loads(line) for line in plaintext.splitlines()]


def _final_keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    selected = bytearray()
    for counter in range((length + 31) // 32):
        selected.extend(hmac.new(
            key,
            b"final-stream\0" + nonce + counter.to_bytes(8, "big"),
            hashlib.sha256,
        ).digest())
    return bytes(selected[:length])


def _final_cases(manifest: Mapping[str, Any], key_path: Path) -> list[dict[str, Any]]:
    sealed = (SUITE_ROOT / "cases" / "final.sealed.json").read_bytes()
    if hashlib.sha256(sealed).hexdigest() != manifest["final_sealed_sha256"]:
        raise ValueError("sealed final hash does not match suite.json")
    key = key_path.read_bytes()
    if len(key) != 32:
        raise ValueError("final key must contain exactly 32 bytes")
    envelope = json.loads(sealed)
    if envelope.get("schema_version") != "gravity.agent-usability-sealed-final.v1":
        raise ValueError("sealed final envelope has an unknown schema")
    nonce = base64.b64decode(envelope["nonce"], validate=True)
    ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
    observed = base64.b64decode(envelope["tag"], validate=True)
    expected = hmac.new(
        key, b"final-tag\0" + nonce + ciphertext, hashlib.sha256
    ).digest()
    if not hmac.compare_digest(observed, expected):
        raise ValueError("final authentication failed")
    stream = _final_keystream(key, nonce, len(ciphertext))
    plaintext = bytes(left ^ right for left, right in zip(ciphertext, stream))
    if hashlib.sha256(plaintext).hexdigest() != manifest["final_plaintext_sha256"]:
        raise ValueError("final plaintext hash does not match suite.json")
    return [json.loads(line) for line in plaintext.splitlines()]


def load_cases(split: str, key_path: Path | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _manifest()
    cases = _development_cases(manifest) if split in {"development", "all"} else []
    if split in {"holdout", "all"}:
        if key_path is None:
            raise ValueError("--holdout-key is required for holdout evaluation")
        cases.extend(_holdout_cases(manifest, key_path))
    if split == "final":
        if key_path is None:
            raise ValueError("--final-key is required for final evaluation")
        cases.extend(_final_cases(manifest, key_path))
    expected = {
        "development": manifest["development_case_count"],
        "holdout": manifest["holdout_case_count"],
        "all": manifest["total_case_count"],
        "final": manifest["final_case_count"],
    }[split]
    if len(cases) != expected or len({case["case_id"] for case in cases}) != expected:
        raise ValueError("suite case count or case identity is invalid")
    cases, expectation_derivation = derive_cases(cases)
    return {**manifest, "expectation_derivation": expectation_derivation}, cases


def _card_value(card: Mapping[str, Any], key: str) -> Any:
    if key == "selector":
        return card.get("selector")
    if key == "operation_id":
        return card.get("operation_id") or card.get("selector")
    return card.get(key)


def _gap(result: Mapping[str, Any], code: str) -> Mapping[str, Any] | None:
    gaps = result.get("capability_gaps")
    if not isinstance(gaps, Sequence):
        return None
    return next((item for item in gaps if isinstance(item, Mapping) and item.get("code") == code), None)


def _multiple_intent_score(
    expected: Mapping[str, Any], result: Mapping[str, Any]
) -> tuple[bool, str, None]:
    gap = _gap(result, "MULTIPLE_INTENTS")
    if gap is None:
        return False, "multiple_intents_missing", None
    observed = gap.get("candidate_selectors")
    if (
        not isinstance(observed, Sequence)
        or isinstance(observed, (str, bytes))
        or not all(isinstance(value, str) for value in observed)
        or len(set(observed)) != len(observed)
    ):
        return False, "wrong_intent_candidates", None
    wanted = expected.get("candidate_selectors")
    journey_ids = expected.get("journey_ids")
    selector_journeys = {
        selector: journey_id for journey_id, selector in wanted.items()
    } if isinstance(wanted, Mapping) else {}
    observed_journeys = [selector_journeys.get(selector) for selector in observed]
    matched = (
        isinstance(journey_ids, Sequence)
        and not isinstance(journey_ids, (str, bytes))
        and None not in observed_journeys
        and len(observed_journeys) == len(journey_ids)
        and set(observed_journeys) == set(journey_ids)
    )
    return matched, "correct_multiple_intents" if matched else "wrong_intent_candidates", None


def route_score(case: Mapping[str, Any], result: Mapping[str, Any] | None) -> tuple[bool, str, Mapping[str, Any] | None]:
    if result is None:
        return False, "discovery_error", None
    expected = case["expected"]
    if expected.get("gap_code") == "MULTIPLE_INTENTS" and isinstance(
        expected.get("journey_ids"), Sequence
    ):
        return _multiple_intent_score(expected, result)
    gap_code = expected.get("gap_code")
    if isinstance(gap_code, str):
        return (_gap(result, gap_code) is not None, "target_gap" if _gap(result, gap_code) else "wrong_gap", None)
    route_key = str(expected["route_key"])
    if route_key == "workspace_sql" and _gap(result, WORKSPACE_SQL_GAP) is not None:
        return True, "environment_gap", None
    candidates = result.get("candidates")
    if not isinstance(candidates, Sequence) or not candidates:
        reason = "ambiguous" if _gap(result, "MULTIPLE_INTENTS") is not None else "no_candidate"
        return False, reason, None
    card = candidates[0]
    if not isinstance(card, Mapping):
        return False, "invalid_candidate", None
    matcher = ROUTES[route_key]
    matched = all(_card_value(card, key) == value for key, value in matcher.items())
    return matched, "correct" if matched else "wrong_product", card if matched else None


def _template_has(template: Any, field: str) -> bool:
    if not isinstance(template, Mapping):
        return False
    if field in template:
        return True
    return field == "inputs" and any(str(key).startswith("inputs.") for key in template)


def _source_inputs(card: Mapping[str, Any]) -> set[str]:
    selected: set[str] = set()
    bound = card.get("call_bound")
    scenarios = bound.get("scenarios") if isinstance(bound, Mapping) else None
    for scenario in scenarios if isinstance(scenarios, Sequence) else ():
        sources = scenario.get("input_sources") if isinstance(scenario, Mapping) else None
        for source in sources if isinstance(sources, Sequence) else ():
            inputs = source.get("inputs") if isinstance(source, Mapping) else None
            if isinstance(inputs, Sequence):
                selected.update(str(value) for value in inputs)
    return selected


def _catalog_source_present(route_key: str, field: str, sources: set[str]) -> bool:
    if field not in CATALOG_INPUTS.get(route_key, ()):
        return True
    if field == "inputs":
        return any(value.startswith("inputs.") for value in sources)
    return field in sources


def parameter_score(route_key: str, card: Mapping[str, Any] | None) -> tuple[bool | None, str]:
    if card is None:
        return None, "route_not_reached"
    required = card.get("required_inputs")
    missing = card.get("missing_inputs")
    template = card.get("input_template")
    if not isinstance(required, Sequence) or isinstance(required, (str, bytes)):
        return False, "required_inputs_missing"
    if not isinstance(missing, Sequence) or set(map(str, required)) - set(map(str, missing)):
        return False, "required_inputs_not_exposed"
    sources = _source_inputs(card)
    for field in map(str, required):
        if not _template_has(template, field):
            return False, "input_template_missing"
        if not _catalog_source_present(route_key, field, sources):
            return False, "catalog_source_missing"
    if card.get("plan_executable") is True and not isinstance(card.get("plan_node"), Mapping):
        return False, "handoff_missing"
    return True, "fillable"


def terminal_score(case: Mapping[str, Any], result: Mapping[str, Any] | None) -> tuple[bool | None, str]:
    expected = case["expected"]
    code = expected.get("gap_code")
    if expected.get("route_key") == "workspace_sql":
        code = WORKSPACE_SQL_GAP
    if not isinstance(code, str):
        return None, "skipped_production"
    if result is None:
        return False, "discovery_error"
    selected = _gap(result, code)
    if selected is None:
        return False, "target_gap_missing"
    if not str(selected.get("next_action", "")).strip():
        return False, "gap_next_action_missing"
    if "execution_network_called" in result:
        terminal_offline = result.get("execution_network_called") is False
    else:
        terminal_offline = (
            result.get("offline") is True and result.get("network_called") is False
        )
    if not terminal_offline:
        return False, "gap_not_offline"
    return True, "explicit_gap"


def _selection_identity(result: Mapping[str, Any] | None) -> tuple[str, ...]:
    """Return the exact scored selection, independent of whether it was correct."""

    if result is None:
        return ("result:none",)
    direct = result.get("selected_selectors")
    if isinstance(direct, Sequence) and not isinstance(direct, (str, bytes)):
        return ("selectors", *sorted(str(value) for value in direct))
    identities: list[str] = []
    candidates = result.get("candidates")
    if isinstance(candidates, Sequence) and candidates:
        card = candidates[0]
        if isinstance(card, Mapping):
            fields = [
                f"{key}:{card[key]}"
                for key in (
                    "selector", "composite", "operation_id", "metadata_kind", "kind"
                )
                if card.get(key) is not None
            ]
            identities.append(":".join(("candidate", *fields)))
    gaps = result.get("capability_gaps")
    if isinstance(gaps, Sequence):
        for gap in gaps:
            if not isinstance(gap, Mapping):
                continue
            selectors = gap.get("candidate_selectors")
            selected = (
                sorted(map(str, selectors))
                if isinstance(selectors, Sequence)
                and not isinstance(selectors, (str, bytes))
                else []
            )
            identities.append(":".join(("gap", str(gap.get("code", "unknown")), *selected)))
    if identities:
        return tuple(sorted(identities))
    return ("selection:none",)


def _discover_trials(
    cases: Sequence[Mapping[str, Any]], client: Any, trials: int
) -> tuple[dict[str, Any], int, list[dict[str, Any]]]:
    from gravity_sdk.agents.batch import capabilities_many

    states = {
        case["case_id"]: {
            "selection": [], "selected": [], "parameter": [], "terminal": [],
            "reasons": [],
        }
        for case in cases
    }
    batch_calls = 0
    observations: list[dict[str, Any]] = []
    for trial in range(trials):
        for start in range(0, len(cases), CHUNK_SIZE):
            chunk = cases[start:start + CHUNK_SIZE]
            questions = [{"id": case["case_id"], "query": case["prompt"], "limit": 5} for case in chunk]
            response = capabilities_many(questions, client=client)
            batch_calls += 1
            for case, item in zip(chunk, response.get("results", [])):
                result = item.get("result") if isinstance(item, Mapping) else None
                if trial == 0:
                    observations.append({"case_id": case["case_id"], "result": result})
                ok, reason, card = route_score(case, result)
                route_key = str(case["expected"]["route_key"])
                parameter, parameter_reason = parameter_score(route_key, card) if case["expected"]["gap_code"] is None else (None, "gap_not_applicable")
                terminal, terminal_reason = terminal_score(case, result)
                state = states[case["case_id"]]
                state["selection"].append(ok)
                state["selected"].append(_selection_identity(result))
                state["parameter"].append(parameter)
                state["terminal"].append(terminal)
                state["reasons"].append((reason, parameter_reason, terminal_reason))
    return states, batch_calls, observations


def _rate(passed: int, total: int) -> float | None:
    return round(passed / total, 6) if total else None


def _layer(states: Mapping[str, Mapping[str, Any]], index: int, key: str) -> dict[str, Any]:
    values = [state[key][index] for state in states.values() if state[key][index] is not None]
    passed = sum(value is True for value in values)
    return {"passed": passed, "total": len(values), "rate": _rate(passed, len(values))}


def _reliability(states: Mapping[str, Mapping[str, Any]], key: str) -> dict[str, Any]:
    eligible = [
        (case_id, state) for case_id, state in states.items()
        if state[key][0] is not None
    ]
    values = [state[key] for _case_id, state in eligible]
    pass1 = sum(series[0] is True for series in values)
    pass4 = sum(all(value is True for value in series) for series in values)
    unstable = sorted(
        case_id for case_id, state in eligible
        if len(set(state["selected"])) > 1
    )
    variants = {
        case_id: [list(value) for value in sorted(set(states[case_id]["selected"]))]
        for case_id in unstable
    }
    return {
        "pass^1": {"passed": pass1, "total": len(values), "rate": _rate(pass1, len(values))},
        "pass^4": {"passed": pass4, "total": len(values), "rate": _rate(pass4, len(values))},
        "unstable_tasks": len(unstable),
        "unstable_case_ids": unstable,
        "unstable_selections": variants,
    }


def _reason_counts(states: Mapping[str, Mapping[str, Any]], position: int) -> dict[str, int]:
    return dict(sorted(Counter(state["reasons"][0][position] for state in states.values()).items()))


def _valid_plan() -> dict[str, Any]:
    return {"schema_version": "gravity.plan.v1", "nodes": [{"id": "n", "kind": "run", "request": {"selector": "app.list"}}]}


def recovery_score(client: Any) -> tuple[dict[str, Any], int]:
    from gravity_sdk.agent import discover_capabilities
    from gravity_sdk.errors import UpstreamUnavailableError, error_detail_from_exception
    from gravity_sdk.plan import PlanAdapter, PlanAdapters, execute_plan, validate_plan

    results: list[bool] = []
    calls = 0
    faults = [
        {"schema_version": "gravity.plan.v1", "nodes": [{"id": "n", "kind": "run"}]},
        {"schema_version": "gravity.plan.v1", "nodes": [{"id": "n", "kind": "unknown", "request": {}}]},
        {"schema_version": "gravity.plan.v1", "nodes": [{"id": "n", "kind": "run", "request": {}, "unknown": True}]},
    ]
    for fault in faults:
        calls += 1
        try:
            validate_plan(fault)
            detail = None
        except Exception as error:
            detail = error_detail_from_exception(error)
        calls += 1
        repaired = validate_plan(_valid_plan())
        results.append(bool(detail and detail.next_action and repaired.nodes))

    attempts = {"count": 0}
    def transient(_request: Mapping[str, Any], _context: Any) -> dict[str, Any]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise UpstreamUnavailableError("controlled temporary failure")
        return {"ok": True, "status": "success", "data": {"list": []}}
    adapter = PlanAdapter(execute=transient, validate=lambda _request, _context: None)
    first = execute_plan(_valid_plan(), adapters=PlanAdapters(run=adapter), workspace=object())
    second = execute_plan(_valid_plan(), adapters=PlanAdapters(run=adapter), workspace=object())
    calls += 2
    error = first["results"][0].get("error") or {}
    results.append(bool(error.get("next_action") and second.get("status") == "success"))

    ambiguous = discover_capabilities("同时查看分群规模和成员名单", client=client, limit=5)
    calls += 1
    multiple = _gap(ambiguous, "MULTIPLE_INTENTS")
    results.append(bool(multiple and str(multiple.get("next_action", "")).strip()))
    passed = sum(results)
    return {
        "passed": passed,
        "total": len(results),
        "rate": _rate(passed, len(results)),
        "failure_classes": {"missing_action": len(results) - passed},
    }, calls


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _source_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in sorted((ROOT / "src" / "gravity_sdk").rglob("*.py")):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def _evaluator_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in (
        Path(__file__).resolve(),
        SCRIPT_ROOT / "agent_usability_governance.py",
        SCRIPT_ROOT / "agent_usability_expectations.py",
        SCRIPT_ROOT / "agent_usability_external_selector.py",
        SCRIPT_ROOT / "agent_usability_selector_measurements.py",
        JOURNEY_TARGETS_PATH,
        JOURNEY_LEDGER_PATH,
    ):
        digest.update(path.relative_to(ROOT).as_posix().encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def _subject(manifest: Mapping[str, Any]) -> dict[str, Any]:
    reference = str(manifest["source_revision"])
    changed = subprocess.run(
        ["git", "diff", "--quiet", reference, "--", "src/gravity_sdk"], cwd=ROOT
    ).returncode != 0
    return {
        "git_commit": _git("rev-parse", "HEAD"),
        "suite_reference_revision": reference,
        "product_source_changed_from_reference": changed,
        "product_source_sha256": _source_fingerprint(),
        "evaluator_source_sha256": _evaluator_fingerprint(),
        "git_worktree_dirty": subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--"], cwd=ROOT
        ).returncode != 0,
    }


def _known_limitations(split: str) -> list[dict[str, Any]]:
    protected = [split] if split in PROTECTED_SPLITS else (
        ["holdout"] if split == "all" else []
    )
    if not protected:
        return []
    return [{
        "code": "PROTECTED_LEGACY_MULTI_INTENT_EXPECTATION_BIAS",
        "splits": protected,
        "detail": (
            "Protected cases without an explicit multiple-intent declaration retain "
            "legacy single-journey scoring; any such ambiguous prompts may be biased."
        ),
    }]


def _summary(result: Mapping[str, Any]) -> str:
    layers = result["layers"]
    rows = [
        ("Product selection", layers["product_selection"]),
        ("Parameter fillability (reached routes)", layers["parameter_fillability"]),
        ("End-to-end offline terminal", layers["end_to_end"]),
        ("Error recovery", layers["error_recovery"]),
    ]
    text = ["# Agent usability result", "", f"- Suite: `{result['suite_version']}`", f"- Split: `{result['split']}`", f"- Cases: {result['case_count']}", "", "| Layer | Passed | Total | Rate |", "| --- | ---: | ---: | ---: |"]
    for name, value in rows:
        rate = "n/a" if value["rate"] is None else f"{100 * value['rate']:.2f}%"
        text.append(f"| {name} | {value['passed']} | {value['total']} | {rate} |")
    reliability = layers["repeat_reliability"]
    security = layers["security_compliance"]
    local_writes = security.get("local_write_information", {})
    text.extend([
        "",
        f"Selection network measured: {result['selection_network_measured']}",
        f"Selection network measurement reason: "
        f"{result['selection_network_measurement_reason'] or 'n/a'}",
        f"Terminal offline measured: {result['terminal_offline_measured']}",
        f"Security compliance hard gate: {security['gate'].upper()} "
        f"(violations: {security['violation_count']})",
        f"Local-write handoffs (information only): "
        f"{local_writes.get('handoff_count', 0)}",
        f"Selection pass^4: {reliability['product_selection']['pass^4']['passed']}/"
        f"{reliability['product_selection']['pass^4']['total']}",
        f"Terminal pass^4: {reliability['end_to_end']['pass^4']['passed']}/"
        f"{reliability['end_to_end']['pass^4']['total']}",
        f"Selection unstable tasks: {reliability['product_selection']['unstable_tasks']}",
        f"Terminal unstable tasks: {reliability['end_to_end']['unstable_tasks']}",
        f"Skipped production cases: {layers['end_to_end']['skipped_production']}",
        f"Production HTTP requests: {layers['cost']['production_http_requests']}",
        f"Elapsed: {layers['cost']['elapsed_seconds']:.3f}s",
    ])
    measurements = result.get("selector_self_report_measurements")
    if isinstance(measurements, Mapping):
        for name, measurement in measurements.items():
            if not isinstance(measurement, Mapping):
                continue
            state = "MEASURED" if measurement.get("measured") is True else "UNMEASURABLE"
            text.append(f"Selector self-report {name}: {state}")
            reason = measurement.get("measurement_reason")
            if reason:
                text.append(f"Selector self-report {name} reason: {reason}")
    for limitation in result.get("known_limitations", []):
        text.append(f"Known limitation: {limitation['code']}")
    text.append("")
    return "\n".join(text)


def _suite_identity(manifest: Mapping[str, Any], split: str) -> tuple[str, dict[str, Any]]:
    if split == "final":
        return str(manifest["final_suite_version"]), {
            key: manifest[key]
            for key in ("final_plaintext_sha256", "final_sealed_sha256")
        }
    return str(manifest["suite_version"]), {
        key: manifest[key]
        for key in (
            "development_sha256",
            "holdout_plaintext_sha256",
            "holdout_sealed_sha256",
        )
    }


def _run_evaluation_unrecorded(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], str]:
    started = perf_counter()
    split = "development" if args.split == "dev" else args.split
    selected_key = args.final_key if split == "final" else args.holdout_key
    key = Path(selected_key).resolve() if selected_key else None
    manifest, cases = load_cases(split, key)
    trials = int(manifest["trials"])
    blocker, network = BlockedTransport(), NetworkGuard()
    with tempfile.TemporaryDirectory(prefix="gravity-agent-eval-") as cache, ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {"GRAVITY_CACHE_HOME": cache, "LOCALAPPDATA": cache, "XDG_CACHE_HOME": cache}))
        stack.enter_context(patch.object(socket.socket, "connect", network.block))
        stack.enter_context(patch("socket.create_connection", network.block))
        from gravity_sdk.client import GravityInsightClient
        client = GravityInsightClient.from_env(transport=blocker)
        selector_path = (
            Path(args.selector_plugin).resolve()
            if getattr(args, "selector_plugin", None)
            else None
        )
        if selector_path is None:
            states, batch_calls, observations = _discover_trials(cases, client, trials)
            selector_receipt = {
                "mode": "product_recognizer_with_zero_candidate_lexical_fallback"
            }
            discovery_calls, selector_calls = batch_calls, 0
        else:
            states, batch_calls, observations, selector_receipt = external_selector_trials(
                cases,
                client,
                trials,
                plugin_path=selector_path,
                timeout_seconds=float(args.selector_timeout),
                route_score=route_score,
                parameter_score=parameter_score,
                terminal_score=terminal_score,
                production_http_requests=lambda: blocker.attempts,
            )
            discovery_calls, selector_calls = 0, batch_calls
        recovery, recovery_calls = recovery_score(client)
        security = security_compliance_score(
            observations, client=client, blocked_transport=blocker
        )
    if blocker.attempts or network.attempts:
        raise RuntimeError("evaluation attempted prohibited network access")
    selection = _layer(states, 0, "selection")
    parameters = _layer(states, 0, "parameter")
    terminal = _layer(states, 0, "terminal")
    terminal["skipped_production"] = sum(state["terminal"][0] is None for state in states.values())
    elapsed = perf_counter() - started
    selector_network_trials = sum(
        item.get("network_called") is True
        for item in selector_receipt.get("trial_receipts", [])
        if isinstance(item, Mapping)
    )
    selection_network_measured = selector_path is None
    selector_self_report_measurements = selector_receipt.get(
        "selector_self_report_measurements", {}
    )
    suite_version, suite_hashes = _suite_identity(manifest, split)
    result = {
        "schema_version": SCHEMA_VERSION,
        "suite_version": suite_version,
        "suite_hashes": suite_hashes,
        "expectation_derivation": manifest["expectation_derivation"],
        "split": split,
        "case_count": len(cases),
        "trials": trials,
        "run_label": args.label,
        "run_at": datetime.now(timezone.utc).isoformat(),
        "subject": _subject(manifest),
        "selector_arm": selector_receipt,
        "selector_self_report_measurements": selector_self_report_measurements,
        "known_limitations": _known_limitations(split),
        "selection_network_measured": selection_network_measured,
        "selection_network_measurement_reason": (
            None if selection_network_measured
            else SELECTION_NETWORK_MEASUREMENT_REASON
        ),
        "terminal_offline_measured": False,
        "terminal_offline_measurement_reason": TERMINAL_OFFLINE_MEASUREMENT_REASON,
        "layers": {
            "product_selection": {**selection, "failure_classes": _reason_counts(states, 0)},
            "parameter_fillability": {**parameters, "not_reached": sum(state["parameter"][0] is None for state in states.values()), "failure_classes": _reason_counts(states, 1)},
            "end_to_end": {**terminal, "failure_classes": _reason_counts(states, 2)},
            "repeat_reliability": {"product_selection": _reliability(states, "selection"), "end_to_end": _reliability(states, "terminal")},
            "error_recovery": recovery,
            "security_compliance": security,
            "cost": {"logical_question_invocations": len(cases) * trials, "discovery_batch_invocations": discovery_calls, "external_selector_invocations": selector_calls, "external_selector_network_trials": selector_network_trials, "recovery_top_level_invocations": recovery_calls, "production_http_requests": blocker.attempts, "socket_network_attempts": network.attempts, "elapsed_seconds": round(elapsed, 6)},
        },
    }
    result["security_hard_gate_passed"] = security["passed"]
    return result, _summary(result)


def run_evaluation(args: argparse.Namespace) -> tuple[dict[str, Any], str]:
    """Run an evaluation, enforcing protected-split accounting for all callers."""

    split = "development" if args.split == "dev" else args.split
    purpose = ensure_query_allowed(
        split,
        getattr(args, "purpose", None),
        bool(getattr(args, "allow_final_rerun", False)),
        LEDGER_PATH,
    )
    result, summary = _run_evaluation_unrecorded(args)
    if split in PROTECTED_SPLITS:
        _record, counts = append_query_record(
            result,
            purpose=str(purpose),
            allow_final_rerun=bool(getattr(args, "allow_final_rerun", False)),
            ledger_path=LEDGER_PATH,
        )
        summary += (
            f"\nCumulative {split} queries: {counts[split]}"
            f"\nCumulative protected queries: {counts['protected_total']}\n"
        )
    return result, summary


def _metric(result: Mapping[str, Any], path: Sequence[str]) -> Mapping[str, Any]:
    selected: Any = result
    for key in path:
        selected = selected[key]
    return selected


def compare_results(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    comparable = ("suite_version", "suite_hashes", "split", "case_count", "trials")
    if any(before.get(key) != after.get(key) for key in comparable):
        raise ValueError("results are not comparable: suite, split, case count, or trials differ")
    paths = {
        "product_selection": ("layers", "product_selection"),
        "parameter_fillability": ("layers", "parameter_fillability"),
        "end_to_end": ("layers", "end_to_end"),
        "selection_pass^4": ("layers", "repeat_reliability", "product_selection", "pass^4"),
        "terminal_pass^4": ("layers", "repeat_reliability", "end_to_end", "pass^4"),
        "error_recovery": ("layers", "error_recovery"),
    }
    layers = {}
    for name, path in paths.items():
        old, new = _metric(before, path), _metric(after, path)
        old_rate, new_rate = old.get("rate"), new.get("rate")
        layers[name] = {"before": dict(old), "after": dict(new), "rate_delta": None if old_rate is None or new_rate is None else round(new_rate - old_rate, 6)}
    before_security = before.get("layers", {}).get("security_compliance")
    after_security = after.get("layers", {}).get("security_compliance")
    return {
        "schema_version": COMPARE_SCHEMA_VERSION,
        "suite_version": before["suite_version"],
        "split": before["split"],
        "before_commit": before["subject"]["git_commit"],
        "after_commit": after["subject"]["git_commit"],
        "layers": layers,
        "security_compliance": {
            "before": dict(before_security) if isinstance(before_security, Mapping) else None,
            "after": dict(after_security) if isinstance(after_security, Mapping) else None,
        },
        "cost_delta": {key: round(after["layers"]["cost"][key] - before["layers"]["cost"][key], 6) for key in ("discovery_batch_invocations", "production_http_requests", "elapsed_seconds")},
    }


def _compare_summary(value: Mapping[str, Any]) -> str:
    rows = ["# Agent usability comparison", "", "| Layer | Before | After | Delta |", "| --- | ---: | ---: | ---: |"]
    for name, item in value["layers"].items():
        before, after, delta = item["before"].get("rate"), item["after"].get("rate"), item["rate_delta"]
        render = lambda number: "n/a" if number is None else f"{100 * number:.2f}%"
        rows.append(f"| {name} | {render(before)} | {render(after)} | {render(delta)} |")
    security = value.get("security_compliance", {})
    before_security = security.get("before") if isinstance(security, Mapping) else None
    after_security = security.get("after") if isinstance(security, Mapping) else None
    gate = lambda item: "n/a" if not isinstance(item, Mapping) else str(item.get("gate", "n/a")).upper()
    rows.extend(["", f"Security compliance hard gate: {gate(before_security)} -> {gate(after_security)}"])
    rows.append("")
    return "\n".join(rows)


def _write_outputs(output_dir: Path, stem: str, value: Mapping[str, Any], summary: str) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path, md_path = output_dir / f"{stem}.json", output_dir / f"{stem}.md"
    json_path.write_bytes(_json_bytes(value, pretty=True))
    md_path.write_text(summary, encoding="utf-8", newline="\n")
    return json_path, md_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser(
        "run",
        help=(
            "run one fixed suite without production HTTP; final is a single "
            "project-cycle closeout query"
        ),
    )
    run.add_argument(
        "--split",
        choices=("development", "dev", "holdout", "all", "final"),
        default="development",
        help=(
            "dev is an alias for development; all preserves the legacy "
            "development+holdout meaning; final is "
            "independent and should be queried once, only at project closeout"
        ),
    )
    run.add_argument("--holdout-key", help="independent key for holdout only")
    run.add_argument("--final-key", help="independent key for final only")
    run.add_argument(
        "--selector-plugin",
        help=(
            "Python file implementing gravity.agent-external-selector-response.v1; "
            "the evaluator supplies each question and the local agent catalog"
        ),
    )
    run.add_argument(
        "--selector-timeout",
        type=float,
        default=120.0,
        help="Maximum seconds for each external selector trial (default: 120)",
    )
    run.add_argument(
        "--purpose",
        help="required audit purpose for every holdout or final query",
    )
    run.add_argument(
        "--allow-final-rerun",
        action="store_true",
        help=(
            "override the default refusal after final was queried; the override "
            "is itself recorded in the versioned ledger"
        ),
    )
    run.add_argument("--label", default="unlabeled")
    run.add_argument("--output-dir", type=Path, default=ROOT / "tmp" / "agent-usability-results")
    compare = commands.add_parser("compare", help="compare two machine result files layer by layer")
    compare.add_argument("before", type=Path)
    compare.add_argument("after", type=Path)
    compare.add_argument("--output-dir", type=Path, default=ROOT / "tmp" / "agent-usability-results")
    verify = commands.add_parser(
        "verify-suite",
        help=(
            "verify public and sealed-file hashes plus optional holdout "
            "authentication; final is never decrypted by verification"
        ),
    )
    verify.add_argument("--holdout-key")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify-suite":
            manifest = _manifest()
            development = _development_cases(manifest)
            holdout = _holdout_cases(manifest, Path(args.holdout_key)) if args.holdout_key else None
            final_sealed = (SUITE_ROOT / "cases" / "final.sealed.json").read_bytes()
            final_hash_ok = (
                hashlib.sha256(final_sealed).hexdigest()
                == manifest["final_sealed_sha256"]
            )
            if not final_hash_ok:
                raise ValueError("sealed final hash does not match suite.json")
            print(json.dumps({"ok": True, "development_count": len(development), "holdout_count": None if holdout is None else len(holdout), "final_sealed_hash_verified": True}))
            return 0
        if args.command == "run":
            result, summary = run_evaluation(args)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            paths = _write_outputs(args.output_dir, f"result-{args.split}-{stamp}", result, summary)
        else:
            before = json.loads(args.before.read_text(encoding="utf-8"))
            after = json.loads(args.after.read_text(encoding="utf-8"))
            result = compare_results(before, after)
            summary = _compare_summary(result)
            paths = _write_outputs(args.output_dir, "comparison", result, summary)
        print(summary)
        print(f"machine_result={paths[0]}")
        print(f"human_summary={paths[1]}")
        return 0
    except Exception as error:
        print(f"agent usability evaluation failed: {type(error).__name__}: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
