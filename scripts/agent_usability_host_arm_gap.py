"""Read-only development measurement: recognizer misses vs host-catalog path.

Does not change the evaluator, suite, scorer, layers, or thresholds.
Does not read holdout/final keys or sealed files.
Uses development reliability trials; writes a compact JSON summary; no production HTTP.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
from collections import Counter
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_ROOT = Path(__file__).resolve().parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from agent_usability_eval import (  # noqa: E402
    BlockedTransport,
    NetworkGuard,
    _gap,
    load_cases,
    route_score,
)
from agent_usability_expectations import TARGETS_PATH  # noqa: E402


CHUNK = 32


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tmp" / "host-arm-gap.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    blocker, network = BlockedTransport(), NetworkGuard()
    with tempfile.TemporaryDirectory(prefix="gravity-host-arm-gap-") as cache, ExitStack() as stack:
        stack.enter_context(
            patch.dict(
                os.environ,
                {
                    "GRAVITY_CACHE_HOME": cache,
                    "LOCALAPPDATA": cache,
                    "XDG_CACHE_HOME": cache,
                },
            )
        )
        stack.enter_context(patch.object(socket.socket, "connect", network.block))
        stack.enter_context(patch("socket.create_connection", network.block))
        from gravity_sdk.agents.batch import capabilities_many
        from gravity_sdk.agents.host_catalog import host_product_catalog
        from gravity_sdk.agents.host_selection import resolve_host_product_selection
        from gravity_sdk.client import GravityInsightClient
        from gravity_sdk.errors import InputValidationError

        client = GravityInsightClient.from_env(transport=blocker)
        manifest, cases = load_cases("development", None)
        catalog = host_product_catalog(client)
        refs = {str(item["catalog_ref"]) for item in catalog["entries"]}
        targets = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
        selectors = targets["candidate_selectors"]

        recognizer_rows = _recognizer_rows(cases, client, capabilities_many)
        host_rows = []
        for case, rec in zip(cases, recognizer_rows):
            host_rows.append(
                _oracle_host_row(
                    case,
                    rec,
                    client,
                    catalog,
                    refs,
                    selectors,
                    resolve_host_product_selection,
                    InputValidationError,
                )
            )

    if blocker.attempts or network.attempts:
        raise RuntimeError("measurement attempted prohibited network access")

    payload = _summarize(cases, recognizer_rows, host_rows, catalog)
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["headline"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _recognizer_rows(
    cases: list[Mapping[str, Any]], client: Any, capabilities_many: Any
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for start in range(0, len(cases), CHUNK):
        chunk = cases[start : start + CHUNK]
        questions = [
            {"id": case["case_id"], "query": case["prompt"], "limit": 5}
            for case in chunk
        ]
        response = capabilities_many(questions, client=client)
        for case, item in zip(chunk, response.get("results", [])):
            result = item.get("result") if isinstance(item, Mapping) else None
            ok, reason, _card = route_score(case, result)
            rows.append(_row(case, result, ok, reason, arm="recognizer"))
    return rows


def _oracle_host_row(
    case: Mapping[str, Any],
    rec: Mapping[str, Any],
    client: Any,
    catalog: Mapping[str, Any],
    refs: set[str],
    selectors: Mapping[str, str],
    resolve_host_product_selection: Any,
    input_error: type[Exception],
) -> dict[str, Any]:
    expected = case["expected"]
    query = str(case["prompt"])
    chosen = _oracle_refs(case, selectors)
    missing = [ref for ref in chosen if ref not in refs]
    decision = (
        "abstained" if not chosen else "selected" if len(chosen) == 1 else "multiple_intents"
    )
    selection = {
        "schema_version": catalog["selection_schema_version"],
        "catalog_sha256": catalog["catalog_sha256"],
        "query": query,
        "decision": decision,
        "reason": {
            "summary": "oracle target identity from journey-targets",
            "needs_clarification": not chosen,
        },
        "candidates": [
            {
                "catalog_ref": ref,
                "reason": {
                    "goal_match": "registered journey target",
                    "boundary_check": "neighbor excluded by target registry",
                },
            }
            for ref in chosen
        ],
    }
    result = None
    error = None
    try:
        result = resolve_host_product_selection(query, selection, client)
    except input_error as exc:
        error = {"field": getattr(exc, "field", None), "message": str(exc)[:240]}
    ok, reason, _card = route_score(case, result)
    row = _row(case, result, ok, reason, arm="host_oracle")
    row["oracle_refs"] = chosen
    row["oracle_refs_missing_from_catalog"] = missing
    row["oracle_error"] = error
    row["recognizer_ok"] = rec["ok"]
    row["recognizer_reason"] = rec["reason"]
    return row


_ROUTE_REFS = {
    "event": "analysis.query.spec:event",
    "funnel": "analysis.query.spec:funnel",
    "retention": "analysis.query.spec:retention",
    "property": "analysis.query.spec:property",
    "scatter": "analysis.query.spec:scatter",
    "period_compare": "analysis.query.spec",
    "segment_evaluate": "analysis.segment.rule.spec",
    "analysis_context": "composite:analysis_context",
    "app_governance": "composite:app_snapshot",
    "attribution_settings": "composite:attribution_snapshot",
    "user_journey": "composite:user_journey",
    "business_pulse": "composite:business_pulse",
    "company_usage": "composite:company_usage",
    "custom_audience": "composite:custom_audience",
    "material_performance": "composite:material_performance",
    "order_directory": "composite:order_directory",
    "order_split_trace": "composite:order_split_trace",
    "monetization_detail": "composite:monetization_detail",
    "workspace_sql": "gap:WORKSPACE_SQL_PRODUCT_NOT_CONFIGURED",
    "dashboard_snapshot": "composite:dashboard_snapshot",
    "dashboard_analysis": "composite:dashboard_analysis",
    "saved_analysis": "composite:saved_analysis",
    "analysis_template": "composite:analysis_template",
    "segment_snapshot": "composite:segment_snapshot",
    "segment_members": "composite:segment_members",
    "multidim": "composite:multidim",
    "promotion_performance": "composite:promotion_performance",
    "bilibili_performance": "composite:bilibili_account_performance",
    "advertiser_profile": "composite:advertiser_profile",
    "title_package": "composite:title_package",
    "metadata_search": "metadata:search",
    "table_lineage": "metadata:table_lineage",
    "material_export": "export.material.report.start",
    "analysis_default_dictionary": "composite:analysis_default_dictionary",
    "realtime_event_catalog": "composite:realtime_event_catalog",
    "app_catalog": "app.list",
    "app_public_info": "app.app_info.get",
    "monetization_aggregate": "report.get.query",
    "report_directory": "composite:report_directory",
    "report_subscriptions": "composite:report_subscriptions",
    "attribution_performance": "composite:attribution_performance",
    "attribution_user_detail": "composite:attribution_user_detail",
    "material_asset": "material.asset.fetch",
}


def _oracle_refs(case: Mapping[str, Any], selectors: Mapping[str, str]) -> list[str]:
    expected = case["expected"]
    gap = expected.get("gap_code")
    if gap == "MULTIPLE_INTENTS":
        wanted = expected.get("candidate_selectors") or {}
        refs: list[str] = []
        for journey_id in expected.get("journey_ids") or ():
            selector = wanted.get(journey_id)
            if selector:
                refs.append(str(selector))
            else:
                target_gap = _journey_gap(str(journey_id))
                if target_gap:
                    refs.append(f"gap:{target_gap}")
        return refs
    if isinstance(gap, str):
        return [f"gap:{gap}"]
    journey_id = str(case.get("journey_id") or "")
    selector = selectors.get(journey_id)
    if selector:
        return [str(selector)]
    route = str(expected.get("route_key") or "")
    mapped = _ROUTE_REFS.get(route)
    return [mapped] if mapped else []


def _journey_gap(journey_id: str) -> str | None:
    from agent_usability_expectations import TARGETS_PATH

    targets = json.loads(TARGETS_PATH.read_text(encoding="utf-8"))
    gap = targets["journeys"].get(journey_id, {}).get("gap")
    if isinstance(gap, Mapping):
        code = gap.get("gap_code")
        return str(code) if code else None
    return None


def _row(
    case: Mapping[str, Any],
    result: Mapping[str, Any] | None,
    ok: bool,
    reason: str,
    *,
    arm: str,
) -> dict[str, Any]:
    prompt = str(case["prompt"])
    expected = case["expected"]
    return {
        "arm": arm,
        "case_id": case["case_id"],
        "journey_id": case.get("journey_id"),
        "family": case.get("family"),
        "language": case.get("language"),
        "prompt_chars": len(prompt),
        "prompt_preview": " ".join(prompt.split())[:160],
        "expected_route": expected.get("route_key"),
        "expected_gap": expected.get("gap_code"),
        "ok": ok,
        "reason": reason,
        "status": None if result is None else result.get("status"),
        "first_selector": _first_selector(result),
        "gap_codes": _gap_codes(result),
        "gap_candidates": _gap_candidates(result),
        "unranked": _gap(result or {}, "UNRANKED_OPERATIONS") is not None,
    }


def _first_selector(result: Mapping[str, Any] | None) -> str | None:
    if not isinstance(result, Mapping):
        return None
    candidates = result.get("candidates")
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], Mapping):
        return str(candidates[0].get("selector") or "") or None
    return None


def _gap_codes(result: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(result, Mapping):
        return []
    gaps = result.get("capability_gaps")
    if not isinstance(gaps, list):
        return []
    return [str(item.get("code")) for item in gaps if isinstance(item, Mapping)]


def _gap_candidates(result: Mapping[str, Any] | None) -> list[str]:
    if not isinstance(result, Mapping):
        return []
    gaps = result.get("capability_gaps")
    if not isinstance(gaps, list):
        return []
    for item in gaps:
        if not isinstance(item, Mapping):
            continue
        selected = item.get("candidate_selectors")
        if isinstance(selected, list):
            return [str(value) for value in selected]
    return []


def _summarize(
    cases: list[Mapping[str, Any]],
    recognizer_rows: list[dict[str, Any]],
    host_rows: list[dict[str, Any]],
    catalog: Mapping[str, Any],
) -> dict[str, Any]:
    rec_ok = sum(row["ok"] for row in recognizer_rows)
    host_ok = sum(row["ok"] for row in host_rows)
    rec_fail = [row for row in recognizer_rows if not row["ok"]]
    host_fail = [row for row in host_rows if not row["ok"]]
    host_wins = [
        {
            "case_id": host["case_id"],
            "journey_id": host["journey_id"],
            "family": host["family"],
            "prompt_chars": host["prompt_chars"],
            "prompt_preview": host["prompt_preview"],
            "recognizer_reason": rec["reason"],
            "recognizer_first_selector": rec["first_selector"],
            "recognizer_gap_codes": rec["gap_codes"],
            "recognizer_unranked": rec["unranked"],
            "host_reason": host["reason"],
            "host_first_selector": host["first_selector"],
            "host_gap_codes": host["gap_codes"],
            "oracle_refs": host["oracle_refs"],
            "class": _recognizer_miss_class(rec),
        }
        for rec, host in zip(recognizer_rows, host_rows)
        if (not rec["ok"]) and host["ok"]
    ]
    both_fail = [
        {
            "case_id": host["case_id"],
            "journey_id": host["journey_id"],
            "family": host["family"],
            "prompt_preview": host["prompt_preview"],
            "recognizer_reason": rec["reason"],
            "host_reason": host["reason"],
            "oracle_refs": host["oracle_refs"],
            "oracle_error": host["oracle_error"],
            "host_gap_codes": host["gap_codes"],
            "host_gap_candidates": host["gap_candidates"],
        }
        for rec, host in zip(recognizer_rows, host_rows)
        if (not rec["ok"]) and (not host["ok"])
    ]
    host_only_fail = [
        {
            "case_id": host["case_id"],
            "journey_id": host["journey_id"],
            "family": host["family"],
            "prompt_preview": host["prompt_preview"],
            "recognizer_reason": rec["reason"],
            "host_reason": host["reason"],
            "oracle_refs": host["oracle_refs"],
            "oracle_error": host["oracle_error"],
            "host_gap_codes": host["gap_codes"],
            "host_gap_candidates": host["gap_candidates"],
        }
        for rec, host in zip(recognizer_rows, host_rows)
        if rec["ok"] and (not host["ok"])
    ]
    return {
        "split": "development",
        "case_count": len(cases),
        "catalog_entry_count": len(catalog["entries"]),
        "catalog_sha256": catalog["catalog_sha256"],
        "headline": {
            "recognizer_passed": rec_ok,
            "recognizer_total": len(recognizer_rows),
            "host_oracle_passed": host_ok,
            "host_oracle_total": len(host_rows),
            "host_wins": len(host_wins),
            "both_fail": len(both_fail),
            "host_only_fail": len(host_only_fail),
            "recognizer_failure_classes": dict(
                sorted(Counter(row["reason"] for row in rec_fail).items())
            ),
            "host_oracle_failure_classes": dict(
                sorted(Counter(row["reason"] for row in host_fail).items())
            ),
            "host_win_classes": dict(
                sorted(Counter(item["class"] for item in host_wins).items())
            ),
        },
        "host_wins": host_wins,
        "both_fail": both_fail,
        "host_only_fail": host_only_fail,
        "recognizer_failures": rec_fail,
        "host_failures": host_fail,
    }


def _recognizer_miss_class(row: Mapping[str, Any]) -> str:
    reason = str(row["reason"])
    family = str(row.get("family") or "")
    if row.get("unranked"):
        return "unranked_raw_operations"
    if reason == "wrong_product" and family == "multiple_intents":
        return "multi_intent_collapsed_to_one_product"
    if reason == "multiple_intents_missing":
        return "multi_intent_not_raised"
    if reason == "wrong_intent_candidates":
        return "multi_intent_wrong_set"
    if reason == "no_candidate":
        if family == "first_turn_followup" or (row.get("prompt_chars") or 0) <= 16:
            return "short_or_first_turn_no_candidate"
        if family == "typo_or_pinyin":
            return "typo_or_pinyin_no_candidate"
        if family == "indirect_business_goal":
            return "indirect_goal_no_candidate"
        return "no_candidate_other"
    if reason == "wrong_product":
        if family == "colloquial_ellipsis":
            return "colloquial_wrong_product"
        if family == "indirect_business_goal":
            return "indirect_goal_wrong_product"
        return "lexical_or_adjacent_wrong_product"
    if reason == "wrong_gap":
        return "wrong_or_missing_gap"
    return reason


DEFAULT_DISPATCH_SCHEMA = "gravity.agent-usability-default-dispatch.v2"


def _source_reexecuted_host_selection(default_symbol: str) -> Any:
    """Execute production host-selection source with one default assignment changed."""

    import ast
    import importlib
    import types

    if default_symbol not in {"RECOGNIZER_ROUTING_MODE", "HOST_ROUTING_MODE"}:
        raise ValueError("default_symbol must name one registered routing arm")
    current = importlib.import_module("gravity_sdk.agents.host_selection")
    source_path = Path(current.__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    assignments = 0
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "DEFAULT_ROUTING_MODE"
            for target in node.targets
        ):
            node.value = ast.copy_location(
                ast.Name(id=default_symbol, ctx=ast.Load()), node.value
            )
            assignments += 1
    if assignments != 1:
        raise RuntimeError(
            "host-selection source must have exactly one default routing assignment"
        )
    ast.fix_missing_locations(tree)
    module = types.ModuleType("gravity_sdk.agents._host_selection_counterfactual")
    module.__file__ = str(source_path)
    module.__package__ = "gravity_sdk.agents"
    exec(compile(tree, str(source_path), "exec"), module.__dict__)
    return module


@contextmanager
def _installed_host_selection(module: Any) -> Any:
    """Install one fully executed routing module for dynamic public entry imports."""

    import importlib

    package = importlib.import_module("gravity_sdk.agents")
    module_name = "gravity_sdk.agents.host_selection"
    previous_module = sys.modules[module_name]
    previous_attribute = package.host_selection
    sys.modules[module_name] = module
    package.host_selection = module
    try:
        yield
    finally:
        sys.modules[module_name] = previous_module
        package.host_selection = previous_attribute


def measure_default_dispatch(
    plugin_path: Path,
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Score two source defaults against the same development selections."""

    import hashlib

    from agent_usability_external_selector import (
        _blind_questions,
        _catalog,
        _invoke_plugin,
        _selection_result,
    )
    from agent_usability_eval import _selection_identity

    manifest, cases = load_cases("development", None)
    trials = int(manifest["trials"])
    if trials < 1:
        raise ValueError("development reliability trials must be at least one")
    blocker, network = BlockedTransport(), NetworkGuard()
    with tempfile.TemporaryDirectory(
        prefix="gravity-default-dispatch-"
    ) as cache, ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {
            "GRAVITY_CACHE_HOME": cache,
            "LOCALAPPDATA": cache,
            "XDG_CACHE_HOME": cache,
        }))
        stack.enter_context(patch("socket.socket.connect", network.block))
        stack.enter_context(patch("socket.create_connection", network.block))
        from gravity_sdk.agents import host_selection as checked_in
        from gravity_sdk.client import GravityInsightClient

        if checked_in.DEFAULT_ROUTING_MODE != checked_in.RECOGNIZER_ROUTING_MODE:
            raise RuntimeError("checked-in default must remain the recognizer")
        counterfactual = _source_reexecuted_host_selection("HOST_ROUTING_MODE")
        client = GravityInsightClient.from_env(transport=blocker)
        selector_catalog, runtime_catalog = _catalog(client)
        questions, aliases, blind_receipt = _blind_questions(cases)
        states = {
            policy: {
                str(case["case_id"]): {"selection": [], "selected": []}
                for case in cases
            }
            for policy in ("checked_in", "counterfactual")
        }
        reasons = {"checked_in": Counter(), "counterfactual": Counter()}
        routing_modes = {"checked_in": Counter(), "counterfactual": Counter()}
        per_trial_scores = {"checked_in": [], "counterfactual": []}
        receipts: list[Mapping[str, Any]] = []
        modules = {
            "checked_in": checked_in,
            "counterfactual": counterfactual,
        }
        plugin_sha256 = hashlib.sha256(plugin_path.read_bytes()).hexdigest()
        for trial in range(1, trials + 1):
            selected, metadata = _invoke_plugin(
                plugin_path,
                selector_catalog,
                questions,
                timeout_seconds=timeout_seconds,
            )
            receipts.append(metadata)
            selected = {
                str(case["case_id"]): selected[aliases[str(case["case_id"])]]
                for case in cases
            }
            trial_reasons = {
                "checked_in": Counter(), "counterfactual": Counter()
            }
            trial_routing_modes = {
                "checked_in": Counter(), "counterfactual": Counter()
            }
            trial_outcomes = {"checked_in": [], "counterfactual": []}
            for policy, module in modules.items():
                with _installed_host_selection(module):
                    for case in cases:
                        result = _selection_result(
                            case,
                            selected[str(case["case_id"])],
                            runtime_catalog,
                            client,
                            metadata,
                            plugin_sha256=plugin_sha256,
                            production_http_requests=lambda: blocker.attempts,
                            dispatch_mode="default",
                        )
                        ok, reason, _card = route_score(case, result)
                        state = states[policy][str(case["case_id"])]
                        state["selection"].append(ok)
                        runtime_result = dict(result)
                        runtime_result.pop("selected_selectors", None)
                        state["selected"].append(
                            _selection_identity(runtime_result)
                        )
                        trial_outcomes[policy].append(ok)
                        trial_reasons[policy][reason] += 1
                        trial_routing_modes[policy][
                            str(result.get("routing_mode"))
                        ] += 1
                        reasons[policy][reason] += 1
                        routing_modes[policy][str(result.get("routing_mode"))] += 1
                passed = sum(trial_outcomes[policy])
                per_trial_scores[policy].append({
                    "trial": trial,
                    "passed": passed,
                    "total": len(cases),
                    "rate": _default_dispatch_rate(passed, len(cases)),
                    "routing_mode_counts": dict(sorted(
                        trial_routing_modes[policy].items()
                    )),
                    "failure_classes": dict(sorted(
                        trial_reasons[policy].items()
                    )),
                })

    if blocker.attempts or network.attempts:
        raise RuntimeError("measurement attempted prohibited Gravity network access")
    request_hashes = [receipt.get("request_sha256") for receipt in receipts]
    if not all(isinstance(value, str) and value for value in request_hashes):
        raise RuntimeError(
            "default-dispatch evidence requires one verified request SHA-256 per trial"
        )
    if len(set(request_hashes)) != 1:
        raise RuntimeError("default-dispatch selector request changed across trials")
    scores: dict[str, Any] = {}
    for policy in ("checked_in", "counterfactual"):
        scores[policy] = _default_dispatch_score(
            states[policy],
            trials=trials,
            per_trial_scores=per_trial_scores[policy],
            routing_mode_counts=routing_modes[policy],
            failure_classes=reasons[policy],
        )
    pass1_difference = (
        scores["counterfactual"]["pass^1"]["passed"]
        - scores["checked_in"]["pass^1"]["passed"]
    )
    passn_difference = (
        scores["counterfactual"]["pass^N"]["passed"]
        - scores["checked_in"]["pass^N"]["passed"]
    )
    multiple_intent_cases = [
        case for case in cases
        if case["expected"].get("gap_code") == "MULTIPLE_INTENTS"
    ]
    gap_identity_case_ids = sorted(
        str(case["case_id"])
        for case in multiple_intent_cases
        if any(
            str(selector).startswith("gap:")
            for selector in case["expected"].get(
                "candidate_selectors", {}
            ).values()
        )
    )
    return {
        "schema_version": DEFAULT_DISPATCH_SCHEMA,
        "evidence_scope": {
            "classification": "development_counterfactual_prediction",
            "is_holdout_result": False,
            "is_post_flip_measurement": False,
            "checked_in_default_changed": False,
            "limitations": [
                "This development result does not establish protected-split generalization.",
                "Protected legacy ambiguous prompts do not carry development's explicit multi-journey expectations.",
                "The selector subprocess reports its own network activity; the parent cannot independently instrument it.",
            ],
        },
        "suite_version": manifest["suite_version"],
        "split": "development",
        "case_count": len(cases),
        "trials": trials,
        "reliability_protocol": {
            "trials_source": "evals/agent_usability/suite.json#trials",
            "N": trials,
            "pass^1_definition": "cases correct on the first trial",
            "pass^N_definition": "cases correct on every one of N trials",
            "instability_definition": "case IDs whose exact runtime selection identity differs across trials",
        },
        "protected_split_comparability": {
            "same_multi_intent_scoring_contract": False,
            "development_explicit_multi_intent_case_count": len(
                multiple_intent_cases
            ),
            "development_gap_identity_case_ids": gap_identity_case_ids,
            "development_gap_identity_score_effect_bound": {
                "max_cases_per_trial": len(gap_identity_case_ids),
                "max_percentage_points": round(
                    100 * len(gap_identity_case_ids) / len(cases), 6
                ),
                "observed_cases_helped": None,
            },
            "protected_legacy_behavior": (
                "cases without an explicit multiple-intent declaration retain "
                "single-journey scoring"
            ),
            "protected_ambiguous_case_count": None,
            "protected_score_impact": None,
            "unquantified_reason": (
                "Determining protected ambiguous cases or score impact would "
                "require opening a protected payload; this measurement did not."
            ),
        },
        "selector_plugin_sha256": plugin_sha256,
        "selector_request_sha256": request_hashes[0],
        "selector_request_sha256_by_trial": request_hashes,
        "blind_order_seed_sha256": blind_receipt["order_seed_sha256"],
        "selector_network_reported_trials": sum(
            receipt.get("network_called") is True for receipt in receipts
        ),
        "checked_in_default": checked_in.DEFAULT_ROUTING_MODE,
        "counterfactual_default": counterfactual.DEFAULT_ROUTING_MODE,
        "scores": scores,
        "score_differences": {
            "counterfactual_minus_checked_in_pass^1": pass1_difference,
            "counterfactual_minus_checked_in_pass^N": passn_difference,
        },
        "scores_differ": passn_difference != 0,
    }


def _default_dispatch_rate(passed: int, total: int) -> float | None:
    return round(passed / total, 6) if total else None


def _default_dispatch_score(
    states: Mapping[str, Mapping[str, list[Any]]],
    *,
    trials: int,
    per_trial_scores: list[dict[str, Any]],
    routing_mode_counts: Counter[str],
    failure_classes: Counter[str],
) -> dict[str, Any]:
    pass1 = sum(state["selection"][0] is True for state in states.values())
    passn = sum(
        all(value is True for value in state["selection"])
        for state in states.values()
    )
    unstable = sorted(
        case_id for case_id, state in states.items()
        if len(set(state["selected"])) > 1
    )
    return {
        "pass^1": {
            "passed": pass1,
            "total": len(states),
            "rate": _default_dispatch_rate(pass1, len(states)),
        },
        "pass^N": {
            "N": trials,
            "passed": passn,
            "total": len(states),
            "rate": _default_dispatch_rate(passn, len(states)),
        },
        "unstable_tasks": len(unstable),
        "unstable_case_ids": unstable,
        "unstable_selections": {
            case_id: [
                list(value) for value in sorted(set(states[case_id]["selected"]))
            ]
            for case_id in unstable
        },
        "routing_mode_counts": dict(sorted(routing_mode_counts.items())),
        "failure_classes": dict(sorted(failure_classes.items())),
        "per_trial_scores": per_trial_scores,
    }


def default_dispatch_parser() -> Any:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Measure public default routing on the visible development suite; "
            "there is intentionally no split option."
        )
    )
    parser.add_argument("--selector-plugin", type=Path, required=True)
    parser.add_argument("--selector-timeout", type=float, default=300.0)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "tmp" / "agent-usability-default-dispatch.json",
    )
    return parser


def default_dispatch_main(argv: list[str] | None = None) -> int:
    args = default_dispatch_parser().parse_args(argv)
    try:
        payload = measure_default_dispatch(
            args.selector_plugin.resolve(),
            timeout_seconds=float(args.selector_timeout),
        )
    except Exception as error:
        print(
            f"default-dispatch measurement failed: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "checked_in_default": payload["checked_in_default"],
        "checked_in_score": payload["scores"]["checked_in"],
        "counterfactual_default": payload["counterfactual_default"],
        "counterfactual_score": payload["scores"]["counterfactual"],
        "scores_differ": payload["scores_differ"],
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "default-dispatch":
        raise SystemExit(default_dispatch_main(sys.argv[2:]))
    raise SystemExit(main())
