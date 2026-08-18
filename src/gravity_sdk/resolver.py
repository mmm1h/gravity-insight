"""Single-process intent-to-execution resolver for operations and recipes."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import (
    ErrorCategory,
    GravityInsightError,
    InputValidationError,
    error_for_status,
    exit_code_for_category,
    exit_code_for_status,
    is_success_status,
    semantic_envelope_ok,
)
from .parent_resolution import resolve_declared_parents
from .pagination_audit import pagination_audit
from .receipt import RequestCounter, build_receipt, count_http_requests, persist_receipt
from .recipe import check_recipe
from .resolver_support import (
    add_event_diagnostics,
    add_parent_diagnostics,
    apply_parent_selections,
    build_inputs,
    description_fingerprint,
    diagnostic,
    error_diagnostic,
    missing_parent_bindings,
    parse_parameter_assignments,
    validation_diagnostic,
    validation_summary,
)
from .result_audit import add_result_audit, result_receipt_references
from .result_source import selector_result_source
from .workspace import Recipe, Workspace


SCHEMA_VERSION = "gravity.resolver.v1"
_EXPECTED_ERRORS = (GravityInsightError, OSError, RuntimeError, ValueError, TypeError)


def resolve_and_run(
    selector: str,
    *,
    client: Any,
    workspace: Workspace,
    supplied_input: Mapping[str, Any] | None = None,
    parameters: Mapping[str, Any] | None = None,
    app: str | int | None = None,
    start: str | None = None,
    end: str | None = None,
    read: Callable[..., Mapping[str, Any]],
    read_all: bool = False,
    max_pages: int | None = None,
    max_items: int | None = None,
    max_workers: int | None = None,
    metadata_database: Path | None = None,
    output_fields: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    resolver = _Resolver(
        selector=selector,
        client=client,
        workspace=workspace,
        supplied_input=dict(supplied_input or {}),
        parameters=dict(parameters or {}),
        app=app,
        start=start,
        end=end,
        read=read,
        read_all=read_all,
        max_pages=max_pages,
        max_items=max_items,
        max_workers=max_workers,
        metadata_database=metadata_database,
        output_fields=tuple(output_fields) if output_fields is not None else None,
    )
    return resolver.run()


@dataclass
class _Resolver:
    selector: str
    client: Any
    workspace: Workspace
    supplied_input: Mapping[str, Any]
    parameters: Mapping[str, Any]
    app: str | int | None
    start: str | None
    end: str | None
    read: Callable[..., Mapping[str, Any]]
    read_all: bool
    max_pages: int | None
    max_items: int | None
    max_workers: int | None
    metadata_database: Path | None
    output_fields: tuple[str, ...] | None
    operation_id: str = field(init=False)
    inputs: dict[str, Any] = field(default_factory=dict, init=False)
    contract_fingerprint: str | None = field(default=None, init=False)
    recipe: Recipe | None = field(default=None, init=False)
    description: Mapping[str, Any] = field(default_factory=dict, init=False)
    validation: Mapping[str, Any] = field(default_factory=dict, init=False)
    pipeline: dict[str, dict[str, Any]] = field(default_factory=dict, init=False)
    diagnostics: list[dict[str, Any]] = field(default_factory=list, init=False)
    counter: RequestCounter = field(default_factory=RequestCounter, init=False)
    started: float = field(default_factory=time.monotonic, init=False)

    def __post_init__(self) -> None:
        self.operation_id = self.selector.removeprefix("@")

    def run(self) -> dict[str, Any]:
        with count_http_requests() as counter:
            self.counter = counter
            failed = self._bind()
            if failed is not None:
                return failed
            self.validation = self.client.validate(self.operation_id, self.inputs)
            self.pipeline["validate"] = validation_summary(self.validation)
            parents = self._resolve_parents()
            unresolved = self._unresolved_parents(parents)
            if unresolved:
                self.pipeline["exec"] = {"status": "skipped"}
                add_parent_diagnostics(self.diagnostics, unresolved, self.operation_id)
                self.pipeline["diagnose"] = {"status": "action_required"}
                return self._finish(False, "needs_parent", parents=parents)
            if self.validation.get("ok") is not True:
                return self._invalid(parents)
            return self._execute(parents)

    def _bind(self) -> dict[str, Any] | None:
        if self.selector.startswith("@"):
            failed = self._bind_recipe()
            if failed is not None:
                return failed
        try:
            self.description = self.client.describe(self.operation_id)
            self.contract_fingerprint = description_fingerprint(self.description)
            self.inputs = build_inputs(
                self.recipe,
                self.workspace,
                self.description,
                self.supplied_input,
                self.parameters,
                app=self.app,
                start=self.start,
                end=self.end,
            )
            if self.output_fields is not None:
                from .output_projection import validate_output_fields

                validate_output_fields(
                    self.description,
                    self.output_fields,
                    request_inputs=self.inputs,
                )
        except _EXPECTED_ERRORS as exc:
            self.pipeline["bind"] = {"status": "error"}
            self.diagnostics.append(error_diagnostic(exc, priority=10))
            return self._finish(False, "invalid")
        self.pipeline["bind"] = {
            "status": "success",
            "source": "recipe" if self.recipe is not None else "operation",
            "app_alias_resolved": bool(
                self.app is not None
                or (self.recipe is not None and self.recipe.bindings.app_ref)
            ),
        }
        self.pipeline["build"] = {
            "status": "success",
            "input_fields": sorted(self.inputs),
        }
        return None

    def _bind_recipe(self) -> dict[str, Any] | None:
        try:
            self.recipe = self.workspace.recipe(self.operation_id)
        except (ValueError, KeyError) as exc:
            self.pipeline["bind"] = {"status": "error"}
            self.diagnostics.append(diagnostic("recipe_missing", 10, str(exc)))
            return self._finish(False, "invalid")
        self.operation_id = self.recipe.operation
        check = check_recipe(self.recipe, self.client)
        value = check.get("contract_fingerprint")
        self.contract_fingerprint = value if isinstance(value, str) else None
        if check["status"] != "stale":
            return None
        self.pipeline["bind"] = {"status": "stale", "recipe_check": check}
        self.diagnostics.append(diagnostic(
            "recipe_stale",
            10,
            "The recipe no longer matches its operation contract.",
            next_action=(
                f"Run `gravity recipe check {self.recipe.name}` then "
                f"`gravity recipe accept-contract {self.recipe.name}` after reviewing the contract diff."
            ),
        ))
        return self._finish(False, "stale")

    def _resolve_parents(self) -> dict[str, Any]:
        missing = missing_parent_bindings(self.description, self.inputs)
        if not missing:
            status = "satisfied" if self.description.get("required_parent") else "not_required"
            self.pipeline["parents"] = {"status": status, "missing_bindings": 0}
            return {
                "schema_version": "gravity-insight.parent-resolution.v1",
                "ok": True,
                "operation_id": self.operation_id,
                "status": status,
                "bindings": [],
                "values_persisted": False,
            }
        selected = dict(self.description)
        selected["required_parent"] = missing
        parents = resolve_declared_parents(selected, self.client.probe)
        apply_parent_selections(self.inputs, parents)
        self.pipeline["parents"] = {
            "status": parents.get("status"),
            "missing_bindings": len(missing),
        }
        if any(item.get("selected") is not None for item in parents["bindings"]):
            self.validation = self.client.validate(self.operation_id, self.inputs)
            self.pipeline["validate"] = validation_summary(self.validation)
        return parents

    def _unresolved_parents(
        self, parents: Mapping[str, Any]
    ) -> list[Mapping[str, Any]]:
        return [
            binding
            for binding in parents.get("bindings", [])
            if isinstance(binding, Mapping)
            and binding.get("target_input") not in self.inputs
        ]

    def _invalid(self, parents: Mapping[str, Any]) -> dict[str, Any]:
        self.pipeline["exec"] = {"status": "skipped"}
        self.diagnostics.append(validation_diagnostic(self.validation, self.operation_id))
        add_event_diagnostics(
            self.diagnostics,
            self.inputs,
            self.description,
            database=self.metadata_database,
        )
        self.pipeline["diagnose"] = {"status": "action_required"}
        return self._finish(False, "invalid", parents=parents)

    def _execute(self, parents: Mapping[str, Any]) -> dict[str, Any]:
        try:
            result = self.read(
                self.client,
                self.operation_id,
                self.inputs,
                read_all=self.read_all,
                max_pages=self.max_pages,
                max_items=self.max_items,
                max_workers=self.max_workers,
            )
        except _EXPECTED_ERRORS as exc:
            self.pipeline["exec"] = {"status": "error"}
            self.diagnostics.append(error_diagnostic(exc, priority=10))
            self.pipeline["diagnose"] = {"status": "action_required"}
            return self._finish(False, "error", parents=parents)
        status = str(result.get("status", "success"))
        if self.output_fields is not None:
            from .output_projection import apply_output_fields

            result = apply_output_fields(
                result,
                self.description,
                self.output_fields,
                request_inputs=self.inputs,
            )
        self.pipeline["exec"] = {"status": status}
        self._diagnose_result(result, status)
        return self._finish(
            semantic_envelope_ok(result),
            status,
            output=result.get("data"),
            result=result,
            parents=parents,
        )

    def _diagnose_result(self, result: Mapping[str, Any], status: str) -> None:
        if status == "empty":
            self.diagnostics.append(diagnostic(
                "empty_result",
                30,
                "The request succeeded but returned no contracted rows.",
                next_action=(
                    "Verify the bound app, time window, metadata names, and declared parent resources."
                ),
            ))
            add_event_diagnostics(
                self.diagnostics,
                self.inputs,
                self.description,
                database=self.metadata_database,
            )
        elif result.get("ok") is False or not is_success_status(status):
            error = result.get("error")
            implied = error_for_status(status, operation_id=self.operation_id)
            if not isinstance(error, Mapping) and implied is not None:
                error = implied
            self.diagnostics.append({
                "code": "execution_failed",
                "priority": 10,
                "message": "The governed read returned a failure envelope.",
                "error": error if isinstance(error, Mapping) else None,
            })
        self.pipeline["diagnose"] = {
            "status": "action_required" if self.diagnostics else "not_required"
        }

    def _finish(
        self,
        ok: bool,
        status: str,
        *,
        output: Any = None,
        result: Mapping[str, Any] | None = None,
        parents: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        receipt = build_receipt(
            operation_id=self.operation_id,
            inputs=self.inputs,
            contract_fingerprint=self.contract_fingerprint,
            output=output,
            status=status,
            duration_ms=(time.monotonic() - self.started) * 1_000,
            request_count=self.counter.count,
        )
        persisted, path = persist_receipt(receipt, self.workspace.state_root)
        envelope: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "result_source": selector_result_source(self.selector),
            "ok": ok,
            "status": status,
            "exit_code": _resolver_exit_code(ok, status, self.diagnostics),
            "selector": self.selector,
            "recipe": self.recipe.name if self.recipe is not None else None,
            "operation_id": self.operation_id,
            "pipeline": self.pipeline,
            "diagnostics": sorted(
                self.diagnostics,
                key=lambda item: (
                    int(item.get("priority", 100)), str(item.get("code", ""))
                ),
            ),
            "receipt": receipt,
            "receipt_storage": {
                "persisted": persisted,
                "relative_path": str(path.relative_to(self.workspace.state_root)),
            },
        }
        if parents is not None:
            envelope["parents"] = parents
        if result is not None:
            envelope["result"] = dict(result)
            envelope["pagination_audit"] = pagination_audit(
                result,
                self.inputs,
                all_pages=self.read_all,
                bounded=(
                    self.read_all
                    or self.max_pages is not None
                    or self.max_items is not None
                ),
                http_requests_made=receipt["request_count"],
            )
            fact_paths = {"operation_id": "/operation_id"}
            if "contract_version" in result:
                fact_paths["contract_version"] = "/result/contract_version"
            envelope = add_result_audit(
                envelope,
                result_receipt_references(result),
                fact_paths=fact_paths,
            )
        return envelope


def _resolver_exit_code(
    ok: bool, status: str, diagnostics: list[dict[str, Any]]
) -> int:
    if ok:
        return 0
    implied = exit_code_for_status(status, ok=ok)
    if implied != exit_code_for_category(ErrorCategory.LOCAL):
        return implied
    categories = {
        str(error.get("category"))
        for item in diagnostics
        if isinstance(item, Mapping)
        for error in (item.get("error"),)
        if isinstance(error, Mapping)
    }
    if ErrorCategory.LOCAL.value in categories:
        return exit_code_for_category(ErrorCategory.LOCAL)
    if ErrorCategory.UPSTREAM.value in categories:
        return exit_code_for_category(ErrorCategory.UPSTREAM)
    if ErrorCategory.CALLER.value in categories or status in {
        "invalid",
        "stale",
        "needs_parent",
    }:
        return exit_code_for_category(ErrorCategory.CALLER)
    return exit_code_for_category(ErrorCategory.LOCAL)


__all__ = ["parse_parameter_assignments", "resolve_and_run"]
