"""Export methods mixed into the public Gravity Insight client."""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from .blob import SafeBlobTransfer
from .errors import ErrorCategory, ErrorCode, ErrorDetail, InputValidationError
from .export_contracts import (
    ExportContractRegistry,
    export_error_field, validate_export_payload,
    validate_wire_projection,
)
from .export_gateway import ExportTaskCenter, GravityExportGateway
from .export_file import export_file_policies
from .export_models import (
    ExportCreationRequest, ExportPollingPolicy, ExportPrivacyContract, ExportState,
    _export_error, _validate_creation_request,
)
from .export_state import ExportOrchestrator
from .registry import PolicyEngine, Registry
from .paths import CONTRACT_ROOT
from .result_source import GOVERNED_PRODUCT, result_source


def load_export_components(
    root: Path,
    registry: Registry,
    *,
    allow_experimental: bool,
) -> tuple[ExportContractRegistry, PolicyEngine]:
    contracts = ExportContractRegistry.from_file(
        CONTRACT_ROOT / "exports" / "routes-v1.json"
    )
    policy = PolicyEngine(
        registry,
        allow_experimental=allow_experimental,
        effect_routes=contracts.effect_routes(),
    )
    return contracts, policy


class ExportClientMixin:
    def export_capabilities(self) -> dict[str, Any]:
        contracts, _, _ = self._export_components()
        values = [contract.capability() for contract in contracts.all()]
        return {
            "schema_version": "gravity-insight.export-capabilities.v1",
            "ok": True,
            "status": "success",
            "count": len(values),
            "callable_count": sum(
                bool(item["currently_callable"]) for item in values
            ),
            "callable_create_count": sum(
                bool(item["currently_callable"])
                and item["effect"] == "export_job_create"
                for item in values
            ),
            "operations": values,
            "next_action": (
                "Run `gravity export describe "
                "<operation-id>` for the input schema and workflow."
            ),
        }

    def export_describe(self, operation_id: str) -> dict[str, Any]:
        contracts, _, _ = self._export_components()
        return contracts.describe(operation_id)

    def export_start(
        self,
        operation_id: str,
        payload: Mapping[str, Any],
        *,
        requested_columns: Sequence[str],
        idempotency_key: str,
        timeout_seconds: float = 120.0,
    ) -> dict[str, Any]:
        request, privacy = self._export_request(
            operation_id,
            payload,
            requested_columns=requested_columns,
            idempotency_key=idempotency_key,
        )
        _validate_creation_request(request, privacy)
        snapshot = self._export_gateway(operation_id).create(
            request,
            timeout_seconds=timeout_seconds,
        )
        return _export_snapshot_envelope(operation_id, snapshot)

    def export_status(
        self,
        operation_id: str,
        job_id: str,
        *,
        timeout_seconds: float = 120.0,
    ) -> dict[str, Any]:
        snapshot = self._export_gateway(operation_id).status(
            job_id,
            timeout_seconds=timeout_seconds,
        )
        return _export_snapshot_envelope(operation_id, snapshot)

    def export_wait(
        self,
        operation_id: str,
        job_id: str,
        *,
        interval_seconds: float = 2.0,
        timeout_seconds: float = 300.0,
    ) -> dict[str, Any]:
        interval = float(interval_seconds)
        timeout = float(timeout_seconds)
        if interval < 2:
            raise InputValidationError(
                "export wait interval must be at least 2 seconds",
                field="interval",
                next_action=(
                    "Run `gravity export wait "
                    f"{job_id} --operation-id {operation_id} --interval 2 "
                    "--timeout 300`."
                ),
            )
        if timeout <= 0 or timeout > 300:
            raise InputValidationError(
                "export wait timeout must be between 0 and 300 seconds",
                field="timeout",
                next_action=(
                    "Run `gravity export wait "
                    f"{job_id} --operation-id {operation_id} --interval 2 "
                    "--timeout 300`."
                ),
            )
        gateway = self._export_gateway(operation_id)
        deadline = time.monotonic() + timeout
        polls = 0
        while True:
            snapshot = gateway.status(job_id, timeout_seconds=min(120.0, timeout))
            polls += 1
            if snapshot.state not in {
                ExportState.QUEUED,
                ExportState.RUNNING,
                ExportState.CANCEL_REQUESTED,
            }:
                if snapshot.state == ExportState.FAILED:
                    return _export_failed_snapshot_envelope(
                        operation_id, snapshot, polls
                    )
                envelope = _export_snapshot_envelope(operation_id, snapshot)
                envelope["polls"] = polls
                return envelope
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise _export_error(
                    "export polling timed out; the upstream task was not cancelled",
                    code="EXPORT_TIMEOUT",
                    stage="polling",
                    retryable=True,
                    details={"job_id": job_id, "cancelled": False},
                )
            time.sleep(min(interval, remaining))

    def export_download(
        self,
        operation_id: str,
        job_id: str,
        destination: str | Path,
        *,
        timeout_seconds: float = 300.0,
    ) -> dict[str, Any]:
        contract = self._export_contract(operation_id)
        destination_path = Path(destination).resolve()
        blob_policy, privacy = export_file_policies(
            contract,
            destination_path.parent,
        )
        result = ExportOrchestrator(
            self._export_gateway(operation_id),
            SafeBlobTransfer(),
            polling_policy=_polling_policy(timeout_seconds),
        ).resume(
            job_id,
            destination_path.name,
            blob_policy,
            privacy,
            timeout_seconds=min(float(timeout_seconds), 300.0),
        )
        return _export_result_envelope(operation_id, result)

    def export_run(
        self,
        operation_id: str,
        payload: Mapping[str, Any],
        destination: str | Path,
        *,
        requested_columns: Sequence[str],
        idempotency_key: str,
        timeout_seconds: float = 300.0,
    ) -> dict[str, Any]:
        request, logical_privacy = self._export_request(
            operation_id,
            payload,
            requested_columns=requested_columns,
            idempotency_key=idempotency_key,
        )
        destination_path = Path(destination).resolve()
        contract = self._export_contract(operation_id)
        blob_policy, file_privacy = export_file_policies(
            contract,
            destination_path.parent,
        )
        request_columns = tuple(
            str(value)
            for value in contract.privacy.get(
                "request_columns",
                file_privacy.allowed_columns,
            )
        )
        if logical_privacy.allowed_columns != request_columns:
            raise _export_error(
                "logical export projection disagrees with the route contract",
                code="EXPORT_PROTOCOL_ERROR",
                stage="configuration",
            )
        result = ExportOrchestrator(
            self._export_gateway(operation_id),
            SafeBlobTransfer(),
            polling_policy=_polling_policy(timeout_seconds),
        ).start(
            request,
            destination_path.name,
            blob_policy,
            file_privacy,
            timeout_seconds=min(float(timeout_seconds), 300.0),
        )
        return _export_result_envelope(operation_id, result)

    def export_cancel(self, operation_id: str, job_id: str) -> dict[str, Any]:
        gateway = self._export_gateway(operation_id)
        result = ExportOrchestrator(
            gateway,
            SafeBlobTransfer(),
            polling_policy=ExportPollingPolicy(
                timeout_seconds=120.0,
                initial_interval_seconds=2.0,
            ),
        ).cancel(job_id)
        envelope = _export_result_envelope(operation_id, result)
        envelope["cancel_requested"] = True
        envelope["next_action"] = (
            "Run `gravity export status "
            f"{job_id} --operation-id {operation_id}`; cancellation is not terminal."
        )
        return envelope

    def export_list(self, *, page: int = 1, page_size: int = 100) -> dict[str, Any]:
        contracts, policy, export_runtime = self._export_components()
        if page < 1:
            raise InputValidationError(
                "export list page must be at least 1",
                field="page",
                next_action=(
                    "Run `gravity export list --page 1 "
                    "--page-size 100`."
                ),
            )
        if not 1 <= page_size <= 300:
            raise InputValidationError(
                "export list page_size must be between 1 and 300",
                field="page_size",
                next_action=(
                    "Run `gravity export list --page 1 "
                    "--page-size 100`."
                ),
            )
        return ExportTaskCenter(contracts, policy, export_runtime).list(
            page=page,
            page_size=page_size,
        )

    def _export_request(
        self,
        operation_id: str,
        payload: Mapping[str, Any],
        *,
        requested_columns: Sequence[str],
        idempotency_key: str,
    ) -> tuple[ExportCreationRequest, ExportPrivacyContract]:
        contract = self._export_contract(operation_id)
        validate_export_payload(contract, payload)
        file_allowed = tuple(
            str(value) for value in contract.privacy.get("allowed_columns", [])
        )
        request_allowed = tuple(
            str(value)
            for value in contract.privacy.get("request_columns", file_allowed)
        )
        request_required = tuple(
            str(value)
            for value in contract.privacy.get(
                "request_required_columns",
                request_allowed,
            )
        )
        if not request_allowed:
            raise _export_error(
                "export operation has no approved column allowlist",
                code="EXPORT_PRIVACY_DENIED",
                stage="privacy_policy",
            )
        request = ExportCreationRequest(
            payload=payload,
            requested_columns=tuple(str(value) for value in requested_columns),
            idempotency_key=idempotency_key,
        )
        privacy = ExportPrivacyContract(
            allowed_columns=request_allowed,
            required_columns=request_required,
            classification=str(contract.privacy.get("classification", "restricted")),
        )
        validate_wire_projection(contract, request)
        return request, privacy

    def _export_contract(self, operation_id: str) -> Any:
        contracts, policy, _ = self._export_components()
        policy.authorize_effect_operation(
            operation_id,
            expected_effect="export_job_create",
        )
        return contracts.get(operation_id)

    def _export_gateway(self, operation_id: str) -> GravityExportGateway:
        contracts, policy, export_runtime = self._export_components()
        return GravityExportGateway(
            contracts,
            policy,
            export_runtime,
            operation_id,
        )

    def _export_components(
        self,
    ) -> tuple[ExportContractRegistry, PolicyEngine, Any]:
        if (
            self._export_contracts is None
            or self._export_policy is None
            or self._export_runtime is None
        ):
            raise _export_error(
                "export runtime is unavailable for this client",
                code="NOT_IMPLEMENTED",
                stage="configuration",
            )
        return self._export_contracts, self._export_policy, self._export_runtime


def _polling_policy(timeout_seconds: float) -> ExportPollingPolicy:
    return ExportPollingPolicy(
        timeout_seconds=min(float(timeout_seconds), 300.0),
        initial_interval_seconds=2.0,
        multiplier=1.5,
        max_interval_seconds=15.0,
        jitter_ratio=0.1,
    )


def _export_snapshot_envelope(operation_id: str, snapshot: Any) -> dict[str, Any]:
    return {
        "schema_version": "gravity-insight.export.v1", "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "success",
        "operation_id": operation_id,
        "job_id": snapshot.job_id,
        "state": (
            snapshot.state.value
            if isinstance(snapshot.state, ExportState)
            else str(snapshot.state)
        ),
        "download_ready": snapshot.download_source is not None,
        "failure_code": snapshot.failure_code,
        "retryable": bool(snapshot.failure_retryable),
    }


def _export_failed_snapshot_envelope(
    operation_id: str,
    snapshot: Any,
    polls: int,
) -> dict[str, Any]:
    detail = ErrorDetail.create(
        ErrorCode.UPSTREAM_UNAVAILABLE,
        "export job reached terminal FAILED state; no file is available",
        operation_id=operation_id,
        retryable=False,
        next_action=(
            "Run `gravity export list --page 1 "
            "--page-size 100` to record the terminal job, then run "
            f"`gravity export describe {operation_id}` "
            "before requesting authorization for a new input."
        ),
    )
    return {
        "schema_version": "gravity-insight.error.v1", "result_source": result_source(GOVERNED_PRODUCT),
        "ok": False,
        "status": "error",
        "operation_id": operation_id,
        "job_id": snapshot.job_id,
        "state": ExportState.FAILED.value,
        "polls": polls,
        "failure_code": snapshot.failure_code,
        "error": detail.to_dict(),
    }


def _export_result_envelope(operation_id: str, result: Any) -> dict[str, Any]:
    if result.error is not None:
        detail = _export_result_error_detail(operation_id, result)
        return {
            "schema_version": "gravity-insight.error.v1",
            "result_source": result_source(GOVERNED_PRODUCT),
            "ok": False,
            "status": "error",
            "operation_id": operation_id,
            "job_id": result.job_id,
            "state": result.state.value,
            "history": [state.value for state in result.history],
            "resumable": result.resumable,
            "error": detail.to_dict(),
        }
    return {
        "schema_version": "gravity-insight.export.v1",
        "result_source": result_source(GOVERNED_PRODUCT),
        "ok": True,
        "status": "success",
        "operation_id": operation_id,
        "job_id": result.job_id,
        "state": result.state.value,
        "history": [state.value for state in result.history],
        "resumable": result.resumable,
        "file": _file_receipt(result.receipt),
    }


def _export_result_error_detail(operation_id: str, result: Any) -> ErrorDetail:
    code = str(getattr(result.error, "code", "UPSTREAM_UNAVAILABLE"))
    public_code, next_action = _public_export_error(code, operation_id, result.job_id)
    return ErrorDetail.create(
        public_code,
        result.error,
        operation_id=operation_id,
        category=(
            ErrorCategory.LOCAL if code == "EXPORT_PRIVACY_DENIED" else None
        ),
        field=export_error_field(code),
        retryable=bool(getattr(result.error, "retryable", False)),
        next_action=next_action,
    )


def _public_export_error(
    code: str,
    operation_id: str,
    job_id: str | None,
) -> tuple[ErrorCode, str]:
    input_codes = {
        "EXPORT_COLUMNS_INVALID",
        "EXPORT_JOB_INVALID",
        "EXPORT_IDEMPOTENCY_KEY_INVALID",
        "EXPORT_TIMEOUT_INVALID",
    }
    local_codes = {"LOCAL_IO_ERROR", "BLOB_PATH_UNSAFE", "BLOB_PATH_REPARSE"}
    contract_codes = {
        "EXPORT_PRIVACY_DENIED",
        "EXPORT_SCHEMA_MISMATCH",
        "EXPORT_FORMAT_INVALID",
        "EXPORT_FORMAT_UNSUPPORTED",
        "BLOB_MIME_MISMATCH",
        "BLOB_TYPE_MISMATCH",
        "BLOB_MAGIC_MISMATCH",
    }
    if code == "EXPORT_TIMEOUT":
        return ErrorCode.EXPORT_TIMEOUT, (
            "Run `gravity export status "
            f"{job_id} --operation-id {operation_id}`, then resume with "
            "`export download` when READY."
        )
    if code in input_codes:
        return ErrorCode.INPUT_INVALID, (
            "Run `gravity export describe "
            f"{operation_id}` and retry `gravity export run` with the documented "
            "input and an explicit output file."
        )
    if code in local_codes:
        return ErrorCode.LOCAL_IO_ERROR, (
            "Run `gravity export download "
            f"{job_id or '<job-id>'} --operation-id {operation_id} --output "
            "<writable-file.xlsx> --timeout 300`."
        )
    if code in contract_codes:
        return ErrorCode.CONTRACT_CHANGED, (
            "Run `gravity export describe "
            f"{operation_id}` and stop automation until the maintainer republishes "
            "a verified contract."
        )
    return ErrorCode.UPSTREAM_UNAVAILABLE, (
        "Run `gravity export list --page 1 --page-size "
        "100` to determine whether a job was created; do not create a duplicate."
    )


def _file_receipt(receipt: Any) -> dict[str, Any] | None:
    if receipt is None:
        return None
    return {
        "path": str(receipt.destination),
        "size_bytes": receipt.size_bytes,
        "source_size_bytes": receipt.source_size_bytes,
        "source_sha256": receipt.source_sha256,
        "committed_sha256": receipt.committed_sha256,
        "content_type": receipt.content_type,
        "extension": receipt.extension,
        "etag_present": receipt.etag is not None,
        "last_modified_present": receipt.last_modified is not None,
        "schema": list(receipt.finalization.schema),
        "rows": receipt.finalization.rows_processed,
    }


__all__ = ["ExportClientMixin", "load_export_components"]
