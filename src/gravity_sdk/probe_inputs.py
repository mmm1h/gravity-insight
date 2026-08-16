"""Resolve value-free minimum-probe placeholders from governed contracts."""

from __future__ import annotations

import secrets
import time
from datetime import date, timedelta
from typing import Any, Mapping

from .errors import PermissionUnavailableError, PolicyViolation
from .parent_resolution import coerce_parent_value, extract_parent_values
from .attribution_user_detail import first_probe_testing_device_field


ParentCache = dict[str, Mapping[str, Any]]


def resolve_probe_inputs(
    client: Any, value: Any, *, operation_id: str | None = None
) -> Any:
    """Resolve one live-probe input tree without persisting selected values."""

    return _resolve(
        client,
        value,
        operation_id=operation_id,
        input_field=None,
        parent_cache={},
    )


def _resolve(
    client: Any,
    value: Any,
    *,
    operation_id: str | None,
    input_field: str | None,
    parent_cache: ParentCache,
) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _resolve(
                client,
                item,
                operation_id=operation_id,
                input_field=str(key),
                parent_cache=parent_cache,
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            _resolve(
                client,
                item,
                operation_id=operation_id,
                input_field=input_field,
                parent_cache=parent_cache,
            )
            for item in value
        ]
    if isinstance(value, str) and value.startswith("$"):
        return _placeholder(
            client,
            value,
            operation_id=operation_id,
            input_field=input_field,
            parent_cache=parent_cache,
        )
    return value


def _placeholder(
    client: Any,
    value: str,
    *,
    operation_id: str | None,
    input_field: str | None,
    parent_cache: ParentCache,
) -> Any:
    parent_field = _parent_placeholder_field(value, input_field)
    if parent_field is not None:
        if operation_id is None:
            raise PolicyViolation("parent probe placeholder has no target operation")
        return _declared_parent_value(
            client, operation_id, parent_field, parent_cache
        )
    exact = {
        "$analysis_query_id": _new_analysis_query_id,
        "$first_app_id": client._first_probe_app_id,
        "$first_client_id": client._first_probe_client_id,
        "$first_event_name": client._first_probe_event_name,
        "$first_event_property_name": client._first_probe_event_property_name,
        "$first_report_config_id": client._first_probe_report_config_id,
        "$first_segment_id": client._first_probe_segment_id,
        "$first_testing_device_app_id": lambda: first_probe_testing_device_field(client, "app_id"),
        "$first_testing_device_id": lambda: first_probe_testing_device_field(client, "device_id"),
        "$first_user_property_name": client._first_probe_user_property_name,
    }
    if value == "$today":
        return date.today().isoformat()
    if value == "$yesterday":
        return (date.today() - timedelta(days=1)).isoformat()
    if value in exact:
        return exact[value]()
    if value in {"$first_dashboard_id", "$first_dashboard_space_id"}:
        field = "space_id" if value.endswith("space_id") else "dashboard_id"
        return client._first_probe_dashboard_field(field)
    if value.startswith("$first_order_"):
        return client._first_probe_order_field(value.removeprefix("$first_order_"))
    if value.startswith("$first_") and value.endswith("_advertiser_id"):
        platform = value.removeprefix("$first_").removesuffix("_advertiser_id")
        if platform in {"bytedance", "tencent", "kuaishou"}:
            return client._first_probe_advertiser_id(platform)
    if value in {"$first_preset_template_id", "$first_preset_template_category"}:
        field = value.removeprefix("$first_preset_template_")
        return client._first_probe_preset_template_field(field)
    raise PolicyViolation("live probe contains an unsupported dynamic placeholder")


def _declared_parent_value(
    client: Any,
    operation_id: str,
    input_field: str,
    cache: ParentCache,
) -> Any:
    parent = _parent_binding(client.describe(operation_id), input_field)
    parent_id = str(parent.get("operation_id") or "")
    output_path = str(parent.get("output_path") or "")
    if not parent_id or not output_path:
        raise PolicyViolation("parent probe declaration is incomplete")
    if parent_id not in cache:
        cache[parent_id] = client.probe(parent_id)
    values = extract_parent_values(cache[parent_id], output_path)
    if not values:
        raise PermissionUnavailableError(
            f"required parent {parent_id} has no selectable value"
        )
    field = client._registry.get(operation_id).fields[input_field]
    field_type = field.item_type if field.type == "array" else field.type
    candidates = [
        coerce_parent_value(item, field_type or "any") for item in values
    ]
    selection = str(parent.get("selection") or "caller_select")
    if selection == "unique" and len(candidates) != 1:
        raise PermissionUnavailableError(
            f"required parent {parent_id} did not yield one unique value"
        )
    return candidates if selection == "all" else candidates[0]


def _parent_binding(
    description: Mapping[str, Any], input_field: str
) -> Mapping[str, Any]:
    parents = description.get("required_parent", [])
    matches = [
        item
        for item in parents
        if isinstance(item, Mapping) and item.get("target_input") == input_field
    ]
    if len(matches) != 1:
        raise PolicyViolation("parent probe placeholder has no unique declaration")
    return matches[0]


def _parent_placeholder_field(value: str, fallback: str | None) -> str | None:
    if value == "$parent":
        return fallback
    if value.startswith("$parent:"):
        return value.partition(":")[2] or None
    return None


def _new_analysis_query_id() -> str:
    milliseconds = f"{int(time.time() * 1_000):013d}"[-13:]
    entropy = secrets.token_hex(10)[:19]
    return milliseconds + entropy


__all__ = ["resolve_probe_inputs"]
