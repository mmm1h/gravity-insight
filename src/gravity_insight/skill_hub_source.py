"""Explicit Stage A Git and static HTTPS Hub source readers."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote

from . import __version__
from .agent_runtime_contracts import canonical_digest
from .skill_hub_contract import (
    SkillHubContractError,
    artifact_path,
    compile_hub_index,
    compile_hub_source,
)
from .skill_hub_paths import assert_unlinked_path


HttpGetter = Callable[[str, int, int], bytes]


@dataclass(frozen=True)
class HubSourceSession:
    source: Mapping[str, Any]
    source_revision: str
    index: Mapping[str, Any]
    network_called: bool
    _read: Callable[[str, int], bytes]

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
    return _sync_https(compiled, http_get or _https_get, runtime_version)


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
        session = _sync_https(compiled, http_get or _https_get, runtime_version)
    session.assert_reference(reference)
    return session


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
    source: Mapping[str, Any], http_get: HttpGetter, runtime_version: str
) -> HubSourceSession:
    selected = source["https"]
    timeout = int(source["limits"]["timeout_seconds"])
    index_bytes = _http_bytes(
        http_get,
        str(selected["index_url"]),
        int(source["limits"]["max_index_bytes"]),
        timeout,
    )
    index = _compile_index_bytes(index_bytes, runtime_version)
    base = str(selected["artifact_base_url"])

    def read(relative: str, maximum: int) -> bytes:
        encoded = quote(relative, safe="/._-")
        return _http_bytes(http_get, base + encoded, maximum, timeout)

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


def _https_get(url: str, maximum: int, timeout: int) -> bytes:
    import requests

    from .receipt import DISTRIBUTION_HTTP_KIND, perform_http_request

    session = requests.Session()
    session.trust_env = False
    try:
        response = perform_http_request(
            session.get,
            url,
            kind=DISTRIBUTION_HTTP_KIND,
            headers={"Accept": "application/json, application/zip"},
            stream=True,
            allow_redirects=False,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        session.close()
        raise SkillHubContractError(
            "HUB_SOURCE_UNAVAILABLE", "Static HTTPS source request failed"
        ) from exc
    try:
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
        response.close()
        session.close()


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
    "HubSourceSession",
    "HttpGetter",
    "open_locked_hub_source",
    "sync_hub_source",
]
