"""Fail-closed RPC guard and facade for external Context Providers."""

from __future__ import annotations

import copy
import json
import queue
import threading
import time
import uuid
from typing import Any, Callable, Mapping

from .errors import ErrorCategory, exit_code_for_category
from .external_context_contract import (
    ExternalContextContractError,
    build_rpc_request,
    compile_external_provider,
    decode_rpc_response,
    normalize_external_context_item,
    resource_is_allowed,
    resource_summary,
)
from .provider_rpc_transport import (
    ProviderTransport,
    ProviderTransportError,
)
from .provider_rpc_state import ProviderRpcState, is_health_failure
from .provider_rpc_reporting import render_rpc_result


_PROCESS_PROVIDER_CAPACITY = 8
_PROCESS_PROVIDER_SLOTS = threading.BoundedSemaphore(_PROCESS_PROVIDER_CAPACITY)
_LOCAL_EXIT = exit_code_for_category(ErrorCategory.LOCAL)
_NULL_STATS = {"internal_requests": None, "retries": None, "cache_hits": None}


class ProviderRpcGuard:
    """Apply one external Provider descriptor to every transport attempt."""

    def __init__(
        self,
        descriptor: Mapping[str, Any],
        transport: ProviderTransport,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        compiled = compile_external_provider(descriptor)
        contract = compiled["contract"]
        if getattr(transport, "kind", None) != contract["transport"]:
            raise ValueError("Provider transport and descriptor disagree")
        self.descriptor = contract
        self.descriptor_digest = compiled["digest"]
        self.transport = transport
        self._clock = clock
        self._local_slots = threading.BoundedSemaphore(
            contract["rpc"]["max_concurrency"]
        )
        self._state = ProviderRpcState(
            contract["rpc"], process_capacity=_PROCESS_PROVIDER_CAPACITY, clock=clock
        )

    def invoke(
        self,
        operation: str,
        payload: Mapping[str, Any],
        *,
        cancellation: threading.Event | None = None,
    ) -> dict[str, Any]:
        early = self._preflight(operation, payload, cancellation)
        if early is not None:
            return early
        request, request_bytes = self._build_request(operation, payload)
        probe = self._state.admit_circuit()
        if probe is None:
            return self._gap(
                operation,
                "PROVIDER_CIRCUIT_OPEN",
                request_id=str(request["request_id"]),
                called=False,
            )
        self._state.increment("logical_calls")
        return self._invoke_attempts(
            request, request_bytes, cancellation=cancellation, probe=probe
        )

    def _preflight(
        self,
        operation: str,
        payload: Mapping[str, Any],
        cancellation: threading.Event | None,
    ) -> dict[str, Any] | None:
        if not isinstance(payload, Mapping):
            raise ExternalContextContractError(
                "PROVIDER_RPC_REQUEST_INVALID", "RPC payload must be an object"
            )
        if operation not in {"list", "search", "read", "list_changed"}:
            raise ExternalContextContractError(
                "PROVIDER_RPC_REQUEST_INVALID", "RPC operation is not read-only"
            )
        if operation not in self.descriptor["capabilities"]["operations"]:
            return self._gap(
                operation,
                "PROVIDER_CAPABILITY_UNSUPPORTED",
                request_id=None,
                called=False,
            )
        if operation == "read":
            resource_uri = payload.get("resource_uri")
            if not isinstance(resource_uri, str):
                raise ExternalContextContractError(
                    "PROVIDER_RPC_REQUEST_INVALID", "read requires a resource URI"
                )
            if not resource_is_allowed(
                resource_uri, self.descriptor["allowed_resource_prefixes"]
            ):
                return self._gap(
                    operation,
                    "PROVIDER_RESOURCE_DENIED",
                    request_id=None,
                    called=False,
                )
        if cancellation is not None and cancellation.is_set():
            self._state.increment("cancellations")
            return self._gap(
                operation,
                "PROVIDER_RPC_CANCELLED",
                request_id=None,
                called=False,
            )
        return None

    def _build_request(
        self, operation: str, payload: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bytes]:
        request = build_rpc_request(
            self.descriptor["uri"],
            operation,
            payload,
            request_id=str(uuid.uuid4()),
        )
        request_bytes = (
            json.dumps(
                request,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        return request, request_bytes

    def _invoke_attempts(
        self,
        request: Mapping[str, Any],
        request_bytes: bytes,
        *,
        cancellation: threading.Event | None,
        probe: bool,
    ) -> dict[str, Any]:
        operation = str(request["operation"])
        request_id = str(request["request_id"])
        maximum_attempts = self.descriptor["rpc"]["max_attempts"]
        called = False
        provider_stats = copy.deepcopy(_NULL_STATS)
        final_reason = "PROVIDER_RPC_UNAVAILABLE"
        for attempt_index in range(maximum_attempts):
            attempt = self._attempt(request, request_bytes, cancellation=cancellation)
            called = called or attempt["called"]
            if attempt["reason"] == "PROVIDER_RPC_CALL_LIMIT":
                final_reason = attempt["reason"]
                break
            if attempt["reason"] == "PROVIDER_RPC_BUSY":
                final_reason = attempt["reason"]
                break
            response = attempt.get("response")
            if response is not None:
                provider_stats = copy.deepcopy(response["stats"])
                terminal, final_reason = self._response_outcome(
                    request,
                    response,
                    called=called,
                    provider_stats=provider_stats,
                    probe=probe,
                )
                if terminal is not None:
                    return terminal
            else:
                final_reason = str(attempt["reason"])
            if (
                final_reason == "PROVIDER_RPC_UNAVAILABLE"
                and attempt_index + 1 < maximum_attempts
            ):
                self._state.increment("retries")
                continue
            break
        if is_health_failure(final_reason):
            self._state.finish_circuit(success=False, probe=probe)
        else:
            self._state.abandon_probe(probe)
        return self._gap(
            operation,
            final_reason,
            request_id=request_id,
            called=called,
            provider_stats=provider_stats,
        )

    def _response_outcome(
        self,
        request: Mapping[str, Any],
        response: Mapping[str, Any],
        *,
        called: bool,
        provider_stats: Mapping[str, Any],
        probe: bool,
    ) -> tuple[dict[str, Any] | None, str]:
        operation = str(request["operation"])
        status = response["status"]
        if status in {"success", "empty"}:
            return (
                self._success_result(
                    operation,
                    request,
                    response,
                    called=called,
                    provider_stats=provider_stats,
                    probe=probe,
                ),
                "",
            )
        reason = {
            "denied": "PROVIDER_RESOURCE_DENIED",
            "unsupported": "PROVIDER_CAPABILITY_UNSUPPORTED",
            "unavailable": "PROVIDER_RPC_UNAVAILABLE",
            "error": "PROVIDER_RPC_ERROR",
        }[status]
        if status in {"denied", "unsupported"}:
            self._state.finish_circuit(success=True, probe=probe)
            return (
                self._gap(
                    operation,
                    reason,
                    request_id=str(request["request_id"]),
                    called=called,
                    provider_stats=provider_stats,
                ),
                reason,
            )
        self._state.record_failure(reason)
        return None, reason

    def metrics(self) -> dict[str, Any]:
        return {
            "schema_version": "gravity.provider-rpc-metrics.v1",
            "provider_uri": self.descriptor["uri"],
            "provider_digest": self.descriptor_digest,
            "enforced_rpc": self._state.stats_snapshot(),
            "circuit": self._state.circuit_snapshot(),
            "provider_internal_io_controlled": False,
            "provider_internal_network": "not_observable",
        }

    def _attempt(
        self,
        request: Mapping[str, Any],
        request_bytes: bytes,
        *,
        cancellation: threading.Event | None,
    ) -> dict[str, Any]:
        blocked = self._reserve_attempt_slots()
        if blocked is not None:
            return {"called": False, "reason": blocked}
        result, cancel_event = self._start_attempt_worker(request, request_bytes)
        return self._await_attempt(
            request,
            result,
            cancel_event,
            cancellation=cancellation,
        )

    def _reserve_attempt_slots(self) -> str | None:
        if not self._local_slots.acquire(blocking=False):
            self._state.increment("busy")
            return "PROVIDER_RPC_BUSY"
        if not _PROCESS_PROVIDER_SLOTS.acquire(blocking=False):
            self._local_slots.release()
            self._state.increment("busy")
            return "PROVIDER_RPC_BUSY"
        if not self._state.start_attempt():
            _PROCESS_PROVIDER_SLOTS.release()
            self._local_slots.release()
            return "PROVIDER_RPC_CALL_LIMIT"
        return None

    def _start_attempt_worker(
        self, request: Mapping[str, Any], request_bytes: bytes
    ) -> tuple[queue.Queue[tuple[str, Any]], threading.Event]:
        result: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
        cancel_event = threading.Event()

        def run() -> None:
            try:
                content = self.transport.invoke(
                    request,
                    request_bytes,
                    timeout_ms=self.descriptor["rpc"]["timeout_ms"],
                    max_output_bytes=self.descriptor["rpc"]["max_output_bytes"],
                    cancellation_grace_ms=self.descriptor["rpc"][
                        "cancellation_grace_ms"
                    ],
                    cancel_event=cancel_event,
                )
                result.put(("result", content))
            except BaseException as exc:
                result.put(("error", exc))
            finally:
                self._release_attempt_slots()

        worker = threading.Thread(
            target=run,
            daemon=True,
            name=f"gravity-provider-{self.descriptor['provider_id']}",
        )
        try:
            worker.start()
        except BaseException:
            self._release_attempt_slots()
            raise
        return result, cancel_event

    def _release_attempt_slots(self) -> None:
        self._state.finish_attempt()
        _PROCESS_PROVIDER_SLOTS.release()
        self._local_slots.release()

    def _await_attempt(
        self,
        request: Mapping[str, Any],
        result: queue.Queue[tuple[str, Any]],
        cancel_event: threading.Event,
        *,
        cancellation: threading.Event | None,
    ) -> dict[str, Any]:
        outer_grace = (
            self.descriptor["rpc"]["cancellation_grace_ms"] / 1000 + 0.25
            if self.descriptor["transport"] == "subprocess"
            else 0.0
        )
        deadline = (
            self._clock()
            + self.descriptor["rpc"]["timeout_ms"] / 1000
            + outer_grace
        )
        while True:
            if cancellation is not None and cancellation.is_set():
                cancel_event.set()
                self._cancel_transport(str(request["request_id"]))
                self._state.increment("cancellations")
                return {"called": True, "reason": "PROVIDER_RPC_CANCELLED"}
            remaining = deadline - self._clock()
            if remaining <= 0:
                cancel_event.set()
                self._cancel_transport(str(request["request_id"]))
                self._state.increment("timeouts")
                return {"called": True, "reason": "PROVIDER_RPC_TIMEOUT"}
            try:
                kind, value = result.get(timeout=min(remaining, 0.01))
            except queue.Empty:
                continue
            if kind == "error":
                reason = _transport_reason(value)
                self._state.record_failure(reason)
                return {"called": True, "reason": reason}
            content = value
            if not isinstance(content, bytes):
                self._state.increment("malformed")
                return {"called": True, "reason": "PROVIDER_RPC_MALFORMED"}
            self._state.increment("output_bytes", len(content))
            self._state.increment("output_tokens", len(content))
            try:
                response, _token_units = decode_rpc_response(
                    content,
                    expected_request_id=str(request["request_id"]),
                    max_output_bytes=self.descriptor["rpc"]["max_output_bytes"],
                    max_output_tokens=self.descriptor["rpc"]["max_output_tokens"],
                )
            except ExternalContextContractError as exc:
                self._state.record_failure(exc.reason_code)
                return {"called": True, "reason": exc.reason_code}
            return {"called": True, "reason": None, "response": response}

    def _success_result(
        self,
        operation: str,
        request: Mapping[str, Any],
        response: Mapping[str, Any],
        *,
        called: bool,
        provider_stats: Mapping[str, Any],
        probe: bool,
    ) -> dict[str, Any]:
        allowed = []
        filtered = 0
        allowed_types = set(self.descriptor["resource_types"])
        prefixes = self.descriptor["allowed_resource_prefixes"]
        for item in response["resources"]:
            if resource_is_allowed(item["uri"], prefixes) and item[
                "resource_type"
            ] in allowed_types:
                allowed.append(item)
            else:
                filtered += 1
        if filtered:
            self._state.increment("permission_filtered", filtered)
        resources: list[dict[str, Any]] = []
        context_items: list[dict[str, Any]] = []
        next_cursor = response["next_cursor"] if allowed else None
        if operation == "read" and response["status"] == "success":
            expected = request["payload"]["resource_uri"]
            if len(allowed) != 1 or allowed[0]["uri"] != expected:
                self._state.record_failure("PROVIDER_RPC_RESPONSE_INVALID")
                self._state.finish_circuit(success=False, probe=probe)
                return self._gap(
                    operation,
                    "PROVIDER_RPC_RESPONSE_INVALID",
                    request_id=str(request["request_id"]),
                    called=called,
                    provider_stats=provider_stats,
                )
            try:
                context_items = [
                    normalize_external_context_item(self.descriptor, allowed[0])
                ]
            except ExternalContextContractError as exc:
                self._state.finish_circuit(success=True, probe=probe)
                return self._gap(
                    operation,
                    exc.reason_code,
                    request_id=str(request["request_id"]),
                    called=called,
                    provider_stats=provider_stats,
                )
        elif operation != "read":
            resources = [resource_summary(item) for item in allowed]
        status = "success" if resources or context_items else "empty"
        self._state.finish_circuit(success=True, probe=probe)
        self._state.increment("successes")
        return render_rpc_result(
            provider_uri=self.descriptor["uri"],
            provider_digest=self.descriptor_digest,
            state=self._state,
            status=status,
            ok=True,
            operation=operation,
            request_id=str(request["request_id"]),
            resources=resources,
            context_items=context_items,
            next_cursor=next_cursor,
            reason_codes=[],
            exit_code=None,
            called=called,
            provider_stats=provider_stats,
        )

    def _gap(
        self,
        operation: str,
        reason: str,
        *,
        request_id: str | None,
        called: bool,
        provider_stats: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._state.increment("gaps")
        return render_rpc_result(
            provider_uri=self.descriptor["uri"],
            provider_digest=self.descriptor_digest,
            state=self._state,
            status="context_gap",
            ok=False,
            operation=operation,
            request_id=request_id,
            resources=[],
            context_items=[],
            next_cursor=None,
            reason_codes=[reason],
            exit_code=_LOCAL_EXIT,
            called=called,
            provider_stats=provider_stats or _NULL_STATS,
        )

    def _cancel_transport(self, request_id: str) -> None:
        thread = threading.Thread(
            target=self.transport.cancel,
            kwargs={
                "request_id": request_id,
                "grace_ms": self.descriptor["rpc"]["cancellation_grace_ms"],
            },
            daemon=True,
            name="gravity-provider-cancel",
        )
        thread.start()
        thread.join(
            timeout=max(
                0.01,
                self.descriptor["rpc"]["cancellation_grace_ms"] / 1000,
            )
        )


def _transport_reason(value: BaseException) -> str:
    if isinstance(value, ProviderTransportError):
        return value.reason_code
    return "PROVIDER_RPC_UNAVAILABLE"
__all__ = ["ProviderRpcGuard"]
