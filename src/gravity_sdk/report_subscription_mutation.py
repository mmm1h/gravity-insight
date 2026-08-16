"""Governed report-subscription create/delete lifecycle."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .actionable_error_values import actual_value
from .errors import MutationReadbackError, ObjectAlreadyExistsError
from .mutation_lifecycle import WRITE_LOCK, mutation_marker
from .report_contracts import SUBSCRIBE_CREATE, SUBSCRIBE_DELETE, SUBSCRIBE_LIST
from .report_mutation_support import (
    catalog,
    completed,
    idempotent,
    json_text,
    marker,
    positive_id,
    preview,
    require_created,
    require_report_authority,
    text_sequence,
    two_texts,
    unique_marker,
    caller_text,
    response_id,
)


def create_subscription(
    client: Any,
    *,
    report_id: int,
    report_name: str,
    subscribe_time: Sequence[str],
    selected_columns: Sequence[str],
    idempotency_key: str | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    """Create one disabled subscription with no recipients, or fail closed."""

    selected_id, selected_marker, name, inputs = _subscription_inputs(
        report_id,
        report_name,
        subscribe_time,
        selected_columns,
        idempotency_key,
    )
    raw_preview = preview(
        client._preview_mutation(SUBSCRIBE_CREATE, inputs),
        target={
            "report_id": selected_id,
            "name": name,
            "marker": selected_marker,
        },
        impact="Create one disabled report subscription with an empty recipient list; no test notification is sent.",
    )
    if not execute:
        return raw_preview
    with WRITE_LOCK:
        rows = catalog(client, SUBSCRIBE_LIST)
        existing = unique_marker(
            rows, selected_marker, fields=("name", "wildcard_name")
        )
        if existing is not None:
            return idempotent(existing, SUBSCRIBE_CREATE)
        if any(row.get("name") == name for row in rows):
            raise ObjectAlreadyExistsError(
                f"actual value: {actual_value(name)}; allowed value: a unique subscription name",
                field="name",
                next_action="Choose a new idempotency key and run dry-run again.",
            )
        mutation = client._execute_mutation(SUBSCRIBE_CREATE, inputs)
        created = require_created(
            client,
            SUBSCRIBE_LIST,
            selected_marker,
            fields=("name", "wildcard_name"),
            name=name,
        )
        if created.get("subscribe_status") not in (0, "0"):
            raise MutationReadbackError(
                "created subscription did not round-trip as disabled",
                next_action="Immediately inspect and disable the marked subscription; do not call the test route.",
            )
        if created.get("send_way") not in (None, "", "[]", []):
            raise MutationReadbackError(
                "created subscription unexpectedly contains a recipient",
                next_action="Immediately inspect and remove the marked subscription; do not call the test route.",
            )
        return completed(raw_preview, mutation, created, "created")


def _subscription_inputs(
    report_id: int,
    report_name: str,
    subscribe_time: Sequence[str],
    selected_columns: Sequence[str],
    idempotency_key: str | None,
) -> tuple[str, str, str, dict[str, Any]]:
    selected_id = positive_id(report_id, "report_id")
    selected_report_name = caller_text(report_name, "report_name", 110)
    dates = two_texts(subscribe_time, "subscribe_time")
    columns = text_sequence(selected_columns, "selected_columns", 256)
    selected_marker = mutation_marker(
        "report_subscription",
        {
            "report_id": selected_id,
            "subscribe_time": dates,
            "selected_columns": columns,
        },
        idempotency_key=idempotency_key,
    )
    wildcard_name = f"<报表名称>_{selected_marker}"
    name = f"{selected_report_name}_{selected_marker}"
    return selected_id, selected_marker, name, {
        "id": selected_id,
        "wildcard_name": wildcard_name,
        "name": name,
        "report_type": 2,
        "subscribe_status": 0,
        "subscribe_time": dates,
        "send_way": "[]",
        "report_conf_template_id": selected_id,
        "subscribe_content": ["excel"],
        "subscribe_selected_columns": json_text(columns, "selected_columns"),
    }


def delete_subscription(
    client: Any,
    subscription_id: int | str,
    *,
    execute: bool = False,
) -> dict[str, Any]:
    """Delete one exact subscription after marker-or-owner preflight."""

    selected_id = positive_id(subscription_id, "subscription_id")
    if not execute:
        from .report_mutation_support import dependent_preview

        return dependent_preview(
            SUBSCRIBE_DELETE,
            {"id": selected_id},
            "Delete this subscription only after complete-list owner readback.",
        )
    with WRITE_LOCK:
        rows = catalog(client, SUBSCRIBE_LIST)
        matches = [
            row for row in rows if response_id(row.get("id"), "id") == selected_id
        ]
        if len(matches) != 1:
            raise MutationReadbackError(
                "subscription delete preimage is missing or ambiguous",
                next_action="Read the complete subscription list and resolve the exact ID before another write.",
            )
        preimage = matches[0]
        ownership = require_report_authority(
            client,
            preimage,
            object_kind="report subscription",
            object_id=selected_id,
            marker_fields=("name", "wildcard_name"),
            field="subscription_id",
        )
        inputs = {"ids": [selected_id]}
        raw_preview = client._preview_mutation(SUBSCRIBE_DELETE, inputs)
        mutation = client._execute_mutation(SUBSCRIBE_DELETE, inputs)
        remaining = catalog(client, SUBSCRIBE_LIST)
        if any(response_id(row.get("id"), "id") == selected_id for row in remaining):
            raise MutationReadbackError(
                "subscription still exists after the delete acknowledgement",
                next_action="Inspect the exact subscription before another explicit delete.",
            )
        return completed(
            raw_preview,
            mutation,
            {
                "id": selected_id,
                "marker": marker(preimage, ("name", "wildcard_name")),
                "deleted": True,
                "ownership": ownership.public(),
            },
            "deleted",
            preimage,
        )


__all__ = ["create_subscription", "delete_subscription"]
