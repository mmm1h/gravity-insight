from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
CHANGELOG_PATH = ROOT / "CHANGELOG.md"
PYPROJECT_PATH = ROOT / "pyproject.toml"
LOCK_PATH = ROOT / "scripts/changelog_release_lock.json"
LOCK_SCHEMA = "gravity.changelog-release-lock.v1"

_VERSION_PATTERN = r"(?:0|[1-9]\d*)"
_VERSION_RE = re.compile(
    rf"^(?P<major>{_VERSION_PATTERN})\."
    rf"(?P<minor>{_VERSION_PATTERN})\."
    rf"(?P<patch>{_VERSION_PATTERN})$"
)
_SECTION_RE = re.compile(
    rf"^## \[(?P<label>Unreleased|{_VERSION_PATTERN}\."
    rf"{_VERSION_PATTERN}\.{_VERSION_PATTERN})\]"
    r"(?: - (?P<date>\d{4}-\d{2}-\d{2}))?$"
)
_TARGET_RE = re.compile(
    rf"^Target release: `(?P<version>{_VERSION_PATTERN}\."
    rf"{_VERSION_PATTERN}\.{_VERSION_PATTERN})`$"
)
_MIGRATION_RE = re.compile(r"^Migration guide: \[[^]]+\]\((?P<path>[^)]+)\)$")
_BREAKING_HEADING = "### Breaking changes"
_BREAKING_MARKERS = ("- **Hard break:**", "- **Soft break:**")
_NO_BREAKING_PREFIXES = ("- None.", "- 未记录。")


class ChangelogError(ValueError):
    """A machine-decidable changelog contract violation."""


@dataclass(frozen=True)
class Section:
    label: str
    date: str | None
    lines: tuple[str, ...]

    @property
    def canonical_text(self) -> str:
        return "\n".join(self.lines).rstrip("\n") + "\n"

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.canonical_text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ChangelogReport:
    project_version: str
    target_version: str
    released_versions: tuple[str, ...]
    breaking_entries: int
    migration_guides: int


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repository_head(root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise ChangelogError("cannot bind changelog receipt to repository HEAD")
    return value


def _read_text(path: Path, label: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ChangelogError(f"cannot read {label} at {path}") from exc


def _project_version(path: Path) -> str:
    try:
        with path.open("rb") as stream:
            document = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ChangelogError(f"cannot read project version from {path}") from exc
    project = document.get("project")
    version = project.get("version") if isinstance(project, Mapping) else None
    if not isinstance(version, str) or _VERSION_RE.fullmatch(version) is None:
        raise ChangelogError("project.version must be a three-part SemVer value")
    return version


def _sections(text: str) -> tuple[Section, ...]:
    lines = text.splitlines()
    starts: list[tuple[int, re.Match[str]]] = []
    malformed: list[str] = []
    for index, line in enumerate(lines):
        if not line.startswith("## ["):
            continue
        match = _SECTION_RE.fullmatch(line)
        if match is None:
            malformed.append(line)
        else:
            starts.append((index, match))
    if malformed:
        raise ChangelogError(f"malformed release heading: {malformed[0]}")
    if not starts:
        raise ChangelogError("no release sections were found")
    parsed: list[Section] = []
    for position, (start, match) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        parsed.append(
            Section(
                label=match.group("label"),
                date=match.group("date"),
                lines=tuple(lines[start:end]),
            )
        )
    return tuple(parsed)


def _subsection_lines(section: Section, heading: str) -> tuple[str, ...]:
    heading_indexes = [
        index for index, line in enumerate(section.lines) if line == heading
    ]
    if len(heading_indexes) != 1:
        raise ChangelogError(
            f"[{section.label}] must contain exactly one {heading!r} section"
        )
    start = heading_indexes[0] + 1
    end = next(
        (
            index
            for index in range(start, len(section.lines))
            if section.lines[index].startswith("### ")
        ),
        len(section.lines),
    )
    return tuple(section.lines[start:end])


def _migration_path(section: Section) -> str | None:
    paths = [
        match.group("path")
        for line in section.lines
        if (match := _MIGRATION_RE.fullmatch(line)) is not None
    ]
    if len(paths) > 1:
        raise ChangelogError(f"[{section.label}] has multiple migration guides")
    return paths[0] if paths else None


def _target_version(unreleased: Section) -> str:
    targets = [
        match.group("version")
        for line in unreleased.lines
        if (match := _TARGET_RE.fullmatch(line)) is not None
    ]
    if len(targets) != 1:
        raise ChangelogError(
            "[Unreleased] must contain exactly one `Target release: `x.y.z`` line"
        )
    return targets[0]


def _version_key(value: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(value)
    if match is None:
        raise ChangelogError(f"invalid release version {value!r}")
    return tuple(int(match.group(name)) for name in ("major", "minor", "patch"))


def _load_lock(path: Path) -> Mapping[str, str]:
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ChangelogError(f"cannot read released-section lock at {path}") from exc
    if not isinstance(payload, Mapping) or payload.get("schema_version") != LOCK_SCHEMA:
        raise ChangelogError(f"released-section lock must use {LOCK_SCHEMA}")
    if payload.get("algorithm") != "sha256":
        raise ChangelogError("released-section lock algorithm must be sha256")
    sections = payload.get("sections")
    if not isinstance(sections, Mapping) or not all(
        isinstance(version, str) and isinstance(digest, str)
        for version, digest in sections.items()
    ):
        raise ChangelogError("released-section lock sections must map versions to digests")
    return sections


def _verify_lock(released: Mapping[str, Section], path: Path) -> None:
    locked = _load_lock(path)
    released_versions = set(released)
    locked_versions = set(locked)
    missing = sorted(released_versions - locked_versions, key=_version_key, reverse=True)
    extra = sorted(locked_versions - released_versions, key=_version_key, reverse=True)
    if missing or extra:
        raise ChangelogError(
            "released-section lock inventory mismatch: "
            f"missing={missing or []}, extra={extra or []}"
        )
    for version in sorted(released, key=_version_key, reverse=True):
        expected = locked[version]
        actual = released[version].digest
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ChangelogError(f"released-section lock for {version} is not SHA-256")
        if actual != expected:
            raise ChangelogError(
                f"released section {version} was modified: "
                f"expected sha256 {expected}, got {actual}"
            )


def validate_changelog(
    *,
    root: Path = ROOT,
    changelog_path: Path = CHANGELOG_PATH,
    pyproject_path: Path = PYPROJECT_PATH,
    lock_path: Path = LOCK_PATH,
    verify_lock: bool = True,
) -> ChangelogReport:
    root = root.resolve()
    sections = _sections(_read_text(changelog_path, "CHANGELOG.md"))
    labels = [section.label for section in sections]
    if labels.count("Unreleased") != 1 or labels[0] != "Unreleased":
        raise ChangelogError("[Unreleased] must be the first and only unreleased section")
    if len(labels) != len(set(labels)):
        raise ChangelogError("release section versions must be unique")

    unreleased = sections[0]
    if unreleased.date is not None:
        raise ChangelogError("[Unreleased] must not have a release date")
    target = _target_version(unreleased)
    released: dict[str, Section] = {}
    for section in sections[1:]:
        if section.date is None:
            raise ChangelogError(f"released section {section.label} must have a date")
        released[section.label] = section
    released_order = list(released)
    if released_order != sorted(released_order, key=_version_key, reverse=True):
        raise ChangelogError("released sections must be ordered newest first")

    project_version = _project_version(pyproject_path)
    if project_version != target and project_version not in released:
        raise ChangelogError(
            f"project version {project_version} has no changelog entry; "
            f"[Unreleased] targets {target} and released versions are "
            f"{released_order or []}"
        )

    breaking_entries = 0
    migration_guides = 0
    for section in sections:
        breaking_lines = _subsection_lines(section, _BREAKING_HEADING)
        bullets = [line for line in breaking_lines if line.startswith("- ")]
        if not bullets:
            raise ChangelogError(
                f"[{section.label}] must explicitly list breaking changes or `- None.`"
            )
        placeholders = [
            line for line in bullets if line.startswith(_NO_BREAKING_PREFIXES)
        ]
        marked = [line for line in bullets if line.startswith(_BREAKING_MARKERS)]
        if len(placeholders) == len(bullets):
            if len(bullets) != 1:
                raise ChangelogError(
                    f"[{section.label}] must use one breaking-change placeholder"
                )
        elif len(marked) != len(bullets):
            raise ChangelogError(
                f"[{section.label}] breaking entries must start with "
                "`**Hard break:**` or `**Soft break:**`"
            )
        else:
            breaking_entries += len(marked)
            migration = _migration_path(section)
            if migration is None:
                raise ChangelogError(
                    f"[{section.label}] has breaking changes but no migration guide"
                )
            expected_version = target if section.label == "Unreleased" else section.label
            expected_path = f"docs/migration/{expected_version}.md"
            if migration != expected_path:
                raise ChangelogError(
                    f"[{section.label}] migration guide must be {expected_path}"
                )
            resolved_migration = (root / migration).resolve()
            if not resolved_migration.is_relative_to(root) or not resolved_migration.is_file():
                raise ChangelogError(
                    f"[{section.label}] migration guide does not exist: {migration}"
                )
            migration_guides += 1
        in_breaking_section = False
        for line in section.lines:
            if line.startswith("### "):
                in_breaking_section = line == _BREAKING_HEADING
                continue
            if not in_breaking_section and line.startswith(_BREAKING_MARKERS):
                raise ChangelogError(
                    f"[{section.label}] has a breaking marker outside {_BREAKING_HEADING}"
                )

    if verify_lock:
        _verify_lock(released, lock_path)
    return ChangelogReport(
        project_version=project_version,
        target_version=target,
        released_versions=tuple(released_order),
        breaking_entries=breaking_entries,
        migration_guides=migration_guides,
    )


def release_declaration(
    release_version: str,
    *,
    root: Path = ROOT,
    changelog_path: Path = CHANGELOG_PATH,
    pyproject_path: Path = PYPROJECT_PATH,
    lock_path: Path = LOCK_PATH,
) -> dict[str, Any]:
    if _VERSION_RE.fullmatch(release_version) is None:
        raise ChangelogError(f"invalid release version {release_version!r}")
    report = validate_changelog(
        root=root,
        changelog_path=changelog_path,
        pyproject_path=pyproject_path,
        lock_path=lock_path,
    )
    if report.project_version != release_version:
        raise ChangelogError(
            f"release version {release_version} does not equal project version "
            f"{report.project_version}"
        )
    sections = _sections(_read_text(changelog_path, "CHANGELOG.md"))
    released = next(
        (section for section in sections if section.label == release_version), None
    )
    if released is not None:
        section = released
        section_state = "released"
    elif sections[0].label == "Unreleased" and _target_version(sections[0]) == release_version:
        section = sections[0]
        section_state = "unreleased_target"
    else:
        raise ChangelogError(
            f"release version {release_version} has no matching changelog section"
        )

    breaking_lines = _subsection_lines(section, _BREAKING_HEADING)
    breaking_entries = [
        line for line in breaking_lines if line.startswith(_BREAKING_MARKERS)
    ]
    migration_path = _migration_path(section)
    if breaking_entries:
        if migration_path is None:
            raise ChangelogError(
                f"release version {release_version} has breaking changes but no migration guide"
            )
        migration_file = (root / migration_path).resolve()
        migration = {
            "status": "required_and_present",
            "path": migration_path,
            "sha256": _sha256(migration_file),
        }
    else:
        migration = {"status": "not_required", "path": None, "sha256": None}
    return {
        "schema_version": "gravity.release-changelog.v1",
        "status": "passed",
        "release_version": release_version,
        "project_version": report.project_version,
        "repository_head": _repository_head(root),
        "section": section.label,
        "section_state": section_state,
        "changelog_sha256": _sha256(changelog_path),
        "released_section_lock_sha256": _sha256(lock_path),
        "breaking_change_declaration": (
            "declared" if breaking_entries else "none_declared"
        ),
        "breaking_entries": len(breaking_entries),
        "migration": migration,
    }


def _path(value: str) -> Path:
    return Path(value).resolve()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate changelog coverage, breaking markers, migrations, and locks."
    )
    parser.add_argument("--root", type=_path, default=ROOT)
    parser.add_argument("--changelog", type=_path, default=CHANGELOG_PATH)
    parser.add_argument("--pyproject", type=_path, default=PYPROJECT_PATH)
    parser.add_argument("--lock", type=_path, default=LOCK_PATH)
    parser.add_argument("--release-version")
    parser.add_argument("--receipt", type=_path)
    parser.add_argument(
        "--print-digests",
        action="store_true",
        help="Print canonical released-section digests without checking the lock.",
    )
    args = parser.parse_args(argv)
    try:
        report = validate_changelog(
            root=args.root,
            changelog_path=args.changelog,
            pyproject_path=args.pyproject,
            lock_path=args.lock,
            verify_lock=not args.print_digests,
        )
        if args.print_digests:
            sections = {
                section.label: section.digest
                for section in _sections(_read_text(args.changelog, "CHANGELOG.md"))
                if section.label != "Unreleased"
            }
            print(json.dumps(sections, indent=2, sort_keys=True))
            return 0
        declaration = None
        if args.receipt is not None and args.release_version is None:
            raise ChangelogError("--receipt requires --release-version")
        if args.release_version is not None:
            declaration = release_declaration(
                args.release_version,
                root=args.root,
                changelog_path=args.changelog,
                pyproject_path=args.pyproject,
                lock_path=args.lock,
            )
            if args.receipt is not None:
                args.receipt.parent.mkdir(parents=True, exist_ok=True)
                args.receipt.write_text(
                    json.dumps(declaration, ensure_ascii=False, indent=2, sort_keys=True)
                    + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
    except ChangelogError as exc:
        print(f"FAIL changelog: {exc}", file=sys.stderr)
        return 1
    suffix = ""
    if declaration is not None:
        suffix = (
            f", release_version={declaration['release_version']}, "
            f"section_state={declaration['section_state']}, "
            f"migration={declaration['migration']['status']}"
        )
    print(
        "PASS changelog: "
        f"project_version={report.project_version}, "
        f"target={report.target_version}, "
        f"released={len(report.released_versions)}, "
        f"locked={len(report.released_versions)}, "
        f"breaking_entries={report.breaking_entries}, "
        f"migration_guides={report.migration_guides}{suffix}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
