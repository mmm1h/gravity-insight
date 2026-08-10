from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Mapping


def _json_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fingerprint_contract(contract: Mapping[str, Any]) -> str:
    """Fingerprint a local contract document without observing upstream data."""

    return _json_fingerprint(contract)


def _raw_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return "unknown"


def _pointer_part(value: Any) -> str:
    return str(value).replace("~", "~0").replace("/", "~1")


class _RawSketchBuilder:
    def __init__(self) -> None:
        self.sample_count = 0
        self.types: dict[str, set[str]] = {}
        self.present: dict[str, int] = {}
        self.parents: dict[str, tuple[str, str]] = {}
        self.object_opportunities: dict[str, int] = {}
        self.array_opportunities: dict[str, int] = {}
        self.array_items_present: dict[str, int] = {}
        self.empty_array_items: set[str] = set()

    def observe(self, value: Any) -> None:
        self.sample_count += 1
        self._visit(value, "$", parent=None)

    def _visit(
        self,
        value: Any,
        path: str,
        *,
        parent: tuple[str, str] | None,
    ) -> None:
        self.types.setdefault(path, set()).add(_raw_type(value))
        self.present[path] = self.present.get(path, 0) + 1
        if parent is not None:
            self.parents.setdefault(path, parent)
        if isinstance(value, Mapping):
            self.object_opportunities[path] = self.object_opportunities.get(path, 0) + 1
            for name, item in value.items():
                self._visit(
                    item,
                    f"{path}/{_pointer_part(name)}",
                    parent=(path, "field"),
                )
        elif isinstance(value, (list, tuple)):
            self._visit_array(value, path)

    def _visit_array(self, value: list[Any] | tuple[Any, ...], path: str) -> None:
        item_path = f"{path}/[]"
        self.parents.setdefault(item_path, (path, "item"))
        self.types.setdefault(item_path, set())
        self.present.setdefault(item_path, 0)
        self.array_opportunities[path] = self.array_opportunities.get(path, 0) + 1
        if not value:
            self.empty_array_items.add(item_path)
            return
        self.array_items_present[item_path] = self.array_items_present.get(item_path, 0) + 1
        for item in value:
            self._visit(item, item_path, parent=(path, "item"))

    def finish(self) -> dict[str, Any]:
        paths = {path: self._path_detail(path) for path in sorted(self.types)}
        fingerprint_payload = {
            "schema_version": "gravity-insight.raw-schema-sketch.v1",
            "paths": paths,
        }
        return {
            **fingerprint_payload,
            "sample_count": self.sample_count,
            "raw_schema_fingerprint": _json_fingerprint(fingerprint_payload),
        }

    def _path_detail(self, path: str) -> dict[str, Any]:
        if path == "$":
            required = self.sample_count > 0 and self.present[path] == self.sample_count
            item_unknown = False
        else:
            parent_path, kind = self.parents[path]
            if kind == "field":
                opportunities = self.object_opportunities.get(parent_path, 0)
                required = opportunities > 0 and self.present[path] == opportunities
                item_unknown = False
            else:
                opportunities = self.array_opportunities.get(parent_path, 0)
                required = (
                    opportunities > 0
                    and self.array_items_present.get(path, 0) == opportunities
                )
                item_unknown = path in self.empty_array_items or not self.types[path]
        return {
            "types": sorted(self.types[path]),
            "required": required,
            "item_unknown": item_unknown,
        }


def build_raw_schema_sketch(samples: Iterable[Any]) -> dict[str, Any]:
    """Build a value-free schema sketch across raw, pre-projection responses."""

    builder = _RawSketchBuilder()
    for sample in samples:
        builder.observe(sample)
    return builder.finish()


def sketch_raw_response(value: Any) -> dict[str, Any]:
    """Build a raw schema sketch for one response, including top-level arrays."""

    return build_raw_schema_sketch((value,))


def _paths(value: Mapping[str, Any]) -> Mapping[str, Any]:
    paths = value.get("paths")
    if not isinstance(paths, Mapping):
        raise ValueError("raw schema sketch must contain a paths object")
    return paths


def _new_path_groups(
    old_paths: Mapping[str, Any], new_paths: Mapping[str, Any]
) -> tuple[list[str], list[str]]:
    old_unknown_items = tuple(
        path
        for path, detail in old_paths.items()
        if isinstance(detail, Mapping) and bool(detail.get("item_unknown"))
    )
    added: list[str] = []
    observed: list[str] = []
    for path in sorted(set(new_paths) - set(old_paths)):
        target = (
            observed
            if any(path.startswith(f"{prefix}/") for prefix in old_unknown_items)
            else added
        )
        target.append(path)
    return added, observed


def _type_changes(
    old_paths: Mapping[str, Any], new_paths: Mapping[str, Any]
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for path in sorted(set(old_paths) & set(new_paths)):
        old_detail = old_paths[path]
        new_detail = new_paths[path]
        if not isinstance(old_detail, Mapping) or not isinstance(new_detail, Mapping):
            continue
        old_types = sorted(str(item) for item in old_detail.get("types", ()))
        new_types = sorted(str(item) for item in new_detail.get("types", ()))
        if old_types and new_types and old_types != new_types:
            changes.append({"path": path, "before": old_types, "after": new_types})
    return changes


def compare_raw_schema_sketches(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> dict[str, Any]:
    """Classify raw shape evidence without treating empty arrays as stable schemas."""

    old_paths = _paths(before)
    new_paths = _paths(after)
    added_paths, newly_observed_paths = _new_path_groups(old_paths, new_paths)
    removed_required_paths = sorted(
        path
        for path in set(old_paths) - set(new_paths)
        if isinstance(old_paths[path], Mapping) and bool(old_paths[path].get("required"))
    )
    type_changes = _type_changes(old_paths, new_paths)
    if removed_required_paths or type_changes:
        classification = "potentially_breaking"
    elif added_paths:
        classification = "additive"
    elif newly_observed_paths:
        classification = "observational_expansion"
    else:
        classification = "unchanged"
    return {
        "schema_version": "gravity-insight.raw-schema-diff.v1",
        "classification": classification,
        "added_paths": added_paths,
        "newly_observed_paths": newly_observed_paths,
        "removed_required_paths": removed_required_paths,
        "type_changes": type_changes,
        "before_fingerprint": before.get("raw_schema_fingerprint"),
        "after_fingerprint": after.get("raw_schema_fingerprint"),
    }


def fingerprint_set(
    *,
    contract_fingerprint: str,
    raw_schema_sketch: Mapping[str, Any],
    projected_fingerprint: str | None,
) -> dict[str, Any]:
    """Keep the three intentionally different fingerprint questions explicit."""

    raw_fingerprint = raw_schema_sketch.get("raw_schema_fingerprint")
    for name, value in (
        ("contract_fingerprint", contract_fingerprint),
        ("raw_schema_fingerprint", raw_fingerprint),
    ):
        if not _safe_fingerprint(value):
            raise ValueError(f"{name} must be a SHA-256 hex digest")
    if projected_fingerprint is not None and not _safe_fingerprint(projected_fingerprint):
        raise ValueError("projected_fingerprint must be a SHA-256 hex digest or null")
    return {
        "contract_fingerprint": contract_fingerprint,
        "raw_schema_fingerprint": raw_fingerprint,
        "projected_fingerprint": projected_fingerprint,
    }


def _safe_fingerprint(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value.casefold())
    )
