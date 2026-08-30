"""Minimum-probe parent resolvers owned by the public Insight client.

These helpers stay on ``GravityInsightClient`` through ``ProbeFirstMixin`` so
``probe_inputs`` and existing patches keep the same method names. The live
probe capability is unchanged; only the implementation home moved.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from .catalog import APP_LIST_OPERATION_ID, _PARENT_INPUT_PLACEHOLDERS
from .errors import PermissionUnavailableError, PolicyViolation


def _probe_operation(*parts: str) -> str:
    operation_id = ".".join(parts)
    if operation_id not in _PARENT_INPUT_PLACEHOLDERS:
        raise PolicyViolation("live probe parent operation is not declared")
    return operation_id


def envelope_rows(envelope: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    data = envelope.get("data")
    rows: Any = data
    if isinstance(data, Mapping):
        rows = data.get("list", data.get("items", []))
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, Mapping)]


def first_dashboard_coordinates(
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


def first_enumerable_property(rows: Sequence[Mapping[str, Any]]) -> str | None:
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


def _usable_split_order_row(row: Mapping[str, Any]) -> bool:
    return bool(
        isinstance(row.get("PayEventTime"), str)
        and row.get("PayEventTime")
        and isinstance(row.get("TraceID"), (str, int))
        and not isinstance(row.get("TraceID"), bool)
        and isinstance(row.get("ClientID"), (str, int))
        and not isinstance(row.get("ClientID"), bool)
        and isinstance(row.get("$split_trace_id_list"), (list, tuple))
        and bool(row.get("$split_trace_id_list"))
    )


class ProbeFirstMixin:
    """Resolve `$first_*` live-probe placeholders from governed reads."""

    def _first_probe_app_id(self) -> str:
        with self._probe_lock:
            cached = self._probe_values.get("first_app_id")
            if isinstance(cached, str) and cached:
                return cached
            envelope = self.read(APP_LIST_OPERATION_ID, {"page": 1, "page_size": 1})
            rows = envelope_rows(envelope)
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
            rows = envelope_rows(envelope)
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
                _probe_operation("analysis", "event", "list"),
                {"app_id": app_id, "page": 1, "page_size": 1},
            )
            rows = envelope_rows(envelope)
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
                _probe_operation("analysis", "user_property", "list"),
                {"app_id": app_id, "page": 1, "page_size": 100},
                max_pages=10,
                max_items=1_000,
            )
            property_name = first_enumerable_property(envelope_rows(envelope))
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
                _probe_operation("analysis", "event", "info"),
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
            property_name = first_enumerable_property(rows)
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
                _probe_operation("analysis", "segment", "list"),
                {"app_id": app_id, "page": 1, "page_size": 1},
            )
            rows = envelope_rows(envelope)
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
                _probe_operation("analysis", "report_config", "list"),
                {"app_id": app_id, "page": 1, "page_size": 1},
            )
            rows = envelope_rows(envelope)
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
                envelope = self.read(
                    _probe_operation("analysis", "dashboard", "tree"),
                    {"app_id": app_id},
                )
                coordinates = first_dashboard_coordinates(envelope_rows(envelope))
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
                _probe_operation("analysis", "user_detail", "list"),
                {
                    "app_id": app_id,
                    "fields": ["ClientID"],
                    "page": 1,
                    "page_size": 1,
                },
            )
            rows = envelope_rows(envelope)
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
                    _probe_operation("analysis", "order_detail", "list"),
                    {
                        "app_id": app_id,
                        "fields": list(field_map.values()),
                        "page": 1,
                        "page_size": 100,
                    },
                )
                cached = next(
                    (row for row in envelope_rows(envelope) if _usable_split_order_row(row)),
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
                _probe_operation("report", "multidim", "template", "preset", "list"),
                {"filters": [], "page": 1, "page_size": 1},
            )
            rows = envelope_rows(envelope)
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
