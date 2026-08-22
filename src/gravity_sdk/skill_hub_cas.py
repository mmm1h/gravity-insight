"""Immutable single-flight local CAS for Stage A Hub artifacts."""

from __future__ import annotations

import os
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Mapping

from .skill_hub_archive import (
    validate_skill_archive,
    validate_skill_directory,
    validate_trusted_wheel,
    validate_wheel_file,
)
from .skill_hub_contract import SkillHubContractError
from .skill_hub_paths import assert_unlinked_path, ensure_unlinked_directory
from .skill_hub_source import HubSourceSession
from .support.process_lock import FileLockTimeout, advisory_file_lock


_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.Lock] = {}


class SkillHubCAS:
    """Store verified packages by digest without exposing partial entries."""

    def __init__(self, root: str | Path) -> None:
        self.root = ensure_unlinked_directory(
            Path(root), reason="HUB_CAS_INVALID", label="CAS root"
        )

    def fetch_skill(
        self, session: HubSourceSession, index_entry: Mapping[str, Any]
    ) -> dict[str, Any]:
        digest = str(index_entry["package"]["package_digest"])
        target = self.skill_path(digest)
        self._assert_cas_path(target)
        with self._single_flight("skill", digest):
            self._assert_cas_path(target)
            if target.exists() or target.is_symlink():
                result = validate_skill_directory(target, expected_digest=digest)
                return _skill_result(target, result, cached=True)
            content = session.read_artifact(index_entry["archive"]["path"])
            result = validate_skill_archive(content, index_entry)
            self._commit_skill(target, result["files"])
            verified = validate_skill_directory(target, expected_digest=digest)
            return _skill_result(target, verified, cached=False)

    def fetch_trusted_pack(
        self, session: HubSourceSession, index_entry: Mapping[str, Any]
    ) -> dict[str, Any]:
        archive = index_entry["archive"]
        digest = str(archive["sha256"])
        target = self.trusted_wheel_path(digest)
        self._assert_cas_path(target)
        with self._single_flight("trusted", digest):
            self._assert_cas_path(target)
            if target.exists() or target.is_symlink():
                selected = validate_wheel_file(
                    target,
                    expected_sha256=digest,
                    expected_size=int(archive["size_bytes"]),
                )
                return _trusted_result(index_entry, selected, cached=True)
            content = session.read_artifact(archive["path"])
            validate_trusted_wheel(content, index_entry)
            self._commit_wheel(target, content)
            selected = validate_wheel_file(
                target,
                expected_sha256=digest,
                expected_size=int(archive["size_bytes"]),
            )
            return _trusted_result(index_entry, selected, cached=False)

    def materialize_skill(
        self, package_digest: str, destination: str | Path
    ) -> dict[str, Any]:
        source = self.skill_path(package_digest)
        self._assert_cas_path(source)
        verified = validate_skill_directory(source, expected_digest=package_digest)
        target = Path(destination).absolute()
        self._assert_install_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._assert_install_path(target.parent)
        with self._single_flight("install", package_digest):
            self._assert_install_path(target)
            if target.exists() or target.is_symlink():
                installed = validate_skill_directory(
                    target, expected_digest=package_digest
                )
                return _materialized_result(target, installed, changed=False)
            temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
            try:
                temporary.mkdir()
                _write_files(temporary, verified["files"])
                self._assert_install_path(target.parent)
                os.replace(temporary, target)
            except BaseException:
                shutil.rmtree(temporary, ignore_errors=True)
                raise
            installed = validate_skill_directory(target, expected_digest=package_digest)
            return _materialized_result(target, installed, changed=True)

    def verify_skill(self, package_digest: str) -> dict[str, Any]:
        self._assert_cas_path(self.skill_path(package_digest))
        selected = validate_skill_directory(
            self.skill_path(package_digest), expected_digest=package_digest
        )
        return _skill_result(self.skill_path(package_digest), selected, cached=True)

    def verify_trusted_wheel(
        self, digest: str, *, size_bytes: int
    ) -> Path:
        self._assert_cas_path(self.trusted_wheel_path(digest))
        return validate_wheel_file(
            self.trusted_wheel_path(digest),
            expected_sha256=digest,
            expected_size=size_bytes,
        )

    def skill_path(self, digest: str) -> Path:
        return self.root / "skills" / "sha256" / _digest(digest)

    def trusted_wheel_path(self, digest: str) -> Path:
        return self.root / "trusted-packs" / "sha256" / _digest(digest) / "artifact.whl"

    def _commit_skill(self, target: Path, files: Mapping[str, bytes]) -> None:
        self._assert_cas_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._assert_cas_path(target.parent)
        temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
        try:
            temporary.mkdir()
            _write_files(temporary, files)
            self._assert_cas_path(target.parent)
            os.replace(temporary, target)
        except BaseException:
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def _commit_wheel(self, target: Path, content: bytes) -> None:
        self._assert_cas_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._assert_cas_path(target.parent)
        temporary = target.parent / f".{target.name}.tmp-{uuid.uuid4().hex}"
        try:
            temporary.write_bytes(content)
            temporary.chmod(0o644)
            self._assert_cas_path(target.parent)
            os.replace(temporary, target)
        except BaseException:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _single_flight(self, channel: str, digest: str) -> Any:
        key = f"{self.root}:{channel}:{_digest(digest)}"
        with _LOCKS_GUARD:
            thread_lock = _THREAD_LOCKS.setdefault(key, threading.Lock())
        lock_path = self.root / ".locks" / f"{channel}-{digest}.lock"
        self._assert_cas_path(lock_path)
        return _CombinedLock(
            thread_lock,
            lock_path,
            owner=f"skill-hub-{channel}",
        )

    def _assert_cas_path(self, path: Path) -> None:
        try:
            path.absolute().relative_to(self.root)
        except ValueError as exc:
            raise SkillHubContractError(
                "HUB_CAS_INVALID", "CAS path escapes its root"
            ) from exc
        assert_unlinked_path(path, reason="HUB_CAS_INVALID", label="CAS path")

    @staticmethod
    def _assert_install_path(path: Path) -> None:
        assert_unlinked_path(
            path, reason="HUB_INSTALL_PATH_INVALID", label="Skill installation path"
        )


class _CombinedLock:
    def __init__(self, thread_lock: threading.Lock, path: Path, *, owner: str) -> None:
        self._thread_lock = thread_lock
        self._path = path
        self._owner = owner
        self._process_lock: Any = None

    def __enter__(self) -> None:
        self._thread_lock.acquire()
        try:
            self._process_lock = advisory_file_lock(self._path, owner=self._owner)
            self._process_lock.__enter__()
        except FileLockTimeout as exc:
            self._thread_lock.release()
            raise SkillHubContractError(
                "HUB_CAS_BUSY", "CAS entry is being committed by another process"
            ) from exc
        except BaseException:
            self._thread_lock.release()
            raise

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        try:
            if self._process_lock is not None:
                self._process_lock.__exit__(exc_type, exc, traceback)
        finally:
            self._thread_lock.release()


def _write_files(root: Path, files: Mapping[str, bytes]) -> None:
    for relative, content in sorted(files.items()):
        path = root.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.chmod(0o644)


def _digest(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise SkillHubContractError("HUB_DIGEST_INVALID", "CAS digest is invalid")
    return value


def _skill_result(
    path: Path, verified: Mapping[str, Any], *, cached: bool
) -> dict[str, Any]:
    return {
        "schema_version": "gravity.skill-cas-result.v1",
        "status": "verified",
        "skill_uri": verified["artifact"]["skill_uri"],
        "package_digest": verified["package"]["package_digest"],
        "cas_path": str(path),
        "cached": cached,
        "network_called": False,
    }


def _trusted_result(
    entry: Mapping[str, Any], path: Path, *, cached: bool
) -> dict[str, Any]:
    return {
        "schema_version": "gravity.trusted-pack-cas-result.v1",
        "status": "verified",
        "pack_id": entry["pack_id"],
        "wheel_sha256": entry["archive"]["sha256"],
        "cas_path": str(path),
        "cached": cached,
        "network_called": False,
    }


def _materialized_result(
    path: Path, verified: Mapping[str, Any], *, changed: bool
) -> dict[str, Any]:
    return {
        "schema_version": "gravity.skill-materialization.v1",
        "status": "installed" if changed else "verified",
        "skill_uri": verified["artifact"]["skill_uri"],
        "package_digest": verified["package"]["package_digest"],
        "path": str(path),
        "changed": changed,
        "network_called": False,
    }


__all__ = ["SkillHubCAS"]
