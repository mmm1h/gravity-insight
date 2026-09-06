"""Plan and transactionally apply conservative stable response drift declarations."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from gravity_insight.agent_runtime_contracts import validate_schema
from gravity_insight.compiler import ContractCompiler
from gravity_insight.contracts.envelope_obligations import (
    CompletenessState,
    DataCompleteness,
    DiagnosticEvidence,
    DiagnosticState,
    EnvelopeObligations,
    ExecutionState,
    ExecutionStatus,
    MutationCertainty,
    MutationState,
    SemanticState,
    SemanticValidity,
    serialize_envelope,
)
from gravity_insight.governance.stable_privacy import (
    REGISTRY_PATH,
    inspect_stable_response_privacy,
    render_registry,
)
from gravity_insight.models import OperationSpec
from gravity_insight.response_drift import normalize_response_drift

from .core import OPERATION_ROOT, REPO_ROOT, canonical_fingerprint, read_json, write_json
from .drift_declaration_policy import (
    apply_projection_edit,
    decide_observation,
    manual_decision,
    validate_combined_decisions,
)


PLAN_SCHEMA_VERSION = "gravity-insight.response-drift-declaration-plan.v1"
RUN_SCHEMA_VERSION = "gravity.capability-validation-run.v2"
RECOVERED_INPUT_VERSION = "recovered-drift-map.v0"
_RUN_SCHEMA = "capability-validation-run-v2.schema.json"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _evidence_observations(
    document: Mapping[str, Any], source: Path
) -> tuple[str, list[tuple[str, str, str]]]:
    schema_version = document.get("schema_version")
    if schema_version == RUN_SCHEMA_VERSION:
        validate_schema(document, _RUN_SCHEMA, "Capability Validation run")
        return RUN_SCHEMA_VERSION, _run_observations(document)
    if schema_version is not None:
        raise ValueError(f"unsupported drift evidence schema: {schema_version}")
    return RECOVERED_INPUT_VERSION, _recovered_observations(document, source)


def _run_observations(
    document: Mapping[str, Any],
) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for outcome in document.get("outcomes", ()):
        if not isinstance(outcome, Mapping) or outcome.get("identity_kind") != "operation":
            continue
        drift = outcome.get("response_drift")
        if drift is None:
            continue
        normalized = normalize_response_drift(drift)
        selector = str(outcome["selector"])
        rows.extend(
            (selector, str(item["path"]), str(item["observed_type"]))
            for item in normalized["fields"]
        )
    return rows


def _recovered_observations(
    document: Mapping[str, Any], source: Path
) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    if not document:
        raise ValueError(f"recovered drift input is empty: {source}")
    for selector, fields in document.items():
        if not isinstance(selector, str) or not isinstance(fields, Mapping):
            raise ValueError("recovered drift input must map selectors to fields")
        for pointer, observed_type in fields.items():
            normalized = normalize_response_drift(
                {
                    "schema_version": "gravity.response-drift.v1",
                    "direction": "response",
                    "classification": "additive",
                    "fields": [
                        {"path": pointer, "observed_type": observed_type}
                    ],
                }
            )
            field = normalized["fields"][0]
            rows.append((selector, field["path"], field["observed_type"]))
    return rows


def _load_observations(
    evidence_paths: Sequence[Path], selectors: frozenset[str]
) -> tuple[dict[tuple[str, str], set[str]], list[dict[str, Any]]]:
    observations: dict[tuple[str, str], set[str]] = defaultdict(set)
    inputs: list[dict[str, Any]] = []
    for raw_path in evidence_paths:
        path = raw_path.resolve()
        payload = path.read_bytes()
        document = read_json(path)
        if not isinstance(document, Mapping):
            raise ValueError(f"drift evidence must be an object: {path}")
        schema_version, rows = _evidence_observations(document, path)
        for selector, pointer, observed_type in rows:
            if not selectors or selector in selectors:
                observations[(selector, pointer)].add(observed_type)
        inputs.append(
            {
                "path": path.as_posix(),
                "sha256": _sha256_bytes(payload),
                "schema_version": schema_version,
            }
        )
    inputs.sort(key=lambda item: item["path"])
    return observations, inputs


def _source_entry(
    operation_id: str,
    observations: Sequence[tuple[str, set[str]]],
    operation_root: Path,
    project_root: Path,
) -> dict[str, Any]:
    path = operation_root / f"{operation_id}.json"
    if not path.is_file():
        decisions = [
            manual_decision(pointer, sorted(types), "direct_stable_source_missing")
            for pointer, types in observations
        ]
        return _operation_entry(operation_id, None, None, decisions)
    payload = path.read_bytes()
    source = read_json(path)
    operation = source.get("operation") if isinstance(source, Mapping) else None
    if not isinstance(operation, Mapping) or operation.get("stability") != "stable":
        decisions = [
            manual_decision(pointer, sorted(types), "operation_not_stable")
            for pointer, types in observations
        ]
    else:
        decisions = [
            decide_observation(operation, pointer, types)
            for pointer, types in observations
        ]
        decisions = validate_combined_decisions(operation, decisions)
    return _operation_entry(
        operation_id,
        _display_path(path, project_root),
        _sha256_bytes(payload),
        decisions,
    )


def _operation_entry(
    operation_id: str,
    source_path: str | None,
    source_sha256: str | None,
    decisions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    counts = Counter(str(item["decision"]) for item in decisions)
    return {
        "operation_id": operation_id,
        "source_path": source_path,
        "source_sha256": source_sha256,
        "summary": {
            "observations": len(decisions),
            "automatic": counts["automatic"],
            "manual": counts["manual"],
        },
        "decisions": list(decisions),
    }


def _plan_summary(operations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    decisions = [
        decision for operation in operations for decision in operation["decisions"]
    ]
    counts = Counter(str(item["decision"]) for item in decisions)
    reasons = Counter(str(item["reason"]) for item in decisions)
    return {
        "selectors": len(operations),
        "observations": len(decisions),
        "automatic": counts["automatic"],
        "manual": counts["manual"],
        "reasons": dict(sorted(reasons.items())),
    }


def build_drift_plan(
    evidence_paths: Sequence[Path],
    *,
    selectors: Sequence[str] = (),
    operation_root: Path = OPERATION_ROOT,
) -> dict[str, Any]:
    """Build a deterministic, read-only declaration plan from drift evidence."""

    if not evidence_paths:
        raise ValueError("at least one drift evidence file is required")
    selected = frozenset(str(item) for item in selectors if str(item))
    observations, inputs = _load_observations(evidence_paths, selected)
    grouped: dict[str, list[tuple[str, set[str]]]] = defaultdict(list)
    for (operation_id, pointer), types in sorted(observations.items()):
        grouped[operation_id].append((pointer, types))
    project_root = operation_root.resolve().parents[3]
    operations = [
        _source_entry(operation_id, grouped[operation_id], operation_root, project_root)
        for operation_id in sorted(grouped)
    ]
    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "input": {
            "canonical_schema_version": RUN_SCHEMA_VERSION,
            "evidence": inputs,
            "selectors": sorted(selected),
        },
        "summary": _plan_summary(operations),
        "operations": operations,
        "network_called": False,
    }
    plan["plan_sha256"] = canonical_fingerprint(plan)
    return plan


def write_drift_plan(path: Path, plan: Mapping[str, Any]) -> None:
    write_json(path.resolve(), plan)


def _verify_plan(plan: Mapping[str, Any], operation_root: Path) -> dict[str, Any]:
    if plan.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise ValueError("unsupported response drift declaration plan")
    expected = canonical_fingerprint(
        {key: value for key, value in plan.items() if key != "plan_sha256"}
    )
    if plan.get("plan_sha256") != expected:
        raise ValueError("response drift declaration plan digest changed")
    inputs = plan.get("input")
    if not isinstance(inputs, Mapping):
        raise ValueError("response drift declaration plan input is invalid")
    evidence = inputs.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("response drift declaration plan evidence is invalid")
    rebuilt = build_drift_plan(
        [Path(str(item["path"])) for item in evidence if isinstance(item, Mapping)],
        selectors=[str(item) for item in inputs.get("selectors", ())],
        operation_root=operation_root,
    )
    if rebuilt.get("plan_sha256") != plan.get("plan_sha256"):
        raise ValueError("response drift declaration plan is stale")
    return rebuilt


def _automatic_operations(plan: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [
        operation
        for operation in plan.get("operations", ())
        if isinstance(operation, Mapping)
        and any(
            isinstance(item, Mapping) and item.get("decision") == "automatic"
            for item in operation.get("decisions", ())
        )
    ]


def _tracked_snapshot(root: Path, *, require_clean: bool) -> dict[Path, bytes]:
    if not (root / ".git").exists():
        if require_clean:
            raise ValueError("drift apply requires a Git worktree")
        return {
            path: path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }
    if require_clean:
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if status.returncode != 0 or status.stdout.strip():
            raise ValueError("drift apply requires a clean tracked worktree")
    listed = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True
    ).stdout.split(b"\0")
    return {
        path: path.read_bytes()
        for raw in listed
        if raw and (path := root / raw.decode("utf-8")).is_file()
    }


def _restore_snapshot(snapshot: Mapping[Path, bytes]) -> None:
    for path, payload in snapshot.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)


def _apply_contract_decisions(
    root: Path, operations: Sequence[Mapping[str, Any]]
) -> list[str]:
    changed: list[str] = []
    for plan_operation in operations:
        source_path = plan_operation.get("source_path")
        if not isinstance(source_path, str):
            raise ValueError("automatic operation has no direct source path")
        path = root / source_path
        source = read_json(path)
        operation = source["operation"]
        for decision in plan_operation["decisions"]:
            if decision.get("decision") == "automatic":
                apply_projection_edit(operation, decision["proposed_edit"])
        OperationSpec.from_dict(operation)
        write_json(path, source)
        changed.append(str(plan_operation["operation_id"]))
    return changed


def _refresh_golden_fixture(
    root: Path, operations: Sequence[Mapping[str, Any]]
) -> None:
    path = root / "tests/fixtures/gravity_insight_golden/operations.json"
    document = read_json(path)
    by_id = {
        str(item.get("operation_id")): item
        for item in document.get("operations", ())
        if isinstance(item, Mapping)
    }
    for plan_operation in operations:
        golden = by_id.get(str(plan_operation["operation_id"]))
        if golden is None:
            continue
        for decision in plan_operation["decisions"]:
            if decision.get("decision") == "automatic":
                apply_projection_edit(golden, decision["proposed_edit"])
    write_json(path, document)


def _run_command(root: Path, command: Sequence[str]) -> dict[str, Any]:
    completed = subprocess.run(
        list(command), cwd=root, check=False, capture_output=True, text=True
    )
    output = (completed.stdout + completed.stderr)[-4000:]
    result = {"command": list(command), "exit_code": completed.returncode, "output_tail": output}
    if completed.returncode != 0:
        raise RuntimeError(
            f"offline gate failed ({completed.returncode}): {' '.join(command)}\n{output}"
        )
    return result


def _refresh_products(
    root: Path, operations: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    registry = root / REGISTRY_PATH
    registry.write_text(render_registry(root), encoding="utf-8", newline="\n")
    errors = inspect_stable_response_privacy(root)
    if errors:
        raise RuntimeError("stable privacy gate failed: " + "; ".join(errors[:5]))
    contract_root = root / "src/gravity_insight/contracts"
    manifest_root = root / "src/gravity_insight/manifests"
    ContractCompiler(contract_root, manifest_root).compile()
    _refresh_golden_fixture(root, operations)
    return [
        _run_command(
            root, [sys.executable, "scripts/refresh_validation_harnesses.py"]
        )
    ]


def _run_offline_gates(root: Path) -> list[dict[str, Any]]:
    commands = (
        [sys.executable, "-m", "gravity_insight.compiler", "check"],
        [sys.executable, "-m", "gravity_insight.quality", "check"],
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "-m", "gravity_insight", "--help"],
        ["git", "diff", "--check"],
    )
    return [_run_command(root, command) for command in commands]


RefreshProducts = Callable[[Path, Sequence[Mapping[str, Any]]], list[dict[str, Any]]]
GateRunner = Callable[[Path], list[dict[str, Any]]]


def _apply_obligations(*, changed: bool) -> EnvelopeObligations:
    return EnvelopeObligations(
        execution_status=ExecutionStatus(
            ExecutionState.COMPLETE, "DRIFT_DECLARATION_APPLY_FINISHED"
        ),
        data_completeness=DataCompleteness(
            CompletenessState.NOT_APPLICABLE,
            "DRIFT_DECLARATION_HAS_NO_DATA_ROWS",
        ),
        semantic_validity=SemanticValidity(
            SemanticState.VALID, ("DRIFT_DECLARATION_PLAN_VERIFIED",)
        ),
        diagnostic_evidence=DiagnosticEvidence(DiagnosticState.NONE),
        mutation_certainty=MutationCertainty(
            MutationState.CONFIRMED if changed else MutationState.NOT_ATTEMPTED,
            "DRIFT_DECLARATION_GATES_PASSED"
            if changed
            else "DRIFT_DECLARATION_NO_AUTOMATIC_CHANGES",
        ),
    )


def apply_drift_plan(
    plan_path: Path,
    *,
    root: Path = REPO_ROOT,
    refresh_products: RefreshProducts = _refresh_products,
    gate_runner: GateRunner = _run_offline_gates,
    require_clean: bool = True,
) -> dict[str, Any]:
    """Apply automatic plan entries, rolling every tracked file back on failure."""

    root = root.resolve()
    plan = read_json(plan_path.resolve())
    if not isinstance(plan, Mapping):
        raise ValueError("response drift declaration plan must be an object")
    operation_root = root / "src/gravity_insight/contracts/operations"
    verified = _verify_plan(plan, operation_root)
    automatic = _automatic_operations(verified)
    if not automatic:
        return serialize_envelope(
            {
                "schema_version": "gravity-insight.response-drift-declaration-apply.v1",
                "status": "no_automatic_changes",
                "operations": [],
                "automatic": 0,
                "network_called": False,
                "gates": [],
            },
            _apply_obligations(changed=False),
        )
    baseline_privacy_errors = inspect_stable_response_privacy(root)
    if baseline_privacy_errors:
        raise ValueError("stable privacy baseline is not clean")
    snapshot = _tracked_snapshot(root, require_clean=require_clean)
    try:
        operation_ids = _apply_contract_decisions(root, automatic)
        refresh_results = refresh_products(root, automatic)
        gate_results = gate_runner(root)
    except Exception as exc:
        _restore_snapshot(snapshot)
        raise RuntimeError("drift declaration apply failed and was rolled back") from exc
    automatic_count = sum(item["summary"]["automatic"] for item in automatic)
    return serialize_envelope(
        {
            "schema_version": "gravity-insight.response-drift-declaration-apply.v1",
            "status": "applied",
            "operations": operation_ids,
            "automatic": automatic_count,
            "network_called": False,
            "refresh": refresh_results,
            "gates": gate_results,
        },
        _apply_obligations(changed=True),
    )


__all__ = [
    "PLAN_SCHEMA_VERSION",
    "RUN_SCHEMA_VERSION",
    "apply_drift_plan",
    "build_drift_plan",
    "write_drift_plan",
]
