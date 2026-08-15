"""Audit registered stable response fields without relying on drafts."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


CHECK_NAME = "stable-response-privacy"
REGISTRY_PATH = Path("src/gravity_sdk/governance/stable_privacy_registry.json")
REGISTRY_VERSION = 1

_ARRAY_KEYS = (
    "data_keys",
    "item_keys",
    "numeric_paths",
)
_DIRECT_PERSONAL_COMPACT = frozenset(
    {
        "avatar",
        "email",
        "emailaddress",
        "phone",
        "phonenumber",
        "mobile",
        "mobilephone",
        "idcard",
        "identitycard",
        "realname",
        "username",
        "operatorname",
        "creatorname",
        "openid",
        "wxopenid",
        "wechatopenid",
        "unionid",
        "idfa",
        "idfv",
        "imei",
        "oaid",
        "androidid",
        "caid",
        "caid1",
        "caid2",
        "ip",
        "ipaddress",
        "birthdate",
        "birthday",
        "homeaddress",
        "preciselocation",
    }
)
_PRIVILEGE_COMPACT = frozenset({"isadmin", "issuperuser"})
_CREDENTIAL_COMPACT = frozenset(
    {
        "accesstoken", "authorization", "cookie", "password", "privatekey",
        "refreshtoken", "secret", "sessiontoken", "token",
    }
)
_PERSON_DETAIL_RESOURCES = frozenset(
    {
        "account_user",
        "monetization_detail",
        "order_detail",
        "segment_user_detail",
        "user_detail",
        "user_event",
    }
)
_PERSON_CONTAINERS = frozenset(
    {"authusers", "creator", "member", "members", "share_members", "user"}
)
_DIRECT_ROW_CONTAINERS = frozenset({"list", "total", "user"})


def _leaf(path: str) -> str:
    return path.rsplit(".", 1)[-1].replace("[]", "").replace("**", "")


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


def _list_root(operation: Mapping[str, Any]) -> str:
    projection = operation.get("response_projection", {})
    if isinstance(projection, Mapping) and projection.get("data_shape") == "list":
        return "data[]"
    pagination = operation.get("pagination", {})
    list_path = pagination.get("list_path") if isinstance(pagination, Mapping) else None
    if isinstance(list_path, str) and list_path:
        return list_path + "[]"
    data_keys = projection.get("data_keys", []) if isinstance(projection, Mapping) else []
    if isinstance(data_keys, list) and "list" in data_keys:
        return "data.list[]"
    return "data[]"


def _append_children(paths: set[str], children_by_parent: Mapping[str, Any]) -> None:
    for _ in range(8):
        added: set[str] = set()
        for parent, children in children_by_parent.items():
            if not isinstance(children, list):
                continue
            parent_paths = [path for path in paths if _leaf(path) == str(parent)]
            for parent_path in parent_paths:
                added.update(f"{parent_path}.{child}" for child in children)
        added -= paths
        if not added:
            return
        paths.update(added)


def operation_exposure_paths(operation: Mapping[str, Any]) -> set[str]:
    """Return exact static paths plus markers for non-static projection surfaces."""

    projection = operation.get("response_projection", {})
    if not isinstance(projection, Mapping):
        return set()
    paths: set[str] = set()
    for value in projection.get("data_keys", []):
        paths.add(f"data.{value}")
    list_root = _list_root(operation)
    for value in projection.get("item_keys", []):
        paths.add(f"{list_root}.{value}")
    for value in projection.get("numeric_paths", []):
        normalized = str(value).replace(".[].", "[].").replace(".[]", "[]")
        paths.add(normalized if normalized.startswith("data") else f"data.{normalized}")
    for data_key, children in projection.get("data_item_keys", {}).items():
        if isinstance(children, list):
            paths.update(f"data.{data_key}[].{child}" for child in children)
    for data_path, children in projection.get("data_path_item_keys", {}).items():
        if isinstance(children, list):
            paths.update(f"data.{data_path}[].{child}" for child in children)
    nested = projection.get("nested_item_keys", {})
    if isinstance(nested, Mapping):
        _append_children(paths, nested)
    recursive = projection.get("recursive_data_item_keys", {})
    if isinstance(recursive, Mapping):
        for data_key, children in recursive.items():
            paths.add(f"@recursive:data.{data_key}")
            if isinstance(children, list):
                paths.update(f"data.{data_key}.**.{child}" for child in children)
    for field in projection.get("opaque_json_item_keys", []):
        matching = sorted(path for path in paths if _leaf(path) == str(field))
        paths.update(f"@opaque:{path}" for path in matching or [f"{list_root}.{field}"])
    for input_name in projection.get("dynamic_item_fields", []):
        paths.add(f"@dynamic:item:{input_name}")
    for input_name in projection.get("numeric_suffix_item_fields", []):
        paths.add(f"@dynamic-numeric:item:{input_name}")
    data_dynamic = projection.get("data_dynamic_item_fields", {})
    if isinstance(data_dynamic, Mapping):
        for data_key, input_names in data_dynamic.items():
            if isinstance(input_names, list):
                paths.update(
                    f"@dynamic:data:{data_key}:{input_name}"
                    for input_name in input_names
                )
    data_numeric = projection.get("data_numeric_suffix_item_fields", {})
    if isinstance(data_numeric, Mapping):
        for data_key, input_names in data_numeric.items():
            if isinstance(input_names, list):
                paths.update(
                    f"@dynamic-numeric:data:{data_key}:{input_name}"
                    for input_name in input_names
                )
    return paths


def _person_name_context(operation: Mapping[str, Any], path: str) -> bool:
    leaf = _leaf(path).casefold()
    if leaf not in {"name", "uname"}:
        return False
    segments = [part.replace("[]", "").casefold() for part in path.split(".")]
    parent = segments[-2] if len(segments) > 1 else ""
    if parent in _PERSON_CONTAINERS:
        return True
    return (
        str(operation.get("resource", "")) in _PERSON_DETAIL_RESOURCES
        and parent in _DIRECT_ROW_CONTAINERS
    )


def suspected_personal_reason(
    operation: Mapping[str, Any], path: str
) -> str | None:
    """Classify high-confidence personal or privilege fields by path and context."""

    if path.startswith("@"):
        return None
    leaf = _leaf(path)
    compact = _compact(leaf)
    if compact in _PRIVILEGE_COMPACT:
        return "privileged_account_marker"
    if leaf == "DeviceId" and ".device[]" in path:
        return "persistent_device_identifier"
    if compact in _DIRECT_PERSONAL_COMPACT:
        if compact in {"idfa", "idfv", "imei", "oaid", "androidid", "caid", "caid1", "caid2"}:
            return "persistent_device_identifier"
        return "direct_personal_identifier"
    normalized = leaf.casefold().replace("-", "_")
    if normalized.endswith(("_email", "_phone", "_mobile", "_avatar")):
        return "direct_personal_identifier"
    if _person_name_context(operation, path):
        return "person_name_context"
    return None


def _stable_operations(root: Path) -> dict[str, Mapping[str, Any]]:
    operations: dict[str, Mapping[str, Any]] = {}
    contract_root = root / "src/gravity_sdk/contracts/operations"
    for path in sorted(contract_root.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        operation = document.get("operation", {})
        if not isinstance(operation, Mapping) or operation.get("stability") != "stable":
            continue
        operation_id = str(operation.get("operation_id", path.stem))
        operations[operation_id] = operation
    return operations


def registry_payload(root: Path) -> dict[str, Any]:
    reviewed = {
        operation_id: sorted(operation_exposure_paths(operation))
        for operation_id, operation in sorted(_stable_operations(root).items())
    }
    return {
        "schema_version": REGISTRY_VERSION,
        "purpose": "Explicit review ledger for every stable response projection surface; not a non-sensitive classification.",
        "reviewed_exposures": reviewed,
    }


def render_registry(root: Path) -> str:
    return json.dumps(registry_payload(root), ensure_ascii=False, indent=2) + "\n"


def _load_registry(root: Path) -> tuple[dict[str, set[str]], list[str]]:
    path = root / REGISTRY_PATH
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, [f"{CHECK_NAME}: cannot load {REGISTRY_PATH.as_posix()}: {exc}"]
    if document.get("schema_version") != REGISTRY_VERSION:
        return {}, [f"{CHECK_NAME}: registry schema_version must be {REGISTRY_VERSION}"]
    raw = document.get("reviewed_exposures")
    if not isinstance(raw, Mapping):
        return {}, [f"{CHECK_NAME}: reviewed_exposures must be an object"]
    reviewed: dict[str, set[str]] = {}
    errors: list[str] = []
    for operation_id, values in raw.items():
        if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
            errors.append(f"{CHECK_NAME}: registry entry {operation_id!r} must be a string array")
            continue
        if values != sorted(set(values)):
            errors.append(f"{CHECK_NAME}: registry entry {operation_id!r} must be sorted and unique")
        reviewed[str(operation_id)] = set(values)
    return reviewed, errors


def inspect_stable_response_privacy(root: Path) -> list[str]:
    operations = _stable_operations(root)
    reviewed, errors = _load_registry(root)
    if errors:
        return errors
    for operation_id in sorted(set(operations) | set(reviewed)):
        current = operation_exposure_paths(operations[operation_id]) if operation_id in operations else set()
        approved = reviewed.get(operation_id, set())
        for path in sorted(current - approved):
            errors.append(
                f"{CHECK_NAME}: {operation_id} exposes unreviewed field {path!r}; "
                "review its contract and update the stable registry"
            )
        for path in sorted(approved - current):
            errors.append(
                f"{CHECK_NAME}: stale registry field {operation_id} {path!r}; "
                "tighten the stable registry"
            )
        operation = operations.get(operation_id)
        if operation is None:
            continue
        for path in sorted(current):
            compact = _compact(_leaf(path))
            if compact in _CREDENTIAL_COMPACT or any(
                compact.endswith(suffix) for suffix in _CREDENTIAL_COMPACT
            ):
                errors.append(
                    f"{CHECK_NAME}: {operation_id} exposes credential field {path!r}"
                )
    return errors


def validate(root: Path) -> list[str]:
    return inspect_stable_response_privacy(root)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "registry"))
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "registry":
        rendered = render_registry(root)
        if args.write:
            target = root / REGISTRY_PATH
            target.write_text(rendered, encoding="utf-8", newline="\n")
        else:
            print(rendered, end="")
        return 0
    errors = inspect_stable_response_privacy(root)
    for error in errors:
        print(error)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
