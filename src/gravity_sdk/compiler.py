"""Build deterministic Gravity Insight runtime manifests from JSON contracts."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from gravity_sdk.models import (
    ManifestError,
    OperationSpec,
    load_operation_manifest,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT_ROOT = Path(__file__).resolve().parent / "contracts"
DEFAULT_MANIFEST_ROOT = Path(__file__).resolve().parent / "manifests"
OPERATION_SCHEMA_REF = "../schema/operation-v2.schema.json"
FAMILY_SCHEMA_REF = "../schema/family-v1.schema.json"
_TARGET_RE = re.compile(r"^[a-z][a-z0-9_]*\.json$")
_BINDING_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ContractError(ValueError):
    """A source contract or compiler invariant is invalid."""


class ContractDriftError(ContractError):
    """Compiled products do not match their contract sources."""


@dataclass(frozen=True)
class CompiledOperation:
    target_manifest: str
    manifest_order: int
    runtime: Mapping[str, Any]
    spec: OperationSpec
    provenance: Mapping[str, Any]


@dataclass(frozen=True)
class CompilationResult:
    manifests: Mapping[str, bytes]
    provenance: bytes
    operation_count: int


class JsonSchemaValidator:
    """Small Draft 2020-12 subset used by the two checked-in schemas.

    Keeping this validator local avoids adding a build-only package to the
    runtime dependency set. Unsupported schema keywords fail closed.
    """

    _SUPPORTED = frozenset(
        {
            "$schema",
            "$id",
            "$ref",
            "$defs",
            "title",
            "description",
            "readOnly",
            "type",
            "const",
            "enum",
            "required",
            "properties",
            "additionalProperties",
            "items",
            "minItems",
            "maxItems",
            "uniqueItems",
            "minProperties",
            "pattern",
            "minLength",
            "maxLength",
            "minimum",
            "maximum",
            "allOf",
            "anyOf",
            "oneOf",
            "not",
        }
    )

    def __init__(self, schema: Mapping[str, Any], label: str) -> None:
        self.schema = schema
        self.label = label
        self._check_keywords(schema, "#")

    def validate(self, value: Any) -> None:
        self._validate(value, self.schema, "$")

    def fragment(self, reference: str) -> Mapping[str, Any]:
        return self._resolve(reference)

    def _check_keywords(self, schema: Any, path: str) -> None:
        if isinstance(schema, bool):
            return
        if not isinstance(schema, Mapping):
            raise ContractError(f"{self.label}: schema node {path} must be an object")
        unknown = set(schema) - self._SUPPORTED
        if unknown:
            raise ContractError(
                f"{self.label}: unsupported schema keywords at {path}: "
                + ", ".join(sorted(unknown))
            )
        for key in ("$defs", "properties"):
            for name, child in schema.get(key, {}).items():
                self._check_keywords(child, f"{path}/{key}/{name}")
        additional = schema.get("additionalProperties")
        if isinstance(additional, Mapping):
            self._check_keywords(additional, f"{path}/additionalProperties")
        items = schema.get("items")
        if isinstance(items, Mapping):
            self._check_keywords(items, f"{path}/items")
        for key in ("allOf", "anyOf", "oneOf"):
            for index, child in enumerate(schema.get(key, ())):
                self._check_keywords(child, f"{path}/{key}/{index}")
        if isinstance(schema.get("not"), Mapping):
            self._check_keywords(schema["not"], f"{path}/not")

    def _resolve(self, reference: str) -> Mapping[str, Any]:
        if not reference.startswith("#/"):
            raise ContractError(f"{self.label}: only local schema references are supported")
        node: Any = self.schema
        for token in reference[2:].split("/"):
            token = token.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, Mapping) or token not in node:
                raise ContractError(f"{self.label}: unresolved schema reference {reference}")
            node = node[token]
        if not isinstance(node, Mapping):
            raise ContractError(f"{self.label}: schema reference {reference} is not an object")
        return node

    def _validate(self, value: Any, schema: Any, path: str) -> None:
        if schema is False:
            raise ContractError(f"{self.label}: {path} is not allowed")
        if schema is True:
            return
        if "$ref" in schema:
            self._validate(value, self._resolve(schema["$ref"]), path)
        for child in schema.get("allOf", ()):
            self._validate(value, child, path)
        if "anyOf" in schema:
            if not any(self._matches(value, child, path) for child in schema["anyOf"]):
                raise ContractError(f"{self.label}: {path} does not match any allowed shape")
        if "oneOf" in schema:
            matches = sum(self._matches(value, child, path) for child in schema["oneOf"])
            if matches != 1:
                raise ContractError(f"{self.label}: {path} must match exactly one allowed shape")
        if "not" in schema and self._matches(value, schema["not"], path):
            raise ContractError(f"{self.label}: {path} matches a forbidden shape")
        if "const" in schema and value != schema["const"]:
            raise ContractError(f"{self.label}: {path} must equal {schema['const']!r}")
        if "enum" in schema and value not in schema["enum"]:
            raise ContractError(f"{self.label}: {path} is outside its enum")
        if "type" in schema and not self._matches_type(value, schema["type"]):
            raise ContractError(f"{self.label}: {path} has the wrong JSON type")

        if isinstance(value, Mapping):
            required = schema.get("required", ())
            missing = [name for name in required if name not in value]
            if missing:
                raise ContractError(
                    f"{self.label}: {path} is missing required fields: "
                    + ", ".join(missing)
                )
            minimum = schema.get("minProperties")
            if minimum is not None and len(value) < minimum:
                raise ContractError(f"{self.label}: {path} has too few properties")
            properties = schema.get("properties", {})
            additional = schema.get("additionalProperties", True)
            for name, item in value.items():
                child_path = f"{path}.{name}"
                if name in properties:
                    self._validate(item, properties[name], child_path)
                elif additional is False:
                    raise ContractError(f"{self.label}: {child_path} is not declared")
                elif isinstance(additional, Mapping):
                    self._validate(item, additional, child_path)

        if isinstance(value, list):
            if len(value) < schema.get("minItems", 0):
                raise ContractError(f"{self.label}: {path} has too few items")
            maximum = schema.get("maxItems")
            if maximum is not None and len(value) > maximum:
                raise ContractError(f"{self.label}: {path} has too many items")
            if schema.get("uniqueItems"):
                encoded = [_canonical_text(item) for item in value]
                if len(encoded) != len(set(encoded)):
                    raise ContractError(f"{self.label}: {path} must contain unique items")
            if "items" in schema:
                for index, item in enumerate(value):
                    self._validate(item, schema["items"], f"{path}[{index}]")

        if isinstance(value, str):
            if len(value) < schema.get("minLength", 0):
                raise ContractError(f"{self.label}: {path} is too short")
            maximum = schema.get("maxLength")
            if maximum is not None and len(value) > maximum:
                raise ContractError(f"{self.label}: {path} is too long")
            pattern = schema.get("pattern")
            if pattern is not None and re.fullmatch(pattern, value) is None:
                raise ContractError(f"{self.label}: {path} does not match {pattern!r}")

        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in schema and value < schema["minimum"]:
                raise ContractError(f"{self.label}: {path} is below its minimum")
            if "maximum" in schema and value > schema["maximum"]:
                raise ContractError(f"{self.label}: {path} exceeds its maximum")

    def _matches(self, value: Any, schema: Any, path: str) -> bool:
        try:
            self._validate(value, schema, path)
        except ContractError:
            return False
        return True

    @staticmethod
    def _matches_type(value: Any, expected: Any) -> bool:
        choices = expected if isinstance(expected, list) else [expected]
        checks = {
            "null": value is None,
            "object": isinstance(value, Mapping),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "boolean": isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        }
        return any(checks.get(choice, False) for choice in choices)


class ContractCompiler:
    def __init__(
        self,
        contract_root: Path | str = DEFAULT_CONTRACT_ROOT,
        manifest_root: Path | str = DEFAULT_MANIFEST_ROOT,
    ) -> None:
        self.contract_root = Path(contract_root)
        self.manifest_root = Path(manifest_root)
        self.provenance_path = self.contract_root / "generated" / "provenance.json"
        self.operation_schema = self._load_validator(
            self.contract_root / "schema" / "operation-v2.schema.json"
        )
        self.family_schema = self._load_validator(
            self.contract_root / "schema" / "family-v1.schema.json"
        )

    def lint(self) -> CompilationResult:
        operations = self._load_operations()
        self._semantic_lint(operations)
        return self._render(operations)

    def compile(self, *, check: bool = False) -> CompilationResult:
        result = self.lint()
        if check:
            self._check_result(result)
        else:
            self._write_result(result)
        return result

    def check(self) -> CompilationResult:
        return self.compile(check=True)

    def migrate_manifests(self) -> int:
        """One-time v1 manifest to flat v2 source conversion."""

        operation_root = self.contract_root / "operations"
        operation_root.mkdir(parents=True, exist_ok=True)
        if any(operation_root.glob("*.json")):
            raise ContractError("operation contract directory is not empty")
        count = 0
        for manifest_path in sorted(self.manifest_root.glob("*.json")):
            document = _read_json(manifest_path)
            raw_operations = document.get("operations") if isinstance(document, Mapping) else None
            if not isinstance(raw_operations, list):
                raise ContractError(f"{manifest_path}: expected an operations array")
            for order, raw in enumerate(raw_operations):
                if not isinstance(raw, Mapping):
                    raise ContractError(f"{manifest_path}: operation must be an object")
                operation_id = raw.get("operation_id")
                if not isinstance(operation_id, str):
                    raise ContractError(f"{manifest_path}: operation_id must be a string")
                source_path = operation_root / f"{operation_id}.json"
                source_operation = self._runtime_to_source(dict(raw), source_path)
                source = {
                    "$schema": OPERATION_SCHEMA_REF,
                    "source_schema_version": 2,
                    "target_manifest": manifest_path.name,
                    "manifest_order": order,
                    "operation": source_operation,
                }
                self.operation_schema.validate(source)
                source_path.write_bytes(_canonical_bytes(source))
                count += 1
        return count

    def _load_validator(self, path: Path) -> JsonSchemaValidator:
        document = _read_json(path)
        if not isinstance(document, Mapping):
            raise ContractError(f"{path}: schema root must be an object")
        return JsonSchemaValidator(document, str(path))

    def _load_operations(self) -> list[CompiledOperation]:
        compiled: list[CompiledOperation] = []
        operation_root = self.contract_root / "operations"
        for source_path in sorted(operation_root.glob("*.json")):
            source = _read_json(source_path)
            if not isinstance(source, Mapping):
                raise ContractError(f"{source_path}: source root must be an object")
            self.operation_schema.validate(source)
            operation = copy.deepcopy(source["operation"])
            self._require_pagination_dimensions(operation, source_path)
            expected = self._direct_provenance(source_path, operation)
            if operation.get("provenance") != expected:
                raise ContractError(f"{source_path}: provenance does not match its source path")
            compiled.append(
                self._compile_operation(
                    source["target_manifest"],
                    source["manifest_order"],
                    operation,
                    expected,
                    source_path,
                )
            )
        family_root = self.contract_root / "families"
        for source_path in sorted(family_root.glob("*.json")):
            compiled.extend(self._expand_family(source_path))
        if not compiled:
            raise ContractError("no operation contracts found")
        return compiled

    def _expand_family(self, source_path: Path) -> list[CompiledOperation]:
        source = _read_json(source_path)
        if not isinstance(source, Mapping):
            raise ContractError(f"{source_path}: family root must be an object")
        self.family_schema.validate(source)
        family_id = source["family_id"]
        results: list[CompiledOperation] = []
        seen_bindings: set[str] = set()
        for matrix_item in source["matrix"]:
            bindings = matrix_item["bindings"]
            binding_key = _canonical_text(bindings)
            if binding_key in seen_bindings:
                raise ContractError(f"{source_path}: duplicate family matrix bindings")
            seen_bindings.add(binding_key)
            operation = _interpolate(source["operation"], bindings)
            applied: list[str] = []
            disabled = False
            for override in source.get("overrides", []):
                if not _matches_bindings(bindings, override["when"]):
                    continue
                applied.append(override["id"])
                if override.get("disabled") is True:
                    disabled = True
                    break
                if override.get("escape_hatch") is True:
                    operation = _interpolate(override["replacement"], bindings)
                else:
                    patch = _interpolate(override["patch"], bindings)
                    operation_schema = self.operation_schema.fragment("#/$defs/operation")
                    self._validate_patch_fields(patch, operation_schema, "operation")
                    operation = _merge_patch(operation, patch)
            if disabled:
                continue
            provenance = {
                "source_files": [source_path.relative_to(self.contract_root).as_posix()],
                "family": family_id,
                "platform": operation.get("platform"),
                "applied_overrides": applied,
            }
            operation["provenance"] = provenance
            self._require_pagination_dimensions(operation, source_path)
            self.operation_schema.validate(
                {
                    "$schema": OPERATION_SCHEMA_REF,
                    "source_schema_version": 2,
                    "target_manifest": source["target_manifest"],
                    "manifest_order": matrix_item["manifest_order"],
                    "operation": operation,
                }
            )
            results.append(
                self._compile_operation(
                    source["target_manifest"],
                    matrix_item["manifest_order"],
                    operation,
                    provenance,
                    source_path,
                )
            )
        return results

    @staticmethod
    def _require_pagination_dimensions(
        operation: Mapping[str, Any], source_path: Path
    ) -> None:
        pagination = operation.get("pagination")
        if not isinstance(pagination, Mapping) or not {
            "completeness", "pagination_evidence"
        } <= set(pagination):
            raise ContractError(
                f"{source_path}: compiled operation pagination must explicitly declare "
                "completeness and pagination_evidence"
            )

    def _compile_operation(
        self,
        target_manifest: str,
        manifest_order: int,
        source_operation: Mapping[str, Any],
        provenance: Mapping[str, Any],
        source_path: Path,
    ) -> CompiledOperation:
        if not _TARGET_RE.fullmatch(target_manifest):
            raise ContractError(f"{source_path}: unsafe target manifest name")
        runtime = self._source_to_runtime(source_operation)
        try:
            spec = load_operation_manifest({"operations": [runtime]})[0]
        except ManifestError as exc:
            raise ContractError(f"{source_path}: runtime contract is invalid: {exc}") from exc
        return CompiledOperation(
            target_manifest=target_manifest,
            manifest_order=manifest_order,
            runtime=runtime,
            spec=spec,
            provenance=provenance,
        )

    def _semantic_lint(self, operations: Sequence[CompiledOperation]) -> None:
        by_id: dict[str, CompiledOperation] = {}
        by_route: dict[tuple[str, str], str] = {}
        orders: set[tuple[str, int]] = set()
        for compiled in operations:
            spec = compiled.spec
            if spec.operation_id in by_id:
                raise ContractError(f"duplicate operation_id: {spec.operation_id}")
            by_id[spec.operation_id] = compiled
            route = (spec.upstream_method, spec.path_template)
            if route in by_route:
                raise ContractError(
                    f"duplicate method+path: {route[0]} {route[1]} "
                    f"({by_route[route]}, {spec.operation_id})"
                )
            by_route[route] = spec.operation_id
            order_key = (compiled.target_manifest, compiled.manifest_order)
            if order_key in orders:
                raise ContractError(
                    f"duplicate manifest_order {compiled.manifest_order} in "
                    f"{compiled.target_manifest}"
                )
            orders.add(order_key)
            if not spec.privacy_policy.classification.strip():
                raise ContractError(f"{spec.operation_id}: privacy classification is required")
            if spec.pagination.kind == "page_info":
                names = set(spec.fields)
                bound = (
                    set(spec.request.path_fields)
                    | set(spec.request.query_fields)
                    | set(spec.request.body_fields)
                    | set(spec.request.defaults)
                )
                pagination_names = {
                    spec.pagination.page_field,
                    spec.pagination.page_size_field,
                }
                if not pagination_names <= names or not pagination_names <= bound:
                    raise ContractError(
                        f"{spec.operation_id}: pagination fields must exist and be request-bound"
                    )
        missing_parents = {
            parent.operation_id
            for compiled in operations
            for parent in compiled.spec.required_parent
            if parent.operation_id and parent.operation_id not in by_id
        }
        if missing_parents:
            raise ContractError(
                "required_parent references unknown operations: "
                + ", ".join(sorted(missing_parents))
            )

    def _render(self, operations: Sequence[CompiledOperation]) -> CompilationResult:
        grouped: dict[str, list[CompiledOperation]] = {}
        for operation in operations:
            grouped.setdefault(operation.target_manifest, []).append(operation)
        manifests: dict[str, bytes] = {}
        for name, items in sorted(grouped.items()):
            ordered = sorted(items, key=lambda item: (item.manifest_order, item.spec.operation_id))
            manifests[name] = _canonical_bytes(
                {"manifest_version": 1, "operations": [item.runtime for item in ordered]}
            )
        provenance = {
            "provenance_version": 1,
            "operation_count": len(operations),
            "operations": {
                item.spec.operation_id: item.provenance
                for item in sorted(operations, key=lambda entry: entry.spec.operation_id)
            },
        }
        return CompilationResult(
            manifests=manifests,
            provenance=_canonical_bytes(provenance),
            operation_count=len(operations),
        )

    def _write_result(self, result: CompilationResult) -> None:
        self.manifest_root.mkdir(parents=True, exist_ok=True)
        for name, payload in result.manifests.items():
            (self.manifest_root / name).write_bytes(payload)
        self.provenance_path.parent.mkdir(parents=True, exist_ok=True)
        self.provenance_path.write_bytes(result.provenance)

    def _check_result(self, result: CompilationResult) -> None:
        drift: list[str] = []
        expected_names = set(result.manifests)
        actual_names = {path.name for path in self.manifest_root.glob("*.json")}
        for name, payload in result.manifests.items():
            path = self.manifest_root / name
            if not path.is_file() or path.read_bytes() != payload:
                drift.append(str(path))
        for name in sorted(actual_names - expected_names):
            drift.append(f"unexpected:{self.manifest_root / name}")
        if not self.provenance_path.is_file() or self.provenance_path.read_bytes() != result.provenance:
            drift.append(str(self.provenance_path))
        if drift:
            raise ContractDriftError("compiled products are stale: " + ", ".join(drift))

    def _direct_provenance(
        self, source_path: Path, operation: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        return {
            "source_files": [source_path.relative_to(self.contract_root).as_posix()],
            "family": None,
            "platform": operation.get("platform"),
            "applied_overrides": [],
        }

    def _runtime_to_source(
        self, runtime: dict[str, Any], source_path: Path
    ) -> dict[str, Any]:
        operation = copy.deepcopy(runtime)
        privacy = operation.get("privacy_policy", {})
        if isinstance(privacy, Mapping):
            privacy = dict(privacy)
            privacy["redact_fields"] = privacy.pop("redact_keys", [])
            operation["privacy_policy"] = privacy
        probe = operation.get("live_probe", {})
        if isinstance(probe, Mapping):
            probe = dict(probe)
            probe["inputs"] = probe.pop("input", {})
            operation["live_probe"] = probe
        parents = []
        for parent in operation.get("required_parent", []):
            if isinstance(parent, str):
                operation_id = parent
                input_field = None
            else:
                operation_id = parent.get("operation_id")
                input_field = parent.get("input_field", parent.get("field"))
            parents.append(
                {
                    "operation_id": operation_id,
                    "input_field": input_field,
                    "output_path": None,
                    "selection": None,
                }
            )
        operation["required_parent"] = parents
        operation["effect"] = "mutation" if operation.get("stability") == "blocked_write" else "read"
        operation["examples"] = []
        operation["provenance"] = self._direct_provenance(source_path, operation)
        return operation

    @staticmethod
    def _source_to_runtime(source: Mapping[str, Any]) -> dict[str, Any]:
        operation = copy.deepcopy(dict(source))
        operation.pop("examples", None)
        operation.pop("provenance", None)
        privacy = operation.get("privacy_policy", {})
        if isinstance(privacy, Mapping):
            privacy = dict(privacy)
            privacy["redact_keys"] = privacy.pop("redact_fields", [])
            operation["privacy_policy"] = privacy
        probe = operation.get("live_probe", {})
        if isinstance(probe, Mapping):
            probe = dict(probe)
            probe["input"] = probe.pop("inputs", {})
            operation["live_probe"] = probe
        runtime_parents: list[Any] = []
        for parent in operation.get("required_parent", []):
            operation_id = parent["operation_id"]
            input_field = parent.get("input_field")
            if input_field:
                runtime_parents.append(
                    {"operation_id": operation_id, "input_field": input_field}
                )
            else:
                runtime_parents.append(operation_id)
        operation["required_parent"] = runtime_parents
        return operation

    def _validate_patch_fields(
        self, patch: Any, schema: Mapping[str, Any], path: str
    ) -> None:
        if "$ref" in schema:
            schema = self.operation_schema.fragment(schema["$ref"])
        if not isinstance(patch, Mapping):
            return
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", False)
        for name, value in patch.items():
            if name in properties:
                child = properties[name]
            elif isinstance(additional, Mapping):
                child = additional
            else:
                raise ContractError(f"override patch field is not schema-declared: {path}.{name}")
            self._validate_patch_fields(value, child, f"{path}.{name}")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError(f"could not read JSON: {path}") from exc


def _canonical_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def _matches_bindings(bindings: Mapping[str, Any], condition: Mapping[str, Any]) -> bool:
    return all(bindings.get(name) == value for name, value in condition.items())


def _merge_patch(target: Any, patch: Any) -> Any:
    if not isinstance(patch, Mapping):
        return copy.deepcopy(patch)
    result = copy.deepcopy(target) if isinstance(target, Mapping) else {}
    result = dict(result)
    for name, value in patch.items():
        if value is None:
            result.pop(name, None)
        else:
            result[name] = _merge_patch(result.get(name), value)
    return result


def _interpolate(value: Any, bindings: Mapping[str, Any]) -> Any:
    if isinstance(value, Mapping):
        return {name: _interpolate(item, bindings) for name, item in value.items()}
    if isinstance(value, list):
        return [_interpolate(item, bindings) for item in value]
    if not isinstance(value, str):
        return copy.deepcopy(value)
    exact = re.fullmatch(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", value)
    if exact and exact.group(1) in bindings:
        return copy.deepcopy(bindings[exact.group(1)])
    rendered = value
    for name, binding in bindings.items():
        if not _BINDING_RE.fullmatch(name):
            raise ContractError(f"unsafe family binding name: {name!r}")
        if binding is None:
            text = "null"
        elif isinstance(binding, bool):
            text = "true" if binding else "false"
        else:
            text = str(binding)
        rendered = rendered.replace("{" + name + "}", text)
    return rendered


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contracts-dir", type=Path, default=DEFAULT_CONTRACT_ROOT)
    parser.add_argument("--manifests-dir", type=Path, default=DEFAULT_MANIFEST_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    compile_parser = subparsers.add_parser("compile", help="write compiled products")
    compile_parser.add_argument(
        "--check", action="store_true", help="check products without writing"
    )
    subparsers.add_parser("check", help="alias for compile --check")
    subparsers.add_parser("lint", help="validate contracts without writing")
    subparsers.add_parser("migrate", help="one-time v1 manifest source migration")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        compiler = ContractCompiler(args.contracts_dir, args.manifests_dir)
        if args.command == "migrate":
            count = compiler.migrate_manifests()
            print(f"migrated {count} operation contracts")
            return 0
        if args.command == "lint":
            result = compiler.lint()
        elif args.command == "check" or args.check:
            result = compiler.check()
        else:
            result = compiler.compile()
        print(
            f"{args.command}: {result.operation_count} operations, "
            f"{len(result.manifests)} manifests"
        )
        return 0
    except ContractError as exc:
        print(f"contract compiler: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
