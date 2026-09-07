"""Explicit Stage A Git and static HTTPS Hub source readers."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from dataclasses import dataclass
from importlib import resources
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote, urlsplit

from . import __version__
from .agent_runtime_contracts import (
    AgentRuntimeContractError,
    canonical_digest,
    validate_schema,
)
from .skill_hub_contract import (
    SkillHubContractError,
    artifact_path,
    compile_hub_index,
    compile_hub_source,
)
from .skill_hub_paths import assert_unlinked_path
from .skill_package import SkillPackageError, validate_package_entries


HttpGetter = Callable[[str, int, int], bytes]
BUNDLED_SKILL_SEED_NAME = "skill-seed-v1.zip"
_SEED_SCHEMA_VERSION = "gravity.skill-library-build.v2"
_AGENT_INDEX_SCHEMA = "agent-skill-index-v1.schema.json"
_MAX_SEED_BYTES = 128 * 1024 * 1024
_MAX_SEED_FILES = 93


@dataclass(frozen=True)
class HubSourceSession:
    source: Mapping[str, Any]
    source_revision: str
    index: Mapping[str, Any]
    network_called: bool
    _read: Callable[[str, int], bytes]
    seed_digest: str | None = None

    def reference(self) -> dict[str, str]:
        return {
            "source_id": str(self.source["source_id"]),
            "transport": str(self.source["transport"]),
            "source_descriptor_digest": canonical_digest(self.source),
            "source_revision": self.source_revision,
            "index_digest": str(self.index["digest"]),
        }

    def read_artifact(self, relative: str) -> bytes:
        selected = artifact_path(relative)
        return self._read(selected, int(self.source["limits"]["max_artifact_bytes"]))

    def assert_reference(self, value: Mapping[str, Any]) -> None:
        if dict(value) != self.reference():
            raise SkillHubContractError(
                "HUB_SOURCE_SNAPSHOT_CHANGED", "Lock and synced Hub snapshot disagree"
            )


def sync_hub_source(
    source: Mapping[str, Any],
    *,
    repository: str | Path | None = None,
    http_get: HttpGetter | None = None,
    runtime_version: str = __version__,
) -> HubSourceSession:
    compiled = compile_hub_source(source)["contract"]
    if compiled["transport"] == "git":
        if repository is None or http_get is not None:
            raise SkillHubContractError(
                "HUB_SOURCE_BINDING_INVALID", "Git Hub Source requires one local mirror"
            )
        return _sync_git(compiled, Path(repository), runtime_version)
    if repository is not None:
        raise SkillHubContractError(
            "HUB_SOURCE_BINDING_INVALID", "HTTPS Hub Source cannot use a Git mirror"
        )
    return _sync_https(compiled, http_get, runtime_version)


def open_locked_hub_source(
    source: Mapping[str, Any],
    reference: Mapping[str, Any],
    *,
    repository: str | Path | None = None,
    http_get: HttpGetter | None = None,
    runtime_version: str = __version__,
) -> HubSourceSession:
    compiled = compile_hub_source(source)["contract"]
    if compiled["transport"] == "git":
        if repository is None or http_get is not None:
            raise SkillHubContractError(
                "HUB_SOURCE_BINDING_INVALID", "Locked Git source requires one local mirror"
            )
        session = _open_git_revision(
            compiled,
            Path(repository),
            str(reference.get("source_revision", "")),
            runtime_version,
        )
    else:
        if repository is not None:
            raise SkillHubContractError(
                "HUB_SOURCE_BINDING_INVALID", "Locked HTTPS source cannot use a mirror"
            )
        session = _sync_https(compiled, http_get, runtime_version)
    session.assert_reference(reference)
    return session


def open_bundled_hub_source(
    content: bytes | None = None,
    *,
    runtime_version: str = __version__,
) -> HubSourceSession:
    """Open the wheel's sealed mirror without treating it as a new transport."""

    selected = _bundled_seed_bytes() if content is None else content
    validated = validate_bundled_skill_seed(
        selected, runtime_version=runtime_version
    )
    source = validated["source"]
    index = validated["index"]
    files = validated["files"]

    def read(relative: str, maximum: int) -> bytes:
        name = artifact_path(relative)
        artifact = files.get(name)
        if artifact is None:
            raise SkillHubContractError(
                "HUB_SEED_INVALID", "Bundled Skill artifact is missing"
            )
        if len(artifact) > maximum:
            raise SkillHubContractError(
                "HUB_SOURCE_OUTPUT_LIMIT", "Bundled Skill artifact exceeds its byte budget"
            )
        return artifact

    return HubSourceSession(
        source,
        str(source["https"]["source_revision"]),
        index,
        False,
        read,
        seed_digest=str(validated["seed_digest"]),
    )


def validate_bundled_skill_seed(
    content: bytes,
    *,
    runtime_version: str = __version__,
) -> dict[str, Any]:
    """Validate the outer seed, its build receipt, indexes, and Agent archives."""

    if not isinstance(content, bytes) or not 1 <= len(content) <= _MAX_SEED_BYTES:
        raise SkillHubContractError("HUB_SEED_INVALID", "Bundled Skill seed is invalid")
    try:
        files = _seed_files(content)
        manifest = _seed_json(files, "build-manifest.json", "build manifest")
        release_rows = _validate_seed_manifest(manifest)
        expected_names = {"build-manifest.json", *release_rows}
        if set(files) != expected_names or len(files) != _MAX_SEED_FILES:
            raise SkillHubContractError(
                "HUB_SEED_INVALID", "Bundled Skill seed file set changed"
            )
        for name, row in release_rows.items():
            artifact = files[name]
            if (
                row["size_bytes"] != len(artifact)
                or row["sha256"] != hashlib.sha256(artifact).hexdigest()
            ):
                raise SkillHubContractError(
                    "HUB_SEED_DIGEST_MISMATCH",
                    "Bundled Skill seed artifact changed",
                )

        compiled_source = compile_hub_source(
            _seed_json(files, "source.json", "Hub Source")
        )
        compiled_index = _compile_index_bytes(files["index.json"], runtime_version)
        agent_index = _seed_json(files, "agent-index.json", "Agent Skill index")
        validate_schema(agent_index, _AGENT_INDEX_SCHEMA, "Agent Skill index")
        _validate_seed_bindings(
            manifest,
            compiled_source["contract"],
            compiled_index,
            agent_index,
            files,
        )
    except SkillHubContractError:
        raise
    except (AgentRuntimeContractError, SkillPackageError) as exc:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill seed validation failed"
        ) from exc
    return {
        "schema_version": "gravity.skill-seed-validation.v1",
        "seed_digest": hashlib.sha256(content).hexdigest(),
        "build_manifest_digest": canonical_digest(manifest),
        "source": compiled_source["contract"],
        "source_descriptor_digest": compiled_source["digest"],
        "index": compiled_index,
        "agent_index": agent_index,
        "skill_count": len(compiled_index["skills"]),
        "agent_skill_count": len(agent_index["skills"]),
        "files": files,
        "network_called": False,
    }


def _bundled_seed_bytes() -> bytes:
    try:
        return (
            resources.files("gravity_insight")
            .joinpath("skill_seed", BUNDLED_SKILL_SEED_NAME)
            .read_bytes()
        )
    except (FileNotFoundError, ModuleNotFoundError, OSError) as exc:
        raise SkillHubContractError(
            "HUB_SEED_UNAVAILABLE", "Bundled Skill seed is unavailable"
        ) from exc


def _seed_files(content: bytes) -> dict[str, bytes]:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if archive.comment:
                raise SkillHubContractError(
                    "HUB_SEED_INVALID", "Bundled Skill seed comment is invalid"
                )
            members = archive.infolist()
            names = [item.filename for item in members]
            if (
                len(members) != _MAX_SEED_FILES
                or names != sorted(names)
                or len(names) != len(set(names))
                or len({name.casefold() for name in names}) != len(names)
            ):
                raise SkillHubContractError(
                    "HUB_SEED_INVALID", "Bundled Skill seed entries are invalid"
                )
            result: dict[str, bytes] = {}
            total = 0
            for member in members:
                path = PurePosixPath(member.filename)
                if (
                    path.is_absolute()
                    or len(path.parts) != 1
                    or any(part in {"", ".", ".."} for part in path.parts)
                    or member.is_dir()
                    or member.flag_bits & 0x1
                    or member.date_time != (1980, 1, 1, 0, 0, 0)
                    or member.compress_type != zipfile.ZIP_STORED
                    or member.create_system != 3
                    or member.external_attr >> 16 != 0o100644
                    or member.file_size < 1
                ):
                    raise SkillHubContractError(
                        "HUB_SEED_INVALID", "Bundled Skill seed member is unsafe"
                    )
                total += member.file_size
                if total > _MAX_SEED_BYTES:
                    raise SkillHubContractError(
                        "HUB_SEED_INVALID", "Bundled Skill seed exceeds its byte budget"
                    )
                value = archive.read(member)
                if len(value) != member.file_size:
                    raise SkillHubContractError(
                        "HUB_SEED_INVALID", "Bundled Skill seed member changed"
                    )
                result[member.filename] = value
            return result
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill seed is not a valid ZIP"
        ) from exc


def _seed_json(files: Mapping[str, bytes], name: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(files[name].decode("utf-8"))
    except (KeyError, UnicodeError, json.JSONDecodeError) as exc:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", f"Bundled {label} is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(value, dict):
        raise SkillHubContractError(
            "HUB_SEED_INVALID", f"Bundled {label} must be an object"
        )
    return value


def _validate_seed_manifest(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    expected = {
        "artifact_kind",
        "schema_version",
        "canonical_source",
        "canonical_source_sha256",
        "publish_target",
        "publish_base_url",
        "files",
        "release_assets",
    }
    if (
        set(manifest) != expected
        or manifest.get("artifact_kind") != "skill_library_build"
        or manifest.get("schema_version") != _SEED_SCHEMA_VERSION
        or manifest.get("canonical_source") != "skills/library"
        or manifest.get("publish_target") != "github_release"
        or not _sha256(manifest.get("canonical_source_sha256"))
        or not isinstance(manifest.get("publish_base_url"), str)
    ):
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill build manifest changed"
        )
    all_rows = _seed_rows(manifest.get("files"), "build files")
    release_rows = _seed_rows(manifest.get("release_assets"), "release assets")
    if (
        len(release_rows) != _MAX_SEED_FILES - 1
        or any("/" in name for name in release_rows)
        or any(all_rows.get(name) != row for name, row in release_rows.items())
    ):
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill release asset binding changed"
        )
    return release_rows


def _seed_rows(value: Any, label: str) -> dict[str, dict[str, Any]]:
    if not isinstance(value, list):
        raise SkillHubContractError("HUB_SEED_INVALID", f"Bundled {label} changed")
    result: dict[str, dict[str, Any]] = {}
    previous = ""
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "size_bytes", "sha256"}
            or not isinstance(item.get("path"), str)
            or not item["path"]
            or item["path"] <= previous
            or not isinstance(item.get("size_bytes"), int)
            or isinstance(item.get("size_bytes"), bool)
            or item["size_bytes"] < 1
            or not _sha256(item.get("sha256"))
        ):
            raise SkillHubContractError("HUB_SEED_INVALID", f"Bundled {label} changed")
        previous = item["path"]
        result[item["path"]] = dict(item)
    return result


def _validate_seed_bindings(
    manifest: Mapping[str, Any],
    source: Mapping[str, Any],
    index: Mapping[str, Any],
    agent_index: Mapping[str, Any],
    files: Mapping[str, bytes],
) -> None:
    source_digest = str(manifest["canonical_source_sha256"])
    https = source["https"]
    publish_base = str(manifest["publish_base_url"])
    runtime_entries = list(index["skills"].values())
    agent_entries = list(agent_index["skills"])
    if (
        source["transport"] != "static_https"
        or source["git"] is not None
        or https["source_revision"] != source_digest
        or https["index_url"] != f"{publish_base}/index.json"
        or https["artifact_base_url"] != f"{publish_base}/"
        or agent_index.get("canonical_source_sha256") != source_digest
        or len(runtime_entries) != 44
        or len(agent_entries) != 44
    ):
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill source binding changed"
        )
    runtime_identities = [item["skill_uri"] for item in runtime_entries]
    agent_identities = [item["skill_uri"] for item in agent_entries]
    if runtime_identities != agent_identities:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Runtime and Agent Skill sets differ"
        )
    expected_assets = {
        "index.json",
        "agent-index.json",
        "agent-skill-index-v1.schema.json",
        "source.json",
        *(item["archive"]["path"] for item in runtime_entries),
        *(item["archive"]["path"] for item in agent_entries),
    }
    if set(files) != {"build-manifest.json", *expected_assets}:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Skill asset references changed"
        )
    for entry in agent_entries:
        _validate_agent_seed_archive(files[entry["archive"]["path"]], entry)


def _validate_agent_seed_archive(content: bytes, entry: Mapping[str, Any]) -> None:
    archive_metadata = entry["archive"]
    if (
        archive_metadata["size_bytes"] != len(content)
        or archive_metadata["sha256"] != hashlib.sha256(content).hexdigest()
        or archive_metadata["media_type"]
        != "application/vnd.gravity.agent-skill.v1+zip"
    ):
        raise SkillHubContractError(
            "HUB_SEED_DIGEST_MISMATCH", "Bundled Agent Skill archive changed"
        )
    expected = {
        f"{entry['directory']}/{item['path']}": item for item in entry["files"]
    }
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = archive.infolist()
            names = [item.filename for item in members]
            if names != sorted(expected) or len(names) != len(set(names)):
                raise SkillHubContractError(
                    "HUB_SEED_INVALID", "Bundled Agent Skill entries changed"
                )
            package_files: dict[str, bytes] = {}
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
                    raise SkillHubContractError(
                        "HUB_SEED_INVALID", "Bundled Agent Skill member is unsafe"
                    )
                value = archive.read(member)
                metadata = expected.get(member.filename)
                if metadata is None or (
                    metadata["size_bytes"] != len(value)
                    or metadata["sha256"] != hashlib.sha256(value).hexdigest()
                ):
                    raise SkillHubContractError(
                        "HUB_SEED_DIGEST_MISMATCH",
                        "Bundled Agent Skill content changed",
                    )
                package_files[PurePosixPath(*path.parts[1:]).as_posix()] = value
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
        raise SkillHubContractError(
            "HUB_SEED_INVALID", "Bundled Agent Skill archive is invalid"
        ) from exc
    validate_package_entries(package_files, allow_skill_md=True)


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _sync_git(
    source: Mapping[str, Any], repository: Path, runtime_version: str
) -> HubSourceSession:
    selected = repository.resolve()
    ref = str(source["git"]["ref"])
    revision = _git_text(selected, "rev-parse", f"{ref}^{{commit}}").strip()
    session = _open_git_revision(source, repository, revision, runtime_version)
    if _git_text(selected, "rev-parse", f"{ref}^{{commit}}").strip() != revision:
        raise SkillHubContractError(
            "HUB_SOURCE_SNAPSHOT_CHANGED", "Git source ref changed during sync"
        )

    return session


def _open_git_revision(
    source: Mapping[str, Any],
    repository: Path,
    revision: str,
    runtime_version: str,
) -> HubSourceSession:
    selected = assert_unlinked_path(
        repository, reason="HUB_SOURCE_UNAVAILABLE", label="Git mirror"
    )
    if not selected.is_dir():
        raise SkillHubContractError(
            "HUB_SOURCE_UNAVAILABLE", "Configured Git mirror is unavailable"
        )
    configured = str(source["git"]["repository_uri"])
    origin = _git_text(selected, "remote", "get-url", "origin").strip()
    if origin != configured:
        raise SkillHubContractError(
            "HUB_SOURCE_IDENTITY_MISMATCH", "Git mirror origin changed"
        )
    if not _sha(revision):
        raise SkillHubContractError(
            "HUB_SOURCE_REVISION_INVALID", "Git source revision is invalid"
        )
    resolved = _git_text(selected, "rev-parse", f"{revision}^{{commit}}").strip()
    if resolved != revision:
        raise SkillHubContractError(
            "HUB_SOURCE_REVISION_INVALID", "Git source revision is unavailable"
        )
    index_bytes = _git_bytes(
        selected,
        revision,
        str(source["git"]["index_path"]),
        int(source["limits"]["max_index_bytes"]),
    )
    index = _compile_index_bytes(index_bytes, runtime_version)

    def read(relative: str, maximum: int) -> bytes:
        current_origin = _git_text(selected, "remote", "get-url", "origin").strip()
        if current_origin != configured:
            raise SkillHubContractError(
                "HUB_SOURCE_IDENTITY_MISMATCH", "Git mirror origin changed"
            )
        return _git_bytes(selected, revision, relative, maximum)

    return HubSourceSession(source, revision, index, False, read)


def _sync_https(
    source: Mapping[str, Any], http_get: HttpGetter | None, runtime_version: str
) -> HubSourceSession:
    selected = source["https"]
    timeout = int(source["limits"]["timeout_seconds"])
    redirect_hosts = tuple(selected.get("allowed_redirect_hosts", ()))
    getter = http_get or (
        lambda url, maximum, selected_timeout: _https_get(
            url,
            maximum,
            selected_timeout,
            allowed_redirect_hosts=redirect_hosts,
        )
    )
    index_bytes = _http_bytes(
        getter,
        str(selected["index_url"]),
        int(source["limits"]["max_index_bytes"]),
        timeout,
    )
    index = _compile_index_bytes(index_bytes, runtime_version)
    base = str(selected["artifact_base_url"])

    def read(relative: str, maximum: int) -> bytes:
        encoded = quote(relative, safe="/._-")
        return _http_bytes(getter, base + encoded, maximum, timeout)

    return HubSourceSession(
        source,
        str(selected["source_revision"]),
        index,
        True,
        read,
    )


def _compile_index_bytes(content: bytes, runtime_version: str) -> dict[str, Any]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SkillHubContractError(
            "HUB_INDEX_INVALID", "Hub Index is not valid UTF-8 JSON"
        ) from exc
    return compile_hub_index(value, runtime_version=runtime_version)


def _git_text(root: Path, *arguments: str) -> str:
    try:
        return _git(root, *arguments, maximum=16 * 1024 * 1024).decode("utf-8")
    except UnicodeError as exc:
        raise SkillHubContractError(
            "HUB_SOURCE_UNAVAILABLE", "Git source metadata is not UTF-8"
        ) from exc


def _git_bytes(root: Path, revision: str, relative: str, maximum: int) -> bytes:
    selected = artifact_path(relative)
    object_name = f"{revision}:{selected}"
    try:
        size = int(
            _git(root, "cat-file", "-s", object_name, maximum=128)
            .decode("ascii")
            .strip()
        )
    except (UnicodeError, ValueError) as exc:
        raise SkillHubContractError(
            "HUB_SOURCE_UNAVAILABLE", "Git source object size is invalid"
        ) from exc
    if not 0 <= size <= maximum:
        raise SkillHubContractError(
            "HUB_SOURCE_OUTPUT_LIMIT", "Git source output exceeds its byte budget"
        )
    content = _git(root, "show", object_name, maximum=maximum)
    if len(content) != size:
        raise SkillHubContractError(
            "HUB_SOURCE_SNAPSHOT_CHANGED", "Git source object changed while reading"
        )
    return content


def _git(root: Path, *arguments: str, maximum: int) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SkillHubContractError(
            "HUB_SOURCE_UNAVAILABLE", "Bounded Git source read failed"
        ) from exc
    if len(result.stdout) > maximum:
        raise SkillHubContractError(
            "HUB_SOURCE_OUTPUT_LIMIT", "Git source output exceeds its byte budget"
        )
    return result.stdout


def _https_get(
    url: str,
    maximum: int,
    timeout: int,
    *,
    allowed_redirect_hosts: Sequence[str] = (),
) -> bytes:
    import requests

    from .receipt import DISTRIBUTION_HTTP_KIND, perform_http_request

    session = requests.Session()
    session.trust_env = False
    response = None

    def request(selected_url: str):
        return perform_http_request(
            session.get,
            selected_url,
            kind=DISTRIBUTION_HTTP_KIND,
            headers={"Accept": "application/json, application/zip"},
            stream=True,
            allow_redirects=False,
            timeout=timeout,
        )

    try:
        response = request(url)
    except requests.RequestException as exc:
        session.close()
        raise SkillHubContractError(
            "HUB_SOURCE_UNAVAILABLE", "Static HTTPS source request failed"
        ) from exc
    try:
        if response.is_redirect or response.status_code in {301, 302, 303, 307, 308}:
            target = _allowed_redirect_target(
                response.headers.get("Location"), allowed_redirect_hosts
            )
            response.close()
            response = None
            try:
                response = request(target)
            except requests.RequestException as exc:
                raise SkillHubContractError(
                    "HUB_SOURCE_UNAVAILABLE", "Static HTTPS redirect request failed"
                ) from exc
        if response.status_code != 200 or response.is_redirect:
            raise SkillHubContractError(
                "HUB_SOURCE_UNAVAILABLE", "Static HTTPS source did not return an exact artifact"
            )
        declared = response.headers.get("Content-Length")
        if declared is not None and (not declared.isdigit() or int(declared) > maximum):
            raise SkillHubContractError(
                "HUB_SOURCE_OUTPUT_LIMIT", "Static HTTPS source exceeds its byte budget"
            )
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > maximum:
                raise SkillHubContractError(
                    "HUB_SOURCE_OUTPUT_LIMIT", "Static HTTPS source exceeds its byte budget"
                )
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        if response is not None:
            response.close()
        session.close()


def _allowed_redirect_target(
    location: object, allowed_redirect_hosts: Sequence[str]
) -> str:
    if not isinstance(location, str) or not location or len(location) > 8192:
        raise SkillHubContractError(
            "HUB_SOURCE_UNAVAILABLE", "Static HTTPS redirect is missing an exact target"
        )
    try:
        parsed = urlsplit(location)
        port = parsed.port
    except ValueError as exc:
        raise SkillHubContractError(
            "HUB_SOURCE_UNAVAILABLE", "Static HTTPS redirect target is invalid"
        ) from exc
    allowed = {str(host).casefold() for host in allowed_redirect_hosts}
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname is None
        or parsed.hostname.casefold() not in allowed
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise SkillHubContractError(
            "HUB_SOURCE_UNAVAILABLE",
            "Static HTTPS redirect target is not explicitly trusted",
        )
    return location


def _http_bytes(
    getter: HttpGetter, url: str, maximum: int, timeout: int
) -> bytes:
    content = getter(url, maximum, timeout)
    if not isinstance(content, bytes) or len(content) > maximum:
        raise SkillHubContractError(
            "HUB_SOURCE_OUTPUT_LIMIT",
            "Static HTTPS transport exceeded its byte contract",
        )
    return content


def _sha(value: str) -> bool:
    return len(value) == 40 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "BUNDLED_SKILL_SEED_NAME",
    "HubSourceSession",
    "HttpGetter",
    "open_bundled_hub_source",
    "open_locked_hub_source",
    "sync_hub_source",
    "validate_bundled_skill_seed",
]
