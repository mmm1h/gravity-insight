"""Small unified SDK facade for callers that use both Insight and SQL.

The specialized clients remain public.  This facade only removes construction
and import ceremony; it does not guess whether a request should use Insight or
SQL, and it does not add another policy layer.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .sdk_analysis import AnalysisSdkMixin
from .sdk_agent_runtime import AgentRuntimeSdkMixin
from .sdk_bootstrap import BootstrapSdkMixin
from .sdk_saved_analysis import SavedAnalysisSdkMixin
from .sdk_analysis_default_dictionary import AnalysisDefaultDictionarySdkMixin
from .sdk_attribution import AttributionSdkMixin
from .sdk_derived_metrics import DerivedMetricsSdkMixin
from .sdk_material import MaterialSdkMixin
from .sdk_metadata import MetadataSdkMixin
from .sdk_monetization import MonetizationSdkMixin
from .sdk_order import OrderSdkMixin
from .sdk_promotion import PromotionSdkMixin
from .sdk_plan_recipe import PlanRecipeSdkMixin
from .sdk_report import ReportSdkMixin
from .sdk_segment_members import SegmentMembersSdkMixin
from .sdk_segment_mutation import SegmentMutationSdkMixin
from .sdk_kanban_mutation import KanbanMutationSdkMixin
from .sdk_custom_metric import CustomMetricSdkMixin
from .sdk_metadata_template import MetadataTemplateSdkMixin
from .sdk_realtime_event import RealtimeEventSdkMixin
from .template_replay_surface import TemplateSdkMixin


ClientFactory = Callable[[], Any]


class GravitySDK(
    AgentRuntimeSdkMixin,
    BootstrapSdkMixin,
    DerivedMetricsSdkMixin,
    SavedAnalysisSdkMixin,
    AnalysisSdkMixin,
    AnalysisDefaultDictionarySdkMixin,
    AttributionSdkMixin,
    SegmentMutationSdkMixin,
    KanbanMutationSdkMixin,
    CustomMetricSdkMixin,
    MetadataTemplateSdkMixin,
    RealtimeEventSdkMixin,
    SegmentMembersSdkMixin,
    ReportSdkMixin,
    MaterialSdkMixin,
    PromotionSdkMixin,
    OrderSdkMixin, MetadataSdkMixin, MonetizationSdkMixin, TemplateSdkMixin,
    PlanRecipeSdkMixin,
):
    """Lazy facade; specialized clients retain their native policy and envelopes."""

    def __init__(
        self,
        *,
        insight: Any | None = None,
        sql: Any | None = None,
        insight_factory: ClientFactory | None = None,
        sql_factory: ClientFactory | None = None,
        workspace: Any | None = None,
        _runtime_scope_bound: bool = False,
    ) -> None:
        if insight is not None and insight_factory is not None:
            raise ValueError("pass either insight or insight_factory, not both")
        if sql is not None and sql_factory is not None:
            raise ValueError("pass either sql or sql_factory, not both")
        self._insight = insight
        self._sql = sql
        self._insight_factory = insight_factory or _default_insight_client
        self._sql_factory = sql_factory or _default_sql_client
        self._workspace = _load_workspace(workspace)
        self._insight_lock = threading.Lock()
        self._sql_lock = threading.Lock()
        self._initialize_agent_runtime_services(_runtime_scope_bound)

    @classmethod
    def from_env(
        cls,
        *,
        allow_experimental: bool = False,
        timeout: float = 120.0,
        attempts: int = 3,
        workspace: Any | None = None,
        env_path: Any | None = None,
    ) -> "GravitySDK":
        """Create a lazy facade configured from the normal SDK environment."""

        from .sdk_environment import environment_components

        build_insight, build_sql, selected_workspace = environment_components(
            allow_experimental=allow_experimental,
            timeout=timeout,
            attempts=attempts,
            workspace=_load_workspace(workspace),
            env_path=env_path,
        )
        return cls(
            insight_factory=build_insight,
            sql_factory=build_sql,
            workspace=selected_workspace,
            _runtime_scope_bound=True,
        )

    @property
    def workspace(self) -> Any:
        """The immutable workspace selection bound when this facade was created."""

        return self._workspace

    @property
    def insight(self) -> Any:
        if self._insight is None:
            with self._insight_lock:
                if self._insight is None:
                    self._insight = self._insight_factory()
        return self._insight

    @property
    def sql(self) -> Any:
        if self._sql is None:
            with self._sql_lock:
                if self._sql is None:
                    self._sql = self._sql_factory()
        return self._sql

    def read(
        self,
        operation_id: str,
        inputs: Mapping[str, Any] | None = None,
        *,
        output_fields: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        values = dict(inputs or {})
        schema = self._output_schema(operation_id, values, output_fields)
        return self._project_read(
            operation_id,
            values,
            output_fields,
            self.insight.read(operation_id, values),
            schema=schema,
        )

    def read_all(
        self,
        operation_id: str,
        inputs: Mapping[str, Any] | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        output_fields = options.pop("output_fields", None)
        values = dict(inputs or {})
        schema = self._output_schema(operation_id, values, output_fields)
        return self._project_read(
            operation_id,
            values,
            output_fields,
            self.insight.read_all(operation_id, values, **options),
            schema=schema,
        )

    def read_limited(
        self,
        operation_id: str,
        inputs: Mapping[str, Any] | None = None,
        **options: Any,
    ) -> dict[str, Any]:
        """Read an Agent-safe prefix and preserve its continuation contract."""

        output_fields = options.pop("output_fields", None)
        values = dict(inputs or {})
        schema = self._output_schema(operation_id, values, output_fields)
        return self._project_read(
            operation_id,
            values,
            output_fields,
            self.insight.read_limited(operation_id, values, **options),
            schema=schema,
        )

    def read_many(
        self,
        requests: Sequence[Mapping[str, Any]],
        **options: Any,
    ) -> list[dict[str, Any]]:
        return self.insight.batch(requests, **options)

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
        """Run the existing governed export state machine in one call."""

        return self.insight.export_run(
            operation_id,
            payload,
            destination,
            requested_columns=requested_columns,
            idempotency_key=idempotency_key,
            timeout_seconds=timeout_seconds,
        )

    def capabilities(
        self,
        query: str | None = None,
        *,
        workspace: Any | None = None,
        domain: str | None = None,
        platform: str | None = None,
        limit: int = 3,
        continuation: str | None = None,
    ) -> dict[str, Any]:
        """Discover recipes and executable Insight operations in one offline call."""

        from .agent import discover_capabilities
        from .agent_client import DeferredAgentClient

        client = DeferredAgentClient(lambda: self.insight) if str(query or "").strip() else None
        return discover_capabilities(
            query,
            client=client,
            workspace=self._select_workspace(workspace),
            domain=domain,
            platform=platform,
            limit=limit,
            continuation=continuation,
        )

    def capabilities_many(
        self,
        questions: Mapping[str, Any] | Sequence[str | Mapping[str, Any]],
        *,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Discover up to 32 questions from one immutable offline catalog snapshot."""

        from .agent_batch import capabilities_many
        from .agent_client import DeferredAgentClient

        return capabilities_many(
            questions,
            client=DeferredAgentClient(lambda: self.insight),
            workspace=self._select_workspace(workspace),
        )

    def run(
        self,
        selector: str,
        inputs: Mapping[str, Any] | None = None,
        *,
        parameters: Mapping[str, Any] | None = None,
        workspace: Any | None = None,
        app: str | int | None = None,
        start: str | None = None,
        end: str | None = None,
        all_pages: bool = False,
        max_pages: int | None = None,
        max_items: int | None = None,
        max_workers: int = 6,
        metadata_database: Any | None = None,
        output_fields: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Resolve a recipe or operation and execute the normal Agent pipeline."""

        from .resolver import resolve_and_run
        from .runtime import call_read
        selected_workspace = self._select_workspace(workspace)
        fallback = (1_000, 100_000) if all_pages else (5, 200) if max_pages is not None or max_items is not None else (None, None)
        effective_pages = max_pages if max_pages is not None else fallback[0]
        effective_items = max_items if max_items is not None else fallback[1]
        return resolve_and_run(
            selector,
            client=self.insight,
            workspace=selected_workspace,
            supplied_input=inputs,
            parameters=parameters,
            app=app,
            start=start,
            end=end,
            read=call_read,
            read_all=all_pages,
            max_pages=effective_pages,
            max_items=effective_items,
            max_workers=max_workers,
            metadata_database=metadata_database,
            output_fields=output_fields,
        )

    def run_many(
        self,
        requests: Mapping[str, Any] | Sequence[Mapping[str, Any]],
        *,
        max_workers: int = 6,
        max_pages: int = 5,
        max_items: int = 200,
        metadata_database: Any | None = None,
        output_fields: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Run resolver selectors concurrently against this instance's workspace."""

        from .resolver_batch import run_many

        options: dict[str, Any] = {
            "client": self.insight,
            "workspace": self._workspace,
            "max_workers": max_workers,
            "max_pages": max_pages,
            "max_items": max_items,
            "metadata_database": metadata_database,
        }
        if output_fields is not None:
            options["output_fields"] = output_fields
        return run_many(requests, **options)

    def describe_sql_products(
        self, workspace: Any | None = None
    ) -> list[dict[str, Any]]:
        """Describe configured aggregate products without exposing their raw SQL."""

        from .sql import describe_products

        return describe_products(self._select_workspace(workspace))

    def list_http_receipts(
        self,
        *,
        limit: int = 100,
        cursor: str | None = None,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """List one stable page from this workspace's private receipt store."""

        from .receipt_query import list_http_receipts

        return list_http_receipts(
            self._workspace.state_root,
            limit=limit,
            cursor=cursor,
            operation_id=operation_id,
        )

    def get_http_receipt(
        self, reference: str | Mapping[str, Any]
    ) -> dict[str, Any]:
        """Resolve an opaque result reference without exposing its backing file."""

        from .receipt_query import get_http_receipt

        return get_http_receipt(self._workspace.state_root, reference)

    def export_http_receipts(
        self,
        destination: str | Path,
        *,
        max_items: int = 10_000,
        operation_id: str | None = None,
    ) -> dict[str, Any]:
        """Export one bounded receipt snapshot to a caller-selected path."""

        from .receipt_query import export_http_receipts

        return export_http_receipts(
            self._workspace.state_root,
            destination,
            max_items=max_items,
            operation_id=operation_id,
        )

    def query_sql_products(
        self,
        requests: Mapping[str, Any] | Sequence[Mapping[str, Any]],
        *,
        max_workers: int = 2,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Execute one or more governed workspace SQL products."""

        from .sql import run_product_queries

        values = [requests] if isinstance(requests, Mapping) else requests
        return run_product_queries(
            self.sql,
            values,
            max_workers=max_workers,
            workspace=self._select_workspace(workspace),
        )

    def validate_plan(
        self,
        plan: Mapping[str, Any],
        *,
        workspace: Any | None = None,
        max_workers: int = 6,
    ) -> dict[str, Any]:
        """Run complete structural and adapter preflight with zero execution."""

        return self.execute_plan(
            plan,
            workspace=workspace,
            max_workers=max_workers,
            dry_run=True,
        )

    def execute_plan(
        self,
        plan: Mapping[str, Any],
        *,
        workspace: Any | None = None,
        max_workers: int = 6,
        dry_run: bool = False,
        metadata_database: Any | None = None,
    ) -> dict[str, Any]:
        """Execute one bounded Plan v1 through the governed adapters."""

        from .plan import PlanAdapters, execute_plan, validate_plan
        from .plan_adapters import build_plan_adapters

        validated = validate_plan(plan)
        local_only = all(
            node.kind in {"metadata_search", "receipt_query"}
            for node in validated.nodes
        )
        if local_only:
            from .plan_metadata_adapter import build_metadata_plan_adapter
            from .plan_receipt_adapter import (
                execute_receipt_query,
                validate_receipt_query,
            )
            from .plan import PlanAdapter

            selected = self._select_workspace(workspace)
            adapters = PlanAdapters(
                metadata_search=(
                    build_metadata_plan_adapter(metadata_database)
                    if any(node.kind == "metadata_search" for node in validated.nodes)
                    else None
                ),
                receipt_query=(
                    PlanAdapter(
                        execute_receipt_query,
                        validate_receipt_query,
                        preserve_partial=True,
                        preserve_capability_gap=True,
                    )
                    if any(node.kind == "receipt_query" for node in validated.nodes)
                    else None
                ),
            )
        else:
            selected = self._select_workspace(workspace)
            adapters = build_plan_adapters(
                self,
                workspace=selected,
                metadata_database=metadata_database,
            )
        return execute_plan(
            plan,
            adapters=adapters,
            workspace=selected,
            max_workers=max_workers,
            dry_run=dry_run,
        )

    def _project_read(
        self,
        operation_id: str,
        inputs: Mapping[str, Any],
        output_fields: Sequence[str] | None,
        result: Mapping[str, Any],
        *,
        schema: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if output_fields is None:
            return dict(result)
        from .output_projection import project_output

        assert schema is not None
        return project_output(
            schema,
            operation_id,
            result,
            output_fields,
            request_inputs=inputs,
        )

    def _output_schema(
        self,
        operation_id: str,
        inputs: Mapping[str, Any],
        output_fields: Sequence[str] | None,
    ) -> Mapping[str, Any] | None:
        if output_fields is None:
            return None
        from .output_projection import validate_output_fields

        schema = self.insight.schema(operation_id)
        validate_output_fields(schema, output_fields, request_inputs=inputs)
        return schema

    @staticmethod
    def _resolve_app(workspace: Any, value: str | int | None) -> int:
        try:
            return workspace.resolve_app(value)
        except ValueError:
            from .errors import InputValidationError
            raise InputValidationError("app must reference a configured workspace App or positive id", field="app") from None

    def _select_workspace(self, workspace: Any | None) -> Any:
        return self._workspace if workspace is None else _load_workspace(workspace)


def connect(
    *,
    allow_experimental: bool = False,
    timeout: float = 120.0,
    attempts: int = 3,
    workspace: Any | None = None,
    env_path: Any | None = None,
) -> GravitySDK:
    """Return the recommended lazy SDK entry point."""

    return GravitySDK.from_env(
        allow_experimental=allow_experimental,
        timeout=timeout,
        attempts=attempts,
        workspace=workspace,
        env_path=env_path,
    )


def _default_insight_client() -> Any:
    from .client import GravityInsightClient

    return GravityInsightClient.from_env()


def _default_sql_client() -> Any:
    from .sql import build_sql_client

    return build_sql_client()


def _load_workspace(value: Any | None) -> Any:
    from pathlib import Path

    from .workspace import load_workspace

    if value is None or isinstance(value, (str, Path)):
        return load_workspace(value)
    return value


__all__ = ["GravitySDK", "connect"]
