"""Export job state-machine orchestration."""
from __future__ import annotations

import math
from pathlib import Path
import random
import time
from typing import Callable

from .blob import BlobMetadata, BlobPolicy, BlobReceipt, BlobTransferError, SafeBlobTransfer
from .export_models import (
    AuthorizedExportGateway, ExportCreationRequest, ExportJobSnapshot,
    ExportPollingPolicy, ExportPrivacyContract, ExportResult, ExportState,
    _POLLABLE_STATES, _TERMINAL_STATES, _TRANSITIONS,
    _assert_exportable_classification, _export_error, _safe_failure_code,
    _validate_creation_request,
)
from .export_privacy import ExportPrivacyFinalizer

class ExportOrchestrator:
    def __init__(
        self,
        gateway: AuthorizedExportGateway,
        transfer: SafeBlobTransfer,
        *,
        polling_policy: ExportPollingPolicy | None = None,
        monotonic_clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        random_source: Callable[[], float] = random.random,
    ) -> None:
        self._gateway = gateway
        self._transfer = transfer
        self._polling = polling_policy or ExportPollingPolicy()
        self._clock = monotonic_clock
        self._sleeper = sleeper
        self._random = random_source

    def start(
        self,
        request: ExportCreationRequest,
        destination: str | Path,
        blob_policy: BlobPolicy,
        privacy_contract: ExportPrivacyContract,
        *,
        timeout_seconds: float | None = None,
    ) -> ExportResult:
        tracker = _StateTracker(ExportState.CREATING)
        try:
            _validate_creation_request(request, privacy_contract)
        except BlobTransferError as exc:
            tracker.move(ExportState.FAILED)
            return _result(tracker, job_id=None, error=exc)

        timeout = _validated_timeout(timeout_seconds, self._polling.timeout_seconds)
        deadline = self._clock() + timeout
        try:
            # Creation is deliberately attempted once.  The gateway must not add
            # retries until the upstream idempotency contract is verified.
            snapshot = self._gateway.create(request, timeout_seconds=timeout)
        except BlobTransferError as exc:
            tracker.move(ExportState.FAILED)
            return _result(tracker, job_id=None, error=exc)
        except Exception:
            error = _export_error(
                "export creation failed and was not retried",
                code="EXPORT_CREATE_FAILED",
                stage="creating",
                retryable=False,
            )
            tracker.move(ExportState.FAILED)
            return _result(tracker, job_id=None, error=error)
        try:
            state = _validate_snapshot(snapshot)
            tracker.move(state)
        except BlobTransferError as exc:
            tracker.move(ExportState.FAILED)
            raw_job_id = getattr(snapshot, "job_id", None)
            safe_job_id = raw_job_id if isinstance(raw_job_id, str) and raw_job_id else None
            return _result(tracker, job_id=safe_job_id, error=exc)
        return self._drive(
            snapshot,
            tracker,
            deadline,
            destination,
            blob_policy,
            privacy_contract,
        )

    def resume(
        self,
        job_id: str,
        destination: str | Path,
        blob_policy: BlobPolicy,
        privacy_contract: ExportPrivacyContract,
        *,
        timeout_seconds: float | None = None,
    ) -> ExportResult:
        if not job_id.strip():
            raise _export_error(
                "resume requires a non-empty export job ID",
                code="EXPORT_JOB_INVALID",
                stage="resume",
            )
        _assert_exportable_classification(privacy_contract)
        timeout = _validated_timeout(timeout_seconds, self._polling.timeout_seconds)
        deadline = self._clock() + timeout
        try:
            snapshot = self._gateway.status(job_id, timeout_seconds=timeout)
            state = _validate_snapshot(snapshot, expected_job_id=job_id)
        except BlobTransferError:
            raise
        except Exception as exc:
            raise _export_error(
                "could not read resumable export status",
                code="EXPORT_STATUS_FAILED",
                stage="resume",
                retryable=True,
                details={"job_id": job_id},
            ) from exc
        tracker = _StateTracker(state)
        return self._drive(
            snapshot,
            tracker,
            deadline,
            destination,
            blob_policy,
            privacy_contract,
        )

    def cancel(self, job_id: str) -> ExportResult:
        if not bool(getattr(self._gateway, "supports_cancel", False)):
            raise _export_error(
                "the export gateway has no verified cancel contract",
                code="CANCEL_UNSUPPORTED",
                stage="cancel",
                details={"job_id": job_id},
            )
        try:
            snapshot = self._gateway.cancel(
                job_id,
                timeout_seconds=self._polling.timeout_seconds,
            )
            state = _validate_snapshot(snapshot, expected_job_id=job_id)
        except BlobTransferError:
            raise
        except Exception as exc:
            raise _export_error(
                "export cancel outcome is uncertain",
                code="EXPORT_CANCEL_FAILED",
                stage="cancel",
                details={"job_id": job_id, "write_may_have_occurred": True},
            ) from exc
        tracker = _StateTracker(state)
        return _result(
            tracker,
            job_id=job_id,
            resumable=state not in _TERMINAL_STATES,
        )

    def _drive(
        self,
        snapshot: ExportJobSnapshot,
        tracker: _StateTracker,
        deadline: float,
        destination: str | Path,
        blob_policy: BlobPolicy,
        privacy_contract: ExportPrivacyContract,
    ) -> ExportResult:
        job_id = snapshot.job_id
        interval = self._polling.initial_interval_seconds
        while tracker.state in _POLLABLE_STATES:
            remaining = deadline - self._clock()
            if remaining <= 0:
                return self._timed_out(tracker, job_id)
            jittered = _jittered_interval(
                interval,
                self._polling.max_interval_seconds,
                self._polling.jitter_ratio,
                self._random(),
            )
            self._sleeper(min(jittered, remaining))
            if self._clock() >= deadline:
                return self._timed_out(tracker, job_id)
            try:
                snapshot = self._gateway.status(
                    job_id,
                    timeout_seconds=max(deadline - self._clock(), 0.001),
                )
                state = _validate_snapshot(snapshot, expected_job_id=job_id)
            except BlobTransferError as exc:
                tracker.move(ExportState.FAILED)
                return _result(tracker, job_id=job_id, error=exc)
            except Exception:
                interval = min(
                    interval * self._polling.multiplier,
                    self._polling.max_interval_seconds,
                )
                continue
            try:
                tracker.move(state)
            except BlobTransferError as exc:
                tracker.move(ExportState.FAILED)
                return _result(tracker, job_id=job_id, error=exc)
            interval = min(
                interval * self._polling.multiplier,
                self._polling.max_interval_seconds,
            )

        if tracker.state == ExportState.FAILED:
            error = _export_error(
                "upstream export job failed",
                code=_safe_failure_code(snapshot.failure_code),
                stage="polling",
                retryable=snapshot.failure_retryable,
                details={"job_id": job_id},
            )
            return _result(tracker, job_id=job_id, error=error)
        if tracker.state == ExportState.CANCELLED:
            return _result(tracker, job_id=job_id)
        if tracker.state != ExportState.READY:
            error = _export_error(
                "export reached an unsupported state",
                code="EXPORT_PROTOCOL_ERROR",
                stage="polling",
                details={"job_id": job_id, "state": tracker.state.value},
            )
            if tracker.state not in _TERMINAL_STATES:
                tracker.move(ExportState.FAILED)
            return _result(tracker, job_id=job_id, error=error)
        if self._clock() >= deadline:
            return self._timed_out(tracker, job_id)
        return self._download(
            snapshot,
            tracker,
            destination,
            blob_policy,
            privacy_contract,
        )

    def _download(
        self,
        snapshot: ExportJobSnapshot,
        tracker: _StateTracker,
        destination: str | Path,
        blob_policy: BlobPolicy,
        privacy_contract: ExportPrivacyContract,
    ) -> ExportResult:
        job_id = snapshot.job_id
        source = snapshot.download_source
        if source is None or source.job_id != job_id:
            error = _export_error(
                "READY status lacks a job-bound authorized download source",
                code="EXPORT_DOWNLOAD_SOURCE_INVALID",
                stage="ready",
                details={"job_id": job_id},
            )
            tracker.move(ExportState.FAILED)
            return _result(tracker, job_id=job_id, error=error)
        tracker.move(ExportState.DOWNLOADING)

        def observe(stage: str, metadata: BlobMetadata) -> None:
            if stage != "verified":
                raise _export_error(
                    "blob transfer emitted an unknown stage",
                    code="EXPORT_PROTOCOL_ERROR",
                    stage="downloading",
                )
            tracker.move(ExportState.VERIFIED)

        try:
            receipt = self._transfer.download(
                source,
                destination,
                blob_policy,
                finalizer=ExportPrivacyFinalizer(privacy_contract),
                observer=observe,
            )
            tracker.move(ExportState.COMMITTED)
            return _result(tracker, job_id=job_id, receipt=receipt)
        except BlobTransferError as exc:
            if tracker.state not in _TERMINAL_STATES:
                tracker.move(ExportState.FAILED)
            return _result(tracker, job_id=job_id, error=exc)
        except Exception:
            error = _export_error(
                "export download failed",
                code="EXPORT_DOWNLOAD_FAILED",
                stage="downloading",
            )
            if tracker.state not in _TERMINAL_STATES:
                tracker.move(ExportState.FAILED)
            return _result(tracker, job_id=job_id, error=error)

    def _timed_out(self, tracker: _StateTracker, job_id: str) -> ExportResult:
        tracker.move(ExportState.TIMED_OUT)
        error = _export_error(
            "export polling timed out; the upstream job was not cancelled",
            code="EXPORT_TIMEOUT",
            stage="polling",
            retryable=True,
            details={"job_id": job_id, "cancelled": False},
        )
        return _result(
            tracker,
            job_id=job_id,
            error=error,
            resumable=True,
        )
class _StateTracker:
    def __init__(self, initial: ExportState) -> None:
        self.state = initial
        self.history: list[ExportState] = [initial]

    def move(self, target: ExportState) -> None:
        if target == self.state:
            return
        if target not in _TRANSITIONS[self.state]:
            raise _export_error(
                "export state transition is not allowed",
                code="EXPORT_STATE_INVALID",
                stage="state_machine",
                details={"from": self.state.value, "to": target.value},
            )
        self.state = target
        self.history.append(target)
def _validate_snapshot(
    snapshot: ExportJobSnapshot,
    *,
    expected_job_id: str | None = None,
) -> ExportState:
    if not isinstance(snapshot, ExportJobSnapshot) or not snapshot.job_id.strip():
        raise _export_error(
            "export gateway returned an invalid normalized snapshot",
            code="EXPORT_PROTOCOL_ERROR",
            stage="status",
        )
    if expected_job_id is not None and snapshot.job_id != expected_job_id:
        raise _export_error(
            "export status job ID changed",
            code="EXPORT_PROTOCOL_ERROR",
            stage="status",
            details={"expected_job_id": expected_job_id},
        )
    try:
        state = snapshot.state if isinstance(snapshot.state, ExportState) else ExportState(snapshot.state)
    except (TypeError, ValueError) as exc:
        raise _export_error(
            "export gateway returned an unknown state",
            code="EXPORT_PROTOCOL_ERROR",
            stage="status",
        ) from exc
    if state in {ExportState.CREATING, ExportState.DOWNLOADING, ExportState.VERIFIED, ExportState.COMMITTED, ExportState.TIMED_OUT}:
        raise _export_error(
            "upstream gateway returned an SDK-owned state",
            code="EXPORT_PROTOCOL_ERROR",
            stage="status",
            details={"state": state.value},
        )
    return state


def _validated_timeout(value: float | None, default: float) -> float:
    timeout = default if value is None else value
    try:
        normalized = float(timeout)
    except (TypeError, ValueError) as exc:
        raise _export_error(
            "export timeout is invalid",
            code="EXPORT_TIMEOUT_INVALID",
            stage="configuration",
        ) from exc
    if isinstance(timeout, bool) or normalized <= 0 or not math.isfinite(normalized):
        raise _export_error(
            "export timeout must be finite and positive",
            code="EXPORT_TIMEOUT_INVALID",
            stage="configuration",
        )
    return normalized


def _jittered_interval(
    base: float,
    maximum: float,
    jitter_ratio: float,
    random_value: float,
) -> float:
    try:
        numeric_random = float(random_value)
    except (TypeError, ValueError) as exc:
        raise _export_error(
            "poll random source returned an invalid value",
            code="EXPORT_POLL_CONFIGURATION_INVALID",
            stage="configuration",
        ) from exc
    if not math.isfinite(numeric_random):
        raise _export_error(
            "poll random source returned a non-finite value",
            code="EXPORT_POLL_CONFIGURATION_INVALID",
            stage="configuration",
        )
    bounded_random = min(max(numeric_random, 0.0), 1.0)
    factor = 1.0 + jitter_ratio * (2.0 * bounded_random - 1.0)
    return min(maximum, max(0.0, base * factor))


def _result(
    tracker: _StateTracker,
    *,
    job_id: str | None,
    receipt: BlobReceipt | None = None,
    error: BlobTransferError | None = None,
    resumable: bool = False,
) -> ExportResult:
    return ExportResult(
        state=tracker.state,
        job_id=job_id,
        history=tuple(tracker.history),
        receipt=receipt,
        error=error,
        resumable=resumable,
    )
