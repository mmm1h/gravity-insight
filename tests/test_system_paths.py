"""OS alias trust and guarded consumers, without privileged symlink creation."""

from __future__ import annotations

import os
import stat
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gravity_insight import account_pool, blob_storage, provider_rpc_transport
from gravity_insight.blob_models import BlobTransferError
from gravity_insight.errors import PolicyViolation
from gravity_insight.skill_hub_client import SkillHubClient
from gravity_insight.skill_hub_contract import SkillHubContractError
from gravity_insight.skill_hub_paths import assert_unlinked_path
from gravity_insight.support import cache_files, system_paths


def metadata(mode: int, uid: int = 0, attributes: int = 0) -> SimpleNamespace:
    return SimpleNamespace(st_mode=mode, st_uid=uid, st_file_attributes=attributes)


@pytest.fixture
def darwin_fs(monkeypatch):
    """Pure POSIX names plus mocked metadata also work on Windows CI."""
    entries = {
        "/": metadata(stat.S_IFDIR | 0o755),
        "/private": metadata(stat.S_IFDIR | 0o755),
    }
    targets = {}
    for name in ("var", "tmp", "etc"):
        entries[f"/{name}"] = metadata(stat.S_IFLNK | 0o777)
        entries[f"/private/{name}"] = metadata(stat.S_IFDIR | (0o1777 if name == "tmp" else 0o755))
        targets[f"/{name}"] = f"private/{name}"
    monkeypatch.setattr(system_paths, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(system_paths, "os", SimpleNamespace(
        lstat=lambda path: entries[str(path)], readlink=lambda path: targets[str(path)],
    ))
    return entries, targets


@pytest.mark.parametrize("name", ["var", "tmp", "etc"])
def test_verified_system_alias_is_accepted(darwin_fs, name):
    entries, _ = darwin_fs
    alias = PurePosixPath(f"/{name}")
    assert system_paths.is_system_alias(alias, entries[str(alias)])
    # Normalization must retain unexamined user links, never resolve them away.
    path = alias / "user-link" / "state"
    assert system_paths.system_alias_path(path) == PurePosixPath(f"/private/{name}/user-link/state")
    assert system_paths.system_alias_path(alias) == alias


@pytest.mark.parametrize(("entry", "replacement"), [
    ("/var", metadata(stat.S_IFLNK | 0o777, uid=501)),
    ("/", metadata(stat.S_IFDIR | 0o755, uid=501)),
    ("/", metadata(stat.S_IFDIR | 0o775)),
    ("/", metadata(stat.S_IFDIR | 0o757)),
    ("/private", metadata(stat.S_IFDIR | 0o777)),
    ("/private/var", metadata(stat.S_IFLNK | 0o777)),
    ("/var", metadata(stat.S_IFLNK | 0o777, attributes=0x400)),
])
def test_untrusted_alias_metadata_is_rejected(darwin_fs, entry, replacement):
    entries, _ = darwin_fs
    entries[entry] = replacement
    assert not system_paths.is_system_alias(PurePosixPath("/var"), entries["/var"])
    assert system_paths.system_alias_path(PurePosixPath("/var/state")) == PurePosixPath("/var/state")


def test_redirected_or_unreadable_alias_is_rejected(darwin_fs):
    entries, targets = darwin_fs
    targets["/var"] = "private/tmp"
    assert not system_paths.is_system_alias(PurePosixPath("/var"), entries["/var"])
    with patch.object(system_paths.os, "readlink", side_effect=OSError("unavailable")):
        assert not system_paths.is_system_alias(PurePosixPath("/var"), entries["/var"])


@pytest.mark.parametrize("platform", ["linux", "win32"])
def test_other_platforms_never_trust_darwin_aliases(darwin_fs, monkeypatch, platform):
    entries, _ = darwin_fs
    monkeypatch.setattr(system_paths.sys, "platform", platform)
    assert not system_paths.is_system_alias(PurePosixPath("/var"), entries["/var"])
    path = PurePosixPath("/var/state")
    assert system_paths.system_alias_path(path) == path


def test_root_owned_user_path_is_not_a_system_alias(darwin_fs):
    assert not system_paths.is_system_alias(
        PurePosixPath("/home/user/var"), metadata(stat.S_IFLNK | 0o777)
    )


@pytest.mark.parametrize("uid", [0, 501])
def test_state_root_rejects_linked_parent_before_resolution(tmp_path, monkeypatch, uid):
    parent = tmp_path / "linked-parent"
    parent.mkdir()
    original = Path.lstat
    monkeypatch.setattr(Path, "lstat", lambda p: (
        metadata(stat.S_IFLNK | 0o777, uid) if p == parent else original(p)
    ))
    with patch.object(Path, "resolve", side_effect=AssertionError("must reject before resolve")):
        with pytest.raises(SkillHubContractError, match="HUB_STATE_INVALID"):
            SkillHubClient(parent / "state")
    assert not (parent / "state").exists()


@pytest.mark.parametrize("guard", ["hub", "blob", "provider", "account", "cache"])
@pytest.mark.parametrize("info", [
    metadata(stat.S_IFLNK | 0o777), metadata(stat.S_IFDIR | 0o755, attributes=0x400),
], ids=["root-owned-link", "reparse"])
def test_guards_reject_user_controlled_ancestors(tmp_path, monkeypatch, guard, info):
    parent = tmp_path / "linked"
    child = parent / "managed"
    child.mkdir(parents=True)
    original_path_lstat, original_lstat = Path.lstat, os.lstat
    monkeypatch.setattr(Path, "lstat", lambda p: info if p == parent else original_path_lstat(p))
    monkeypatch.setattr(os, "lstat", lambda p, **kw: info if Path(p) == parent else original_lstat(p, **kw))
    if guard == "hub":
        with pytest.raises(SkillHubContractError):
            assert_unlinked_path(child, reason="HUB_CAS_INVALID", label="CAS root")
    elif guard == "blob":
        with pytest.raises(BlobTransferError, match="symlink or reparse"):
            blob_storage._require_plain_directory(child, stage="destination_policy")
    elif guard == "provider":
        with pytest.raises(ValueError, match="link or reparse"):
            provider_rpc_transport._real_directory(child, "Work root")
    elif guard == "account":
        with pytest.raises(PolicyViolation) as error:
            account_pool._protect_sources(child / "synthetic.env")
        assert error.value.code == "ACCOUNT_SOURCE_LINK_BLOCKED"
    else:
        with pytest.raises(OSError, match="CACHE_LINK_REFUSED"):
            cache_files.assert_unlinked(child)


def test_provider_checks_original_links_after_normalized_containment(tmp_path):
    lexical, canonical = tmp_path / "var", tmp_path / "private" / "var"
    argument = lexical / "provider.py"
    with patch.object(provider_rpc_transport, "system_alias_path", return_value=canonical / "provider.py"):
        with patch.object(provider_rpc_transport, "_assert_unlinked") as guard:
            provider_rpc_transport._validate_argument_path(str(argument), canonical)
        guard.assert_called_once_with(argument, "Provider argument path", root=canonical)
        with patch.object(provider_rpc_transport, "_assert_unlinked", side_effect=ValueError("linked")):
            with pytest.raises(ValueError, match="linked"):
                provider_rpc_transport._validate_argument_path(str(argument), canonical)


def test_blob_accepts_mixed_verified_system_spellings(tmp_path):
    lexical, canonical = tmp_path / "var", tmp_path / "private" / "var"
    lexical.mkdir()
    canonical.mkdir(parents=True)
    def normalized(path):
        return canonical / path.relative_to(lexical) if path.is_relative_to(lexical) else path
    with patch.object(blob_storage, "system_alias_path", side_effect=normalized):
        with patch.object(Path, "resolve", autospec=True, side_effect=lambda path, **kw: normalized(path)):
            assert blob_storage._require_plain_directory(
                lexical, boundary=canonical, stage="resume_policy",
            ) == lexical


def test_cache_delete_uses_verified_root_spelling(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    path = root / "entry"
    path.write_bytes(b"fixture")
    info = path.lstat()
    lexical = tmp_path / "system-alias" / "cache"
    with patch.object(cache_files, "system_alias_path", side_effect=lambda p: root if p == lexical else p):
        cache_files.unlink_unchanged(lexical, lexical / "entry", info)
    assert not path.exists()
