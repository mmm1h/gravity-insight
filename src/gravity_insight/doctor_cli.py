"""Doctor command orchestration kept out of the shared CLI spine."""

from __future__ import annotations

from typing import Any, Mapping

from . import runtime
from .domains import DOMAIN_OPERATIONS
from .errors import ErrorCategory, ErrorDetail
from .install_doctor import inspect_install_consistency


def run_doctor(args: Any) -> dict[str, Any]:
    installation = inspect_install_consistency()
    if installation["status"] != "pass":
        return _install_failure(installation)

    local = runtime.validate_manifest_json()
    client = runtime.build_client()
    operation_ids = runtime.operation_ids(client.operations())
    result: dict[str, Any] = {
        "status": "pass",
        "live": False,
        "network_called": False,
        "installation": installation,
        **local,
        "registered_operations": len(operation_ids),
        "auth": runtime.credential_status(),
    }
    if not args.live:
        return result
    if callable(getattr(client, "probe_all", None)):
        probes = client.probe_all(max_workers=args.concurrency)
        coverage = probes.get("coverage", {}) if isinstance(probes, Mapping) else {}
        probe_status = (
            str(probes.get("status", "error"))
            if isinstance(probes, Mapping)
            else "error"
        )
        result.update(
            {
                "status": (
                    "pass" if probe_status in {"success", "empty"} else "partial"
                ),
                "live": True,
                "network_called": True,
                "probe_status": probe_status,
                "probes_run": (
                    probes.get("probed", 0) if isinstance(probes, Mapping) else 0
                ),
                "coverage": coverage,
            }
        )
        return result
    operation_id = runtime.resolve_operation_id(
        client, DOMAIN_OPERATIONS["apps.list"]
    )
    schema = runtime.to_jsonable(client.schema(operation_id))
    live_probe = schema.get("live_probe", {}) if isinstance(schema, Mapping) else {}
    if not isinstance(live_probe, Mapping):
        raise ValueError(f"{operation_id} has an invalid live probe contract")
    probe_inputs = live_probe.get("inputs", live_probe.get("input", {}))
    if not isinstance(probe_inputs, Mapping):
        raise ValueError(f"{operation_id} live probe inputs must be an object")
    runtime.call_read(client, operation_id, dict(probe_inputs), read_all=False)
    result.update(
        {
            "live": True,
            "network_called": True,
            "probe_operation_id": operation_id,
            "probe_succeeded": True,
        }
    )
    return result


def _install_failure(installation: Mapping[str, Any]) -> dict[str, Any]:
    reason_code = str(installation["reason_code"])
    detail = ErrorDetail.create(
        reason_code,
        str(installation["message"]),
        category=ErrorCategory.LOCAL,
        retryable=False,
        next_action=str(installation["next_action"]),
    )
    return {
        "schema_version": "gravity-sdk.doctor.v1",
        "ok": False,
        "status": "error",
        "live": False,
        "network_called": False,
        "reason_code": reason_code,
        "installation": dict(installation),
        "error": detail.to_dict(),
    }


__all__ = ["run_doctor"]
