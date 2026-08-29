"""Generate the value-free R14-C Direct/Plan equivalence artifact."""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from gravity_sdk.analysis_query_execution_variant import (
    execute_fixed_analysis_query_event_variant,
)
from gravity_sdk.execution_variant_characterization import (
    build_execution_variant_characterization,
    execution_evidence,
)
from gravity_sdk.execution_variant_contract import (
    DIRECT_VARIANT_URI,
    PLAN_VARIANT_URI,
    REFERENCE_JOURNEY,
    product_reference,
)
from gravity_sdk.plan import AdapterContext
from gravity_sdk.sdk import GravitySDK
from gravity_sdk.workspace import load_workspace


ROOT = Path(__file__).resolve().parents[1]
TARGET = (
    ROOT
    / "src"
    / "gravity_sdk"
    / "contracts"
    / "execution-variants"
    / "analysis-query-event-direct-plan-v1.json"
)
PRIVATE_EVENT = "private-characterization-event"
PRIVATE_ROW = "private-characterization-row"
_OPERATION = "analysis.event.query"
_FETCHED_AT = "2026-08-24T00:00:00Z"
_QUERY_ID = "1787554279563Y7jyuoWZwFBto1tlFsR"


class _FixtureInsight:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.reads: list[dict[str, Any]] = []

    @staticmethod
    def validate(_operation_id: str, _inputs: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "status": "valid"}

    @staticmethod
    def schema(_operation_id: str) -> dict[str, Any]:
        return {"response_projection": {"data_keys": ["list"]}}

    def read(self, operation_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        self.reads.append(
            {"operation_id": operation_id, "inputs": copy.deepcopy(dict(inputs))}
        )
        return copy.deepcopy(self.result)


def build_artifact() -> dict[str, Any]:
    workspace = load_workspace(ROOT / "examples" / "workspace")
    request = _request()
    cases = []
    product = product_reference()
    for case_id in ("success", "empty", "contract_drift", "runtime_failure"):
        baseline = _execute(case_id, DIRECT_VARIANT_URI, request, workspace, product)
        candidate = _execute(case_id, PLAN_VARIANT_URI, request, workspace, product)
        cases.append(
            {"case_id": case_id, "baseline": baseline, "candidate": candidate}
        )
    artifact = build_execution_variant_characterization(cases)
    if artifact["equivalent"] is not True:
        raise RuntimeError("Execution Variant corpus is not equivalent")
    return artifact


def _execute(
    case_id: str,
    variant_uri: str,
    request: dict[str, Any],
    workspace: Any,
    product: dict[str, str],
) -> dict[str, Any]:
    raw = _result(case_id)
    insight = _FixtureInsight(raw)
    sdk = GravitySDK(insight=insight, workspace=workspace)
    context = AdapterContext(
        "variant", "variant", "composite", workspace, (), (), 5, 200
    )
    output = execute_fixed_analysis_query_event_variant(
        sdk, copy.deepcopy(request), context, variant_uri
    )
    return execution_evidence(
        input_value={"request": request, "compiled_trace": insight.reads},
        output_value=output,
        completeness={
            "declared": "unknown",
            "result": raw.get("completeness", "unknown"),
        },
        data_quality={
            "required": "pass",
            "result": raw.get("data_quality", "unknown"),
        },
        allowed_claims=["returned-event-metric-observation"],
        privacy_classification="user_level",
        freshness={"fetched_at": raw.get("fetched_at")},
        request_count=len(insight.reads),
        journey_value={
            "journey_id": REFERENCE_JOURNEY,
            "product_contract_digest": product["contract_digest"],
            "status": output.get("status"),
            "output": output,
        },
    )


def _request() -> dict[str, Any]:
    return {
        "name": "analysis_query",
        "kind": "event",
        "app": "demo",
        "spec": {
            "query_id": _QUERY_ID,
            "start": "2026-08-01",
            "end": "2026-08-02",
            "steps": [
                {
                    "event": PRIVATE_EVENT,
                    "metric": {
                        "field": "PresetAllCount",
                        "aggregation": "PresetAllCount",
                    },
                }
            ],
        },
    }


def _result(case_id: str) -> dict[str, Any]:
    base = {
        "schema_version": "gravity-insight.read.v1",
        "operation_id": _OPERATION,
        "fetched_at": _FETCHED_AT,
        "warnings": [],
        "request": {"private": PRIVATE_EVENT},
        "completeness": "complete",
        "data_quality": {"status": "pass"},
    }
    if case_id == "success":
        return {
            **base,
            "ok": True,
            "status": "success",
            "data": {"list": [{"value": PRIVATE_ROW}], "target_list": []},
        }
    if case_id == "empty":
        return {
            **base,
            "ok": True,
            "status": "empty",
            "data": {"list": [], "target_list": []},
        }
    error = {
        "category": "upstream",
        "code": (
            "CONTRACT_CHANGED"
            if case_id == "contract_drift"
            else "UPSTREAM_UNAVAILABLE"
        ),
        "message": "Fixture request failed without private diagnostics.",
        "next_action": "Stop on drift." if case_id == "contract_drift" else "Retry once.",
        "retryable": case_id != "contract_drift",
    }
    return {
        **base,
        "ok": False,
        "status": "contract_changed" if case_id == "contract_drift" else "error",
        "data": {"private": PRIVATE_ROW},
        "error": error,
    }


def _render(value: dict[str, Any]) -> str:
    rendered = json.dumps(
        value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False
    ) + "\n"
    for private in (
        PRIVATE_EVENT,
        PRIVATE_ROW,
        '"demo"',
        "2026-08-01",
        "PresetAllCount",
    ):
        if private in rendered:
            raise RuntimeError("Characterization artifact contains corpus values")
    return rendered


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    options = parser.parse_args()
    rendered = _render(build_artifact())
    if options.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.is_file() else ""
        if current != rendered:
            raise SystemExit("generated Execution Variant Characterization is stale")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(rendered, encoding="utf-8", newline="")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
