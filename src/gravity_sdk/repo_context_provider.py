"""Public built-in Repo Context Provider facade."""

from __future__ import annotations

import copy
import hashlib
import re
from pathlib import Path
from typing import Any, Mapping

from .context_contract import (
    ContextContractError,
    PROJECT_REPO_PROVIDER_URI,
    project_repo_provider_artifact,
    validate_context_pack,
)
from .errors import ErrorCategory, exit_code_for_category
from .repo_context_git import assert_clean_paths, git_snapshot
from .repo_context_index import (
    build_repo_index,
    get_repo_resource,
    read_context_file,
    search_repo_index,
)
from .repo_context_pack import assemble_context_pack


_PROJECT_ID = re.compile(r"^[a-z][a-z0-9.-]*$")
_LOCAL_EXIT = exit_code_for_category(ErrorCategory.LOCAL)


class RepoContextProvider:
    """Read one project repository through deterministic Context contracts."""

    def __init__(self, root: str | Path, *, project_id: str) -> None:
        candidate = Path(root)
        selected = candidate.resolve()
        if candidate.is_symlink() or not selected.is_dir():
            raise ContextContractError(
                "CONTEXT_PROVIDER_UNSUPPORTED", "Project repository root is invalid"
            )
        if not isinstance(project_id, str) or _PROJECT_ID.fullmatch(project_id) is None:
            raise ContextContractError(
                "CONTEXT_PROVIDER_INVALID", "Project identity is invalid"
            )
        self.root = selected
        self.project_id = project_id
        self._provider = project_repo_provider_artifact()
        self._index: dict[str, Any] | None = None

    def describe(self) -> dict[str, Any]:
        return {
            "schema_version": "gravity.context-provider-description.v1",
            "status": "success",
            "ok": True,
            "project_id": self.project_id,
            "provider": copy.deepcopy(self._provider),
            "network_called": False,
        }

    def index(self) -> dict[str, Any]:
        self._index = build_repo_index(
            self.root,
            project_id=self.project_id,
            provider=self._provider,
        )
        return copy.deepcopy(self._index)

    def search(
        self,
        query: str,
        *,
        maximum: int | None = None,
        excerpt_lines: int | None = None,
    ) -> dict[str, Any]:
        limits = self._provider["contract"]["limits"]
        selected_maximum = _bounded_limit(
            maximum, limits["max_search_results"], "maximum"
        )
        selected_lines = _bounded_limit(
            excerpt_lines, limits["max_excerpt_lines"], "excerpt_lines"
        )
        return search_repo_index(
            self.root,
            self._current_index(),
            query,
            maximum=selected_maximum,
            excerpt_lines=selected_lines,
        )

    def get(self, uri: str, *, maximum_lines: int | None = None) -> dict[str, Any]:
        limit = self._provider["contract"]["limits"]["max_excerpt_lines"]
        selected = _bounded_limit(maximum_lines, limit, "maximum_lines")
        return get_repo_resource(
            self.root,
            self._current_index(),
            uri,
            maximum_lines=selected,
        )

    def pack(
        self,
        requirement: Mapping[str, Any],
        *,
        requested_time: Mapping[str, Mapping[str, Any]],
        entity_aliases: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        return assemble_context_pack(
            self.root,
            project_id=self.project_id,
            provider=self._provider,
            requirement=requirement,
            requested_time=requested_time,
            entity_aliases=entity_aliases,
        )

    def verify(self, pack: Mapping[str, Any]) -> dict[str, Any]:
        digest = pack.get("pack_digest") if isinstance(pack, Mapping) else None
        try:
            selected = validate_context_pack(pack)
            revision = self._verify_identity(selected)
            self._verify_items(selected)
            assert_clean_paths(
                self.root, [item["citation"]["path"] for item in selected["items"]]
            )
            if git_snapshot(self.root)["source_revision"] != revision:
                raise ContextContractError(
                    "CONTEXT_SNAPSHOT_CHANGED", "Context Pack changed during verification"
                )
        except ContextContractError as exc:
            return _verification(digest, False, [exc.reason_code])
        return _verification(selected["pack_digest"], True, [])

    def _current_index(self) -> dict[str, Any]:
        if self._index is None:
            self.index()
        return copy.deepcopy(self._index)

    def _verify_identity(self, pack: Mapping[str, Any]) -> str:
        provider = pack["provider"]
        snapshot = git_snapshot(self.root)
        if (
            provider.get("uri") != PROJECT_REPO_PROVIDER_URI
            or provider.get("digest") != self._provider["digest"]
            or provider.get("source_revision") != snapshot["source_revision"]
        ):
            raise ContextContractError(
                "CONTEXT_SNAPSHOT_CHANGED", "Context Pack Provider snapshot changed"
            )
        return snapshot["source_revision"]

    def _verify_items(self, pack: Mapping[str, Any]) -> None:
        limits = self._provider["contract"]["limits"]
        for item in pack["items"]:
            expected_uri = f"repo://{self.project_id}/{item['citation']['path']}"
            if item["uri"] != expected_uri:
                raise ContextContractError(
                    "CONTEXT_ITEM_INVALID", "Context Item repository URI changed"
                )
            content, _path = read_context_file(
                self.root,
                item["citation"]["path"],
                maximum=limits["max_file_bytes"],
                require_tracked=True,
                max_depth=limits["max_path_depth"],
            )
            if hashlib.sha256(content.encode("utf-8")).hexdigest() != item[
                "content_hash"
            ]:
                raise ContextContractError(
                    "CONTEXT_SNAPSHOT_CHANGED", "Context Item content changed"
                )


def _bounded_limit(value: Any, maximum: int, field: str) -> int:
    selected = maximum if value is None else value
    if isinstance(selected, bool) or not isinstance(selected, int) or not 1 <= selected <= maximum:
        raise ContextContractError(
            "CONTEXT_RESOURCE_LIMIT", f"{field} exceeds the Provider boundary"
        )
    return selected


def _verification(
    digest: Any, valid: bool, reasons: list[str]
) -> dict[str, Any]:
    result = {
        "schema_version": "gravity.context-pack-verification.v1",
        "status": "valid" if valid else "invalid",
        "ok": valid,
        "pack_digest": digest if isinstance(digest, str) else None,
        "reason_codes": reasons,
        "network_called": False,
    }
    if not valid:
        result["exit_code"] = _LOCAL_EXIT
    return result


__all__ = ["RepoContextProvider"]
