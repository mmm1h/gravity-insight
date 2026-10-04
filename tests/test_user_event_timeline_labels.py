"""Timeline rows key event properties by display label, unique only per event (#238)."""

from __future__ import annotations

from typing import Any, Mapping

from tests.test_gravity_insight_analysis import client_for, page

_OPERATIONS = (
    "analysis.user_event.list",
    "analysis.event.list",
    "analysis.event.info",
    "analysis.event_property.list",
    "analysis.user_property.list",
    "analysis.segment.list",
)
# "获得或消耗" is shared App-wide, as observed on the live catalog.
_PROPERTIES = [
    {"name": "stamina_action", "cname": "获得或消耗", "data_type": "STRING", "visible": True},
    {"name": "piece_action", "cname": "获得或消耗", "data_type": "STRING", "visible": True},
    {"name": "stamina_change_count", "cname": "体力变化次数", "data_type": "INT", "visible": True},
]


def _row(event: str, **properties: Any) -> dict[str, Any]:
    return {"事件名称": event, "事件时间": "2026-10-03 10:00:00", "事件英文名": event, **properties}


def _read(
    rows: list[Mapping[str, Any]], properties: list[dict[str, Any]] = _PROPERTIES, **inputs: Any
) -> tuple[dict[str, Any], list[Any]]:
    def handler(_method: str, path: str, kwargs: Mapping[str, Any]):
        if path.endswith("event_list/"):
            return page([{"name": "stamina_res", "cname": "体力", "visible": True},
                         {"name": "piece_res", "cname": "碎片", "visible": True}])
        if path.endswith("event_property_list/"):
            return page(properties)
        if path.endswith("event_info/"):
            event = kwargs["query"]["event_name"]
            bound = {"stamina_res": ("stamina_action", "stamina_change_count"), "piece_res": ("piece_action",)}[event]
            return {"code": 0, "data": {"properties": {
                "common": [], "preset": [],
                "custom": [row for row in _PROPERTIES if row["name"] in bound],
            }}}
        if path.endswith(("user_property_list/", "segment/list/")):
            return page([])
        if path.endswith("user/event/list/"):
            return {"code": 0, "data": {"event_timeline": [{"timeline": "2026-10-03", "list": rows}], "summary": []}}
        raise AssertionError(path)

    client, transport = client_for(*_OPERATIONS, handler=handler)
    request = {
        "app_id": "101", "client_id": "client-1", "date_list": ["2026-10-03", "2026-10-03"],
        "page": 1, "page_size": 200, "fields": ["stamina_action", "stamina_change_count"], **inputs,
    }
    return client.read("analysis.user_event.list", request), transport.calls


def test_listed_event_maps_shared_labels_through_its_binding():
    result, calls = _read(
        [_row("stamina_res", 获得或消耗="get", 体力变化次数=2, 未选属性="omitted")],
        event_list=["stamina_res"],
    )
    event = result["data"]["event_timeline"][0]["list"][0]
    assert result["status"] == "success"
    assert (event["stamina_action"], event["stamina_change_count"], event["事件英文名"]) == ("get", 2, "stamina_res")
    assert "获得或消耗" not in event and "未选属性" not in event
    assert result["data"]["field_coverage"]["status"] == "complete"
    assert sum(path.endswith("event_info/") for _m, path, _k in calls) == 1


def test_unlisted_events_never_attribute_a_shared_label():
    # Without event_list, a piece_res row carrying the shared label must not
    # become stamina_action; the unique label still maps.
    result, calls = _read([_row("piece_res", 获得或消耗="piece-value", 体力变化次数=1)], event_list=[])
    event = result["data"]["event_timeline"][0]["list"][0]
    coverage = result["data"]["field_coverage"]
    assert "stamina_action" not in event and event["stamina_change_count"] == 1
    assert coverage["unmapped_fields"] == ["stamina_action"]
    assert any("event_list" in warning for warning in result["warnings"])
    assert not any(path.endswith("event_info/") for _m, path, _k in calls)


def test_absent_selected_property_is_partial_coverage_not_contract_drift():
    result, _calls = _read(
        [_row("stamina_res", 获得或消耗="get"), _row("stamina_res", 获得或消耗="use", 体力变化次数=1)],
        event_list=["stamina_res"],
    )
    coverage = result["data"]["field_coverage"]
    assert result["status"] == "success"
    assert (coverage["status"], coverage["missing_counts"]["stamina_change_count"]) == ("partial", 1)
    assert coverage["missing_fields"] == ["stamina_change_count"]


def test_listed_events_keep_app_wide_unique_labels_they_do_not_bind():
    # piece_res binds neither selected property; the App-wide unique label still maps.
    result, _calls = _read([_row("piece_res", 获得或消耗="piece-value", 体力变化次数=3)], event_list=["piece_res"])
    event = result["data"]["event_timeline"][0]["list"][0]
    coverage = result["data"]["field_coverage"]
    assert event["stamina_change_count"] == 3 and "stamina_action" not in event
    assert (coverage["status"], coverage["unmapped_fields"]) == ("partial", ["stamina_action"])


def test_a_selected_shared_label_is_never_certified_complete():
    result, _calls = _read(
        [_row("stamina_res", 获得或消耗="get"), _row("piece_res", 获得或消耗="piece-value")],
        fields=["获得或消耗"], event_list=[],
    )
    coverage = result["data"]["field_coverage"]
    assert (coverage["status"], coverage["unmapped_fields"]) == ("partial", ["获得或消耗"])
    assert any("shared labels" in warning for warning in result["warnings"])


def test_a_property_with_two_labels_stays_unmapped():
    properties = [{**_PROPERTIES[2], "dim_table": [{"name": "stamina_change_count", "cname": "ID"}]}]
    result, _calls = _read([_row("stamina_res", 体力变化次数=2)], properties=properties,
                           fields=["stamina_change_count"], event_list=[])
    coverage = result["data"]["field_coverage"]
    assert (coverage["status"], coverage["unmapped_fields"]) == ("partial", ["stamina_change_count"])
