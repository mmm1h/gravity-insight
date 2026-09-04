"""AST and schema ratchet for consumer-facing result envelope obligations."""

from __future__ import annotations

import argparse
import ast
import hashlib
import textwrap
import json
import os
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from gravity_insight.agent_runtime_contracts import validate_schema
from gravity_insight.paths import PROJECT_ROOT


ROOT = PROJECT_ROOT
SOURCE_ROOT = Path("src/gravity_insight")
BASELINE_PATH = Path("src/gravity_insight/governance/envelope-obligations-baseline.json")
BASELINE_SCHEMA_VERSION = "gravity.envelope-obligation-baseline.v1"
BASE_REF_ENV = "GRAVITY_QUALITY_BASE_REF"
OBLIGATIONS = (
    "execution_status",
    "data_completeness",
    "semantic_validity",
    "diagnostic_evidence",
    "mutation_certainty",
)
_OUTCOME_KEYS = frozenset({"ok", "status", "error", "next_action"})
_PAYLOAD_KEYS = frozenset({"data", "result", "results", "items", "summary", "warnings"})
_SERIALIZER = "serialize_envelope"
_SERIALIZER_MODULE = "contracts.envelope_obligations"
_OUTER_LITERAL_STATES = frozenset(
    {
        "complete", "partial", "failed", "not_started", "prefix", "unknown",
        "not_applicable", "valid", "invalid", "none", "available", "incomplete",
        "not_attempted", "applied", "confirmed", "uncertain",
    }
)
_OBLIGATION_TYPE_NAMES = frozenset(
    {
        "EnvelopeObligations", "ExecutionStatus", "DataCompleteness",
        "SemanticValidity", "DiagnosticEvidence", "MutationCertainty",
    }
)
_EXEMPTION_CLASSIFICATIONS = frozenset(
    {"schema_document", "internal_state", "non_consumer_transport"}
)


@dataclass(frozen=True)
class EnvelopePath:
    identity: str
    path: str
    qualname: str
    line: int
    structural_keys: tuple[str, ...]
    typed: bool


def _literal_keys(node: ast.AST | None) -> set[str]:
    if isinstance(node, ast.Dict):
        return {
            key.value
            for key in node.keys
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
        return {keyword.arg for keyword in node.keywords if keyword.arg is not None}
    return set()


def _local_nodes(function: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterable[ast.AST]:
    pending = list(reversed(function.body))
    while pending:
        node = pending.pop()
        yield node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        pending.extend(reversed(list(ast.iter_child_nodes(node))))


def _assignment_target(target: ast.AST) -> tuple[str, str | None] | None:
    if isinstance(target, ast.Name):
        return target.id, None
    if (
        isinstance(target, ast.Subscript)
        and isinstance(target.value, ast.Name)
        and isinstance(target.slice, ast.Constant)
        and isinstance(target.slice.value, str)
    ):
        return target.value.id, target.slice.value
    return None


def _update_call(node: ast.AST) -> tuple[str, set[str]] | None:
    if not (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "update"
        and isinstance(node.func.value, ast.Name)
    ):
        return None
    keys: set[str] = set()
    for argument in node.args:
        keys.update(_literal_keys(argument))
    keys.update(keyword.arg for keyword in node.keywords if keyword.arg is not None)
    return node.func.value.id, keys


def _mapping_keys(function: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for node in _local_nodes(function):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            keys = _literal_keys(value)
            for target in targets:
                selected = _assignment_target(target)
                if selected is None:
                    continue
                name, key = selected
                result.setdefault(name, set()).update({key} if key else keys)
            continue
        updated = _update_call(node)
        if updated is not None:
            name, keys = updated
            result.setdefault(name, set()).update(keys)
    return result


def _serializer_bindings(tree: ast.Module) -> tuple[set[str], set[str]]:
    names: set[str] = set()
    modules: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith(
            _SERIALIZER_MODULE
        ):
            names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == _SERIALIZER
            )
        elif isinstance(node, ast.Import):
            modules.update(
                alias.asname
                for alias in node.names
                if alias.asname and alias.name.endswith(_SERIALIZER_MODULE)
            )
    return names, modules


def _canonical_serializer_call(
    node: ast.AST | None, names: set[str], modules: set[str]
) -> ast.Call | None:
    if not isinstance(node, ast.Call):
        return None
    direct = isinstance(node.func, ast.Name) and node.func.id in names
    qualified = (
        isinstance(node.func, ast.Attribute)
        and node.func.attr == _SERIALIZER
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in modules
    )
    if not direct and not qualified:
        return None
    obligation = next(
        (keyword.value for keyword in node.keywords if keyword.arg == "obligations"),
        node.args[1] if len(node.args) > 1 else None,
    )
    return node if isinstance(obligation, ast.Name) else None


def _outer_reconstructs_facts(
    function: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    nodes = tuple(_local_nodes(function))
    if any(
        isinstance(node, ast.Constant) and node.value in _OUTER_LITERAL_STATES
        for node in nodes
    ):
        return True
    if any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _OBLIGATION_TYPE_NAMES
        for node in nodes
    ):
        return True
    return _uses_exception_string(nodes)


def _uses_exception_string(nodes: Sequence[ast.AST]) -> bool:
    exception_names = {
        node.name
        for node in nodes
        if isinstance(node, ast.ExceptHandler) and isinstance(node.name, str)
    }
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "str"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id in exception_names
        for node in nodes
    )


def _is_envelope_shape(keys: set[str]) -> bool:
    return bool(
        "schema_version" in keys and keys & _OUTCOME_KEYS
        or {"ok", "status"} <= keys
        or "status" in keys and bool(keys & _PAYLOAD_KEYS)
    )


def _return_shape(node: ast.AST, source: str) -> str:
    """Describe a returned value by its source text, not by its parsed shape.

    `ast.dump` is not a stable identity across interpreters: Python 3.13 stopped
    emitting fields left at their empty defaults, so the same return statement
    dumps differently on 3.12 and on 3.14. Every baseline key here embeds this
    digest, so an AST-derived one would mark all 319 recorded paths as new the
    moment the gate ran on a different supported Python.

    Pinning `feature_version` on the parse does not help; it constrains the
    grammar accepted, not how the resulting tree is rendered.
    """

    segment = ast.get_source_segment(source, node)
    if segment is None:  # pragma: no cover - parsed nodes always carry positions
        return ast.dump(node, annotate_fields=True, include_attributes=False)
    lines = [line.rstrip() for line in segment.splitlines()]
    return textwrap.dedent("\n".join(lines))


def _function_paths(
    path: str,
    qualname: str,
    function: ast.FunctionDef | ast.AsyncFunctionDef,
    serializer_names: set[str],
    serializer_modules: set[str],
    source: str,
) -> list[EnvelopePath]:
    names = _mapping_keys(function)
    candidates: list[tuple[ast.Return, set[str], bool, str]] = []
    for node in _local_nodes(function):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        serializer_call = _canonical_serializer_call(
            node.value, serializer_names, serializer_modules
        )
        typed = serializer_call is not None and not _outer_reconstructs_facts(function)
        if serializer_call is not None:
            keys = {"obligations"}
        elif isinstance(node.value, ast.Name):
            keys = set(names.get(node.value.id, ()))
        else:
            keys = _literal_keys(node.value)
        if serializer_call is None and not _is_envelope_shape(keys):
            continue
        shape = _return_shape(node.value, source)
        digest = hashlib.sha256(
            (shape + "\0" + "\0".join(sorted(keys))).encode("utf-8")
        ).hexdigest()[:16]
        candidates.append((node, keys, typed, digest))
    duplicate = Counter(item[3] for item in candidates)
    observed: Counter[str] = Counter()
    result: list[EnvelopePath] = []
    for node, keys, typed, digest in sorted(candidates, key=lambda item: item[0].lineno):
        observed[digest] += 1
        suffix = f":{observed[digest]}" if duplicate[digest] > 1 else ""
        identity = f"{path}::{qualname}::{digest}{suffix}"
        result.append(
            EnvelopePath(
                identity,
                path,
                qualname,
                node.lineno,
                tuple(sorted(keys)),
                typed,
            )
        )
    return result


def _functions(tree: ast.Module) -> Iterable[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    def visit(body: Sequence[ast.stmt], prefix: tuple[str, ...] = ()):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = ".".join((*prefix, node.name))
                yield qualname, node
                yield from visit(node.body, (*prefix, node.name, "<locals>"))
            elif isinstance(node, ast.ClassDef):
                yield from visit(node.body, (*prefix, node.name))
    yield from visit(tree.body)


def inspect_repository(root: Path = ROOT) -> list[EnvelopePath]:
    rows: list[EnvelopePath] = []
    for source_path in sorted((root / SOURCE_ROOT).rglob("*.py")):
        relative = source_path.relative_to(root).as_posix()
        try:
            source = source_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=relative, feature_version=(3, 11))
        except (OSError, UnicodeError, SyntaxError) as exc:
            raise ValueError(f"cannot inspect envelope source {relative}: {exc}") from exc
        names, modules = _serializer_bindings(tree)
        for qualname, function in _functions(tree):
            rows.extend(
                _function_paths(
                    relative, qualname, function, names, modules, source
                )
            )
    return sorted(rows, key=lambda item: item.identity)


def _load_baseline(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("envelope obligation baseline must be an object")
    validate_schema(
        value,
        "envelope-obligation-baseline-v1.schema.json",
        "Envelope obligation baseline",
    )
    if tuple(value["required_obligations"]) != OBLIGATIONS:
        raise ValueError("envelope obligation baseline changed the required obligation set")
    for field in ("legacy_violations", "exemptions"):
        if not isinstance(value[field], dict):
            raise ValueError(f"envelope obligation baseline {field} must be an object")
    return value


def _entry(row: EnvelopePath) -> dict[str, Any]:
    return {
        "path": row.path,
        "qualname": row.qualname,
        "structural_keys": list(row.structural_keys),
    }


def baseline_document(paths: Sequence[EnvelopePath]) -> dict[str, Any]:
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "required_obligations": list(OBLIGATIONS),
        "legacy_violations": {
            row.identity: _entry(row) for row in paths if not row.typed
        },
        "exemptions": {},
    }


def compare_baselines(current: Mapping[str, Any], base: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("legacy_violations", "exemptions"):
        current_rows = current.get(field, {})
        base_rows = base.get(field, {})
        if not isinstance(current_rows, Mapping) or not isinstance(base_rows, Mapping):
            errors.append(f"envelope obligation {field} must remain an object")
            continue
        added = sorted(set(current_rows) - set(base_rows))
        if added:
            errors.append(
                f"envelope obligation baseline cannot add {field}: {', '.join(added[:5])}"
            )
        for identity in sorted(set(current_rows) & set(base_rows)):
            if current_rows[identity] != base_rows[identity]:
                errors.append(f"envelope obligation baseline entry changed: {identity}")
    return errors


def _valid_exemption(value: Any, row: EnvelopePath) -> bool:
    required = {
        "path", "qualname", "structural_keys", "classification", "reason"
    }
    if not isinstance(value, Mapping) or set(value) != required:
        return False
    identity_fields = {
        name: value[name] for name in ("path", "qualname", "structural_keys")
    }
    return bool(
        value.get("classification") in _EXEMPTION_CLASSIFICATIONS
        and isinstance(value.get("reason"), str)
        and value["reason"].strip()
        and identity_fields == _entry(row)
    )


def evaluate(paths: Sequence[EnvelopePath], baseline: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    legacy = baseline["legacy_violations"]
    exemptions = baseline["exemptions"]
    untyped = {row.identity: row for row in paths if not row.typed}
    for identity, row in sorted(untyped.items()):
        if identity in exemptions:
            exemption = exemptions[identity]
            if not _valid_exemption(exemption, row):
                errors.append(f"invalid envelope obligation exemption: {identity}")
            continue
        if identity not in legacy:
            errors.append(
                f"{row.path}:{row.line}: new untyped consumer envelope path {row.qualname}; "
                "return typed EnvelopeObligations through serialize_envelope"
            )
        elif legacy[identity] != _entry(row):
            errors.append(f"envelope obligation legacy entry drifted: {identity}")
    active = set(untyped)
    for identity in sorted(set(legacy) - active):
        errors.append(f"stale envelope obligation legacy entry must be removed: {identity}")
    for identity in sorted(set(exemptions) - active):
        errors.append(f"stale envelope obligation exemption must be removed: {identity}")
    return errors


def _baseline_at_ref(root: Path, ref: str | None) -> dict[str, Any] | None:
    if not ref or not ref.strip("0"):
        return None
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{BASELINE_PATH.as_posix()}"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        return None
    value = json.loads(result.stdout.decode("utf-8"))
    return value if isinstance(value, dict) else None


def validate(root: Path = ROOT, *, base_ref: str | None = None) -> list[str]:
    try:
        validate_schema(
            {
                "schema_version": "gravity.envelope-obligations.v1",
                "execution_status": {"state": "not_started", "evidence_code": "SCHEMA_PROBE"},
                "data_completeness": {
                    "state": "not_applicable", "evidence_code": "SCHEMA_PROBE", "facts": {}
                },
                "semantic_validity": {"state": "not_applicable", "evidence_codes": []},
                "diagnostic_evidence": {"state": "none", "evidence_codes": []},
                "mutation_certainty": {
                    "state": "not_applicable", "evidence_code": "SCHEMA_PROBE"
                },
            },
            "envelope-obligations-v1.schema.json",
            "Envelope obligation schema probe",
        )
        paths = inspect_repository(root)
        baseline = _load_baseline(root / BASELINE_PATH)
        errors = evaluate(paths, baseline)
        resolved_ref = base_ref if base_ref is not None else os.environ.get(BASE_REF_ENV)
        base = _baseline_at_ref(root, resolved_ref)
        if base is not None:
            errors.extend(compare_baselines(baseline, base))
        return errors
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        return [f"invalid envelope obligation gate: {exc}"]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check")
    check.add_argument("--base-ref")
    baseline = subparsers.add_parser("baseline")
    baseline.add_argument("--write", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    paths = inspect_repository(root)
    if args.command == "baseline":
        document = baseline_document(paths)
        payload = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ) + "\n"
        if args.write:
            path = root / BASELINE_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8", newline="\n")
        else:
            print(payload, end="")
        return 0
    errors = validate(root, base_ref=args.base_ref)
    if errors:
        for error in errors:
            print(f"FAIL P1 envelope-obligations: {error}")
        return 1
    typed = sum(row.typed for row in paths)
    print(
        "PASS envelope-obligations: "
        f"paths={len(paths)}, typed={typed}, legacy={len(paths) - typed}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BASELINE_PATH",
    "EnvelopePath",
    "baseline_document",
    "compare_baselines",
    "evaluate",
    "inspect_repository",
    "validate",
]
