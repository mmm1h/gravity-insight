"""Offline checks that bind an installed CLI to its intended source tree."""

from __future__ import annotations

import json
import os
import re
import tomllib
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit
from urllib.request import url2pathname


_DISTRIBUTION_NAME = "gravity-insight"
_PACKAGE_DIRECTORY = Path("src") / "gravity_sdk"
_SCHEMA_VERSION = "gravity-sdk.install-consistency.v1"


def inspect_install_consistency() -> dict[str, Any]:
    """Inspect local metadata, source version, and the imported package path."""

    import gravity_sdk

    package_path = Path(str(gravity_sdk.__file__)).resolve()
    records = _distribution_records()
    source = _find_project(Path.cwd())
    source_origin = "working_directory"
    if source is None:
        source = _find_project(package_path.parent)
        source_origin = "import_path"
    if source is None and len(records) == 1 and records[0].get("project_root"):
        source = _project_at(Path(str(records[0]["project_root"])))
        source_origin = "editable_metadata"
    if source is not None:
        source = {**source, "origin": source_origin}
    imported = {
        "path": str(package_path),
        "version": str(getattr(gravity_sdk, "__version__", "")),
    }
    return assess_install_consistency(records, source, imported)


def assess_install_consistency(
    records: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any] | None,
    imported: Mapping[str, Any],
) -> dict[str, Any]:
    """Return one deterministic diagnostic from already collected observations."""

    metadata_records = [dict(item) for item in records]
    source_record = dict(source) if source is not None else None
    import_record = dict(imported)
    mismatches = _mismatches(metadata_records, source_record, import_record)
    reason_code = mismatches[0] if mismatches else "INSTALL_CONSISTENT"
    result: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "status": "fail" if mismatches else "pass",
        "reason_code": reason_code,
        "network_called": False,
        "mismatches": mismatches,
        "metadata": metadata_records,
        "source": source_record,
        "import": import_record,
    }
    if mismatches:
        commands = _reinstall_commands(source_record)
        result.update(
            {
                "message": _reason_message(reason_code),
                "next_action": (
                    "Activate the intended checkout's virtual environment, run "
                    "reinstall_commands in order, and do not use this SDK until "
                    "the recheck passes."
                ),
                "reinstall_commands": commands,
            }
        )
    return result


def _mismatches(
    records: Sequence[Mapping[str, Any]],
    source: Mapping[str, Any] | None,
    imported: Mapping[str, Any],
) -> list[str]:
    if not records:
        return ["INSTALL_METADATA_MISSING"]
    if len(records) != 1:
        return ["INSTALL_METADATA_AMBIGUOUS"]

    record = records[0]
    mismatches = (
        ["INSTALL_METADATA_INVALID"]
        if record.get("direct_url_valid") is False
        else []
    )
    mismatches.extend(_version_mismatches(record, source, imported))
    mismatches.extend(_source_mismatches(record, source, imported))
    return list(dict.fromkeys(mismatches))


def _version_mismatches(
    record: Mapping[str, Any],
    source: Mapping[str, Any] | None,
    imported: Mapping[str, Any],
) -> list[str]:
    metadata_version = str(record.get("version", ""))
    import_version = str(imported.get("version", ""))
    checks = [
        (import_version != metadata_version, "INSTALL_IMPORT_VERSION_MISMATCH")
    ]
    if source is not None:
        source_version = str(source.get("version", ""))
        checks.extend(
            [
                (
                    metadata_version != source_version,
                    "INSTALL_METADATA_VERSION_MISMATCH",
                ),
                (import_version != source_version, "INSTALL_IMPORT_VERSION_MISMATCH"),
            ]
        )
    return [code for failed, code in checks if failed]


def _source_mismatches(
    record: Mapping[str, Any],
    source: Mapping[str, Any] | None,
    imported: Mapping[str, Any],
) -> list[str]:
    editable = bool(record.get("editable"))
    metadata_root = record.get("project_root")
    if source is None:
        return ["INSTALL_SOURCE_MISSING"] if editable else []
    import_root = Path(str(imported.get("path"))).parent
    source_root = source.get("project_root")
    checks = [
        (not editable, "INSTALL_METADATA_NOT_EDITABLE"),
        (editable and not metadata_root, "INSTALL_METADATA_INVALID"),
        (
            bool(metadata_root) and not _same_path(metadata_root, source_root),
            "INSTALL_EDITABLE_ROOT_MISMATCH",
        ),
        (
            not _same_path(import_root, Path(str(source_root)) / _PACKAGE_DIRECTORY),
            "INSTALL_IMPORT_ROOT_MISMATCH",
        ),
        (
            editable
            and bool(metadata_root)
            and not _same_path(
                import_root, Path(str(metadata_root)) / _PACKAGE_DIRECTORY
            ),
            "INSTALL_IMPORT_ROOT_MISMATCH",
        ),
    ]
    return [code for failed, code in checks if failed]


def _distribution_records() -> list[dict[str, Any]]:
    discovered: list[tuple[dict[str, Any], bool]] = []
    for distribution in metadata.distributions(name=_DISTRIBUTION_NAME):
        name = str(distribution.metadata.get("Name", ""))
        if _canonical_name(name) != _DISTRIBUTION_NAME:
            continue
        direct_url, valid = _direct_url(distribution.read_text("direct_url.json"))
        directory_info = direct_url.get("dir_info", {}) if direct_url else {}
        editable = bool(
            isinstance(directory_info, Mapping) and directory_info.get("editable")
        )
        project_root = _file_url_path(direct_url.get("url")) if direct_url else None
        metadata_path = Path(str(getattr(distribution, "_path", ""))).resolve()
        record = {
            "version": str(distribution.version),
            "editable": editable,
            "project_root": str(project_root) if project_root is not None else None,
            "direct_url_valid": valid,
            "metadata_path": str(metadata_path),
        }
        discovered.append((record, metadata_path.name.endswith(".dist-info")))

    # setuptools editable installs expose both the installed dist-info and a
    # source-tree egg-info. The latter is a build companion, not a second install.
    if any(is_dist_info for _, is_dist_info in discovered):
        discovered = [item for item in discovered if item[1]]
    records: list[dict[str, Any]] = []
    identities: set[tuple[str, bool, str | None, bool, str]] = set()
    for record, _ in discovered:
        identity = (
            record["version"],
            bool(record["editable"]),
            record["project_root"],
            bool(record["direct_url_valid"]),
            os.path.normcase(record["metadata_path"]),
        )
        if identity not in identities:
            identities.add(identity)
            records.append(record)
    return sorted(
        records,
        key=lambda item: (
            item["version"],
            item["project_root"] or "",
            item["metadata_path"],
        ),
    )


def _direct_url(raw: str | None) -> tuple[Mapping[str, Any] | None, bool]:
    if raw is None:
        return None, True
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None, False
    return (value, True) if isinstance(value, Mapping) else (None, False)


def _file_url_path(value: Any) -> Path | None:
    if not isinstance(value, str):
        return None
    parsed = urlsplit(value)
    if parsed.scheme.casefold() != "file":
        return None
    path = url2pathname(parsed.path)
    if parsed.netloc and parsed.netloc.casefold() != "localhost":
        path = f"//{parsed.netloc}{path}"
    return Path(path).resolve()


def _find_project(start: Path) -> dict[str, str] | None:
    current = start if start.is_dir() else start.parent
    for root in (current, *current.parents):
        project = _project_at(root)
        if project is not None:
            return project
    return None


def _project_at(root: Path) -> dict[str, str] | None:
    path = root / "pyproject.toml"
    if not path.is_file():
        return None
    try:
        project = tomllib.loads(path.read_text(encoding="utf-8")).get("project", {})
    except (OSError, tomllib.TOMLDecodeError):
        return None
    if (
        not isinstance(project, Mapping)
        or _canonical_name(project.get("name")) != _DISTRIBUTION_NAME
    ):
        return None
    version = project.get("version")
    if not isinstance(version, str) or not version.strip():
        return None
    return {"project_root": str(root.resolve()), "version": version.strip()}


def _same_path(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    left_path, right_path = Path(str(left)), Path(str(right))
    try:
        return left_path.samefile(right_path)
    except OSError:
        return os.path.normcase(str(left_path.resolve())) == os.path.normcase(
            str(right_path.resolve())
        )


def _canonical_name(value: Any) -> str:
    return re.sub(r"[-_.]+", "-", str(value).strip().casefold())


def _reinstall_commands(source: Mapping[str, Any] | None) -> list[str]:
    root = str(source.get("project_root")) if source else "<gravity-sdk-checkout>"
    return [
        "python -m pip uninstall gravity-insight -y",
        f'python -m pip install -e "{root}"',
        "python -m gravity_sdk doctor",
    ]


def _reason_message(reason_code: str) -> str:
    return {
        "INSTALL_METADATA_MISSING": (
            "No gravity-insight distribution metadata is visible to the active "
            "Python interpreter."
        ),
        "INSTALL_METADATA_AMBIGUOUS": (
            "Multiple conflicting gravity-insight distribution metadata records "
            "are visible."
        ),
        "INSTALL_METADATA_INVALID": (
            "The gravity-insight editable-install metadata is invalid or incomplete."
        ),
        "INSTALL_METADATA_VERSION_MISMATCH": (
            "The installed metadata version differs from the current source version."
        ),
        "INSTALL_IMPORT_VERSION_MISMATCH": (
            "The imported gravity_sdk version differs from its metadata or "
            "current source."
        ),
        "INSTALL_METADATA_NOT_EDITABLE": (
            "A source checkout is active but gravity-insight is not installed "
            "editable from it."
        ),
        "INSTALL_EDITABLE_ROOT_MISMATCH": (
            "Editable metadata points at a different Gravity SDK checkout."
        ),
        "INSTALL_IMPORT_ROOT_MISMATCH": (
            "gravity_sdk was imported from a different checkout than the "
            "current editable source."
        ),
        "INSTALL_SOURCE_MISSING": (
            "Editable metadata points at a source tree without a readable "
            "Gravity SDK pyproject.toml."
        ),
    }[reason_code]


__all__ = ["assess_install_consistency", "inspect_install_consistency"]
