"""Build CT03 full no-code Skill packages, coverage, eval, and exact lock."""

from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile
from typing import Any

from gravity_sdk import __version__
from gravity_sdk.agent_runtime_contracts import load_json_object
from gravity_sdk.skill_contract import skill_uri
from gravity_sdk.skill_hub_archive import validate_skill_archive
from gravity_sdk.skill_hub_contract import compile_hub_index, compile_hub_source
from gravity_sdk.skill_hub_locks import build_skills_lock, compile_skills_lock
from gravity_sdk.skill_render import render_package_files, skill_package_descriptor
from gravity_sdk.thinkingai_full_specification import (
    compile_full_source,
    compile_full_specification,
    full_source_manifests,
)
from gravity_sdk.thinkingai_full_eval import compile_full_eval
from gravity_sdk.thinkingai_inventory import load_inventory_snapshot
from gravity_sdk.thinkingai_representative import (
    validate_representative_eval,
    validate_representative_set,
)
from gravity_sdk.agent_runtime_contracts import canonical_digest


ROOT = Path(__file__).resolve().parents[1]
CONTENT_ROOT = ROOT / "content" / "thinkingai" / "full"
SOURCE_INPUT = CONTENT_ROOT / "specifications.json"
SKILL_ROOT = CONTENT_ROOT / "skills"
HUB_ROOT = CONTENT_ROOT / "hub"
SOURCE_TARGET = HUB_ROOT / "source.json"
INDEX_TARGET = HUB_ROOT / "index.json"
SPECIFICATION_TARGET = HUB_ROOT / "full-specification.json"
EVAL_TARGET = HUB_ROOT / "eval.json"
LOCK_TARGET = CONTENT_ROOT / "lock" / "gravity.skills.lock.json"
REPRESENTATIVE_ROOT = ROOT / "content" / "thinkingai" / "representative" / "hub"
REPRESENTATIVE_INDEX = REPRESENTATIVE_ROOT / "index.json"
REPRESENTATIVE_SET = REPRESENTATIVE_ROOT / "representative-set.json"
REPRESENTATIVE_EVAL = REPRESENTATIVE_ROOT / "eval.json"
_INDEX_REPOSITORY_PATH = "content/thinkingai/full/hub/index.json"
_ARCHIVE_ROOT = "content/thinkingai/full/hub/artifacts/skills"
_REVISION = re.compile(r"^[0-9a-f]{40}$")


def render_outputs(source_revision: str | None) -> dict[Path, bytes]:
    snapshot = _snapshot()
    representative_set = validate_representative_set(
        load_json_object(REPRESENTATIVE_SET, "CT02 representative set")
    )
    representative_eval = validate_representative_eval(
        load_json_object(REPRESENTATIVE_EVAL, "CT02 representative eval")
    )
    source_value = load_json_object(SOURCE_INPUT, "CT03 full specification source")
    compile_full_source(source_value, snapshot, representative_set)
    manifests = full_source_manifests(source_value, snapshot, representative_set)
    source = _hub_source()

    representative_index = compile_hub_index(
        load_json_object(REPRESENTATIVE_INDEX, "CT02 representative Hub index"),
        runtime_version=__version__,
    )
    entries = copy.deepcopy(representative_index["contract"]["skills"])
    archive_outputs: dict[Path, bytes] = {}
    manifest_outputs: dict[Path, bytes] = {}
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
        manifest_outputs[SKILL_ROOT / f"{manifest['skill_id']}.json"] = _json_bytes(
            manifest
        )

    index = compile_hub_index(
        {
            "artifact_kind": "skill_hub_index",
            "schema_version": "gravity.skill-hub-index.v1",
            "index_version": 1,
            "skills": sorted(entries, key=lambda item: item["skill_uri"]),
            "trusted_packs": [],
        },
        runtime_version=__version__,
    )
    for identity, entry in index["skills"].items():
        archive_path = ROOT.joinpath(*entry["archive"]["path"].split("/"))
        content = archive_outputs.get(archive_path)
        if content is None:
            content = archive_path.read_bytes()
        validate_skill_archive(content, entry)

    specification = compile_full_specification(
        source_value, snapshot, representative_set, index
    )
    evaluation = compile_full_eval(specification, representative_eval)
    outputs = {
        SOURCE_TARGET: _json_bytes(source["contract"]),
        INDEX_TARGET: _json_bytes(index["contract"]),
        SPECIFICATION_TARGET: _json_bytes(specification),
        EVAL_TARGET: _json_bytes(evaluation),
        **manifest_outputs,
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


def _snapshot() -> dict[str, Any]:
    paths = sorted(
        (ROOT / "src" / "gravity_sdk" / "contracts" / "thinkingai" / "snapshots").glob(
            "*.json"
        )
    )
    if len(paths) != 1:
        raise SystemExit("CT03 requires one exact CT01 source snapshot")
    return load_inventory_snapshot(paths[0])


def _hub_source() -> dict[str, Any]:
    return compile_hub_source(
        {
            "artifact_kind": "skill_hub_source",
            "schema_version": "gravity.skill-hub-source.v1",
            "source_id": "hub-source://gravity/thinkingai-full@1",
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
                "max_index_bytes": 4194304,
                "max_artifact_bytes": 4194304,
                "timeout_seconds": 10,
            },
        }
    )


def _zip(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(
        output, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
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
        load_json_object(LOCK_TARGET, "CT03 full Skill lock")
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
        raise SystemExit("source revision does not contain the generated full Hub index")
    if completed.stdout != expected_index:
        raise SystemExit("source revision full Hub index does not match generated index")


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
                "generated CT03 full specification artifacts are stale: "
                + ", ".join(str(path.relative_to(ROOT)) for path in mismatched)
            )
        print("CT03 full specification artifacts are current")
        return 0
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print(f"rendered {len(outputs)} CT03 full specification artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
