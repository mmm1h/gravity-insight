"""Privacy-safe runtime verification metadata for Gravity operations."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .drift import HealthOverlay, operation_availability, operation_health
from .errors import (
    ErrorCategory,
    InputValidationError,
    OperationNotImplementedError,
    UnknownOperationError,
    error_detail_from_exception,
)
from .fingerprints import (
    contract_fingerprint,
    legacy_contract_fingerprint,
    migrate_catalog_fingerprints,
    write_json_atomic,
)
from .models import OperationSpec
from .operation_search import (
    expose_non_callable_result as _expose_non_callable_result,
    normalize_search_text as _normalize_search_text,
    ordered_search as _ordered_search,
    search_page_limit as _search_page_limit,
    search_score as _search_score,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class OperationProbe:
    last_verified_at: str | None = None
    status: str = "unverified"
    schema_fingerprint: str | None = None
    warnings_count: int = 0
    last_attempted_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_attempted_at": self.last_attempted_at, "last_verified_at": self.last_verified_at,
            "status": self.status, "schema_fingerprint": self.schema_fingerprint, "warnings_count": self.warnings_count,
        }


def _json_copy(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _load_catalog_drafts(compiled_ids: set[str]) -> tuple[tuple[OperationSpec, ...], dict[str, Mapping[str, Any]]]:
    draft_root = Path(__file__).resolve().parent / "contracts" / "drafts"
    if not draft_root.is_dir():
        return (), {}
    specs: list[OperationSpec] = []
    metadata: dict[str, Mapping[str, Any]] = {}
    seen = set(compiled_ids)
    for path in sorted(draft_root.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        operation, draft = document["operation"], document["draft"]
        operation_id = str(operation["operation_id"])
        if operation_id in seen:
            continue
        runtime = _json_copy(operation)
        if runtime.get("pagination", {}).get("kind") == "unverified":
            runtime["pagination"] = {"kind": "none"}
        spec = OperationSpec.from_dict(runtime)
        if spec.executable or draft.get("status") != "draft":
            continue
        seen.add(operation_id)
        specs.append(spec)
        metadata[operation_id] = {"operation": _json_copy(operation), "draft": _json_copy(draft)}
    return tuple(specs), metadata


def _draft_description(metadata: Mapping[str, Any], provenance: Mapping[str, Any]) -> dict[str, Any]:
    draft = metadata.get("draft")
    if not isinstance(draft, Mapping):
        return {}
    blockers = draft.get("blockers")
    safe_blockers = (
        [dict(item) for item in blockers if isinstance(item, Mapping)]
        if isinstance(blockers, list) else None
    )
    coverage = draft.get("coverage_reference")
    gate = draft.get("promotion_gate")
    codes = [str(item.get("code")) for item in safe_blockers or () if item.get("code")]
    operation = metadata.get("operation")
    operation_id = str(operation.get("operation_id", "<operation-id>")) if isinstance(operation, Mapping) else "<operation-id>"
    return {
        "draft_status": str(draft.get("status", "draft")), "blockers": safe_blockers,
        "blockers_status": "known" if safe_blockers is not None else "unknown",
        "promotion_gate": dict(gate) if isinstance(gate, Mapping) else None,
        "next_action": _draft_next_action(operation_id, codes),
        "user_can_unlock": False,
        "provenance": {**dict(provenance), "source_kind": "census_draft",
                       "census_route": dict(coverage) if isinstance(coverage, Mapping) else None},
    }


def _draft_error(metadata: Mapping[str, Any]) -> OperationNotImplementedError:
    draft = metadata.get("draft")
    blockers = draft.get("blockers") if isinstance(draft, Mapping) else None
    codes = [str(item.get("code")) for item in blockers if isinstance(item, Mapping) and item.get("code")] if isinstance(blockers, list) else []
    rendered = ", ".join(codes) if codes else "unknown"
    operation = metadata.get("operation") if isinstance(metadata, Mapping) else None
    operation_id = str(operation.get("operation_id", "<operation-id>")) if isinstance(operation, Mapping) else "<operation-id>"
    return OperationNotImplementedError(f"operation is catalog-only; open draft blockers: {rendered}",
                                        next_action=_draft_next_action(operation_id, codes))


def _draft_next_action(operation_id: str, blocker_codes: Iterable[str]) -> str:
    rendered = ", ".join(blocker_codes) or "unknown"
    return ("This operation is discoverable but disabled because the SDK lacks enough "
            f"verified request/response evidence (blockers: {rendered}). An SDK caller cannot unlock it. "
            f"Contact the Gravity Insight SDK maintainers with operation_id `{operation_id}` and these blocker codes; "
            "ask them to verify it on an authorized account that satisfies the listed data or credential requirements and publish it as executable. Until then, search for a stable executable alternative.")


class OperationCatalog:
    """Immutable operation inventory plus minimal, value-free probe history."""

    def __init__(
        self,
        operations: Iterable[OperationSpec],
        *,
        clock: Callable[[], datetime] = _utc_now,
        state_path: Path | None = None,
        contract_metadata: Mapping[str, Mapping[str, Any]] | None = None,
        health_overlay: HealthOverlay | None = None,
    ) -> None:
        operation_list = tuple(operations)
        compiled_ids = {item.operation_id for item in operation_list}
        draft_specs, draft_metadata = _load_catalog_drafts(compiled_ids) if contract_metadata is not None else ((), {})
        catalog_operations = operation_list + draft_specs
        self._draft_ids = frozenset(item.operation_id for item in draft_specs)
        self._catalog_statuses = dict.fromkeys(self._draft_ids, "draft_catalog_only")
        self._specs = {item.operation_id: item for item in catalog_operations}
        self._operations = {
            item.operation_id: item.operation_summary() for item in catalog_operations
        }
        self._contract_fingerprints = {item.operation_id: _contract_fingerprint(item) for item in catalog_operations}
        self._clock = clock
        self._lock = threading.RLock()
        self._probes = {item.operation_id: OperationProbe() for item in catalog_operations}
        self._state_path = state_path
        metadata = dict(contract_metadata or {})
        metadata.update(draft_metadata)
        self._contract_metadata = {operation_id: dict(value) for operation_id, value in metadata.items()
                                   if operation_id in self._operations}
        self._health_overlay = HealthOverlay.from_environment(health_overlay)
        self._load_state()

    def search(
        self,
        query: str,
        *,
        domain: str | None = None,
        platform: str | None = None,
        stability: str | None = None,
        limit: int = 20,
        continuation: str | None = None,
    ) -> dict[str, Any]:
        """Return a deterministic lexical/semantic operation search page."""

        if not isinstance(query, str) or not query.strip():
            raise InputValidationError(
                "operation search query must be a non-empty string", field="query"
            )
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 20:
            raise InputValidationError(
                "operation search limit must be between 1 and 20", field="limit"
            )
        normalized_query = _normalize_search_text(query)
        signature = {
            "query": normalized_query,
            "domain": domain,
            "platform": platform,
            "stability": stability,
            "limit": limit, "catalog": _catalog_signature(self._specs.values()),
        }
        offset = _decode_continuation(continuation, signature) if continuation else 0
        scored = _search_candidates(
            self._specs,
            self._operations,
            self._probes,
            self._catalog_statuses,
            self._health_overlay,
            normalized_query,
            domain,
            platform,
            stability,
        )
        ordered = _expose_non_callable_result(
            _ordered_search(scored, normalized_query), limit, stability
        )
        if offset > len(ordered):
            raise InputValidationError(
                "operation search continuation is outside the result set",
                field="continuation",
            )
        page_limit = _search_page_limit(
            ordered,
            limit,
            continuation=continuation,
            stability=stability,
        )
        page = ordered[offset : offset + page_limit]
        next_offset = offset + len(page)
        token = (
            _encode_continuation(signature, next_offset)
            if next_offset < len(ordered)
            else None
        )
        return {
            "schema_version": "gravity-insight.operation-search.v1",
            "ok": True,
            "status": "success",
            "query": query,
            "count": len(page),
            "total": len(ordered),
            "limit": limit,
            "continuation_token": token,
            "presentation": {
                "mode": "callable_stable_first",
                "non_callable_total": sum(
                    not bool(item.get("executable", True)) for item in ordered
                ),
                "non_callable_shown": sum(
                    not bool(item.get("executable", True)) for item in page
                ),
            },
            "operations": page,
        }

    def describe(self, operation_id: str) -> dict[str, Any]:
        operation = self._specs.get(operation_id)
        if operation is None:
            raise UnknownOperationError(f"unknown Gravity operation: {operation_id}")
        operation_summary = self._operations[operation_id]
        schema = operation.schema()
        metadata = self._contract_metadata.get(operation_id, {})
        source_operation = metadata.get("operation", metadata)
        if not isinstance(source_operation, Mapping):
            source_operation = {}
        request = source_operation.get("request")
        if not isinstance(request, Mapping):
            request = {}
        privacy = source_operation.get("privacy_policy")
        if not isinstance(privacy, Mapping):
            privacy = {}
        sensitive_names = {str(name).casefold() for name in privacy.get("redact_fields", ())}
        parent_values = source_operation.get("required_parent")
        if not isinstance(parent_values, list):
            parent_values = []
        parents = []
        for parent in parent_values:
            if not isinstance(parent, Mapping):
                continue
            parents.append(
                {
                    "operation_id": parent.get("operation_id"),
                    "output_path": parent.get("output_path"),
                    "selection": parent.get("selection"),
                    "target_input": parent.get("input_field")
                    or _infer_target_input(source_operation, parent),
                }
            )
        pagination = source_operation.get("pagination")
        if not isinstance(pagination, Mapping):
            pagination = schema.get("pagination", {})
        examples = source_operation.get("examples", [])
        if not isinstance(examples, list):
            examples = []
        probe = self._probes.get(operation_id, OperationProbe())
        provenance = source_operation.get("provenance")
        if not isinstance(provenance, Mapping):
            provenance = {}
        result = {
            "schema_version": "gravity-insight.operation-description.v1",
            "ok": True,
            "status": "success",
            "operation_id": operation_id,
            "domain": operation_summary.get("domain"),
            "resource": operation_summary.get("resource"),
            "action": operation_summary.get("action"),
            "platform": operation_summary.get("platform"),
            "description": operation_summary.get("description", ""),
            "contract_version": operation_summary.get("contract_version"),
            "stability": operation_summary.get("stability"),
            "executable": operation_summary.get("executable", True),
            "block_reason": operation_summary.get("block_reason"),
            "catalog_status": self._catalog_statuses.get(operation_id, "registered"),
            "currently_callable": bool(operation_summary.get("executable", True)),
            "effect": source_operation.get("effect", "read"),
            "input_schema": schema.get("input_fields", {}),
            "wire": {
                "method": getattr(operation, "upstream_method", None),
                "path_template": getattr(operation, "path_template", None),
                "query": {
                    "input_fields": list(request.get("query_fields", ())),
                    "fixed": _safe_fixed_values(
                        request.get("fixed_query"), sensitive_names
                    ),
                },
                "body": {
                    "input_fields": list(request.get("body_fields", ())),
                    "fixed": _safe_fixed_values(request.get("fixed_body"), sensitive_names),
                },
            },
            "response_projection": schema.get("response_projection", {}),
            "pagination": dict(pagination),
            "privacy": {
                "classification": privacy.get(
                    "classification",
                    schema.get("privacy", {}).get("classification")
                    if isinstance(schema.get("privacy"), Mapping)
                    else None,
                ),
                "redact_fields": sorted(str(name) for name in privacy.get("redact_fields", ())),
            },
            "examples": examples,
            "examples_status": (
                "complete"
                if examples
                else "unknown"
                if operation_summary.get("stability") == "stable"
                else "not_provided"
            ),
            "examples_unknown_reason": (
                None
                if examples or operation_summary.get("stability") != "stable"
                else "minimum input depends on account or live metadata values"
            ),
            "required_parent": parents,
            "health": {
                "status": operation_health(operation_summary, probe.status, self._health_overlay, operation_id),
                "probe": probe.to_dict(),
                "contract_fingerprint": self._contract_fingerprints[operation_id],
            },
            "provenance": dict(provenance),
        }
        result.update(_draft_description(metadata, provenance))
        return result

    def guard(self, operation_id: str) -> dict[str, Any]:
        """Reject catalog-only drafts, then enforce the active health overlay."""

        if operation_id in self._draft_ids:
            raise _draft_error(self._contract_metadata.get(operation_id, {}))
        if self._health_overlay is not None:
            return self._health_overlay.guard(operation_id)
        return {"allowed": True, "error_code": None, "warning": None, "retry": False}

    def record(
        self,
        operation_id: str,
        *,
        status: str,
        schema_fingerprint: str | None = None,
        warnings_count: int = 0,
        verified_at: str | None = None,
    ) -> None:
        if operation_id not in self._operations:
            return
        safe_status = status if status in _CATALOG_STATUSES - {"unverified"} else "error"
        safe_fingerprint = (
            schema_fingerprint if isinstance(schema_fingerprint, str) and len(schema_fingerprint) == 64
            and all(character in "0123456789abcdef" for character in schema_fingerprint.casefold())
            else None
        )
        try:
            warning_count = max(0, int(warnings_count))
        except (TypeError, ValueError):
            warning_count = 0
        attempted_at = _safe_timestamp(verified_at) or self._clock().astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        with self._lock:
            previous = self._probes[operation_id]
            verified = safe_status in _VERIFIED_STATUSES
            self._probes[operation_id] = OperationProbe(
                last_attempted_at=attempted_at,
                last_verified_at=attempted_at if verified else previous.last_verified_at,
                status=safe_status,
                schema_fingerprint=safe_fingerprint if verified else previous.schema_fingerprint,
                warnings_count=warning_count,
            )
            self._persist_state()

    def record_upstream_exception(
        self, operation_id: str, error: Exception, *, status: str
    ) -> None:
        if error_detail_from_exception(error).category == ErrorCategory.UPSTREAM.value:
            self.record(operation_id, status=status)

    def record_envelope(self, operation_id: str, envelope: Mapping[str, Any]) -> None:
        error = envelope.get("error")
        if isinstance(error, Mapping) and error.get("category") != "upstream":
            return
        warnings = envelope.get("warnings")
        self.record(
            operation_id,
            status=str(envelope.get("status", "error")),
            schema_fingerprint=str(envelope["schema_fingerprint"]) if envelope.get("schema_fingerprint") is not None else None,
            warnings_count=len(warnings) if isinstance(warnings, (list, tuple)) else 0,
            verified_at=str(envelope["fetched_at"]) if envelope.get("fetched_at") is not None else None,
        )

    def probe(self, operation_id: str) -> dict[str, Any]:
        with self._lock:
            probe = self._probes.get(operation_id)
        if probe is None:
            raise KeyError(operation_id)
        return {
            **probe.to_dict(),
            "contract_fingerprint": self._contract_fingerprints[operation_id],
        }

    def merge(self, operations: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        with self._lock:
            probes = dict(self._probes)
            contract_fingerprints = dict(self._contract_fingerprints)
        for operation in operations:
            item = dict(operation)
            operation_id = str(item.get("operation_id", ""))
            stability = str(item.get("stability", ""))
            item["availability_status"] = operation_availability(
                stability,
                executable=bool(item.get("executable", True)),
                block_reason=(
                    str(item["block_reason"]) if item.get("block_reason") else None
                ),
                health_overlay=self._health_overlay,
                operation_id=operation_id,
            )
            item["probe"] = {
                **probes.get(operation_id, OperationProbe()).to_dict(),
                "contract_fingerprint": contract_fingerprints.get(operation_id),
            }
            merged.append(item)
        return merged

    def coverage(
        self,
        *,
        domain: str | None = None,
        platform: str | None = None,
        stability: str | None = "stable",
    ) -> dict[str, Any]:
        operations = list(self._operations.values())
        if domain is not None:
            operations = [item for item in operations if item.get("domain") == domain]
        if platform is not None:
            operations = [item for item in operations if item.get("platform") == platform]
        if stability is not None:
            operations = [item for item in operations if item.get("stability") == stability]
        with self._lock:
            probes = {str(item["operation_id"]): self._probes[str(item["operation_id"])] for item in operations}
        status_counts = Counter(probe.status for probe in probes.values())
        verified = sum(count for status, count in status_counts.items() if status in _VERIFIED_STATUSES)
        attempted = len(probes) - status_counts.get("unverified", 0)
        failed = attempted - verified
        total = len(operations)
        return {
            "total": total, "verified": verified, "attempted": attempted,
            "failed": failed, "unverified": total - attempted,
            "coverage_ratio": (verified / total) if total else 0.0,
            "status_counts": dict(sorted(status_counts.items())),
            "stability_counts": dict(sorted(Counter(str(item.get("stability")) for item in operations).items())),
            "domain_counts": dict(sorted(Counter(str(item.get("domain")) for item in operations).items())),
            "platform_counts": dict(
                sorted(Counter(str(item.get("platform") or "unscoped") for item in operations).items())
            ),
        }

    def _load_state(self) -> None:
        if self._state_path is None:
            return
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        if not isinstance(raw, Mapping) or raw.get("schema_version") != 2:
            return
        probes = raw.get("probes")
        if not isinstance(probes, Mapping):
            return
        migrated: dict[str, str] = {}
        for operation_id, value in probes.items():
            if operation_id not in self._probes or not isinstance(value, Mapping):
                continue
            saved_fingerprint = value.get("contract_fingerprint")
            current_fingerprint = self._contract_fingerprints[operation_id]
            legacy_fingerprint = legacy_contract_fingerprint(self._specs[operation_id])
            if saved_fingerprint == current_fingerprint:
                pass
            elif saved_fingerprint == legacy_fingerprint:
                migrated[operation_id] = current_fingerprint
            else:
                continue
            status = str(value.get("status", "unverified"))
            if status not in _CATALOG_STATUSES:
                continue
            fingerprint = value.get("schema_fingerprint")
            if not _safe_fingerprint(fingerprint):
                fingerprint = None
            self._probes[operation_id] = OperationProbe(
                last_attempted_at=_safe_timestamp(value.get("last_attempted_at")),
                last_verified_at=_safe_timestamp(value.get("last_verified_at")),
                status=status,
                schema_fingerprint=fingerprint,
                warnings_count=_safe_warning_count(value.get("warnings_count")),
            )
        if migrated:
            migrate_catalog_fingerprints(self._state_path, raw, migrated)

    def _persist_state(self) -> None:
        if self._state_path is None:
            return
        payload = {
            "schema_version": 2,
            "probes": {
                operation_id: {
                    **probe.to_dict(),
                    "contract_fingerprint": self._contract_fingerprints[operation_id],
                }
                for operation_id, probe in sorted(self._probes.items())
                if probe.status != "unverified"
            },
        }
        write_json_atomic(self._state_path, payload)


def _search_candidates(
    specs: Mapping[str, OperationSpec], operations: Mapping[str, Mapping[str, Any]],
    probes: Mapping[str, OperationProbe], catalog_statuses: Mapping[str, str],
    overlay: HealthOverlay | None, query: str, domain: str | None,
    platform: str | None, stability: str | None,
) -> list[tuple[int, str, dict[str, Any]]]:
    scored: list[tuple[int, str, dict[str, Any]]] = []
    for operation_id in specs:
        operation = operations[operation_id]
        if domain is not None and operation.get("domain") != domain:
            continue
        if platform is not None and operation.get("platform") != platform:
            continue
        if stability is not None and operation.get("stability") != stability:
            continue
        score, matched_on = _search_score(
            query, operation_id=operation_id, domain=str(operation.get("domain", "")),
            resource=str(operation.get("resource", "")), platform=str(operation.get("platform") or ""),
            description=str(operation.get("description", "")))
        if score <= 0:
            continue
        probe = probes.get(operation_id, OperationProbe())
        item = {**dict(operation),
                "health": operation_health(operation, probe.status, overlay, operation_id),
                "catalog_status": catalog_statuses.get(operation_id, "registered"),
                "matched_on": matched_on, "score": score}
        scored.append((score, operation_id, item))
    return scored


def _catalog_signature(operations: Iterable[Any]) -> str:
    values = [
        (str(getattr(operation, "operation_id", "")), str(getattr(operation, "contract_version", "")))
        for operation in operations
    ]
    encoded = json.dumps(sorted(values), separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _encode_continuation(signature: Mapping[str, Any], offset: int) -> str:
    payload = {"v": 1, "offset": offset, **dict(signature)}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_continuation(token: str, signature: Mapping[str, Any]) -> int:
    try:
        padding = "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode((token + padding).encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputValidationError("operation search continuation is invalid", field="continuation") from exc
    if not isinstance(payload, Mapping) or payload.get("v") != 1:
        raise InputValidationError(
            "operation search continuation is invalid", field="continuation"
        )
    expected = {"v": 1, **dict(signature)}
    if any(payload.get(key) != value for key, value in expected.items()):
        raise InputValidationError(
            "operation search continuation does not match this query",
            field="continuation",
        )
    offset = payload.get("offset")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise InputValidationError(
            "operation search continuation is invalid", field="continuation"
        )
    return offset


def _safe_fixed_values(value: Any, sensitive_names: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for name, item in value.items():
        lowered = str(name).casefold()
        sensitive = lowered in sensitive_names or any(
            marker in lowered
            for marker in ("token", "password", "secret", "authorization", "cookie")
        )
        result[str(name)] = "[REDACTED]" if sensitive else item
    return result


def _contains_placeholder(value: Any, placeholders: tuple[str, ...]) -> bool:
    if isinstance(value, str):
        return any(
            value == placeholder or placeholder.endswith("*") and value.startswith(placeholder[:-1])
            for placeholder in placeholders
        )
    if isinstance(value, Mapping):
        return any(_contains_placeholder(item, placeholders) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_placeholder(item, placeholders) for item in value)
    return False


def _infer_target_input(
    source_operation: Mapping[str, Any], parent: Mapping[str, Any]
) -> str | None:
    operation_id = str(parent.get("operation_id", ""))
    placeholders: tuple[str, ...]
    if operation_id == "app.list":
        placeholders = ("$first_app_id",)
    elif operation_id == "analysis.event.list":
        placeholders = ("$first_event_name",)
    elif operation_id == "analysis.event.info":
        placeholders = ("$first_event_property_name",)
    elif operation_id == "analysis.user_property.list":
        placeholders = ("$first_user_property_name",)
    elif operation_id == "analysis.segment.list":
        placeholders = ("$first_segment_id",)
    elif operation_id == "analysis.report_config.list":
        placeholders = ("$first_report_config_id",)
    elif operation_id in {"analysis.dashboard.tree", "analysis.dashboard.detail"}:
        placeholders = ("$first_dashboard_id", "$first_dashboard_space_id")
    elif operation_id == "analysis.order_detail.list":
        placeholders = ("$first_order_*",)
    elif operation_id == "analysis.user_detail.list":
        placeholders = ("$first_client_id",)
    elif operation_id.startswith("promotion.") and operation_id.endswith(
        ".advertiser.list"
    ):
        platform = operation_id.split(".", 2)[1]
        placeholders = (f"$first_{platform}_advertiser_id",)
    elif operation_id == "report.multidim.template.preset.list":
        placeholders = (
            "$first_preset_template_id",
            "$first_preset_template_category",
        )
    elif operation_id == "report.multidim.query":
        return "data_list" if "data_list" in source_operation.get("input_fields", {}) else None
    else:
        return None
    probe = source_operation.get("live_probe")
    inputs = probe.get("inputs") if isinstance(probe, Mapping) else None
    if not isinstance(inputs, Mapping):
        return None
    candidates = [
        str(name)
        for name, value in inputs.items()
        if _contains_placeholder(value, placeholders)
    ]
    return candidates[0] if len(candidates) == 1 else None


_VERIFIED_STATUSES = frozenset({"success", "empty", "contract_changed_additive"})
_CATALOG_STATUSES = _VERIFIED_STATUSES | frozenset({
    "contract_changed", "partial", "parent_required", "permission_unavailable",
    "semantic_error", "unavailable", "error", "unverified",
})


def _contract_fingerprint(operation: OperationSpec) -> str:
    """Return the shared semantic identity used by registry and probe state."""
    return contract_fingerprint(operation)


def _safe_fingerprint(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and not set(value.casefold()) - set("0123456789abcdef")


def _safe_warning_count(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _safe_timestamp(value: str | None) -> str | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
