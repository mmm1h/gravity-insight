"""Unified SDK convenience methods for governed Segment mutations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class SegmentMutationSdkMixin:
    def segment_create_from_analysis(
        self,
        spec: Mapping[str, Any],
        *,
        app: str | int | None = None,
        name: str,
        step: int,
        is_loss: bool = True,
        remark: str = "",
        idempotency_key: str | None = None,
        execute: bool = False,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Preview by default, or explicitly run funnel→persistent-segment."""

        from .segment_mutation import create_segment_from_analysis

        selected = self._select_workspace(workspace)
        return create_segment_from_analysis(
            self.insight,
            spec,
            app=self._resolve_app(selected, app),
            name=name,
            step=step,
            is_loss=is_loss,
            remark=remark,
            idempotency_key=idempotency_key,
            execute=execute,
        )

    def segment_create_from_rule(
        self,
        spec: Mapping[str, Any],
        *,
        app: str | int | None = None,
        idempotency_key: str | None = None,
        execute: bool = False,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        """Preview by default, or explicitly create one rule segment."""

        from .segment_mutation import create_segment_from_rule

        selected = self._select_workspace(workspace)
        return create_segment_from_rule(
            self.insight,
            spec,
            app=self._resolve_app(selected, app),
            idempotency_key=idempotency_key,
            execute=execute,
        )

    def segment_create_from_history(
        self,
        source_segment_id: str | int,
        version_id: str | int,
        *,
        app: str | int | None = None,
        name: str,
        remark: str = "",
        idempotency_key: str | None = None,
        execute: bool = False,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        from .segment_mutation import create_segment_from_history

        selected = self._select_workspace(workspace)
        return create_segment_from_history(
            self.insight,
            app_id=self._resolve_app(selected, app),
            source_segment_id=source_segment_id,
            version_id=version_id,
            name=name,
            remark=remark,
            idempotency_key=idempotency_key,
            execute=execute,
        )

    def segment_create_from_tmp(
        self,
        tmp_segment_id: str | int,
        *,
        app: str | int | None = None,
        name: str,
        remark: str = "",
        idempotency_key: str | None = None,
        execute: bool = False,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        from .segment_mutation import create_segment_from_tmp

        selected = self._select_workspace(workspace)
        return create_segment_from_tmp(
            self.insight,
            app_id=self._resolve_app(selected, app),
            tmp_segment_id=tmp_segment_id,
            name=name,
            remark=remark,
            idempotency_key=idempotency_key,
            execute=execute,
        )

    def segment_update(
        self,
        segment_id: str | int,
        *,
        name: str,
        remark: str = "",
        execute: bool = False,
    ) -> dict[str, Any]:
        from .segment_mutation import update_segment_metadata

        return update_segment_metadata(
            self.insight, segment_id, name=name, remark=remark, execute=execute
        )

    def segment_update_rule(
        self,
        segment_id: str | int,
        spec: Mapping[str, Any],
        *,
        app: str | int | None = None,
        execute: bool = False,
        workspace: Any | None = None,
    ) -> dict[str, Any]:
        from .segment_mutation import update_segment_rule

        selected = self._select_workspace(workspace)
        return update_segment_rule(
            self.insight,
            segment_id,
            spec,
            app=self._resolve_app(selected, app),
            execute=execute,
        )

    def segment_refresh(
        self, segment_id: str | int, *, execute: bool = False
    ) -> dict[str, Any]:
        from .segment_mutation import refresh_segment

        return refresh_segment(self.insight, segment_id, execute=execute)

    def segment_delete(
        self, segment_id: str | int, *, execute: bool = False
    ) -> dict[str, Any]:
        from .segment_mutation import delete_segment

        return delete_segment(self.insight, segment_id, execute=execute)


__all__ = ["SegmentMutationSdkMixin"]
