"""Atomic installation for reviewed Registered SQL Product definitions."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .support.documents import replace_atomic_durable
from .support.process_lock import FileLockTimeout, advisory_file_lock
from .workspace import (
    Workspace,
    WorkspaceError,
    WorkspaceNotConfiguredError,
    _read_workspace_path,
    validate_registered_sql_product_definition,
)


class WorkspaceProductExistsError(WorkspaceError):
    """Raised when registration would replace an existing SQL product."""


def install_registered_sql_product(
    workspace: Workspace,
    name: str,
    definition: Mapping[str, Any],
) -> Workspace:
    """Atomically register one validated product and return verified readback."""

    if workspace.path is None:
        raise WorkspaceNotConfiguredError(
            "registered SQL product installation requires a configured workspace"
        )
    lock_path = workspace.state_root / "locks" / "registered-sql-products.lock"
    try:
        with advisory_file_lock(
            lock_path,
            owner=f"registered SQL product install {workspace.path}",
        ):
            return _install_locked(workspace, name, definition)
    except FileLockTimeout as exc:
        raise WorkspaceError(
            "timed out waiting for another registered SQL product installation"
        ) from exc


def _install_locked(
    workspace: Workspace,
    name: str,
    definition: Mapping[str, Any],
) -> Workspace:
    path = workspace.path
    assert path is not None
    current = _read_workspace_path(path, workspace.state_root)
    if name in current.products:
        raise WorkspaceProductExistsError(
            f"registered SQL product already exists: {name}"
        )
    selected = validate_registered_sql_product_definition(current, name, definition)
    try:
        original = path.read_bytes()
        text = original.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise WorkspaceError(f"cannot stage Gravity workspace {path}: {exc}") from exc
    updated = _append_product(text, name, selected)
    return _commit_product(current, name, selected, original, updated)


def _commit_product(
    current: Workspace,
    name: str,
    definition: Mapping[str, Any],
    original: bytes,
    updated: str,
) -> Workspace:
    path = current.path
    assert path is not None
    try:
        encoded = updated.encode("utf-8")
    except UnicodeError as exc:
        raise WorkspaceError("registered SQL product is not valid UTF-8") from exc
    temporary = _stage_workspace_bytes(path, encoded, "install")
    committed = False
    try:
        staged = _read_workspace_path(temporary, current.state_root)
        _verify_readback(current, staged, name, definition)
        replace_atomic_durable(temporary, path)
        temporary = None
        committed = True
        installed = _read_workspace_path(path, current.state_root)
        _verify_readback(current, installed, name, definition)
        return installed
    except (OSError, WorkspaceError) as exc:
        if committed:
            _rollback_install(current, original)
        raise WorkspaceError(
            f"registered SQL product {name!r} was not installed"
        ) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _rollback_install(previous: Workspace, original: bytes) -> None:
    path = previous.path
    assert path is not None
    temporary = _stage_workspace_bytes(path, original, "rollback")
    try:
        replace_atomic_durable(temporary, path)
        temporary = None
        restored = _read_workspace_path(path, previous.state_root)
        if path.read_bytes() != original or not _same_non_product_content(
            previous, restored
        ) or restored.products != previous.products:
            raise WorkspaceError("workspace rollback readback changed original content")
    except (OSError, WorkspaceError) as rollback_error:
        raise WorkspaceError(
            "registered SQL product readback failed and workspace rollback could not be verified"
        ) from rollback_error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _verify_readback(
    previous: Workspace,
    readback: Workspace,
    name: str,
    definition: Mapping[str, Any],
) -> None:
    expected_products = dict(previous.products)
    expected_products[name] = dict(definition)
    if not _same_non_product_content(previous, readback):
        raise WorkspaceError("registered SQL product install changed unrelated workspace data")
    if readback.products != expected_products:
        raise WorkspaceError("registered SQL product readback did not match staged products")


def _same_non_product_content(left: Workspace, right: Workspace) -> bool:
    return (
        right.apps == left.apps
        and right.defaults == left.defaults
        and right.datasources == left.datasources
        and right.recipes == left.recipes
        and right.plan_recipes == left.plan_recipes
        and right.semantic_context == left.semantic_context
    )


def _append_product(text: str, name: str, definition: Mapping[str, Any]) -> str:
    if text.endswith("\n\n"):
        separator = ""
    elif text.endswith("\n"):
        separator = "\n"
    else:
        separator = "\n\n"
    return text + separator + _render_product(name, definition)


def _render_product(name: str, definition: Mapping[str, Any]) -> str:
    string_fields = (
        "kind",
        "datasource",
        "privacy",
        "sql",
        "contract_version",
        "promotion_source_sha256",
        "review_evidence_sha256",
    )
    list_fields = ("apps", "forbidden_claims", "output_fields")
    lines = [f"[products.{_toml_string(name)}]"]
    lines.extend(
        f"{field} = {_toml_string(definition[field])}" for field in string_fields
    )
    lines.extend(
        f"{field} = [{', '.join(_toml_value(item) for item in definition[field])}]"
        for field in list_fields
    )
    lines.append(f"max_rows = {definition['max_rows']}")
    lines.extend(("", f"[products.{_toml_string(name)}.output_semantics]"))
    semantics = definition["output_semantics"]
    lines.extend(
        f"{_toml_string(field)} = {_toml_string(semantics[field])}"
        for field in definition["output_fields"]
    )
    return "\n".join(lines) + "\n"


def _toml_value(value: Any) -> str:
    if type(value) is int:
        return str(value)
    if isinstance(value, str):
        return _toml_string(value)
    raise WorkspaceError("registered SQL product contains an unsupported TOML value")


def _toml_string(value: Any) -> str:
    if not isinstance(value, str):
        raise WorkspaceError("registered SQL product contains a non-string TOML value")
    return json.dumps(value, ensure_ascii=False)


def _stage_workspace_bytes(path: Path, content: bytes, label: str) -> Path:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.{label}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except OSError as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise WorkspaceError(f"cannot stage Gravity workspace {path}: {exc}") from exc


__all__ = [
    "WorkspaceProductExistsError",
    "install_registered_sql_product",
]
