from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Sequence
from unittest.mock import patch

from gravity_sdk.paths import PROJECT_ROOT
from gravity_sdk.support.process_lock import FileLockTimeout, advisory_file_lock


ROOT = PROJECT_ROOT
SECRET_FILES = (".env.gravity.local",)
RELEASE_TAG = "credential-sync"
ASSET_NAME = "gravity-sdk-credentials.json"
AUTO_PUSH_ENV = "GRAVITY_CREDENTIAL_AUTO_PUSH"
LOCK_PATH = ROOT / "tmp" / "credential-sync.lock"
PUSH_STATE_PATH = ROOT / "tmp" / "credential-sync.sha256"
MAX_SECRET_BYTES = 1024 * 1024


class CredentialSyncError(RuntimeError):
    pass


class CredentialSyncNotReady(CredentialSyncError):
    pass


def _enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _tool(name: str) -> str:
    path = shutil.which(name)
    if not path and os.name == "nt":
        winget_link = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links" / f"{name}.exe"
        path = str(winget_link) if winget_link.is_file() else None
    if path:
        return path
    if name == "gh":
        install = "brew install gh" if os.name != "nt" else "winget install GitHub.cli"
    else:
        install = name
    raise CredentialSyncError(f"Missing {name}. Install it with: {install}")


def _run(
    args: Sequence[str],
    *,
    timeout: int = 120,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    try:
        result = subprocess.run(
            list(args),
            cwd=ROOT if ROOT.is_dir() else Path.cwd(),
            check=False,
            capture_output=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CredentialSyncError(f"Could not run {Path(args[0]).name}.") from exc
    if check and result.returncode:
        lines = result.stderr.decode("utf-8", errors="replace").strip().splitlines()
        detail = f" ({lines[-1][:300]})" if lines else ""
        raise CredentialSyncError(f"{Path(args[0]).name} failed with exit {result.returncode}{detail}")
    return result


def restrict_local_secret(path: Path) -> None:
    if os.name != "nt":
        path.chmod(0o600)
        return
    domain = os.environ.get("USERDOMAIN", "").strip()
    if not domain or domain.upper() == "WORKGROUP":
        domain = os.environ.get("COMPUTERNAME", "").strip()
    account = "\\".join(
        part for part in (domain, os.environ.get("USERNAME", "").strip()) if part
    ) or getpass.getuser()
    result = _run(
        [
            "icacls.exe",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{account}:(F)",
            "*S-1-5-18:(F)",
            "*S-1-5-32-544:(F)",
        ],
        timeout=10,
        check=False,
    )
    if result.returncode:
        raise CredentialSyncError("Could not restrict access to a local credential file.")


@contextmanager
def sync_lock(path: Path = LOCK_PATH, timeout: float = 30.0) -> Iterator[None]:
    with ExitStack() as stack:
        try:
            stack.enter_context(
                advisory_file_lock(path, owner="Gravity credential sync", timeout=timeout)
            )
        except FileLockTimeout as exc:
            raise CredentialSyncError("Another credential sync is still running.") from exc
        yield


def _build_payload(root: Path = ROOT) -> bytes:
    files: dict[str, dict[str, str]] = {}
    for name in SECRET_FILES:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise CredentialSyncError(f"Missing regular credential file: {name}")
        content = path.read_bytes()
        if len(content) > MAX_SECRET_BYTES:
            raise CredentialSyncError(f"Credential file is unexpectedly large: {name}")
        files[name] = {
            "content": base64.b64encode(content).decode("ascii"),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    payload = {
        "version": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": files,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _env_values(path: Path) -> dict[str, str]:
    values = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise CredentialSyncNotReady(f"Credential file is not configured: {path.name}") from exc
    except (OSError, UnicodeError) as exc:
        raise CredentialSyncError(f"Could not read credential file: {path.name}") from exc
    for line in lines:
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _credential_fingerprint(root: Path = ROOT) -> str:
    gravity = _env_values(root / ".env.gravity.local")
    values = {
        "storage": "github-draft-release-plaintext-v1",
        "gravityUsername": gravity.get("GRAVITY_USERNAME"),
        "gravityPassword": gravity.get("GRAVITY_PASSWORD"),
    }
    if not all(values.values()):
        raise CredentialSyncNotReady("One or more credential files do not contain an access token.")
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def _saved_fingerprint() -> str:
    try:
        value = PUSH_STATE_PATH.read_text(encoding="ascii").strip()
        return value if len(value) == 64 else ""
    except OSError:
        return ""


def _save_fingerprint(value: str) -> None:
    PUSH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PUSH_STATE_PATH.with_suffix(".tmp")
    try:
        temporary.write_text(value + "\n", encoding="ascii")
        restrict_local_secret(temporary)
        os.replace(temporary, PUSH_STATE_PATH)
    finally:
        temporary.unlink(missing_ok=True)


def _parse_payload(value: bytes) -> dict[str, bytes]:
    try:
        payload = json.loads(value)
        records = payload["files"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CredentialSyncError("Credential bundle is malformed.") from exc
    if payload.get("version") != 1 or not isinstance(records, dict) or set(records) != set(SECRET_FILES):
        raise CredentialSyncError("Credential bundle has an unsupported file set.")
    files: dict[str, bytes] = {}
    for name in SECRET_FILES:
        try:
            record = records[name]
            content = base64.b64decode(record["content"], validate=True)
            digest = record["sha256"]
        except (KeyError, TypeError, ValueError) as exc:
            raise CredentialSyncError("Credential bundle contains invalid data.") from exc
        if len(content) > MAX_SECRET_BYTES or hashlib.sha256(content).hexdigest() != digest:
            raise CredentialSyncError("Credential bundle failed integrity validation.")
        files[name] = content
    return files


def _write_secret_files(files: dict[str, bytes], root: Path = ROOT) -> None:
    staged: list[tuple[Path, Path]] = []
    replaced = 0
    try:
        for name in SECRET_FILES:
            destination = root / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                "wb", dir=destination.parent, prefix=f".{name}.", suffix=".tmp", delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(files[name])
                handle.flush()
                os.fsync(handle.fileno())
            staged.append((temporary, destination))
            restrict_local_secret(temporary)
        for temporary, destination in staged:
            os.replace(temporary, destination)
            replaced += 1
    except OSError as exc:
        detail = " Credential files may be mixed; rerun credentials pull." if replaced else ""
        raise CredentialSyncError(f"Could not install the credential bundle.{detail}") from exc
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def _release_exists() -> bool:
    result = _run([_tool("gh"), "release", "view", RELEASE_TAG], timeout=30, check=False)
    if result.returncode == 0:
        return True
    error = result.stderr.decode("utf-8", errors="replace").lower()
    if "release not found" in error or "http 404" in error:
        return False
    raise CredentialSyncError("Could not inspect the GitHub credential release.")


def push() -> dict[str, str]:
    with sync_lock():
        fingerprint = _credential_fingerprint()
        with tempfile.TemporaryDirectory(prefix="gravity-sdk-credentials-") as temp:
            asset = Path(temp) / ASSET_NAME
            asset.write_bytes(_build_payload())
            restrict_local_secret(asset)
            gh = _tool("gh")
            if _release_exists():
                # ponytail: clobber has a short gap; use versioned assets if concurrent pulls matter.
                _run([gh, "release", "upload", RELEASE_TAG, str(asset), "--clobber"])
            else:
                _run(
                    [
                        gh,
                        "release",
                        "create",
                        RELEASE_TAG,
                        str(asset),
                        "--draft",
                        "--latest=false",
                        "--title",
                        "Credential sync",
                        "--notes",
                        "Plaintext GM/Gravity credentials. Anyone with repository read access can download them.",
                    ]
                )
        _save_fingerprint(fingerprint)
    return {"status": "uploaded", "asset": ASSET_NAME}


def pull() -> dict[str, str]:
    with sync_lock():
        downloaded = _run(
            [
                _tool("gh"),
                "release",
                "download",
                RELEASE_TAG,
                "--pattern",
                ASSET_NAME,
                "--output",
                "-",
            ]
        ).stdout
        _write_secret_files(_parse_payload(downloaded))
    return {"status": "updated", "asset": ASSET_NAME}


def push_if_enabled() -> bool:
    if not _enabled(AUTO_PUSH_ENV):
        return False
    try:
        fingerprint = _credential_fingerprint()
    except CredentialSyncNotReady:
        if _saved_fingerprint():
            raise
        return False
    if fingerprint == _saved_fingerprint():
        return False
    push()
    return True


def status() -> dict[str, object]:
    return {
        "sourceFilesPresent": {name: (ROOT / name).is_file() for name in SECRET_FILES},
        "ghInstalled": shutil.which("gh") is not None,
        "autoPush": _enabled(AUTO_PUSH_ENV),
        "storage": "github-draft-release-plaintext",
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as source_temp, tempfile.TemporaryDirectory() as target_temp:
        source = Path(source_temp)
        expected = {}
        for index, name in enumerate(SECRET_FILES):
            content = f"KEY_{index}=value_{index}\n".encode()
            (source / name).write_bytes(content)
            expected[name] = content
        parsed = _parse_payload(_build_payload(source))
        assert parsed == expected
        invalid = json.loads(_build_payload(source))
        invalid["version"] = 2
        try:
            _parse_payload(json.dumps(invalid).encode())
        except CredentialSyncError:
            pass
        else:
            raise AssertionError("an unsupported credential bundle version was accepted")
        invalid["version"] = 1
        invalid["files"][SECRET_FILES[0]]["sha256"] = "0" * 64
        try:
            _parse_payload(json.dumps(invalid).encode())
        except CredentialSyncError:
            pass
        else:
            raise AssertionError("a tampered credential bundle was accepted")
        target = Path(target_temp)
        _write_secret_files(parsed, target)
        assert {name: (target / name).read_bytes() for name in SECRET_FILES} == expected
        failed_target = target / "failed"
        with patch(f"{__name__}.restrict_local_secret", side_effect=CredentialSyncError("probe")):
            try:
                _write_secret_files(parsed, failed_target)
            except CredentialSyncError:
                pass
            else:
                raise AssertionError("a local permission failure was accepted")
        assert not list(failed_target.iterdir())
        (source / ".env.gravity.local").write_text(
            "GRAVITY_USERNAME=account\nGRAVITY_PASSWORD=password-1\n"
        )
        fingerprint = _credential_fingerprint(source)
        (source / ".env.gravity.local").write_text(
            "GRAVITY_USERNAME=account\nGRAVITY_PASSWORD=password-1\n# comment changed\n"
        )
        assert _credential_fingerprint(source) == fingerprint
        (source / ".env.gravity.local").write_text(
            "GRAVITY_USERNAME=account\nGRAVITY_PASSWORD=password-2\n"
        )
        assert _credential_fingerprint(source) != fingerprint
        (source / ".env.gravity.local").unlink()
        try:
            _credential_fingerprint(source)
        except CredentialSyncError:
            pass
        else:
            raise AssertionError("a missing credential file was accepted")
