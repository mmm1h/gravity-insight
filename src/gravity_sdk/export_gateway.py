"""Authenticated export gateway bound to effect-specific policy receipts."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import re
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, urlsplit

from .blob import AuthorizedBlobSource
from .errors import AuthenticationError, PermissionUnavailableError, TransportError
from .export_contracts import ExportContractRegistry, ExportRouteContract
from .export_models import (
    ExportCreationRequest,
    ExportJobSnapshot,
    ExportRuntimeError,
    ExportState,
    _export_error,
)
from .result_source import GOVERNED_PRODUCT, result_source
from .export_policy import _AuthorizedEffectRequest
from .registry import PolicyEngine


_AUTH_CODES = frozenset({2001, 10000, 10001})
_SUCCESS_CODES = frozenset({0, 200, "0", "200", None})
_STATE_MAP = {
    0: ExportState.QUEUED,
    1: ExportState.RUNNING,
    2: ExportState.READY,
    3: ExportState.FAILED,
    4: ExportState.CANCEL_REQUESTED,
    5: ExportState.FAILED,
    "0": ExportState.QUEUED,
    "1": ExportState.RUNNING,
    "2": ExportState.READY,
    "3": ExportState.FAILED,
    "4": ExportState.CANCEL_REQUESTED,
    "5": ExportState.FAILED,
    "queued": ExportState.QUEUED,
    "pending": ExportState.QUEUED,
    "running": ExportState.RUNNING,
    "processing": ExportState.RUNNING,
    "ready": ExportState.READY,
    "success": ExportState.READY,
    "completed": ExportState.READY,
    "failed": ExportState.FAILED,
    "cancelled": ExportState.CANCEL_REQUESTED,
    "canceled": ExportState.CANCEL_REQUESTED,
}


class GravityExportGateway:
    """Normalize one create route through the shared task center protocol."""

    supports_cancel = True

    def __init__(
        self,
        contracts: ExportContractRegistry,
        policy: PolicyEngine,
        runtime: Any,
        create_operation_id: str,
        *,
        status_operation_id: str = "export.task.progress",
        cancel_operation_id: str = "export.task.cancel",
        wall_clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.contracts = contracts
        self.policy = policy
        self.runtime = runtime
        self.create_contract = contracts.get(create_operation_id)
        self.status_contract = contracts.get(status_operation_id)
        self.cancel_contract = contracts.get(cancel_operation_id)
        if self.create_contract.effect != "export_job_create":
            raise ValueError("create_operation_id must own export_job_create")
        if self.status_contract.effect != "export_status":
            raise ValueError("status operation must own export_status")
        if self.cancel_contract.effect != "export_cancel":
            raise ValueError("cancel operation must own export_cancel")
        self._clock = wall_clock or (lambda: datetime.now(timezone.utc))

    def create(
        self,
        request: ExportCreationRequest,
        *,
        timeout_seconds: float,
    ) -> ExportJobSnapshot:
        _, payload, _ = self._call(
            self.create_contract,
            request.payload,
            timeout_seconds=timeout_seconds,
            attempts=1,
        )
        job_id = _first_path(payload, self.create_contract.response.get("job_id_paths", []))
        if job_id is None:
            raise _export_error(
                "export creation response omitted task_id",
                code="EXPORT_PROTOCOL_ERROR",
                stage="creating",
            )
        return ExportJobSnapshot(
            str(job_id),
            ExportState.QUEUED,
            completeness=request.completeness,
        )

    def status(self, job_id: str, *, timeout_seconds: float) -> ExportJobSnapshot:
        authorization, payload, _ = self._call(
            self.status_contract,
            {"task_id": _job_identifier(job_id)},
            timeout_seconds=timeout_seconds,
            attempts=3,
        )
        raw_state = _first_path(
            payload,
            self.status_contract.response.get("state_paths", []),
        )
        normalized_state = _normalize_state(raw_state)
        failure_message = _first_path(
            payload,
            self.status_contract.response.get("failure_message_paths", []),
        )
        source = None
        if normalized_state == ExportState.READY:
            source = self._download_source(authorization, payload, job_id)
        return ExportJobSnapshot(
            job_id,
            normalized_state,
            download_source=source,
            failure_code=(
                "EXPORT_UPSTREAM_EXPIRED"
                if str(raw_state) == "5"
                else "EXPORT_UPSTREAM_FAILED"
                if normalized_state == ExportState.FAILED
                else None
            ),
            failure_message=(
                str(failure_message)[:500]
                if failure_message not in (None, "")
                else None
            ),
            failure_retryable=False,
        )

    def cancel(self, job_id: str, *, timeout_seconds: float) -> ExportJobSnapshot:
        self._call(
            self.cancel_contract,
            {"task_id": _job_identifier(job_id)},
            timeout_seconds=timeout_seconds,
            attempts=1,
        )
        return ExportJobSnapshot(job_id, ExportState.CANCEL_REQUESTED)

    def _download_source(
        self,
        status_authorization: _AuthorizedEffectRequest,
        payload: Mapping[str, Any],
        job_id: str,
    ) -> AuthorizedBlobSource | None:
        url_value = _first_path(
            payload,
            self.status_contract.response.get("download_url_paths", []),
        )
        if not isinstance(url_value, str) or not url_value.strip():
            return None
        url = url_value.strip()
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or not parsed.path:
            raise _export_error(
                "export status returned an invalid download URL",
                code="EXPORT_DOWNLOAD_SOURCE_INVALID",
                stage="status",
            )
        expiry = _signed_url_expiry(url)
        fallback_ttl = self.create_contract.privacy.get(
            "download_authorization_ttl_seconds"
        )
        if expiry is None and isinstance(fallback_ttl, int) and fallback_ttl > 0:
            expiry = self._clock() + timedelta(seconds=fallback_ttl)
        mime_type = self.create_contract.privacy.get("mime_type")
        if expiry is None or not isinstance(mime_type, str) or not mime_type:
            return None
        size = _integer_path(
            payload,
            self.status_contract.response.get("size_paths", []),
        )
        digest = _first_path(
            payload,
            self.status_contract.response.get("sha256_paths", []),
        )
        expected_sha256 = (
            str(digest).lower()
            if isinstance(digest, str) and re.fullmatch(r"[0-9a-fA-F]{64}", digest)
            else None
        )
        scope = f"export_download:{self.create_contract.operation_id}:{job_id}"
        receipt = self.policy.authorize_blob_download(
            status_authorization,
            job_id=job_id,
            url=url,
            declared_path=parsed.path,
            expires_at=expiry,
            authorization_scope=scope,
        )
        return AuthorizedBlobSource(
            url=url,
            declared_path=parsed.path,
            expires_at=expiry,
            authorization_scope=scope,
            job_id=job_id,
            declared_size=size,
            declared_mime_type=mime_type,
            expected_sha256=expected_sha256,
            effect_receipt=receipt,
        )

    def _call(
        self,
        contract: ExportRouteContract,
        payload: Mapping[str, Any],
        *,
        timeout_seconds: float,
        attempts: int,
    ) -> tuple[_AuthorizedEffectRequest, Mapping[str, Any], Mapping[str, str]]:
        authorization = self.policy._prepare_effect_request(
            contract.operation_id,
            contract.effect,
            payload,
        )
        response = self.runtime._request_insight(
            contract.method,
            contract.path,
            policy_authorization=authorization,
            params=dict(authorization.query),
            json_body=dict(authorization.body) or None,
            semantic_auth_codes=_AUTH_CODES,
            timeout=timeout_seconds,
            attempts=attempts,
        )
        status = int(getattr(response, "status_code", 0))
        raw_payload = getattr(response, "payload", None)
        if status == 403:
            raise PermissionUnavailableError(
                "the authenticated Gravity account cannot use this export operation"
            )
        if status == 401:
            raise AuthenticationError("Gravity authorization is invalid or expired")
        if status < 200 or status >= 300:
            raise TransportError(f"Gravity export request failed with HTTP {status}")
        if not isinstance(raw_payload, Mapping):
            raise _export_error(
                "Gravity export returned an unexpected JSON envelope",
                code="EXPORT_PROTOCOL_ERROR",
                stage=contract.effect,
            )
        code = raw_payload.get("code")
        if code not in _SUCCESS_CODES:
            raise _export_error(
                "Gravity export returned a non-success semantic code",
                code="EXPORT_UPSTREAM_FAILED",
                stage=contract.effect,
                details={"semantic_code": str(code)[:64]},
            )
        return authorization, raw_payload, getattr(response, "headers", {})


class ExportTaskCenter:
    def __init__(
        self,
        contracts: ExportContractRegistry,
        policy: PolicyEngine,
        runtime: Any,
    ) -> None:
        self.contracts = contracts
        self.policy = policy
        self.runtime = runtime

    def list(self, *, page: int = 1, page_size: int = 100) -> dict[str, Any]:
        list_contract = self.contracts.get("export.task.list")
        authorization = self.policy._prepare_effect_request(
            list_contract.operation_id,
            list_contract.effect,
            {
                "page": page,
                "page_size": page_size,
                "filters": [
                    {"field": "source", "operator": 6, "values": ["turbo"]}
                ],
            },
        )
        response = self.runtime._request_insight(
            list_contract.method,
            list_contract.path,
            policy_authorization=authorization,
            params=dict(authorization.query),
            json_body=dict(authorization.body) or None,
            semantic_auth_codes=_AUTH_CODES,
            attempts=3,
        )
        payload = getattr(response, "payload", None)
        if not isinstance(payload, Mapping) or payload.get("code") not in _SUCCESS_CODES:
            raise _export_error(
                "export task list returned an invalid envelope",
                code="EXPORT_PROTOCOL_ERROR",
                stage="export_status",
            )
        rows = _first_path(payload, list_contract.response.get("list_paths", []))
        if not isinstance(rows, list):
            raise _export_error(
                "export task list omitted its list",
                code="EXPORT_PROTOCOL_ERROR",
                stage="export_status",
            )
        page_info = _first_path(
            payload,
            list_contract.response.get("page_info_paths", []),
        )
        return {
            "schema_version": "gravity-insight.export-list.v2",
            "result_source": result_source(GOVERNED_PRODUCT),
            "ok": True,
            "status": "success",
            "jobs": _sanitize_task_rows(rows, self.contracts),
            "page_info": dict(page_info) if isinstance(page_info, Mapping) else {},
        }


def _sanitize_task_rows(
    rows: list[Any], contracts: ExportContractRegistry
) -> list[dict[str, Any]]:
    operation_by_type = _operation_by_task_type(contracts)
    return [
        _sanitize_task_row(row, contracts, operation_by_type)
        for row in rows
        if isinstance(row, Mapping)
    ]


def _sanitize_task_row(
    row: Mapping[str, Any],
    contracts: ExportContractRegistry,
    operation_by_type: Mapping[str, str],
) -> dict[str, Any]:
    task_type = str(row.get("task_type", ""))[:100]
    operation_id = operation_by_type.get(task_type)
    contract = contracts.get(operation_id) if operation_id is not None else None
    task_name = str(row.get("task_name", ""))[:200]
    fingerprint = (
        hashlib.sha256(task_name.encode("utf-8")).hexdigest()[:16]
        if task_name else None
    )
    field_names = (
        sorted(str(value) for value in contract.request.get("allowed_fields", []))
        if contract is not None else []
    )
    return {
        "job_id": str(row.get("id", row.get("task_id", ""))),
        "operation_id": operation_id,
        "operation_mapping": "verified" if operation_id is not None else "unknown",
        "task_type": task_type,
        "state": _normalize_state(row.get("status")).value,
        "download_ready": bool(row.get("download_url")),
        "created_at": row.get("create_time"),
        "request_summary": {
            "field_names": field_names,
            "task_name_fingerprint": fingerprint,
            "task_name_length": len(task_name),
            "parameter_values_redacted": True,
        },
    }


def _operation_by_task_type(
    contracts: ExportContractRegistry,
) -> dict[str, str]:
    candidates: dict[str, list[str]] = {}
    for contract in contracts.all():
        if (
            contract.effect != "export_job_create"
            or not contract.executable
            or contract.contract_status != "verified"
        ):
            continue
        values = contract.response.get("task_type_values", [])
        if not isinstance(values, list):
            continue
        for value in values:
            if isinstance(value, str) and value:
                candidates.setdefault(value, []).append(contract.operation_id)
    return {
        task_type: operation_ids[0]
        for task_type, operation_ids in candidates.items()
        if len(operation_ids) == 1
    }


def _normalize_state(value: Any) -> ExportState:
    key = value.casefold() if isinstance(value, str) else value
    try:
        return _STATE_MAP[key]
    except (KeyError, TypeError) as exc:
        raise _export_error(
            "export task status is outside the verified state map",
            code="EXPORT_PROTOCOL_ERROR",
            stage="export_status",
            details={"state_type": type(value).__name__},
        ) from exc


def _job_identifier(value: str) -> str | int:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise _export_error(
            "export job ID is invalid",
            code="EXPORT_JOB_INVALID",
            stage="input",
        )
    stripped = value.strip()
    return int(stripped) if stripped.isdecimal() else stripped


def _first_path(value: Mapping[str, Any], paths: Any) -> Any:
    if not isinstance(paths, (list, tuple)):
        return None
    for path in paths:
        current: Any = value
        for part in str(path).split("."):
            if not isinstance(current, Mapping) or part not in current:
                current = None
                break
            current = current[part]
        if current is not None:
            return current
    return None


def _integer_path(value: Mapping[str, Any], paths: Any) -> int | None:
    raw = _first_path(value, paths)
    if isinstance(raw, bool):
        return None
    try:
        result = int(raw)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _signed_url_expiry(url: str) -> datetime | None:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    for name in ("Expires", "expires", "expiry", "e"):
        values = query.get(name)
        if values and str(values[0]).isdigit():
            value = int(values[0])
            if value > 1_000_000_000:
                return datetime.fromtimestamp(value, timezone.utc)
    sign_time = query.get("q-sign-time")
    if sign_time:
        parts = str(sign_time[0]).split(";")
        if len(parts) == 2 and parts[1].isdigit():
            return datetime.fromtimestamp(int(parts[1]), timezone.utc)
    amz_date = query.get("X-Amz-Date") or query.get("x-amz-date")
    amz_expires = query.get("X-Amz-Expires") or query.get("x-amz-expires")
    if amz_date and amz_expires:
        try:
            started = datetime.strptime(amz_date[0], "%Y%m%dT%H%M%SZ").replace(
                tzinfo=timezone.utc
            )
            return started + timedelta(seconds=int(amz_expires[0]))
        except (TypeError, ValueError):
            return None
    return None
