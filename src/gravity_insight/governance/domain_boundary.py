"""Four-layer ownership measurement and ratchet over the governed module graph."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .module_graph import (
    MODULE_GRAPH_DEFINITION_START,
    MODULE_GRAPH_DEFINITION_END,
    module_graph_canonical_sha256,
    module_graph_cyclic_sccs,
    module_graph_definition,
    module_graph_edge_kinds,
    module_graph_for_profile,
)
from .domain_boundary_coverage import (
    classification_ratchet_errors,
    coverage_is_lower,
    valid_coverage_fraction,
)

_ModuleGraphAny = Any
_module_graph_argparse = argparse
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ROOT = PACKAGE_ROOT.parents[1]


DOMAIN_BOUNDARY_BASELINE_PATH = (
    ROOT / "src/gravity_insight/governance/domain-boundary-baseline.json"
)
DOMAIN_BOUNDARY_SCHEMA_VERSION = "gravity.domain-boundary-baseline.v2"
DOMAIN_UNCLASSIFIED = "unclassified"
DOMAIN_LAYER_ORDER = {
    "contracts_value_objects": 0,
    "domain_services": 1,
    "product_composite_plan": 2,
    "facade_cli_mcp": 3,
}
DOMAIN_PACKAGE_LAYER_DEFAULTS = {
    "contracts": "contracts_value_objects",
    "manifests": "contracts_value_objects",
    "control_plane": "domain_services",
    "governance": "domain_services",
    "prober": "domain_services",
    "skills": "domain_services",
    "agents": "product_composite_plan",
    "census": "product_composite_plan",
    "sql": "product_composite_plan",
    "mcp": "facade_cli_mcp",
}
DOMAIN_MODULE_LAYER_OVERRIDES = {
    "gravity_insight": "facade_cli_mcp",
    "gravity_insight.__main__": "facade_cli_mcp",
    "gravity_insight.agent": "facade_cli_mcp",
    "gravity_insight.cli": "facade_cli_mcp",
    "gravity_insight.sdk": "facade_cli_mcp",
    "gravity_insight.client": "domain_services",
    "gravity_insight.executor": "domain_services",
    "gravity_insight.composite": "product_composite_plan",
    "gravity_insight.plan": "product_composite_plan",
    "gravity_insight.plan_adapters": "product_composite_plan",
    "gravity_insight.analysis_result_contract": "contracts_value_objects",
    "gravity_insight.plan_analysis_contract": "contracts_value_objects",
}


def domain_boundary_policy() -> dict[str, _ModuleGraphAny]:
    """Return the deliberately small, fail-honest four-layer classifier."""

    return {
        "edge_direction": "importer_to_dependency",
        "layer_order": dict(DOMAIN_LAYER_ORDER),
        "package_directory_defaults": dict(DOMAIN_PACKAGE_LAYER_DEFAULTS),
        "exact_module_overrides": dict(DOMAIN_MODULE_LAYER_OVERRIDES),
        "fallback": DOMAIN_UNCLASSIFIED,
        "violation_rule": (
            "A classified dependency edge violates the boundary when the "
            "importer's layer ordinal is lower than the dependency's ordinal."
        ),
    }


def _domain_module_layer(
    module: str,
    *,
    package_name: str,
    direct_package_heads: set[str],
) -> str:
    override = DOMAIN_MODULE_LAYER_OVERRIDES.get(module)
    if override is not None:
        return override
    prefix = package_name + "."
    if not module.startswith(prefix):
        return DOMAIN_UNCLASSIFIED
    relative = module[len(prefix):]
    head = relative.split(".", 1)[0]
    if head not in direct_package_heads:
        return DOMAIN_UNCLASSIFIED
    return DOMAIN_PACKAGE_LAYER_DEFAULTS.get(head, DOMAIN_UNCLASSIFIED)


def _domain_layers(
    package_root: Path,
    inventory: Mapping[Path, tuple[str, bool]],
    nodes: Sequence[str],
) -> dict[str, str]:
    package_name = package_root.name
    direct_packages = {
        name[len(package_name) + 1:]
        for path, (name, is_package) in inventory.items()
        if is_package
        and len(path.relative_to(package_root).parts) == 2
        and name != package_name
    }
    return {
        module: _domain_module_layer(
            module,
            package_name=package_name,
            direct_package_heads=direct_packages,
        )
        for module in nodes
    }


def _domain_direction_violations(
    graph: Mapping[str, set[str]],
    nodes: Sequence[str],
    layers: Mapping[str, str],
) -> list[dict[str, str]]:
    return [
        {
            "source": source,
            "target": target,
            "source_layer": layers[source],
            "target_layer": layers[target],
        }
        for source in nodes
        for target in sorted(graph[source])
        if layers[source] != DOMAIN_UNCLASSIFIED
        and layers[target] != DOMAIN_UNCLASSIFIED
        and DOMAIN_LAYER_ORDER[layers[source]] < DOMAIN_LAYER_ORDER[layers[target]]
    ]


def _domain_root_classification(
    package_root: Path,
    inventory: Mapping[Path, tuple[str, bool]],
    layers: Mapping[str, str],
) -> tuple[list[str], dict[str, str], list[str]]:
    root_modules = sorted(
        name
        for path, (name, _is_package) in inventory.items()
        if path.parent == package_root
    )
    classified = {
        module: layers[module]
        for module in root_modules
        if layers[module] != DOMAIN_UNCLASSIFIED
    }
    unclassified = [
        module for module in root_modules if layers[module] == DOMAIN_UNCLASSIFIED
    ]
    return root_modules, classified, unclassified


def domain_boundary_measurement(
    package_root: Path = PACKAGE_ROOT,
) -> dict[str, _ModuleGraphAny]:
    """Measure boundaries over the governed v1 graph without guessing owners."""

    definition = module_graph_definition()
    inventory, edge_kinds = module_graph_edge_kinds(package_root)
    nodes = sorted(name for name, _is_package in inventory.values())
    graph = module_graph_for_profile(
        nodes,
        edge_kinds,
        definition["profiles"]["ast-only"],
    )
    components = module_graph_cyclic_sccs(graph)
    layers = _domain_layers(package_root, inventory, nodes)
    violations = _domain_direction_violations(graph, nodes, layers)
    root_modules, classified_root, unclassified_root = _domain_root_classification(
        package_root, inventory, layers
    )
    layer_counts = Counter(layers.values())
    unclassified_modules = sorted(
        module for module in nodes if layers[module] == DOMAIN_UNCLASSIFIED
    )
    classified_module_count = len(nodes) - len(unclassified_modules)
    return {
        "schema_version": "gravity.domain-boundary-measurement.v2",
        "graph": {
            "definition_id": definition["definition_id"],
            "definition_sha256": module_graph_canonical_sha256(definition),
            "profile": "ast-only",
            "node_count": len(nodes),
            "edge_count": sum(len(targets) for targets in graph.values()),
            "cyclic_scc_count": len(components),
            "cyclic_scc_sizes": [len(component) for component in components],
            "largest_cyclic_scc_size": len(components[0]) if components else 0,
            "largest_cyclic_scc_members": components[0] if components else [],
        },
        "direction": {
            "violation_count": len(violations),
            "violations": violations,
        },
        "classification": {
            "policy": domain_boundary_policy(),
            "policy_sha256": module_graph_canonical_sha256(domain_boundary_policy()),
            "layer_counts": {
                layer: layer_counts.get(layer, 0)
                for layer in (*DOMAIN_LAYER_ORDER, DOMAIN_UNCLASSIFIED)
            },
            "coverage": {
                "classified_module_count": classified_module_count,
                "module_count": len(nodes),
            },
            "classified_module_count": classified_module_count,
            "unclassified_module_count": len(unclassified_modules),
            "unclassified_modules": unclassified_modules,
            "root_direct_module_count": len(root_modules),
            "root_classified_count": len(classified_root),
            "root_unclassified_count": len(unclassified_root),
            "root_module_layers": classified_root,
            "root_unclassified_modules": unclassified_root,
        },
        "root_direct_modules": root_modules,
    }


def domain_boundary_baseline_document(
    measurement: Mapping[str, _ModuleGraphAny],
    prior: Mapping[str, _ModuleGraphAny] | None = None,
) -> dict[str, _ModuleGraphAny]:
    exemptions = [] if prior is None else prior.get(
        "unclassified_module_exemptions",
        prior.get("root_module_exemptions", []),
    )
    if not isinstance(exemptions, list):
        raise ValueError("unclassified_module_exemptions must be a list")
    protected_root = (
        measurement["root_direct_modules"]
        if prior is None
        else prior.get("protected_root_modules")
    )
    if not isinstance(protected_root, list):
        raise ValueError("protected_root_modules must be a list")
    root_modules = set(measurement["root_direct_modules"])
    current_non_root_unclassified = sorted(
        set(measurement["classification"]["unclassified_modules"]) - root_modules
    )
    protected_non_root = (
        current_non_root_unclassified
        if prior is None or "protected_non_root_unclassified_modules" not in prior
        else prior.get("protected_non_root_unclassified_modules")
    )
    if not isinstance(protected_non_root, list):
        raise ValueError("protected_non_root_unclassified_modules must be a list")
    coverage = dict(measurement["classification"]["coverage"])
    if prior is not None and "minimum_classification_coverage" in prior:
        previous_coverage = prior["minimum_classification_coverage"]
        if not valid_coverage_fraction(previous_coverage):
            raise ValueError("minimum_classification_coverage is invalid")
        if coverage_is_lower(coverage, previous_coverage):
            coverage = dict(previous_coverage)

    def threshold(key: str, observed: int) -> int:
        if prior is None or key not in prior:
            return observed
        previous = prior[key]
        if not isinstance(previous, int) or previous < 0:
            raise ValueError(f"{key} must be a non-negative integer")
        return min(previous, observed)

    return {
        "schema_version": DOMAIN_BOUNDARY_SCHEMA_VERSION,
        "graph_definition_id": measurement["graph"]["definition_id"],
        "graph_definition_sha256": measurement["graph"]["definition_sha256"],
        "classification_policy_sha256": measurement["classification"]["policy_sha256"],
        "maximum_ast_only_scc_size": threshold(
            "maximum_ast_only_scc_size",
            measurement["graph"]["largest_cyclic_scc_size"],
        ),
        "maximum_direction_violation_count": threshold(
            "maximum_direction_violation_count",
            measurement["direction"]["violation_count"],
        ),
        "minimum_classification_coverage": coverage,
        "protected_root_modules": protected_root,
        "protected_non_root_unclassified_modules": protected_non_root,
        "unclassified_module_exemptions": exemptions,
    }


def _domain_identity_errors(
    measurement: Mapping[str, _ModuleGraphAny],
    baseline: Mapping[str, _ModuleGraphAny],
) -> list[str]:
    graph = measurement["graph"]
    classification = measurement["classification"]
    errors = []
    for baseline_key, observed, label in (
        ("graph_definition_sha256", graph["definition_sha256"], "module graph definition"),
        (
            "classification_policy_sha256",
            classification["policy_sha256"],
            "classification policy",
        ),
    ):
        if baseline.get(baseline_key) != observed:
            errors.append(
                f"domain boundary {label} drifted; regenerate and review the baseline"
            )
    return errors


def _domain_threshold_errors(
    measurement: Mapping[str, _ModuleGraphAny],
    baseline: Mapping[str, _ModuleGraphAny],
) -> list[str]:
    checks = (
        (
            "maximum_ast_only_scc_size",
            int(measurement["graph"]["largest_cyclic_scc_size"]),
            "largest AST-only SCC",
        ),
        (
            "maximum_direction_violation_count",
            int(measurement["direction"]["violation_count"]),
            "dependency-direction violations",
        ),
    )
    errors = []
    for key, observed, label in checks:
        expected = baseline.get(key)
        if not isinstance(expected, int) or expected < 0:
            errors.append(f"domain boundary baseline {key} must be a non-negative integer")
        elif observed > expected:
            errors.append(
                f"domain boundary {label} increased: current={observed}, maximum={expected}"
            )
    return errors


def evaluate_domain_boundary(
    measurement: Mapping[str, _ModuleGraphAny],
    baseline: Mapping[str, _ModuleGraphAny],
) -> list[str]:
    if baseline.get("schema_version") != DOMAIN_BOUNDARY_SCHEMA_VERSION:
        return [
            "domain boundary baseline schema is invalid; regenerate the governed baseline"
        ]
    return [
        *_domain_identity_errors(measurement, baseline),
        *_domain_threshold_errors(measurement, baseline),
        *classification_ratchet_errors(measurement, baseline),
    ]


def domain_boundary_errors(
    root: Path = ROOT,
) -> tuple[list[str], dict[str, _ModuleGraphAny]]:
    package_root = root / "src/gravity_insight"
    measurement = domain_boundary_measurement(package_root)
    baseline_path = root / DOMAIN_BOUNDARY_BASELINE_PATH.relative_to(ROOT)
    if not baseline_path.is_file():
        return ([f"missing domain boundary baseline {baseline_path.relative_to(root)}"], measurement)
    try:
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return ([f"invalid domain boundary baseline: {exc}"], measurement)
    if not isinstance(baseline, dict):
        return (["domain boundary baseline must be a JSON object"], measurement)
    return evaluate_domain_boundary(measurement, baseline), measurement


def _write_json(path: Path, document: Mapping[str, _ModuleGraphAny]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _domain_boundary_cli(argv: Sequence[str]) -> int:
    parser = _module_graph_argparse.ArgumentParser(
        description="Measure and ratchet the governed Runtime domain boundary."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    report = subparsers.add_parser("report")
    report.add_argument("--json-out", type=Path)
    baseline = subparsers.add_parser("baseline")
    baseline.add_argument("--write", action="store_true")
    subparsers.add_parser("check")
    args = parser.parse_args(list(argv))
    measurement = domain_boundary_measurement()
    if args.command == "report":
        if args.json_out:
            selected = args.json_out if args.json_out.is_absolute() else ROOT / args.json_out
            _write_json(selected, measurement)
            print(f"wrote {selected}")
        else:
            print(json.dumps(measurement, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "baseline":
        prior = None
        if DOMAIN_BOUNDARY_BASELINE_PATH.is_file():
            prior = json.loads(DOMAIN_BOUNDARY_BASELINE_PATH.read_text(encoding="utf-8"))
        document = domain_boundary_baseline_document(measurement, prior)
        if args.write:
            _write_json(DOMAIN_BOUNDARY_BASELINE_PATH, document)
            print(f"wrote {DOMAIN_BOUNDARY_BASELINE_PATH}")
        else:
            print(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    errors, observed = domain_boundary_errors()
    if errors:
        for error in errors:
            print(f"FAIL domain-boundary: {error}")
        return 1
    print(
        "PASS domain-boundary: "
        f"ast_scc={observed['graph']['largest_cyclic_scc_size']} "
        f"direction_violations={observed['direction']['violation_count']} "
        f"classified={observed['classification']['classified_module_count']}/"
        f"{observed['graph']['node_count']} "
        f"root_modules={observed['classification']['root_direct_module_count']} "
        f"unclassified_root={observed['classification']['root_unclassified_count']}"
    )
    return 0
