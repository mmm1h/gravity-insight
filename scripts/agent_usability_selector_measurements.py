"""Independent checks and explicit limits for selector self-reported fields."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
from typing import Any


RESULT_REASON_MEASUREMENT_REASON = (
    "the harness observes the text and selected selectors but has no independent "
    "selector decision trace"
)
MEANINGFUL_ACCURACY_MEASUREMENT_REASON = (
    "meaningful_accuracy_evidence is plugin-reported without an independently "
    "verifiable evidence reference"
)
STDIN_ENCODING_MEASUREMENT_REASON = (
    "the parent sends UTF-8 bytes but cannot observe the arbitrary child process's "
    "decoder or sys.stdin.encoding value"
)
ADDITIONAL_METADATA_MEASUREMENT_REASON = (
    "additional provider, model, request, token, or latency metadata is reported by "
    "the uninstrumented plugin without an external receipt"
)


def canonical_request_text(request: Mapping[str, Any]) -> str:
    return json.dumps(
        request, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def request_sha256(request: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_request_text(request).encode("utf-8")).hexdigest()


def validate_request_sha256(
    metadata: Mapping[str, Any], request: Mapping[str, Any]
) -> None:
    reported = metadata.get("request_sha256")
    if reported is not None and reported != request_sha256(request):
        raise ValueError(
            "external selector metadata.request_sha256 does not match the "
            "canonical UTF-8 request; hash the exact request object with "
            "sorted keys and compact JSON separators"
        )


def validate_selector_version_binding(
    receipts: Sequence[Mapping[str, Any]],
    *,
    plugin_path: Path,
    plugin_sha256: str,
) -> str:
    current_sha256 = hashlib.sha256(plugin_path.read_bytes()).hexdigest()
    if current_sha256 != plugin_sha256:
        raise ValueError(
            "external selector plugin bytes changed during evaluation; restore one "
            "stable plugin file and rerun"
        )
    versions = {
        str(receipt.get("selector", "")).strip()
        for receipt in receipts
        if isinstance(receipt, Mapping)
    }
    if len(versions) != 1:
        rendered = ", ".join(sorted(version or "<empty>" for version in versions))
        raise ValueError(
            "external selector metadata.selector changed for one plugin SHA-256 "
            f"({plugin_sha256}): {rendered}; report one stable selector version"
        )
    return next(iter(versions))


def self_report_measurements() -> dict[str, dict[str, Any]]:
    return {
        "result_reason": _unmeasured(RESULT_REASON_MEASUREMENT_REASON),
        "selector_version_plugin_sha_binding": _measured(),
        "meaningful_accuracy_evidence": _unmeasured(
            MEANINGFUL_ACCURACY_MEASUREMENT_REASON
        ),
        "request_sha256": _measured(),
        "stdin_encoding": _unmeasured(STDIN_ENCODING_MEASUREMENT_REASON),
        "additional_metadata": _unmeasured(ADDITIONAL_METADATA_MEASUREMENT_REASON),
    }


def _measured() -> dict[str, Any]:
    return {"measured": True, "measurement_reason": None}


def _unmeasured(reason: str) -> dict[str, Any]:
    return {"measured": False, "measurement_reason": reason}


__all__ = [
    "canonical_request_text",
    "request_sha256",
    "self_report_measurements",
    "validate_request_sha256",
    "validate_selector_version_binding",
]
