"""Build CT02 no-code Team Hub packages, evidence artifacts, and exact lock."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile
from typing import Any

from gravity_sdk import __version__
from gravity_sdk.agent_runtime_contracts import canonical_digest, load_json_object
from gravity_sdk.skill_contract import compile_skill_manifest, skill_uri
from gravity_sdk.skill_hub_archive import validate_skill_archive
from gravity_sdk.skill_hub_contract import compile_hub_index, compile_hub_source
from gravity_sdk.skill_hub_locks import build_skills_lock, compile_skills_lock
from gravity_sdk.skill_render import render_package_files, skill_package_descriptor
from gravity_sdk.thinkingai_inventory import load_inventory_snapshot
from gravity_sdk.thinkingai_representative import (
    compile_representative_eval,
    compile_representative_set,
)


ROOT = Path(__file__).resolve().parents[1]
CONTENT_ROOT = ROOT / "content" / "thinkingai" / "representative"
SKILL_ROOT = CONTENT_ROOT / "skills"
HUB_ROOT = CONTENT_ROOT / "hub"
SOURCE_TARGET = HUB_ROOT / "source.json"
INDEX_TARGET = HUB_ROOT / "index.json"
SET_TARGET = HUB_ROOT / "representative-set.json"
EVAL_TARGET = HUB_ROOT / "eval.json"
LOCK_TARGET = CONTENT_ROOT / "lock" / "gravity.skills.lock.json"
_INDEX_REPOSITORY_PATH = "content/thinkingai/representative/hub/index.json"
_ARCHIVE_ROOT = "content/thinkingai/representative/hub/artifacts/skills"
_REVISION = re.compile(r"^[0-9a-f]{40}$")


def render_outputs(source_revision: str | None) -> dict[Path, bytes]:
    source = _hub_source()
    manifests = _manifests()
    entries = []
    archive_outputs: dict[Path, bytes] = {}
    records = []
    for manifest in manifests:
        identity = skill_uri(manifest)
        artifact = {
            "contract": manifest,
            "digest": canonical_digest(manifest),
            "skill_uri": identity,
        }
        package = skill_package_descriptor(artifact)
        archive = _zip(render_package_files(artifact))
        relative = f"{_ARCHIVE_ROOT}/{manifest['skill_id']}-{manifest['version']}.zip"
        archive_digest = hashlib.sha256(archive).hexdigest()
        entries.append(
            {
                "skill_uri": identity,
                "manifest": manifest,
                "package": package,
                "archive": {
                    "path": relative,
                    "sha256": archive_digest,
                    "size_bytes": len(archive),
                    "media_type": "application/vnd.gravity.skill-package.v1+zip",
                },
            }
        )
        archive_outputs[ROOT.joinpath(*relative.split("/"))] = archive
        records.append({"manifest": manifest, "archive_sha256": archive_digest})

    index = compile_hub_index(
        {
            "artifact_kind": "skill_hub_index",
            "schema_version": "gravity.skill-hub-index.v1",
            "index_version": 1,
            "skills": entries,
            "trusted_packs": [],
        },
        runtime_version=__version__,
    )
    for identity, entry in index["skills"].items():
        archive_path = ROOT.joinpath(*entry["archive"]["path"].split("/"))
        validate_skill_archive(archive_outputs[archive_path], entry)

    snapshot = load_inventory_snapshot(
        next(
            (
                ROOT / "src" / "gravity_sdk" / "contracts" / "thinkingai" / "snapshots"
            ).glob("*.json")
        )
    )
    representative_set = compile_representative_set(records, snapshot)
    evaluation = compile_representative_eval(representative_set)
    outputs = {
        SOURCE_TARGET: _json_bytes(source["contract"]),
        INDEX_TARGET: _json_bytes(index["contract"]),
        SET_TARGET: _json_bytes(representative_set),
        EVAL_TARGET: _json_bytes(evaluation),
        **archive_outputs,
    }
    if source_revision is not None:
        if _REVISION.fullmatch(source_revision) is None:
            raise SystemExit("source revision must be one exact lowercase Git SHA")
        reference = {
            "source_id": source["contract"]["source_id"],
            "transport": source["contract"]["transport"],
            "source_descriptor_digest": source["digest"],
            "source_revision": source_revision,
            "index_digest": index["digest"],
        }
        lock = build_skills_lock(
            index,
            reference,
            [entry["skill_uri"] for entry in index["contract"]["skills"]],
            runtime_version=__version__,
        )
        outputs[LOCK_TARGET] = _json_bytes(lock)
    return outputs


def _hub_source() -> dict[str, Any]:
    return compile_hub_source(
        {
            "artifact_kind": "skill_hub_source",
            "schema_version": "gravity.skill-hub-source.v1",
            "source_id": "hub-source://gravity/thinkingai-representative@1",
            "transport": "git",
            "owner": "gravity-content",
            "trust_model": "stage_a_team_controlled_reviewed",
            "git": {
                "repository_uri": "https://github.com/mmm1h/gravity-sdk.git",
                "ref": "refs/heads/dev",
                "index_path": _INDEX_REPOSITORY_PATH,
            },
            "https": None,
            "limits": {
                "max_index_bytes": 1048576,
                "max_artifact_bytes": 4194304,
                "timeout_seconds": 10,
            },
        }
    )


def _manifests() -> list[dict[str, Any]]:
    paths = sorted(SKILL_ROOT.glob("*.json"))
    manifests = [
        compile_skill_manifest(
            load_json_object(path, f"CT02 Skill source {path.name}"),
            label=f"CT02 Skill source {path.name}",
        )
        for path in paths
    ]
    if len(manifests) != 5:
        raise SystemExit("CT02 requires exactly five Skill source manifests")
    return manifests


def _zip(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output, mode="w", compression=zipfile.ZIP_STORED
    ) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    return output.getvalue()


def _json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _locked_revision() -> str:
    lock = compile_skills_lock(
        load_json_object(LOCK_TARGET, "CT02 representative Skill lock")
    )
    return str(lock["source"]["source_revision"])


def _verify_source_revision(revision: str, expected_index: bytes) -> None:
    completed = subprocess.run(
        ["git", "show", f"{revision}:{_INDEX_REPOSITORY_PATH}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    if completed.returncode:
        raise SystemExit("source revision does not contain the generated Hub index")
    if completed.stdout != expected_index:
        raise SystemExit("source revision Hub index does not match generated index")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true")
    group.add_argument("--source-revision")
    group.add_argument("--packages-only", action="store_true")
    options = parser.parse_args()
    revision = _locked_revision() if options.check else options.source_revision
    outputs = render_outputs(revision)
    if revision is not None:
        _verify_source_revision(revision, outputs[INDEX_TARGET])
    mismatched = [
        path
        for path, content in outputs.items()
        if not path.is_file() or path.read_bytes() != content
    ]
    if options.check:
        if mismatched:
            raise SystemExit(
                "generated CT02 representative artifacts are stale: "
                + ", ".join(str(path.relative_to(ROOT)) for path in mismatched)
            )
        print("CT02 representative Hub artifacts are current")
        return 0
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print(f"rendered {len(outputs)} CT02 representative artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
