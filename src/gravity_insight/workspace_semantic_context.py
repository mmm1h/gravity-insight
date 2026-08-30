"""Caller-owned semantic context schema and fail-closed reference validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .errors import ErrorCategory, GravityInsightError


SCHEMA_VERSION = "gravity.semantic-context.v1"
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_TARGET_KINDS = frozenset(
    {
        "product",
        "operation",
        "event",
        "event_property",
        "user_property",
        "metric",
        "custom_metric",
    }
)
_APP_TARGET_KINDS = frozenset({"event", "event_property", "user_property"})
_ROOT_FIELDS = frozenset(
    {
        "schema_version", "instructions", "terms", "exclusions", "verified_queries",
        "derived_metrics",
    }
)


class SemanticContextError(GravityInsightError, ValueError):
    """A caller workspace semantic contract failed local validation."""

    code = "SEMANTIC_CONTEXT_INVALID"
    category = ErrorCategory.LOCAL

    def __init__(self, message: str, *, field: str) -> None:
        super().__init__(
            message,
            field=field,
            next_action="Correct [semantic_context] in gravity.toml, then retry.",
        )


@dataclass(frozen=True)
class SemanticTarget:
    kind: str
    ref: str
    app: str | None = None

    def contract(self) -> dict[str, str]:
        value = {"kind": self.kind, "ref": self.ref}
        if self.app is not None:
            value["app"] = self.app
        return value

    @property
    def identity(self) -> str:
        return f"{self.kind}:{self.app or ''}:{self.ref}"


@dataclass(frozen=True)
class SemanticTerm:
    name: str
    phrases: tuple[str, ...]
    description: str
    target: SemanticTarget


@dataclass(frozen=True)
class SemanticExclusion:
    name: str
    when: tuple[str, ...]
    reason: str
    target: SemanticTarget


@dataclass(frozen=True)
class VerifiedQuery:
    name: str
    question: str
    description: str
    operation: str
    inputs: Mapping[str, Any]
    all_pages: bool


@dataclass(frozen=True)
class DerivedMetric:
    name: str
    phrases: tuple[str, ...]
    description: str
    spec: Mapping[str, Any]


@dataclass(frozen=True)
class SemanticContext:
    instructions: str
    terms: tuple[SemanticTerm, ...]
    exclusions: tuple[SemanticExclusion, ...]
    verified_queries: tuple[VerifiedQuery, ...]
    derived_metrics: tuple[DerivedMetric, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def contract(self) -> dict[str, Any]:
        """Return a deterministic, caller-value-preserving fingerprint payload."""

        return {
            "schema_version": self.schema_version,
            "instructions": self.instructions,
            "terms": [
                {
                    "name": item.name,
                    "phrases": list(item.phrases),
                    "description": item.description,
                    "target": item.target.contract(),
                }
                for item in self.terms
            ],
            "exclusions": [
                {
                    "name": item.name,
                    "when": list(item.when),
                    "reason": item.reason,
                    "target": item.target.contract(),
                }
                for item in self.exclusions
            ],
            "verified_queries": [
                {
                    "name": item.name,
                    "question": item.question,
                    "description": item.description,
                    "operation": item.operation,
                    "input": dict(item.inputs),
                    "all_pages": item.all_pages,
                }
                for item in self.verified_queries
            ],
            "derived_metrics": [
                {
                    "name": item.name,
                    "phrases": list(item.phrases),
                    "description": item.description,
                    "spec": dict(item.spec),
                }
                for item in self.derived_metrics
            ],
        }


def validate_semantic_context(
    value: Any,
    *,
    apps: Mapping[str, int],
    products: Mapping[str, Mapping[str, Any]],
    recipes: Mapping[str, Any],
    path: Path,
) -> SemanticContext | None:
    """Validate the optional independent semantic-context sub-contract."""

    if value is None:
        return None
    field = "semantic_context"
    if not isinstance(value, dict):
        raise _invalid(path, field, "must be a table")
    unknown = sorted(set(value) - _ROOT_FIELDS)
    if unknown:
        raise _invalid(path, field, f"has unknown fields: {', '.join(unknown)}")
    if value.get("schema_version") != SCHEMA_VERSION:
        raise _invalid(path, f"{field}.schema_version", f"must be {SCHEMA_VERSION!r}")
    instructions = (
        _nonempty_text(value["instructions"], f"{field}.instructions", path)
        if "instructions" in value
        else ""
    )

    operations = _compiled_operations()
    product_selectors = _workspace_product_selectors(products, recipes)
    terms = _terms(
        value.get("terms", []), apps, product_selectors, operations, path
    )
    exclusions = _exclusions(
        value.get("exclusions", []), apps, product_selectors, operations, path
    )
    verified = _verified_queries(value.get("verified_queries", []), operations, path)
    derived = _derived_metrics(value.get("derived_metrics", []), path)
    if not (instructions or terms or exclusions or verified or derived):
        raise _invalid(path, field, "must declare instructions, terms, exclusions, verified_queries, or derived_metrics")
    _unique_triggers(terms, exclusions, verified, derived, path)
    return SemanticContext(
        instructions=instructions,
        terms=tuple(terms),
        exclusions=tuple(exclusions),
        verified_queries=tuple(verified),
        derived_metrics=tuple(derived),
    )


def normalized_phrase(value: str) -> str:
    """Normalize literal matching without similarity or semantic expansion."""

    return " ".join(value.strip().casefold().split())


def phrase_matches(query: str, phrase: str) -> bool:
    """Match an explicitly declared literal phrase at deterministic boundaries."""

    selected = normalized_phrase(query)
    target = normalized_phrase(phrase)
    if not target:
        return False
    if target.isascii():
        expression = re.escape(target).replace(r"\ ", r"\s+")
        return bool(re.search(rf"(?<![a-z0-9_]){expression}(?![a-z0-9_])", selected))
    return target in selected


def compiled_operation(operation_id: str) -> Any | None:
    return _compiled_operations().get(operation_id)


def semantic_fingerprint_fields(workspace: Any | None) -> dict[str, Any]:
    context = getattr(workspace, "semantic_context", None)
    return {"semantic_context": context.contract()} if context is not None else {}


def _terms(
    value: Any,
    apps: Mapping[str, int],
    products: frozenset[str],
    operations: Mapping[str, Any],
    path: Path,
) -> list[SemanticTerm]:
    rows = _object_array(value, "semantic_context.terms", path)
    result: list[SemanticTerm] = []
    for index, raw in enumerate(rows):
        field = f"semantic_context.terms.{index}"
        _fields(raw, field, required={"name", "phrases", "target"}, optional={"description"}, path=path)
        result.append(
            SemanticTerm(
                name=_name(raw["name"], f"{field}.name", path),
                phrases=tuple(_phrases(raw["phrases"], f"{field}.phrases", path)),
                description=_text(raw.get("description", ""), f"{field}.description", path),
                target=_target(raw["target"], f"{field}.target", apps, products, operations, path),
            )
        )
    return result


def _exclusions(
    value: Any,
    apps: Mapping[str, int],
    products: frozenset[str],
    operations: Mapping[str, Any],
    path: Path,
) -> list[SemanticExclusion]:
    rows = _object_array(value, "semantic_context.exclusions", path)
    result: list[SemanticExclusion] = []
    for index, raw in enumerate(rows):
        field = f"semantic_context.exclusions.{index}"
        _fields(raw, field, required={"name", "when", "reason", "target"}, optional=set(), path=path)
        result.append(
            SemanticExclusion(
                name=_name(raw["name"], f"{field}.name", path),
                when=tuple(_phrases(raw["when"], f"{field}.when", path)),
                reason=_nonempty_text(raw["reason"], f"{field}.reason", path),
                target=_target(raw["target"], f"{field}.target", apps, products, operations, path),
            )
        )
    return result


def _verified_queries(
    value: Any, operations: Mapping[str, Any], path: Path
) -> list[VerifiedQuery]:
    rows = _object_array(value, "semantic_context.verified_queries", path)
    result: list[VerifiedQuery] = []
    for index, raw in enumerate(rows):
        field = f"semantic_context.verified_queries.{index}"
        _fields(
            raw,
            field,
            required={"name", "question", "operation", "input"},
            optional={"description", "all_pages"},
            path=path,
        )
        operation_id = _nonempty_text(raw["operation"], f"{field}.operation", path)
        operation = _read_operation(operation_id, operations, f"{field}.operation", path)
        inputs = raw["input"]
        if not isinstance(inputs, dict):
            raise _invalid(path, f"{field}.input", "must be a table")
        _json_value(inputs, f"{field}.input", path)
        try:
            operation.validate_inputs(inputs)
        except (TypeError, ValueError) as exc:
            raise _invalid(path, f"{field}.input", f"is invalid for {operation_id!r}: {exc}") from exc
        all_pages = raw.get("all_pages", False)
        if type(all_pages) is not bool:
            raise _invalid(path, f"{field}.all_pages", "must be a boolean")
        if all_pages and operation.pagination.kind == "none":
            raise _invalid(path, f"{field}.all_pages", "requires a paginated operation")
        result.append(
            VerifiedQuery(
                name=_name(raw["name"], f"{field}.name", path),
                question=_nonempty_text(raw["question"], f"{field}.question", path),
                description=_text(raw.get("description", ""), f"{field}.description", path),
                operation=operation_id,
                inputs=dict(inputs),
                all_pages=all_pages,
            )
        )
    return result


def _derived_metrics(value: Any, path: Path) -> list[DerivedMetric]:
    from .derived_metrics import validate_derived_spec

    rows = _object_array(value, "semantic_context.derived_metrics", path)
    result: list[DerivedMetric] = []
    for index, raw in enumerate(rows):
        field = f"semantic_context.derived_metrics.{index}"
        _fields(
            raw,
            field,
            required={"name", "phrases", "spec"},
            optional={"description"},
            path=path,
        )
        specification = raw["spec"]
        try:
            validate_derived_spec(specification)
        except (TypeError, ValueError) as exc:
            raise _invalid(path, f"{field}.spec", f"is invalid: {exc}") from exc
        result.append(
            DerivedMetric(
                name=_name(raw["name"], f"{field}.name", path),
                phrases=tuple(_phrases(raw["phrases"], f"{field}.phrases", path)),
                description=_text(raw.get("description", ""), f"{field}.description", path),
                spec=dict(specification),
            )
        )
    return result


def _target(
    value: Any,
    field: str,
    apps: Mapping[str, int],
    products: frozenset[str],
    operations: Mapping[str, Any],
    path: Path,
) -> SemanticTarget:
    if not isinstance(value, dict):
        raise _invalid(path, field, "must be a table")
    kind = value.get("kind")
    required = {"kind", "ref", *(("app",) if kind in _APP_TARGET_KINDS else ())}
    _fields(value, field, required=required, optional=set(), path=path)
    if kind not in _TARGET_KINDS:
        raise _invalid(path, f"{field}.kind", "is unsupported")
    ref = _nonempty_text(value["ref"], f"{field}.ref", path)
    app = value.get("app")
    if kind in _APP_TARGET_KINDS:
        if not isinstance(app, str) or app not in apps:
            raise _invalid(path, f"{field}.app", "must name an alias in [apps]")
    elif app is not None:
        raise _invalid(path, f"{field}.app", f"is not valid for target kind {kind!r}")
    if kind == "product" and not (
        ref.startswith("composite:") or ref in products
    ):
        raise _invalid(path, f"{field}.ref", f"references unknown product selector {ref!r}")
    if kind == "operation":
        _read_operation(ref, operations, f"{field}.ref", path)
    return SemanticTarget(str(kind), ref, app)


def _workspace_product_selectors(
    products: Mapping[str, Mapping[str, Any]], recipes: Mapping[str, Any]
) -> frozenset[str]:
    return frozenset(
        {
            *(f"@{name}" for name in recipes),
            *(f"sql:{name}" for name in products),
        }
    )


@lru_cache(maxsize=1)
def _compiled_operations() -> Mapping[str, Any]:
    from .models import load_operation_manifest

    root = Path(__file__).resolve().parent / "manifests"
    operations: dict[str, Any] = {}
    for manifest in sorted(root.glob("*.json")):
        for operation in load_operation_manifest(manifest):
            if operation.operation_id in operations:
                raise RuntimeError(f"duplicate compiled operation: {operation.operation_id}")
            operations[operation.operation_id] = operation
    if not operations:
        raise RuntimeError("compiled operation catalog is empty")
    return operations


def _read_operation(
    operation_id: str, operations: Mapping[str, Any], field: str, path: Path
) -> Any:
    operation = operations.get(operation_id)
    if (
        operation is None
        or operation.stability != "stable"
        or not operation.executable
        or operation.effect != "read"
    ):
        raise _invalid(path, field, f"references unknown stable read operation {operation_id!r}")
    return operation


def _unique_triggers(
    terms: list[SemanticTerm],
    exclusions: list[SemanticExclusion],
    verified: list[VerifiedQuery],
    derived: list[DerivedMetric],
    path: Path,
) -> None:
    names = [item.name for item in (*terms, *exclusions, *verified, *derived)]
    if len(names) != len(set(names)):
        raise _invalid(path, "semantic_context", "declaration names must be unique")
    triggers: dict[str, str] = {}
    for owner, values in (
        *((item.name, item.phrases) for item in terms),
        *((item.name, (item.question,)) for item in verified),
        *((item.name, item.phrases) for item in derived),
    ):
        for value in values:
            normalized = normalized_phrase(value)
            if normalized in triggers:
                raise _invalid(
                    path,
                    "semantic_context",
                    f"query trigger {value!r} is duplicated by {triggers[normalized]!r} and {owner!r}",
                )
            triggers[normalized] = owner


def _object_array(value: Any, field: str, path: Path) -> list[Mapping[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise _invalid(path, field, "must be an array of tables")
    return value


def _fields(
    value: Mapping[str, Any],
    field: str,
    *,
    required: set[str],
    optional: set[str],
    path: Path,
) -> None:
    missing = sorted(required - set(value))
    unknown = sorted(set(value) - required - optional)
    if missing or unknown:
        details = [
            *(f"missing {name}" for name in missing),
            *(f"unknown {name}" for name in unknown),
        ]
        raise _invalid(path, field, f"has invalid fields: {', '.join(details)}")


def _phrases(value: Any, field: str, path: Path) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and normalized_phrase(item) for item in value)
    ):
        raise _invalid(path, field, "must be a non-empty string array")
    normalized = [normalized_phrase(item) for item in value]
    if len(normalized) != len(set(normalized)):
        raise _invalid(path, field, "must not contain duplicate phrases")
    return list(value)


def _name(value: Any, field: str, path: Path) -> str:
    if not isinstance(value, str) or not _NAME_RE.fullmatch(value):
        raise _invalid(path, field, "must be a stable name")
    return value


def _text(value: Any, field: str, path: Path) -> str:
    if not isinstance(value, str):
        raise _invalid(path, field, "must be a string")
    return value


def _nonempty_text(value: Any, field: str, path: Path) -> str:
    selected = _text(value, field, path)
    if not selected.strip():
        raise _invalid(path, field, "must be non-empty")
    return selected


def _json_value(value: Any, field: str, path: Path) -> None:
    try:
        json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise _invalid(path, field, "contains a non-JSON value") from exc


def _invalid(path: Path, field: str, message: str) -> SemanticContextError:
    return SemanticContextError(f"{path}: {field} {message}", field=field)


__all__ = [
    "SCHEMA_VERSION",
    "SemanticContext",
    "SemanticContextError",
    "SemanticExclusion",
    "SemanticTarget",
    "SemanticTerm",
    "DerivedMetric",
    "VerifiedQuery",
    "compiled_operation",
    "normalized_phrase",
    "phrase_matches",
    "semantic_fingerprint_fields",
    "validate_semantic_context",
]
