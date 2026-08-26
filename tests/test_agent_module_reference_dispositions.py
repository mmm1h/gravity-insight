"""Validate the reproducible R17 dynamic-reference disposition ledger."""

from __future__ import annotations

import ast
import builtins
from collections import Counter
from collections import deque
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

import scripts.generate_agent_module_reference_dispositions as checkpoint_generator
import scripts.validate_r17_canonical_source_errata as errata_validator
from scripts.audit_agent_module_references import (
    GENERATED_GOVERNANCE_FILES,
    GOVERNANCE_EXCLUSION_RULE,
    Finding,
    ReferenceScanner,
    is_generated_governance_artifact,
    make_module_map,
    scan_repository,
    source_key,
)
from scripts.generate_agent_module_reference_dispositions import (
    ACTIVE_BARE_FILES,
    ACTIVE_REFERENCE,
    AMBIGUOUS_REFERENCE,
    DATED_DECISION_RECORD,
    DELETED_MODULE_RECORD,
    RUNTIME_CONSUMER,
    build_document,
    checkpoint_sites,
    classify_active_bare_context as generator_classify_active_bare_context,
    _classify_reference as generator_classify_reference,
    render_document,
)
from scripts.validate_r17_canonical_source_errata import (
    ErrataValidationError,
    build_expected_source,
    derive_source_replacements,
    load_git_baseline,
    validate_bound_ledger,
    validate_final_state,
    validate_phase1_reviewed_state,
)


ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "tests/fixtures/agent_module_reference_dispositions.json"
CHECKPOINT = ROOT / "tests/fixtures/agent_module_reference_checkpoint.json"
DIRECTIVE = ROOT / "specs/agent-runtime/directive.json"
CANONICAL_SOURCE = ROOT / "specs/agent-runtime/architecture-source.md"
INDEX_JSON = ROOT / "specs/agent-runtime/index.json"
INDEX_MARKDOWN = ROOT / "specs/agent-runtime/index.md"
R17_SPECIFICATION = ROOT / "specs/agent-runtime/R17-agent-module-package-migration.md"
ROADMAP = ROOT / "docs/roadmap.md"
TECHNICAL_DEBT = ROOT / "docs/maintainers/technical-debt.md"
R17_INVENTORY_START = "<!-- R17_INDEPENDENT_INVENTORY_JSON_START -->"
R17_INVENTORY_END = "<!-- R17_INDEPENDENT_INVENTORY_JSON_END -->"
R17_INVENTORY_SCHEMA = "gravity.r17-independent-responsibility-inventory.v1"
R17_RESPONSIBILITY_SCHEMA = "gravity.r17-responsibility-contracts.v1"
R17_RESPONSIBILITY_CONTRACTS_JSON = r"""
{
  "schema_version": "gravity.r17-responsibility-contracts.v1",
  "payload_sha256": "4d71ad27bf5be3269ba94b599dc8b9b10e6e31d55d590ac8447fa05f6fce9777",
  "boundary_policy": {
    "included_owner_layers": [
      "compact_agent_interaction",
      "public_agent_facade"
    ],
    "non_inputs": [
      "direct_consumer_count",
      "directory_path",
      "migration_ledger",
      "module_basename",
      "module_docstring",
      "name_prefix",
      "signed_member_inventory"
    ]
  },
  "responsibilities": [
    {
      "id": "agent-facade",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "declared_schema",
      "entry": {
        "kind": "function",
        "symbol": "discover_capabilities",
        "parameters": ["query", "client", "workspace", "domain", "platform", "limit", "continuation", "sources", "plan_node_namespace", "routing", "host_selection"]
      },
      "output": {
        "return_contract": "dict[str, Any]",
        "required_keys": ["candidates", "capability_gaps", "routing_mode"],
        "key_scope": "owner"
      },
      "owner_layer": "public_agent_facade"
    },
    {
      "id": "advertiser-profile",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "advertiser_profile_plan_request", "parameters": ["_card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["end", "name", "start"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "analysis-query-spec",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "analysis_query_spec_inventory", "parameters": []},
      "output": {"return_contract": "tuple[dict[str, Any], ...]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "analysis-default-dictionary",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "analysis_default_dictionary_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["app", "name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "analysis-task",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "analysis_metadata_candidates", "parameters": ["query", "metadata_rows", "limit"]},
      "output": {"return_contract": "dict[str, list[dict[str, Any]]]", "required_keys": ["events", "metrics", "properties"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "app-catalog",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "app_catalog_capability_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "app-public-info",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "app_public_info_capability_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "attribution-performance",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "attribution_performance_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "attribution-user-detail",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "attribution_user_detail_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "batch-discovery",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "snapshot_failure", "parameters": ["questions"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["results", "schema_version", "status"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "batch-question-validation",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "validate_question", "parameters": ["value", "index"]},
      "output": {"return_contract": "CapabilityQuestion", "required_keys": ["query"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "batch-source-snapshot",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "snapshot_recipes", "parameters": ["workspace"]},
      "output": {"return_contract": "tuple[Mapping[str, Any], ...]", "required_keys": ["name", "operation_id", "required_parameters"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "bilibili-account-performance",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "bilibili_account_performance_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "business-pulse",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "business_pulse_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["apps", "end", "start"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "call-bound",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "call_bound_for_card", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["known_inputs", "schema_version", "unit"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "caller-language",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "caller_language_fields", "parameters": ["selector"]},
      "output": {"return_contract": "tuple[str, ...]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "capability-matching",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "operation_query_match", "parameters": ["query", "item"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["confidence", "matched_terms", "missing_terms"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "agent-catalog",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "run_agent_catalog_command", "parameters": ["args", "client"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "catalog-parity",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "validate_catalog_parity", "parameters": ["inventory", "product_cards", "operations", "gaps"]},
      "output": {"return_contract": "None", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "catalog-refresh",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "refresh_complete_catalog", "parameters": ["client", "include_table_lineage", "database"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["database"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "deferred-client",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "class", "symbol": "DeferredAgentClient", "parameters": ["factory"]},
      "output": {"return_contract": "DeferredAgentClient", "required_keys": ["loaded_attribute"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "company-usage",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "company_usage_plan_request", "parameters": ["_card"]},
      "output": {"return_contract": "dict[str, str]", "required_keys": ["name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "composite-card",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "composite_card", "parameters": ["query", "normalized", "domain", "definition"]},
      "output": {"return_contract": "dict[str, Any] | None", "required_keys": ["composite", "kind", "selector"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "composite-inventory",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "constant", "symbol": "COMPOSITE_CAPABILITIES", "parameters": []},
      "output": {"return_contract": "tuple[Mapping[str, Any], ...]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "custom-audience",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "custom_audience_plan_request", "parameters": ["_card"]},
      "output": {"return_contract": "dict[str, str]", "required_keys": ["name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "custom-metric",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "custom_metric_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "dashboard",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "dashboard_analysis_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["mode", "name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "derived-metrics",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "derived_metrics_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "discovery-policy",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "operation_fallback_gap", "parameters": ["query"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": ["kind", "next_action", "reason"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "discovery-support",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "unranked_operations_gap", "parameters": ["query", "operation_ids"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["kind", "next_action", "reason"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "export-discovery",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "material_export_capability_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": ["effect", "kind", "selector"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "fixed-snapshots",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "fixed_snapshot_query", "parameters": ["name", "query"]},
      "output": {"return_contract": "bool", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "capability-gap",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "unavailable_gap", "parameters": ["query", "code", "journey", "reason", "next_action", "argv"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["code", "kind", "reason"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "agent-handoff",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "agent_execution_contract", "parameters": ["workspace_path"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["argv", "bounded_stdout", "input_forms"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "host-catalog",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "host_selection_upgrade_contract", "parameters": ["query"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["next_action", "selection_schema", "when"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "host-selection",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "compile_host_product_selection", "parameters": ["query", "response", "client"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["catalog_sha256", "schema_version", "selected_catalog_refs"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "input-catalogs",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "live_catalog_for_card", "parameters": ["card", "client", "workspace", "known_inputs"]},
      "output": {"return_contract": "dict[str, Any] | None", "required_keys": ["catalogs", "schema_version", "status"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "input-resolution",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "resolve_capabilities", "parameters": ["query", "known_inputs", "client", "workspace", "domain", "platform", "limit"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "intent-routing",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "product_selection_gap", "parameters": ["query", "selectors", "reason"]},
      "output": {"return_contract": "dict[str, object]", "required_keys": ["candidate_selectors", "code", "reason"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "intent-text",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "affirmative_intent_text", "parameters": ["query"]},
      "output": {"return_contract": "str", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "kanban-mutation",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "kanban_mutation_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "lexical-rescue",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "indexed_evidence_rescue", "parameters": ["documents", "query_terms", "document_terms", "idf"]},
      "output": {"return_contract": "IndexedEvidenceDecision", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "lexical-retrieval",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "selected_candidate", "parameters": ["match"]},
      "output": {"return_contract": "tuple[str, Mapping[str, Any]] | None", "required_keys": ["confidence", "matched_terms", "missing_terms"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "material-asset",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "material_asset_capability_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": ["artifact_schema_version", "output_root_bound", "selector"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "material-performance",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "material_performance_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "metadata-onboarding",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "metadata_onboarding_capability_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "metadata-search",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "metadata_search_capability_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "metadata-template",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "metadata_template_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "monetization-aggregate",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "monetization_aggregate_capability_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "monetization-guard",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "monetization_detail_plan_request", "parameters": ["_card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "multidim",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "multidim_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["app", "inputs", "name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "mutation-cards",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "mutation_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "operation-contract",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "operation_contract_overlay", "parameters": ["client", "operation", "extra"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["effect", "pagination", "supported"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "order-directory",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "order_directory_plan_request", "parameters": ["_card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "order-trace",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "order_split_trace_plan_request", "parameters": ["_card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "output-envelope",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "ndjson_metadata", "parameters": ["value"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["capability_gaps", "routing_mode", "total"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "pagination-completeness",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "compact_pagination", "parameters": ["value"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["completeness", "pagination_evidence", "supported"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "product-inventory",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "canonical_capability_cards", "parameters": ["client"]},
      "output": {"return_contract": "tuple[dict[str, Any], ...]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "promotion-performance",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "promotion_performance_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "realtime-event-mutation",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "realtime_event_mutation_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "realtime-event-catalog",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "realtime_event_catalog_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["app", "end", "start"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "report-directory",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "report_read_plan_request", "parameters": ["name", "_card"]},
      "output": {"return_contract": "dict[str, str]", "required_keys": ["name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "report-mutation",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "report_mutation_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "report-routing",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "report_product_plan_request", "parameters": ["name", "card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "saved-analysis",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "saved_analysis_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["app", "name", "ref"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "saved-analysis-mutation",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "saved_analysis_mutation_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "segment",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "segment_rule_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["app", "name", "spec"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "segment-members",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "segment_members_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["app", "name", "ref"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "segment-snapshot",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "segment_snapshot_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["app", "date", "ref"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "semantic-compose",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "semantic_compose_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["app", "inputs", "name"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "semantic-context",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "load_agent_workspace", "parameters": ["workspace", "sources"]},
      "output": {"return_contract": "Any | None", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "semantic-derived",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "multiple_gap", "parameters": ["query", "selectors"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["candidate_selectors", "code", "reason"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "source-discovery",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "snapshot_recipe_cards", "parameters": ["query", "inventory"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": ["kind", "recipe", "selector"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "sql-product-discovery",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "apply_workspace_sql_owner", "parameters": ["query", "workspace", "sources"]},
      "output": {"return_contract": "AppliedLexicalFallback", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "sql-product-gap",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "registered_sql_product_gap", "parameters": ["query"]},
      "output": {"return_contract": "dict[str, Any] | None", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "table-lineage",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "table_lineage_capability_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": ["metadata_kind", "scope", "selector"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "title-package",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "title_package_plan_request", "parameters": ["card"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["app", "name", "package_kind"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "unavailable-journey",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "unavailable_journey_gap", "parameters": ["query"]},
      "output": {"return_contract": "dict[str, Any] | None", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "unavailable-analysis",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "unavailable_analysis_gap", "parameters": ["query"]},
      "output": {"return_contract": "dict[str, Any] | None", "required_keys": ["candidate_selectors", "reason_code", "selection_required"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "unavailable-promotion",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "unavailable_promotion_gap", "parameters": ["query"]},
      "output": {"return_contract": "dict[str, Any] | None", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "unavailable-report",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "unavailable_report_gap", "parameters": ["query"]},
      "output": {"return_contract": "dict[str, Any] | None", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "user-journey",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "user_journey_capability_cards", "parameters": ["query", "domain", "platform"]},
      "output": {"return_contract": "list[dict[str, Any]]", "required_keys": []},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "vocabulary",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "vocabulary_card_fields", "parameters": ["item", "query"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["scope", "selector", "source"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "relative-date-resolution",
      "service_protocol": "gravity.agent.v1",
      "protocol_binding": "facade_reachable",
      "entry": {"kind": "function", "symbol": "fill_agent_relative_dates", "parameters": ["card", "query", "workspace", "now"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["resolved_date_window", "start", "end"]},
      "owner_layer": "compact_agent_interaction"
    },
    {
      "id": "runtime-contracts",
      "service_protocol": "JsonSchemaValidator",
      "protocol_binding": "schema_validator",
      "entry": {"kind": "function", "symbol": "validate_schema", "parameters": ["value", "schema_name", "label"]},
      "output": {"return_contract": "None", "required_keys": [], "raises": ["AgentRuntimeContractError"]},
      "owner_layer": "shared_runtime_contract"
    },
    {
      "id": "find",
      "service_protocol": "gravity.find.v1",
      "protocol_binding": "declared_schema",
      "entry": {"kind": "function", "symbol": "run_find_command", "parameters": ["args", "client", "workspace"]},
      "output": {"return_contract": "dict[str, Any]", "required_keys": ["results", "schema_version", "status"]},
      "owner_layer": "independent_primary_protocol"
    }
  ]
}

"""
R17_COCHANGE_BASELINE = "f2e8eec1f3c0567e20ab8c0be6465cc4e2c52e59"
R17_ORACLE_BASELINE_COMMIT = "ddbca7aca1b7baee2ee42e96f886d7ddaee84947"
R17_ORACLE_TREE_OID = "aebfca0423628ea36b48f227435abf6854400c00"
R17_ROLE_MARKERS = (
    ("agent_role", r"\bagent\b"),
    ("natural_language_boundary", r"natural-language"),
    ("caller_language", r"caller-language"),
    ("agent_facing", r"agent-facing"),
    ("host_product_selection", r"product-selection"),
    ("intent_boundary", r"\bintent\b"),
    ("lexical_retrieval", r"\blexical\b"),
    ("semantic_gap_support", r"semantic gaps?"),
    ("unavailable_journey", r"unavailable .*journey"),
    ("catalog_aware_discovery", r"catalog-aware discovery"),
    ("lazy_discovery_client", r"lazy client boundary"),
)
R17_PROTOCOL_PATTERN = re.compile(r"gravity\.[a-z0-9_.-]+\.v[0-9]+")
LEDGER_SHA256 = "9d5b4d197cd84a0da4bb644256c9df7670ec89b7258e710434ab1ac8fed8be20"
EXPECTED_CATEGORIES = {
    "agent_prefix_template": 2,
    "bare_agent_string": 101,
    "dynamic_import": 11,
    "module_owner_receiver": 7,
    "non_string_patch_expression": 117,
}
EXPECTED_DISPOSITIONS = {
    "no_migration_effect": 224,
    "rewrite_reference": 13,
    "rewrite_selector_data": 1,
}
ALLOWED_DISPOSITIONS = {
    "rewrite_reference",
    "rewrite_selector_data",
    "rewrite_consolidated_reference",
    "no_migration_effect",
    "runtime_verification_required",
    "blocker",
}
PAGINATION_MODULE = "gravity_sdk.agent_pagination"
PAGINATION_TARGET = "gravity_sdk.pagination_completeness"
RETAINED_MODULE = "gravity_sdk.agent_runtime_contracts"
FROZEN_BASELINE_EXCLUSION_RULE = (
    "Exclude only tmp/**, direct specs/agent-runtime/R17-*.md migration "
    "specifications, the checked-in disposition fixture and its validator, and "
    "the two scripts that produce this audit. These paths define, generate, or "
    "validate R17 governance metadata rather than consume migrated runtime "
    "modules. Do not exclude AGENTS.md; specs/agent-runtime/architecture-source.md, "
    "index.json, or index.md; docs/maintainers/technical-debt.md; "
    "tests/agent_migration_characterization.py; or any other src, docs, specs, "
    "or tests path."
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _canonical_sites_sha256(sites: list[dict[str, Any]]) -> str:
    return hashlib.sha256(
        json.dumps(
            sites,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _r17_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _r17_module_id(name: str, namespace: str = "gravity_sdk") -> str:
    if name == namespace:
        return "."
    prefix = namespace + "."
    _require(name.startswith(prefix), f"module is outside {namespace}: {name}")
    return name.removeprefix(prefix)


def _r17_assigned_string(
    node: ast.Assign | ast.AnnAssign, name: str
) -> str | None:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
        return None
    value = node.value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value
    return None


def _r17_frozen_tree_blobs(prefix: str) -> dict[str, bytes]:
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "-z", R17_ORACLE_TREE_OID, "--", prefix],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    entries: list[tuple[str, str]] = []
    for raw_entry in listing.split(b"\0"):
        if not raw_entry:
            continue
        metadata, raw_path = raw_entry.split(b"\t", 1)
        _mode, object_type, raw_oid = metadata.split(b" ")
        _require(object_type == b"blob", f"non-blob frozen entry: {raw_path!r}")
        entries.append((raw_path.decode("utf-8"), raw_oid.decode("ascii")))
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    request = "".join(f"{oid}\n" for _, oid in entries).encode("ascii")
    stdout, stderr = process.communicate(request)
    _require(
        process.returncode == 0,
        f"cannot read frozen tree: {stderr.decode('utf-8', errors='replace')}",
    )
    blobs: dict[str, bytes] = {}
    offset = 0
    for path, expected_oid in entries:
        line_end = stdout.index(b"\n", offset)
        oid, object_type, raw_size = stdout[offset:line_end].split(b" ")
        _require(
            oid.decode("ascii") == expected_oid and object_type == b"blob",
            f"unexpected frozen object header: {path}",
        )
        size = int(raw_size)
        start = line_end + 1
        end = start + size
        blobs[path] = stdout[start:end]
        _require(stdout[end : end + 1] == b"\n", f"unterminated blob: {path}")
        offset = end + 1
    return blobs


def _r17_frozen_blob(path: str) -> bytes:
    return _r17_frozen_tree_blobs(path)[path]


def _r17_non_docstring_strings(tree: ast.Module) -> set[str]:
    docstring_nodes = {
        node.body[0].value
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node not in docstring_nodes
    }


def _r17_read_modules(
    package_root: Path | None,
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if package_root is None:
        package_name = "gravity_sdk"
        source_rows = [
            (ROOT / path, raw.decode("utf-8"))
            for path, raw in sorted(
                _r17_frozen_tree_blobs("src/gravity_sdk").items()
            )
            if path.endswith(".py")
        ]
        source_root = ROOT / "src/gravity_sdk"
    else:
        package_name = package_root.name
        source_rows = [
            (path, path.read_text(encoding="utf-8"))
            for path in sorted(package_root.rglob("*.py"))
        ]
        source_root = package_root
    for path, source in source_rows:
        parts = list(path.relative_to(source_root).with_suffix("").parts)
        is_package = parts[-1] == "__init__"
        if is_package:
            parts.pop()
        name = package_name + ("." + ".".join(parts) if parts else "")
        filename = (
            str(path)
            if package_root is not None
            else f"{R17_ORACLE_TREE_OID}:{path.relative_to(ROOT).as_posix()}"
        )
        tree = ast.parse(source, filename=filename)
        strings = _r17_non_docstring_strings(tree)
        schemas = [
            value
            for node in tree.body
            if isinstance(node, (ast.Assign, ast.AnnAssign))
            if (value := _r17_assigned_string(node, "SCHEMA_VERSION")) is not None
        ]
        commands: set[str] = set()
        response_keys: set[str] = set()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and node.args
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_parser"
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                commands.add(node.args[0].value)
            if isinstance(node, ast.Dict):
                response_keys.update(
                    key.value
                    for key in node.keys
                    if isinstance(key, ast.Constant) and isinstance(key.value, str)
                )
        records[name] = {
            "path": path,
            "package": is_package,
            "source": source,
            "tree": tree,
            "protocols": tuple(sorted(
                value for value in strings if R17_PROTOCOL_PATTERN.fullmatch(value)
            )),
            "schemas": tuple(sorted(schemas)),
            "functions": frozenset(
                node.name
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ),
            "commands": tuple(sorted(commands)),
            "response_keys": frozenset(response_keys),
        }
    return records


def _r17_read_legacy_modules(
    package_root: Path | None,
) -> dict[str, dict[str, Any]]:
    records = _r17_read_modules(package_root)
    for record in records.values():
        record["docstring"] = ast.get_docstring(record["tree"]) or ""
    return records


def _r17_existing(name: str, modules: set[str]) -> str | None:
    parts = name.split(".")
    for size in range(len(parts), 0, -1):
        candidate = ".".join(parts[:size])
        if candidate in modules:
            return candidate
    return None


def _r17_import_base(source: str, package: bool, node: ast.ImportFrom) -> str:
    if node.level == 0:
        return node.module or ""
    parts = (source if package else source.rpartition(".")[0]).split(".")
    if node.level > 1:
        parts = parts[: -(node.level - 1)]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _r17_import_graph(
    records: dict[str, dict[str, Any]],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    modules = set(records)
    graph = {name: set() for name in modules}
    for source, record in records.items():
        for node in ast.walk(record["tree"]):
            targets: list[str | None]
            if isinstance(node, ast.Import):
                targets = [_r17_existing(alias.name, modules) for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = _r17_import_base(source, record["package"], node)
                targets = [_r17_existing(base, modules)] if node.module else []
                targets.extend(
                    f"{base}.{alias.name}"
                    if f"{base}.{alias.name}" in modules
                    else None
                    for alias in node.names
                    if alias.name != "*"
                )
            else:
                continue
            graph[source].update(
                target for target in targets if target is not None and target != source
            )
    reverse = {name: set() for name in modules}
    for source, targets in graph.items():
        for target in targets:
            reverse[target].add(source)
    return graph, reverse


def _r17_contract_parameters(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    *, drop_receiver: bool = False,
) -> tuple[str, ...]:
    parameters = [
        argument.arg for argument in (*node.args.posonlyargs, *node.args.args)
    ]
    if drop_receiver and parameters[:1] in (["self"], ["cls"]):
        parameters.pop(0)
    if node.args.vararg is not None:
        parameters.append("*" + node.args.vararg.arg)
    parameters.extend(argument.arg for argument in node.args.kwonlyargs)
    if node.args.kwarg is not None:
        parameters.append("**" + node.args.kwarg.arg)
    return tuple(parameters)


def _r17_subscript_key(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Subscript):
        return None
    selected = node.slice
    if isinstance(selected, ast.Constant) and isinstance(selected.value, str):
        return selected.value
    return None


def _r17_contract_response_keys(node: ast.AST) -> tuple[str, ...]:
    keys: set[str] = set()
    for descendant in ast.walk(node):
        if isinstance(descendant, ast.Dict):
            keys.update(
                key.value
                for key in descendant.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )
        if isinstance(descendant, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets: list[ast.AST]
            if isinstance(descendant, ast.Assign):
                targets = list(descendant.targets)
            else:
                targets = [descendant.target]
            keys.update(
                key
                for target in targets
                if (key := _r17_subscript_key(target)) is not None
            )
    return tuple(sorted(keys))


def _r17_contract_raises(node: ast.AST) -> tuple[str, ...]:
    raised: set[str] = set()
    for descendant in ast.walk(node):
        if not isinstance(descendant, ast.Raise) or descendant.exc is None:
            continue
        selected = descendant.exc.func if isinstance(descendant.exc, ast.Call) else descendant.exc
        if isinstance(selected, ast.Name):
            raised.add(selected.id)
        elif isinstance(selected, ast.Attribute):
            raised.add(selected.attr)
    return tuple(sorted(raised))


def _r17_contract_symbols(tree: ast.Module) -> dict[str, dict[str, Any]]:
    symbols: dict[str, dict[str, Any]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            symbols[node.name] = {
                "kind": "function",
                "parameters": _r17_contract_parameters(node),
                "return_contract": ast.unparse(node.returns) if node.returns else "",
                "response_keys": _r17_contract_response_keys(node),
                "raises": _r17_contract_raises(node),
            }
        elif isinstance(node, ast.ClassDef):
            initializer = next(
                (
                    child
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and child.name == "__init__"
                ),
                None,
            )
            symbols[node.name] = {
                "kind": "class",
                "parameters": (
                    _r17_contract_parameters(initializer, drop_receiver=True)
                    if initializer is not None
                    else ()
                ),
                "return_contract": node.name,
                "response_keys": tuple(sorted(
                    child.name
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and not child.name.startswith("_")
                )),
                "raises": (),
            }
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            symbols[node.target.id] = {
                "kind": "constant",
                "parameters": (),
                "return_contract": ast.unparse(node.annotation),
                "response_keys": _r17_contract_response_keys(node.value),
                "raises": (),
            }
    return symbols


def _r17_string_sequence(node: ast.AST | None) -> tuple[str, ...] | None:
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        values = tuple(
            item.value
            for item in node.elts
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        )
        return values if len(values) == len(node.elts) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left = _r17_string_sequence(node.left)
        right = _r17_string_sequence(node.right)
        return (*left, *right) if left is not None and right is not None else None
    return None


def _r17_declared_exports(tree: ast.Module) -> tuple[str, ...] | None:
    declared = False
    exports: list[str] = []
    for node in tree.body:
        value: ast.AST | None = None
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        ):
            declared = True
            value = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__all__"
        ):
            declared = True
            value = node.value
        elif (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "__all__"
            and isinstance(node.op, ast.Add)
        ):
            declared = True
            value = node.value
        else:
            continue
        values = _r17_string_sequence(value)
        if values is None:
            return ()
        exports.extend(values)
    return tuple(sorted(set(exports))) if declared else None


def _r17_dotted_name(node: ast.AST) -> tuple[str, ...] | None:
    parts: list[str] = []
    selected = node
    while isinstance(selected, ast.Attribute):
        parts.append(selected.attr)
        selected = selected.value
    if not isinstance(selected, ast.Name):
        return None
    parts.append(selected.id)
    return tuple(reversed(parts))


def _r17_symbol_bindings(
    source: str,
    record: dict[str, Any],
    modules: set[str],
) -> tuple[dict[str, tuple[tuple[str, str], ...]], tuple[str, ...]]:
    bindings: dict[str, set[tuple[str, str]]] = {}
    module_aliases: dict[str, str] = {}
    star_imports: set[str] = set()
    for node in record["tree"].body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                target = _r17_existing(alias.name, modules)
                if target is None:
                    continue
                local = alias.asname or alias.name.split(".", 1)[0]
                module_aliases[local] = target if alias.asname else local
        elif isinstance(node, ast.ImportFrom):
            base = _r17_import_base(source, record["package"], node)
            target = _r17_existing(base, modules)
            if target is None:
                continue
            for alias in node.names:
                if alias.name == "*":
                    star_imports.add(target)
                    continue
                local = alias.asname or alias.name
                imported_module = f"{base}.{alias.name}"
                if imported_module in modules:
                    module_aliases[local] = imported_module
                else:
                    bindings.setdefault(local, set()).add((target, alias.name))

    local_symbols = set(_r17_contract_symbols(record["tree"]))
    assignments: list[tuple[str, ast.AST]] = []
    for node in record["tree"].body:
        if isinstance(node, ast.Assign):
            assignments.extend(
                (target.id, node.value)
                for target in node.targets
                if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.value is not None:
                assignments.append((node.target.id, node.value))
    for _ in range(len(assignments) + 1):
        changed = False
        for local, value in assignments:
            targets: set[tuple[str, str]] = set()
            if isinstance(value, ast.Name):
                targets.update(bindings.get(value.id, set()))
                if value.id in local_symbols:
                    targets.add((source, value.id))
            else:
                parts = _r17_dotted_name(value)
                if parts and parts[0] in module_aliases:
                    qualified = ".".join((module_aliases[parts[0]], *parts[1:]))
                    module = _r17_existing(qualified, modules)
                    if module is not None:
                        suffix = qualified.removeprefix(module).lstrip(".").split(".")
                        if len(suffix) == 1 and suffix[0]:
                            targets.add((module, suffix[0]))
            previous = bindings.setdefault(local, set())
            before = len(previous)
            previous.update(targets)
            changed = changed or len(previous) != before
        if not changed:
            break
    return (
        {
            name: tuple(sorted(targets))
            for name, targets in sorted(bindings.items())
        },
        tuple(sorted(star_imports)),
    )


def _r17_contract_fragment(
    record: dict[str, Any],
    symbol_bindings: dict[str, tuple[tuple[str, str], ...]],
    star_imports: tuple[str, ...],
) -> dict[str, Any]:
    imported_symbols: set[str] = set()
    for node in record["tree"].body:
        if isinstance(node, ast.Import):
            imported_symbols.update(
                alias.asname or alias.name.rpartition(".")[2] for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            imported_symbols.update(alias.asname or alias.name for alias in node.names)
    return {
        "package": record["package"],
        "schemas": tuple(record["schemas"]),
        "protocols": tuple(record["protocols"]),
        "commands": tuple(record["commands"]),
        "response_keys": tuple(sorted(record["response_keys"])),
        "imported_symbols": tuple(sorted(imported_symbols)),
        "symbols": _r17_contract_symbols(record["tree"]),
        "exports": _r17_declared_exports(record["tree"]),
        "symbol_bindings": symbol_bindings,
        "star_imports": star_imports,
    }


def _r17_responsibility_model(
    records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    graph, _reverse = _r17_import_graph(records)
    modules = set(records)
    return {
        "nodes": {
            name: {
                "fragments": (_r17_contract_fragment(
                    record, *_r17_symbol_bindings(name, record, modules)
                ),),
                "responsibility_ids": frozenset(),
            }
            for name, record in records.items()
        },
        "graph": {name: set(targets) for name, targets in graph.items()},
    }


def _r17_load_responsibility_contracts() -> dict[str, Any]:
    document = json.loads(R17_RESPONSIBILITY_CONTRACTS_JSON)
    _require(isinstance(document, dict), "responsibility contracts must be an object")
    payload = dict(document)
    digest = payload.pop("payload_sha256", None)
    _require(digest == _r17_digest(payload), "responsibility contract payload digest")
    _require(
        document.get("schema_version") == R17_RESPONSIBILITY_SCHEMA,
        "responsibility contract schema",
    )
    policy = document.get("boundary_policy")
    _require(isinstance(policy, dict), "responsibility boundary policy")
    _require(
        policy.get("included_owner_layers")
        == ["compact_agent_interaction", "public_agent_facade"],
        "responsibility included owner layers",
    )
    _require(
        policy.get("non_inputs")
        == [
            "direct_consumer_count",
            "directory_path",
            "migration_ledger",
            "module_basename",
            "module_docstring",
            "name_prefix",
            "signed_member_inventory",
        ],
        "responsibility non-input declaration",
    )
    rows = document.get("responsibilities")
    _require(isinstance(rows, list) and rows, "responsibility contract rows")
    identifiers: set[str] = set()
    for row in rows:
        _require(isinstance(row, dict), "responsibility row must be an object")
        _require(
            set(row)
            == {
                "id",
                "service_protocol",
                "protocol_binding",
                "entry",
                "output",
                "owner_layer",
            },
            f"responsibility row fields: {row}",
        )
        identifier = row["id"]
        _require(
            isinstance(identifier, str)
            and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", identifier) is not None,
            f"responsibility id: {identifier!r}",
        )
        _require(identifier not in identifiers, f"duplicate responsibility: {identifier}")
        identifiers.add(identifier)
        entry = row["entry"]
        _require(
            isinstance(entry, dict)
            and set(entry) == {"kind", "symbol", "parameters"}
            and entry["kind"] in {"function", "class", "constant"}
            and isinstance(entry["symbol"], str)
            and isinstance(entry["parameters"], list)
            and all(isinstance(value, str) for value in entry["parameters"]),
            f"responsibility entry: {identifier}",
        )
        output = row["output"]
        _require(
            isinstance(output, dict)
            and {"return_contract", "required_keys"} <= set(output)
            and set(output) <= {
                "return_contract", "required_keys", "key_scope", "raises",
            }
            and isinstance(output["return_contract"], str)
            and isinstance(output["required_keys"], list)
            and all(isinstance(value, str) for value in output["required_keys"])
            and output.get("key_scope", "entry") in {"entry", "owner"}
            and isinstance(output.get("raises", []), list)
            and all(isinstance(value, str) for value in output.get("raises", [])),
            f"responsibility output: {identifier}",
        )
        _require(
            row["protocol_binding"]
            in {"declared_schema", "facade_reachable", "schema_validator"},
            f"responsibility protocol binding: {identifier}",
        )
        _require(
            row["owner_layer"]
            in {
                "compact_agent_interaction",
                "public_agent_facade",
                "independent_primary_protocol",
                "shared_runtime_contract",
            },
            f"responsibility owner layer: {identifier}",
        )
    return document


def _r17_responsibility_closure(
    graph: dict[str, set[str]], starts: set[str]
) -> set[str]:
    selected = set(starts)
    queue = deque(sorted(starts))
    while queue:
        source = queue.popleft()
        for target in sorted(graph[source]):
            if target not in selected:
                selected.add(target)
                queue.append(target)
    return selected


def _r17_contract_matches_fragment(
    contract: dict[str, Any], fragment: dict[str, Any]
) -> bool:
    entry = contract["entry"]
    fact = fragment["symbols"].get(entry["symbol"])
    if fact is None:
        return False
    if fact["kind"] != entry["kind"]:
        return False
    if fact["parameters"] != tuple(entry["parameters"]):
        return False
    output = contract["output"]
    if fact["return_contract"] != output["return_contract"]:
        return False
    if (
        output.get("key_scope", "entry") == "entry"
        and not set(output["required_keys"]) <= set(fact["response_keys"])
    ):
        return False
    return set(output.get("raises", [])) <= set(fact["raises"])


def _r17_contract_binding_matches(
    contract: dict[str, Any],
    fragment: dict[str, Any],
    locator: str,
    facade_closure: set[str] | None,
) -> bool:
    binding = contract["protocol_binding"]
    protocol = contract["service_protocol"]
    layer = contract["owner_layer"]
    if binding == "declared_schema":
        matched = protocol in fragment["schemas"]
    elif binding == "facade_reachable":
        matched = (
            facade_closure is not None
            and locator in facade_closure
            and not any(
                schema for schema in fragment["schemas"]
                if not schema.startswith("gravity.agent")
            )
        )
    else:
        matched = (
            protocol in fragment["imported_symbols"]
            and not fragment["schemas"]
        )
    if not matched:
        return False
    if layer == "public_agent_facade":
        return binding == "declared_schema" and protocol == "gravity.agent.v1"
    if layer == "compact_agent_interaction":
        return binding == "facade_reachable" and protocol == "gravity.agent.v1"
    if layer == "independent_primary_protocol":
        return binding == "declared_schema" and not protocol.startswith("gravity.agent")
    return layer == "shared_runtime_contract" and binding == "schema_validator"


def _r17_fragment_exports_symbol(fragment: dict[str, Any], symbol: str) -> bool:
    exports = fragment["exports"]
    return symbol in exports if exports is not None else not symbol.startswith("_")


def _r17_resolve_public_symbol(
    model: dict[str, Any],
    locator: str,
    fragment_index: int,
    symbol: str,
) -> set[tuple[str, int]]:
    definitions: set[tuple[str, int]] = set()
    queue = deque([(locator, fragment_index, symbol, True)])
    visited: set[tuple[str, int, str, bool]] = set()
    while queue:
        selected_locator, selected_index, selected_symbol, require_public = queue.popleft()
        state = (selected_locator, selected_index, selected_symbol, require_public)
        if state in visited:
            continue
        visited.add(state)
        fragment = model["nodes"][selected_locator]["fragments"][selected_index]
        if require_public and not _r17_fragment_exports_symbol(
            fragment, selected_symbol
        ):
            continue
        if selected_symbol in fragment["symbols"]:
            definitions.add((selected_locator, selected_index))
        for target_locator, target_symbol in fragment["symbol_bindings"].get(
            selected_symbol, ()
        ):
            for target_index, _target in enumerate(
                model["nodes"][target_locator]["fragments"]
            ):
                queue.append((target_locator, target_index, target_symbol, False))
        for target_locator in fragment["star_imports"]:
            for target_index, _target in enumerate(
                model["nodes"][target_locator]["fragments"]
            ):
                queue.append((target_locator, target_index, selected_symbol, True))
    return definitions


def _r17_contract_binding_witnesses(
    model: dict[str, Any],
    contract: dict[str, Any],
    owner: tuple[str, int],
    facade_closure: set[str] | None,
) -> set[str]:
    symbol = contract["entry"]["symbol"]
    owner_locator, owner_index = owner
    owner_fragment = model["nodes"][owner_locator]["fragments"][owner_index]
    required_owner_keys = (
        set(contract["output"]["required_keys"])
        if contract["output"].get("key_scope", "entry") == "owner"
        else set()
    )
    if contract["protocol_binding"] == "facade_reachable":
        locator, fragment_index = owner
        fragment = model["nodes"][locator]["fragments"][fragment_index]
        return (
            {locator}
            if _r17_contract_binding_matches(
                contract, fragment, locator, facade_closure
            )
            and required_owner_keys <= set(fragment["response_keys"])
            else set()
        )
    witnesses: set[str] = set()
    for locator, node in model["nodes"].items():
        for fragment_index, fragment in enumerate(node["fragments"]):
            if owner not in _r17_resolve_public_symbol(
                model, locator, fragment_index, symbol
            ):
                continue
            if _r17_contract_binding_matches(
                contract, fragment, locator, facade_closure
            ) and required_owner_keys <= (
                set(owner_fragment["response_keys"])
                | set(fragment["response_keys"])
            ):
                witnesses.add(locator)
    return witnesses


def _r17_resolve_responsibility_contract(
    model: dict[str, Any],
    contract: dict[str, Any],
    facade_closure: set[str] | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    semantic_owners: set[str] = set()
    binding_witnesses: set[str] = set()
    for locator, node in model["nodes"].items():
        for fragment_index, fragment in enumerate(node["fragments"]):
            if not _r17_contract_matches_fragment(contract, fragment):
                continue
            witnesses = _r17_contract_binding_witnesses(
                model, contract, (locator, fragment_index), facade_closure
            )
            if not witnesses:
                continue
            semantic_owners.add(locator)
            binding_witnesses.update(witnesses)
    _require(
        bool(semantic_owners),
        f"responsibility {contract['id']} semantic owners: "
        f"{sorted(semantic_owners)}",
    )
    return tuple(sorted(semantic_owners)), tuple(sorted(binding_witnesses))


def _r17_derive_responsibility_inventory(
    model: dict[str, Any], contracts: dict[str, Any]
) -> dict[str, Any]:
    rows = contracts["responsibilities"]
    facade_contracts = [row for row in rows if row["id"] == "agent-facade"]
    _require(len(facade_contracts) == 1, "one agent facade responsibility")
    facade_locators, facade_bindings = _r17_resolve_responsibility_contract(
        model, facade_contracts[0], None
    )
    facade_closure = _r17_responsibility_closure(
        model["graph"], set(facade_bindings)
    )
    included_layers = set(contracts["boundary_policy"]["included_owner_layers"])
    decisions: dict[str, dict[str, Any]] = {}
    for contract in rows:
        locators = (
            facade_locators
            if contract["id"] == "agent-facade"
            else _r17_resolve_responsibility_contract(
                model, contract, facade_closure
            )[0]
        )
        included = contract["owner_layer"] in included_layers
        decisions[contract["id"]] = {
            "include": included,
            "reason": "included_owner_layer" if included else contract["owner_layer"],
            "owner_layer": contract["owner_layer"],
            "service_protocol": contract["service_protocol"],
            "entry_symbol": contract["entry"]["symbol"],
            "locators": locators,
        }
    members = tuple(sorted(
        identifier for identifier, decision in decisions.items()
        if decision["include"]
    ))
    return {
        "member_count": len(members),
        "members": members,
        "members_sha256": _r17_digest(members),
        "decisions": decisions,
        "facade_closure_count": len(facade_closure),
        "source_node_count": len(model["nodes"]),
    }


def _r17_responsibility_inventory_pipeline(
    package_root: Path | None,
) -> dict[str, Any]:
    return _r17_derive_responsibility_inventory(
        _r17_responsibility_model(_r17_read_modules(package_root)),
        _r17_load_responsibility_contracts(),
    )


def _r17_ast_import_bindings(nodes: list[ast.stmt]) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".", 1)[0]
                bindings[local] = alias.name if alias.asname else local
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name != "*":
                    bindings[alias.asname or alias.name] = (
                        f"{node.module}.{alias.name}"
                    )
    return bindings


def _r17_ast_reference(
    node: ast.AST,
    bindings: dict[str, str],
) -> str | None:
    if isinstance(node, ast.Name):
        if node.id in bindings:
            return bindings[node.id]
        return node.id if node.id in vars(builtins) else None
    if isinstance(node, ast.Attribute):
        base = _r17_ast_reference(node.value, bindings)
        return f"{base}.{node.attr}" if base is not None else None
    return None


def _r17_ast_alias_assignments(
    nodes: list[ast.stmt],
    bindings: dict[str, str],
) -> dict[str, str]:
    selected = dict(bindings)
    assignments = [
        (target.id, node.value)
        for node in nodes
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        for target in (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
        )
        if isinstance(target, ast.Name)
        if node.value is not None
    ]
    for _ in range(len(assignments) + 1):
        changed = False
        for name, value in assignments:
            reference = _r17_ast_reference(value, selected)
            if reference is not None and selected.get(name) != reference:
                selected[name] = reference
                changed = True
        if not changed:
            break
    return selected


def _r17_ast_call_closure(
    tree: ast.Module,
    roots: tuple[str, ...],
) -> dict[str, Any]:
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    module_bindings = _r17_ast_import_bindings(tree.body)
    module_bindings.update({name: name for name in functions})
    module_bindings = _r17_ast_alias_assignments(tree.body, module_bindings)
    reachable: set[str] = set()
    resolved_calls: dict[str, set[str]] = {}
    unresolved_name_calls: dict[str, set[str]] = {}
    queue = deque(roots)
    while queue:
        name = queue.popleft()
        _require(name in functions, f"derivation gate root missing: {name}")
        if name in reachable:
            continue
        reachable.add(name)
        function = functions[name]
        function_bindings = dict(module_bindings)
        function_bindings.update(_r17_ast_import_bindings([
            node for node in ast.walk(function)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]))
        function_bindings = _r17_ast_alias_assignments(
            [
                node for node in ast.walk(function)
                if isinstance(node, (ast.Assign, ast.AnnAssign))
            ],
            function_bindings,
        )
        calls: set[str] = set()
        unresolved: set[str] = set()
        for node in ast.walk(function):
            if not isinstance(node, ast.Call):
                continue
            reference = _r17_ast_reference(node.func, function_bindings)
            if reference is not None:
                calls.add(reference)
                if reference in functions and reference not in reachable:
                    queue.append(reference)
            elif isinstance(node.func, ast.Name):
                unresolved.add(node.func.id)
        resolved_calls[name] = calls
        unresolved_name_calls[name] = unresolved
    return {
        "functions": functions,
        "module_bindings": module_bindings,
        "reachable": tuple(sorted(reachable)),
        "resolved_calls": {
            name: tuple(sorted(calls)) for name, calls in resolved_calls.items()
        },
        "unresolved_name_calls": {
            name: tuple(sorted(calls))
            for name, calls in unresolved_name_calls.items()
            if calls
        },
    }


def _r17_annotate_responsibility_nodes(
    model: dict[str, Any], inventory: dict[str, Any]
) -> dict[str, Any]:
    selected = copy.deepcopy(model)
    by_locator: dict[str, set[str]] = {}
    for identifier, decision in inventory["decisions"].items():
        for locator in decision["locators"]:
            by_locator.setdefault(locator, set()).add(identifier)
    for locator, node in selected["nodes"].items():
        node["responsibility_ids"] = frozenset(by_locator.get(locator, set()))
    return selected


def _r17_rewrite_fragment_bindings(
    fragment: dict[str, Any],
    replacements: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    selected = copy.deepcopy(fragment)
    selected["symbol_bindings"] = {
        symbol: tuple(sorted({
            (rewritten, target_symbol)
            for target_locator, target_symbol in targets
            for rewritten in replacements[target_locator]
        }))
        for symbol, targets in fragment["symbol_bindings"].items()
    }
    selected["star_imports"] = tuple(sorted({
        rewritten
        for target_locator in fragment["star_imports"]
        for rewritten in replacements[target_locator]
    }))
    return selected


def _r17_rename_responsibility_nodes(
    model: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    mapping = {
        name: f"m{index:04d}"
        for index, name in enumerate(sorted(model["nodes"]), start=1)
    }
    replacements = {name: (target,) for name, target in mapping.items()}
    renamed = {
        "nodes": {
            mapping[name]: {
                **copy.deepcopy(node),
                "fragments": tuple(
                    _r17_rewrite_fragment_bindings(fragment, replacements)
                    for fragment in node["fragments"]
                ),
            }
            for name, node in model["nodes"].items()
        },
        "graph": {
            mapping[source]: {mapping[target] for target in targets}
            for source, targets in model["graph"].items()
        },
    }
    return renamed, mapping


def _r17_clear_module_docstrings(
    records: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    selected = copy.deepcopy(records)
    for record in selected.values():
        tree = record["tree"]
        if (
            tree.body
            and isinstance(tree.body[0], ast.Expr)
            and isinstance(tree.body[0].value, ast.Constant)
            and isinstance(tree.body[0].value.value, str)
        ):
            tree.body.pop(0)
    return selected


def _r17_materialize_frozen_package(package_root: Path) -> None:
    for path, raw in sorted(_r17_frozen_tree_blobs("src/gravity_sdk").items()):
        target = package_root / Path(path).relative_to("src/gravity_sdk")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)


def _r17_move_entry_to_reexported_submodule(
    package_root: Path,
    symbol: str,
) -> tuple[str, str]:
    origin: Path | None = None
    source = ""
    tree: ast.Module | None = None
    definition: ast.FunctionDef | ast.AsyncFunctionDef | None = None
    for path in sorted(package_root.rglob("*.py")):
        selected_source = path.read_text(encoding="utf-8")
        selected_tree = ast.parse(selected_source, filename=str(path))
        selected_definition = next(
            (
                node
                for node in selected_tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == symbol
            ),
            None,
        )
        if selected_definition is not None:
            _require(origin is None, f"multiple entry definitions: {symbol}")
            origin = path
            source = selected_source
            tree = selected_tree
            definition = selected_definition
    _require(
        origin is not None and tree is not None and definition is not None,
        f"entry definition not found: {symbol}",
    )
    lines = source.splitlines(keepends=True)
    start = min(
        [definition.lineno, *(node.lineno for node in definition.decorator_list)]
    ) - 1
    moved = "".join(lines[start : definition.end_lineno])
    remaining = lines[:start] + lines[definition.end_lineno :]

    parameters = {
        argument.arg
        for argument in (
            *definition.args.posonlyargs,
            *definition.args.args,
            *definition.args.kwonlyargs,
        )
    }
    local_names = parameters | {
        node.id
        for node in ast.walk(definition)
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
    } | {
        alias.asname or alias.name
        for node in ast.walk(definition)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    loaded_names = {
        node.id
        for node in ast.walk(definition)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    origin_globals = tuple(sorted(
        loaded_names - local_names - set(vars(builtins)) - {symbol}
    ))

    relative = origin.relative_to(package_root).with_suffix("")
    origin_module = ".".join((package_root.name, *relative.parts))
    implementation = origin.with_name(f"{origin.stem}_impl.py")
    _require(not implementation.exists(), f"implementation exists: {implementation}")
    implementation.write_text(
        "from __future__ import annotations\n\n"
        + f"from {origin_module} import (\n"
        + "".join(f"    {name},\n" for name in origin_globals)
        + ")"
        + "\n\n"
        + moved,
        encoding="utf-8",
    )

    implementation_module = origin_module + "_impl"
    origin.write_text(
        "".join(remaining)
        + f"\nfrom {implementation_module} import {symbol}\n",
        encoding="utf-8",
    )
    return origin_module, implementation_module


def _r17_split_merge_responsibility_consumers(
    model: dict[str, Any], inventory: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, int]]:
    selected = _r17_annotate_responsibility_nodes(model, inventory)
    included = set(inventory["members"])
    split_nodes = {
        name
        for name, node in selected["nodes"].items()
        if set(node["responsibility_ids"]) & included and selected["graph"][name]
    }
    external_groups: dict[tuple[str, ...], list[str]] = {}
    for name, node in selected["nodes"].items():
        if node["responsibility_ids"] or not selected["graph"][name]:
            continue
        signature = tuple(sorted(selected["graph"][name]))
        external_groups.setdefault(signature, []).append(name)
    merged_groups = [
        sorted(names)
        for names in external_groups.values()
        if len(names) > 1
    ]
    _require(split_nodes, "no compact responsibility consumers to split")
    _require(merged_groups, "no external responsibility consumers to merge")

    replacements = {name: (name,) for name in selected["nodes"]}
    for index, name in enumerate(sorted(split_nodes), start=1):
        replacements[name] = (f"compact-split-{index:03d}-a", f"compact-split-{index:03d}-b")
    for index, names in enumerate(sorted(merged_groups), start=1):
        merged = f"external-merge-{index:03d}"
        for name in names:
            replacements[name] = (merged,)

    nodes: dict[str, dict[str, Any]] = {}
    for name, node in selected["nodes"].items():
        targets = replacements[name]
        rewritten_fragments = tuple(
            _r17_rewrite_fragment_bindings(fragment, replacements)
            for fragment in node["fragments"]
        )
        if len(targets) == 2:
            for target in targets:
                nodes[target] = {
                    **copy.deepcopy(node),
                    "fragments": copy.deepcopy(rewritten_fragments),
                }
        elif targets[0].startswith("external-merge-"):
            merged = nodes.setdefault(targets[0], {
                "fragments": (),
                "responsibility_ids": frozenset(),
            })
            merged["fragments"] = (*merged["fragments"], *rewritten_fragments)
        else:
            nodes[targets[0]] = {
                **copy.deepcopy(node),
                "fragments": rewritten_fragments,
            }

    graph = {name: set() for name in nodes}
    for source, targets in selected["graph"].items():
        rewritten_targets = {
            rewritten
            for target in targets
            for rewritten in replacements[target]
        }
        for rewritten_source in replacements[source]:
            graph[rewritten_source].update(rewritten_targets)
    transformed = {"nodes": nodes, "graph": graph}
    stats = {
        "baseline_nodes": len(selected["nodes"]),
        "transformed_nodes": len(nodes),
        "split_nodes": len(split_nodes),
        "merged_groups": len(merged_groups),
        "merged_nodes": sum(len(group) for group in merged_groups),
        "baseline_edges": sum(len(targets) for targets in selected["graph"].values()),
        "transformed_edges": sum(len(targets) for targets in graph.values()),
    }
    return transformed, stats


def _r17_compare_responsibilities_to_migration_ledger(
    inventory: dict[str, Any],
) -> dict[str, Any]:
    ledger = json.loads(
        _r17_frozen_blob(LEDGER.relative_to(ROOT).as_posix()).decode("utf-8")
    )
    moves = {
        row["old_module"] for row in ledger["scope"]["one_to_one_moves"]
    }
    included_locators = {
        locator
        for decision in inventory["decisions"].values()
        if decision["include"]
        for locator in decision["locators"]
    }
    normalized = set(included_locators)
    normalized -= set(inventory["decisions"]["agent-facade"]["locators"])
    normalized -= set(
        inventory["decisions"]["pagination-completeness"]["locators"]
    )
    return {
        "normalized_move_count": len(normalized),
        "normalized_moves_equal_ledger": normalized == moves,
        "responsibility_owners_not_moves": sorted(normalized - moves),
        "moves_not_responsibility_owners": sorted(moves - normalized),
    }


def _r17_direct_consumer_counts(
    model: dict[str, Any], inventory: dict[str, Any]
) -> dict[str, int]:
    reverse = {name: set() for name in model["nodes"]}
    for source, targets in model["graph"].items():
        for target in targets:
            reverse[target].add(source)
    return {
        identifier: len({
            consumer
            for locator in decision["locators"]
            for consumer in reverse[locator]
        })
        for identifier, decision in inventory["decisions"].items()
    }


def _r17_closure(graph: dict[str, set[str]], start: str) -> set[str]:
    selected = {start}
    queue = deque([start])
    while queue:
        source = queue.popleft()
        for target in sorted(graph[source]):
            if target not in selected:
                selected.add(target)
                queue.append(target)
    return selected


def _r17_role_markers(docstring: str) -> tuple[str, ...]:
    return tuple(
        name
        for name, pattern in R17_ROLE_MARKERS
        if re.search(pattern, docstring, flags=re.IGNORECASE)
    )


def _r17_analyze_legacy_module_inventory(
    package_root: Path | None,
) -> dict[str, Any]:
    records = _r17_read_legacy_modules(package_root)
    graph, reverse = _r17_import_graph(records)
    facade_candidates = [
        name
        for name, record in records.items()
        if not record["package"]
        and "gravity.agent.v1" in record["schemas"]
        and {"add_agent_command", "discover_capabilities", "run_agent_command"}
        <= record["functions"]
        and "agent" in record["commands"]
        and {"routing_mode", "candidates", "capability_gaps"}
        <= record["response_keys"]
    ]
    _require(len(facade_candidates) == 1, f"semantic facade: {facade_candidates}")
    facade = facade_candidates[0]
    closure = _r17_closure(graph, facade)
    markers = {
        name: _r17_role_markers(record["docstring"])
        for name, record in records.items()
    }
    marked = {
        name
        for name in closure
        if not records[name]["package"] and markers[name]
    } | {facade}
    members: set[str] = set()
    decisions: list[dict[str, Any]] = []
    for name in sorted(marked):
        record = records[name]
        compact_consumers = reverse[name] & marked
        other_consumers = reverse[name] - marked
        independent_schemas = [
            value
            for value in record["schemas"]
            if not value.startswith("gravity.agent")
        ]
        agent_protocol = any(
            value.startswith("gravity.agent") for value in record["protocols"]
        )
        if name == facade:
            include, reason = True, "unique_semantic_facade"
        elif independent_schemas:
            include, reason = False, "independent_primary_protocol"
        elif "agent_role" in markers[name] and agent_protocol:
            include, reason = True, "declared_agent_protocol_surface"
        elif compact_consumers and len(compact_consumers) >= len(other_consumers):
            include, reason = True, "compact_consumer_owned"
        else:
            include, reason = False, "broader_runtime_consumer_owned"
        if include:
            members.add(name)
        decisions.append({
            "module": name,
            "include": include,
            "reason": reason,
            "role_markers": list(markers[name]),
            "compact_consumers": compact_consumers,
            "other_consumers": other_consumers,
            "source_sha256": hashlib.sha256(
                record["source"].encode("utf-8")
            ).hexdigest(),
        })
    return {
        "records": records,
        "graph": graph,
        "reverse": reverse,
        "facade": facade,
        "closure": closure,
        "marked": marked,
        "members": members,
        "decisions": decisions,
    }


def _r17_set_observation(name: str, members: set[str], **extra: Any) -> dict[str, Any]:
    selected = sorted(_r17_module_id(member) for member in members)
    return {
        "name": name,
        "member_count": len(selected),
        "members_sha256": _r17_digest(selected),
        **extra,
    }


def _r17_pagerank_sweep(
    directed: dict[str, set[str]], implementation: set[str], start: str
) -> tuple[set[str], float, int]:
    graph = {name: set() for name in implementation}
    for source in implementation:
        for target in directed[source] & implementation:
            graph[source].add(target)
            graph[target].add(source)
    damping, tolerance = 0.85, 1e-14
    nodes = sorted(graph)
    rank = dict.fromkeys(nodes, 0.0)
    rank[start] = 1.0
    iterations = 0
    for iterations in range(1, 1001):
        updated = dict.fromkeys(nodes, 0.0)
        updated[start] = 1.0 - damping
        updated[start] += damping * sum(rank[name] for name in nodes if not graph[name])
        for source in nodes:
            if graph[source]:
                share = damping * rank[source] / len(graph[source])
                for target in graph[source]:
                    updated[target] += share
        if sum(abs(updated[name] - rank[name]) for name in nodes) <= tolerance:
            rank = updated
            break
        rank = updated
    order = sorted(
        nodes,
        key=lambda name: (
            -(rank[name] / len(graph[name]) if graph[name] else rank[name]),
            name,
        ),
    )
    total_volume = sum(len(targets) for targets in graph.values())
    selected: set[str] = set()
    volume = crossing = 0
    best: tuple[float, int, tuple[str, ...]] | None = None
    for name in order[:-1]:
        crossing += len(graph[name]) - 2 * len(graph[name] & selected)
        selected.add(name)
        volume += len(graph[name])
        denominator = min(volume, total_volume - volume)
        if denominator > 0:
            candidate = (crossing / denominator, len(selected), tuple(sorted(selected)))
            if best is None or candidate[:2] < best[:2]:
                best = candidate
    _require(best is not None, "import graph has no conductance cut")
    return set(best[2]), best[0], iterations


def _r17_cochange_component(records: dict[str, dict[str, Any]], start: str) -> set[str]:
    paths = {
        record["path"].relative_to(ROOT).as_posix(): name
        for name, record in records.items()
        if not record["package"]
    }
    output = subprocess.run(
        [
            "git", "log", "--format=commit:%H", "--name-only",
            R17_COCHANGE_BASELINE, "--", "src/gravity_sdk",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    parent = {name: name for name in paths.values()}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(left: str, right: str) -> None:
        left, right = find(left), find(right)
        if left != right:
            parent[right] = left

    changed: list[str] = []
    for line in (*output.splitlines(), "commit:end"):
        if line.startswith("commit:"):
            if changed:
                for member in changed[1:]:
                    union(changed[0], member)
            changed = []
        elif line in paths:
            changed.append(paths[line])
    root = find(start)
    return {name for name in parent if find(name) == root}


def _r17_build_legacy_signed_module_inventory(
    package_root: Path | None = None,
) -> dict[str, Any]:
    analysis = _r17_analyze_legacy_module_inventory(package_root)
    records = analysis["records"]
    graph = analysis["graph"]
    reverse = analysis["reverse"]
    facade = analysis["facade"]
    members = analysis["members"]
    migration_bytes = (
        _r17_frozen_blob(LEDGER.relative_to(ROOT).as_posix())
        if package_root is None
        else LEDGER.read_bytes()
    )
    migration = json.loads(migration_bytes.decode("utf-8"))
    scope = migration["scope"]
    moves = {row["old_module"] for row in scope["one_to_one_moves"]}
    consolidation = scope["consolidate_delete"]["old_module"]
    retained = scope["retained_modules"]
    _require(len(retained) == 1, f"one retained module required: {retained}")
    excluded = retained[0]
    find_owners = [
        name for name, record in records.items() if "gravity.find.v1" in record["schemas"]
    ]
    _require(len(find_owners) == 1, f"one Find owner required: {find_owners}")
    implementation = {
        name for name, record in records.items() if not record["package"]
    }
    reverse_graph = {name: set() for name in graph}
    for source, targets in graph.items():
        for target in targets:
            reverse_graph[target].add(source)
    scc = _r17_closure(graph, facade) & _r17_closure(reverse_graph, facade)
    scc &= implementation
    unrestricted = analysis["closure"] & implementation
    conductance, conductance_value, iterations = _r17_pagerank_sweep(
        graph, implementation, facade
    )
    cochange = _r17_cochange_component(records, facade)
    rows: list[dict[str, Any]] = []
    for decision in analysis["decisions"]:
        name = decision["module"]
        if not decision["include"]:
            disposition = "not_a_member"
        elif name == facade:
            disposition = "retain_public_facade"
        elif name == consolidation:
            disposition = "consolidate_delete"
        elif name in moves:
            disposition = "move"
        else:
            disposition = "unmapped_member"
        compact = sorted(_r17_module_id(value) for value in decision["compact_consumers"])
        other = sorted(_r17_module_id(value) for value in decision["other_consumers"])
        rows.append({
            "module": _r17_module_id(name),
            "include": decision["include"],
            "reason": decision["reason"],
            "role_markers": decision["role_markers"],
            "compact_consumer_count": len(compact),
            "compact_consumers_sha256": _r17_digest(compact),
            "other_consumer_count": len(other),
            "other_consumers_sha256": _r17_digest(other),
            "source_sha256": decision["source_sha256"],
            "r17_disposition": disposition,
        })
    selected_ids = sorted(_r17_module_id(name) for name in members)
    comparable = members - {facade, consolidation}

    def boundary(module: str, label: str) -> dict[str, Any]:
        record = records[module]
        return {
            "label": label,
            "module": _r17_module_id(module),
            "selected": module in members,
            "in_unrestricted_facade_closure": module in analysis["closure"],
            "primary_schemas": list(record["schemas"]),
            "cli_commands": list(record["commands"]),
            "direct_consumer_count": len(reverse[module]),
            "direct_member_consumers": sorted(
                _r17_module_id(name) for name in reverse[module] & members
            ),
            "direct_other_consumer_count": len(reverse[module] - members),
            "direct_imports_to_members": sorted(
                _r17_module_id(name) for name in graph[module] & members
            ),
        }

    method = {
        "candidate_universe": (
            "Parse every Python module in the package; module names and paths label "
            "results but never filter candidates."
        ),
        "semantic_facade": (
            "Select the unique non-package owner of gravity.agent.v1 that defines "
            "the three facade callables, registers the agent command, and emits the "
            "three response-shape keys."
        ),
        "dependency_scope": (
            "Build an AST import graph from every lexical depth and take the facade's "
            "unrestricted directed closure."
        ),
        "responsibility_declaration": (
            "Match module docstrings against the closed role-marker regex list."
        ),
        "ownership_decision": (
            "Include the facade; reject a non-Agent primary schema; otherwise include "
            "an Agent protocol surface or a marked owner with at least one marked "
            "consumer and no more other than marked direct consumers."
        ),
        "post_selection_comparison": (
            "Load the R17 move ledger only after classification and compute differences."
        ),
        "role_markers": [
            {"id": name, "regex": pattern, "flags": ["IGNORECASE"]}
            for name, pattern in R17_ROLE_MARKERS
        ],
        "graph_methods": {
            "facade_scc": "directed mutual reachability",
            "unrestricted_closure": "directed static-import reachability",
            "import_conductance": (
                "degree-normalized personalized PageRank; damping 0.85; tolerance "
                "1e-14; deterministic minimum-conductance sweep"
            ),
            "cochange": "fixed-baseline all-history connected component",
        },
    }
    document: dict[str, Any] = {
        "schema_version": R17_INVENTORY_SCHEMA,
        "analysis_baseline": f"dev@{R17_COCHANGE_BASELINE}",
        "module_namespace": "gravity_sdk" if package_root is None else package_root.name,
        "method": method,
        "method_sha256": _r17_digest(method),
        "source_snapshot": {
            "package_module_count": len(records),
            "implementation_module_count": len(implementation),
            "tree_sha256": _r17_digest([
                {
                    "module": _r17_module_id(name),
                    "source_sha256": hashlib.sha256(
                        record["source"].encode("utf-8")
                    ).hexdigest(),
                }
                for name, record in sorted(records.items())
            ]),
        },
        "selector_summary": {
            "semantic_facade": _r17_module_id(facade),
            "unrestricted_closure_count": len(unrestricted),
            "role_candidate_count": len(analysis["marked"]),
            "member_count": len(members),
            "rejected_role_candidate_count": sum(not row["include"] for row in rows),
        },
        "members": selected_ids,
        "members_sha256": _r17_digest(selected_ids),
        "decisions": rows,
        "r17_comparison": {
            "ledger_sha256": hashlib.sha256(migration_bytes).hexdigest(),
            "move_count": len(moves),
            "independent_members_not_moves": sorted(
                _r17_module_id(name) for name in members - moves
            ),
            "moves_not_independent_members": sorted(
                _r17_module_id(name) for name in moves - members
            ),
            "action_normalized_members_equal_moves": comparable == moves,
            "action_normalized_members_not_moves": sorted(
                _r17_module_id(name) for name in comparable - moves
            ),
            "moves_not_action_normalized_members": sorted(
                _r17_module_id(name) for name in moves - comparable
            ),
        },
        "boundary_cases": [
            boundary(excluded, "broader_runtime_contracts_owner"),
            boundary(find_owners[0], "independent_find_surface"),
        ],
        "graph_observations": [
            _r17_set_observation("facade_scc", scc),
            _r17_set_observation("unrestricted_facade_closure", unrestricted),
            _r17_set_observation(
                "import_graph_minimum_conductance",
                conductance,
                conductance=conductance_value,
                pagerank_iterations=iterations,
                damping=0.85,
                tolerance=1e-14,
            ),
            _r17_set_observation(
                "cochange_component", cochange, baseline=R17_COCHANGE_BASELINE
            ),
        ],
        "conclusion": {
            "boundary": "inconsistent_but_adjustable",
            "complete_agent_domain_proven": False,
            "graph_methods_converged": False,
            "r17_82_moves_supported": comparable == moves,
        },
    }
    document["payload_sha256"] = _r17_digest(document)
    return document


def _r17_load_legacy_signed_module_inventory() -> dict[str, Any]:
    source = R17_SPECIFICATION.read_text(encoding="utf-8")
    _require(source.count(R17_INVENTORY_START) == 1, "inventory start marker")
    _require(source.count(R17_INVENTORY_END) == 1, "inventory end marker")
    payload = source.split(R17_INVENTORY_START, 1)[1].split(R17_INVENTORY_END, 1)[0]
    match = re.fullmatch(r"\s*```json\s*\n(.*)\n```\s*", payload, flags=re.DOTALL)
    _require(match is not None, "inventory must be one fenced JSON object")
    value = json.loads(match.group(1))
    _require(isinstance(value, dict), "inventory must be a JSON object")
    return value


def _r17_owner_projection_state(
    module_names: set[str],
    frozen_inventory: dict[str, Any],
    frozen_scope: dict[str, Any],
) -> str:
    moves = {
        move["old_module"]: move["new_module"]
        for move in frozen_scope["one_to_one_moves"]
    }
    inventory_moves = {
        f"gravity_sdk.{row['module']}"
        for row in frozen_inventory["decisions"]
        if row["include"] and row["r17_disposition"] == "move"
    }
    _require(
        inventory_moves == set(moves),
        "frozen responsibility rows differ from the immutable move ledger",
    )
    overlaps = [
        old for old, new in moves.items() if old in module_names and new in module_names
    ]
    missing = [
        old for old, new in moves.items() if old not in module_names and new not in module_names
    ]
    _require(
        not overlaps and not missing,
        f"current responsibility owners are not one-to-one: overlaps={overlaps[:5]}, "
        f"missing={missing[:5]}",
    )
    old_count = sum(old in module_names for old in moves)
    new_count = sum(new in module_names for new in moves.values())
    consolidation = frozen_scope["consolidate_delete"]
    pagination_old = consolidation["old_module"] in module_names
    _require(
        consolidation["new_module"] in module_names,
        "pagination consolidation target is missing",
    )
    for retained in frozen_scope["retained_modules"]:
        _require(retained in module_names, f"retained owner is missing: {retained}")
    owner_state = (old_count, new_count, pagination_old)
    states = {
        "baseline": (82, 0, True),
        "phase_1": (34, 48, False),
        "phase_2": (0, 82, False),
    }
    matches = [name for name, expected in states.items() if expected == owner_state]
    _require(
        len(matches) == 1,
        f"responsibility projection is outside Phase 0/1/2: {owner_state}",
    )
    return matches[0]


def _r17_phase_module_names(
    frozen_scope: dict[str, Any], *, old_count: int, pagination_old: bool
) -> set[str]:
    moves = frozen_scope["one_to_one_moves"]
    result = {
        move["old_module"] if index < old_count else move["new_module"]
        for index, move in enumerate(moves)
    }
    result.add(frozen_scope["consolidate_delete"]["new_module"])
    result.update(frozen_scope["retained_modules"])
    if pagination_old:
        result.add(frozen_scope["consolidate_delete"]["old_module"])
    return result


def _validator_has_current_path_semantics(old_module: str, context: str) -> bool:
    """Conservatively detect consumers without using the generator classifier."""

    short = re.escape(old_module.removeprefix("gravity_sdk."))
    names = rf"(?:(?:gravity_sdk\.)?{short}|\.{short})"
    checks = (
        rf"\b(?:from|import)\s+{names}(?:\s+import\b|\b)",
        rf"{names}\s*\.(?!py\b)[A-Za-z_]\w*",
        rf"{names}\s*\(",
        rf"\b(?:getattr|__import__|import_module|patch|setattr)\s*\("
        rf"[^\n)]{{0,160}}{names}",
        rf"(?:src/gravity_sdk/)?{short}\.py",
    )
    return any(re.search(check, context, re.IGNORECASE) for check in checks)


def _validator_is_dated_decision(context: str) -> bool:
    return bool(
        re.search(
            r"(?:\u7acb\u9879|decision(?:\s+record)?)\s*[\uff08(]"
            r"\d{4}-\d{2}-\d{2}[\uff09)]",
            context,
            re.IGNORECASE,
        )
    )


def _validator_is_deleted_module_fact(old_module: str, context: str) -> bool:
    short = old_module.removeprefix("gravity_sdk.")
    if '"consolidated_deleted_modules"' in context and f'"{short}"' in context:
        return True
    normalized = " ".join(context.lower().split())
    position = normalized.find(short.lower())
    if position < 0:
        return False
    window = normalized[max(0, position - 120):position + len(short) + 120]
    return any(
        marker in window
        for marker in (
            "\u5408\u5e76\u5220\u9664",
            "consolidate/delete",
            "consolidated and deleted",
            "deleted module",
            "removed module",
        )
    )


def validate_ledger(document: dict[str, Any]) -> None:
    _require(
        document.get("schema_version")
        == "gravity.agent-module-reference-dispositions.v2",
        "invalid disposition-ledger schema",
    )
    source = document.get("source_audit", {})
    _require(source.get("method") == "direct repository scan", "audit is not direct")
    _require(
        source.get("file_universe")
        == "git ls-files --cached --others --exclude-standard",
        "audit file universe changed",
    )
    _require(
        source.get("governance_exclusion_rule") == FROZEN_BASELINE_EXCLUSION_RULE,
        "governance exclusion rule changed",
    )
    _require(
        source.get("scanner_path") == "scripts/audit_agent_module_references.py",
        "scanner is not repository-owned",
    )
    _require(
        source.get("generator_path")
        == "scripts/generate_agent_module_reference_dispositions.py",
        "generator is not repository-owned",
    )
    for field, value in source.items():
        if field.endswith("_path") or field == "command":
            _require("tmp/" not in str(value).replace("\\", "/"), f"tmp input at {field}")

    scope = document.get("scope", {})
    moves = scope.get("one_to_one_moves", [])
    _require(len(moves) == 82, "R17 must have exactly 82 one-to-one targets")
    old_targets = {item.get("old_module") for item in moves}
    new_targets = {item.get("new_module") for item in moves}
    move_mapping = {item.get("old_module"): item.get("new_module") for item in moves}
    _require(len(old_targets) == len(new_targets) == 82, "move targets must be unique")
    for item in moves:
        old = item.get("old_module")
        new = item.get("new_module")
        old_name = old.removeprefix("gravity_sdk.") if isinstance(old, str) else ""
        if old_name.startswith("agent_"):
            responsibility = old_name.removeprefix("agent_")
        elif old_name.endswith("_agent"):
            responsibility = old_name.removesuffix("_agent")
        else:
            responsibility = ""
        _require(
            bool(responsibility)
            and new == f"gravity_sdk.agents.{responsibility}",
            f"invalid one-to-one move: {old!r} -> {new!r}",
        )
    _require(PAGINATION_MODULE not in old_targets, "pagination cannot be one-to-one")
    _require(RETAINED_MODULE not in old_targets, "retained contracts cannot move")
    _require(
        scope.get("consolidate_delete")
        == {
            "old_module": PAGINATION_MODULE,
            "new_module": PAGINATION_TARGET,
            "symbol": "compact_pagination",
        },
        "pagination consolidation target changed",
    )
    _require(scope.get("retained_modules") == [RETAINED_MODULE], "retained scope changed")

    taxonomy = document.get("taxonomy", {})
    _require(ALLOWED_DISPOSITIONS <= set(taxonomy), "taxonomy is incomplete")
    sites = document.get("sites")
    _require(isinstance(sites, list) and len(sites) == 238, "ledger must have 238 sites")
    keys = [site.get("source_key") for site in sites]
    _require(len(set(keys)) == 238, "ledger source keys must be unique")

    categories: Counter[str] = Counter()
    dispositions: Counter[str] = Counter()
    for site in sites:
        key = site.get("source_key")
        source_site = site.get("source", {})
        expected_key = (
            f"{source_site.get('file')}:{source_site.get('line')}:"
            f"{source_site.get('column')}:{source_site.get('form')}"
        )
        _require(key == expected_key, f"source key does not bind coordinates: {key!r}")
        category = site.get("audit_category")
        disposition = site.get("disposition")
        _require(category in EXPECTED_CATEGORIES, f"unknown audit category at {key}")
        _require(disposition in ALLOWED_DISPOSITIONS, f"unclassified disposition at {key}")
        _require(bool(site.get("basis")), f"missing classification basis at {key}")
        _require(bool(site.get("evidence_kind")), f"missing evidence kind at {key}")
        action = site.get("migration_action", {})
        categories[category] += 1
        dispositions[disposition] += 1

        if disposition == "no_migration_effect":
            _require(action == {"kind": "none"}, f"no-effect row has action at {key}")
        elif disposition == "rewrite_reference":
            _require(action.get("kind") == "replace_text", f"invalid text action at {key}")
            _require(action.get("old_module") in old_targets, f"unknown source at {key}")
            _require(action.get("new_module") in new_targets, f"illegal target at {key}")
            _require(
                move_mapping[action["old_module"]] == action["new_module"],
                f"mismatched move pair at {key}",
            )
            old_text = action.get("old_text")
            new_text = action.get("new_text")
            if isinstance(old_text, str) and old_text.endswith(".py"):
                target_name = action["new_module"].removeprefix(
                    "gravity_sdk.agents."
                )
                expected_text = (
                    f"src/gravity_sdk/agents/{target_name}.py"
                    if old_text.startswith("src/gravity_sdk/")
                    else f"agents/{target_name}.py"
                )
                _require(
                    new_text == expected_text,
                    f"file rewrite target is ambiguous at {key}: {new_text!r}",
                )
                root_peer = ROOT / "src/gravity_sdk" / f"{target_name}.py"
                root_peer_module = f"gravity_sdk.{target_name}"
                if root_peer.is_file() and root_peer_module not in old_targets:
                    _require(
                        new_text != root_peer.name,
                        f"rewrite target aliases unrelated root file at {key}",
                    )
        elif disposition == "rewrite_selector_data":
            rewrites = action.get("rewrites", [])
            _require(
                action.get("kind") == "replace_selector_values"
                and len(rewrites) == 6
                and len({rewrite.get("symbol") for rewrite in rewrites}) == 6,
                f"root selector must have six rewrites at {key}",
            )
        elif disposition == "rewrite_consolidated_reference":
            _require(
                action.get("kind") == "replace_module"
                and action.get("old_module") == PAGINATION_MODULE
                and action.get("new_module") == PAGINATION_TARGET,
                f"invalid pagination rewrite at {key}",
            )
        elif disposition == "runtime_verification_required":
            verification = site.get("verification", {})
            _require(
                action.get("kind") == "verify_before_migration"
                and bool(verification.get("method"))
                and bool(verification.get("failure_action")),
                f"runtime verification is not executable at {key}",
            )
        else:
            _require(action.get("kind") == "block", f"blocker has no stop action at {key}")

        reference = site.get("module_reference", {})
        if reference.get("candidate_new_module") in new_targets:
            _require(
                move_mapping.get(reference.get("old_module"))
                == reference.get("candidate_new_module"),
                f"invalid no-effect candidate mapping at {key}",
            )
        if reference.get("old_module") == RETAINED_MODULE:
            _require(disposition == "no_migration_effect", f"retained owner moved at {key}")

        old_value = source_site.get("old_value")
        old_module = f"gravity_sdk.{old_value}"
        if category == "bare_agent_string" and source_site.get("file") in ACTIVE_BARE_FILES:
            context = source_site.get("audit_context")
            snippet = source_site.get("audit_snippet")
            _require(isinstance(context, str) and bool(context), f"missing context at {key}")
            _require(
                isinstance(snippet, str) and snippet in context,
                f"source snippet is outside bounded context at {key}",
            )
            current_path = _validator_has_current_path_semantics(
                old_module, context
            )
            if old_module == PAGINATION_MODULE:
                if current_path:
                    _require(
                        disposition
                        in {"rewrite_consolidated_reference", "blocker"},
                        f"active consumer syntax must rewrite or block at {key}",
                    )
                elif _validator_is_deleted_module_fact(old_module, context):
                    _require(
                        disposition == "no_migration_effect"
                        and site.get("reason_code") == "deleted_module_governance_fact"
                        and reference
                        == {
                            "old_module": PAGINATION_MODULE,
                            "candidate_new_module": PAGINATION_TARGET,
                        },
                        f"deleted-module fact must remain unchanged at {key}",
                    )
                else:
                    _require(
                        disposition == "blocker",
                        f"ambiguous pagination reference must block at {key}",
                    )
            elif old_module in old_targets:
                if current_path:
                    _require(
                        disposition in {"rewrite_reference", "blocker"},
                        f"active consumer syntax must rewrite or block at {key}",
                    )
                elif site.get("reason_code") == "dated_governance_decision_evidence":
                    _require(
                        _validator_is_dated_decision(context)
                        and disposition == "no_migration_effect"
                        and reference
                        == {
                            "old_module": old_module,
                            "candidate_new_module": move_mapping[old_module],
                        },
                        f"dated decision evidence must remain unchanged at {key}",
                    )
        elif old_module == PAGINATION_MODULE:
            if str(source_site.get("file", "")).startswith("docs/archive/"):
                _require(
                    disposition == "no_migration_effect"
                    and site.get("reason_code") == "frozen_historical_text",
                    f"archived pagination evidence must remain unchanged at {key}",
                )
            else:
                _require(
                    disposition in {"rewrite_consolidated_reference", "blocker"},
                    f"pagination consumer must rewrite or block at {key}",
                )

    _require(dict(categories) == EXPECTED_CATEGORIES, "audit denominator changed")
    _require(dict(dispositions) == EXPECTED_DISPOSITIONS, "dispositions changed")
    reason_counts = Counter(site.get("reason_code") for site in sites)
    _require(
        reason_counts["deleted_module_governance_fact"] == 3,
        "deleted-module governance facts changed",
    )
    _require(
        reason_counts["dated_governance_decision_evidence"] == 2,
        "dated governance decision evidence changed",
    )
    summary = document.get("summary", {})
    _require(summary.get("site_count") == len(sites), "declared site count differs")
    _require(summary.get("unique_source_keys") == len(set(keys)), "key count differs")
    _require(summary.get("unclassified_sites") == 0, "ledger has unclassified sites")
    _require(summary.get("blocker_count") == dispositions["blocker"], "blockers differ")
    _require(document.get("blockers") == [], "blocker list is not empty")
    _require(summary.get("audit_categories") == EXPECTED_CATEGORIES, "category summary differs")
    _require(summary.get("dispositions") == EXPECTED_DISPOSITIONS, "disposition summary differs")
    _require(
        summary.get("sites_sha256") == _canonical_sites_sha256(sites),
        "canonical site digest differs",
    )


def validate_checkpoint_receipt(document: dict[str, Any]) -> None:
    _require(
        document.get("schema_version")
        == "gravity.agent-module-reference-checkpoint.v1",
        "invalid checkpoint schema",
    )
    _require(
        document.get("receipt_role")
        == "live_checkpoint_scan_only; not authority for canonical errata replacements",
        "checkpoint role changed",
    )
    baseline = document.get("immutable_baseline_ledger", {})
    directive = json.loads(DIRECTIVE.read_text(encoding="utf-8"))
    derivation = directive["canonical_source_errata"]["allowed_source_replacements"]
    expected_binding = {
        "role": "errata_source_only_immutable_baseline",
        "repository_path": derivation["ledger_repository_path"],
        "git_blob": derivation["ledger_git_blob"],
        "sha256": derivation["ledger_sha256"],
        "schema_version": derivation["ledger_schema_version"],
    }
    _require(baseline == expected_binding, "checkpoint baseline binding changed")
    reviewed_at_revision = derivation.get("reviewed_at_revision")
    _require(
        reviewed_at_revision == errata_validator.REVIEWED_AT_REVISION,
        "checkpoint ledger review revision changed",
    )
    reviewed_blob = subprocess.run(
        [
            "git",
            "rev-parse",
            f"{reviewed_at_revision}:{baseline['repository_path']}",
        ],
        cwd=ROOT,
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
    ).stdout.strip()
    _require(
        reviewed_blob == baseline["git_blob"],
        "baseline blob differs at the fixed review revision",
    )
    current_blob = subprocess.run(
        ["git", "rev-parse", f"HEAD:{baseline['repository_path']}"],
        cwd=ROOT,
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
    ).stdout.strip()
    _require(current_blob == baseline["git_blob"], "baseline blob is not current")
    bound = subprocess.run(
        [
            "git",
            "cat-file",
            "blob",
            baseline["git_blob"],
        ],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    _require(bound == LEDGER.read_bytes(), "baseline ledger is not the bound Git object")
    _require(
        hashlib.sha256(bound).hexdigest() == baseline["sha256"],
        "baseline ledger digest changed",
    )

    scope = document.get("scope", {})
    moves = scope.get("one_to_one_moves", [])
    move_mapping = {
        item.get("old_module"): item.get("new_module") for item in moves
    }
    _require(len(move_mapping) == 82, "checkpoint move scope changed")
    site_records = document.get("sites")
    _require(isinstance(site_records, list), "checkpoint sites must be a list")
    sites = checkpoint_sites(document)
    classification_basis = document.get("classification_basis")
    _require(
        isinstance(classification_basis, list) and classification_basis,
        "checkpoint classification basis is missing",
    )
    keys = [site.get("source_key") for site in sites]
    _require(len(keys) == len(set(keys)), "checkpoint source keys repeat")
    dispositions: Counter[str] = Counter()
    reference_categories: Counter[str] = Counter()
    manual_categories: Counter[str] = Counter()
    reference_count = 0
    manual_count = 0
    overlap_count = 0
    for site in sites:
        key = site.get("source_key")
        source = site.get("source", {})
        expected_key = (
            f"{source.get('file')}:{source.get('line')}:"
            f"{source.get('column')}:{source.get('form')}"
        )
        _require(key == expected_key, f"checkpoint coordinate key drifted at {key}")
        tracked = site.get("tracked_sources")
        _require(
            isinstance(tracked, list)
            and tracked
            and set(tracked) <= {"reference", "manual_review"},
            f"invalid tracked denominator at {key}",
        )
        disposition = site.get("disposition")
        _require(disposition in ALLOWED_DISPOSITIONS, f"unknown disposition at {key}")
        basis_id = site.get("basis_id")
        basis = (
            classification_basis[basis_id]
            if isinstance(basis_id, int) and 0 <= basis_id < len(classification_basis)
            else {}
        )
        _require(bool(basis.get("basis")), f"missing basis at {key}")
        _require(bool(basis.get("evidence_kind")), f"missing evidence kind at {key}")
        dispositions[disposition] += 1
        if "reference" in tracked:
            reference_count += 1
            category = source.get("reference_category")
            _require(isinstance(category, str) and bool(category), f"missing reference category at {key}")
            reference_categories[category] += 1
        if "manual_review" in tracked:
            manual_count += 1
            manual_categories[site.get("audit_category")] += 1
        if set(tracked) == {"reference", "manual_review"}:
            overlap_count += 1

        action = site.get("migration_action", {})
        if disposition == "no_migration_effect":
            _require(action == {"kind": "none"}, f"no-effect action at {key}")
        elif disposition == "rewrite_reference":
            old = action.get("old_module")
            _require(
                action.get("kind") == "replace_text"
                and move_mapping.get(old) == action.get("new_module"),
                f"invalid exact move at {key}",
            )
        elif disposition == "rewrite_consolidated_reference":
            _require(
                action.get("kind") == "replace_module"
                and action.get("old_module") == PAGINATION_MODULE
                and action.get("new_module") == PAGINATION_TARGET,
                f"invalid consolidation at {key}",
            )
        elif disposition == "rewrite_selector_data":
            _require(
                action.get("kind") == "replace_selector_values"
                and len(action.get("rewrites", [])) == 6,
                f"invalid selector rewrite at {key}",
            )
        elif disposition == "blocker":
            _require(action == {"kind": "block"}, f"invalid blocker action at {key}")

        if site.get("audit_category") == "exact_reference":
            file = str(source.get("file", ""))
            old_value = source.get("old_value")
            old_module = old_value if old_value in move_mapping else None
            if old_module is None and isinstance(old_value, str):
                old_module = next(
                    (
                        old
                        for old in [*move_mapping, PAGINATION_MODULE, RETAINED_MODULE]
                        if old_value == "src/" + old.replace(".", "/") + ".py"
                    ),
                    old_value
                    if old_value in {PAGINATION_MODULE, RETAINED_MODULE}
                    else None,
                )
            sentinel = (
                file == "tests/test_agent_concept_deletions.py"
                and source.get("reference_category") == "string_reference"
            )
            if file.startswith("docs/archive/") or sentinel or old_module == RETAINED_MODULE:
                _require(disposition == "no_migration_effect", f"frozen exact reference moved at {key}")
            elif old_module == PAGINATION_MODULE:
                if site.get("reason_code") == "deleted_module_governance_fact":
                    _require(
                        disposition == "no_migration_effect",
                        f"pagination deletion fact changed at {key}",
                    )
                else:
                    _require(
                        disposition in {"rewrite_consolidated_reference", "blocker"},
                        f"pagination exact reference escaped at {key}",
                    )
            else:
                _require(
                    old_module in move_mapping
                    and disposition in {"rewrite_reference", "blocker"},
                    f"moved exact reference escaped at {key}",
                )

    summary = document.get("summary", {})
    _require(summary.get("tracked_site_count") == len(sites), "tracked count drifted")
    _require(summary.get("reference_site_count") == reference_count, "reference denominator drifted")
    _require(summary.get("manual_review_site_count") == manual_count, "manual denominator drifted")
    _require(summary.get("reference_manual_overlap_count") == overlap_count, "overlap drifted")
    _require(summary.get("manual_only_site_count") == manual_count - overlap_count, "manual-only count drifted")
    _require(summary.get("reference_categories") == dict(sorted(reference_categories.items())), "reference categories drifted")
    _require(summary.get("manual_review_categories") == dict(sorted(manual_categories.items())), "manual categories drifted")
    _require(summary.get("dispositions") == dict(sorted(dispositions.items())), "dispositions drifted")
    _require(summary.get("unique_source_keys") == len(set(keys)), "unique key count drifted")
    _require(summary.get("unclassified_sites") == 0, "checkpoint has unclassified sites")
    _require(summary.get("sites_sha256") == _canonical_sites_sha256(site_records), "checkpoint digest drifted")
    blockers = document.get("blockers")
    _require(isinstance(blockers, list), "checkpoint blockers must be a list")
    _require(summary.get("blocker_count") == len(blockers), "checkpoint blocker count drifted")


def _text_state_projection(text: str) -> dict[str, Any]:
    scalar_names = (
        "status",
        "dynamic_import_audit_classification.satisfied",
        "schema",
        "candidate_sites",
        "classified_sites",
        "unclassified_sites",
        "blocking_sites",
        "m0_bound_implementation_baseline",
        "ledger_sha256",
        "live_checkpoint_sha256",
        "live_checkpoint_tracked_sites",
    )
    projection: dict[str, Any] = {}
    for name in scalar_names:
        values = set(
            re.findall(
                rf"(?<![A-Za-z0-9_.]){re.escape(name)}=([A-Za-z0-9._-]+)",
                text,
            )
        )
        _require(len(values) == 1, f"ambiguous {name} marker: {values}")
        projection[name] = values.pop()
    artifact_markers = re.findall(
        r"m0_bound_artifact_sha256=(\{[^`\r\n]+\})",
        text,
    )
    _require(
        len(artifact_markers) == 1,
        f"ambiguous m0 artifact marker: {artifact_markers}",
    )
    try:
        projection["m0_bound_artifact_sha256"] = json.loads(artifact_markers[0])
    except json.JSONDecodeError as exc:
        raise AssertionError("invalid m0 artifact marker JSON") from exc
    return projection


def validate_active_scope_owner_projection(
    roadmap: str,
    technical_debt: str,
    ledger: dict[str, Any],
) -> None:
    moves = ledger.get("scope", {}).get("one_to_one_moves", [])
    _require(len(moves) == 82, "scope projection requires the reviewed 82 moves")
    expected = {
        "old_paths": len(moves) + 1,
        "moves": len(moves),
        "root_py": 495,
        "agents_implementation_py": len(moves),
    }
    roadmap_match = re.search(
        r"R17 \u7ec8\u6001\u987b\u79fb\u9664\s+(\d+)\s+\u4e2a\u65e7 deep module path"
        r"\uff08(\d+)\s+\u8fc1\u79fb\s*\+\s*pagination \u5220\u9664\uff09",
        roadmap,
    )
    _require(roadmap_match is not None, "roadmap has no unique R17 scope projection")
    roadmap_projection = {
        "old_paths": int(roadmap_match.group(1)),
        "moves": int(roadmap_match.group(2)),
    }
    _require(
        roadmap_projection
        == {"old_paths": expected["old_paths"], "moves": expected["moves"]},
        "roadmap R17 scope projection differs from the reviewed ledger",
    )

    debt_match = re.search(
        r"\u6839 `\.py` \u4e3a\s*(\d+)\u3001\s*\n?\s*`agents/` \u542b\s*(\d+)\s*\u4e2a\u5b9e\u73b0\u6a21\u5757",
        technical_debt,
    )
    _require(
        debt_match is not None,
        "technical-debt has no unique R17 exit-count projection",
    )
    debt_projection = {
        "root_py": int(debt_match.group(1)),
        "agents_implementation_py": int(debt_match.group(2)),
    }
    _require(
        debt_projection
        == {
            "root_py": expected["root_py"],
            "agents_implementation_py": expected["agents_implementation_py"],
        },
        "technical-debt R17 exit projection differs from the reviewed ledger",
    )


def validate_index_and_specification_state(
    index: dict[str, Any],
    index_markdown: str,
    specification: str,
    ledger: dict[str, Any],
    directive: dict[str, Any],
    *,
    ledger_bytes: bytes,
    checkpoint: dict[str, Any],
    checkpoint_bytes: bytes,
) -> None:
    requirement = next(
        item for item in index["requirements"] if item.get("id") == "R17"
    )
    _require(requirement["status"] == "specified", "R17 status changed")
    m0 = next(
        item
        for item in requirement["ready_prerequisites"]
        if item.get("id") == "m0_characterization"
    )
    dynamic = next(
        item
        for item in requirement["ready_prerequisites"]
        if item.get("id") == "dynamic_import_audit_classification"
    )
    summary = ledger["summary"]
    actual_dynamic_evidence = (
        dynamic["required_schema_version"] == ledger["schema_version"]
        and dynamic["candidate_sites"] == len(ledger["sites"])
        and dynamic["classified_sites"]
        == len(ledger["sites"]) - summary["unclassified_sites"]
        and dynamic["unclassified_sites"] == summary["unclassified_sites"] == 0
        and dynamic["blocking_sites"] == summary["blocker_count"] == 0
        and ledger["blockers"] == []
    )
    _require(
        dynamic["satisfied"] is actual_dynamic_evidence,
        "dynamic prerequisite boolean differs from ledger evidence",
    )

    ledger_sha256 = hashlib.sha256(ledger_bytes).hexdigest()
    derivation = directive["canonical_source_errata"]["allowed_source_replacements"]
    _require(
        ledger_sha256
        == dynamic["ledger_sha256"]
        == derivation["ledger_sha256"],
        "ledger digest differs across bytes, index, and directive",
    )
    checkpoint_sha256 = hashlib.sha256(checkpoint_bytes).hexdigest()
    checkpoint_summary = checkpoint["summary"]
    _require(
        dynamic["live_checkpoint_path"]
        == CHECKPOINT.relative_to(ROOT).as_posix()
        and dynamic["live_checkpoint_schema_version"]
        == checkpoint["schema_version"]
        and dynamic["live_checkpoint_sha256"] == checkpoint_sha256
        and dynamic["live_checkpoint_tracked_sites"]
        == checkpoint_summary["tracked_site_count"]
        and dynamic["live_checkpoint_unclassified_sites"]
        == checkpoint_summary["unclassified_sites"]
        == 0
        and dynamic["live_checkpoint_blocking_sites"]
        == checkpoint_summary["blocker_count"]
        == 0,
        "live checkpoint differs from the index prerequisite",
    )
    expected_projection = {
        "status": requirement["status"],
        "dynamic_import_audit_classification.satisfied": str(
            dynamic["satisfied"]
        ).lower(),
        "schema": dynamic["required_schema_version"],
        "candidate_sites": str(dynamic["candidate_sites"]),
        "classified_sites": str(dynamic["classified_sites"]),
        "unclassified_sites": str(dynamic["unclassified_sites"]),
        "blocking_sites": str(dynamic["blocking_sites"]),
        "m0_bound_implementation_baseline": m0["bound_implementation_baseline"],
        "m0_bound_artifact_sha256": m0["bound_artifact_sha256"],
        "ledger_sha256": ledger_sha256,
        "live_checkpoint_sha256": checkpoint_sha256,
        "live_checkpoint_tracked_sites": str(checkpoint_summary["tracked_site_count"]),
    }
    for label, text in (
        ("R17 specification", specification),
        ("index markdown", index_markdown),
    ):
        _require(
            _text_state_projection(text) == expected_projection,
            f"{label} state projection differs from index JSON",
        )

    revision = m0["bound_implementation_baseline"]
    _require(
        re.fullmatch(r"[0-9a-f]{40}", revision) is not None,
        "M0 baseline is not a full Git revision",
    )
    ancestor = subprocess.run(
        [
            "git",
            "merge-base",
            "--is-ancestor",
            m0["ancestor_candidate_commit"],
            revision,
        ],
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    _require(ancestor.returncode == 0, "M0 candidate is not an ancestor of baseline")
    for path, expected_sha256 in m0["bound_artifact_sha256"].items():
        bound = subprocess.run(
            ["git", "show", f"{revision}:{path}"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout
        _require(
            hashlib.sha256(bound).hexdigest() == expected_sha256,
            f"M0 artifact digest differs at {path}",
        )

    combined = "\n".join(
        (json.dumps(index, ensure_ascii=False), index_markdown, specification)
    )
    for residue in (
        "gravity.agent-module-reference-dispositions.v1",
        "candidate_sites=227",
        "classified_sites=227",
        '"candidate_sites": 227',
        '"classified_sites": 227',
        '"site_count": 227',
        "3fa8fe6c3247fd5bdbcd9cded32f89b4644e8515",
        "87bd51daac6b88f7aa31bb740a84cc14a0a0147c",
    ):
        _require(residue not in combined, f"previous state residue: {residue}")


class AgentModuleReferenceDispositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = LEDGER.read_bytes()
        cls.document = json.loads(cls.raw)
        cls.checkpoint_raw = CHECKPOINT.read_bytes()
        cls.checkpoint = json.loads(cls.checkpoint_raw)
        cls.directive = json.loads(DIRECTIVE.read_text(encoding="utf-8"))

    def test_reviewed_fixture_sha256_is_bound(self) -> None:
        self.assertEqual(LEDGER_SHA256, hashlib.sha256(self.raw).hexdigest())

    def test_current_ledger_satisfies_the_machine_contract(self) -> None:
        validate_ledger(self.document)

    def test_checkpoint_receipt_satisfies_the_machine_contract(self) -> None:
        validate_checkpoint_receipt(self.checkpoint)

    def test_repository_scan_reproduces_the_checked_in_checkpoint(self) -> None:
        self.assertEqual(self.checkpoint_raw, render_document(build_document()))

    def test_checkpoint_dispositions_cover_both_scan_denominators(self) -> None:
        audit = scan_repository()
        reference_keys = {source_key(row) for row in audit.references}
        manual_keys = {source_key(row) for row in audit.manual_review}
        checkpoint_reference_keys = {
            site["source_key"]
            for site in checkpoint_sites(self.checkpoint)
            if "reference" in site["tracked_sources"]
        }
        checkpoint_manual_keys = {
            site["source_key"]
            for site in checkpoint_sites(self.checkpoint)
            if "manual_review" in site["tracked_sources"]
        }
        self.assertEqual(reference_keys, checkpoint_reference_keys)
        self.assertEqual(manual_keys, checkpoint_manual_keys)
        summary = self.checkpoint["summary"]
        self.assertEqual(summary["reference_site_count"], len(reference_keys))
        self.assertEqual(summary["manual_review_site_count"], len(manual_keys))
        self.assertEqual(summary["reference_manual_overlap_count"], len(reference_keys & manual_keys))
        self.assertEqual(summary["tracked_site_count"], len(reference_keys | manual_keys))
        if self.checkpoint["source_audit"]["owner_state"] == "baseline":
            self.assertEqual((907, 242, 240, 909), (
                len(reference_keys),
                len(manual_keys),
                len(reference_keys & manual_keys),
                len(reference_keys | manual_keys),
            ))

    def test_new_exact_dynamic_and_alias_loader_sites_cannot_escape_disposition(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tests", prefix="r17-tracked-") as temp:
            attack = Path(temp) / "attack.py"
            attack.write_text(
                "import importlib\n"
                'dynamic = importlib.import_module("gravity_sdk.agent_sources")\n'
                'alias = acquire("gravity_sdk.agent_sources")\n',
                encoding="utf-8",
            )
            generated = build_document()
            relative = attack.relative_to(ROOT).as_posix()
            sites = [
                site
                for site in checkpoint_sites(generated)
                if site["source"]["file"] == relative
            ]
        self.assertEqual(3, len(sites))
        self.assertEqual(
            {"dynamic_import", "string_reference"},
            {site["source"]["reference_category"] for site in sites},
        )
        self.assertTrue(all(site["disposition"] == "rewrite_reference" for site in sites))
        self.assertTrue(all(site["tracked_sources"] == ["reference"] for site in sites))

    def test_unknown_dynamic_domain_remains_a_blocker_after_regeneration(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "tests", prefix="r17-blocker-") as temp:
            attack = Path(temp) / "attack.py"
            attack.write_text(
                "from importlib import import_module\n"
                "owner = import_module(runtime_module_name)\n",
                encoding="utf-8",
            )
            generated = build_document()
            relative = attack.relative_to(ROOT).as_posix()
            blockers = [
                site
                for site in checkpoint_sites(generated)
                if site["source"]["file"] == relative
                and site["disposition"] == "blocker"
            ]
        self.assertEqual(1, len(blockers))
        self.assertEqual("unreviewed_dynamic_import_domain", blockers[0]["reason_code"])
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "checkpoint.json"
            output.write_bytes(render_document(generated))
            with patch.object(
                checkpoint_generator, "build_document", return_value=generated
            ), patch.object(checkpoint_generator, "OUTPUT", output):
                self.assertEqual(1, checkpoint_generator.main(["--check"]))

    def test_index_and_specification_state_agree(self) -> None:
        validate_index_and_specification_state(
            json.loads(INDEX_JSON.read_text(encoding="utf-8")),
            INDEX_MARKDOWN.read_text(encoding="utf-8"),
            R17_SPECIFICATION.read_text(encoding="utf-8"),
            self.document,
            self.directive,
            ledger_bytes=self.raw,
            checkpoint=self.checkpoint,
            checkpoint_bytes=self.checkpoint_raw,
        )

    def test_index_and_specification_state_injections_fail_closed(self) -> None:
        index = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
        index_markdown = INDEX_MARKDOWN.read_text(encoding="utf-8")
        specification = R17_SPECIFICATION.read_text(encoding="utf-8")

        def mutated_index(field: str) -> dict[str, Any]:
            selected = copy.deepcopy(index)
            requirement = next(
                item for item in selected["requirements"] if item.get("id") == "R17"
            )
            prerequisite = next(
                item
                for item in requirement["ready_prerequisites"]
                if item.get("id") == field
            )
            if field == "dynamic_import_audit_classification":
                prerequisite["satisfied"] = False
            else:
                first = next(iter(prerequisite["bound_artifact_sha256"]))
                prerequisite["bound_artifact_sha256"][first] = "0" * 64
            return selected

        injections = {
            "spec dynamic marker": (
                index,
                index_markdown,
                specification.replace(
                    "dynamic_import_audit_classification.satisfied=true",
                    "dynamic_import_audit_classification.satisfied=false",
                    1,
                ),
            ),
            "index markdown dynamic marker": (
                index,
                index_markdown.replace(
                    "dynamic_import_audit_classification.satisfied=true",
                    "dynamic_import_audit_classification.satisfied=false",
                    1,
                ),
                specification,
            ),
            "index JSON boolean": (
                mutated_index("dynamic_import_audit_classification"),
                index_markdown,
                specification,
            ),
            "spec M0 revision": (
                index,
                index_markdown,
                specification.replace(
                    "m0_bound_implementation_baseline="
                    "113176a381b6d232e95a112d78d1d2f4bc5ac024",
                    "m0_bound_implementation_baseline=" + "0" * 40,
                    1,
                ),
            ),
            "index markdown M0 revision": (
                index,
                index_markdown.replace(
                    "m0_bound_implementation_baseline="
                    "113176a381b6d232e95a112d78d1d2f4bc5ac024",
                    "m0_bound_implementation_baseline=" + "0" * 40,
                    1,
                ),
                specification,
            ),
            "index JSON M0 digest": (
                mutated_index("m0_characterization"),
                index_markdown,
                specification,
            ),
            "spec M0 digest": (
                index,
                index_markdown,
                specification.replace(
                    'm0_bound_artifact_sha256={"tests/agent_migration_characterization.py":"'
                    "97b3c71842b3904213ec24667ae09f4c821df0384f6667847e3c03f6c9d9d640",
                    'm0_bound_artifact_sha256={"tests/agent_migration_characterization.py":"'
                    + "0" * 64,
                    1,
                ),
            ),
            "spec ledger digest": (
                index,
                index_markdown,
                specification.replace(
                    "ledger_sha256=" + LEDGER_SHA256,
                    "ledger_sha256=" + "0" * 64,
                    1,
                ),
            ),
            "index markdown ledger digest": (
                index,
                index_markdown.replace(
                    "ledger_sha256=" + LEDGER_SHA256,
                    "ledger_sha256=" + "0" * 64,
                    1,
                ),
                specification,
            ),
            "index JSON ledger digest": (
                copy.deepcopy(index),
                index_markdown,
                specification,
            ),
        }
        ledger_index = injections["index JSON ledger digest"][0]
        ledger_requirement = next(
            item for item in ledger_index["requirements"] if item.get("id") == "R17"
        )
        dynamic = next(
            item
            for item in ledger_requirement["ready_prerequisites"]
            if item.get("id") == "dynamic_import_audit_classification"
        )
        dynamic["ledger_sha256"] = "0" * 64
        for label, (injected_index, injected_markdown, injected_spec) in injections.items():
            with self.subTest(label=label), self.assertRaises(AssertionError):
                validate_index_and_specification_state(
                    injected_index,
                    injected_markdown,
                    injected_spec,
                    self.document,
                    self.directive,
                    ledger_bytes=self.raw,
                    checkpoint=self.checkpoint,
                    checkpoint_bytes=self.checkpoint_raw,
                )

    def test_active_scope_owner_documents_are_in_the_consistency_set(self) -> None:
        roadmap = ROADMAP.read_text(encoding="utf-8")
        technical_debt = TECHNICAL_DEBT.read_text(encoding="utf-8")
        corrected_roadmap = roadmap.replace(
            "\u79fb\u9664 82 \u4e2a\u65e7 deep module path\uff0881 \u8fc1\u79fb + pagination \u5220\u9664\uff09",
            "\u79fb\u9664 83 \u4e2a\u65e7 deep module path\uff0882 \u8fc1\u79fb + pagination \u5220\u9664\uff09",
            1,
        )
        corrected_debt = technical_debt.replace(
            "\u6839 `.py` \u4e3a 496\u3001\n  `agents/` \u542b 81 \u4e2a\u5b9e\u73b0\u6a21\u5757",
            "\u6839 `.py` \u4e3a 495\u3001\n  `agents/` \u542b 82 \u4e2a\u5b9e\u73b0\u6a21\u5757",
            1,
        )
        validate_active_scope_owner_projection(
            corrected_roadmap,
            corrected_debt,
            self.document,
        )

        injections = {
            "roadmap old-path count": (
                corrected_roadmap.replace("\u79fb\u9664 83 \u4e2a", "\u79fb\u9664 84 \u4e2a", 1),
                corrected_debt,
                "roadmap R17 scope projection differs",
            ),
            "roadmap move count": (
                corrected_roadmap.replace("\uff0882 \u8fc1\u79fb", "\uff0881 \u8fc1\u79fb", 1),
                corrected_debt,
                "roadmap R17 scope projection differs",
            ),
            "technical-debt root count": (
                corrected_roadmap,
                corrected_debt.replace("\u6839 `.py` \u4e3a 495", "\u6839 `.py` \u4e3a 496", 1),
                "technical-debt R17 exit projection differs",
            ),
            "technical-debt agents count": (
                corrected_roadmap,
                corrected_debt.replace("`agents/` \u542b 82", "`agents/` \u542b 81", 1),
                "technical-debt R17 exit projection differs",
            ),
        }
        for label, (injected_roadmap, injected_debt, message) in injections.items():
            with self.subTest(label=label), self.assertRaisesRegex(
                AssertionError, message
            ):
                validate_active_scope_owner_projection(
                    injected_roadmap,
                    injected_debt,
                    self.document,
                )

        try:
            validate_active_scope_owner_projection(
                roadmap,
                technical_debt,
                self.document,
            )
        except AssertionError:
            self.assertIn(
                "\u79fb\u9664 82 \u4e2a\u65e7 deep module path\uff0881 \u8fc1\u79fb + pagination \u5220\u9664\uff09",
                roadmap,
            )
            self.assertIn("\u6839 `.py` \u4e3a 496", technical_debt)
            self.assertIn("`agents/` \u542b 81 \u4e2a\u5b9e\u73b0\u6a21\u5757", technical_debt)

    def test_frozen_scope_supports_all_three_owner_states(self) -> None:
        moves = self.document["scope"]["one_to_one_moves"]
        states = {
            "baseline": (82, True),
            "phase_1": (34, False),
            "phase_2": (0, False),
        }
        for label, (old_count, pagination_old) in states.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                ledger = root / "tests/fixtures/agent_module_reference_dispositions.json"
                ledger.parent.mkdir(parents=True)
                ledger.write_bytes(self.raw)
                pagination_target = (
                    root / "src/gravity_sdk/pagination_completeness.py"
                )
                pagination_target.parent.mkdir(parents=True)
                pagination_target.write_text("", encoding="utf-8")
                retained = root / "src/gravity_sdk/agent_runtime_contracts.py"
                retained.write_text("", encoding="utf-8")
                if pagination_old:
                    (root / "src/gravity_sdk/agent_pagination.py").write_text(
                        "", encoding="utf-8"
                    )
                for index, move in enumerate(moves):
                    module = (
                        move["old_module"]
                        if index < old_count
                        else move["new_module"]
                    )
                    path = root / "src" / Path(*module.split(".")).with_suffix(".py")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text("", encoding="utf-8")
                mappings, mapping = make_module_map(root)
                self.assertEqual(84, len(mappings))
                self.assertEqual(84, len(mapping))
                self.assertEqual(
                    82,
                    sum(
                        item.new_module.startswith("gravity_sdk.agents.")
                        for item in mappings
                    ),
                )

    def test_relative_date_target_uses_the_shared_boundary_token_rule(self) -> None:
        mappings, _ = make_module_map(ROOT)
        relative_date = next(
            item
            for item in mappings
            if item.old_module == "gravity_sdk.relative_date_agent"
        )
        self.assertEqual("gravity_sdk.agents.relative_date", relative_date.new_module)
        self.assertEqual("src/gravity_sdk/agents/relative_date.py", relative_date.new_file)
        self.assertFalse(relative_date.target_exists)
        self.assertFalse(relative_date.casefold_target_collision)
        self.assertFalse(relative_date.stdlib_basename_collision)
        self.assertFalse((ROOT / "src/gravity_sdk/relative_date.py").exists())

    def test_canonical_errata_replacements_are_derived_only_from_ledger(self) -> None:
        declaration = self.directive["canonical_source_errata"][
            "allowed_source_replacements"
        ]
        self.assertIsInstance(declaration, dict)
        self.assertNotIn("old", declaration)
        self.assertNotIn("new", declaration)
        self.assertEqual(
            "tests/fixtures/agent_module_reference_dispositions.json",
            declaration["ledger_repository_path"],
        )
        self.assertRegex(declaration["ledger_git_blob"], r"^[0-9a-f]{40}$")
        self.assertEqual(LEDGER_SHA256, declaration["ledger_sha256"])
        self.assertEqual(
            errata_validator.REVIEWED_AT_REVISION,
            declaration["reviewed_at_revision"],
        )
        replacements = derive_source_replacements(self.directive, self.document)
        selected_rows = [
            site
            for site in self.document["sites"]
            if site["disposition"] == declaration["disposition"]
            and site["source"]["file"] == declaration["source_file"]
        ]
        self.assertEqual(4, len(replacements))
        self.assertEqual(
            {site["source_key"] for site in selected_rows},
            {replacement["source_key"] for replacement in replacements},
        )
        self.assertEqual(
            {
                (
                    site["source"]["line"],
                    site["source"]["column"],
                    site["migration_action"]["old_text"],
                    site["migration_action"]["new_text"],
                )
                for site in selected_rows
            },
            {
                (
                    replacement["line"],
                    replacement["column"],
                    replacement["old_text"],
                    replacement["new_text"],
                )
                for replacement in replacements
            },
        )

    def test_canonical_errata_derivation_fails_closed_on_ledger_drift(self) -> None:
        extra = copy.deepcopy(self.document)
        extra["sites"].append(copy.deepcopy(extra["sites"][0]))
        injected = next(
            site
            for site in extra["sites"]
            if site["disposition"] == "rewrite_reference"
            and site["source"]["file"]
            == "specs/agent-runtime/architecture-source.md"
        )
        extra["sites"][-1] = copy.deepcopy(injected)
        with self.assertRaisesRegex(
            ErrataValidationError,
            "directive-bound ledger object",
        ):
            derive_source_replacements(self.directive, extra)

        missing = copy.deepcopy(self.document)
        missing["sites"].remove(
            next(
                site
                for site in missing["sites"]
                if site["disposition"] == "rewrite_reference"
                and site["source"]["file"]
                == "specs/agent-runtime/architecture-source.md"
            )
        )
        with self.assertRaisesRegex(
            ErrataValidationError,
            "directive-bound ledger object",
        ):
            derive_source_replacements(self.directive, missing)

        self_loop = copy.deepcopy(self.document)
        loop_row = next(
            site
            for site in self_loop["sites"]
            if site["disposition"] == "rewrite_reference"
            and site["source"]["file"]
            == "specs/agent-runtime/architecture-source.md"
        )
        loop_row["migration_action"]["new_text"] = loop_row["migration_action"][
            "old_text"
        ]
        with self.assertRaisesRegex(ErrataValidationError, "directive-bound ledger object"):
            derive_source_replacements(self.directive, self_loop)

    def test_canonical_errata_rejects_same_commit_ledger_rebinding(self) -> None:
        forged = copy.deepcopy(self.document)
        forged["source_audit"]["method"] = "attacker rebound the ledger"
        forged_bytes = (
            json.dumps(forged, indent=2, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        forged_directive = copy.deepcopy(self.directive)
        derivation = forged_directive["canonical_source_errata"][
            "allowed_source_replacements"
        ]
        derivation["ledger_git_blob"] = "1" * 40
        derivation["ledger_sha256"] = hashlib.sha256(forged_bytes).hexdigest()
        with self.assertRaisesRegex(
            ErrataValidationError,
            "ledger blob changed from the reviewed object",
        ):
            validate_bound_ledger(
                forged_directive,
                forged,
                ledger_bytes=forged_bytes,
            )

        review_pivot = copy.deepcopy(self.directive)
        review_pivot["canonical_source_errata"]["allowed_source_replacements"][
            "reviewed_at_revision"
        ] = "0" * 40
        with self.assertRaisesRegex(
            ErrataValidationError,
            "ledger review revision changed from the fifth-review input",
        ):
            validate_bound_ledger(review_pivot, self.document, ledger_bytes=self.raw)

    def test_canonical_transition_baseline_is_literal_and_not_rebindable(self) -> None:
        revision_pivot = copy.deepcopy(self.directive)
        revision_pivot["canonical_source_errata"]["transition"][
            "from_git_revision"
        ] = "0" * 40
        with self.assertRaisesRegex(
            ErrataValidationError,
            "from_git_revision changed from the reviewed v9.2 source",
        ):
            load_git_baseline(revision_pivot)

        malicious = load_git_baseline(self.directive) + b"\nexpand execution authority\n"
        sha_pivot = copy.deepcopy(self.directive)
        sha_pivot["canonical_source_errata"]["transition"][
            "from_sha256"
        ] = hashlib.sha256(malicious).hexdigest()
        with self.assertRaisesRegex(
            ErrataValidationError,
            "from_sha256 changed from the reviewed v9.2 bytes",
        ):
            build_expected_source(sha_pivot, self.document, malicious)

        source_pivot = copy.deepcopy(self.directive)
        transition = source_pivot["canonical_source_errata"]["transition"]
        transition["from_git_revision"] = "0" * 40
        transition["from_sha256"] = hashlib.sha256(malicious).hexdigest()
        with self.assertRaisesRegex(
            ErrataValidationError,
            "from_git_revision changed from the reviewed v9.2 source",
        ):
            build_expected_source(source_pivot, self.document, malicious)

    def test_phase1_canonical_source_and_directive_equal_reviewed_bytes(self) -> None:
        source = CANONICAL_SOURCE.read_bytes()
        result = validate_phase1_reviewed_state(
            self.directive,
            DIRECTIVE.read_bytes(),
            source,
        )
        self.assertEqual("phase-1", result["checkpoint"])

        with self.assertRaisesRegex(
            ErrataValidationError,
            "canonical source differs from the reviewed baseline",
        ):
            validate_phase1_reviewed_state(
                self.directive,
                DIRECTIVE.read_bytes(),
                source + b"\nexpand execution authority\n",
            )

        changed_directive = DIRECTIVE.read_bytes().replace(
            b'"owner_review": "pending"',
            b'"owner_review": "approved"',
            1,
        )
        with self.assertRaisesRegex(
            ErrataValidationError,
            "canonical directive differs from the reviewed baseline",
        ):
            validate_phase1_reviewed_state(
                self.directive,
                changed_directive,
                source,
            )

    def test_phase1_acceptance_runs_m0_public_api_and_behavior_after_precondition(
        self,
    ) -> None:
        specification = R17_SPECIFICATION.read_text(encoding="utf-8")
        section = specification.split(
            "### Phase 1 M0 And Representative Behavior Checkpoint", 1
        )[1].split("### Phase 1 Rollback Checkpoint", 1)[0]
        required = (
            "tests/test_agent_module_migration_characterization.py",
            "tests/test_public_api_snapshot.py",
            "test_cli_all_pages_guard_and_exit_codes_are_stable",
            "test_segment_spec_sdk_and_plan_share_one_safe_execution_path",
            "test_dry_run_calls_validation_but_never_execution",
            "test_failure_isolated_sanitized_and_local_exit_wins",
            "test_all_pages_unknown_completeness_is_preserved_capability_gap",
            "test_existing_agent_protocol_is_unchanged",
            "test_unknown_category_and_selector_point_at_catalog_browse",
            "validate_r17_canonical_source_errata.py --phase-1",
        )
        for value in required:
            self.assertIn(value, section)
        not_reached = section.index("Phase 1 behavior checkpoint not reached")
        regression = section.index(
            "R17 Phase 1 behavior regression after checkpoint preconditions passed"
        )
        self.assertLess(not_reached, regression)

    def test_canonical_errata_final_assertion_is_full_text_and_one_shot(self) -> None:
        baseline = load_git_baseline(self.directive)
        expected = build_expected_source(self.directive, self.document, baseline)
        final_directive = copy.deepcopy(self.directive)
        transition = final_directive["canonical_source_errata"]["transition"]
        final_directive["version"] = transition["to_version"]
        final_directive["supersedes"] = {
            "version": transition["from_version"],
            "sha256": transition["from_sha256"],
        }
        final_directive["canonical_source"]["sha256"] = hashlib.sha256(
            expected
        ).hexdigest()
        final_directive["canonical_source_errata"]["one_shot"] = {
            "state": "consumed",
            "reusable": False,
            "consumed_by": "R17",
            "consumed_at_checkpoint": "R17-phase-2-core",
        }
        result = validate_final_state(
            final_directive, self.document, expected, baseline
        )
        self.assertEqual(4, result["source_replacements"])

        with self.assertRaisesRegex(
            ErrataValidationError,
            "diff exceeds the ledger-derived errata",
        ):
            validate_final_state(
                final_directive,
                self.document,
                expected + b"unexpected second source change\n",
                baseline,
            )

        ledger_drift = copy.deepcopy(self.document)
        drift_row = next(
            site
            for site in ledger_drift["sites"]
            if site["source"].get("old_value") == "agent_handoff"
            and site["migration_action"].get("old_text") == "agent_handoff"
        )
        drift_row["migration_action"].update(
            {
                "new_text": "agents.handoff_next",
                "new_module": "gravity_sdk.agents.handoff_next",
            }
        )
        with self.assertRaisesRegex(
            ErrataValidationError,
            "directive-bound ledger object",
        ):
            build_expected_source(
                self.directive, ledger_drift, baseline
            )

        reused = copy.deepcopy(final_directive)
        reused["canonical_source_errata"]["one_shot"]["consumed_by"] = "R18"
        with self.assertRaisesRegex(ErrataValidationError, "exactly once by R17"):
            validate_final_state(reused, self.document, expected, baseline)

        second_transition = copy.deepcopy(final_directive)
        second_transition["canonical_source_errata"]["transition"].update(
            {"from_version": "v9.3", "to_version": "v9.4"}
        )
        with self.assertRaisesRegex(
            ErrataValidationError, "must remain v9.2 to v9.3"
        ):
            validate_final_state(
                second_transition, self.document, expected, baseline
            )

    def test_terminal_directive_accepts_exact_r17_consumption_changes(self) -> None:
        baseline = load_git_baseline(self.directive)
        expected_source = build_expected_source(
            self.directive, self.document, baseline
        )
        terminal = copy.deepcopy(self.directive)
        transition = terminal["canonical_source_errata"]["transition"]
        terminal["version"] = "v9.3"
        terminal["supersedes"] = {
            "version": "v9.2",
            "sha256": transition["from_sha256"],
        }
        terminal["canonical_source"]["sha256"] = hashlib.sha256(
            expected_source
        ).hexdigest()
        one_shot = terminal["canonical_source_errata"]["one_shot"]
        one_shot["state"] = "consumed"
        one_shot["consumed_by"] = "R17"
        one_shot["consumed_at_checkpoint"] = "R17-phase-2-core"

        result = validate_final_state(
            terminal, self.document, expected_source, baseline
        )

        self.assertEqual("v9.2->v9.3", result["transition"])

    def test_terminal_directive_rejects_approval_scope_drift_with_path(self) -> None:
        baseline = load_git_baseline(self.directive)
        expected_source = build_expected_source(
            self.directive, self.document, baseline
        )
        terminal = copy.deepcopy(self.directive)
        transition = terminal["canonical_source_errata"]["transition"]
        terminal["version"] = transition["to_version"]
        terminal["supersedes"] = {
            "version": transition["from_version"],
            "sha256": transition["from_sha256"],
        }
        terminal["canonical_source"]["sha256"] = hashlib.sha256(
            expected_source
        ).hexdigest()
        one_shot = terminal["canonical_source_errata"]["one_shot"]
        one_shot["state"] = "consumed"
        one_shot["consumed_by"] = "R17"
        one_shot["consumed_at_checkpoint"] = "R17-phase-2-core"
        terminal["approval"]["program_implementation_scope"] = (
            "all indexed requirements without readiness gates"
        )

        with self.assertRaisesRegex(
            ErrataValidationError,
            r"approval\.program_implementation_scope",
        ):
            validate_final_state(
                terminal, self.document, expected_source, baseline
            )

    def test_terminal_directive_rejects_main_unfreeze_with_path(self) -> None:
        baseline = load_git_baseline(self.directive)
        expected_source = build_expected_source(
            self.directive, self.document, baseline
        )
        terminal = copy.deepcopy(self.directive)
        transition = terminal["canonical_source_errata"]["transition"]
        terminal["version"] = transition["to_version"]
        terminal["supersedes"] = {
            "version": transition["from_version"],
            "sha256": transition["from_sha256"],
        }
        terminal["canonical_source"]["sha256"] = hashlib.sha256(
            expected_source
        ).hexdigest()
        one_shot = terminal["canonical_source_errata"]["one_shot"]
        one_shot["state"] = "consumed"
        one_shot["consumed_by"] = "R17"
        one_shot["consumed_at_checkpoint"] = "R17-phase-2-core"
        terminal["main_integration"]["status"] = "unfrozen"

        with self.assertRaisesRegex(
            ErrataValidationError,
            r"main_integration\.status",
        ):
            validate_final_state(
                terminal, self.document, expected_source, baseline
            )

    def test_canonical_errata_rejects_semantic_change_hidden_as_metadata(self) -> None:
        malicious = copy.deepcopy(self.directive)
        malicious["canonical_source_errata"]["allowed_version_metadata_changes"][0][
            "text"
        ] = "ARCHITECTURAL SEMANTIC CHANGE: widen the execution boundary.\n\n"
        with self.assertRaisesRegex(
            ErrataValidationError,
            "version metadata allowlist changed from the exact three literals",
        ):
            build_expected_source(
                malicious,
                self.document,
                load_git_baseline(malicious),
            )

    def test_phase2_checkpoint_and_immutable_errata_gate_pass_together(self) -> None:
        audit = scan_repository()
        baseline_receipt = build_document(audit=audit)
        actionable_keys = {
            site["source_key"]
            for site in checkpoint_sites(baseline_receipt)
            if site["disposition"].startswith("rewrite_")
        }

        def remains_in_terminal(row: Any) -> bool:
            return source_key(row) not in actionable_keys or (
                row.file == "src/gravity_sdk/__init__.py"
                and row.form == "import_module"
            )

        terminal_audit = replace(
            audit,
            references=tuple(row for row in audit.references if remains_in_terminal(row)),
            manual_review=tuple(
                row for row in audit.manual_review if remains_in_terminal(row)
            ),
            owner_state="phase_2",
        )
        exports = json.loads(
            (ROOT / "tests/fixtures/public_api_exports.json").read_text(encoding="utf-8")
        )
        move_mapping = {
            move["old_module"]: move["new_module"]
            for move in baseline_receipt["scope"]["one_to_one_moves"]
        }
        for value in exports.values():
            owner = f"gravity_sdk{value[0]}"
            if owner in move_mapping:
                value[0] = move_mapping[owner].removeprefix("gravity_sdk")

        terminal_receipt = build_document(
            audit=terminal_audit,
            public_exports=exports,
        )
        validate_checkpoint_receipt(terminal_receipt)
        self.assertEqual("phase_2", terminal_receipt["source_audit"]["owner_state"])
        self.assertEqual(0, terminal_receipt["summary"]["actionable_site_count"])
        self.assertEqual([], terminal_receipt["blockers"])

        with tempfile.TemporaryDirectory() as temp:
            receipt_path = Path(temp) / "checkpoint.json"
            exports_path = Path(temp) / "public_api_exports.json"
            exports_path.write_text(json.dumps(exports), encoding="utf-8")
            with patch.object(
                checkpoint_generator, "scan_repository", return_value=terminal_audit
            ), patch.object(
                checkpoint_generator, "PUBLIC_EXPORTS", exports_path
            ), patch.object(
                checkpoint_generator, "OUTPUT", receipt_path
            ):
                self.assertEqual(0, checkpoint_generator.main([]))
                self.assertEqual(0, checkpoint_generator.main(["--check"]))

        baseline = load_git_baseline(self.directive)
        expected = build_expected_source(self.directive, self.document, baseline)
        final_directive = copy.deepcopy(self.directive)
        transition = final_directive["canonical_source_errata"]["transition"]
        final_directive["version"] = transition["to_version"]
        final_directive["supersedes"] = {
            "version": transition["from_version"],
            "sha256": transition["from_sha256"],
        }
        final_directive["canonical_source"]["sha256"] = hashlib.sha256(
            expected
        ).hexdigest()
        final_directive["canonical_source_errata"]["one_shot"] = {
            "state": "consumed",
            "reusable": False,
            "consumed_by": "R17",
            "consumed_at_checkpoint": "R17-phase-2-core",
        }
        result = validate_final_state(
            final_directive,
            self.document,
            expected,
            baseline,
        )
        self.assertEqual("v9.2->v9.3", result["transition"])

    def test_canonical_errata_rejects_forged_move_with_synced_source_digest(self) -> None:
        forged = copy.deepcopy(self.document)
        row = next(
            site
            for site in forged["sites"]
            if site["source"].get("file")
            == "specs/agent-runtime/architecture-source.md"
            and site["migration_action"].get("old_module")
            == "gravity_sdk.agent_capabilities"
        )
        row["migration_action"].update(
            {
                "new_module": "gravity_sdk.agents.unrelated_owner",
                "new_text": "agents/unrelated_owner.py",
            }
        )
        forged["summary"]["sites_sha256"] = _canonical_sites_sha256(
            forged["sites"]
        )
        forged_directive = copy.deepcopy(self.directive)
        forged_bytes = (json.dumps(forged, indent=2, ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        forged_directive["canonical_source_errata"]["allowed_source_replacements"][
            "ledger_sha256"
        ] = hashlib.sha256(forged_bytes).hexdigest()
        baseline = load_git_baseline(self.directive)
        with self.assertRaisesRegex(
            ErrataValidationError,
            "ledger SHA-256 changed from the reviewed bytes",
        ):
            build_expected_source(forged_directive, forged, baseline)

    def test_current_canonical_source_still_matches_v92_binding(self) -> None:
        source = CANONICAL_SOURCE.read_bytes()
        self.assertEqual(load_git_baseline(self.directive), source)
        self.assertEqual(
            self.directive["canonical_source"]["sha256"],
            hashlib.sha256(source).hexdigest(),
        )

    def test_governance_exclusion_is_narrow_and_explicit(self) -> None:
        for path in GENERATED_GOVERNANCE_FILES:
            self.assertTrue(is_generated_governance_artifact(path), path)
        self.assertTrue(
            is_generated_governance_artifact(
                "specs/agent-runtime/R17-agent-module-package-migration.md"
            )
        )
        self.assertTrue(is_generated_governance_artifact("tmp/codex/audit/output.csv"))
        protected = (
            "AGENTS.md",
            "specs/agent-runtime/architecture-source.md",
            "specs/agent-runtime/index.json",
            "specs/agent-runtime/index.md",
            "docs/maintainers/technical-debt.md",
            "tests/agent_migration_characterization.py",
            "src/gravity_sdk/agent_sources.py",
        )
        for path in protected:
            self.assertFalse(is_generated_governance_artifact(path), path)

        scanner = ReferenceScanner(
            {"gravity_sdk.agent_sources": "gravity_sdk.agents.sources"}
        )
        references, _ = scanner.scan_python(
            "src/gravity_sdk/real_consumer.py",
            "from gravity_sdk.agent_sources import snapshot_recipe_cards\n",
        )
        self.assertEqual(["static_import"], [item.category for item in references])
        pagination_scanner = ReferenceScanner({PAGINATION_MODULE: PAGINATION_TARGET})
        references, _ = pagination_scanner.scan_python(
            "src/gravity_sdk/real_pagination_consumer.py",
            "from .agent_pagination import compact_pagination\n",
        )
        self.assertEqual(
            [("static_import", PAGINATION_MODULE, PAGINATION_TARGET)],
            [(item.category, item.old_value, item.new_value) for item in references],
        )

    def test_bare_context_classifier_separates_records_from_consumers(self) -> None:
        pagination_rows = [
            site
            for site in self.document["sites"]
            if site["source"].get("old_value") == "agent_pagination"
        ]
        self.assertEqual(3, len(pagination_rows))
        self.assertEqual(
            {DELETED_MODULE_RECORD},
            {
                generator_classify_active_bare_context(
                    PAGINATION_MODULE,
                    site["source"]["audit_context"],
                )
                for site in pagination_rows
            },
        )
        for context in (
            '"consolidated_deleted_modules": [\n  "agent_pagination"\n]',
            "The deleted module is `agent_pagination.py`; keep the retained owner.",
        ):
            self.assertEqual(
                DELETED_MODULE_RECORD,
                generator_classify_active_bare_context(PAGINATION_MODULE, context),
            )
        for context in (
            "from gravity_sdk.agent_pagination import compact_pagination",
            "from .agent_pagination import compact_pagination",
            "from gravity_sdk import agent_pagination",
            "import gravity_sdk.agent_pagination",
            "gravity_sdk.agent_pagination.compact_pagination(items)",
        ):
            self.assertEqual(
                RUNTIME_CONSUMER,
                generator_classify_active_bare_context(PAGINATION_MODULE, context),
            )
        self.assertEqual(
            AMBIGUOUS_REFERENCE,
            generator_classify_active_bare_context(
                PAGINATION_MODULE,
                "Review agent_pagination before R17 starts.",
            ),
        )
        dated_rows = {
            site["source"]["old_value"]: site
            for site in self.document["sites"]
            if site["source"].get("file")
            == "docs/maintainers/technical-debt.md"
            and site["source"].get("old_value")
            in {"agent_batch", "agent_input_resolution"}
        }
        self.assertEqual({"agent_batch", "agent_input_resolution"}, set(dated_rows))
        for site in dated_rows.values():
            self.assertEqual("no_migration_effect", site["disposition"])
            self.assertEqual(
                "dated_governance_decision_evidence",
                site["reason_code"],
            )
            self.assertEqual({"kind": "none"}, site["migration_action"])
        list_item_start = next(
            site["source"]
            for site in self.document["sites"]
            if str(site["source"].get("audit_snippet", "")).lstrip().startswith(
                "- **\u9000\u51fa\u6761\u4ef6**"
            )
            and site["source"].get("old_value") == "agent_runtime_contracts"
        )
        self.assertTrue(
            list_item_start["audit_context"].startswith(
                list_item_start["audit_snippet"]
            )
        )

    def test_future_exact_pagination_text_uses_bounded_context(self) -> None:
        cases = {
            "deleted qualified module": (
                "future.md",
                "The deleted module gravity_sdk.agent_pagination was consolidated "
                "and removed.",
                "no_migration_effect",
                "deleted_module_governance_fact",
            ),
            "ambiguous qualified module": (
                "future.json",
                '{\n  "note": "Review gravity_sdk.agent_pagination before R17."\n}',
                "blocker",
                "ambiguous_deleted_module_reference",
            ),
            "qualified consumer": (
                "future.md",
                "Use gravity_sdk.agent_pagination.compact_pagination(items).",
                "rewrite_consolidated_reference",
                "pagination_consolidation_reference",
            ),
            "deleted exact source path": (
                "future.md",
                "The deleted module src/gravity_sdk/agent_pagination.py was removed.",
                "no_migration_effect",
                "deleted_module_governance_fact",
            ),
        }
        mapping = {PAGINATION_MODULE: PAGINATION_TARGET}
        scanner = ReferenceScanner(mapping)
        for label, (name, content, disposition, reason) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                path = root / "docs" / name
                path.parent.mkdir(parents=True)
                path.write_text(content, encoding="utf-8")
                rows = scanner.scan_text(f"docs/{name}", content)
                exact = next(row for row in rows if row.certainty == "exact")
                result = generator_classify_reference(
                    exact,
                    {},
                    mapping,
                    root,
                )
                self.assertEqual(disposition, result["disposition"])
                self.assertEqual(reason, result["reason_code"])

        python_fact = Finding(
            "string_reference",
            "tests/future_note.py",
            1,
            1,
            "python comment module string",
            PAGINATION_MODULE,
            PAGINATION_TARGET,
            "exact",
            "# deleted module gravity_sdk.agent_pagination was removed",
        )
        result = generator_classify_reference(
            python_fact,
            {},
            mapping,
        )
        self.assertEqual("no_migration_effect", result["disposition"])
        self.assertEqual("deleted_module_governance_fact", result["reason_code"])

    def test_consumer_syntax_takes_precedence_over_dated_evidence(self) -> None:
        consumers = {
            "import": "from gravity_sdk.agent_batch import capabilities_many",
            "call": "gravity_sdk.agent_batch.capabilities_many([])",
            "patch": "patch('gravity_sdk.agent_batch.capabilities_many')",
            "attribute": "handler = gravity_sdk.agent_batch.capabilities_many",
        }
        for form, consumer in consumers.items():
            context = f"Decision record (2026-08-26)\n{consumer}"
            with self.subTest(form=form):
                self.assertEqual(
                    ACTIVE_REFERENCE,
                    generator_classify_active_bare_context(
                        "gravity_sdk.agent_batch", context
                    ),
                )

    def test_six_short_spine_rewrites_keep_the_agents_directory(self) -> None:
        paths = {"AGENTS.md", "specs/agent-runtime/architecture-source.md"}
        rows = [
            site
            for site in self.document["sites"]
            if site["source"].get("file") in paths
            and site["migration_action"].get("old_module")
            in {
                "gravity_sdk.agent_capabilities",
                "gravity_sdk.agent_composite",
                "gravity_sdk.agent_handoff",
            }
            and site["migration_action"].get("old_text", "").endswith(".py")
        ]
        self.assertEqual(6, len(rows))
        self.assertEqual(
            {
                "agents/capabilities.py",
                "agents/composite.py",
                "agents/handoff.py",
            },
            {site["migration_action"]["new_text"] for site in rows},
        )

    def test_rewrite_targets_cannot_alias_unrelated_existing_root_files(self) -> None:
        conflicts: list[str] = []
        for site in self.document["sites"]:
            action = site.get("migration_action", {})
            new_text = str(action.get("new_text", "")).replace("\\", "/")
            new_module = action.get("new_module")
            if not new_text.endswith(".py") or not isinstance(new_module, str):
                continue
            root_peer = ROOT / "src/gravity_sdk" / Path(new_text).name
            root_peer_module = f"gravity_sdk.{Path(new_text).stem}"
            related = {
                PAGINATION_TARGET,
                *{
                    move["old_module"]
                    for move in self.document["scope"]["one_to_one_moves"]
                },
                *{
                    move["new_module"]
                    for move in self.document["scope"]["one_to_one_moves"]
                },
            }
            if (
                root_peer.is_file()
                and root_peer_module not in related
                and new_text == Path(new_text).name
            ):
                conflicts.append(f"{site['source_key']} -> {new_text}")
        self.assertEqual([], conflicts, f"ambiguous root-file rewrite targets: {conflicts}")

    def test_validator_rejects_consumer_disguised_as_no_effect(self) -> None:
        injected = copy.deepcopy(self.document)
        site = next(
            item
            for item in injected["sites"]
            if item["source"].get("old_value") == "agent_pagination"
        )
        consumer = "from gravity_sdk.agent_pagination import compact_pagination"
        site["source"]["audit_snippet"] = consumer
        site["source"]["audit_context"] = consumer
        with self.assertRaisesRegex(
            AssertionError,
            "active consumer syntax must rewrite or block",
        ):
            validate_ledger(injected)

    def test_validator_independently_rejects_dated_consumer_syntax(self) -> None:
        injected = copy.deepcopy(self.document)
        site = next(
            item
            for item in injected["sites"]
            if item.get("reason_code") == "dated_governance_decision_evidence"
            and item["source"].get("old_value") == "agent_batch"
        )
        consumers = {
            "import": "from gravity_sdk.agent_batch import capabilities_many",
            "call": "gravity_sdk.agent_batch.capabilities_many([])",
            "patch": "patch('gravity_sdk.agent_batch.capabilities_many')",
            "attribute": "handler = gravity_sdk.agent_batch.capabilities_many",
        }
        for form, consumer in consumers.items():
            mutated = copy.deepcopy(injected)
            mutated_site = next(
                item
                for item in mutated["sites"]
                if item["source_key"] == site["source_key"]
            )
            mutated_site["source"]["audit_snippet"] = consumer
            mutated_site["source"]["audit_context"] = (
                f"Decision record (2026-08-26)\n{consumer}"
            )
            with self.subTest(form=form), self.assertRaisesRegex(
                AssertionError,
                "active consumer syntax must rewrite or block",
            ):
                validate_ledger(mutated)

    def test_validator_rejects_required_regressions(self) -> None:
        mutations: dict[str, Any] = {}
        missing = copy.deepcopy(self.document)
        missing["sites"].pop()
        mutations["missing row"] = missing
        duplicate = copy.deepcopy(self.document)
        duplicate["sites"][1]["source_key"] = duplicate["sites"][0]["source_key"]
        mutations["duplicate key"] = duplicate
        unclassified = copy.deepcopy(self.document)
        unclassified["sites"][0]["disposition"] = "unclassified"
        mutations["unclassified row"] = unclassified
        blocker_mismatch = copy.deepcopy(self.document)
        blocker_mismatch["summary"]["blocker_count"] = 1
        mutations["blocker count mismatch"] = blocker_mismatch
        illegal_target = copy.deepcopy(self.document)
        rewrite = next(
            site
            for site in illegal_target["sites"]
            if site["disposition"] == "rewrite_reference"
        )
        rewrite["migration_action"]["new_module"] = "gravity_sdk.agents.pagination"
        mutations["illegal target"] = illegal_target
        for label, document in mutations.items():
            with self.subTest(label=label), self.assertRaises(AssertionError):
                validate_ledger(document)


class R17ResponsibilityInventoryTests(unittest.TestCase):
    def test_frozen_tree_oid_is_literal_and_resolves_from_the_bound_commit(self) -> None:
        resolved = subprocess.run(
            ["git", "rev-parse", f"{R17_ORACLE_BASELINE_COMMIT}^{{tree}}"],
            cwd=ROOT,
            check=True,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.strip()
        self.assertEqual(R17_ORACLE_TREE_OID, resolved)
        self.assertEqual(
            "tree",
            subprocess.run(
                ["git", "cat-file", "-t", R17_ORACLE_TREE_OID],
                cwd=ROOT,
                check=True,
                text=True,
                encoding="utf-8",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout.strip(),
        )

    def test_frozen_ledger_blob_is_read_from_the_pinned_tree(self) -> None:
        path = LEDGER.relative_to(ROOT).as_posix()
        frozen = _r17_frozen_blob(path)
        self.assertEqual(LEDGER_SHA256, hashlib.sha256(frozen).hexdigest())
        blob_oid = subprocess.run(
            ["git", "rev-parse", f"{R17_ORACLE_TREE_OID}:{path}"],
            cwd=ROOT,
            check=True,
            text=True,
            encoding="utf-8",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        ).stdout.strip()
        self.assertEqual(
            frozen,
            subprocess.run(
                ["git", "cat-file", "blob", blob_oid],
                cwd=ROOT,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout,
        )

    def test_legacy_signed_module_inventory_uses_no_worktree_source_io(self) -> None:
        signed = _r17_load_legacy_signed_module_inventory()
        with patch.object(
            Path, "read_text", side_effect=AssertionError("worktree text read")
        ), patch.object(
            Path, "read_bytes", side_effect=AssertionError("worktree bytes read")
        ):
            self.assertEqual(signed, _r17_build_legacy_signed_module_inventory())

    def test_legacy_signed_module_inventory_matches_frozen_recomputation(self) -> None:
        signed = _r17_load_legacy_signed_module_inventory()
        self.assertEqual(signed, _r17_build_legacy_signed_module_inventory())
        payload = dict(signed)
        digest = payload.pop("payload_sha256")
        self.assertEqual(digest, _r17_digest(payload))

    def test_current_tree_projects_to_the_frozen_responsibility_ids(self) -> None:
        current = set(_r17_read_modules(ROOT / "src/gravity_sdk"))
        frozen = _r17_load_legacy_signed_module_inventory()
        scope = json.loads(
            _r17_frozen_blob(LEDGER.relative_to(ROOT).as_posix()).decode("utf-8")
        )["scope"]
        self.assertIn(
            _r17_owner_projection_state(current, frozen, scope),
            {"baseline", "phase_1", "phase_2"},
        )

    def test_frozen_move_mapping_is_an_exact_bijection(self) -> None:
        frozen = _r17_load_legacy_signed_module_inventory()
        scope = json.loads(
            _r17_frozen_blob(LEDGER.relative_to(ROOT).as_posix()).decode("utf-8")
        )["scope"]
        moves = scope["one_to_one_moves"]
        self.assertEqual(82, len(moves))
        self.assertEqual(82, len({move["old_module"] for move in moves}))
        self.assertEqual(82, len({move["new_module"] for move in moves}))
        inventory_moves = {
            f"gravity_sdk.{row['module']}"
            for row in frozen["decisions"]
            if row["include"] and row["r17_disposition"] == "move"
        }
        self.assertEqual(inventory_moves, {move["old_module"] for move in moves})

    def test_frozen_relative_date_mapping_uses_the_boundary_token_rule(self) -> None:
        scope = json.loads(
            _r17_frozen_blob(LEDGER.relative_to(ROOT).as_posix()).decode("utf-8")
        )["scope"]
        relative_date = next(
            move
            for move in scope["one_to_one_moves"]
            if move["old_module"] == "gravity_sdk.relative_date_agent"
        )
        self.assertEqual("gravity_sdk.agents.relative_date", relative_date["new_module"])

    def test_phase1_paths_map_to_frozen_responsibilities(self) -> None:
        frozen = _r17_load_legacy_signed_module_inventory()
        scope = json.loads(
            _r17_frozen_blob(LEDGER.relative_to(ROOT).as_posix()).decode("utf-8")
        )["scope"]
        modules = _r17_phase_module_names(scope, old_count=34, pagination_old=False)
        self.assertEqual("phase_1", _r17_owner_projection_state(modules, frozen, scope))

    def test_phase2_paths_map_to_frozen_responsibilities(self) -> None:
        frozen = _r17_load_legacy_signed_module_inventory()
        scope = json.loads(
            _r17_frozen_blob(LEDGER.relative_to(ROOT).as_posix()).decode("utf-8")
        )["scope"]
        modules = _r17_phase_module_names(scope, old_count=0, pagination_old=False)
        self.assertEqual("phase_2", _r17_owner_projection_state(modules, frozen, scope))

    def test_owner_projection_rejects_old_and_new_owner_overlap(self) -> None:
        frozen = _r17_load_legacy_signed_module_inventory()
        scope = json.loads(
            _r17_frozen_blob(LEDGER.relative_to(ROOT).as_posix()).decode("utf-8")
        )["scope"]
        modules = _r17_phase_module_names(scope, old_count=34, pagination_old=False)
        move = scope["one_to_one_moves"][0]
        modules.update({move["old_module"], move["new_module"]})
        with self.assertRaisesRegex(AssertionError, "not one-to-one"):
            _r17_owner_projection_state(modules, frozen, scope)

    def test_owner_projection_rejects_an_unreviewed_phase_partition(self) -> None:
        frozen = _r17_load_legacy_signed_module_inventory()
        scope = json.loads(
            _r17_frozen_blob(LEDGER.relative_to(ROOT).as_posix()).decode("utf-8")
        )["scope"]
        modules = _r17_phase_module_names(scope, old_count=33, pagination_old=False)
        with self.assertRaisesRegex(AssertionError, "outside Phase 0/1/2"):
            _r17_owner_projection_state(modules, frozen, scope)

    def test_owner_projection_rejects_missing_fixed_owners(self) -> None:
        frozen = _r17_load_legacy_signed_module_inventory()
        scope = json.loads(
            _r17_frozen_blob(LEDGER.relative_to(ROOT).as_posix()).decode("utf-8")
        )["scope"]
        baseline = _r17_phase_module_names(scope, old_count=82, pagination_old=True)
        cases = {
            "consolidation target": scope["consolidate_delete"]["new_module"],
            "retained owner": scope["retained_modules"][0],
        }
        for label, missing in cases.items():
            with self.subTest(owner=label), self.assertRaisesRegex(
                AssertionError, "is missing"
            ):
                _r17_owner_projection_state(baseline - {missing}, frozen, scope)

    def test_legacy_signed_module_inventory_rows_are_complete(self) -> None:
        signed = _r17_load_legacy_signed_module_inventory()
        decisions = signed["decisions"]
        included = [row for row in decisions if row["include"]]
        rejected = [row for row in decisions if not row["include"]]
        comparison = signed["r17_comparison"]
        self.assertEqual(84, len(signed["members"]))
        self.assertEqual(signed["members"], sorted(row["module"] for row in included))
        self.assertEqual(92, len(decisions))
        self.assertEqual(8, len(rejected))
        non_moves = sorted(
            row["module"]
            for row in included
            if row["r17_disposition"] in {
                "retain_public_facade",
                "consolidate_delete",
            }
        )
        self.assertEqual(non_moves, comparison["independent_members_not_moves"])
        self.assertEqual([], comparison["moves_not_independent_members"])
        self.assertTrue(comparison["action_normalized_members_equal_moves"])
        self.assertEqual([], comparison["action_normalized_members_not_moves"])
        self.assertEqual([], comparison["moves_not_action_normalized_members"])
        self.assertNotIn(
            "unmapped_member", {row["r17_disposition"] for row in included}
        )

    def test_legacy_signed_boundary_cases_are_preserved(self) -> None:
        cases = {
            item["label"]: item
            for item in _r17_load_legacy_signed_module_inventory()["boundary_cases"]
        }
        contracts = cases["broader_runtime_contracts_owner"]
        self.assertFalse(contracts["selected"])
        self.assertEqual(55, contracts["direct_consumer_count"])
        self.assertEqual([], contracts["direct_member_consumers"])
        self.assertEqual([], contracts["direct_imports_to_members"])
        find = cases["independent_find_surface"]
        self.assertFalse(find["selected"])
        self.assertEqual(["gravity.find.v1"], find["primary_schemas"])
        self.assertIn("find", find["cli_commands"])
        self.assertEqual(10, find["direct_consumer_count"])
        self.assertEqual(7, len(find["direct_member_consumers"]))
        self.assertEqual(2, len(find["direct_imports_to_members"]))

    def test_legacy_graph_observations_preserve_the_nonconvergence_claim(self) -> None:
        signed = _r17_load_legacy_signed_module_inventory()
        observations = {
            item["name"]: item for item in signed["graph_observations"]
        }
        self.assertEqual(40, observations["facade_scc"]["member_count"])
        self.assertEqual(311, observations["unrestricted_facade_closure"]["member_count"])
        self.assertEqual(496, observations["import_graph_minimum_conductance"]["member_count"])
        self.assertEqual(626, observations["cochange_component"]["member_count"])
        self.assertFalse(signed["conclusion"]["graph_methods_converged"])
        self.assertFalse(signed["conclusion"]["complete_agent_domain_proven"])

    def test_responsibility_derivation_has_no_migration_or_file_inputs(self) -> None:
        contracts = _r17_load_responsibility_contracts()
        serialized_rows = json.dumps(
            contracts["responsibilities"], sort_keys=True, ensure_ascii=True
        )
        self.assertNotIn("gravity_sdk.", serialized_rows)
        self.assertNotIn("src/", serialized_rows)
        self.assertNotIn(".py", serialized_rows)
        for row in contracts["responsibilities"]:
            self.assertFalse(
                {"module", "path", "basename", "prefix", "docstring", "consumer_count"}
                & set(row)
            )

        source = Path(__file__).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=__file__)
        gate = _r17_ast_call_closure(
            tree, ("_r17_responsibility_inventory_pipeline",)
        )
        expected_tcb = {
            "_r17_assigned_string",
            "_r17_contract_binding_matches",
            "_r17_contract_binding_witnesses",
            "_r17_contract_fragment",
            "_r17_contract_matches_fragment",
            "_r17_contract_parameters",
            "_r17_contract_raises",
            "_r17_contract_response_keys",
            "_r17_contract_symbols",
            "_r17_declared_exports",
            "_r17_derive_responsibility_inventory",
            "_r17_digest",
            "_r17_dotted_name",
            "_r17_existing",
            "_r17_fragment_exports_symbol",
            "_r17_frozen_tree_blobs",
            "_r17_import_base",
            "_r17_import_graph",
            "_r17_load_responsibility_contracts",
            "_r17_non_docstring_strings",
            "_r17_read_modules",
            "_r17_resolve_public_symbol",
            "_r17_resolve_responsibility_contract",
            "_r17_responsibility_closure",
            "_r17_responsibility_inventory_pipeline",
            "_r17_responsibility_model",
            "_r17_string_sequence",
            "_r17_subscript_key",
            "_r17_symbol_bindings",
            "_require",
        }
        self.assertEqual(expected_tcb, set(gate["reachable"]))
        self.assertIn("_r17_read_modules", gate["reachable"])
        self.assertEqual({}, gate["unresolved_name_calls"])

        allowed_external_calls = {
            "AssertionError",
            "all",
            "any",
            "ast.parse",
            "ast.unparse",
            "ast.walk",
            "bool",
            "collections.deque",
            "dict",
            "enumerate",
            "frozenset",
            "hashlib.sha256",
            "int",
            "isinstance",
            "json.dumps",
            "json.loads",
            "len",
            "list",
            "next",
            "range",
            "re.fullmatch",
            "reversed",
            "set",
            "sorted",
            "str",
            "subprocess.Popen",
            "subprocess.run",
            "tuple",
        }
        resolved_calls = {
            call
            for calls in gate["resolved_calls"].values()
            for call in calls
        }
        external_calls = resolved_calls - set(gate["functions"])
        self.assertEqual(set(), external_calls - allowed_external_calls)

        allowed_globals = (
            expected_tcb
            | set(vars(builtins))
            | {
                "Any",
                "Path",
                "R17_ORACLE_TREE_OID",
                "R17_PROTOCOL_PATTERN",
                "R17_RESPONSIBILITY_CONTRACTS_JSON",
                "R17_RESPONSIBILITY_SCHEMA",
                "ROOT",
                "ast",
                "deque",
                "hashlib",
                "json",
                "re",
                "subprocess",
            }
        )
        for name in gate["reachable"]:
            node = gate["functions"][name]
            parameters = {
                argument.arg
                for argument in (
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                )
            }
            if node.args.vararg is not None:
                parameters.add(node.args.vararg.arg)
            if node.args.kwarg is not None:
                parameters.add(node.args.kwarg.arg)
            local_names = parameters | {
                child.id
                for child in ast.walk(node)
                if isinstance(child, ast.Name)
                and isinstance(child.ctx, (ast.Store, ast.Del))
            }
            loaded_names = {
                child.id
                for child in ast.walk(node)
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
            }
            self.assertEqual(
                set(), (loaded_names - local_names) - allowed_globals, name
            )

        alias_probe = ast.parse(
            "import ast as syntax\n"
            "from scripts.audit_agent_module_references import scan_repository as helper\n"
            "def forbidden_local():\n    pass\n"
            "alias = forbidden_local\n"
            "reader = open\n"
            "def root():\n"
            "    alias()\n"
            "    syntax.get_docstring(None)\n"
            "    helper()\n"
            "    reader('ignored')\n"
        )
        alias_gate = _r17_ast_call_closure(alias_probe, ("root",))
        self.assertEqual({"forbidden_local", "root"}, set(alias_gate["reachable"]))
        self.assertEqual(
            {
                "ast.get_docstring",
                "forbidden_local",
                "open",
                "scripts.audit_agent_module_references.scan_repository",
            },
            set(alias_gate["resolved_calls"]["root"]),
        )

        real_popen = subprocess.Popen
        observed_git_calls: list[tuple[str, ...]] = []

        def guarded_popen(command: list[str], *args: Any, **kwargs: Any) -> Any:
            self.assertIn(
                command,
                [
                    [
                        "git", "ls-tree", "-r", "-z", R17_ORACLE_TREE_OID,
                        "--", "src/gravity_sdk",
                    ],
                    ["git", "cat-file", "--batch"],
                ],
            )
            observed_git_calls.append(tuple(command))
            return real_popen(command, *args, **kwargs)

        blocked = AssertionError("forbidden derivation capability")
        with patch.object(
            Path, "read_text", side_effect=AssertionError("derivation text read")
        ), patch.object(
            Path, "read_bytes", side_effect=AssertionError("derivation bytes read")
        ), patch.object(
            Path, "open", side_effect=AssertionError("derivation path open")
        ), patch.object(
            builtins, "open", side_effect=AssertionError("derivation builtin open")
        ), patch.object(
            ast, "get_docstring", side_effect=AssertionError("derivation docstring read")
        ), patch.object(
            subprocess, "Popen", side_effect=guarded_popen
        ), patch(
            __name__ + "._r17_direct_consumer_counts", side_effect=blocked
        ), patch(
            __name__ + "._r17_compare_responsibilities_to_migration_ledger",
            side_effect=blocked,
        ), patch(
            __name__ + "._r17_read_legacy_modules", side_effect=blocked
        ), patch(
            __name__ + "._r17_load_legacy_signed_module_inventory",
            side_effect=blocked,
        ):
            self.assertEqual(
                84,
                _r17_responsibility_inventory_pipeline(None)["member_count"],
            )
        self.assertEqual(2, len(observed_git_calls))

    def test_protocol_discovery_excludes_docstrings_by_structure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="r17-docstrings-") as raw_temp:
            package_root = Path(raw_temp) / "synthetic_sdk"
            package_root.mkdir()
            (package_root / "surface.py").write_text(
                '"""gravity.module-doc.v1"""\n'
                'SCHEMA_VERSION = "gravity.actual.v1"\n'
                "class Surface:\n"
                '    """gravity.class-doc.v1"""\n'
                "\n"
                "def payload():\n"
                '    """gravity.function-doc.v1"""\n'
                '    return "gravity.returned.v1"\n',
                encoding="utf-8",
            )
            records = _r17_read_modules(package_root)
        record = records["synthetic_sdk.surface"]
        self.assertNotIn("docstring", record)
        self.assertEqual(("gravity.actual.v1",), record["schemas"])
        self.assertEqual(
            ("gravity.actual.v1", "gravity.returned.v1"),
            record["protocols"],
        )

    def test_boundary_is_invariant_to_file_structure(self) -> None:
        contracts = _r17_load_responsibility_contracts()
        records = _r17_read_modules(None)
        model = _r17_responsibility_model(records)
        baseline = _r17_derive_responsibility_inventory(model, contracts)

        renamed_model, names = _r17_rename_responsibility_nodes(model)
        renamed = _r17_derive_responsibility_inventory(renamed_model, contracts)
        self.assertEqual(642, len(names))
        self.assertTrue(set(names).isdisjoint(renamed_model["nodes"]))
        self.assertTrue(
            all(re.fullmatch(r"m[0-9]{4}", name) for name in renamed_model["nodes"])
        )
        self.assertEqual(
            set(renamed_model["nodes"]),
            set(renamed_model["graph"])
            | {target for targets in renamed_model["graph"].values() for target in targets},
        )

        self.assertTrue(any(
            ast.get_docstring(record["tree"])
            for record in records.values()
        ))
        docstring_free_records = _r17_clear_module_docstrings(records)
        self.assertFalse(any(
            ast.get_docstring(record["tree"], clean=False)
            for record in docstring_free_records.values()
        ))
        docstring_free_model = _r17_responsibility_model(docstring_free_records)
        docstring_free = _r17_derive_responsibility_inventory(
            docstring_free_model, contracts
        )

        split_merge_model, split_merge_stats = (
            _r17_split_merge_responsibility_consumers(model, baseline)
        )
        split_merge = _r17_derive_responsibility_inventory(
            split_merge_model, contracts
        )
        self.assertGreater(split_merge_stats["split_nodes"], 0)
        self.assertGreater(split_merge_stats["merged_groups"], 0)
        self.assertTrue(all(
            node["responsibility_ids"]
            for name, node in split_merge_model["nodes"].items()
            if name.startswith("compact-split-")
        ))
        self.assertTrue(all(
            not node["responsibility_ids"]
            for name, node in split_merge_model["nodes"].items()
            if name.startswith("external-merge-")
        ))
        self.assertNotEqual(
            split_merge_stats["baseline_nodes"],
            split_merge_stats["transformed_nodes"],
        )
        self.assertNotEqual(
            split_merge_stats["baseline_edges"],
            split_merge_stats["transformed_edges"],
        )
        baseline_consumers = _r17_direct_consumer_counts(model, baseline)
        transformed_consumers = _r17_direct_consumer_counts(
            split_merge_model, split_merge
        )
        self.assertTrue(any(
            transformed_consumers[name] > baseline_consumers[name]
            for name in baseline_consumers
        ))
        self.assertTrue(any(
            transformed_consumers[name] < baseline_consumers[name]
            for name in baseline_consumers
        ))

        facade_contract = next(
            row for row in contracts["responsibilities"]
            if row["id"] == "agent-facade"
        )
        with tempfile.TemporaryDirectory(prefix="r17-reexport-") as raw_temp:
            package_root = Path(raw_temp) / "gravity_sdk"
            package_root.mkdir()
            _r17_materialize_frozen_package(package_root)
            probe = (
                "import json\n"
                "from gravity_sdk.agent import discover_capabilities\n"
                "print(json.dumps(discover_capabilities(), sort_keys=True, "
                "separators=(',', ':')))\n"
            )
            control_behavior = subprocess.run(
                [sys.executable, "-c", probe],
                cwd=package_root.parent,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout
            origin, implementation = _r17_move_entry_to_reexported_submodule(
                package_root, facade_contract["entry"]["symbol"]
            )
            reexported_behavior = subprocess.run(
                [sys.executable, "-c", probe],
                cwd=package_root.parent,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ).stdout
            reexported_model = _r17_responsibility_model(
                _r17_read_modules(package_root)
            )
            reexported = _r17_derive_responsibility_inventory(
                reexported_model, contracts
            )
        self.assertEqual(control_behavior, reexported_behavior)
        reexported_owners, reexported_bindings = (
            _r17_resolve_responsibility_contract(
                reexported_model, facade_contract, None
            )
        )
        self.assertEqual((implementation,), reexported_owners)
        self.assertEqual((origin,), reexported_bindings)
        self.assertEqual(baseline["source_node_count"] + 1, reexported["source_node_count"])
        reexported_comparison = _r17_compare_responsibilities_to_migration_ledger(
            reexported
        )
        self.assertEqual(82, reexported_comparison["normalized_move_count"])
        self.assertTrue(reexported_comparison["normalized_moves_equal_ledger"])

        variants = (renamed, docstring_free, split_merge, reexported)
        member_delta = sorted(set().union(*(
            set(baseline["members"]) ^ set(variant["members"])
            for variant in variants
        )))
        comparison = _r17_compare_responsibilities_to_migration_ledger(baseline)
        observations = [
            f"baseline_members={baseline['member_count']}",
            f"renamed_members={renamed['member_count']}",
            f"docstring_free_members={docstring_free['member_count']}",
            f"split_merge_members={split_merge['member_count']}",
            f"reexported_members={reexported['member_count']}",
            f"member_delta={json.dumps(member_delta, separators=(',', ':'))}",
            (
                "relative-date-resolution=include"
                if baseline["decisions"]["relative-date-resolution"]["include"]
                else "relative-date-resolution=exclude"
            ),
            "runtime-contracts=exclude:"
            + baseline["decisions"]["runtime-contracts"]["reason"],
            "find=exclude:" + baseline["decisions"]["find"]["reason"],
            f"normalized_moves={comparison['normalized_move_count']}",
        ]
        self.assertEqual(
            [
                "baseline_members=84",
                "renamed_members=84",
                "docstring_free_members=84",
                "split_merge_members=84",
                "reexported_members=84",
                "member_delta=[]",
                "relative-date-resolution=include",
                "runtime-contracts=exclude:shared_runtime_contract",
                "find=exclude:independent_primary_protocol",
                "normalized_moves=82",
            ],
            observations,
        )
        self.assertTrue(comparison["normalized_moves_equal_ledger"])
        self.assertEqual([], comparison["responsibility_owners_not_moves"])
        self.assertEqual([], comparison["moves_not_responsibility_owners"])

    def test_requirement_summary_binds_every_legacy_inventory_digest(self) -> None:
        signed = _r17_load_legacy_signed_module_inventory()
        summary = R17_SPECIFICATION.read_text(encoding="utf-8").split(
            R17_INVENTORY_START, 1
        )[0]
        for digest in (
            signed["payload_sha256"],
            signed["method_sha256"],
            signed["members_sha256"],
            signed["source_snapshot"]["tree_sha256"],
        ):
            self.assertEqual(1, summary.count(digest), digest)


if __name__ == "__main__":
    unittest.main()
