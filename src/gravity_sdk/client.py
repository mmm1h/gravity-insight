"""Public manifest-driven Gravity Insight client."""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .cache import MetadataCache, is_metadata_operation
from .catalog import OperationCatalog
from .credentials import CredentialProvider
from .drift import aggregate_contract_status
from .errors import ErrorCode, ErrorDetail, GravityInsightError, InputValidationError, PaginationError, ParentRequiredError, PermissionUnavailableError, PolicyViolation, UnknownOperationError, UpstreamError, error_detail_from_exception
from .executor import ReadExecutor
from .export_batch import batch_input_error, validate_batch_item
from .export_client import ExportClientMixin, load_export_components
from .export_validation import validate_export_input
from .field_policy import FieldPolicy
from .fingerprints import shape_fingerprint
from .http_runtime import (
    DEFAULT_CONCURRENCY, MAX_CONCURRENCY, GravityHttpRuntime, get_shared_runtime,
)
from .models import BatchRequest, BatchResult, OperationSpec, ReadResult, load_operation_manifest
from .paths import CONTRACT_ROOT, MANIFEST_ROOT, PROJECT_ROOT
from .registry import PolicyEngine, Registry
from .transport import Transport


_LOGGER = logging.getLogger("gravity_sdk")
_MAX_READ_PAGES = 1_000
_MAX_READ_ITEMS = 100_000


class GravityInsightClient(ExportClientMixin):
    """Stable facade over private, versioned Gravity read APIs."""

    def __init__(
        self,
        registry: Registry,
        executor: ReadExecutor,
        *,
        allow_experimental: bool = False,
        metadata_cache: MetadataCache | None = None,
        capability_catalog: OperationCatalog | None = None,
        field_policy: FieldPolicy | None = None,
        export_components: tuple[Any, Any, Any] | None = None,
    ) -> None:
        self._registry = registry
        self._executor = executor
        self.allow_experimental = allow_experimental
        self._metadata_cache = metadata_cache or MetadataCache(
            operation.operation_id for operation in registry.all() if is_metadata_operation(operation)
        )
        self._operation_catalog = capability_catalog or OperationCatalog(registry.all())
        self._field_policy = field_policy or FieldPolicy()
        self._export_contracts, self._export_policy, self._export_runtime = (
            export_components or (None, None, None)
        )
        self._probe_lock = threading.Lock()
        self._probe_values: dict[str, Any] = {}
        self._executor._bind_call_guard(self._operation_catalog.guard)
        self._executor._bind_field_validator(self._validate_field_request)

    @classmethod
    def from_env(
        cls,
        *,
        allow_experimental: bool = False,
        session: Any | None = None,
        credentials: CredentialProvider | None = None,
        transport: Transport | None = None,
        runtime: GravityHttpRuntime | None = None,
        timeout: float = 120.0,
        attempts: int = 3,
    ) -> "GravityInsightClient":
        root = PROJECT_ROOT
        manifests = MANIFEST_ROOT
        paths = sorted(manifests.glob("*.json")) if manifests.is_dir() else []
        if not paths:
            from .errors import ManifestError

            raise ManifestError("no Gravity Insight JSON manifests were found")
        operations: list[OperationSpec] = []
        for path in paths:
            operations.extend(load_operation_manifest(path))
        registry = Registry(operations)
        policy = PolicyEngine(registry, allow_experimental=allow_experimental)
        if transport is not None and runtime is not None:
            raise ValueError("transport and runtime cannot both be supplied")
        if transport is not None:
            request_transport = transport
        else:
            if runtime is None:
                runtime = (
                    get_shared_runtime(
                        env_path=root / ".env.gravity.local",
                        timeout=timeout,
                        attempts=attempts,
                    )
                    if session is None and credentials is None
                    else GravityHttpRuntime(
                        env_path=root / ".env.gravity.local",
                        session=session,
                        credentials=credentials,
                        timeout=timeout,
                        attempts=attempts,
                    )
                )
            request_transport = Transport(
                policy=policy,
                timeout=timeout,
                attempts=attempts,
                runtime=runtime,
            )
        cache_root = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_CACHE_HOME")
        catalog_path = (
            Path(cache_root) / "GravityInsight" / "capability-catalog.json"
            if cache_root
            else Path.home() / ".cache" / "gravity-insight" / "capability-catalog.json"
        )
        export_contracts, export_policy = load_export_components(
            root,
            registry,
            allow_experimental=allow_experimental,
        )
        return cls(
            registry,
            ReadExecutor(registry, policy, request_transport),
            allow_experimental=allow_experimental,
            capability_catalog=OperationCatalog(
                registry.all(),
                state_path=catalog_path,
                contract_metadata=_load_contract_metadata(
                    CONTRACT_ROOT / "operations"
                ),
            ),
            export_components=(
                export_contracts,
                export_policy,
                getattr(request_transport, "_runtime", runtime),
            ),
        )

    @classmethod
    def _from_manifest_for_tests(
        cls,
        manifest: Any,
        *,
        transport: Any,
        allow_experimental: bool = False,
    ) -> "GravityInsightClient":
        if transport is None or not getattr(transport, "is_test_transport", False):
            raise TypeError("tests must inject an explicit fake transport")
        registry = Registry(load_operation_manifest(manifest))
        policy = PolicyEngine(registry, allow_experimental=allow_experimental)
        return cls(
            registry,
            ReadExecutor(registry, policy, transport),
            allow_experimental=allow_experimental,
        )

    def capabilities(
        self,
        *,
        domain: str | None = None,
        platform: str | None = None,
        stability: str | None = "stable",
        include_probe_metadata: bool = True,
    ) -> list[dict[str, object]]:
        operations = self._registry.capabilities(
            domain=domain, platform=platform, stability=stability
        )
        return (
            self._operation_catalog.merge(operations)
            if include_probe_metadata
            else operations
        )

    def capability_coverage(
        self,
        *,
        domain: str | None = None,
        platform: str | None = None,
        stability: str | None = "stable",
    ) -> dict[str, Any]:
        return self._operation_catalog.coverage(
            domain=domain, platform=platform, stability=stability
        )

    def schema(self, operation_id: str | None = None) -> dict[str, object]:
        return self._registry.schema(operation_id)

    def search_capabilities(
        self,
        query: str,
        *,
        domain: str | None = None,
        platform: str | None = None,
        stability: str | None = "stable",
        limit: int = 20,
        continuation: str | None = None,
    ) -> dict[str, Any]:
        return self._operation_catalog.search(
            query,
            domain=domain,
            platform=platform,
            stability=stability,
            limit=limit,
            continuation=continuation,
        )

    def describe(self, operation_id: str) -> dict[str, Any]:
        return self._operation_catalog.describe(operation_id)

    def validate(
        self,
        operation_id: str,
        inputs: Mapping[str, Any] | None = None,
        *, render_wire: bool = False,
    ) -> dict[str, Any]:
        if operation_id.startswith("export."):
            return validate_export_input(self, operation_id, inputs, render_wire=render_wire)

        try:
            operation = self._executor._policy.authorize_operation(operation_id)
            normalized = operation.validate_inputs(inputs)
        except GravityInsightError as exc:
            return _validation_error(operation_id, exc)
        state = "valid_offline"
        dependencies: list[str] = []

        def offline_metadata_loader(
            dependency_operation_id: str, _inputs: Mapping[str, Any]
        ) -> Mapping[str, Any]:
            dependencies.append(dependency_operation_id)
            raise _OfflineMetadataRequired(dependency_operation_id)

        try:
            self._field_policy.validate(
                operation, normalized, offline_metadata_loader
            )
        except _OfflineMetadataRequired:
            state = "needs_live_metadata"
        except GravityInsightError as exc:
            return _validation_error(operation_id, exc)

        result: dict[str, Any] = {
            "schema_version": "gravity-insight.validation.v1",
            "ok": True,
            "status": state,
            "operation_id": operation_id,
            "network_called": False,
            "normalized_input": _redact_operation_values(operation, normalized),
            "live_metadata_dependencies": list(dict.fromkeys(dependencies)),
            "error": None,
        }
        if render_wire:
            authorization = self._executor._policy._prepare_request(
                operation_id, normalized
            )
            query, body = self._executor._policy._consume_request(
                authorization,
                operation=authorization.operation,
                method=authorization.method,
                path=authorization.path,
                query=authorization.query,
                body=authorization.body,
            )
            path = authorization.path
            if any(
                operation.fields[name].sensitive
                for name in operation.path_fields
                if name in operation.fields
            ):
                path = operation.path_template
            result["wire"] = {
                "method": authorization.method,
                "path": path,
                "query": _redact_operation_values(operation, query),
                "body": _redact_operation_values(operation, body),
            }
        return result

    def probe(self, operation_id: str) -> dict[str, Any]:
        operation = self._executor._policy.authorize_operation(operation_id)
        if not operation.live_probe.enabled:
            raise PolicyViolation("operation has no enabled minimum live probe")
        inputs = self._resolve_probe_inputs(operation.live_probe.inputs)
        return self.read(operation_id, inputs)

    def probe_all(
        self,
        *,
        domain: str | None = None,
        platform: str | None = None,
        max_workers: int = DEFAULT_CONCURRENCY,
    ) -> dict[str, Any]:
        operations = [
            operation
            for operation in self._registry.all()
            if operation.stability == "stable"
            and operation.live_probe.enabled
            and (domain is None or operation.domain == domain)
            and (platform is None or operation.platform == platform)
        ]
        requests: list[dict[str, Any]] = []
        resolution_failures: dict[str, dict[str, Any]] = {}
        for operation in operations:
            try:
                inputs = self._resolve_probe_inputs(operation.live_probe.inputs)
            except GravityInsightError as exc:
                envelope = self._error_envelope(operation.operation_id, exc)
                self._operation_catalog.record_envelope(operation.operation_id, envelope)
                resolution_failures[operation.operation_id] = BatchResult(
                    operation.operation_id,
                    False,
                    str(envelope["status"]),
                    envelope,
                    operation.operation_id,
                    envelope["error"],
                ).to_dict()
                continue
            requests.append(
                {
                    "operation_id": operation.operation_id,
                    "request_id": operation.operation_id,
                    "inputs": inputs,
                }
            )
        completed = self.batch(requests, max_workers=max_workers) if requests else []
        completed_by_id = {
            str(item.get("operation_id")): item for item in completed
        }
        results = [
            resolution_failures.get(operation.operation_id)
            or completed_by_id[operation.operation_id]
            for operation in operations
        ]
        return {
            "schema_version": "gravity-insight.probe.v1",
            "status": (
                "success"
                if results
                and all(item.get("status") in {"success", "empty"} for item in results)
                else "empty"
                if not results
                else "partial"
            ),
            "probed": len(results),
            "coverage": self.capability_coverage(
                domain=domain, platform=platform, stability="stable"
            ),
            "results": results,
        }

    def _resolve_probe_inputs(self, value: Any) -> Any:
        if value == "$today":
            return date.today().isoformat()
        if value == "$yesterday":
            return (date.today() - timedelta(days=1)).isoformat()
        if value == "$analysis_query_id":
            return _new_analysis_query_id()
        if value == "$first_app_id":
            return self._first_probe_app_id()
        if value == "$first_event_name":
            return self._first_probe_event_name()
        if value == "$first_user_property_name":
            return self._first_probe_user_property_name()
        if value == "$first_event_property_name":
            return self._first_probe_event_property_name()
        if value == "$first_segment_id":
            return self._first_probe_segment_id()
        if value == "$first_report_config_id":
            return self._first_probe_report_config_id()
        if value == "$first_dashboard_id":
            return self._first_probe_dashboard_field("dashboard_id")
        if value == "$first_dashboard_space_id":
            return self._first_probe_dashboard_field("space_id")
        if value == "$first_client_id":
            return self._first_probe_client_id()
        if isinstance(value, str) and value.startswith("$first_order_"):
            field = value.removeprefix("$first_order_")
            return self._first_probe_order_field(field)
        if isinstance(value, str) and value.startswith("$first_") and value.endswith(
            "_advertiser_id"
        ):
            platform = value.removeprefix("$first_").removesuffix("_advertiser_id")
            if platform in {"bytedance", "tencent", "kuaishou"}:
                return self._first_probe_advertiser_id(platform)
        if isinstance(value, str) and value in {
            "$first_preset_template_id",
            "$first_preset_template_category",
        }:
            field = value.removeprefix("$first_preset_template_")
            return self._first_probe_preset_template_field(field)
        if isinstance(value, str) and value.startswith("$"):
            raise PolicyViolation("live probe contains an unsupported dynamic placeholder")
        if isinstance(value, Mapping):
            return {
                str(key): self._resolve_probe_inputs(item) for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self._resolve_probe_inputs(item) for item in value]
        return value

    def _first_probe_app_id(self) -> str:
        with self._probe_lock:
            cached = self._probe_values.get("first_app_id")
            if isinstance(cached, str) and cached:
                return cached
            envelope = self.read("app.list", {"page": 1, "page_size": 1})
            rows = _envelope_rows(envelope)
            app_id = rows[0].get("id") if rows else None
            if not isinstance(app_id, (str, int)) or isinstance(app_id, bool):
                raise PermissionUnavailableError(
                    "no readable App is available for the minimum report probe"
                )
            resolved = str(app_id)
            self._probe_values["first_app_id"] = resolved
            return resolved

    def _first_probe_advertiser_id(self, platform: str) -> str:
        cache_key = f"first_{platform}_advertiser_id"
        with self._probe_lock:
            cached = self._probe_values.get(cache_key)
            if isinstance(cached, str) and cached:
                return cached
            parent_id = f"promotion.{platform}.advertiser.list"
            parent = self._registry.get(parent_id)
            if not parent.live_probe.enabled:
                raise PermissionUnavailableError(
                    f"{platform} advertiser parent has no minimum live probe"
                )
            envelope = self.read(
                parent_id,
                self._resolve_probe_inputs(parent.live_probe.inputs),
            )
            rows = _envelope_rows(envelope)
            advertiser_id = rows[0].get("advertiser_id") if rows else None
            if not isinstance(advertiser_id, (str, int)) or isinstance(
                advertiser_id, bool
            ):
                raise PermissionUnavailableError(
                    f"no readable {platform} advertiser is available for the minimum material probe"
                )
            resolved = str(advertiser_id)
            self._probe_values[cache_key] = resolved
            return resolved

    def _first_probe_event_name(self) -> str:
        app_id = self._first_probe_app_id()
        cache_key = f"first_event_name:{app_id}"
        with self._probe_lock:
            cached = self._probe_values.get(cache_key)
            if isinstance(cached, str) and cached:
                return cached
            envelope = self.read(
                "analysis.event.list",
                {"app_id": app_id, "page": 1, "page_size": 1},
            )
            rows = _envelope_rows(envelope)
            event_name = rows[0].get("name") if rows else None
            if not isinstance(event_name, str) or not event_name:
                raise PermissionUnavailableError(
                    "no readable event is available for the minimum analysis probe"
                )
            self._probe_values[cache_key] = event_name
            return event_name

    def _first_probe_user_property_name(self) -> str:
        app_id = self._first_probe_app_id()
        cache_key = f"first_user_property_name:{app_id}"
        with self._probe_lock:
            cached = self._probe_values.get(cache_key)
            if isinstance(cached, str) and cached:
                return cached
            envelope = self.read_all(
                "analysis.user_property.list",
                {"app_id": app_id, "page": 1, "page_size": 100},
                max_pages=10,
                max_items=1_000,
            )
            property_name = _first_enumerable_property(_envelope_rows(envelope))
            if property_name is None:
                raise PermissionUnavailableError(
                    "no enumerable user property is available for the minimum analysis probe"
                )
            self._probe_values[cache_key] = property_name
            return property_name

    def _first_probe_event_property_name(self) -> str:
        app_id = self._first_probe_app_id()
        event_name = self._first_probe_event_name()
        cache_key = f"first_event_property_name:{app_id}:{event_name}"
        with self._probe_lock:
            cached = self._probe_values.get(cache_key)
            if isinstance(cached, str) and cached:
                return cached
            envelope = self.read(
                "analysis.event.info",
                {"app_id": app_id, "event_name": event_name},
            )
            data = envelope.get("data")
            properties = data.get("properties") if isinstance(data, Mapping) else None
            rows: list[Mapping[str, Any]] = []
            if isinstance(properties, Mapping):
                for group in ("common", "custom", "preset"):
                    values = properties.get(group)
                    if isinstance(values, list):
                        rows.extend(item for item in values if isinstance(item, Mapping))
            property_name = _first_enumerable_property(rows)
            if property_name is None:
                raise PermissionUnavailableError(
                    "no enumerable event property is available for the minimum analysis probe"
                )
            self._probe_values[cache_key] = property_name
            return property_name

    def _first_probe_segment_id(self) -> str:
        app_id = self._first_probe_app_id()
        cache_key = f"first_segment_id:{app_id}"
        with self._probe_lock:
            cached = self._probe_values.get(cache_key)
            if isinstance(cached, str) and cached:
                return cached
            envelope = self.read(
                "analysis.segment.list",
                {"app_id": app_id, "page": 1, "page_size": 1},
            )
            rows = _envelope_rows(envelope)
            segment_id = (
                rows[0].get("segment_id", rows[0].get("id")) if rows else None
            )
            if not isinstance(segment_id, (str, int)) or isinstance(segment_id, bool):
                raise PermissionUnavailableError(
                    "no readable segment is available for the minimum analysis probe"
                )
            resolved = str(segment_id)
            self._probe_values[cache_key] = resolved
            return resolved

    def _first_probe_report_config_id(self) -> str:
        app_id = self._first_probe_app_id()
        cache_key = f"first_report_config_id:{app_id}"
        with self._probe_lock:
            cached = self._probe_values.get(cache_key)
            if isinstance(cached, str) and cached:
                return cached
            envelope = self.read(
                "analysis.report_config.list",
                {"app_id": app_id, "page": 1, "page_size": 1},
            )
            rows = _envelope_rows(envelope)
            config_id = rows[0].get("id") if rows else None
            if not isinstance(config_id, (str, int)) or isinstance(config_id, bool):
                raise PermissionUnavailableError(
                    "no readable analysis report config is available for the minimum probe"
                )
            resolved = str(config_id)
            self._probe_values[cache_key] = resolved
            return resolved

    def _first_probe_dashboard_field(self, field: str) -> str:
        if field not in {"dashboard_id", "space_id"}:
            raise PolicyViolation("live probe contains an unsupported dashboard placeholder")
        app_id = self._first_probe_app_id()
        cache_key = f"first_dashboard:{app_id}"
        with self._probe_lock:
            cached = self._probe_values.get(cache_key)
            if not isinstance(cached, Mapping):
                envelope = self.read("analysis.dashboard.tree", {"app_id": app_id})
                coordinates = _first_dashboard_coordinates(_envelope_rows(envelope))
                if coordinates is None:
                    raise PermissionUnavailableError(
                        "no readable dashboard is available for the minimum analysis probe"
                    )
                cached = {
                    "dashboard_id": coordinates[0],
                    "space_id": coordinates[1],
                }
                self._probe_values[cache_key] = cached
            result = cached.get(field)
            if not isinstance(result, (str, int)) or isinstance(result, bool):
                raise PermissionUnavailableError(
                    "the minimum dashboard probe is missing a required identifier"
                )
            return str(result)

    def _first_probe_client_id(self) -> str:
        app_id = self._first_probe_app_id()
        cache_key = f"first_client_id:{app_id}"
        with self._probe_lock:
            cached = self._probe_values.get(cache_key)
            if isinstance(cached, str) and cached:
                return cached
            envelope = self.read(
                "analysis.user_detail.list",
                {
                    "app_id": app_id,
                    "fields": ["ClientID"],
                    "page": 1,
                    "page_size": 1,
                },
            )
            rows = _envelope_rows(envelope)
            client_id = rows[0].get("ClientID") if rows else None
            if not isinstance(client_id, (str, int)) or isinstance(client_id, bool):
                raise PermissionUnavailableError(
                    "no readable user is available for the minimum analysis probe"
                )
            resolved = str(client_id)
            self._probe_values[cache_key] = resolved
            return resolved

    def _first_probe_order_field(self, field: str) -> Any:
        field_map = {
            "pay_event_time": "PayEventTime",
            "trace_id": "TraceID",
            "client_id": "ClientID",
            "split_trace_ids": "$split_trace_id_list",
        }
        upstream_field = field_map.get(field)
        if upstream_field is None:
            raise PolicyViolation("live probe contains an unsupported order placeholder")
        app_id = self._first_probe_app_id()
        cache_key = f"first_order_row:{app_id}"
        with self._probe_lock:
            cached = self._probe_values.get(cache_key)
            if not isinstance(cached, Mapping):
                envelope = self.read(
                    "analysis.order_detail.list",
                    {
                        "app_id": app_id,
                        "fields": list(field_map.values()),
                        "page": 1,
                        "page_size": 100,
                    },
                )
                rows = _envelope_rows(envelope)
                cached = next(
                    (
                        row
                        for row in rows
                        if isinstance(row.get("PayEventTime"), str)
                        and row.get("PayEventTime")
                        and isinstance(row.get("TraceID"), (str, int))
                        and not isinstance(row.get("TraceID"), bool)
                        and isinstance(row.get("ClientID"), (str, int))
                        and not isinstance(row.get("ClientID"), bool)
                        and isinstance(row.get("$split_trace_id_list"), (list, tuple))
                        and bool(row.get("$split_trace_id_list"))
                    ),
                    None,
                )
                if cached is None:
                    raise PermissionUnavailableError(
                        "no readable split order is available for the minimum analysis probe"
                    )
                cached = dict(cached)
                self._probe_values[cache_key] = cached
            result = cached.get(upstream_field)
            if field == "split_trace_ids":
                if not isinstance(result, (list, tuple)) or not result:
                    raise PermissionUnavailableError(
                        "the minimum split-order probe has no split identifiers"
                    )
                return list(result)
            if not isinstance(result, (str, int)) or isinstance(result, bool):
                raise PermissionUnavailableError(
                    "the minimum split-order probe is missing a required identifier"
                )
            return str(result)

    def _first_probe_preset_template_field(self, field: str) -> str:
        cache_key = f"first_preset_template_{field}"
        with self._probe_lock:
            cached = self._probe_values.get(cache_key)
            if isinstance(cached, str):
                return cached
            envelope = self.read(
                "report.multidim.template.preset.list",
                {"filters": [], "page": 1, "page_size": 1},
            )
            rows = _envelope_rows(envelope)
            if not rows:
                raise PermissionUnavailableError(
                    "no readable preset template is available for the minimum detail probe"
                )
            template_id = rows[0].get("id")
            category = rows[0].get("category", "")
            if not isinstance(template_id, (str, int)) or isinstance(template_id, bool):
                raise PermissionUnavailableError(
                    "the preset template parent did not return a usable id"
                )
            if not isinstance(category, (str, int)) or isinstance(category, bool):
                category = ""
            self._probe_values["first_preset_template_id"] = str(template_id)
            self._probe_values["first_preset_template_category"] = str(category)
            return str(self._probe_values[cache_key])

    def _error_envelope(
        self, operation_id: str, error: GravityInsightError
    ) -> dict[str, Any]:
        operation = self._registry.get(operation_id)
        status = _error_status(error)
        next_action = None
        if isinstance(error, ParentRequiredError) and operation.required_parent:
            parent = next(
                (
                    item.operation_id
                    for item in operation.required_parent
                    if item.operation_id
                ),
                None,
            )
            if parent:
                next_action = (
                    f"Run `python -m gravity_sdk operations describe {parent}`, "
                    f"then run `python -m gravity_sdk read {parent} --input "
                    f"<parent-input.json>` and pass the selected value to `{operation_id}`."
                )
        detail = error_detail_from_exception(
            error, operation_id=operation_id, next_action=next_action
        )
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        )
        return {
            "schema_version": "gravity-insight.read.v1",
            "ok": False,
            "operation_id": operation.operation_id,
            "contract_version": operation.contract_version,
            "status": status,
            "source": {
                "system": "gravity_insight",
                "domain": operation.domain,
                "resource": operation.resource,
                "platform": operation.platform,
                "contract_fingerprint": self._registry.fingerprint(operation_id),
            },
            "fetched_at": fetched_at,
            "schema_fingerprint": None,
            "request": {},
            "page": {},
            "data": {},
            "warnings": [],
            "error": detail.to_dict(),
        }

    def read(self, operation_id: str, inputs: Mapping[str, Any] | None = None) -> dict[str, Any]:
        started = time.monotonic()
        try:
            envelope = self._execute_result(operation_id, inputs).to_dict()
        except (UpstreamError, ParentRequiredError, PermissionUnavailableError) as exc:
            envelope = self._error_envelope(operation_id, exc)
        except GravityInsightError as exc:
            self._operation_catalog.record_upstream_exception(operation_id, exc, status=_error_status(exc))
            _audit_read(operation_id, _error_status(exc), started)
            raise
        self._operation_catalog.record_envelope(operation_id, envelope)
        _audit_read(operation_id, str(envelope.get("status", "success")), started, envelope)
        return envelope

    def _execute_result(
        self, operation_id: str, inputs: Mapping[str, Any] | None
    ) -> ReadResult:
        self._operation_catalog.guard(operation_id)
        operation = self._executor._policy.authorize_operation(operation_id)
        normalized_inputs = operation.validate_inputs(inputs)
        return self._metadata_cache.get_or_load(
            operation_id,
            normalized_inputs,
            lambda: self._executor.execute(operation_id, normalized_inputs),
        )

    def _validate_field_request(
        self, operation: OperationSpec, inputs: Mapping[str, Any]
    ) -> None:
        self._field_policy.validate(operation, inputs, self._load_field_metadata)

    def _load_field_metadata(
        self, operation_id: str, inputs: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        return self._read_all_untracked(
            operation_id,
            inputs,
            max_pages=1_000,
            max_items=100_000,
        )

    def read_all(
        self,
        operation_id: str,
        inputs: Mapping[str, Any] | None = None,
        *,
        max_pages: int = 1_000,
        max_items: int = 100_000,
    ) -> dict[str, Any]:
        started = time.monotonic()
        try:
            envelope = self._read_all_untracked(
                operation_id,
                inputs,
                max_pages=max_pages,
                max_items=max_items,
            )
        except (UpstreamError, ParentRequiredError, PermissionUnavailableError) as exc:
            envelope = self._error_envelope(operation_id, exc)
        except GravityInsightError as exc:
            self._operation_catalog.record_upstream_exception(operation_id, exc, status=_error_status(exc))
            _audit_read(operation_id, _error_status(exc), started)
            raise
        self._operation_catalog.record_envelope(operation_id, envelope)
        _audit_read(operation_id, str(envelope.get("status", "success")), started, envelope)
        return envelope

    def read_limited(
        self,
        operation_id: str,
        inputs: Mapping[str, Any] | None = None,
        *,
        max_pages: int = 5,
        max_items: int = 200,
    ) -> dict[str, Any]:
        """Read up to agent-safe bounds and return an explicit continuation."""

        started = time.monotonic()
        try:
            envelope = self._read_limited_untracked(
                operation_id,
                inputs,
                max_pages=max_pages,
                max_items=max_items,
            )
        except (UpstreamError, ParentRequiredError, PermissionUnavailableError) as exc:
            envelope = self._error_envelope(operation_id, exc)
        except GravityInsightError as exc:
            self._operation_catalog.record_upstream_exception(operation_id, exc, status=_error_status(exc))
            _audit_read(operation_id, _error_status(exc), started)
            raise
        self._operation_catalog.record_envelope(operation_id, envelope)
        _audit_read(
            operation_id,
            str(envelope.get("status", "success")),
            started,
            envelope,
        )
        return envelope

    def _read_limited_untracked(
        self,
        operation_id: str,
        inputs: Mapping[str, Any] | None = None,
        *,
        max_pages: int, max_items: int,
    ) -> dict[str, Any]:
        if not 1 <= max_pages <= _MAX_READ_PAGES:
            raise InputValidationError(
                f"max_pages must be between 1 and {_MAX_READ_PAGES}",
                field="max_pages",
            )
        if not 1 <= max_items <= _MAX_READ_ITEMS:
            raise InputValidationError(
                f"max_items must be between 1 and {_MAX_READ_ITEMS}",
                field="max_items",
            )
        self._operation_catalog.guard(operation_id)
        operation = self._executor._policy.authorize_operation(operation_id)
        supplied = dict(inputs or {})
        requested_page_size: int | None = None
        safe_size: int | None = None
        if operation.pagination.kind == "page_info":
            configured_size = _integer(
                supplied.get(operation.pagination.page_size_field),
                operation.request.defaults.get(
                    operation.pagination.page_size_field,
                    operation.pagination.default_page_size,
                ),
                default=max_items,
            )
            requested_page_size = configured_size
            per_page_budget = max(1, max_items // max_pages)
            safe_size = min(configured_size or max_items, per_page_budget)
            supplied[operation.pagination.page_size_field] = safe_size

        first = self._execute_result(operation_id, supplied)
        if operation.pagination.kind == "none":
            result = first.to_dict()
            returned, original = _truncate_nonpaginated_result(result, max_items)
            truncated = original > returned
            result["truncated"] = truncated
            result["next_page_input"] = None
            result["total"] = {
                "items": original,
                "pages": 1,
                "returned_items": returned,
                "returned_pages": 1,
            }
            result["safety_limits"] = {
                "max_pages": max_pages,
                "max_items": max_items,
                "page_size_clamped": False,
            }
            return result

        all_items = list(first.items)
        pages = [first]
        page_number = _integer(
            first.page_info.get(operation.pagination.page_field),
            supplied.get(
                operation.pagination.page_field,
                operation.request.defaults.get(operation.pagination.page_field, 1),
            ),
            default=1,
        )
        page_size = _integer(
            first.page_info.get(operation.pagination.page_size_field),
            supplied.get(operation.pagination.page_size_field),
            default=None,
        )
        total_pages = _integer(
            first.page_info.get(operation.pagination.total_page_field),
            None,
            default=None,
        )
        truncated = False
        next_page_input: dict[str, Any] | None = None
        current = first
        while _has_next_page(
            len(current.items), page_number, page_size, total_pages
        ):
            next_page = (page_number or 0) + 1
            if len(pages) >= max_pages or len(all_items) >= max_items:
                truncated = True
                next_page_input = {
                    **supplied,
                    operation.pagination.page_field: next_page,
                }
                break
            supplied[operation.pagination.page_field] = next_page
            candidate = self._execute_result(operation_id, supplied)
            observed_page = _integer(
                candidate.page_info.get(operation.pagination.page_field),
                next_page,
                default=next_page,
            )
            if observed_page <= (page_number or 0):
                raise PaginationError("Gravity pagination did not advance")
            if len(all_items) + len(candidate.items) > max_items:
                truncated = True
                next_page_input = dict(supplied)
                break
            page_number = observed_page
            if candidate.page_info.get(operation.pagination.total_page_field) is not None:
                total_pages = _integer(
                    candidate.page_info.get(operation.pagination.total_page_field),
                    total_pages,
                    default=total_pages,
                )
            pages.append(candidate)
            all_items.extend(candidate.items)
            current = candidate

        result = pages[0].to_dict()
        item_field = operation.pagination.list_path.rsplit(".", 1)[-1] or "list"
        if isinstance(result["data"], Mapping):
            result["data"] = dict(result["data"])
            result["data"][item_field] = all_items
        else:
            result["data"] = all_items
        result["fetched_at"] = pages[-1].fetched_at
        result["warnings"] = list(
            dict.fromkeys(warning for page in pages for warning in page.warnings)
        )
        result["status"] = (
            contract_status
            if (contract_status := aggregate_contract_status({page.status for page in pages}))
            else "empty"
            if not all_items
            else "success"
        )
        reported_total = (
            pages[-1].page.get("total_items") if pages[-1].page else None
        )
        result["page"] = {
            "number": pages[0].page.get("number") if pages[0].page else 1,
            "size": page_size,
            "item_count": len(all_items),
            "total_pages": total_pages,
            "total_items": reported_total,
            "has_more": truncated,
            "pages_fetched": len(pages),
        }
        result["truncated"] = truncated
        result["next_page_input"] = next_page_input
        result["total"] = {
            "items": reported_total,
            "pages": total_pages,
            "returned_items": len(all_items),
            "returned_pages": len(pages),
        }
        result["safety_limits"] = {
            "max_pages": max_pages,
            "max_items": max_items,
            "requested_page_size": requested_page_size,
            "effective_page_size": safe_size,
            "page_size_clamped": requested_page_size != safe_size,
        }
        result["schema_fingerprint"] = shape_fingerprint(result["data"])
        return result

    def _read_all_untracked(
        self,
        operation_id: str,
        inputs: Mapping[str, Any] | None = None,
        *,
        max_pages: int = 1_000, max_items: int = 100_000,
    ) -> dict[str, Any]:
        if not 1 <= max_pages <= _MAX_READ_PAGES:
            raise ValueError(f"max_pages must be between 1 and {_MAX_READ_PAGES}")
        if not 1 <= max_items <= _MAX_READ_ITEMS:
            raise ValueError(f"max_items must be between 1 and {_MAX_READ_ITEMS}")
        self._operation_catalog.guard(operation_id)
        operation = self._executor._policy.authorize_operation(operation_id)
        supplied = dict(inputs or {})
        first = self._execute_result(operation_id, supplied)
        if len(first.items) > max_items:
            raise PaginationError("read_all exceeded its item safety bound")
        if operation.pagination.kind == "none":
            return first.to_dict()

        all_items = list(first.items)
        pages = [first]
        page_number = _integer(
            first.page_info.get(operation.pagination.page_field),
            supplied.get(
                operation.pagination.page_field,
                operation.request.defaults.get(operation.pagination.page_field, 1),
            ),
            default=1,
        )
        page_size = _integer(
            first.page_info.get(operation.pagination.page_size_field),
            supplied.get(
                operation.pagination.page_size_field,
                operation.request.defaults.get(operation.pagination.page_size_field),
            ),
            default=None,
        )
        total_pages = _integer(
            first.page_info.get(operation.pagination.total_page_field), None, default=None
        )
        while _has_next_page(len(first.items), page_number, page_size, total_pages):
            if len(pages) >= max_pages:
                raise PaginationError("read_all exceeded its page safety bound")
            next_page = page_number + 1
            supplied[operation.pagination.page_field] = next_page
            current = self._execute_result(operation_id, supplied)
            observed_page = _integer(
                current.page_info.get(operation.pagination.page_field), next_page, default=next_page
            )
            if observed_page <= page_number:
                raise PaginationError("Gravity pagination did not advance")
            page_number = observed_page
            if current.page_info.get(operation.pagination.total_page_field) is not None:
                total_pages = _integer(
                    current.page_info.get(operation.pagination.total_page_field),
                    total_pages,
                    default=total_pages,
                )
            pages.append(current)
            all_items.extend(current.items)
            first = current
            if len(all_items) > max_items:
                raise PaginationError("read_all exceeded its item safety bound")

        result = pages[0].to_dict()
        item_field = operation.pagination.list_path.rsplit(".", 1)[-1] or "list"
        if isinstance(result["data"], Mapping):
            result["data"] = dict(result["data"])
            result["data"][item_field] = all_items
        else:
            result["data"] = all_items
        result["fetched_at"] = pages[-1].fetched_at
        aggregate_warnings = list(
            dict.fromkeys(warning for page in pages for warning in page.warnings)
        )
        result["warnings"] = aggregate_warnings
        result["status"] = (
            contract_status
            if (contract_status := aggregate_contract_status({page.status for page in pages}))
            else "empty"
            if not all_items
            else "success"
        )
        result["page"] = {
            "number": pages[0].page.get("number") if pages[0].page else 1,
            "size": page_size,
            "item_count": len(all_items),
            "total_pages": total_pages,
            "total_items": pages[-1].page.get("total_items") if pages[-1].page else None,
            "has_more": False,
            "pages_fetched": len(pages),
        }
        result["schema_fingerprint"] = shape_fingerprint(result["data"])
        return result

    def batch(
        self,
        requests: Sequence[BatchRequest | Mapping[str, Any]],
        *,
        max_workers: int = DEFAULT_CONCURRENCY,
        fail_fast: bool = False,
        max_total_items: int = _MAX_READ_ITEMS,
    ) -> list[dict[str, Any]]:
        normalized = [_batch_request(item) for item in requests]
        if not normalized:
            return []
        if max_workers < 1 or max_workers > MAX_CONCURRENCY:
            raise ValueError(
                f"batch max_workers must be between 1 and {MAX_CONCURRENCY}"
            )
        if not 1 <= max_total_items <= _MAX_READ_ITEMS:
            raise ValueError(
                f"batch max_total_items must be between 1 and {_MAX_READ_ITEMS}"
            )
        if len(normalized) > max_total_items:
            raise ValueError("batch request count exceeds its aggregate item safety bound")
        per_request_limit = max(1, max_total_items // len(normalized))

        def run(item: BatchRequest) -> BatchResult:
            try:
                value = (
                    self.read_all(
                        item.operation_id,
                        item.inputs,
                        max_items=per_request_limit,
                    )
                    if item.read_all
                    else self.read(item.operation_id, item.inputs)
                )
                if _envelope_item_count(value) > per_request_limit:
                    raise PaginationError(
                        "batch item exceeded its aggregate item safety share"
                    )
                status = str(value.get("status", "success"))
                ok = status not in {
                    "semantic_error",
                    "parent_required",
                    "permission_unavailable",
                    "error",
                }
                error_value = value.get("error")
                return BatchResult(
                    item.operation_id,
                    ok,
                    status,
                    value,
                    item.request_id,
                    dict(error_value)
                    if not ok and isinstance(error_value, Mapping)
                    else None,
                )
            except GravityInsightError as exc:
                if fail_fast:
                    raise
                return BatchResult(
                    item.operation_id,
                    False,
                    _error_status(exc),
                    None,
                    item.request_id,
                    error_detail_from_exception(
                        exc, operation_id=item.operation_id
                    ),
                )

        workers = min(max_workers, len(normalized))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gravity-read") as pool:
            return [item.to_dict() for item in pool.map(run, normalized)]


class _OfflineMetadataRequired(Exception):
    pass


def _validation_error(operation_id: str, error: GravityInsightError) -> dict[str, Any]:
    detail: ErrorDetail
    if isinstance(error, PolicyViolation) and "catalog-only" in str(error):
        detail = ErrorDetail.create(
            ErrorCode.NOT_IMPLEMENTED, error, operation_id=operation_id
        )
    else:
        detail = error_detail_from_exception(error, operation_id=operation_id)
    return {
        "schema_version": "gravity-insight.validation.v1",
        "ok": False,
        "status": "invalid",
        "operation_id": operation_id,
        "network_called": False,
        "normalized_input": None,
        "live_metadata_dependencies": [],
        "error": detail.to_dict(),
    }


def _load_contract_metadata(
    operation_root: Path,
) -> dict[str, Mapping[str, Any]]:
    metadata: dict[str, Mapping[str, Any]] = {}
    if not operation_root.is_dir():
        return metadata
    for path in sorted(operation_root.glob("*.json")):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        operation = document.get("operation") if isinstance(document, Mapping) else None
        operation_id = operation.get("operation_id") if isinstance(operation, Mapping) else None
        if isinstance(operation_id, str):
            metadata[operation_id] = dict(operation)
    return metadata


def _redact_operation_values(operation: OperationSpec, value: Any) -> Any:
    sensitive_names = {
        field.name.casefold() for field in operation.input_fields if field.sensitive
    } | {name.casefold() for name in operation.privacy_policy.redact_fields}

    def redact(item: Any) -> Any:
        if isinstance(item, Mapping):
            result: dict[str, Any] = {}
            for name, nested in item.items():
                lowered = str(name).casefold()
                if lowered in sensitive_names or any(
                    marker in lowered
                    for marker in (
                        "authorization",
                        "password",
                        "secret",
                        "token",
                        "cookie",
                    )
                ):
                    result[str(name)] = "[REDACTED]"
                else:
                    result[str(name)] = redact(nested)
            return result
        if isinstance(item, (list, tuple)):
            return [redact(nested) for nested in item]
        return item

    return redact(value)


def _truncate_nonpaginated_result(
    result: dict[str, Any], max_items: int
) -> tuple[int, int]:
    data = result.get("data")
    if isinstance(data, list):
        original = len(data)
        result["data"] = data[:max_items]
        return len(result["data"]), original
    if isinstance(data, Mapping):
        for key in ("list", "items"):
            rows = data.get(key)
            if isinstance(rows, list):
                original = len(rows)
                result["data"] = {**dict(data), key: rows[:max_items]}
                return min(original, max_items), original
    count = _envelope_item_count(result)
    return count, count


def _envelope_item_count(envelope: Mapping[str, Any]) -> int:
    page = envelope.get("page")
    if isinstance(page, Mapping):
        count = page.get("item_count")
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            return count
    data = envelope.get("data")
    if isinstance(data, list):
        return len(data)
    if isinstance(data, Mapping):
        for key in ("list", "items"):
            rows = data.get(key)
            if isinstance(rows, list):
                return len(rows)
    return 0


def _envelope_rows(envelope: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = envelope.get("data")
    rows: Any = data
    if isinstance(data, Mapping):
        rows = data.get("list", data.get("items", []))
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, Mapping)]


def _first_dashboard_coordinates(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[str, str] | None:
    def identifier(value: Any) -> str | None:
        if isinstance(value, bool) or not isinstance(value, (str, int)):
            return None
        normalized = str(value)
        return normalized if normalized else None

    def visit_nodes(
        nodes: Sequence[Any], inherited_space_id: str | None, depth: int
    ) -> tuple[str, str] | None:
        if depth > 16:
            return None
        for value in nodes:
            if not isinstance(value, Mapping):
                continue
            row_id = identifier(value.get("id"))
            row_space_id = identifier(value.get("space_id")) or inherited_space_id
            if value.get("is_folder") is not True and row_id and row_space_id:
                return row_id, row_space_id

            dashboards = value.get("dashboards")
            if isinstance(dashboards, (list, tuple)):
                found = visit_nodes(dashboards, row_space_id, depth + 1)
                if found is not None:
                    return found

            folder_children = value.get("folder_or_dashboard")
            if isinstance(folder_children, (list, tuple)):
                found = visit_nodes(folder_children, row_space_id, depth + 1)
                if found is not None:
                    return found
        return None

    for space in rows:
        space_id = identifier(space.get("id"))
        if space_id is None:
            continue
        direct = space.get("dashboards")
        if isinstance(direct, (list, tuple)):
            found = visit_nodes(direct, space_id, 1)
            if found is not None:
                return found
        nested = space.get("folder_or_dashboard")
        if isinstance(nested, (list, tuple)):
            found = visit_nodes(nested, space_id, 1)
            if found is not None:
                return found
    return None


def _first_enumerable_property(rows: Sequence[Mapping[str, Any]]) -> str | None:
    sensitive_fragments = (
        "token",
        "password",
        "secret",
        "cookie",
        "authorization",
        "email",
        "phone",
        "mobile",
    )
    for row in rows:
        name = row.get("name")
        data_type = row.get("data_type")
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(data_type, str) or data_type.upper() not in {
            "STRING",
            "BOOL",
            "BOOLEAN",
            "LIST",
        }:
            continue
        normalized = name.casefold()
        if any(fragment in normalized for fragment in sensitive_fragments):
            continue
        return name
    return None


def _audit_read(
    operation_id: str,
    status: str,
    started: float,
    envelope: Mapping[str, Any] | None = None,
) -> None:
    page = envelope.get("page") if isinstance(envelope, Mapping) else None
    pages = page.get("pages_fetched", 1) if isinstance(page, Mapping) else 0
    _LOGGER.info(
        "gravity_read",
        extra={
            "gravity_operation_id": operation_id,
            "gravity_status": status,
            "gravity_duration_ms": round((time.monotonic() - started) * 1_000, 3),
            "gravity_pages": pages,
            "gravity_rows": _envelope_item_count(envelope or {}),
        },
    )


def _batch_request(
    value: BatchRequest | Mapping[str, Any],
) -> BatchRequest:
    if isinstance(value, BatchRequest):
        return value
    item = validate_batch_item(value)
    operation_id = item.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id.strip():
        raise batch_input_error("batch operation_id must be a non-empty string", "operation_id")
    normalized_operation_id = operation_id.strip()
    inputs = item.get("inputs", item.get("input", {}))
    if not isinstance(inputs, Mapping):
        raise batch_input_error("batch inputs must be an object", "inputs")
    normalized_inputs = dict(inputs)
    request_id = item.get("request_id")
    if request_id is not None and not isinstance(request_id, str):
        raise batch_input_error("batch request_id must be a string", "request_id")
    read_all = item.get("read_all", False)
    if not isinstance(read_all, bool):
        raise batch_input_error("batch read_all must be a boolean", "read_all")
    return BatchRequest(normalized_operation_id, normalized_inputs, request_id, read_all)


def _integer(primary: Any, fallback: Any, *, default: int | None) -> int | None:
    value = primary if primary is not None else fallback
    if isinstance(value, bool):
        return default
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _has_next_page(
    item_count: int,
    page_number: int | None,
    page_size: int | None,
    total_pages: int | None,
) -> bool:
    if page_number is not None and total_pages is not None:
        return page_number < total_pages
    return bool(page_size and item_count >= page_size)


def _new_analysis_query_id() -> str:
    milliseconds = f"{int(time.time() * 1_000):013d}"[-13:]
    entropy = secrets.token_hex(10)[:19]
    return milliseconds + entropy


def _error_status(error: GravityInsightError) -> str:
    if isinstance(error, ParentRequiredError):
        return "parent_required"
    if isinstance(error, PermissionUnavailableError):
        return "permission_unavailable"
    if isinstance(error, UpstreamError):
        return "semantic_error"
    if isinstance(error, (PolicyViolation, UnknownOperationError)):
        return "unavailable"
    return "error"
