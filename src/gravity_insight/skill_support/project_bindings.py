"""Project-owned Semantic and Context binding template renderer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..agent_runtime_contracts import validate_schema
from ..skill_contract import skill_uri


_PROJECT_BINDINGS_SCHEMA = "skill-project-bindings-template-v1.schema.json"
_SEMANTIC_KINDS = {
    "metric",
    "dimension",
    "entity",
    "cohort",
    "event",
    "sku",
    "activity",
    "release",
    "schema",
}


def render_project_bindings_template(contract: Mapping[str, Any]) -> dict[str, Any]:
    identity = skill_uri(contract)
    semantic_dependencies = [
        _semantic_binding_template(uri, contract)
        for uri in contract["semantic_dependencies"]
    ]
    context_dependencies = [
        _context_binding_template(uri, contract, required=True)
        for uri in contract["context_dependencies"]["required"]
    ] + [
        _context_binding_template(uri, contract, required=False)
        for uri in contract["context_dependencies"]["optional"]
    ]
    result = {
        "artifact_kind": "skill_project_bindings_template",
        "schema_version": "gravity.skill-project-bindings-template.v1",
        "skill_uri": identity,
        "project_placeholders": {
            "project_id": "<project-id>",
            "owner": "<project-owner>",
            "app_alias": "<project-app-alias>",
            "journey_id": "<project-journey-id>",
            "semantic_source_path": "<tracked-semantic-source-relative-path>",
        },
        "semantic_dependencies": semantic_dependencies,
        "semantic_source_template": _semantic_source_template(
            contract, semantic_dependencies
        ),
        "context_dependencies": context_dependencies,
        "overlay_template": _overlay_template(
            contract, identity, context_dependencies
        ),
        "remedies": _remedies(semantic_dependencies, context_dependencies),
    }
    validate_schema(
        result,
        _PROJECT_BINDINGS_SCHEMA,
        "Skill project bindings template",
    )
    return result


def _semantic_binding_template(
    uri: str, contract: Mapping[str, Any]
) -> dict[str, Any]:
    kind = str(uri).split("://", 1)[0]
    if kind not in _SEMANTIC_KINDS:
        kind = "<approved-semantic-kind>"
    return {
        "uri": uri,
        "required_fields": [
            "owner",
            "display_name",
            "description",
            "effective_range",
            "unit_aggregation_time_formula_when_metric",
            "claim_policy",
            "app_alias",
            "physical_provider",
            "parameters",
        ],
        "definition_template": _semantic_definition_template(uri, kind),
        "binding_template": _semantic_physical_binding_template(uri, contract),
    }


def _semantic_definition_template(uri: str, kind: str) -> dict[str, Any]:
    metric = kind == "metric"
    return {
        "artifact_kind": "semantic_definition",
        "schema_version": "gravity.semantic-definition.v1",
        "uri": uri,
        "kind": kind,
        "version": int(uri.rsplit("@", 1)[1]),
        "owner": "<project-owner>",
        "authority": "project",
        "display_name": "<project-definition-display-name>",
        "description": "<project-business-definition>",
        "effective_range": {
            "start": "<YYYY-MM-DD-or-null>",
            "end": "<YYYY-MM-DD-or-null>",
        },
        "unit": (
            {
                "kind": "<approved-unit-kind>",
                "symbol": "<unit-symbol>",
                "currency": "<uppercase-currency-or-null>",
                "scale": "<integer-0-through-12>",
            }
            if metric
            else None
        ),
        "aggregation": (
            {
                "method": "<approved-aggregation-method>",
                "additivity": "<approved-additivity>",
            }
            if metric
            else None
        ),
        "time": (
            {
                "grains": ["<approved-time-grain>"],
                "timezone": "<IANA-timezone>",
                "attribution_window": None,
            }
            if metric
            else None
        ),
        "entity_uri": "<versioned-entity-uri>" if metric else None,
        "formula": (
            {
                "operator": "<source|sum|difference|ratio>",
                "dependencies": [],
                "parameters": [],
            }
            if metric
            else None
        ),
        "binding_required": True,
        "claim_policy": {
            "allowed": ["<allowed-project-claim>"],
            "forbidden": ["<forbidden-project-claim>"],
        },
    }


def _semantic_physical_binding_template(
    uri: str, contract: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "artifact_kind": "semantic_binding",
        "schema_version": "gravity.semantic-binding.v1",
        "binding_uri": (
            f"binding://project.<project-id>/{contract['skill_id']}-binding@1"
        ),
        "semantic_uri": uri,
        "project_id": "<project-id>",
        "owner": "<project-owner>",
        "app_alias": "<project-app-alias>",
        "effective_range": {
            "start": "<YYYY-MM-DD-or-null>",
            "end": "<YYYY-MM-DD-or-null>",
        },
        "provider": {
            "kind": "semantic_compose",
            "definition": {
                "definition_id": "<registered-semantic-compose-definition-id>",
                "version": "<positive-integer>",
            },
            "members": {
                "metric": {
                    "definition_id": "<registered-member-definition-id>",
                    "version": "<positive-integer>",
                }
            },
        },
        "parameters": {},
    }


def _semantic_source_template(
    contract: Mapping[str, Any], dependencies: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    return {
        "artifact_kind": "semantic_source",
        "schema_version": "gravity.semantic-source.v1",
        "source_id": f"<project-id>/{contract['skill_id']}",
        "source_kind": "project_json",
        "project_id": "<project-id>",
        "owner": "<project-owner>",
        "definitions": [item["definition_template"] for item in dependencies],
        "bindings": [item["binding_template"] for item in dependencies],
    }


def _context_binding_template(
    uri: str, contract: Mapping[str, Any], *, required: bool
) -> dict[str, Any]:
    return {
        "uri": uri,
        "required": required,
        "required_fields": [
            "subject_entities",
            "required_windows",
            "authority_policy",
            "allowed_sensitivity",
            "freshness_policy",
            "budget",
            "tracked_item",
        ],
        "requirement_template": {
            "artifact_kind": "context_requirement",
            "schema_version": "gravity.context-requirement.v1",
            "requirement_id": uri,
            "provider_uri": "context-provider://gravity/project-repo@1",
            "skill_uri": skill_uri(contract),
            "journey_id": "<project-journey-id>",
            "subject_entities": ["<versioned-project-entity-uri>"],
            "required_windows": ["current", "reference"],
            "authority_policy": {
                "required": ["<project_authoritative|canonical|supporting>"],
                "allow_supporting": False,
                "allow_declared_intent": False,
                "allow_unverified": False,
            },
            "allowed_sensitivity": [
                "<public|internal|confidential|restricted>"
            ],
            "freshness_policy": {
                "as_of": "<YYYY-MM-DD-or-null>",
                "max_age_days": "<nonnegative-integer-or-null>",
            },
            "budget": {
                "max_files": "<positive-integer>",
                "max_file_bytes": "<positive-integer>",
                "max_total_bytes": "<positive-integer>",
                "max_total_lines": "<positive-integer>",
            },
            "items": [_context_item_template(required)],
        },
    }


def _context_item_template(required: bool) -> dict[str, Any]:
    return {
        "item_id": "<lowercase-context-item-id>",
        "fact_id": "<lowercase-fact-id>",
        "required": required,
        "path": "<tracked-source-of-record-relative-path>",
        "title": "<source-of-record-title>",
        "resource_type": (
            "<document|code|configuration|contract|release|project_semantic>"
        ),
        "entity_refs": ["<versioned-project-entity-uri>"],
        "valid_time": {
            "start": "<YYYY-MM-DD-or-null>",
            "end": "<YYYY-MM-DD-or-null>",
            "timezone": "<IANA-timezone>",
        },
        "effective_range": {
            "start": "<YYYY-MM-DD-or-null>",
            "end": "<YYYY-MM-DD-or-null>",
        },
        "authority": "<project_authoritative|canonical|supporting>",
        "sensitivity": "<public|internal|confidential|restricted>",
        "supersedes": [],
        "max_age_days": "<nonnegative-integer-or-null>",
    }


def _overlay_template(
    contract: Mapping[str, Any],
    identity: str,
    context_dependencies: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "artifact_kind": "project_skill_overlay",
        "schema_version": "gravity.project-skill-overlay.v1",
        "overlay_uri": f"skill://project.<project-id>/{contract['skill_id']}@1.0.0",
        "version": "1.0.0",
        "project_id": "<project-id>",
        "owner": "<project-owner>",
        "extends": {"skill_uri": identity},
        "journey_id": "<project-journey-id>",
        "semantic_sources": ["<tracked-semantic-source-relative-path>"],
        "semantic_scope": {"app_alias": "<project-app-alias>"},
        "context_requirements": [
            item["requirement_template"] for item in context_dependencies
        ],
        "default_scope": {"app_alias": "<project-app-alias>"},
    }


def _remedies(
    semantic_dependencies: Sequence[Mapping[str, Any]],
    context_dependencies: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    semantic = [
        {
            "dependency_uri": str(item["uri"]),
            "reason_code": "SEMANTIC_DEFINITION_MISSING",
            "next_action": (
                "Fill the project-owned Definition and Binding in "
                "semantic_source_template, commit the source and Project Overlay, "
                "then retry exact resolution."
            ),
        }
        for item in semantic_dependencies
    ]
    context = [
        {
            "dependency_uri": str(item["uri"]),
            "reason_code": "CONTEXT_REQUIRED_MISSING",
            "next_action": (
                "Fill the project-repo Context Requirement and tracked "
                "source-of-record item, commit the Project Overlay, then retry "
                "exact resolution."
            ),
        }
        for item in context_dependencies
        if item["required"]
    ]
    return semantic + context


__all__ = ["render_project_bindings_template"]
