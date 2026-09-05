"""Startup-only immutable pip stages and supervised process activation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence, TextIO

from . import __version__
from ._auto_upgrade_state import (
    UpdateStateBusy,
    _write_state_file,
    build_upgrade_attempt,
    format_timestamp,
    hold_update_lease,
    recent_incomplete_upgrade,
    runtime_scope_id,
    utc,
    write_upgrade_attempt,
)


RECEIPT_SCHEMA = "gravity.runtime-update-receipt.v1"
RECEIPT_ENV = "GRAVITY_INSIGHT_UPDATE_RECEIPT"
_BOOTSTRAP = (
    "import sys,runpy; sys.path.insert(0,sys.argv.pop(1)); "
    "runpy.run_module('gravity_insight',run_name='__main__')"
)
_VERIFY = (
    "import sys; sys.path.insert(0,sys.argv[1]); "
    "import gravity_insight as g; import gravity_insight.__main__ as cli; "
    "from pathlib import Path; "
    "assert Path(g.__file__).resolve().is_relative_to(Path(sys.argv[1]).resolve()); "
    "assert g.__version__ == sys.argv[2]; assert callable(cli.main)"
)


def _python(
    target: Path,
    arguments: Sequence[str],
    *,
    environment: Mapping[str, str],
    capture: bool = True,
    timeout: int | None = 180,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(target), "-X", "utf8", *arguments],
        env={**environment, "PYTHONIOENCODING": "utf-8"},
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=capture,
        timeout=timeout,
        check=False,
    )


def _child_environment(environment: Mapping[str, str]) -> dict[str, str]:
    return {
        **environment,
        "GRAVITY_INSIGHT_AUTO_UPGRADE": "0",
        "GRAVITY_SDK_AUTO_UPGRADE": "0",
        "PYTHONUTF8": "1",
    }


@dataclass(frozen=True)
class InstallationReceipt:
    """Lifecycle provenance, not a consumer analysis-result envelope."""

    receipt_id: str
    from_version: str
    to_version: str
    captured_at: str
    trigger: Mapping[str, str | int]
    target_python: str
    stage: str
    running_version: str
    schema_version: str = RECEIPT_SCHEMA
    status: str = "installing"
    activation: str = "supervised_reexec"


def prepare_install(
    version: str,
    *,
    target_python: str | os.PathLike[str] | None,
    cache_root: Path,
    now: datetime,
    environment: Mapping[str, str],
) -> tuple[str, dict[str, Any] | None, str | None]:
    """Install without changing any file visible to an existing runtime."""

    target = Path(target_python or sys.executable).expanduser().resolve()
    if not target.is_file():
        return (
            "failed",
            None,
            "target Python does not exist; configure a valid target interpreter",
        )
    root = cache_root / "runtime-updates" / runtime_scope_id(str(target), target.parent)
    try:
        with hold_update_lease(root / "install.json", now):
            return _prepare_locked(version, target, root, now, environment)
    except UpdateStateBusy:
        return (
            "busy",
            None,
            "another startup owns the installation lock; retry next startup",
        )


def _prepare_locked(
    version: str,
    target: Path,
    root: Path,
    now: datetime,
    environment: Mapping[str, str],
) -> tuple[str, dict[str, Any] | None, str | None]:
    manifest = root / f"installed-{version}.json"
    receipt = _read_installed(manifest, version, target)
    if receipt is not None:
        return "installed", receipt, None
    attempt = root / "attempt.json"
    if recent_incomplete_upgrade(attempt, now, timedelta(hours=24)):
        return (
            "suppressed",
            None,
            f"recent incomplete installation; inspect {root} and retry after 24 hours",
        )
    write_upgrade_attempt(
        attempt,
        build_upgrade_attempt(
            attempted_version=version,
            attempted_at=now,
            status="started",
        ),
    )
    stage = root / f"{version}-{uuid.uuid4().hex}"
    stage.mkdir()
    receipt = asdict(
        InstallationReceipt(
            receipt_id=uuid.uuid4().hex,
            from_version=__version__,
            to_version=version,
            captured_at=format_timestamp(now),
            trigger={"kind": "cli_startup", "pid": os.getpid()},
            target_python=str(target),
            stage=str(stage),
            running_version=__version__,
        )
    )
    journal = root / f"receipt-{receipt['receipt_id']}.json"
    _write_state_file(journal, receipt)
    child_env = _child_environment(environment)
    try:
        log = root / f"pip-{receipt['receipt_id']}.log"
        _install_and_verify(target, stage, version, log, child_env)
        receipt.update(status="installed", captured_at=format_timestamp(utc(None)))
        _write_state_file(journal, receipt)
        _write_state_file(manifest, receipt)
        write_upgrade_attempt(
            attempt,
            build_upgrade_attempt(
                attempted_version=version,
                attempted_at=now,
                status="verified",
            ),
        )
        return "installed", receipt, None
    except Exception as exc:
        receipt.update(status="failed", reason=f"{type(exc).__name__}: {exc}")
        _write_state_file(journal, receipt)
        write_upgrade_attempt(
            attempt,
            build_upgrade_attempt(
                attempted_version=version,
                attempted_at=now,
                status="failed",
            ),
        )
        raise


def _read_installed(
    manifest: Path, version: str, target: Path
) -> dict[str, Any] | None:
    if not manifest.exists():
        return None
    receipt = json.loads(manifest.read_text(encoding="utf-8"))
    stage = Path(receipt["stage"])
    if (
        receipt.get("schema_version") != RECEIPT_SCHEMA
        or receipt.get("status") != "installed"
        or receipt.get("to_version") != version
        or receipt.get("target_python") != str(target)
        or stage.parent != manifest.parent
        or not stage.is_dir()
    ):
        raise ValueError(
            "installed update receipt is invalid; repair the runtime-updates cache"
        )
    return receipt


def _install_and_verify(
    target: Path,
    stage: Path,
    version: str,
    log: Path,
    environment: Mapping[str, str],
) -> None:
    installed = _python(
        target,
        [
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--only-binary=:all:",
            "--target",
            str(stage),
            f"gravity-insight=={version}",
        ],
        environment=environment,
    )
    # Keep pip diagnostics private: index configuration can contain credentials.
    descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(installed.stdout + installed.stderr)
    if installed.returncode:
        raise RuntimeError(
            f"pip exited {installed.returncode}; inspect private log {log}; "
            "check index connectivity, wheel availability and cache write permissions"
        )
    verified = _python(
        target, ["-I", "-c", _VERIFY, str(stage), version], environment=environment
    )
    if verified.returncode:
        raise RuntimeError(
            "installed wheel failed isolated version/CLI validation; repair or republish the wheel"
        )


def activate_install(
    receipt: Mapping[str, Any],
    argv: Sequence[str],
    *,
    output: TextIO,
) -> int | None:
    """Re-launch once; only failures BEFORE business execution may fall back."""

    target, stage = Path(receipt["target_python"]), Path(receipt["stage"])
    environment = _child_environment(os.environ)
    activation = {
        **receipt,
        "receipt_id": uuid.uuid4().hex,
        "status": "activation_requested",
        "installation_receipt_id": receipt["receipt_id"],
        "from_version": __version__,
        "captured_at": format_timestamp(utc(None)),
        "trigger": {"kind": "cli_startup", "pid": os.getpid()},
    }
    journal = stage.parent / f"activation-{activation['receipt_id']}.json"
    try:
        verified = _python(
            target,
            ["-I", "-c", _VERIFY, str(stage), receipt["to_version"]],
            environment=environment,
        )
        if verified.returncode:
            raise RuntimeError(
                "staged CLI validation failed; repair the runtime-updates cache"
            )
        _write_state_file(journal, activation)
    except Exception as exc:
        print(
            f"warning: update activation failed ({type(exc).__name__}: {exc}). "
            f"Continuing this command with {__version__}; repair the update cache or set "
            "GRAVITY_INSIGHT_AUTO_UPGRADE=0.",
            file=output,
        )
        return None
    environment[RECEIPT_ENV] = str(journal)
    print(
        f"Gravity SDK re-exec {__version__} -> {receipt['to_version']}; receipt={journal}",
        file=output,
    )
    try:
        # Inherit stdin/stdout/stderr. Never replay a command after it has started.
        completed = _python(
            target,
            ["-I", "-c", _BOOTSTRAP, str(stage), *argv],
            environment=environment,
            capture=False,
            timeout=None,
        )
    except OSError as exc:
        print(
            f"warning: cannot start updated Python ({exc}); continuing with {__version__}. "
            "Check target permissions or set GRAVITY_INSIGHT_AUTO_UPGRADE=0.",
            file=output,
        )
        return None
    activation.update(
        status="process_exited",
        exit_code=completed.returncode,
        running_version=receipt["to_version"],
    )
    try:
        _write_state_file(journal, activation)
    except OSError:
        print(
            f"warning: cannot finalize update receipt {journal}; inspect cache permissions.",
            file=output,
        )
    return completed.returncode
