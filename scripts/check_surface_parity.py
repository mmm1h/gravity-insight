"""Generate and gate registry-derived semantic parity across public surfaces."""

from __future__ import annotations

import argparse
import copy
import json
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from gravity_insight import GravitySDK, cli, json_output, nonempty_cli
from gravity_insight.agent_runtime_contracts import (
    canonical_digest,
    load_json_object,
    validate_schema,
)
from gravity_insight.client import GravityInsightClient
from gravity_insight.errors import UpstreamError, exit_code_for_category
from gravity_insight.export_batch import envelope_exit_code
from gravity_insight.executor import ReadExecutor
from gravity_insight.mcp.server import MCPServer, PROTOCOL_VERSION
from gravity_insight.mcp.tool_catalog import tool_catalog
from gravity_insight.models import OperationSpec, load_operation_manifest
from gravity_insight.pagination_completeness import aggregate_completeness
from gravity_insight.paths import MANIFEST_ROOT
from gravity_insight.registry import PolicyEngine, Registry
from gravity_insight.transport import TransportResponse
from gravity_insight.workspace import load_workspace


ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = Path(
    "src/gravity_insight/governance/surface-parity-baseline.json"
)
SURFACES = ("direct_sdk", "cli", "sdk_wrapper", "plan", "mcp")
MATRIX_SCHEMA_VERSION = "gravity.surface-parity-matrix.v1"
_FIXED_FETCHED_AT = "2026-08-08T06:00:00Z"
_OPAQUE_QUERY_ID = "1723000000000Abcdefghijk12345678"


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: Any = None) -> datetime:
        value = cls(2026, 8, 8, 6, 0, 0, tzinfo=timezone.utc)
        return value if tz is None else value.astimezone(tz)


class _EmptyTransport:
    is_test_transport = True

    def request(self, _method: str, _path: str, **_kwargs: Any) -> TransportResponse:
        return TransportResponse(204, {}, _FIXED_FETCHED_AT)


class _UpstreamFailureTransport:
    is_test_transport = True

    def request(self, _method: str, _path: str, **_kwargs: Any) -> TransportResponse:
        raise UpstreamError("surface parity synthetic upstream unavailable")


class _ContractOnlyFieldPolicy:
    """Keep the offline probe on operation contracts, not live metadata values."""

    @staticmethod
    def validate(*_args: Any, **_kwargs: Any) -> None:
        return None

    @staticmethod
    def dependencies(*_args: Any, **_kwargs: Any) -> tuple[Any, ...]:
        return ()


def load_operation_registry() -> Registry:
    operations = [
        operation
        for path in sorted(MANIFEST_ROOT.glob("*.json"))
        for operation in load_operation_manifest(path)
    ]
    return Registry(operations)


def stable_read_operations(registry: Registry) -> tuple[OperationSpec, ...]:
    return tuple(
        operation
        for operation in registry.all()
        if operation.stability == "stable"
        and operation.effect == "read"
        and operation.executable
    )


def stable_excluded_operations(registry: Registry) -> tuple[OperationSpec, ...]:
    return tuple(
        operation
        for operation in registry.all()
        if operation.stability == "stable"
        and operation.effect != "read"
        and operation.executable
    )


def _client(registry: Registry, transport: Any) -> GravityInsightClient:
    policy = PolicyEngine(registry)
    client = GravityInsightClient(
        registry,
        ReadExecutor(registry, policy, transport),
        field_policy=_ContractOnlyFieldPolicy(),
    )
    return client


def _json_copy(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_copy(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_copy(item) for item in value]
    return copy.deepcopy(value)


def _placeholder(value: Any, item_type: str = "string") -> Any:
    if isinstance(value, str) and value.startswith("$"):
        if item_type == "integer":
            return 1
        if "today" in value or "yesterday" in value:
            return "2026-01-01"
        return "1"
    if isinstance(value, Mapping):
        return {
            str(key): _placeholder(
                item, "integer" if str(key).endswith("_id") else "string"
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_placeholder(item, item_type) for item in value]
    return copy.deepcopy(value)


def _field_sample(field: Any) -> Any:
    if field.enum:
        return _json_copy(field.enum[0])
    if field.type == "integer":
        return 1
    if field.type == "number":
        return 1.0
    if field.type == "boolean":
        return False
    if field.type == "date":
        return "2026-01-01"
    if field.type == "datetime":
        return "2026-01-01T00:00:00+08:00"
    if field.type == "object":
        return {}
    if field.type == "array":
        count = max(1, field.min_items or 0)
        item = (
            _json_copy(field.item_enum[0])
            if field.item_enum
            else 1
            if field.item_type in {"integer", "number"}
            else "sample"
        )
        return [copy.deepcopy(item) for _ in range(count)]
    if field.name == "query_id":
        return _OPAQUE_QUERY_ID
    if field.name == "app_id":
        return "1"
    return "sample"


def sample_inputs(operation: OperationSpec) -> dict[str, Any]:
    values = {
        name: _placeholder(value, operation.fields[name].item_type or operation.fields[name].type)
        for name, value in operation.live_probe.inputs.items()
        if name in operation.fields
    }
    for field in operation.input_fields:
        if (
            field.type == "array"
            and field.name in values
            and not isinstance(values[field.name], list)
        ):
            count = max(1, field.min_items or 0)
            values[field.name] = [
                _placeholder(values[field.name], field.item_type or "string")
                for _ in range(count)
            ]
        if field.required and field.name not in values:
            values[field.name] = _field_sample(field)
    return operation.validate_inputs(values)


def _limits(operation: OperationSpec) -> tuple[int, int]:
    return 1, max(200, operation.pagination.default_page_size or 0)


def _cli_observation(
    parser: Any,
    argv: list[str],
    client: GravityInsightClient,
) -> tuple[Any, int]:
    args = parser.parse_args(argv)
    with patch("gravity_insight.runtime.build_client", return_value=client):
        result = cli.dispatch_command(
            args,
            cli._client,
            cli._object_input,
            nonempty_cli.runner(cli._object_input, cli.run),
        )
    if isinstance(result, Mapping) and type(result.get("exit_code")) is int:
        exit_code = int(result["exit_code"])
        public = cli._safe_stdout_result(result)
    elif isinstance(result, Mapping) and result.get("ok") is False:
        exit_code = envelope_exit_code(result)
        public = result
    else:
        exit_code = 0
        public = cli._safe_stdout_result(result)
    encoded = json_output.dumps(
        cli._sanitize_credentials(public),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return json.loads(encoded), exit_code


def _plan(
    operation: OperationSpec,
    inputs: Mapping[str, Any],
    sdk: GravitySDK,
) -> dict[str, Any]:
    max_pages, max_items = _limits(operation)
    return sdk.execute_plan(
        {
            "schema_version": "gravity.plan.v1",
            "nodes": [
                {
                    "id": "surface-parity-sample",
                    "kind": "run",
                    "request": {
                        "selector": operation.operation_id,
                        "inputs": copy.deepcopy(dict(inputs)),
                    },
                    "limits": {
                        "max_pages": max_pages,
                        "max_items": max_items,
                    },
                }
            ],
        },
        max_workers=1,
    )


def _mcp_call(server: MCPServer, operation: OperationSpec) -> dict[str, Any]:
    value = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "gravity.execute",
                "arguments": {
                    "journey_id": operation.operation_id,
                    "inputs": sample_inputs(operation),
                },
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                    "io.modelcontextprotocol/clientCapabilities": {},
                    "io.modelcontextprotocol/clientInfo": {
                        "name": "surface-parity-gate",
                        "version": "1",
                    },
                },
            },
        }
    )
    if not isinstance(value, Mapping):
        raise RuntimeError("MCP surface returned no response")
    return copy.deepcopy(dict(value))


def _semantic_contract(schema: Mapping[str, Any], effect: str) -> dict[str, Any]:
    return {
        "operation_id": schema.get("operation_id"),
        "contract_version": schema.get("contract_version"),
        "effect": effect,
        "input_fields": copy.deepcopy(
            schema.get("input_fields", schema.get("input_schema"))
        ),
        "response_projection": copy.deepcopy(schema.get("response_projection")),
        "pagination": copy.deepcopy(schema.get("pagination")),
        "privacy_classification": (
            schema.get("privacy", {}).get("classification")
            if isinstance(schema.get("privacy"), Mapping)
            else None
        ),
    }


def _read_sample(
    operation: OperationSpec,
    client: Any,
) -> dict[str, Any]:
    max_pages, max_items = _limits(operation)
    return client.read_limited(
        operation.operation_id,
        sample_inputs(operation),
        max_pages=max_pages,
        max_items=max_items,
        max_workers=1,
    )


def _cli_read_sample(
    parser: Any,
    operation: OperationSpec,
    client: GravityInsightClient,
) -> tuple[dict[str, Any], int]:
    max_pages, max_items = _limits(operation)
    value, exit_code = _cli_observation(
        parser,
        [
            "read",
            operation.operation_id,
            "--input",
            json.dumps(sample_inputs(operation), separators=(",", ":")),
            "--max-pages",
            str(max_pages),
            "--max-items",
            str(max_items),
            "--concurrency",
            "1",
        ],
        client,
    )
    if not isinstance(value, dict):
        raise RuntimeError("CLI read did not return an object envelope")
    return value, exit_code


def _operation_row(
    operation: OperationSpec,
    parser: Any,
    clients: Mapping[str, GravityInsightClient],
    sdks: Mapping[str, GravitySDK],
    mcp: MCPServer,
) -> dict[str, Any]:
    source = operation.schema()
    cli_schema, schema_exit = _cli_observation(
        parser,
        ["operations", "schema", operation.operation_id],
        clients["cli_empty"],
    )
    direct_empty = _read_sample(operation, clients["direct_empty"])
    cli_empty, cli_empty_exit = _cli_read_sample(
        parser, operation, clients["cli_empty"]
    )
    sdk_empty = _read_sample(operation, sdks["sdk_empty"])
    plan_empty = _plan(operation, sample_inputs(operation), sdks["plan_empty"])
    direct_error = _read_sample(operation, clients["direct_error"])
    cli_error, cli_error_exit = _cli_read_sample(
        parser, operation, clients["cli_error"]
    )
    sdk_error = _read_sample(operation, sdks["sdk_error"])
    plan_error = _plan(operation, sample_inputs(operation), sdks["plan_error"])
    described = clients["plan_empty"].describe(operation.operation_id)
    row = {
        "row_id": f"operation:{operation.operation_id}",
        "row_kind": "operation",
        "operation_id": operation.operation_id,
        "effect": operation.effect,
        "source_contract": source,
        "input_sample": sample_inputs(operation),
        "cells": {
            "direct_sdk": {
                "availability": "available",
                "published_contract": clients["direct_empty"].schema(
                    operation.operation_id
                ),
                "semantic_contract": _semantic_contract(source, operation.effect),
                "samples": {"empty": direct_empty, "upstream_error": direct_error},
            },
            "cli": {
                "availability": "available",
                "published_contract": cli_schema,
                "semantic_contract": _semantic_contract(cli_schema, operation.effect),
                "schema_exit_code": schema_exit,
                "samples": {"empty": cli_empty, "upstream_error": cli_error},
                "sample_exit_codes": {
                    "empty": cli_empty_exit,
                    "upstream_error": cli_error_exit,
                },
            },
            "sdk_wrapper": {
                "availability": "available",
                "published_contract": clients["sdk_empty"].schema(
                    operation.operation_id
                ),
                "semantic_contract": _semantic_contract(source, operation.effect),
                "samples": {"empty": sdk_empty, "upstream_error": sdk_error},
            },
            "plan": {
                "availability": "available",
                "published_contract": described,
                "semantic_contract": _semantic_contract(
                    described, operation.effect
                ),
                "samples": {"empty": plan_empty, "upstream_error": plan_error},
            },
            "mcp": {
                "availability": "unsupported",
                "published_contract": next(
                    item
                    for item in tool_catalog()["tools"]
                    if item["name"] == "gravity.execute"
                ),
                "semantic_contract": {
                    "accepted_identity": "journey_id",
                    "raw_operation_accepted": False,
                },
                "samples": {"unsupported": _mcp_call(mcp, operation)},
            },
        },
    }
    return row


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return type(value).__name__


def _pointer(path: str, token: object) -> str:
    encoded = str(token).replace("~", "~0").replace("/", "~1")
    return f"{path}/{encoded}" if path else f"/{encoded}"


def json_differences(reference: Any, candidate: Any, path: str = "") -> list[dict[str, Any]]:
    reference_type, candidate_type = _json_type(reference), _json_type(candidate)
    if reference_type != candidate_type:
        return [{"kind": "type", "path": path or "/", "expected": reference_type, "actual": candidate_type}]
    if isinstance(reference, Mapping):
        differences: list[dict[str, Any]] = []
        for key in sorted(set(reference) - set(candidate)):
            differences.append({"kind": "missing", "path": _pointer(path, key), "expected": _json_type(reference[key]), "actual": "absent"})
        for key in sorted(set(candidate) - set(reference)):
            differences.append({"kind": "extra", "path": _pointer(path, key), "expected": "absent", "actual": _json_type(candidate[key])})
        for key in sorted(set(reference) & set(candidate)):
            differences.extend(json_differences(reference[key], candidate[key], _pointer(path, key)))
        return differences
    if isinstance(reference, list):
        differences = []
        if len(reference) != len(candidate):
            differences.append({"kind": "length", "path": path or "/", "expected": len(reference), "actual": len(candidate)})
        for index, (left, right) in enumerate(zip(reference, candidate)):
            differences.extend(json_differences(left, right, _pointer(path, index)))
        return differences
    if reference != candidate:
        return [{"kind": "value", "path": path or "/", "expected": reference, "actual": candidate}]
    return []


def _normalized(value: Any) -> Any:
    selected = copy.deepcopy(value)
    if isinstance(selected, dict) and "fetched_at" in selected:
        selected["fetched_at"] = {"json_type": _json_type(selected["fetched_at"])}
    return selected


def _allowance(
    allowances: Sequence[Mapping[str, Any]],
    *,
    surface: str,
    outcome: str,
    kind: str,
    path: str,
) -> Mapping[str, Any] | None:
    return next(
        (
            item
            for item in allowances
            if item.get("row_kind") == "operation"
            and item.get("surface") == surface
            and item.get("outcome") == outcome
            and item.get("difference_kind") == kind
            and item.get("path") == path
        ),
        None,
    )


def _severity(kind: str, path: str) -> str:
    if "completeness" in path or "/error" in path or kind == "availability":
        return "critical"
    if kind in {"missing", "type", "value", "wrapper"}:
        return "high"
    return "medium"


def _finding(
    row: Mapping[str, Any], surface: str, outcome: str, difference: Mapping[str, Any]
) -> dict[str, Any]:
    path = str(difference["path"])
    kind = str(difference["kind"])
    difference_digest = canonical_digest(
        {
            "kind": kind,
            "path": path,
            "expected": difference.get("expected"),
            "actual": difference.get("actual"),
        }
    )
    finding_id = ":".join(
        (
            str(row["row_id"]),
            surface,
            outcome,
            kind,
            path.replace("/", "~"),
            difference_digest[:12],
        )
    )
    expected = difference.get("expected")
    actual = difference.get("actual")
    type_names = {
        "absent",
        "array",
        "boolean",
        "integer",
        "null",
        "number",
        "object",
        "string",
    }
    return {
        "finding_id": finding_id,
        "severity": _severity(kind, path),
        "row_id": row["row_id"],
        "surface": surface,
        "outcome": outcome,
        "difference_kind": kind,
        "difference_digest": difference_digest,
        "path": path,
        "expected_type": str(expected) if expected in type_names else _json_type(expected),
        "actual_type": str(actual) if actual in type_names else _json_type(actual),
    }


def _compare(
    row: Mapping[str, Any],
    surface: str,
    outcome: str,
    reference: Any,
    candidate: Any,
    allowances: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings, applications = [], []
    for difference in json_differences(_normalized(reference), _normalized(candidate)):
        rule = _allowance(
            allowances,
            surface=surface,
            outcome=outcome,
            kind=str(difference["kind"]),
            path=str(difference["path"]),
        )
        if rule is None:
            findings.append(_finding(row, surface, outcome, difference))
        else:
            applications.append(
                {
                    "allowance_id": rule["allowance_id"],
                    "row_id": row["row_id"],
                    "surface": surface,
                    "outcome": outcome,
                    "path": difference["path"],
                }
            )
    return findings, applications


def _required_allowance(
    row: Mapping[str, Any],
    allowances: Sequence[Mapping[str, Any]],
    surface: str,
    outcome: str,
    kind: str,
    path: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rule = _allowance(
        allowances,
        surface=surface,
        outcome=outcome,
        kind=kind,
        path=path,
    )
    difference = {"kind": kind, "path": path, "expected": "registered", "actual": "unregistered"}
    if rule is None:
        return [_finding(row, surface, outcome, difference)], []
    return [], [{"allowance_id": rule["allowance_id"], "row_id": row["row_id"], "surface": surface, "outcome": outcome, "path": path}]


def _plan_node(sample: Mapping[str, Any]) -> Mapping[str, Any] | None:
    results = sample.get("results")
    if not isinstance(results, list) or len(results) != 1:
        return None
    return results[0] if isinstance(results[0], Mapping) else None


def _walker_finding(
    row: Mapping[str, Any], surface: str, outcome: str, sample: Mapping[str, Any], expected: str
) -> dict[str, Any] | None:
    try:
        observed = aggregate_completeness(sample)
    except Exception:
        return _finding(row, surface, outcome, {"kind": "type", "path": "/completeness", "expected": "walkable", "actual": "exception"})
    if observed != expected:
        return _finding(row, surface, outcome, {"kind": "value", "path": "/completeness", "expected": expected, "actual": observed})
    return None


def _cli_audit_finding(
    row: Mapping[str, Any], outcome: str, sample: Mapping[str, Any], expected: str
) -> dict[str, Any] | None:
    audit = sample.get("pagination_audit")
    completeness = audit.get("completeness") if isinstance(audit, Mapping) else None
    if not isinstance(completeness, Mapping):
        return _finding(
            row,
            "cli",
            outcome,
            {
                "kind": "type",
                "path": "/pagination_audit/completeness",
                "expected": "object",
                "actual": _json_type(completeness),
            },
        )
    observed = completeness.get("status")
    if observed != expected:
        return _finding(
            row,
            "cli",
            outcome,
            {
                "kind": "value",
                "path": "/pagination_audit/completeness/status",
                "expected": expected,
                "actual": observed,
            },
        )
    return None


def analyze_operation_row(
    row: Mapping[str, Any], allowances: Sequence[Mapping[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    cells = row["cells"]
    findings: list[dict[str, Any]] = []
    applications: list[dict[str, Any]] = []
    source = row["source_contract"]
    for surface in ("direct_sdk", "cli", "sdk_wrapper"):
        selected, applied = _compare(
            row, surface, "contract", source, cells[surface]["published_contract"], allowances
        )
        findings.extend(selected)
        applications.extend(applied)
    selected, applied = _compare(
        row,
        "plan",
        "contract",
        cells["direct_sdk"]["semantic_contract"],
        cells["plan"]["semantic_contract"],
        allowances,
    )
    findings.extend(selected)
    applications.extend(applied)
    for outcome in ("empty", "upstream_error"):
        reference = cells["direct_sdk"]["samples"][outcome]
        for surface in ("cli", "sdk_wrapper"):
            selected, applied = _compare(
                row, surface, outcome, reference, cells[surface]["samples"][outcome], allowances
            )
            findings.extend(selected)
            applications.extend(applied)
        kind = "wrapper"
        path = "/results/0/result" if outcome == "empty" else "/results/0/error"
        selected, applied = _required_allowance(row, allowances, "plan", outcome, kind, path)
        findings.extend(selected)
        applications.extend(applied)
        node = _plan_node(cells["plan"]["samples"][outcome])
        if node is None:
            findings.append(_finding(row, "plan", outcome, {"kind": "missing", "path": "/results/0", "expected": "object", "actual": "absent"}))
        elif outcome == "empty":
            selected, applied = _compare(row, "plan", outcome, reference, node.get("result"), allowances)
            findings.extend(selected)
            applications.extend(applied)
        else:
            selected, applied = _compare(row, "plan", outcome, reference.get("error"), node.get("error"), allowances)
            findings.extend(selected)
            applications.extend(applied)
        expected_completeness = aggregate_completeness(reference)
        audit_finding = _cli_audit_finding(
            row,
            outcome,
            cells["cli"]["samples"][outcome],
            expected_completeness,
        )
        if audit_finding is not None:
            findings.append(audit_finding)
        expected_exit = (
            0
            if outcome == "empty"
            else exit_code_for_category(reference["error"]["category"])
        )
        if cells["cli"]["sample_exit_codes"][outcome] != expected_exit:
            findings.append(
                _finding(
                    row,
                    "cli",
                    outcome,
                    {
                        "kind": "value",
                        "path": "/process_exit_code",
                        "expected": expected_exit,
                        "actual": cells["cli"]["sample_exit_codes"][outcome],
                    },
                )
            )
        if node is not None and node.get("exit_code") != expected_exit:
            findings.append(
                _finding(
                    row,
                    "plan",
                    outcome,
                    {
                        "kind": "value",
                        "path": "/results/0/exit_code",
                        "expected": expected_exit,
                        "actual": node.get("exit_code"),
                    },
                )
            )
        for surface in ("direct_sdk", "cli", "sdk_wrapper", "plan"):
            sample = cells[surface]["samples"][outcome]
            finding = _walker_finding(row, surface, outcome, sample, expected_completeness)
            if finding is not None:
                findings.append(finding)
    selected, applied = _required_allowance(
        row, allowances, "mcp", "availability", "unsupported", "/"
    )
    findings.extend(selected)
    applications.extend(applied)
    mcp_sample = cells["mcp"]["samples"]["unsupported"]
    structured = mcp_sample.get("result", {}).get("structuredContent", {})
    domain = structured.get("result", {}) if isinstance(structured, Mapping) else {}
    error = domain.get("error", {}) if isinstance(domain, Mapping) else {}
    if (
        structured.get("ok") is not False
        or error.get("category") != "caller"
        or error.get("code") != "INPUT_INVALID"
        or error.get("field") != "journey_id"
    ):
        findings.append(_finding(row, "mcp", "availability", {"kind": "availability", "path": "/", "expected": "raw_operation_unsupported", "actual": "changed"}))
    return findings, applications


def build_surface_matrix(
    *, baseline: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    baseline = load_baseline() if baseline is None else dict(baseline)
    allowances = baseline["allowances"]
    registry = load_operation_registry()
    operations = stable_read_operations(registry)
    parser = cli.build_parser()
    with tempfile.TemporaryDirectory(prefix="gravity-surface-parity-") as raw:
        workspace = load_workspace(start=raw, environ={}, cache_root=raw)
        clients = {
            f"{surface}_{outcome}": _client(
                registry,
                _EmptyTransport() if outcome == "empty" else _UpstreamFailureTransport(),
            )
            for surface in ("direct", "cli", "sdk", "plan")
            for outcome in ("empty", "error")
        }
        sdks = {
            "sdk_empty": GravitySDK(insight=clients["sdk_empty"], workspace=workspace),
            "sdk_error": GravitySDK(insight=clients["sdk_error"], workspace=workspace),
            "plan_empty": GravitySDK(insight=clients["plan_empty"], workspace=workspace),
            "plan_error": GravitySDK(insight=clients["plan_error"], workspace=workspace),
        }
        mcp = MCPServer(GravitySDK(workspace=workspace))
        with patch("gravity_insight.client.datetime", _FixedDateTime):
            rows = [
                _operation_row(operation, parser, clients, sdks, mcp)
                for operation in operations
            ]
    findings, applications = [], []
    for row in rows:
        selected, applied = analyze_operation_row(row, allowances)
        row["findings"] = selected
        row["legal_differences"] = applied
        findings.extend(selected)
        applications.extend(applied)
    stable = tuple(item for item in registry.all() if item.stability == "stable")
    excluded_ids = {
        operation.operation_id for operation in stable_excluded_operations(registry)
    }
    registered_exclusions = {
        str(item["operation_id"])
        for item in baseline.get("excluded_operations", [])
    }
    matrix = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "registry": {
            "source": "compiled OperationSpec registry",
            "operation_count": len(registry.all()),
            "stable_operation_count": len(stable),
            "stable_read_operation_count": len(operations),
            "stable_non_read_operation_count": len(stable) - len(operations),
            "contract_digest": canonical_digest(
                [operation.schema() for operation in operations]
            ),
        },
        "surfaces": list(SURFACES),
        "probe": {
            "network_called": False,
            "field_policy": "operation contract only; no live metadata values",
            "empty_outcome": "actual public adapters over a synthetic HTTP 204",
            "upstream_error_outcome": "actual public adapters over UpstreamError",
            "sample_shape": "complete surface output; no reduced envelope fixtures",
        },
        "row_count": len(rows),
        "rows": rows,
        "scope_exclusions": {
            "policy": "stable executable non-read operations require action-specific parity and an exact registered exclusion from generic read parity",
            "observed_count": len(excluded_ids),
            "registered_count": len(registered_exclusions),
            "unregistered_operation_ids": sorted(excluded_ids - registered_exclusions),
            "stale_operation_ids": sorted(registered_exclusions - excluded_ids),
        },
        "allowance_application_count": len(applications),
        "findings": sorted(findings, key=lambda item: item["finding_id"]),
        "severity_counts": {
            severity: sum(item["severity"] == severity for item in findings)
            for severity in ("critical", "high", "medium")
        },
    }
    matrix["matrix_digest"] = canonical_digest(matrix)
    validate_schema(matrix, "surface-parity-matrix-v1.schema.json", "surface parity matrix")
    return matrix


def load_baseline(path: Path | None = None) -> dict[str, Any]:
    selected = ROOT / BASELINE_PATH if path is None else path
    baseline = load_json_object(selected, "surface parity baseline")
    validate_schema(
        baseline,
        "surface-parity-baseline-v1.schema.json",
        "surface parity baseline",
    )
    return baseline


def gate_errors(matrix: Mapping[str, Any], baseline: Mapping[str, Any]) -> list[str]:
    allowed = {
        str(item["finding_id"]): item
        for item in baseline.get("allowed_findings", [])
    }
    errors = []
    for finding in matrix.get("findings", []):
        finding_id = str(finding["finding_id"])
        registered = allowed.get(finding_id)
        if registered is None:
            errors.append(f"new surface parity finding: {finding_id}")
        elif registered.get("severity") != finding.get("severity"):
            errors.append(f"surface parity severity drifted: {finding_id}")
        elif registered.get("difference_digest") != finding.get("difference_digest"):
            errors.append(f"surface parity difference drifted: {finding_id}")
    exclusions = matrix.get("scope_exclusions", {})
    for operation_id in exclusions.get("unregistered_operation_ids", []):
        errors.append(
            "stable non-read operation lacks an exact surface parity exclusion: "
            + str(operation_id)
        )
    return errors


def compare_baselines(current: Mapping[str, Any], base: Mapping[str, Any]) -> list[str]:
    current_findings = {
        str(item["finding_id"]): item for item in current.get("allowed_findings", [])
    }
    base_findings = {
        str(item["finding_id"]): item for item in base.get("allowed_findings", [])
    }
    added = sorted(set(current_findings) - set(base_findings))
    errors = [f"surface parity baseline may only decrease; added {item}" for item in added]
    for finding_id in sorted(set(current_findings) & set(base_findings)):
        if current_findings[finding_id] != base_findings[finding_id]:
            errors.append(f"surface parity baseline entry changed: {finding_id}")
    current_exclusions = {
        str(item["operation_id"]): item
        for item in current.get("excluded_operations", [])
    }
    base_exclusions = {
        str(item["operation_id"]): item
        for item in base.get("excluded_operations", [])
    }
    for operation_id in sorted(set(current_exclusions) - set(base_exclusions)):
        errors.append(
            "surface parity exclusions may only decrease; added " + operation_id
        )
    for operation_id in sorted(set(current_exclusions) & set(base_exclusions)):
        if current_exclusions[operation_id] != base_exclusions[operation_id]:
            errors.append(
                "surface parity exclusion changed: " + operation_id
            )
    return errors


def _baseline_at_ref(ref: str) -> dict[str, Any] | None:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{ref}:{BASELINE_PATH.as_posix()}"],
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        return None
    value = json.loads(completed.stdout.decode("utf-8"))
    return value if isinstance(value, dict) else None


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, default=ROOT / BASELINE_PATH)
    parser.add_argument("--base-ref")
    parser.add_argument("--matrix-out", type=Path)
    args = parser.parse_args(argv)
    baseline = load_baseline(args.baseline)
    matrix = build_surface_matrix(baseline=baseline)
    errors = gate_errors(matrix, baseline)
    if args.base_ref:
        base = _baseline_at_ref(args.base_ref)
        if base is not None:
            errors.extend(compare_baselines(baseline, base))
    if args.matrix_out:
        output = args.matrix_out if args.matrix_out.is_absolute() else ROOT / args.matrix_out
        _write_json(output, matrix)
    summary = {
        "schema_version": MATRIX_SCHEMA_VERSION,
        "status": "failed" if errors else "passed",
        "row_count": matrix["row_count"],
        "surface_count": len(matrix["surfaces"]),
        "allowance_application_count": matrix["allowance_application_count"],
        "finding_count": len(matrix["findings"]),
        "scope_exclusion_count": matrix["scope_exclusions"]["observed_count"],
        "severity_counts": matrix["severity_counts"],
        "matrix_digest": matrix["matrix_digest"],
        "errors": errors,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
