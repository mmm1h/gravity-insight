from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if __package__:
    from scripts.check_changelog import (
        CHANGELOG_PATH,
        LOCK_PATH,
        PYPROJECT_PATH,
        Section,
        _migration_path,
        _sections,
        _subsection_lines,
        _target_version,
        _version_key,
        validate_changelog,
    )
else:
    sys.path.insert(0, str(ROOT))
    from scripts.check_changelog import (
        CHANGELOG_PATH,
        LOCK_PATH,
        PYPROJECT_PATH,
        Section,
        _migration_path,
        _sections,
        _subsection_lines,
        _target_version,
        _version_key,
        validate_changelog,
    )


OUTPUT_PATH = (
    ROOT
    / "src/gravity_insight/contracts/generated/release-compatibility.v1.json"
)
CONTRACT_SCHEMA = "gravity.release-compatibility.v1"
_BREAKING_HEADING = "### Breaking changes"
_HARD_MARKER = "- **Hard break:**"
_SOFT_MARKER = "- **Soft break:**"
_NONE_MARKER = "- None."
_UNKNOWN_MARKER = "- 未记录。"


class CompatibilityContractError(ValueError):
    """A deterministic release compatibility contract violation."""


def _bullet_entries(lines: Sequence[str]) -> tuple[str, ...]:
    entries: list[list[str]] = []
    for line in lines:
        if line.startswith("- "):
            entries.append([line])
        elif entries and line.strip():
            entries[-1].append(line.strip())
    flattened: list[str] = []
    for parts in entries:
        entry = parts[0]
        for continuation in parts[1:]:
            separator = (
                " "
                if entry[-1].isascii() or continuation[0].isascii()
                else ""
            )
            entry += separator + continuation
        flattened.append(entry)
    return tuple(flattened)


def _break_item(
    *,
    version: str,
    kind: str,
    index: int,
    entry: str,
    marker: str,
    migration_guide: str,
) -> dict[str, str]:
    description = entry.removeprefix(marker).strip()
    if not description:
        raise CompatibilityContractError(
            f"release {version} has an empty {kind.replace('_', ' ')} description"
        )
    return {
        "id": f"{version}-{kind.replace('_', '-')}-{index}",
        "description": description,
        "migration_guide": migration_guide,
    }


def _release(section: Section, target_version: str) -> dict[str, Any]:
    version = target_version if section.label == "Unreleased" else section.label
    migration_guide = _migration_path(section)
    entries = _bullet_entries(_subsection_lines(section, _BREAKING_HEADING))
    hard_entries = [entry for entry in entries if entry.startswith(_HARD_MARKER)]
    soft_entries = [entry for entry in entries if entry.startswith(_SOFT_MARKER)]

    if hard_entries or soft_entries:
        if migration_guide is None:
            raise CompatibilityContractError(
                f"release {version} has breaking entries without a migration guide"
            )
        breaking_status = "breaking"
        status_reason = "breaking_changes_recorded"
    elif len(entries) == 1 and entries[0].startswith(_NONE_MARKER):
        breaking_status = "none"
        status_reason = "explicitly_recorded_none"
    elif len(entries) == 1 and entries[0].startswith(_UNKNOWN_MARKER):
        breaking_status = "unknown"
        status_reason = entries[0].removeprefix("- ").strip()
    else:
        raise CompatibilityContractError(
            f"release {version} has an unsupported breaking-change declaration"
        )

    return {
        "version": version,
        "release_status": (
            "unreleased" if section.label == "Unreleased" else "released"
        ),
        "release_date": section.date,
        "breaking_status": breaking_status,
        "breaking_status_reason": status_reason,
        "hard_breaks": [
            _break_item(
                version=version,
                kind="hard_break",
                index=index,
                entry=entry,
                marker=_HARD_MARKER,
                migration_guide=migration_guide or "",
            )
            for index, entry in enumerate(hard_entries, start=1)
        ],
        "soft_breaks": [
            _break_item(
                version=version,
                kind="soft_break",
                index=index,
                entry=entry,
                marker=_SOFT_MARKER,
                migration_guide=migration_guide or "",
            )
            for index, entry in enumerate(soft_entries, start=1)
        ],
        "migration_guide": migration_guide,
    }


def _compatibility_digest(target_version: str, releases: Sequence[Mapping[str, Any]]) -> str:
    source = json.dumps(
        {"target_version": target_version, "releases": releases},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(source).hexdigest()


def build_release_compatibility(
    *,
    root: Path = ROOT,
    changelog_path: Path = CHANGELOG_PATH,
    pyproject_path: Path = PYPROJECT_PATH,
    lock_path: Path = LOCK_PATH,
) -> dict[str, Any]:
    validate_changelog(
        root=root,
        changelog_path=changelog_path,
        pyproject_path=pyproject_path,
        lock_path=lock_path,
    )
    sections = _sections(changelog_path.read_text(encoding="utf-8"))
    target_version = _target_version(sections[0])
    releases = sorted(
        (_release(section, target_version) for section in sections),
        key=lambda release: _version_key(release["version"]),
    )
    versions = [release["version"] for release in releases]
    if len(versions) != len(set(versions)):
        raise CompatibilityContractError(
            "target release must not duplicate a released changelog version"
        )
    return {
        "schema_version": CONTRACT_SCHEMA,
        "generated_from": {
            "path": "CHANGELOG.md",
            "compatibility_sha256": _compatibility_digest(
                target_version, releases
            ),
        },
        "upgrade_policy": {
            "release_order": "ascending_semver",
            "crossed_release_interval": "from_exclusive_to_inclusive",
            "hard_break_decision": "block",
            "unknown_decision": "manual_review",
            "unlisted_version_decision": "manual_review",
            "downgrade_decision": "manual_review",
            "same_version_decision": "allow",
            "known_no_hard_break_decision": "allow",
        },
        "releases": releases,
    }


def serialize_contract(contract: Mapping[str, Any]) -> str:
    return json.dumps(contract, ensure_ascii=False, indent=2) + "\n"


def check_generated_contract(
    *,
    root: Path = ROOT,
    changelog_path: Path = CHANGELOG_PATH,
    pyproject_path: Path = PYPROJECT_PATH,
    lock_path: Path = LOCK_PATH,
    output_path: Path = OUTPUT_PATH,
) -> dict[str, Any]:
    contract = build_release_compatibility(
        root=root,
        changelog_path=changelog_path,
        pyproject_path=pyproject_path,
        lock_path=lock_path,
    )
    expected = serialize_contract(contract)
    try:
        actual = output_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CompatibilityContractError(
            f"generated contract is missing or unreadable: {output_path}"
        ) from exc
    if actual != expected:
        raise CompatibilityContractError(
            "generated contract is stale: "
            f"{output_path} does not match {changelog_path}; run "
            "scripts/generate_release_compatibility.py"
        )
    return contract


def _resolve(value: str | None, default: Path, root: Path) -> Path:
    if value is None:
        return default if root == ROOT else root / default.relative_to(ROOT)
    path = Path(value)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the packaged release compatibility contract."
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--changelog")
    parser.add_argument("--pyproject")
    parser.add_argument("--lock")
    parser.add_argument("--output")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if the checked-in contract differs from CHANGELOG.md.",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    changelog_path = _resolve(args.changelog, CHANGELOG_PATH, root)
    pyproject_path = _resolve(args.pyproject, PYPROJECT_PATH, root)
    lock_path = _resolve(args.lock, LOCK_PATH, root)
    output_path = _resolve(args.output, OUTPUT_PATH, root)
    try:
        if args.check:
            contract = check_generated_contract(
                root=root,
                changelog_path=changelog_path,
                pyproject_path=pyproject_path,
                lock_path=lock_path,
                output_path=output_path,
            )
            print(
                "PASS release compatibility: "
                f"releases={len(contract['releases'])}, output={output_path}"
            )
            return 0
        contract = build_release_compatibility(
            root=root,
            changelog_path=changelog_path,
            pyproject_path=pyproject_path,
            lock_path=lock_path,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(serialize_contract(contract), encoding="utf-8")
    except (CompatibilityContractError, OSError, UnicodeError, ValueError) as exc:
        print(f"FAIL release compatibility: {exc}", file=sys.stderr)
        return 1
    print(
        "WROTE release compatibility: "
        f"releases={len(contract['releases'])}, output={output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
