"""Governed report/template mutations with marker-or-owner preflight."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .actionable_error_values import actual_value
from .errors import MutationReadbackError, ObjectAlreadyExistsError
from .mutation_lifecycle import MARKER_PREFIX, WRITE_LOCK, mutation_marker
from .report_contracts import (
    REPORT_DETAIL,
    REPORT_LIST,
    REPORT_UPDATE,
    TEMPLATE_CREATE,
    TEMPLATE_DETAIL,
    TEMPLATE_LIST,
    TEMPLATE_UPDATE,
)
from .report_mutation_support import (
    SCHEMA_VERSION,
    catalog,
    caller_text,
    completed,
    contract_text,
    dependent_preview,
    detail,
    idempotent,
    json_text,
    marker,
    marker_in_report,
    marker_in_subscription,
    optional_caller_text,
    optional_nonnegative_id,
    positive_id,
    preview,
    require_created,
    require_report_authority,
    response_id,
    subscription_report_config,
    unique_marker,
)
from .report_subscription_mutation import create_subscription, delete_subscription


def create_report(
    client: Any,
    *,
    app_id: int,
    name: str,
    config: Mapping[str, Any],
    subject: str = "measurement_report",
    remark: str = "SDK production-contract test",
    idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Preview or create one visibly marked report and verify list/detail readback."""

    selected_app, selected_name, selected_marker, inputs = _report_create_inputs(
        app_id,
        name,
        config,
        subject,
        remark,
        idempotency_key,
    )
    raw_preview = preview(
        client._preview_mutation(REPORT_UPDATE, inputs),
        target={
            "name": selected_name,
            "app_id": selected_app,
            "marker": selected_marker,
        },
        impact="Create one reusable test report without changing material, promotion, permission, or subscription state.",
    )
    if not execute:
        return raw_preview
    with WRITE_LOCK:
        rows = catalog(client, REPORT_LIST)
        existing = unique_marker(rows, selected_marker, fields=("remark",))
        if existing is not None:
            if existing.get("name") != selected_name:
                raise ObjectAlreadyExistsError(
                    f"actual value: {actual_value(existing.get('name'))}; allowed value: {actual_value(selected_name)}",
                    field="name",
                    next_action="Reuse the marked report or choose a new idempotency key and test name.",
                )
            return idempotent(existing, REPORT_UPDATE)
        if any(row.get("name") == selected_name for row in rows):
            raise ObjectAlreadyExistsError(
                f"actual value: {actual_value(selected_name)}; allowed value: a unique report name",
                field="name",
                next_action="Choose another obvious test name and run dry-run again.",
            )
        mutation = client._execute_mutation(REPORT_UPDATE, inputs)
        created = require_created(
            client,
            REPORT_LIST,
            selected_marker,
            fields=("remark",),
            name=selected_name,
        )
        report_detail = detail(
            client, REPORT_DETAIL, response_id(created.get("id"), "id")
        )
        if marker(report_detail, ("remark",)) != selected_marker:
            raise MutationReadbackError(
                "created report marker did not round-trip through detail",
                next_action="Stop writes and inspect the exact marked report before cleanup.",
            )
        return completed(raw_preview, mutation, report_detail, "created")


def _report_create_inputs(
    app_id: int,
    name: str,
    config: Mapping[str, Any],
    subject: str,
    remark: str,
    idempotency_key: str | None,
) -> tuple[str, str, str, dict[str, Any]]:
    from .errors import InputValidationError

    selected_app = positive_id(app_id, "app_id")
    selected_name = caller_text(name, "name", 128)
    selected_subject = caller_text(subject, "subject", 64)
    selected_remark = optional_caller_text(remark, "remark", 1_980)
    if not isinstance(config, Mapping):
        raise InputValidationError(
            f"actual value: {actual_value({'type': type(config).__name__})}; allowed value: a JSON object",
            field="config",
            next_action="Provide the exact frontend report config object and run dry-run again.",
        )
    config_text = json_text(config, "config")
    semantic = {
        "app_id": selected_app,
        "name": selected_name,
        "subject": selected_subject,
        "config": config_text,
    }
    selected_marker = mutation_marker(
        "report", semantic, idempotency_key=idempotency_key
    )
    marked_remark = (
        f"{selected_marker} | {selected_remark}"
        if selected_remark
        else selected_marker
    )
    return selected_app, selected_name, selected_marker, {
        "name": selected_name,
        "remark": marked_remark,
        "subject": selected_subject,
        "app_id": selected_app,
        "config": config_text,
    }


def delete_report(
    client: Any, report_id: int | str, *, execute: bool = False
) -> dict[str, Any]:
    selected_id = positive_id(report_id, "report_id")
    if not execute:
        return dependent_preview(
            REPORT_UPDATE,
            {"id": selected_id},
            "Delete this exact report after marker-or-owner list/detail readback.",
        )
    with WRITE_LOCK:
        preimage = detail(client, REPORT_DETAIL, selected_id)
        ownership = require_report_authority(
            client,
            preimage,
            object_kind="report",
            object_id=selected_id,
            marker_fields=("remark",),
            field="report_id",
        )
        inputs = {
            "id": selected_id,
            "name": contract_text(preimage.get("name"), "name", 128),
            "subject": contract_text(preimage.get("subject"), "subject", 64),
            "report_group_id": optional_nonnegative_id(
                preimage.get("report_group_id"), "report_group_id"
            ),
            "config": contract_text(preimage.get("config"), "config", 100_000),
            "remark": contract_text(preimage.get("remark"), "remark", 2_000),
            "is_delete": 1,
        }
        raw_preview = client._preview_mutation(REPORT_UPDATE, inputs)
        mutation = client._execute_mutation(REPORT_UPDATE, inputs)
        if any(
            response_id(row.get("id"), "id") == selected_id
            for row in catalog(client, REPORT_LIST)
        ):
            raise MutationReadbackError(
                "report still exists after the delete acknowledgement",
                next_action="Read the exact report and inspect references before another explicit delete.",
            )
        return completed(
            raw_preview,
            mutation,
            {
                "id": selected_id,
                "marker": marker(preimage, ("remark",)),
                "deleted": True,
                "ownership": ownership.public(),
            },
            "deleted",
            preimage,
        )


def create_subscription_report(
    client: Any,
    *,
    app_id: int | str,
    name: str = "GSDK订阅父报表",
    idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Create the v3 report-template parent required by subscriptions."""

    selected_app = positive_id(app_id, "app_id")
    selected_name = caller_text(name, "name", 20)
    selected_marker = mutation_marker(
        "subscription_report",
        {"app_id": selected_app, "name": selected_name},
        idempotency_key=idempotency_key,
    )
    inputs = {
        "name": selected_name,
        "remark": f"{selected_marker} | SDK subscription contract test",
        "category": "adreport",
        "config": subscription_report_config(selected_app),
        "app_id": selected_app,
        "project_id": "0",
    }
    raw_preview = preview(
        client._preview_mutation(TEMPLATE_CREATE, inputs),
        target={
            "name": selected_name,
            "app_id": selected_app,
            "marker": selected_marker,
        },
        impact="Create one v3 test report used only as the parent of a disabled recipient-free subscription.",
    )
    if not execute:
        return raw_preview
    with WRITE_LOCK:
        rows = catalog(client, TEMPLATE_LIST)
        existing = unique_marker(rows, selected_marker, fields=("remark",))
        if existing is not None:
            return idempotent(existing, TEMPLATE_CREATE)
        if any(row.get("name") == selected_name for row in rows):
            raise ObjectAlreadyExistsError(
                f"actual value: {actual_value(selected_name)}; allowed value: a unique v3 report name",
                field="name",
                next_action="Choose a unique obvious test name and run dry-run again.",
            )
        mutation = client._execute_mutation(TEMPLATE_CREATE, inputs)
        created = require_created(
            client,
            TEMPLATE_LIST,
            selected_marker,
            fields=("remark",),
            name=selected_name,
        )
        report_detail = detail(
            client,
            TEMPLATE_DETAIL,
            response_id(created.get("id"), "id"),
            nested=True,
        )
        if marker(report_detail, ("remark",)) != selected_marker:
            raise MutationReadbackError(
                "created v3 report marker did not round-trip through detail",
                next_action="Stop writes and inspect the exact marked report before cleanup.",
            )
        return completed(raw_preview, mutation, report_detail, "created")


def delete_subscription_report(
    client: Any, report_id: int | str, *, execute: bool = False
) -> dict[str, Any]:
    selected_id = positive_id(report_id, "report_id")
    if not execute:
        return dependent_preview(
            TEMPLATE_UPDATE,
            {"id": selected_id},
            "Delete this v3 report after marker-or-owner list readback.",
        )
    with WRITE_LOCK:
        matches = [
            row
            for row in catalog(client, TEMPLATE_LIST)
            if response_id(row.get("id"), "id") == selected_id
        ]
        if len(matches) != 1:
            raise MutationReadbackError(
                "v3 report delete preimage is missing or ambiguous",
                next_action="Read the complete v3 report list and resolve the exact ID before another write.",
            )
        preimage = matches[0]
        ownership = require_report_authority(
            client,
            preimage,
            object_kind="report template",
            object_id=selected_id,
            marker_fields=("remark",),
            field="report_id",
        )
        inputs = {"id": selected_id, "is_deleted": 1}
        raw_preview = client._preview_mutation(TEMPLATE_UPDATE, inputs)
        mutation = client._execute_mutation(TEMPLATE_UPDATE, inputs)
        if any(
            response_id(row.get("id"), "id") == selected_id
            for row in catalog(client, TEMPLATE_LIST)
        ):
            raise MutationReadbackError(
                "v3 report still exists after the delete acknowledgement",
                next_action="Inspect the exact report template before another explicit delete.",
            )
        return completed(
            raw_preview,
            mutation,
            {
                "id": selected_id,
                "marker": marker(preimage, ("remark",)),
                "deleted": True,
                "ownership": ownership.public(),
            },
            "deleted",
            preimage,
        )


__all__ = [
    "MARKER_PREFIX",
    "SCHEMA_VERSION",
    "create_report",
    "create_subscription",
    "create_subscription_report",
    "delete_report",
    "delete_subscription",
    "delete_subscription_report",
    "marker_in_report",
    "marker_in_subscription",
]
