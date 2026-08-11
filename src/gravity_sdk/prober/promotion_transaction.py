"""Atomic filesystem commit for promoted probe contracts."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .core import display_path, read_json, write_json


PromotionCandidate = tuple[Path, Path, Mapping[str, Any]]
GateEvaluator = Callable[[Mapping[str, Any]], Mapping[str, Any]]
StableBuilder = Callable[[Mapping[str, Any], Path], Mapping[str, Any]]


def _compile_contract_products() -> None:
    from gravity_sdk.compiler import ContractCompiler

    ContractCompiler().compile()


def _rollback_promotion_files(candidates: Sequence[PromotionCandidate]) -> None:
    for draft_path, destination, source in candidates:
        if not draft_path.exists():
            write_json(draft_path, source)
        if destination.exists():
            destination.unlink()


def _rollback_failed_promotion(
    candidates: Sequence[PromotionCandidate],
    *,
    restore_products: bool,
    cause: Exception,
) -> None:
    failures: list[Exception] = []
    try:
        _rollback_promotion_files(candidates)
    except Exception as exc:
        failures.append(exc)
    if restore_products:
        try:
            _compile_contract_products()
        except Exception as exc:
            failures.append(exc)
    if failures:
        kinds = ", ".join(type(item).__name__ for item in failures)
        raise RuntimeError(
            f"promotion failed and rollback was incomplete ({kinds})"
        ) from cause


def _prepare_candidate(
    operation_id: str,
    draft_root: Path,
    operation_root: Path,
    evaluate_gate: GateEvaluator,
    stable_source: StableBuilder,
) -> tuple[PromotionCandidate, Mapping[str, Any], dict[str, Any]]:
    draft_path = draft_root / f"{operation_id}.json"
    if not draft_path.is_file():
        raise ValueError(f"unknown draft operation: {operation_id}")
    source = read_json(draft_path)
    gate = evaluate_gate(source)
    if not gate["eligible"]:
        raise ValueError(
            f"promotion gate blocked {operation_id}: "
            + ", ".join(gate["missing"])
        )
    destination = operation_root / f"{operation_id}.json"
    if destination.exists():
        raise ValueError(f"stable operation already exists: {operation_id}")
    candidate = (draft_path, destination, source)
    result = {
        "operation_id": operation_id,
        "status": "stable",
        "operation_path": display_path(destination),
    }
    return candidate, stable_source(source, operation_root), result


def promote_atomically(
    operation_ids: Sequence[str],
    *,
    draft_root: Path,
    operation_root: Path,
    compile_products: bool,
    evaluate_gate: GateEvaluator,
    stable_source: StableBuilder,
) -> list[dict[str, Any]]:
    """Promote all requested drafts or restore the pre-call file state."""

    promoted: list[dict[str, Any]] = []
    candidates: list[PromotionCandidate] = []
    compile_started = False
    try:
        for operation_id in operation_ids:
            candidate, stable, result = _prepare_candidate(
                operation_id,
                draft_root,
                operation_root,
                evaluate_gate,
                stable_source,
            )
            candidates.append(candidate)
            write_json(candidate[1], stable)
            promoted.append(result)
        if compile_products and promoted:
            compile_started = True
            _compile_contract_products()
        for draft_path, _, _ in candidates:
            draft_path.unlink()
        return promoted
    except Exception as exc:
        _rollback_failed_promotion(
            candidates,
            restore_products=compile_started,
            cause=exc,
        )
        raise
