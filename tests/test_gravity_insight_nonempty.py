from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk import cli, nonempty_cli, nonempty_runtime, nonempty_support
from gravity_sdk.nonempty import (
    SearchDimension,
    _apply_found_draft,
    _build_plan,
    _iter_combinations,
    discover_nonempty,
    task_empty_sample_operation_ids,
)
from gravity_sdk.prober import probe_support
from gravity_sdk.prober.probe_support import conclusion, data_nonempty
from gravity_sdk.prober.promotion import _runnable_example_inputs
from gravity_sdk.prober.transport import HttpObservation


ROOT = Path(__file__).resolve().parents[1]


def _source(operation_id: str = "report.synthetic.query") -> dict[str, object]:
    return {
        "operation": {
            "operation_id": operation_id,
            "effect": "read",
            "upstream_method": "POST",
            "path_template": "/report/api/v1/synthetic/list/",
            "input_fields": {
                "scope": {"type": "string", "enum": ["primary", "secondary"]},
                "date_range": {"type": "array", "item_type": "string"},
                "filters": {"type": "array"},
            },
            "request": {
                "defaults": {"filters": []},
                "path_fields": [],
                "query_fields": [],
                "body_fields": ["scope", "date_range", "filters"],
                "fixed_query": {},
                "fixed_body": {},
            },
            "live_probe": {
                "enabled": False,
                "inputs": {
                    "scope": "primary",
                    "date_range": ["$today", "$today"],
                    "filters": [],
                },
            },
            "required_parent": [],
            "provenance": {"family": "synthetic.family"},
        },
        "draft": {"blockers": []},
    }


class _Response:
    status_code = 200
    headers: dict[str, str] = {}

    def __init__(self, payload: object) -> None:
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _SequenceSession:
    headers: dict[str, str] = {}

    def __init__(self, payloads: list[object]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs: object) -> _Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        payload = self.payloads.pop(0)
        return _Response(payload)


class _TargetClient:
    def __init__(self, recording: object) -> None:
        self.recording = recording

    def read(self, operation_id: str, inputs: dict[str, object]) -> dict[str, object]:
        self.recording.request(
            "POST",
            "https://web.gravity-engine.com/report/api/v1/synthetic/list/",
            json=inputs,
        )
        return {"operation_id": operation_id, "status": "empty"}


class _StableClient:
    def __init__(self, recording: object) -> None:
        self.recording = recording

    @classmethod
    def from_env(cls, **kwargs: object) -> "_StableClient":
        runtime = kwargs["runtime"]
        return cls(runtime.recording)

    def read(self, operation_id: str, inputs: dict[str, object]) -> dict[str, object]:
        response = self.recording.request(
            "GET",
            f"https://web.gravity-engine.com/{operation_id}",
            params=inputs,
        )
        return response.json()

    def probe(self, operation_id: str) -> dict[str, object]:
        return self.read(operation_id, {})


def _run_discovery(
    tmp_path: Path,
    monkeypatch: object,
    *,
    source: dict[str, object],
    payloads: list[object],
    request_budget: int = 12,
    input_overrides: dict[str, object] | None = None,
) -> tuple[dict[str, object], _SequenceSession]:
    draft_root = tmp_path / "drafts"
    operation_root = tmp_path / "operations"
    cache_root = tmp_path / "tmp" / "cache"
    draft_root.mkdir(parents=True, exist_ok=True)
    operation_root.mkdir(parents=True, exist_ok=True)
    operation_id = str(source["operation"]["operation_id"])
    (draft_root / f"{operation_id}.json").write_text(
        json.dumps(source), encoding="utf-8"
    )
    session = _SequenceSession(payloads)
    session.runtime_sources = []
    monkeypatch.setattr(nonempty_support, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        nonempty_runtime, "_ensure_auth", lambda: {"auth_state": "valid_token"}
    )
    monkeypatch.setattr(
        nonempty_runtime,
        "build_runtime",
        lambda recording: SimpleNamespace(recording=recording),
    )
    def build_target(runtime_source: object, runtime: object) -> _TargetClient:
        session.runtime_sources.append(runtime_source)
        return _TargetClient(runtime.recording)

    monkeypatch.setattr(nonempty_runtime, "build_draft_client", build_target)
    monkeypatch.setattr(
        nonempty_runtime, "sdk_parts", lambda: {"GravityInsightClient": _StableClient}
    )
    result = discover_nonempty(
        operation_id,
        input_overrides=input_overrides,
        request_budget=request_budget,
        interval_seconds=0.3,
        cache_root=cache_root,
        draft_root=draft_root,
        operation_root=operation_root,
        session=session,
        anchor=date(2026, 8, 9),
    )
    return result, session


def test_plan_derives_parent_enum_and_date_dimensions_from_contract() -> None:
    source = _source()
    source["operation"]["input_fields"]["app_selection"] = {
        "type": "array",
        "item_type": "string",
    }
    source["operation"]["live_probe"]["inputs"]["app_selection"] = ["$first"]

    base, dimensions, unresolved = _build_plan(
        source,
        overrides={},
        parent_values={"app_selection": [1, 2, 3]},
        parent_failures={},
        anchor=date(2026, 8, 9),
    )

    assert base == {"filters": []}
    assert [(item.label, item.source) for item in dimensions] == [
        ("app_selection", "required_parent"),
        ("scope", "enum"),
        ("date_range", "date_window"),
    ]
    assert {item["field"] for item in unresolved} == {"filters"}
    first = next(_iter_combinations(base, dimensions))
    assert first["app_selection"] == ["1"]
    assert first["scope"] == "primary"
    assert first["date_range"] == ["2026-07-11", "2026-08-09"]


def test_weighted_search_varies_parent_before_lower_priority_dimensions() -> None:
    dimensions = [
        SearchDimension("parent", "required_parent", ({"parent": 1}, {"parent": 2}), 1),
        SearchDimension("enum", "enum", ({"enum": "a"}, {"enum": "b"}), 2),
        SearchDimension("date", "date_window", ({"date": "wide"}, {"date": "short"}), 3),
    ]

    combinations = list(_iter_combinations({}, dimensions))

    assert combinations[0] == {"parent": 1, "enum": "a", "date": "wide"}
    assert combinations[1] == {"parent": 2, "enum": "a", "date": "wide"}
    assert combinations[2] == {"parent": 1, "enum": "b", "date": "wide"}


def test_discovery_stops_on_first_nonempty_and_caches_result(
    tmp_path: Path, monkeypatch: object
) -> None:
    empty = {"code": 0, "data": {"list": [], "page_info": {}}}
    nonempty_payload = {
        "code": 0,
        "data": {"list": [{"campaign_id": "business-value"}], "page_info": {}},
    }
    source = _source()
    result, session = _run_discovery(
        tmp_path,
        monkeypatch,
        source=source,
        payloads=[empty, nonempty_payload, empty],
    )

    assert result["resolution"] == "unblocked"
    assert result["request_stats"]["total"] == 2
    assert result["search"]["attempted_combinations"] == 2
    assert result["search"]["stopped_early_on_nonempty"] is True
    assert len(session.calls) == 2
    assert result["schema_version"] == "gravity-insight.nonempty-discovery.v2"
    assert result["successful_input"] == {
        "field_names": ["date_range", "filters", "scope"],
        "values_redacted": True,
    }
    assert result["cache"]["contains_business_values"] is False
    rendered = json.dumps(result)
    assert "primary" not in rendered
    assert "secondary" not in rendered
    cache_path = tmp_path / result["cache"]["path"]
    assert "primary" not in cache_path.read_text(encoding="utf-8")
    assert "secondary" not in cache_path.read_text(encoding="utf-8")

    cached, second_session = _run_discovery(
        tmp_path,
        monkeypatch,
        source=source,
        payloads=[],
    )
    assert cached["cache"]["hit"] is True
    assert cached["request_stats"]["total"] == 0
    assert cached["request_stats"]["reused_request_count"] == 2
    assert cached["cache"]["contains_business_values"] is False
    assert second_session.calls == []


def test_legacy_business_value_cache_is_not_reused(tmp_path: Path) -> None:
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "gravity-insight.nonempty-discovery.v1",
                "inputs": {"album_id": "private-business-value"},
            }
        ),
        encoding="utf-8",
    )

    assert nonempty_support._cached_result(path) is None


def test_resolved_parent_is_not_required_in_temporary_target_registry(
    tmp_path: Path, monkeypatch: object
) -> None:
    source = _source()
    source["operation"]["input_fields"]["selection"] = {
        "type": "array",
        "item_type": "string",
    }
    source["operation"]["request"]["body_fields"].append("selection")
    source["operation"]["live_probe"]["inputs"]["selection"] = ["$first"]
    source["operation"]["required_parent"] = [
        {
            "operation_id": "app.list",
            "input_field": "selection",
            "output_path": "data.list[].id",
            "selection": "caller_select",
        }
    ]
    payload = {"code": 0, "data": {"list": [{"id": "row"}]}}

    result, session = _run_discovery(
        tmp_path,
        monkeypatch,
        source=source,
        payloads=[payload],
        input_overrides={"selection": ["chosen-parent"]},
    )

    assert result["resolution"] == "unblocked"
    assert session.runtime_sources[0]["operation"]["required_parent"] == []


def test_discovery_extracts_recursive_parent_candidates(
    tmp_path: Path, monkeypatch: object
) -> None:
    source = _source()
    source["operation"]["input_fields"] = {
        "album_id": {"type": "integer", "required": True}
    }
    source["operation"]["request"]["defaults"] = {}
    source["operation"]["request"]["body_fields"] = ["album_id"]
    source["operation"]["live_probe"]["inputs"] = {
        "album_id": "$parent:album_id"
    }
    source["operation"]["required_parent"] = [
        {
            "operation_id": "material.album.tree",
            "input_field": "album_id",
            "output_path": "data.tree..id",
            "selection": "caller_select",
        }
    ]
    operation_root = tmp_path / "operations"
    operation_root.mkdir(parents=True)
    (operation_root / "material.album.tree.json").write_text(
        json.dumps(
            {
                "operation": {
                    "operation_id": "material.album.tree",
                    "effect": "read",
                    "input_fields": {},
                    "request": {"defaults": {}},
                    "live_probe": {"inputs": {}},
                }
            }
        ),
        encoding="utf-8",
    )
    parent_payload = {
        "status": "success",
        "data": {
            "tree": [
                {"id": 11, "children": [{"id": 22}]},
                {"id": 33},
            ]
        },
    }
    target_payload = {"code": 0, "data": {"list": [{"id": "row"}]}}

    result, session = _run_discovery(
        tmp_path,
        monkeypatch,
        source=source,
        payloads=[parent_payload, target_payload],
    )

    assert result["resolution"] == "unblocked"
    assert result["parents"][0]["candidate_count"] == 3
    assert session.calls[1]["json"]["album_id"] == 11


def test_missing_required_parent_candidates_skip_invalid_target_attempts(
    tmp_path: Path, monkeypatch: object
) -> None:
    source = _source()
    source["operation"]["input_fields"]["selection"] = {
        "type": "array",
        "item_type": "string",
    }
    source["operation"]["request"]["body_fields"].append("selection")
    source["operation"]["live_probe"]["inputs"]["selection"] = ["$first"]
    source["operation"]["required_parent"] = [
        {
            "operation_id": "missing.parent.list",
            "input_field": "selection",
            "output_path": "data.list[].id",
            "selection": "caller_select",
        }
    ]

    result, session = _run_discovery(
        tmp_path, monkeypatch, source=source, payloads=[]
    )

    assert result["resolution"] == "undetermined"
    assert result["search"]["attempted_combinations"] == 0
    assert result["search"]["evaluated_combinations"] == 0
    assert session.calls == []


def test_confirmed_empty_requires_exhaustive_nonopaque_space(
    tmp_path: Path, monkeypatch: object
) -> None:
    source = _source()
    source["operation"]["input_fields"] = {
        "scope": {"type": "string", "enum": ["primary", "secondary"]}
    }
    source["operation"]["request"]["defaults"] = {}
    source["operation"]["request"]["body_fields"] = ["scope"]
    source["operation"]["live_probe"]["inputs"] = {"scope": "primary"}
    empty = {"code": 0, "data": {"list": []}}

    result, _ = _run_discovery(
        tmp_path, monkeypatch, source=source, payloads=[empty, empty]
    )

    assert result["resolution"] == "confirmed_empty"
    assert result["search"]["planned_combinations"] == 2
    assert result["search"]["attempted_combinations"] == 2
    assert result["search"]["unresolved_dimensions"] == []


def test_empty_opaque_space_remains_undetermined(
    tmp_path: Path, monkeypatch: object
) -> None:
    source = _source()
    empty = {"code": 0, "data": {"list": []}}

    result, _ = _run_discovery(
        tmp_path,
        monkeypatch,
        source=source,
        payloads=[empty] * 8,
    )

    assert result["resolution"] == "undetermined"
    assert result["search"]["exhausted_planned_combinations"] is True
    assert {
        item["reason"] for item in result["search"]["unresolved_dimensions"]
    } == {"opaque_candidate_space"}


def test_semantic_diagnostics_retain_parameter_names_without_messages(
    tmp_path: Path, monkeypatch: object
) -> None:
    source = _source()
    source["operation"]["input_fields"] = {
        "scope": {"type": "string", "enum": ["primary"]}
    }
    source["operation"]["request"]["defaults"] = {}
    source["operation"]["request"]["body_fields"] = ["scope"]
    source["operation"]["live_probe"]["inputs"] = {"scope": "primary"}
    payload = {"code": 1003, "extra": {"scope": "private response message"}}

    result, _ = _run_discovery(
        tmp_path, monkeypatch, source=source, payloads=[payload]
    )

    assert result["resolution"] == "undetermined"
    assert result["search"]["diagnostics"]["semantic_parameter_hints"] == [
        {"field": "scope", "basis": "semantic_error_extra_key"}
    ]
    assert "private response message" not in json.dumps(result)


def test_request_budget_caps_lazy_cartesian_search(
    tmp_path: Path, monkeypatch: object
) -> None:
    source = _source()
    source["operation"]["input_fields"] = {
        "scope": {"type": "string", "enum": ["a", "b", "c", "d"]}
    }
    source["operation"]["request"]["defaults"] = {}
    source["operation"]["request"]["body_fields"] = ["scope"]
    source["operation"]["live_probe"]["inputs"] = {"scope": "a"}
    empty = {"code": 0, "data": {"list": []}}

    result, session = _run_discovery(
        tmp_path,
        monkeypatch,
        source=source,
        payloads=[empty, empty],
        request_budget=2,
    )

    assert result["resolution"] == "undetermined"
    assert result["request_stats"]["total"] == 2
    assert result["search"]["budget_exhausted"] is True
    assert len(session.calls) == 2


def test_found_draft_evidence_retains_schema_but_not_business_values(
    tmp_path: Path, monkeypatch: object
) -> None:
    source_path = (
        ROOT
        / "src"
        / "gravity_sdk"
        / "contracts"
        / "drafts"
        / "promotion.youdao.campaign.list.json"
    )
    source = json.loads(source_path.read_text(encoding="utf-8"))
    draft_root = tmp_path / "drafts"
    evidence_root = tmp_path / "evidence"
    draft_root.mkdir()
    (draft_root / source_path.name).write_text(
        json.dumps(source, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(nonempty_support, "DEFAULT_EVIDENCE_ROOT", evidence_root)
    monkeypatch.setattr(probe_support, "REPO_ROOT", tmp_path)
    observation = HttpObservation(
        operation_id="promotion.youdao.campaign.list",
        family_id="promotion.family.017",
        purpose="nonempty_search",
        method="POST",
        path="/turbo_engine/api/v1/youdao/report/campaign/list/",
        status_code=200,
        payload={
            "code": 0,
            "data": {
                "list": [{"campaign_id": "business-secret-value"}],
                "page_info": {
                    "page": 1,
                    "page_size": 20,
                    "total_page": 1,
                },
            },
        },
        request_shape={"body": {"date_list": ["string"]}},
    )

    applied = _apply_found_draft(
        source, observation, parent_summary=None, draft_root=draft_root
    )

    evidence = (tmp_path / applied["evidence"]).read_text(encoding="utf-8")
    persisted = (draft_root / source_path.name).read_text(encoding="utf-8")
    assert "business-secret-value" not in evidence
    assert "business-secret-value" not in persisted
    assert "data.list[].campaign_id" in evidence


def test_cli_dispatches_nonempty_discovery_without_building_normal_client() -> None:
    args = cli.build_parser().parse_args(
        [
            "discover-nonempty",
            "report.synthetic.query",
            "--request-budget",
            "7",
            "--candidate-limit",
            "3",
            "--refresh-cache",
        ]
    )
    expected = {"schema_version": "gravity-insight.nonempty-discovery.v2"}
    with patch(
        "gravity_sdk.nonempty.discover_nonempty", return_value=expected
    ) as discover:
        result = nonempty_cli.dispatch_or(args, cli._object_input, cli.run)

    assert result == expected
    discover.assert_called_once_with(
        "report.synthetic.query",
        input_overrides={},
        request_budget=7,
        candidate_limit=3,
        interval_seconds=0.31,
        refresh_cache=True,
        apply_draft=False,
    )


def test_additive_confirmation_is_success_and_examples_resolve_only_dates() -> None:
    assert conclusion(200, {"code": 0, "data": {"list": [{}]}}, "contract_changed_additive") == "success"
    runnable = _runnable_example_inputs(
        {"date_list": ["$yesterday", "$today"], "page": 1}
    )
    assert runnable is not None
    assert all(not value.startswith("$") for value in runnable["date_list"])
    assert _runnable_example_inputs({"app_id": "$first_app_id"}) is None


def test_null_only_object_is_not_a_nonempty_probe_sample() -> None:
    assert not data_nonempty({"code": 0, "data": {"conf": None}})
    assert not data_nonempty({"code": 0, "data": {"conf": {"value": None}}})
    assert conclusion(200, {"code": 0, "data": {"conf": None}}, None) == (
        "inconclusive_empty"
    )


def test_false_and_zero_remain_meaningful_probe_values() -> None:
    assert data_nonempty({"code": 0, "data": {"conf": {"is_enabled": False}}})
    assert data_nonempty({"code": 0, "data": {"total": 0}})


def test_task_scope_tracks_integrated_exact_blocker_sets() -> None:
    operation_ids = task_empty_sample_operation_ids(
        ROOT / "src" / "gravity_sdk" / "contracts" / "drafts"
    )

    assert len(operation_ids) == 118
