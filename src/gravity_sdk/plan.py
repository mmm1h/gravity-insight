"""Public, dependency-injected API for bounded Gravity capability plans."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, ContextManager

from .errors import InputValidationError
from .plan_budget import PlanWorkerLease, SerialWorkerLease


PLAN_SCHEMA_VERSION = "gravity.plan.v1"
RESULT_SCHEMA_VERSION = "gravity.plan-result.v1"
SCHEMA_SCHEMA_VERSION = "gravity.plan-schema.v1"
NODE_KINDS = ("run", "sql_product", "metadata_search", "composite", "receipt_query")
DEFAULT_MAX_WORKERS = 6
MAX_WORKERS = 24
DEFAULT_MAX_PAGES = 5
DEFAULT_MAX_ITEMS = 200
DEFAULT_FOREACH_ITEMS = 32
MAX_FOREACH_ITEMS = 64
MAX_DECLARED_NODES = 64
MAX_EXPANDED_NODES = 256
MAX_AGGREGATE_ITEMS = 100_000

AdapterExecute = Callable[[Mapping[str, Any], "AdapterContext"], Any]
AdapterProject = Callable[[Any, tuple[str, ...], "AdapterContext"], Any]
AdapterValidate = Callable[[Mapping[str, Any], "AdapterContext"], None]


@dataclass(frozen=True)
class AdapterContext:
    """Value-free execution context supplied to every controlled adapter."""

    node_id: str
    execution_id: str
    kind: str
    workspace: Any
    output_fields: tuple[str, ...]
    dynamic_targets: tuple[str, ...]
    max_pages: int
    max_items: int
    max_workers: int = 1
    _worker_lease: PlanWorkerLease | SerialWorkerLease = field(
        default_factory=SerialWorkerLease, repr=False, compare=False
    )

    def borrow_workers(self, limit: int) -> ContextManager[int]:
        """Borrow available outer Plan capacity without waiting for extra slots."""

        return self._worker_lease.borrow(limit)


@dataclass(frozen=True)
class PlanAdapter:
    """One adapter plus its optional governed post-execution projector."""

    execute: AdapterExecute
    validate: AdapterValidate
    project: AdapterProject | None = None
    preserve_partial: bool = False
    preserve_capability_gap: bool = False


@dataclass(frozen=True)
class PlanAdapters:
    run: PlanAdapter | None = None
    sql_product: PlanAdapter | None = None
    metadata_search: PlanAdapter | None = None
    composite: PlanAdapter | None = None
    receipt_query: PlanAdapter | None = None


@dataclass(frozen=True)
class Binding:
    source_node: str
    source: str
    target: str


@dataclass(frozen=True)
class Foreach:
    source_node: str
    source: str
    target: str
    max_items: int


@dataclass(frozen=True)
class NodeLimits:
    max_pages: int
    max_items: int


@dataclass(frozen=True)
class PlanNode:
    node_id: str
    kind: str
    request: Mapping[str, Any]
    depends_on: tuple[str, ...]
    bindings: tuple[Binding, ...]
    foreach: Foreach | None
    limits: NodeLimits
    output_fields: tuple[str, ...]


@dataclass(frozen=True)
class ValidatedPlan:
    nodes: tuple[PlanNode, ...]
    max_workers: int
    max_total_items: int
    max_expanded_nodes: int
    max_aggregate_items: int


class PlanValidationError(InputValidationError):
    """A caller-safe preflight failure with a stable field identity."""

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(
            message,
            field=field,
            next_action="Correct the gravity.plan.v1 document, then retry.",
        )


def validate_plan(plan: Mapping[str, Any]) -> ValidatedPlan:
    """Fully preflight a v1 plan before any adapter may be called."""

    from .plan_validation import validate_plan as validate

    return validate(plan)


def execute_plan(
    plan: Mapping[str, Any],
    *,
    adapters: PlanAdapters | Mapping[str, PlanAdapter],
    workspace: Any,
    max_workers: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute dependency layers under one outer worker budget."""

    from .plan_execution import execute_plan as execute

    return execute(
        plan,
        adapters=adapters,
        workspace=workspace,
        max_workers=max_workers,
        dry_run=dry_run,
    )


def execute_plan_for_sdk(
    sdk: Any,
    plan: Mapping[str, Any],
    *,
    adapters: PlanAdapters | Mapping[str, PlanAdapter],
    workspace: Any | None = None,
    max_workers: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Thin SDK hook; the owning facade supplies its controlled adapters."""

    selected_workspace = sdk.workspace if workspace is None else workspace
    return execute_plan(
        plan,
        adapters=adapters,
        workspace=selected_workspace,
        max_workers=max_workers,
        dry_run=dry_run,
    )


def plan_schema() -> dict[str, Any]:
    """Return the compact, machine-readable v1 contract."""

    return {
        "schema_version": SCHEMA_SCHEMA_VERSION,
        "ok": True,
        "status": "success",
        "plan_schema_version": PLAN_SCHEMA_VERSION,
        "result_schema_version": RESULT_SCHEMA_VERSION,
        "node_kinds": list(NODE_KINDS),
        "limits": {
            "declared_nodes": MAX_DECLARED_NODES,
            "expanded_executions": MAX_EXPANDED_NODES,
            "aggregate_items": MAX_AGGREGATE_ITEMS,
            "foreach_default": DEFAULT_FOREACH_ITEMS,
            "foreach_max": MAX_FOREACH_ITEMS,
            "outer_concurrency_default": DEFAULT_MAX_WORKERS,
            "outer_concurrency_max": MAX_WORKERS,
            "adapter_inner_concurrency": 1,
            "adapter_borrowed_concurrency_max": MAX_WORKERS,
            "adapter_and_outer_concurrency": "shared outer budget",
        },
        "node": {
            "required": ["id", "kind", "request"],
            "allowed_fields": [
                "bindings", "call_bound", "depends_on", "foreach", "id", "kind",
                "limits", "output_fields", "request",
            ],
            "call_bound": {
                "required": False,
                "schema_version": "gravity.agent-call-bound.v1",
                "default": None,
                "execution_effect": "advisory_only",
                "unknown_capability_assumes": "required_inputs_known",
            },
            "bindings": {
                "fields": ["from", "source", "target"],
                "value": "JSON scalar only",
                "pointer": "RFC 6901 JSON Pointer",
            },
            "foreach": {
                "fields": ["from", "source", "target", "max_items"],
                "nesting": 1,
            },
            "output_fields": "adapter-owned field projection; requires a projector",
            "dynamic_targets": (
                "binding/foreach target pointers are exposed to adapter preflight; "
                "their values are never exposed"
            ),
        },
        "failure": {
            "dependency": "a failed node skips every dependent node",
            "dependency_code": "DEPENDENCY_FAILED",
            "binding_code": "BINDING_FAILED",
            "siblings": "independent nodes continue",
            "failed_result": None,
            "partial_result": "adapter-safe result preserved; node remains failed",
            "exit_precedence": "4 > 3 > 2 > 0",
        },
    }


__all__ = [
    "AdapterContext",
    "PlanAdapter",
    "PlanAdapters",
    "PlanValidationError",
    "ValidatedPlan",
    "execute_plan",
    "execute_plan_for_sdk",
    "plan_schema",
    "validate_plan",
]
