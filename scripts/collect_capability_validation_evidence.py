"""Collect principal-scoped Capability Validation from real read executions."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from gravity_insight.capability_contract import _operations, capability_contracts
from gravity_insight.capability_trust import CapabilityTrustService
from gravity_insight.capability_validation import CapabilityValidationStore
from gravity_insight.cache import bypass_metadata_cache
from gravity_insight.client import GravityInsightClient
from gravity_insight.http_runtime import GravityHttpRuntime, _build_session
from gravity_insight.probe_inputs import resolve_probe_inputs
from gravity_insight.receipt import count_http_requests
from gravity_insight.result_audit import (
    error_receipt_references,
    result_receipt_references,
)
from gravity_insight.result_output import write_rendered_result
from gravity_insight.runtime_scope import resolve_env_path, scope_workspace
from gravity_insight.workspace import load_workspace

from capability_validation_evidence_support import (
    MAX_PRODUCTION_REQUESTS,
    RUN_SCHEMA_VERSION,
    BudgetedSession,
    RequestBudgetExceeded,
    bind_probe_app,
    error_outcome,
    inventory,
    mark_budget_exhausted,
    mark_terminal_stop,
    ranked_candidates,
    resolve_receipts,
    result_outcome,
    static_outcomes,
    timestamp,
    terminal_stop_category,
    trust_counts,
    validation_from_execution,
)


def collect(
    *,
    app_id: str,
    request_budget: int,
    prior_requests: int = 0,
    selectors: Sequence[str] = (),
) -> dict[str, Any]:
    _validate_arguments(app_id, request_budget, prior_requests)
    started_at = datetime.now(timezone.utc)
    base_workspace = load_workspace()
    env_path, isolated = resolve_env_path()
    scoped_workspace = scope_workspace(
        base_workspace, env_path, isolated=isolated
    )
    session = BudgetedSession(_build_session(), request_budget - prior_requests)
    runtime = GravityHttpRuntime(
        env_path=env_path,
        session=session,
        attempts=1,
        receipt_root=scoped_workspace.state_root,
        isolated=isolated,
    )
    client = GravityInsightClient.from_env(
        runtime=runtime, env_path=env_path, attempts=1
    )
    bypass_metadata_cache(client, True)
    artifacts = _artifacts()
    selected_set = {str(value) for value in selectors if str(value)}
    outcomes = static_outcomes(artifacts)
    candidates = ranked_candidates(artifacts, selected_set)
    validations: list[dict[str, Any]] = []
    with count_http_requests() as counter:
        _execute_candidates(
            candidates,
            outcomes,
            validations,
            client=client,
            state_root=scoped_workspace.state_root,
            app_id=app_id,
            session=session,
            prior_requests=prior_requests,
            request_budget=request_budget,
        )
        counter_count = counter.count
    _require_unchanged_scope(base_workspace, scoped_workspace.state_root)
    store = CapabilityValidationStore(
        scoped_workspace.state_root, scope_bound=True
    )
    if validations:
        store.upsert(validations)
    finished_at = datetime.now(timezone.utc)
    report = _run_report(
        started_at=started_at,
        finished_at=finished_at,
        app_id=app_id,
        request_budget=request_budget,
        prior_requests=prior_requests,
        requests_sent=session.sent,
        counter_count=counter_count,
        candidates=candidates,
        validations=validations,
        store=store,
        outcomes=outcomes,
    )
    _write_report(scoped_workspace.state_root, report, finished_at)
    return _summary(report)


def summarize() -> dict[str, Any]:
    env_path, isolated = resolve_env_path()
    workspace = scope_workspace(load_workspace(), env_path, isolated=isolated)
    run_root = (
        workspace.state_root / "agent-runtime" / "capability-validation-runs"
    )
    paths = sorted(run_root.glob("*.json"))
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    request_total = 0
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("schema_version") != RUN_SCHEMA_VERSION:
            continue
        request_total = max(
            request_total, int(value.get("production_requests_total", 0))
        )
        for outcome in value.get("outcomes", []):
            key = str(outcome["identity_kind"]), str(outcome["selector"])
            latest[key] = _normalized_final_outcome(outcome)
    unresolved = [
        latest[key]
        for key in sorted(latest)
        if latest[key]["category"] != "validated"
    ]
    result = {
        "schema_version": "gravity.capability-validation-summary.v1",
        "generated_at": timestamp(datetime.now(timezone.utc)),
        "source_run_count": len(paths),
        "production_requests_total": request_total,
        "outcome_counts": dict(
            sorted(Counter(item["category"] for item in latest.values()).items())
        ),
        "trust_counts": trust_counts(
            CapabilityValidationStore(
                workspace.state_root, scope_bound=True
            )
        ),
        "unresolved": unresolved,
        "network_called": False,
    }
    target = (
        workspace.state_root
        / "agent-runtime"
        / "capability-validation-summary.v1.json"
    )
    write_rendered_result(
        str(target),
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return {
        key: result[key]
        for key in (
            "source_run_count",
            "production_requests_total",
            "outcome_counts",
            "trust_counts",
            "network_called",
        )
    }


def _normalized_final_outcome(value: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(value)
    reasons = set(str(item) for item in result.get("reason_codes", []))
    if "EXECUTION_RESPONSE_DRIFT" in reasons:
        result["category"] = "response_contract_drift"
    return result


def _execute_candidates(
    candidates: Sequence[Mapping[str, Any]],
    outcomes: dict[tuple[str, str], dict[str, Any]],
    validations: list[dict[str, Any]],
    **context: Any,
) -> None:
    client = context["client"]
    session = context["session"]
    for artifact in candidates:
        if context["prior_requests"] + session.sent >= context["request_budget"]:
            mark_budget_exhausted(outcomes, candidates, artifact)
            break
        selector = str(artifact["contract"]["selector"])
        operation = _operations()[selector]
        before = session.sent
        operation_started = datetime.now(timezone.utc)
        result: Mapping[str, Any] | None = None
        error: BaseException | None = None
        try:
            raw = bind_probe_app(
                dict(operation.live_probe.inputs), context["app_id"]
            )
            inputs = resolve_probe_inputs(client, raw, operation_id=selector)
            result = client.read(selector, inputs)
        except Exception as caught:
            error = caught
        observed_at = datetime.now(timezone.utc)
        references = (
            error_receipt_references(error)
            if error is not None
            else result_receipt_references(result)
        )
        receipts = resolve_receipts(context["state_root"], references)
        if error is not None:
            outcomes[("operation", selector)] = error_outcome(
                selector, error, session.sent - before, receipts
            )
            if isinstance(error, RequestBudgetExceeded):
                mark_budget_exhausted(outcomes, candidates, artifact)
                break
            stop = terminal_stop_category(error=error)
            if stop is not None:
                mark_terminal_stop(outcomes, candidates, artifact, stop)
                break
            continue
        assert result is not None
        validation, reasons = validation_from_execution(
            artifact,
            result,
            receipts,
            started_at=operation_started,
            observed_at=observed_at,
        )
        if validation is not None:
            _require_stable(validation, selector)
            validations.append(validation)
        outcomes[("operation", selector)] = result_outcome(
            selector,
            result,
            session.sent - before,
            receipts,
            validation is not None,
            reasons,
        )
        stop = terminal_stop_category(result=result)
        if stop is not None:
            mark_terminal_stop(outcomes, candidates, artifact, stop)
            break


def _require_stable(validation: Mapping[str, Any], selector: str) -> None:
    empty = CapabilityValidationStore(values=[])
    result = CapabilityTrustService(empty).validate(validation)
    if result["trust_status"] != "stable":
        raise RuntimeError(f"qualified validation did not evaluate stable: {selector}")


def _run_report(**values: Any) -> dict[str, Any]:
    outcomes = [values["outcomes"][key] for key in sorted(values["outcomes"])]
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "status": "complete",
        "started_at": timestamp(values["started_at"]),
        "finished_at": timestamp(values["finished_at"]),
        "app_scope_sha256": hashlib.sha256(
            values["app_id"].encode("utf-8")
        ).hexdigest(),
        "request_budget": values["request_budget"],
        "prior_requests": values["prior_requests"],
        "production_requests_sent": values["requests_sent"],
        "production_requests_total": values["prior_requests"] + values["requests_sent"],
        "runtime_request_counter": values["counter_count"],
        "attempts": 1,
        "candidate_operations": len(values["candidates"]),
        "validations_recorded": len(values["validations"]),
        "validation_store_count": len(values["store"].list()),
        "outcome_counts": dict(
            sorted(Counter(item["category"] for item in outcomes).items())
        ),
        "trust_counts": trust_counts(values["store"]),
        "outcomes": outcomes,
        "network_called": values["requests_sent"] > 0,
        "privacy": {
            "credentials_persisted": False,
            "request_values_persisted": False,
            "response_values_persisted": False,
            "raw_rows_persisted": False,
        },
    }


def _write_report(state_root: Any, report: Mapping[str, Any], finished_at: datetime) -> None:
    path = (
        state_root
        / "agent-runtime"
        / "capability-validation-runs"
        / f"{finished_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    write_rendered_result(
        str(path),
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _summary(report: Mapping[str, Any]) -> dict[str, Any]:
    fields = (
        "status", "request_budget", "prior_requests",
        "production_requests_sent", "production_requests_total",
        "runtime_request_counter", "candidate_operations",
        "validations_recorded", "validation_store_count", "outcome_counts",
        "trust_counts", "network_called",
    )
    return {field: report[field] for field in fields}


def _artifacts() -> dict[tuple[str, str], Mapping[str, Any]]:
    return {
        (
            str(item["contract"]["identity_kind"]),
            str(item["contract"]["selector"]),
        ): item
        for item in capability_contracts()
    }


def _require_unchanged_scope(base_workspace: Any, expected: Any) -> None:
    env_path, isolated = resolve_env_path()
    current = scope_workspace(base_workspace, env_path, isolated=isolated)
    if current.state_root != expected:
        raise RuntimeError(
            "credential generation changed during collection; evidence was not published"
        )


def _validate_arguments(app_id: str, budget: int, prior: int) -> None:
    if not app_id.isdigit() or int(app_id) <= 0:
        raise ValueError("app-id must be a positive integer")
    if (
        type(budget) is not int
        or not 1 <= budget <= MAX_PRODUCTION_REQUESTS
        or type(prior) is not int
        or not 0 <= prior <= budget
    ):
        raise ValueError("request accounting is outside the governed budget")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Collect Capability Trust and Data Quality evidence from governed reads."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inventory", help="Classify contracts without network I/O.")
    subparsers.add_parser(
        "summarize", help="Merge current scoped run receipts without network I/O."
    )
    runner = subparsers.add_parser(
        "collect", help="Execute registered read probes and publish qualified Validation."
    )
    runner.add_argument("--app-id", required=True)
    runner.add_argument("--request-budget", type=int, default=480)
    runner.add_argument("--prior-requests", type=int, default=0)
    runner.add_argument("--selector", action="append", default=[])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "inventory":
        value = inventory()
    elif args.command == "summarize":
        value = summarize()
    else:
        value = collect(
            app_id=str(args.app_id),
            request_budget=args.request_budget,
            prior_requests=args.prior_requests,
            selectors=args.selector,
        )
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
