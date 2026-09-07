"""Opt-in, sequential authentication failover for complete governed SDK reads."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from .account_pool_lease import AccountReadLease, ReadGenerationChanged
from .errors import AuthenticationError, CredentialError, GravityInsightError, InputValidationError, PermissionUnavailableError, PolicyViolation


_LOGGER = logging.getLogger("gravity_insight")
_READ_METHODS = frozenset({"read", "read_all", "read_limited", "run", "execute_plan", "query_sql_products"})
ADMISSION_PATH = Path("agent-runtime") / "account-failover-admission.v1.json"


@dataclass(frozen=True, repr=False)
class AccountPoolConfig:
    enabled: bool = False
    env_paths: tuple[Path | str, ...] = ()
    max_accounts: int = 2

    def __repr__(self) -> str:
        return f"AccountPoolConfig(enabled={self.enabled!r}, configured_count={len(self.env_paths)})"

    def paths(self) -> tuple[Path, ...]:
        if type(self.enabled) is not bool:
            raise _account_config_error("ACCOUNT_POOL_CONFIG_INVALID", field="account_pool.enabled", next_action="Use a boolean enable flag.")
        if not self.enabled:
            return ()
        if type(self.max_accounts) is not int or self.max_accounts < 1:
            raise _account_config_error("ACCOUNT_POOL_LIMIT_INVALID", field="account_pool.max_accounts", next_action="Use a positive integer bound.")
        if not isinstance(self.env_paths, (tuple, list)) or not 1 <= len(self.env_paths) <= self.max_accounts:
            raise _account_config_error("ACCOUNT_POOL_SIZE_INVALID", field="account_pool.env_paths", next_action="Provide between one and max_accounts sources.")
        try:
            paths = tuple(Path(value).expanduser().absolute() for value in self.env_paths)
        except (TypeError, ValueError, OSError):
            raise _account_config_error("ACCOUNT_POOL_SOURCE_INVALID", field="account_pool.env_paths", next_action="Provide independent env file paths.") from None
        if len(set(paths)) != len(paths):
            raise _account_config_error("ACCOUNT_POOL_DUPLICATE_SOURCE", field="account_pool.env_paths", next_action="Remove duplicate env file paths.")
        return paths

    @classmethod
    def from_environment(cls) -> "AccountPoolConfig":
        flag = os.environ.get("GRAVITY_ACCOUNT_FAILOVER", "0")
        if flag == "0":
            return cls()
        if flag != "1":
            raise _account_config_error("ACCOUNT_POOL_CONFIG_INVALID", field="GRAVITY_ACCOUNT_FAILOVER", next_action="Use 0 or 1.")
        try:
            paths = json.loads(os.environ.get("GRAVITY_ACCOUNT_ENV_FILES", "[]"))
            limit = int(os.environ.get("GRAVITY_ACCOUNT_MAX_ACCOUNTS", "2"))
        except (ValueError, TypeError):
            raise _account_config_error("ACCOUNT_POOL_CONFIG_INVALID", field="GRAVITY_ACCOUNT_ENV_FILES", next_action="Use a JSON path array and a positive integer account bound.") from None
        config = cls(enabled=True, env_paths=paths, max_accounts=limit)
        config.paths()
        return config


def _account_config_error(reason: str, *, field: str, next_action: str) -> InputValidationError:
    error = InputValidationError(
        f"actual value: invalid; {reason}", code=reason, field=field, next_action=next_action,
    )
    error.category = "caller"
    return error


def _unavailable(reason: str) -> PolicyViolation:
    return PolicyViolation(
        reason, code=reason,
        next_action="Renew and validate the account admission evidence, then reconnect the pool.",
    )


class AccountPool:
    def __init__(self, config: AccountPoolConfig, options: Mapping[str, Any]) -> None:
        self.paths = config.paths()
        self.options = dict(options)
        self.lock = threading.RLock()
        self.slots = [{"slot": index + 1, "state": "configured_unavailable", "reason_code": "ADMISSION_PENDING"}
                      for index in range(len(self.paths))]
        self.active = 0
        self.switch_count = 0
        self.transition = "never_switched"
        self.reason = "ACCOUNT_POOL_NOT_ATTEMPTED"
        self.sdk: Any | None = None

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            secondary = self.slots[1:]
            return {
                "mode": "failover", "active_slot": self.active + 1,
                "secondary_state": "not_configured" if not secondary else (
                    "configured_healthy" if any(slot["state"] == "configured_healthy" for slot in secondary)
                    else "configured_unavailable"
                ),
                "transition_state": self.transition, "switch_count": self.switch_count,
                "reason_code": self.reason, "slots": [dict(slot) for slot in self.slots],
            }

    def _connect(self, index: int, lease: AccountReadLease) -> Any:
        from .sdk import connect

        return connect(env_path=self.paths[index], account_pool=AccountPoolConfig(),
                       _read_lease=lease, **self.options)

    def execute(self, method: str, args: tuple[Any, ...], options: Mapping[str, Any]) -> Any:
        if method not in _READ_METHODS:
            raise _unavailable("ACCOUNT_READ_BOUNDARY_REQUIRED")
        if options.get("workspace") is not None:
            raise _unavailable("ACCOUNT_WORKSPACE_OVERRIDE_BLOCKED")
        # No extra account workers. The selected SDK retains the existing bounded
        # page/operation pools and the process-wide host limiter.
        with self.lock:
            return self._execute(method, args, dict(options))

    def _execute(self, method: str, args: tuple[Any, ...], options: dict[str, Any]) -> Any:
        if self.transition == "exhausted":
            raise self._exhausted()
        sdks, leases, admissions = self._admitted_slots()
        if self.active not in sdks:
            self.reason = "ACCOUNT_ADMISSION_UNAVAILABLE"
            raise _unavailable(self.reason)
        for index in range(self.active, len(self.paths)):
            if index not in sdks:
                continue
            if index != self.active:
                self.active = index
                self.switch_count += 1
                self.transition = "switching"
                self.reason = "AUTH_REJECTED"
            completed, value = self._attempt_account(
                index, sdks[index], leases[index], admissions[index], method, args, options
            )
            if completed:
                return value
        self.transition = "exhausted"
        self.reason = "ACCOUNT_POOL_EXHAUSTED"
        self._record(self.reason)
        raise self._exhausted() from None

    def _admitted_slots(self) -> tuple[dict[int, Any], dict[int, Any], dict[int, Any]]:
        admissions: dict[int, Any] = {}
        sdks: dict[int, Any] = {}
        leases: dict[int, AccountReadLease] = {}
        principals: set[str] = set()
        scopes: set[tuple[str, str]] = set()
        for index, path in enumerate(self.paths):
            if self.slots[index]["reason_code"] == "AUTH_REJECTED":
                continue
            try:
                _protect_sources(path)
                lease = AccountReadLease()
                sdk = self._connect(index, lease)
                admission = _load_admission(sdk, path)
                admission = {**admission, "_validation_root": sdk.workspace.state_root}
                _validate_capabilities(sdk, admission, lease)
            except (CredentialError, PolicyViolation, OSError, ValueError):
                self.slots[index].update(state="configured_unavailable", reason_code="ACCOUNT_ADMISSION_UNAVAILABLE")
                continue
            principal = admission["principal"]
            if principal in principals:
                self.reason = "ACCOUNT_DUPLICATE_PRINCIPAL"
                self.slots[index].update(state="configured_unavailable", reason_code=self.reason)
                raise _unavailable("ACCOUNT_DUPLICATE_PRINCIPAL")
            principals.add(principal)
            scopes.add((admission["permission_scope"], admission["data_scope"]))
            sdks[index], leases[index], admissions[index] = sdk, lease, admission
            self.slots[index].update(state="configured_healthy", reason_code="ACCOUNT_ADMITTED")
        if len(scopes) > 1:
            self.reason = "ACCOUNT_SCOPE_MISMATCH"
            for index in sdks:
                self.slots[index].update(state="configured_unavailable", reason_code=self.reason)
            raise _unavailable("ACCOUNT_SCOPE_MISMATCH")
        return sdks, leases, admissions

    def _attempt_account(self, index: int, sdk: Any, lease: AccountReadLease,
                         admission: Any, method: str, args: tuple[Any, ...],
                         options: dict[str, Any]) -> tuple[bool, Any]:
        for generation_attempt in range(2):
            self.sdk = sdk
            lease.check_generation = self._generation_checker(index, lease)
            self._record("ACCOUNT_READ_STARTED")
            try:
                value = getattr(sdk, method)(*args, **options)
                lease.check()  # A returned adapter error must not hide a failed lease.
            except ReadGenerationChanged:
                self._record("ACCOUNT_GENERATION_RESTART")
                if generation_attempt:
                    raise _unavailable("ACCOUNT_GENERATION_UNSTABLE") from None
                refreshed = lease.refreshed
                lease = AccountReadLease()
                lease.refreshed = refreshed
                sdk = self._connect(index, lease)
                _validate_capabilities(sdk, admission, lease)
                continue
            except AuthenticationError:
                self.slots[index].update(state="configured_unavailable", reason_code="AUTH_REJECTED")
                self.reason = "AUTH_REJECTED"
                self._record("AUTH_REJECTED")
                return False, None
            except GravityInsightError as exc:
                if isinstance(exc, PermissionUnavailableError):
                    self.slots[index].update(state="configured_unavailable", reason_code="PERMISSION_UNAVAILABLE")
                self._finished(False)
                raise
            else:
                succeeded = not isinstance(value, Mapping) or value.get("ok") is not False
                self._finished(succeeded)
                return True, value
        raise _unavailable("ACCOUNT_GENERATION_UNSTABLE")

    def _finished(self, succeeded: bool) -> None:
        self.transition = ("switched_success" if succeeded else "switched_failed") if self.switch_count else "never_switched"
        self.reason = "ACCOUNT_READ_SUCCEEDED" if succeeded else "ACCOUNT_READ_FAILED"
        self._record(self.reason)

    def _generation_checker(self, index: int, lease: AccountReadLease) -> Any:
        from .runtime_scope import runtime_scope_key

        expected = runtime_scope_key(self.paths[index], isolated=True)

        def check() -> None:
            current = runtime_scope_key(self.paths[index], isolated=True)
            if (current.account_fingerprint, current.principal_fingerprint) != (
                expected.account_fingerprint, expected.principal_fingerprint
            ):
                failure = _unavailable("ACCOUNT_PRINCIPAL_CHANGED")
                lease.reject(failure)
                raise failure
            if current != expected:
                failure = ReadGenerationChanged("credential generation changed during logical read")
                lease.reject(failure)
                raise failure

        return check

    def _exhausted(self) -> AuthenticationError:
        error = AuthenticationError(
            "ACCOUNT_POOL_EXHAUSTED: all configured accounts are rejected or unavailable",
            code="ACCOUNT_POOL_EXHAUSTED",
            next_action="Repair the configured accounts and admission evidence, then create a new pool.",
        )
        error.category = "caller"
        return error

    def _record(self, reason: str) -> None:
        from .result_output import write_rendered_result
        from .runtime_scope import credential_scope_opaque_id

        assert self.sdk is not None
        root = self.sdk.workspace.state_root
        value = {"schema_version": "gravity.account-failover.v1", **self.snapshot(),
                 "event_reason": reason, "generation_ref": credential_scope_opaque_id(root)}
        _LOGGER.info("gravity_account_failover", extra={"account_failover": value})
        try:
            write_rendered_result(str(root / "account-failover" / f"{uuid.uuid4().hex}.json"),
                                  json.dumps(value, sort_keys=True) + "\n")
        except (OSError, ValueError):
            raise _unavailable("ACCOUNT_AUDIT_WRITE_FAILED") from None


def _protect_sources(path: Path) -> None:
    from .credential_storage import _restrict_secret_file, session_path
    from .paths import PROJECT_ROOT

    for source in (path, session_path(path)):
        if any(_linked_source(parent) for parent in (source, *source.parents)):
            raise _unavailable("ACCOUNT_SOURCE_LINK_BLOCKED")
        if source.resolve().is_relative_to(PROJECT_ROOT.resolve()):
            raise _unavailable("ACCOUNT_SOURCE_IN_REPOSITORY")
        if not source.exists() and source != path:
            continue
        if not source.is_file():
            raise _unavailable("ACCOUNT_SOURCE_UNAVAILABLE")
        _restrict_secret_file(source)
        if os.name != "nt" and source.stat().st_mode & 0o077:
            raise _unavailable("ACCOUNT_SOURCE_PERMISSIONS")
        if os.name == "nt":
            _check_windows_acl(source)


def _linked_source(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return bool(stat.S_ISLNK(info.st_mode) or (
        getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
    ))


def _check_windows_acl(path: Path) -> None:
    import subprocess

    # Only the exit code escapes. Broad explicit grants left after tightening
    # inheritance are rejected, not interpreted as a protected credential source.
    script = (
        "$p=$env:GRAVITY_ACCOUNT_ACL_PATH;"
        "$allowed=@([Security.Principal.WindowsIdentity]::GetCurrent().User.Value,'S-1-5-18','S-1-5-32-544');"
        "$rules=(Get-Acl -LiteralPath $p -ErrorAction Stop).GetAccessRules($true,$true,[Security.Principal.SecurityIdentifier]);"
        "foreach($r in $rules){if($r.AccessControlType -eq 'Allow' -and $r.IdentityReference.Value -notin $allowed){exit 2}}"
    )
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            env={**os.environ, "GRAVITY_ACCOUNT_ACL_PATH": str(path)}, capture_output=True,
            timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise _unavailable("ACCOUNT_SOURCE_PERMISSIONS") from None
    if result.returncode:
        raise _unavailable("ACCOUNT_SOURCE_PERMISSIONS")


def _load_admission(sdk: Any, path: Path) -> dict[str, Any]:
    from .agent_runtime_contracts import validate_schema
    from .runtime_scope import credential_scope_opaque_id
    from .capability_validation import parse_utc_timestamp

    try:
        proof = sdk.workspace.state_root / ADMISSION_PATH
        if proof.is_symlink() or proof.stat().st_size > 65_536:
            raise ValueError
        document = json.loads(proof.read_text(encoding="utf-8"))
        validate_schema(document, "account-admission-v1.schema.json", "account admission")
        now = datetime.now(timezone.utc)
        start, end = (parse_utc_timestamp(document[key]) for key in ("validated_at", "expires_at"))
        if not start <= now < end or end - start > timedelta(days=1):
            raise ValueError
        if document["generation_ref"] != credential_scope_opaque_id(sdk.workspace.state_root):
            raise ValueError
    except (OSError, ValueError, TypeError, KeyError):
        raise _unavailable("ACCOUNT_ADMISSION_UNAVAILABLE") from None
    return document


def _validate_capabilities(sdk: Any, admission: Mapping[str, Any], lease: AccountReadLease) -> None:
    from .capability_trust import CapabilityTrustService
    from .capability_validation import CapabilityValidationStore, parse_utc_timestamp

    from .account_pool_validation import validate_sql_capability

    store = CapabilityValidationStore(admission["_validation_root"], scope_bound=True)
    service = CapabilityTrustService(store)
    allowed: set[str] = set()
    sql_products: set[str] = set()
    for entry in admission["capabilities"]:
        if entry["identity_kind"] == "product" and entry["selector"].startswith("sql-product:"):
            sql_products.add(validate_sql_capability(sdk, store, entry["selector"]))
            allowed.add("sql.query")
            continue
        trust = service.trust(entry["identity_kind"], entry["selector"])
        if trust["trust_status"] != "stable" or trust["completeness"] != "complete":
            raise _unavailable("ACCOUNT_CAPABILITY_UNAVAILABLE")
        if entry["identity_kind"] == "operation":
            allowed.add(entry["selector"])
    lease.sql_products = frozenset(sql_products)

    def check(operation_id: str) -> None:
        if parse_utc_timestamp(admission["expires_at"]) <= datetime.now(timezone.utc):
            raise _unavailable("ACCOUNT_ADMISSION_EXPIRED")
        if operation_id not in allowed:
            raise _unavailable("ACCOUNT_CAPABILITY_UNAVAILABLE")
        # Reuse the frozen store, but re-evaluate expiry and dependency trust at
        # each request boundary so a long read cannot outlive its validation.
        for entry in admission["capabilities"]:
            if entry["identity_kind"] == "product" and entry["selector"].startswith("sql-product:"):
                validate_sql_capability(sdk, store, entry["selector"])
            else:
                trust = service.trust(entry["identity_kind"], entry["selector"])
                if trust["trust_status"] != "stable" or trust["completeness"] != "complete":
                    raise _unavailable("ACCOUNT_CAPABILITY_UNAVAILABLE")
        principal = lease.runtime.current_principal_id() if lease.runtime is not None else None
        if principal is None or hashlib.sha256(principal.encode("utf-8")).hexdigest() != admission["principal"]:
            raise _unavailable("ACCOUNT_PRINCIPAL_CHANGED")

    lease.check_capability = check


__all__ = ["AccountPoolConfig"]
