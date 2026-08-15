"""Shared paths and value-free JSON helpers for contract probing."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gravity_sdk.paths import (
    CENSUS_DATA_ROOT,
    CONTRACT_ROOT,
    EVIDENCE_ROOT as SDK_EVIDENCE_ROOT,
    STATE_ROOT,
    TMP_ROOT as SDK_TMP_ROOT,
)
from gravity_sdk.result_output import write_rendered_result


REPO_ROOT = STATE_ROOT
COVERAGE_PATH = CENSUS_DATA_ROOT / "coverage.json"
DRAFT_ROOT = CONTRACT_ROOT / "drafts"
OPERATION_ROOT = CONTRACT_ROOT / "operations"
EVIDENCE_ROOT = SDK_EVIDENCE_ROOT / "probe"
TMP_ROOT = SDK_TMP_ROOT / "codex" / "gi-probe-pipeline"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read JSON: {path}") from exc


def iter_json_evidence(
    evidence_root: Path,
    *,
    skipped_files: list[dict[str, str]] | None = None,
) -> Iterator[tuple[Path, Mapping[str, Any]]]:
    """Yield probe evidence while reporting files that cannot be consumed."""

    if not evidence_root.is_dir():
        return
    for path in sorted(evidence_root.glob("*.yaml")):
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            if skipped_files is not None:
                skipped_files.append(
                    {"path": display_path(path), "reason": "unreadable"}
                )
            continue
        try:
            evidence = json.loads(source)
        except json.JSONDecodeError:
            if skipped_files is not None:
                skipped_files.append(
                    {
                        "path": display_path(path),
                        "reason": (
                            "non_json_yaml"
                            if source.lstrip()[:1] not in {"{", "["}
                            else "invalid_json"
                        ),
                    }
                )
            continue
        if not isinstance(evidence, Mapping):
            if skipped_files is not None:
                skipped_files.append(
                    {"path": display_path(path), "reason": "invalid_document_type"}
                )
            continue
        yield path, evidence


def write_json(path: Path, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_rendered_result(str(path), payload)


def display_path(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def canonical_fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
