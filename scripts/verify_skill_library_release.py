from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from gravity_insight import __version__
from gravity_insight.compiler import ContractError, JsonSchemaValidator
from gravity_insight.skill_hub_archive import validate_skill_archive
from gravity_insight.skill_hub_contract import compile_hub_index, compile_hub_source

try:
    from generate_skill_library import PUBLISH_BASE, validate_agent_archive
except ModuleNotFoundError:  # Imported as scripts.verify_skill_library_release.
    from scripts.generate_skill_library import PUBLISH_BASE, validate_agent_archive


ROOT = Path(__file__).resolve().parents[1]
RELEASE_TAG = "skill-library-v2"
MANIFEST_NAME = "build-manifest.json"
_MANIFEST_LIMIT = 1_048_576
_ASSET_LIMIT = 4_194_304
_TOTAL_LIMIT = 67_108_864
_CORE_ASSETS = {
    "agent-index.json",
    "agent-skill-index-v1.schema.json",
    "index.json",
    "source.json",
}
_DOWNLOAD_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}
_Fetch = Callable[[str, int], bytes]


class SkillLibraryReleaseError(ValueError):
    """The published Skill Library is missing, drifted, or unsafe."""


def verify_release(fetch: _Fetch | None = None) -> dict[str, Any]:
    selected_fetch = fetch or _download
    network_called = fetch is None
    manifest_bytes = selected_fetch(
        f"{PUBLISH_BASE}/{MANIFEST_NAME}", _MANIFEST_LIMIT
    )
    manifest = _json_object(manifest_bytes, "build manifest")
    rows = _release_rows(manifest)
    downloaded: dict[str, bytes] = {}
    total = 0
    with tempfile.TemporaryDirectory(prefix="gravity-skill-release-readback-") as raw:
        outside_root = Path(raw).resolve()
        if outside_root == ROOT or ROOT in outside_root.parents:
            raise SkillLibraryReleaseError(
                "external readback directory is inside the source checkout"
            )
        for path, row in rows.items():
            content = selected_fetch(
                f"{PUBLISH_BASE}/{quote(path, safe='')}",
                min(_ASSET_LIMIT, row["size_bytes"] + 1),
            )
            if (
                len(content) != row["size_bytes"]
                or hashlib.sha256(content).hexdigest() != row["sha256"]
            ):
                raise SkillLibraryReleaseError(
                    f"published asset size or digest changed: {path}"
                )
            total += len(content)
            if total > _TOTAL_LIMIT:
                raise SkillLibraryReleaseError(
                    "published asset set exceeds the readback byte budget"
                )
            target = outside_root / path
            target.write_bytes(content)
            downloaded[path] = target.read_bytes()
        result = _validate_downloaded(manifest, downloaded)
    return {
        "schema_version": "gravity.skill-library-release-readback.v1",
        "status": "passed",
        "release_tag": RELEASE_TAG,
        "release_base_url": PUBLISH_BASE,
        "canonical_source_sha256": manifest["canonical_source_sha256"],
        "build_manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "release_asset_count": len(rows) + 1,
        "receipt_bound_asset_count": len(rows),
        "downloaded_bytes": total + len(manifest_bytes),
        "runtime_archive_count": result["runtime_archive_count"],
        "agent_archive_count": result["agent_archive_count"],
        "validated_outside_checkout": True,
        "network_called": network_called,
    }


def _release_rows(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if set(manifest) != {
        "artifact_kind",
        "schema_version",
        "canonical_source",
        "canonical_source_sha256",
        "publish_target",
        "publish_base_url",
        "files",
        "release_assets",
    } or (
        manifest.get("artifact_kind") != "skill_library_build"
        or manifest.get("schema_version") != "gravity.skill-library-build.v2"
        or manifest.get("publish_target") != "github_release"
        or manifest.get("publish_base_url") != PUBLISH_BASE
    ):
        raise SkillLibraryReleaseError("published build manifest is unsupported")
    raw_rows = manifest.get("release_assets")
    if not isinstance(raw_rows, list) or len(raw_rows) != 90:
        raise SkillLibraryReleaseError(
            "published build manifest must bind exactly 90 assets"
        )
    rows: dict[str, dict[str, Any]] = {}
    for position, raw in enumerate(raw_rows):
        if not isinstance(raw, Mapping) or set(raw) != {
            "path",
            "size_bytes",
            "sha256",
        }:
            raise SkillLibraryReleaseError(
                f"release_assets[{position}] is invalid"
            )
        path = raw.get("path")
        size = raw.get("size_bytes")
        digest = raw.get("sha256")
        if (
            not isinstance(path, str)
            or PurePosixPath(path).name != path
            or path in rows
            or path == MANIFEST_NAME
            or type(size) is not int
            or not 0 < size <= _ASSET_LIMIT
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise SkillLibraryReleaseError(
                f"release_assets[{position}] metadata is invalid"
            )
        rows[path] = {"size_bytes": size, "sha256": digest}
    if list(rows) != sorted(rows):
        raise SkillLibraryReleaseError("release asset rows are not sorted")
    return rows


def _validate_downloaded(
    manifest: Mapping[str, Any], downloaded: Mapping[str, bytes]
) -> dict[str, int]:
    runtime_index = _json_object(downloaded["index.json"], "Runtime index")
    compiled_index = compile_hub_index(
        runtime_index, runtime_version=__version__
    )["contract"]
    source = compile_hub_source(
        _json_object(downloaded["source.json"], "Hub source")
    )["contract"]
    agent_index = _json_object(downloaded["agent-index.json"], "Agent index")
    agent_schema = _json_object(
        downloaded["agent-skill-index-v1.schema.json"], "Agent index schema"
    )
    try:
        JsonSchemaValidator(
            agent_schema, "downloaded Agent Skill index schema"
        ).validate(agent_index)
    except ContractError as exc:
        raise SkillLibraryReleaseError(
            "downloaded Agent Skill index does not match its schema"
        ) from exc
    runtime_entries = compiled_index["skills"]
    agent_entries = agent_index.get("skills")
    if not isinstance(agent_entries, list):
        raise SkillLibraryReleaseError("downloaded Agent Skill index is invalid")
    source_digest = manifest["canonical_source_sha256"]
    if (
        len(runtime_entries) != 43
        or len(agent_entries) != 43
        or agent_index.get("canonical_source_sha256") != source_digest
        or source["https"]["source_revision"] != source_digest
        or source["https"]["artifact_base_url"] != f"{PUBLISH_BASE}/"
    ):
        raise SkillLibraryReleaseError(
            "downloaded index or source identity differs from the build manifest"
        )
    runtime_archives = {
        str(entry["archive"]["path"]) for entry in runtime_entries
    }
    agent_archives = {
        str(entry["archive"]["path"]) for entry in agent_entries
    }
    if (
        len(runtime_archives) != 43
        or len(agent_archives) != 43
        or set(downloaded) != _CORE_ASSETS | runtime_archives | agent_archives
    ):
        raise SkillLibraryReleaseError(
            "published asset set differs from the two downloaded indexes"
        )
    for entry in runtime_entries:
        validate_skill_archive(downloaded[entry["archive"]["path"]], entry)
    for entry in agent_entries:
        validate_agent_archive(downloaded[entry["archive"]["path"]], entry)
    return {
        "runtime_archive_count": len(runtime_archives),
        "agent_archive_count": len(agent_archives),
    }


def _json_object(content: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SkillLibraryReleaseError(f"downloaded {label} is not UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise SkillLibraryReleaseError(f"downloaded {label} must be an object")
    return value


def _download(url: str, maximum: int) -> bytes:
    if not url.startswith(f"{PUBLISH_BASE}/") or maximum < 1:
        raise SkillLibraryReleaseError("download target is outside the fixed release")
    request = Request(url, headers={"User-Agent": "gravity-skill-release-readback/1"})
    try:
        with urlopen(request, timeout=20) as response:
            selected = urlparse(response.geturl())
            if selected.scheme != "https" or selected.hostname not in _DOWNLOAD_HOSTS:
                raise SkillLibraryReleaseError(
                    "release download redirected to an unsupported origin"
                )
            content = response.read(maximum + 1)
    except OSError as exc:
        raise SkillLibraryReleaseError("release asset download failed") from exc
    if len(content) > maximum:
        raise SkillLibraryReleaseError("release asset exceeds its download budget")
    return content


def _write_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Download and validate the fixed Skill Library v2 release."
    )
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = verify_release()
    except (OSError, ValueError) as exc:
        print(f"Skill Library release readback failed closed: {exc}", file=sys.stderr)
        return 2
    if args.receipt is not None:
        _write_receipt(args.receipt, receipt)
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
