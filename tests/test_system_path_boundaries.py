"""Managed-root boundaries and baseline consumer behavior on simulated filesystems."""
from __future__ import annotations

import os
import stat
from pathlib import PurePosixPath, PureWindowsPath
from types import SimpleNamespace

import pytest

from gravity_insight import blob_policy, blob_storage, provider_rpc_transport
from gravity_insight.blob_models import BlobTransferError
from gravity_insight.blob_policy import BlobPolicy
from gravity_insight.support import system_paths


@pytest.fixture
def model_fs(monkeypatch):
    def install(platform):
        trace, entries = [], {}
        base = PureWindowsPath if platform == "win32" else PurePosixPath

        def lstat(path):
            trace.append(("lstat", str(path)))
            entry = entries.get(str(path), SimpleNamespace(
                st_mode=stat.S_IFDIR | 0o755, st_uid=0, st_file_attributes=0,
            ))
            if isinstance(entry, Exception):
                raise entry
            return entry

        class ModelPath(base):
            def absolute(self):
                return self

            def lstat(self):
                return lstat(self)

            def resolve(self, **kwargs):
                trace.append(("resolve", str(self)))
                return system_paths.system_alias_path(self)

        def lexists(path):
            trace.append(("lexists", str(path)))
            return False

        aliases = {f"/{name}": f"private/{name}" for name in ("var", "tmp", "etc")}
        filesystem = SimpleNamespace(
            lstat=lstat, readlink=lambda p: aliases[str(p)], fspath=os.fspath,
            path=SimpleNamespace(abspath=lambda p: str(p), lexists=lexists),
        )
        monkeypatch.setattr(system_paths, "sys", SimpleNamespace(platform=platform))
        monkeypatch.setattr(system_paths, "os", filesystem)
        monkeypatch.setattr(blob_storage, "sys", SimpleNamespace(platform=platform, modules={}))
        monkeypatch.setattr(blob_storage, "os", filesystem)
        monkeypatch.setattr(blob_storage, "Path", ModelPath)
        # BlobPolicy rebuilds its roots with Path; a Windows host would otherwise
        # rewrite the simulated POSIX spellings.
        monkeypatch.setattr(blob_policy, "Path", ModelPath)
        monkeypatch.setattr(provider_rpc_transport, "Path", ModelPath)
        return ModelPath, entries, trace
    return install


def link_metadata(attributes=0):
    return SimpleNamespace(st_mode=stat.S_IFLNK | 0o777, st_uid=0, st_file_attributes=attributes)


@pytest.mark.parametrize("consumer", ["blob", "provider"])
@pytest.mark.parametrize("root", ["/", "/var", "/private/var"])
def test_managed_root_and_internal_system_alias_are_rejected(model_fs, consumer, root):
    path, entries, _ = model_fs("darwin")
    entries["/var"] = link_metadata()
    if consumer == "blob":
        with pytest.raises(BlobTransferError) as error:
            blob_storage._require_plain_directory(
                path("/var/folders/session"), boundary=path(root), stage="destination_policy",
            )
        assert error.value.code == "BLOB_PATH_REPARSE"
    else:
        message = "escapes its work root" if root == "/var" else "contains a link or reparse point"
        with pytest.raises(ValueError, match=f"^Provider argument path {message}$"):
            provider_rpc_transport._validate_argument_path("/var/folders/session/result.csv", path(root))


@pytest.mark.parametrize("destination_root", ["/", "/var/folders/session"])
def test_blob_destination_rejects_system_alias_inside_temporary_root(model_fs, destination_root):
    path, entries, _ = model_fs("darwin")
    entries["/var"] = link_metadata()
    destination = "var/folders/session/result.csv" if destination_root == "/" else "result.csv"
    policy = BlobPolicy(destination_root=path(destination_root), temporary_root=path("/"), allowed_extensions=frozenset({".csv"}))
    with pytest.raises(BlobTransferError) as error:
        blob_storage._prepare_destination(destination, policy)
    assert error.value.code == "BLOB_PATH_REPARSE"


@pytest.mark.parametrize("root", ["/work/session", "/var/folders/session", "/private/var/folders/session"])
def test_consumers_accept_plain_roots_and_default_tmpdir_spelling(model_fs, root):
    path, entries, trace = model_fs("darwin")
    entries["/var"] = link_metadata()
    lexical = root.replace("/private/var/", "/var/")
    policy = BlobPolicy(destination_root=path(lexical), temporary_root=path(root), allowed_extensions=frozenset({".csv"}))
    assert blob_storage._prepare_destination("child/result.csv", policy) == (
        path(lexical) / "child/result.csv", ".csv",
    )
    provider_rpc_transport._validate_argument_path(
        str(path(lexical) / "child/result.csv"), system_paths.system_alias_path(path(root)),
    )
    assert ("lstat", str(path(lexical) / "child")) in trace


@pytest.mark.parametrize("replacement_check", [1, 2])
def test_blob_mixed_spelling_checks_original_internal_components(model_fs, monkeypatch, replacement_check):
    path, entries, trace = model_fs("darwin")
    entries["/var"] = link_metadata()
    original = blob_storage.os.lstat
    checks = 0

    def lstat(candidate):
        nonlocal checks
        if str(candidate) == "/var/folders/session/linked":
            checks += 1
            if checks == replacement_check:
                entries[str(candidate)] = link_metadata()
        return original(candidate)

    monkeypatch.setattr(blob_storage.os, "lstat", lstat)
    with pytest.raises(BlobTransferError) as error:
        blob_storage._require_plain_directory(
            path("/var/folders/session/linked/child"),
            boundary=path("/private/var/folders/session"), stage="resume_policy",
        )
    assert error.value.code == "BLOB_PATH_REPARSE"
    assert ("lstat", "/private/var/folders/session/linked") not in trace


@pytest.mark.parametrize("platform", ["darwin", "linux", "win32"])
@pytest.mark.parametrize("outside_kind", ["unavailable", "link"])
def test_provider_outside_root_does_not_access_filesystem(model_fs, platform, outside_kind):
    path, entries, trace = model_fs(platform)
    prefix = "C:/" if platform == "win32" else "/"
    outside = path(prefix + "outside/argument")
    entries[str(outside)] = PermissionError("denied") if outside_kind == "unavailable" else link_metadata()
    with pytest.raises(ValueError, match="^Provider argument path escapes its work root$"):
        provider_rpc_transport._validate_argument_path(str(outside), path(prefix + "work"))
    assert trace == []


@pytest.mark.parametrize("platform", ["linux", "win32"])
@pytest.mark.parametrize("case", ["plain", "missing", "link", "reparse", "unavailable", "relative", "traversal"])
def test_provider_non_darwin_validation_matches_baseline(model_fs, platform, case):
    path, entries, trace = model_fs(platform)
    root = path("C:/work" if platform == "win32" else "/work")
    candidate = root / "child/argument"
    errors = {
        "missing": FileNotFoundError(), "link": link_metadata(),
        "reparse": SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_file_attributes=0x400),
        "unavailable": PermissionError(),
    }
    # FILE_ATTRIBUTE_REPARSE_POINT is defined by stat on all supported Pythons.
    if case in errors:
        entries[str(candidate)] = errors[case]
    value = {"relative": "child/argument", "traversal": str(root / "../outside")}.get(case, str(candidate))
    messages = {
        "link": "Provider argument path contains a link or reparse point",
        "reparse": "Provider argument path contains a link or reparse point",
        "unavailable": "Provider argument path is unavailable",
        "traversal": "Provider argument path escapes its work root",
    }
    if case in messages:
        with pytest.raises(ValueError, match=f"^{messages[case]}$"):
            provider_rpc_transport._validate_argument_path(value, root)
    else:
        provider_rpc_transport._validate_argument_path(value, root)
    checked = [] if case in ("relative", "traversal") else (
        [candidate] if case in ("link", "reparse", "unavailable") else [candidate, *candidate.parents]
    )
    assert trace == [("lstat", str(item)) for item in checked]


@pytest.mark.parametrize("platform", ["linux", "win32"])
@pytest.mark.parametrize("linked", [False, True])
def test_blob_non_darwin_destination_matches_baseline(model_fs, platform, linked):
    path, entries, trace = model_fs(platform)
    root = path("C:/work" if platform == "win32" else "/work")
    policy = BlobPolicy(destination_root=root, temporary_root=root, allowed_extensions=frozenset({".csv"}))
    if linked:
        entries[str(root / "child")] = link_metadata()
        with pytest.raises(BlobTransferError) as error:
            blob_storage._prepare_destination("child/result.csv", policy)
        assert (error.value.code, error.value.stage, str(error.value)) == (
            "BLOB_PATH_REPARSE", "destination_policy",
            "configured local directory is a symlink or reparse point",
        )
        expected = [("lstat", root), ("lstat", root), ("lstat", root / "child")]
    else:
        assert blob_storage._prepare_destination("child/result.csv", policy) == (root / "child/result.csv", ".csv")
        expected = [
            ("lstat", root), ("lstat", root), ("lstat", root / "child"),
            ("lstat", root), ("lstat", root / "child"), ("lstat", root),
            ("lstat", root / "child"), ("resolve", root / "child"), ("resolve", root),
            ("lstat", root), ("lstat", root), ("lexists", root / "child/result.csv"),
        ]
    assert trace == [(operation, str(item)) for operation, item in expected]
