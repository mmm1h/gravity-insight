"""Deterministic Runtime self-checks used by CLI and the quality gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Mapping

from .compiler import ContractCompiler
from .context_contract import project_repo_provider_artifact
from .evidence_common import load_object, relative
from .journey_certification import journey_certifications
from .model_registry import ModelRegistry
from .operator_registry import OperatorRegistry
from .paths import PROJECT_ROOT
from .repo_context_provider import RepoContextProvider
from .semantic_registry import SemanticRegistry
from .skill_contract import compile_skill_manifest


def _check(
    check_id: str,
    source: str,
    collector: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    try:
        observed = dict(collector())
        passed = observed.pop("passed", True) is True
        errors = list(observed.pop("errors", []))
    except (OSError, RuntimeError, UnicodeError, ValueError, TypeError) as exc:
        passed = False
        observed = {}
        errors = [f"{type(exc).__name__}: {exc}"]
    return {
        "id": check_id,
        "status": "pass" if passed else "fail",
        "source": source,
        "observed": observed,
        "errors": errors,
    }


def _compiler(root: Path) -> dict[str, Any]:
    package = root / "src/gravity_insight"
    result = ContractCompiler(
        package / "contracts", package / "manifests"
    ).check()
    provenance = json.loads(result.provenance)
    operations = provenance.get("operations", {})
    return {
        "passed": isinstance(operations, dict)
        and len(operations) == result.operation_count,
        "operations": result.operation_count,
        "manifests": len(result.manifests),
        "provenance_operations": len(operations) if isinstance(operations, dict) else None,
    }


def _journeys(root: Path) -> dict[str, Any]:
    result = journey_certifications(root)
    return {
        "passed": result["ok"],
        "journeys": result["counts"]["total"],
        "registry_errors": len(result["registry_errors"]),
        "errors": result["registry_errors"],
    }


def _skills(root: Path) -> dict[str, Any]:
    paths = sorted((root / "skills/library").glob("*.json"))
    errors: list[str] = []
    valid = 0
    for path in paths:
        try:
            compile_skill_manifest(load_object(path), label=relative(root, path))
            valid += 1
        except (OSError, RuntimeError, UnicodeError, ValueError, TypeError) as exc:
            errors.append(f"{relative(root, path)}: {type(exc).__name__}: {exc}")
    return {
        "passed": bool(paths) and valid == len(paths),
        "canonical_library": len(paths),
        "canonical_valid": valid,
        "errors": errors,
    }


def _registries() -> dict[str, Any]:
    semantics = SemanticRegistry().list()
    operators = OperatorRegistry().list()
    models = ModelRegistry().list()
    return {
        "passed": all(
            item.get("status") == "success" for item in (semantics, operators, models)
        ),
        "semantic_definitions": semantics["count"],
        "operators": operators["count"],
        "models": models["count"],
    }


def _routes(root: Path) -> dict[str, Any]:
    coverage_path = root / "src/gravity_insight/census/data/coverage.json"
    registry_path = root / "src/gravity_insight/contracts/routes/registry.json"
    coverage = load_object(coverage_path)
    registry = load_object(registry_path)
    summary = coverage.get("summary", {})
    routes = registry.get("routes", [])
    keys = [
        (item.get("method"), item.get("path"))
        for item in routes
        if isinstance(item, Mapping)
    ]
    passed = (
        summary.get("accounting_complete") is True
        and summary.get("unaccounted") == 0
        and bool(routes)
        and len(keys) == len(routes) == len(set(keys))
    )
    return {
        "passed": passed,
        "census_routes": summary.get("total_routes"),
        "accounted": summary.get("accounted"),
        "unaccounted": summary.get("unaccounted"),
        "registered_classifications": len(routes),
        "unique_registered_routes": len(set(keys)),
    }


def _provider(root: Path) -> dict[str, Any]:
    artifact = project_repo_provider_artifact()
    result = RepoContextProvider(root, project_id="gravity-insight").describe()
    return {
        "passed": result.get("ok") is True,
        "provider_uri": artifact["contract"]["uri"],
        "transport": artifact["contract"]["transport"],
        "network_called": result["network_called"],
    }


def runtime_health_report(
    root: Path = PROJECT_ROOT, *, include_compiler: bool = True
) -> dict[str, Any]:
    root = root.resolve()
    checks: list[dict[str, Any]] = []
    if include_compiler:
        checks.append(
            _check(
                "contract_compilation",
                "src/gravity_insight/contracts + src/gravity_insight/manifests",
                lambda: _compiler(root),
            )
        )
    checks.extend(
        (
            _check(
                "journey_registry",
                "src/gravity_insight/contracts/journeys",
                lambda: _journeys(root),
            ),
            _check("skill_contracts", "skills/library", lambda: _skills(root)),
            _check(
                "semantic_operator_model_registries",
                "src/gravity_insight/contracts/{semantic,operators}",
                _registries,
            ),
            _check(
                "route_registration",
                "src/gravity_insight/census/data/coverage.json + contracts/routes/registry.json",
                lambda: _routes(root),
            ),
            _check(
                "provider_offline_reachability",
                "src/gravity_insight/contracts/context-providers/project-repo.v1.json",
                lambda: _provider(root),
            ),
        )
    )
    failed = [check for check in checks if check["status"] != "pass"]
    return {
        "schema_version": "gravity.runtime-health.v1",
        "status": "pass" if not failed else "fail",
        "ok": not failed,
        "exit_code": 0 if not failed else 1,
        "summary": {
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "total": len(checks),
        },
        "checks": checks,
        "scope": "offline",
        "network_called": False,
    }


def runtime_health_errors(
    root: Path = PROJECT_ROOT, *, include_compiler: bool = False
) -> list[str]:
    result = runtime_health_report(root, include_compiler=include_compiler)
    return [
        f"runtime health {check['id']}: {error or check['status']}"
        for check in result["checks"]
        if check["status"] != "pass"
        for error in (check["errors"] or [""])
    ]


__all__ = ["runtime_health_errors", "runtime_health_report"]
