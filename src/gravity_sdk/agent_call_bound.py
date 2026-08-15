"""Machine-readable CLI/SDK call lower bounds for Agent handoffs."""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from ._field_policy_operations import ANALYSIS_SEGMENT, PROMOTION_METRIC
from .dashboard_snapshot import TREE_OPERATION
from .domains import MULTIDIM_METADATA_OPERATIONS
from .metadata_sync import APP_OPERATION_ID
from .saved_analysis_catalog import LIST_OPERATION_ID


SCHEMA_VERSION = "gravity.agent-call-bound.v1"
UNIT = "cli_or_sdk_invocation"

_APP_SOURCE = {
    "inputs": ["app"],
    "kind": "upstream_catalog",
    "selector": APP_OPERATION_ID,
    "cli_argv": ["gravity", "apps", "list", "--all-pages", "--format", "ndjson"],
    "sdk_method": "GravitySDK.read_all",
    "depends_on_inputs": [],
    "depends_on_sources": [],
}
_REFERENCE_SOURCES: Mapping[str, tuple[str, list[str], str, bool]] = {
    "dashboard_analysis": (
        TREE_OPERATION,
        ["gravity", "run", TREE_OPERATION, "--input", "<app-input.json>"],
        "GravitySDK.read",
        True,
    ),
    "dashboard_snapshot": (
        TREE_OPERATION,
        ["gravity", "run", TREE_OPERATION, "--input", "<app-input.json>"],
        "GravitySDK.read",
        True,
    ),
    "saved_analysis": (
        LIST_OPERATION_ID,
        ["gravity", "analysis", "saved", "list", "--app", "<app>"],
        "GravitySDK.saved_analyses",
        True,
    ),
    "segment_snapshot": (
        ANALYSIS_SEGMENT,
        [
            "gravity", "run", ANALYSIS_SEGMENT, "--input", "<app-input.json>",
            "--all-pages", "--format", "ndjson",
        ],
        "GravitySDK.read_all",
        True,
    ),
    "segment_members": (
        ANALYSIS_SEGMENT,
        [
            "gravity", "run", ANALYSIS_SEGMENT, "--input", "<app-input.json>",
            "--all-pages", "--format", "ndjson",
        ],
        "GravitySDK.read_all",
        True,
    ),
    "analysis_template": (
        "analysis.template.catalog",
        ["gravity", "analysis", "template", "list"],
        "GravitySDK.analysis_templates",
        False,
    ),
}


def call_bound_for_card(card: Mapping[str, Any]) -> dict[str, Any]:
    """Return a fresh additive contract; ordinary cards retain the 1/2 default."""

    bound: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "unit": UNIT,
        "known_inputs": 1,
        "unknown_capability": 2,
        "unknown_capability_assumes": "required_inputs_known",
        "scenarios": [],
    }
    required = frozenset(str(value) for value in card.get("required_inputs", ()))
    app_inputs = sorted(required & {"app", "apps", "app_id"})
    if app_inputs:
        bound["scenarios"].append(
            _scenario(
                "unknown_app",
                3,
                1,
                app_inputs,
                [_source_for_inputs(_APP_SOURCE, app_inputs)],
            )
        )
    composite = str(card.get("composite", ""))
    if composite in _REFERENCE_SOURCES:
        selector, argv, sdk_method, app_scoped = _REFERENCE_SOURCES[composite]
        reference_inputs = ["scope", "ref"] if composite == "analysis_template" else ["ref"]
        reference_source = _source(
            reference_inputs,
            "upstream_catalog",
            selector,
            argv,
            sdk_method,
            ["app"] if app_scoped else [],
        )
        bound["scenarios"].append(
            _scenario("unknown_reference", 3, 1, reference_inputs, [reference_source])
        )
        if app_inputs:
            sources = [_source_for_inputs(_APP_SOURCE, app_inputs), reference_source]
            discovery_calls = 2
            bound["scenarios"].append(
                _scenario(
                    "unknown_app_and_reference",
                    discovery_calls + 2,
                    discovery_calls,
                    [*app_inputs, *reference_inputs],
                    sources,
                )
            )
    _add_physical_input_scenarios(bound, card, composite, app_inputs)
    _add_catalog_scenarios(bound, card, app_inputs)
    return copy.deepcopy(bound)


def _add_physical_input_scenarios(
    bound: dict[str, Any],
    card: Mapping[str, Any],
    composite: str,
    app_inputs: list[str],
) -> None:
    source: dict[str, Any] | None = None
    unknown_inputs: list[str] = []
    if composite == "multidim":
        unknown_inputs = [
            "inputs.metrics_list",
            "inputs.custom_metrics_list",
            "inputs.data_dims",
            "inputs.relate_dims",
        ]
        source = _source(
            unknown_inputs,
            "upstream_catalog",
            "multidim.metadata",
            ["gravity", "multidim", "metadata"],
            "GravitySDK.read_many",
        )
    elif composite == "promotion_performance":
        unknown_inputs = ["metrics"]
        source = _source(
            unknown_inputs,
            "upstream_catalog",
            PROMOTION_METRIC,
            ["gravity", "batch", "read", "--input", "<platform-metric-requests.json>"],
            "GravitySDK.read_many",
            ["platforms"],
        )
    if source is None:
        return
    bound["scenarios"].append(
        _scenario(
            "unknown_physical_inputs",
            3,
            1,
            unknown_inputs,
            [source],
        )
    )
    if app_inputs:
        sources, discovery_calls = _combined_physical_sources(
            composite, app_inputs, unknown_inputs, source
        )
        bound["scenarios"].append(
            _scenario(
                "unknown_app_and_physical_inputs",
                discovery_calls + 2,
                discovery_calls,
                [*app_inputs, *unknown_inputs],
                sources,
            )
        )


def _combined_physical_sources(
    composite: str,
    app_inputs: list[str],
    unknown_inputs: list[str],
    physical_source: dict[str, Any],
) -> tuple[list[dict[str, Any]], int]:
    inputs = [*app_inputs, *unknown_inputs]
    if composite == "multidim":
        return [
            _batch_source(
                inputs,
                [APP_OPERATION_ID, *MULTIDIM_METADATA_OPERATIONS],
                "<app-and-multidim-catalogs.json>",
            )
        ], 1
    if composite == "promotion_performance":
        return [
            _batch_source(
                inputs,
                [APP_OPERATION_ID, PROMOTION_METRIC],
                "<app-and-platform-metric-catalogs.json>",
                depends_on_inputs=["platforms"],
            )
        ], 1
    return [_source_for_inputs(_APP_SOURCE, app_inputs), physical_source], 2


def _add_catalog_scenarios(
    bound: dict[str, Any], card: Mapping[str, Any], app_inputs: list[str]
) -> None:
    if card.get("kind") != "analysis_task" or card.get("catalog_missing") is not True:
        return
    sync_source = _source(
        ["spec.physical_fields"],
        "catalog_sync",
        "metadata.sync",
        ["gravity", "metadata", "sync", "--all-apps"],
        "gravity_sdk.metadata_sync.sync_all_apps",
    )
    catalog_source = _source(
        ["spec.physical_fields"],
        "local_catalog",
        "agent.metadata_catalog",
        ["gravity", "agent", "<same-analysis-query>"],
        "GravitySDK.capabilities",
        depends_on_sources=["metadata.sync"],
    )
    bound["scenarios"].append(
        _scenario(
            "physical_inputs_catalog_unsynced",
            4,
            2,
            ["spec.physical_fields"],
            [sync_source, catalog_source],
            catalog_status="missing",
        )
    )
    if app_inputs:
        bound["scenarios"].append(
            _scenario(
                "unknown_app_and_physical_inputs_catalog_unsynced",
                5,
                3,
                [*app_inputs, "spec.physical_fields"],
                [
                    sync_source,
                    _source_for_inputs(_APP_SOURCE, app_inputs),
                    catalog_source,
                ],
                catalog_status="missing",
            )
        )


def _scenario(
    scenario_id: str,
    minimum_calls: int,
    discovery_calls: int,
    unknown_inputs: list[str],
    input_sources: list[dict[str, Any]],
    *,
    catalog_status: str = "any",
) -> dict[str, Any]:
    return {
        "id": scenario_id,
        "minimum_calls": minimum_calls,
        "discovery_calls": discovery_calls,
        "unknown_inputs": unknown_inputs,
        "input_sources": input_sources,
        "selection": "caller_exact",
        "catalog_status": catalog_status,
    }


def _source(
    inputs: list[str],
    kind: str,
    selector: str,
    cli_argv: list[str],
    sdk_method: str,
    depends_on_inputs: list[str] | None = None,
    depends_on_sources: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "inputs": list(inputs),
        "kind": kind,
        "selector": selector,
        "cli_argv": list(cli_argv),
        "sdk_method": sdk_method,
        "depends_on_inputs": list(depends_on_inputs or ()),
        "depends_on_sources": list(depends_on_sources or ()),
    }


def _source_for_inputs(source: Mapping[str, Any], inputs: list[str]) -> dict[str, Any]:
    selected = copy.deepcopy(dict(source))
    selected["inputs"] = list(inputs)
    return selected


def _batch_source(
    inputs: list[str],
    selectors: list[str],
    input_file: str,
    *,
    depends_on_inputs: list[str] | None = None,
) -> dict[str, Any]:
    return {
        **_source(
            inputs,
            "upstream_catalog",
            "gravity.batch.v1",
            ["gravity", "batch", "read", "--input", input_file],
            "GravitySDK.read_many",
            depends_on_inputs,
        ),
        "selectors": selectors,
    }


__all__ = ["SCHEMA_VERSION", "UNIT", "call_bound_for_card"]
