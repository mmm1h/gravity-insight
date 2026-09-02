"""Build deterministic Runtime and Agent Skill distributions from canonical Skills."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any
import zipfile

from gravity_insight import __version__
from gravity_insight.agent_runtime_contracts import (
    canonical_digest,
    load_json_object,
    validate_schema,
)
from gravity_insight.external_method_registry import (
    SOURCE_REF_PREFIX,
    load_source_registry,
)
from gravity_insight.skill_contract import compile_skill_manifest, skill_uri
from gravity_insight.skill_hub_archive import validate_skill_archive
from gravity_insight.skill_hub_contract import compile_hub_index, compile_hub_source
from gravity_insight.skill_package import SkillPackageError, validate_package_entries
from gravity_insight.skill_render import (
    render_agent_export,
    render_guide,
    render_package_files,
    skill_package_descriptor,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "skills" / "library"
REGISTRY_PATH = ROOT / "skills" / "sources" / "registry.json"
AGENT_INDEX_SCHEMA_PATH = (
    ROOT
    / "src"
    / "gravity_insight"
    / "contracts"
    / "schema"
    / "agent-skill-index-v1.schema.json"
)
DEFAULT_OUTPUT = ROOT / "build" / "skill-hub"
PUBLISH_BASE = (
    "https://github.com/mmm1h/gravity-insight/releases/download/skill-library-v2"
)
_NAMESPACE = re.compile(
    r"^(?:gravity\.(?:core|game)(?:\.[a-z][a-z0-9-]*)*|"
    r"(?:org|project)\.[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)*)$"
)
_ZH_CN = re.compile(r"[\u3400-\u9fff]")
_AGENT_INDEX_SCHEMA = "agent-skill-index-v1.schema.json"
_AGENT_FILES = {
    "SKILL.md",
    "references/GUIDE.md",
    "references/SCHEMA.json",
    "references/CLAIMS.md",
    "references/EXAMPLES.md",
    "references/PROJECT_BINDINGS.json",
}


def load_canonical_skills() -> tuple[dict[str, Any], ...]:
    paths = sorted(SOURCE_ROOT.glob("*.json"))
    manifests = tuple(
        compile_skill_manifest(
            load_json_object(path, f"canonical Skill {path.name}"),
            label=f"canonical Skill {path.name}",
        )
        for path in paths
    )
    if not manifests:
        raise SystemExit("canonical Skill library is empty")
    identities = [skill_uri(manifest) for manifest in manifests]
    if len(identities) != len(set(identities)):
        raise SystemExit("canonical Skill identities must be unique")
    manifests = tuple(sorted(manifests, key=skill_uri))
    _validate_namespaces_and_language(manifests)
    _validate_provenance(manifests)
    return manifests


def render_outputs() -> dict[str, bytes]:
    manifests = load_canonical_skills()
    source_digest = _source_digest()
    outputs: dict[str, bytes] = {}
    entries: list[dict[str, Any]] = []
    agent_entries: list[dict[str, Any]] = []
    archives: dict[str, bytes] = {}
    for manifest in manifests:
        artifact = _artifact(manifest)
        package = skill_package_descriptor(artifact)
        package_files = render_package_files(artifact)
        archive = _zip(package_files)
        stem = f"{manifest['namespace']}.{manifest['skill_id']}-{manifest['version']}"
        archive_path = f"runtime-skill-{stem}.zip"
        entries.append(
            {
                "skill_uri": artifact["skill_uri"],
                "manifest": manifest,
                "package": package,
                "archive": {
                    "path": archive_path,
                    "sha256": hashlib.sha256(archive).hexdigest(),
                    "size_bytes": len(archive),
                    "media_type": "application/vnd.gravity.skill-package.v1+zip",
                },
            }
        )
        archives[archive_path] = archive
        outputs[archive_path] = archive
        outputs[f"docs/{manifest['namespace']}/{manifest['skill_id']}.md"] = (
            render_guide(manifest).encode("utf-8")
        )
        for name, content in package_files.items():
            outputs[f"packages/{manifest['namespace']}.{manifest['skill_id']}/{name}"] = content
        agent_export = render_agent_export(artifact, manifests)
        agent_files = _agent_files(agent_export)
        agent_name = agent_export["name"]
        agent_archive_path = f"agent-skill-{agent_name}.zip"
        agent_archive = _zip(
            {f"{agent_name}/{path}": content for path, content in agent_files.items()}
        )
        agent_entry = _agent_entry(
            manifest,
            artifact,
            agent_export,
            agent_archive_path,
            agent_archive,
        )
        validate_agent_archive(agent_archive, agent_entry)
        agent_entries.append(agent_entry)
        outputs[agent_archive_path] = agent_archive
        for name, content in agent_files.items():
            outputs[f"agent-skills/{agent_name}/{name}"] = content
    index = _hub_index(entries)
    for identity, entry in index["skills"].items():
        validate_skill_archive(archives[entry["archive"]["path"]], entry)
    outputs["index.json"] = _json_bytes(index["contract"])
    outputs["agent-index.json"] = _json_bytes(
        _agent_index(source_digest, agent_entries)
    )
    outputs["agent-skill-index-v1.schema.json"] = AGENT_INDEX_SCHEMA_PATH.read_bytes()
    outputs["source.json"] = _json_bytes(_hub_source(source_digest))
    outputs["build-manifest.json"] = _json_bytes(
        _build_manifest(source_digest, outputs)
    )
    return dict(sorted(outputs.items()))


def _artifact(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract": manifest,
        "digest": canonical_digest(manifest),
        "skill_uri": skill_uri(manifest),
    }


def _hub_index(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return compile_hub_index(
        {
            "artifact_kind": "skill_hub_index",
            "schema_version": "gravity.skill-hub-index.v1",
            "index_version": 1,
            "skills": entries,
            "trusted_packs": [],
        },
        runtime_version=__version__,
    )


def _agent_files(export: dict[str, Any]) -> dict[str, bytes]:
    files = {
        str(item["path"]): str(item["content"]).encode("utf-8")
        for item in export["files"]
    }
    if set(files) != _AGENT_FILES:
        raise SkillPackageError("Agent Skill export file set is invalid")
    validate_package_entries(files, allow_skill_md=True)
    for item in export["files"]:
        content = files[str(item["path"])]
        if (
            item["size_bytes"] != len(content)
            or item["sha256"] != hashlib.sha256(content).hexdigest()
        ):
            raise SkillPackageError("Agent Skill export file metadata drifted")
    return dict(sorted(files.items()))


def _agent_entry(
    manifest: dict[str, Any],
    artifact: dict[str, Any],
    export: dict[str, Any],
    archive_path: str,
    archive: bytes,
) -> dict[str, Any]:
    return {
        "skill_uri": artifact["skill_uri"],
        "name": export["name"],
        "directory": export["directory"],
        "namespace": manifest["namespace"],
        "skill_id": manifest["skill_id"],
        "version": manifest["version"],
        "title": manifest["guide"]["title"],
        "summary": manifest["summary"],
        "lifecycle": manifest["lifecycle"],
        "readiness": manifest["readiness"],
        "validation": manifest["validation"],
        "runtime_requires": manifest["runtime_requires"],
        "manifest_digest": artifact["digest"],
        "package_digest": export["package_digest"],
        "files": [
            {
                "path": item["path"],
                "size_bytes": item["size_bytes"],
                "sha256": item["sha256"],
            }
            for item in export["files"]
        ],
        "archive": {
            "path": archive_path,
            "sha256": hashlib.sha256(archive).hexdigest(),
            "size_bytes": len(archive),
            "media_type": "application/vnd.gravity.agent-skill.v1+zip",
        },
    }


def _agent_index(
    source_digest: str, entries: list[dict[str, Any]]
) -> dict[str, Any]:
    identities = [str(item["skill_uri"]) for item in entries]
    names = [str(item["name"]) for item in entries]
    if identities != sorted(identities) or len(identities) != len(set(identities)):
        raise SkillPackageError("Agent Skill index identities are not unique and sorted")
    if len(names) != len(set(names)):
        raise SkillPackageError("Agent Skill index names are not unique")
    if any(item["name"] != item["directory"] for item in entries):
        raise SkillPackageError("Agent Skill index directory differs from its name")
    result = {
        "artifact_kind": "agent_skill_index",
        "schema_version": "gravity.agent-skill-index.v1",
        "index_version": 1,
        "canonical_source_sha256": source_digest,
        "skills": entries,
    }
    validate_schema(result, _AGENT_INDEX_SCHEMA, "Agent Skill index")
    return result


def validate_agent_archive(archive: bytes, entry: dict[str, Any]) -> None:
    archive_metadata = entry["archive"]
    if (
        archive_metadata["size_bytes"] != len(archive)
        or archive_metadata["sha256"] != hashlib.sha256(archive).hexdigest()
    ):
        raise SkillPackageError("Agent Skill archive metadata drifted")
    expected = {
        f"{entry['directory']}/{item['path']}": item
        for item in entry["files"]
    }
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as selected:
            members = selected.infolist()
            names = [item.filename for item in members]
            if names != sorted(expected) or len(names) != len(set(names)):
                raise SkillPackageError("Agent Skill archive entries are invalid")
            files: dict[str, bytes] = {}
            for member in members:
                path = PurePosixPath(member.filename)
                if (
                    path.is_absolute()
                    or any(part in {"", ".", ".."} for part in path.parts)
                    or not path.parts
                    or path.parts[0] != entry["directory"]
                    or member.is_dir()
                    or member.flag_bits & 0x1
                    or member.date_time != (1980, 1, 1, 0, 0, 0)
                    or member.compress_type != zipfile.ZIP_STORED
                    or member.create_system != 3
                    or member.external_attr >> 16 != 0o100644
                ):
                    raise SkillPackageError("Agent Skill archive member is unsafe")
                content = selected.read(member)
                metadata = expected.get(member.filename)
                if metadata is None or (
                    metadata["size_bytes"] != len(content)
                    or metadata["sha256"] != hashlib.sha256(content).hexdigest()
                ):
                    raise SkillPackageError("Agent Skill archive content drifted")
                files[PurePosixPath(*path.parts[1:]).as_posix()] = content
    except (OSError, zipfile.BadZipFile) as exc:
        raise SkillPackageError("Agent Skill archive is not a valid ZIP") from exc
    validate_package_entries(files, allow_skill_md=True)


def _hub_source(source_digest: str) -> dict[str, Any]:
    compiled = compile_hub_source(
        {
            "artifact_kind": "skill_hub_source",
            "schema_version": "gravity.skill-hub-source.v1",
            "source_id": "hub-source://gravity/skill-library@1",
            "transport": "static_https",
            "owner": "gravity-content",
            "trust_model": "stage_a_team_controlled_reviewed",
            "git": None,
            "https": {
                "index_url": f"{PUBLISH_BASE}/index.json",
                "artifact_base_url": f"{PUBLISH_BASE}/",
                "source_revision": source_digest,
            },
            "limits": {
                "max_index_bytes": 1048576,
                "max_artifact_bytes": 4194304,
                "timeout_seconds": 10,
            },
        }
    )
    return compiled["contract"]


def _build_manifest(source_digest: str, outputs: dict[str, bytes]) -> dict[str, Any]:
    release_assets = {
        path: content
        for path, content in outputs.items()
        if _is_release_asset(path)
    }
    return {
        "artifact_kind": "skill_library_build",
        "schema_version": "gravity.skill-library-build.v2",
        "canonical_source": "skills/library",
        "canonical_source_sha256": source_digest,
        "publish_target": "github_release",
        "publish_base_url": PUBLISH_BASE,
        "files": [
            {
                "path": path,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for path, content in sorted(outputs.items())
        ],
        "release_assets": [
            {
                "path": path,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for path, content in sorted(release_assets.items())
        ],
    }


def _is_release_asset(path: str) -> bool:
    return (
        path
        in {
            "index.json",
            "agent-index.json",
            "agent-skill-index-v1.schema.json",
            "source.json",
        }
        or path.startswith("runtime-skill-")
        or path.startswith("agent-skill-")
    )


def _validate_namespaces_and_language(manifests: tuple[dict[str, Any], ...]) -> None:
    for manifest in manifests:
        if _NAMESPACE.fullmatch(manifest["namespace"]) is None:
            raise SystemExit(f"unsupported neutral namespace: {manifest['namespace']}")
        visible = [
            manifest["summary"],
            manifest["description"],
            manifest["guide"]["title"],
            manifest["guide"]["applicability"],
            manifest["guide"]["context_boundary"],
            *manifest["guide"]["steps"],
        ]
        if any(_ZH_CN.search(text) is None for text in visible):
            raise SystemExit(f"Skill visible method content must default to zh-CN: {skill_uri(manifest)}")


def _validate_provenance(manifests: tuple[dict[str, Any], ...]) -> None:
    registry = load_source_registry(REGISTRY_PATH)
    items = {
        SOURCE_REF_PREFIX + item["opaque_id"]: item
        for item in registry["items"]
    }
    expected = {
        item["future_skill_uri"]
        for item in registry["items"]
        if item["mapping_kind"] == "future_skill"
    }
    actual = {skill_uri(manifest) for manifest in manifests}
    if expected != actual:
        raise SystemExit("future Skill registry and canonical manifests differ")
    for manifest in manifests:
        identity = skill_uri(manifest)
        source = items.get(manifest["provenance"]["source_ref"])
        if source is None or source["future_skill_uri"] != identity:
            raise SystemExit(f"Skill provenance is absent or drifted: {identity}")
        if manifest["provenance"]["authorship"] != "independently_authored":
            raise SystemExit(f"Skill independent authorship is not declared: {identity}")


def _source_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(SOURCE_ROOT.glob("*.json")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _zip(files: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content)
    return output.getvalue()


def _json_bytes(value: Any) -> bytes:
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


def _assert_no_tracked_mirrors() -> None:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    tracked = completed.stdout.decode("utf-8").split("\0")
    legacy_content_root = "content/" + "thinking" + "ai/"
    mirrors = [
        path
        for path in tracked
        if path.casefold().endswith(".zip")
        or path.startswith(legacy_content_root)
    ]
    if mirrors:
        raise SystemExit("generated Skill mirrors are tracked: " + ", ".join(mirrors))


def _write_outputs(output_root: Path, outputs: dict[str, bytes]) -> None:
    for relative, content in outputs.items():
        target = output_root.joinpath(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    options = parser.parse_args(argv)
    first = render_outputs()
    second = render_outputs()
    if first != second:
        raise SystemExit("Skill library build is not deterministic")
    if options.check:
        _assert_no_tracked_mirrors()
        print(
            f"Skill library source is valid and deterministic: skills={len(list(SOURCE_ROOT.glob('*.json')))}, "
            f"outputs={len(first)}, source_sha256={_source_digest()}"
        )
        return 0
    output = options.output_dir
    if not output.is_absolute():
        output = ROOT / output
    _write_outputs(output, first)
    print(f"rendered {len(first)} Skill Hub files under {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
