from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .io import read_json


def _route_key(item: dict[str, Any]) -> tuple[str, str]:
    return str(item.get("method", "UNKNOWN")), str(item.get("path", ""))


def _extract_method_changes(
    removed: set[tuple[str, str]], added: set[tuple[str, str]]
) -> list[dict[str, Any]]:
    method_changes: list[dict[str, Any]] = []
    for path in sorted({path for _, path in removed} & {path for _, path in added}):
        old_methods = sorted(method for method, item_path in removed if item_path == path)
        new_methods = sorted(method for method, item_path in added if item_path == path)
        if old_methods and new_methods:
            method_changes.append({"path": path, "old_methods": old_methods, "new_methods": new_methods})
            removed -= {(method, path) for method in old_methods}
            added -= {(method, path) for method in new_methods}
    return method_changes


def _path_change_candidates(
    removed: set[tuple[str, str]], added: set[tuple[str, str]]
) -> list[tuple[float, tuple[str, str], tuple[str, str]]]:
    candidates: list[tuple[float, tuple[str, str], tuple[str, str]]] = []
    for old_key in removed:
        for new_key in added:
            if old_key[0] != new_key[0]:
                continue
            old_leaf = old_key[1].rstrip("/").rsplit("/", 1)[-1]
            new_leaf = new_key[1].rstrip("/").rsplit("/", 1)[-1]
            if old_leaf != new_leaf:
                continue
            ratio = SequenceMatcher(None, old_key[1], new_key[1]).ratio()
            if ratio >= 0.72:
                candidates.append((ratio, old_key, new_key))
    return sorted(candidates, key=lambda item: (-item[0], item[1], item[2]))


def _extract_path_changes(
    removed: set[tuple[str, str]], added: set[tuple[str, str]]
) -> list[dict[str, Any]]:
    path_changes: list[dict[str, Any]] = []
    used_old: set[tuple[str, str]] = set()
    used_new: set[tuple[str, str]] = set()
    for ratio, old_key, new_key in _path_change_candidates(removed, added):
        if old_key in used_old or new_key in used_new:
            continue
        used_old.add(old_key)
        used_new.add(new_key)
        path_changes.append(
            {
                "method": old_key[0],
                "old_path": old_key[1],
                "new_path": new_key[1],
                "similarity": round(ratio, 4),
                "certainty": "heuristic",
            }
        )
    removed -= used_old
    added -= used_new
    return path_changes


def _route_rows(keys: set[tuple[str, str]]) -> list[dict[str, str]]:
    return [
        {"method": method, "path": path}
        for method, path in sorted(keys, key=lambda item: (item[1], item[0]))
    ]


def diff_routes(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_map = {_route_key(item): item for item in old.get("routes", [])}
    new_map = {_route_key(item): item for item in new.get("routes", [])}
    removed = set(old_map) - set(new_map)
    added = set(new_map) - set(old_map)
    method_changes = _extract_method_changes(removed, added)
    path_changes = _extract_path_changes(removed, added)
    added_rows = _route_rows(added)
    removed_rows = _route_rows(removed)
    return {
        "schema_version": 1,
        "kind": "route_diff",
        "old_bundle_id": old.get("source", {}).get("bundle_id"),
        "new_bundle_id": new.get("source", {}).get("bundle_id"),
        "old_bundle_complete": bool(old.get("source", {}).get("bundle_complete", False)),
        "new_bundle_complete": bool(new.get("source", {}).get("bundle_complete", False)),
        "summary": {
            "added": len(added_rows),
            "removed": len(removed_rows),
            "method_changed": len(method_changes),
            "path_changed": len(path_changes),
        },
        "added": added_rows,
        "removed": removed_rows,
        "method_changes": method_changes,
        "path_changes": sorted(path_changes, key=lambda item: (item["old_path"], item["method"])),
    }


def diff_snapshots(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    old_files = {str(item.get("url")): item for item in old.get("files", [])}
    new_files = {str(item.get("url")): item for item in new.get("files", [])}
    common = set(old_files) & set(new_files)
    changed = [
        {
            "url": url,
            "old_sha256": old_files[url].get("sha256"),
            "new_sha256": new_files[url].get("sha256"),
        }
        for url in sorted(common)
        if old_files[url].get("sha256") != new_files[url].get("sha256")
    ]
    return {
        "schema_version": 1,
        "kind": "bundle_snapshot_diff",
        "old_bundle_complete": bool(old.get("summary", {}).get("complete", False)),
        "new_bundle_complete": bool(new.get("summary", {}).get("complete", False)),
        "summary": {
            "added_files": len(set(new_files) - set(old_files)),
            "removed_files": len(set(old_files) - set(new_files)),
            "changed_files": len(changed),
        },
        "added_files": sorted(set(new_files) - set(old_files)),
        "removed_files": sorted(set(old_files) - set(new_files)),
        "changed_files": changed,
        "note": "Route method/path changes require routes.json inputs; snapshots only contain static asset identities.",
    }


def diff_files(old_path: Path, new_path: Path) -> dict[str, Any]:
    old = read_json(old_path)
    new = read_json(new_path)
    if isinstance(old, dict) and isinstance(new, dict) and "routes" in old and "routes" in new:
        return diff_routes(old, new)
    if isinstance(old, dict) and isinstance(new, dict) and "files" in old and "files" in new:
        return diff_snapshots(old, new)
    raise ValueError("both inputs must be routes.json files or both must be bundle snapshots")
