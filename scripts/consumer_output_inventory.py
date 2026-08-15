"""Render the conservative LLM-consumer boundary from checked-in contracts.

This command is offline.  It inventories every compiled stable operation, every
declared response-projection path, the authoritative analysis-journey table, and
versioned envelope identifiers found in runtime source.  It deliberately treats
whole content zones as untrusted instead of guessing whether a field name is
human-controlled.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_ROOT = ROOT / "src" / "gravity_sdk" / "manifests"
SOURCE_ROOT = ROOT / "src" / "gravity_sdk"
JOURNEYS = ROOT / "docs" / "analysis-journeys.md"
SCHEMA_VERSION_RE = re.compile(r"^gravity(?:-insight|-sql|\.)[a-z0-9_.-]*\.v[0-9]+$")


BOUNDARY_PATTERNS = {
    "untrusted_content_roots": [
        "request.inputs",
        "data",
        "result",
        "results",
        "components",
        "charts",
        "windows",
        "items",
        "candidates",
        "catalogs[].items",
        "dashboard",
        "segment",
        "template",
        "saved_analysis",
        "jobs",
        "query",
        "goal",
    ],
    "advisory_text_not_instruction": [
        "warnings[]",
        "error.message",
        "error.next_action",
        "next_action",
        "description",
        "reason",
        "diagnostics",
    ],
    "machine_control_fields": [
        "schema_version",
        "ok",
        "status",
        "operation_id",
        "contract_version",
        "error.code",
        "error.category",
        "error.retryable",
        "error.retry_after_ms",
        "exit_code",
        "schema_fingerprint",
        "contract_fingerprint",
    ],
}


def _add(
    rows: dict[str, dict[str, Any]], path: str, kind: str, *, potential_text: bool = True
) -> None:
    rows[path] = {
        "path": path,
        "contract_kind": kind,
        "potential_text": potential_text,
    }


def _projection_paths(operation: Mapping[str, Any]) -> list[dict[str, Any]]:
    projection = operation.get("response_projection", {})
    pagination = operation.get("pagination", {})
    list_path = pagination.get("list_path") or (
        "data" if projection.get("data_shape") == "list" else "data.list"
    )
    rows: dict[str, dict[str, Any]] = {}
    for key in projection.get("data_keys", []):
        _add(rows, f"data.{key}", "declared_data_value")
    for key in projection.get("item_keys", []):
        _add(rows, f"{list_path}[].{key}", "declared_row_value")
    for field in projection.get("dynamic_item_fields", []):
        _add(rows, f"{list_path}[].<input:{field}>", "caller_selected_dynamic_value")
    for field in projection.get("numeric_suffix_item_fields", []):
        _add(rows, f"{list_path}[].<numeric-suffix:{field}>", "dynamic_scalar_value")
    for parent, keys in projection.get("nested_item_keys", {}).items():
        for key in keys:
            _add(rows, f"{list_path}[].{parent}.{key}", "declared_nested_value")
    for parent, keys in projection.get("data_item_keys", {}).items():
        for key in keys:
            _add(rows, f"data.{parent}.{key}", "declared_data_item_value")
    for parent, item_type in projection.get("scalar_list_item_types", {}).items():
        _add(
            rows,
            f"{list_path}[].{parent}[]",
            f"typed_{item_type}_list_value",
            potential_text=item_type == "string",
        )
    for parent, item_type in projection.get("data_scalar_list_types", {}).items():
        _add(
            rows,
            f"data.{parent}[]",
            f"typed_{item_type}_list_value",
            potential_text=item_type == "string",
        )
    for parent, keys in projection.get("data_path_item_keys", {}).items():
        for key in keys:
            _add(rows, f"data.{parent}[].{key}", "declared_nested_collection_value")
    for parent, fields in projection.get("data_dynamic_item_fields", {}).items():
        for field in fields:
            _add(rows, f"data.{parent}[].<input:{field}>", "caller_selected_dynamic_value")
    for parent, fields in projection.get("data_numeric_suffix_item_fields", {}).items():
        for field in fields:
            _add(rows, f"data.{parent}[].<numeric-suffix:{field}>", "dynamic_scalar_value")
    for parent, keys in projection.get("recursive_data_item_keys", {}).items():
        for key in keys:
            _add(rows, f"data.{parent}..{key}", "declared_recursive_value")
    for key in projection.get("opaque_json_item_keys", []):
        _add(rows, f"{list_path}[].{key}..*", "opaque_json_value")
    for path in projection.get("numeric_paths", []):
        normalized = path if path.startswith("data") else f"data.{path}"
        _add(rows, normalized, "numeric_value", potential_text=False)
    return sorted(rows.values(), key=lambda item: item["path"])


def _operations() -> list[dict[str, Any]]:
    result = []
    for manifest in sorted(MANIFEST_ROOT.glob("*.json")):
        document = json.loads(manifest.read_text(encoding="utf-8"))
        for operation in document["operations"]:
            if operation.get("stability") != "stable":
                continue
            paths = _projection_paths(operation)
            result.append(
                {
                    "operation_id": operation["operation_id"],
                    "manifest": manifest.name,
                    "privacy_classification": operation["privacy_policy"]["classification"],
                    "untrusted_envelope_roots": ["request.inputs", "data"],
                    "projection_paths": paths,
                    "potential_text_paths": [
                        item["path"] for item in paths if item["potential_text"]
                    ],
                    "dynamic_or_opaque_paths": [
                        item["path"]
                        for item in paths
                        if "dynamic" in item["contract_kind"]
                        or item["contract_kind"] == "opaque_json_value"
                    ],
                }
            )
    return sorted(result, key=lambda item: item["operation_id"])


def _journeys() -> list[dict[str, Any]]:
    result = []
    for line in JOURNEYS.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith(("| ---", "| 动线")):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        result.append(
            {
                "product": cells[0],
                "status": cells[1],
                "counted": not cells[1].startswith("不计独立动线"),
                "can_return_business_content": cells[1] == "已闭环",
            }
        )
    return result


def _schema_versions() -> list[dict[str, str]]:
    result = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        values = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and SCHEMA_VERSION_RE.fullmatch(node.value)
        }
        for value in sorted(values):
            result.append(
                {"schema_version": value, "source": path.relative_to(ROOT).as_posix()}
            )
    return result


def inventory() -> dict[str, Any]:
    operations = _operations()
    journeys = _journeys()
    schemas = _schema_versions()
    return {
        "schema_version": "gravity.consumer-output-inventory.v1",
        "method": {
            "operations": "all compiled stable manifests",
            "products": "every row in docs/analysis-journeys.md; counted=false preserves compatibility rows",
            "text_boundary": (
                "potential_text is a conservative contract upper bound; current contracts "
                "do not prove human authorship or scalar types for every path"
            ),
            "network_called": False,
        },
        "boundary_patterns": BOUNDARY_PATTERNS,
        "counts": {
            "stable_operations": len(operations),
            "stable_operations_with_potential_text": sum(
                bool(item["potential_text_paths"]) for item in operations
            ),
            "stable_operations_with_dynamic_or_opaque_content": sum(
                bool(item["dynamic_or_opaque_paths"]) for item in operations
            ),
            "product_rows": len(journeys),
            "counted_products": sum(item["counted"] for item in journeys),
            "closed_products": sum(
                item["counted"] and item["status"] == "已闭环" for item in journeys
            ),
            "missing_products": sum(
                item["counted"] and item["status"] == "完全缺失" for item in journeys
            ),
            "versioned_envelope_literals": len(schemas),
        },
        "operations": operations,
        "products": journeys,
        "versioned_envelopes": schemas,
    }


def main() -> None:
    print(
        json.dumps(
            inventory(), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
        )
    )


if __name__ == "__main__":
    main()
