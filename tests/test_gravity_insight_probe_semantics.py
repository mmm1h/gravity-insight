from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk import cli
from gravity_sdk.catalog import OperationCatalog
from gravity_sdk.executor import ReadExecutor
from gravity_sdk.models import load_operation_manifest
from gravity_sdk.prober import draft_probe
from gravity_sdk.prober.model import (
    build_draft,
    build_projection,
    candidate_fields,
    canonical_fingerprint,
    reevaluate_drafts,
    response_schema_sketch,
)
from gravity_sdk.probe_inputs import resolve_probe_inputs
from gravity_sdk.registry import PolicyEngine, Registry

try:
    from gravity_sdk import GravityInsightClient
    from gravity_sdk.transport import TransportResponse
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_sdk import GravityInsightClient
    from gravity_sdk.transport import TransportResponse


SENSITIVE_KEY = "user_count"
SENSITIVE_VALUE = "must-never-appear"


def _route(platform: str = "tencent") -> dict[str, object]:
    return {
        "business_module": "推广平台",
        "callers": ["loadAccounts"],
        "contract_family": None,
        "estimated_implementation_cost": "低",
        "first_occurrence": {"file": "raw/example.js", "offset": 10},
        "manifest_operations": [],
        "method": "GET",
        "method_certainty": "high",
        "method_evidence": ["same_request_options"],
        "path": f"/turbo_engine/api/v1/{platform}/manager/account/by_company/",
        "promotion_platform": platform,
        "status": "uncovered_read",
        "ui_texts": ["账户主体"],
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _payload(*, manual: bool = False) -> dict[str, object]:
    row = {"campaign_id": "campaign-1", SENSITIVE_KEY: SENSITIVE_VALUE}
    if manual:
        row["content"] = "classification-unknown"
    return {"code": 0, "data": [row]}


def _probe(
    tmp_path: Path, *, platform: str = "tencent", manual: bool = False
) -> tuple[dict[str, object], dict[str, object]]:
    source = build_draft(_route(platform), set())
    payload = _payload(manual=manual)
    discovery = SimpleNamespace(status_code=200, payload=payload)
    recording = SimpleNamespace(observations=[])
    with (
        patch.object(
            draft_probe,
            "_discover",
            return_value=(source, {}, None, discovery, []),
        ),
        patch.object(draft_probe, "_confirm", return_value=("success", "f" * 64)),
        patch.object(draft_probe, "relative", side_effect=lambda path: path.as_posix()),
    ):
        result = draft_probe.probe_draft(
            source,
            stable_client=object(),
            runtime=object(),
            recording=recording,
            evidence_root=tmp_path / "evidence",
            draft_root=tmp_path / "drafts",
        )
    updated = json.loads(
        (tmp_path / "drafts" / f"{source['operation']['operation_id']}.json").read_text(
            encoding="utf-8"
        )
    )
    return result, updated


def _exposed_response_fields(projection: dict[str, object]) -> set[str]:
    return {
        *(str(value) for value in projection.get("data_keys", [])),
        *(str(value) for value in projection.get("item_keys", [])),
    }


def test_sensitive_observation_completes_probe_when_projection_hides_it(
    tmp_path: Path,
) -> None:
    result, source = _probe(tmp_path)

    assert result["conclusion"] == "success"
    assert result["eligible"] is True
    assert source["draft"]["probe_evidence"][-1]["successful"] is True
    sensitive = [
        item
        for item in source["draft"]["candidate_fields"]
        if item["privacy_classification"] == "sensitive"
    ]
    assert [item["path"] for item in sensitive] == [f"data[].{SENSITIVE_KEY}"]
    assert SENSITIVE_KEY not in _exposed_response_fields(
        source["operation"]["response_projection"]
    )


def test_manual_review_remains_blocked_after_successful_transport_probe(
    tmp_path: Path,
) -> None:
    result, source = _probe(tmp_path, platform="bytedance", manual=True)

    assert result["conclusion"] == "success"
    assert source["draft"]["probe_evidence"][-1]["successful"] is True
    assert result["eligible"] is False
    assert "field_review_required" in result["missing"]
    assert source["draft"]["manual_review_fields"] == ["data[].content"]


def test_semantic_error_keeps_successfully_resolved_parent_attribution(
    tmp_path: Path,
) -> None:
    source = build_draft(_route("bytedance"), set())
    source["operation"]["input_fields"]["advertiser_id"] = {"type": "string"}
    source["operation"]["required_parent"] = [
        {
            "operation_id": "promotion.bytedance.account.list",
            "input_field": "advertiser_id",
            "output_path": "data.list[].advertiser_id",
            "selection": "caller_select",
        }
    ]
    discovery = SimpleNamespace(
        status_code=200,
        payload={"code": 2015, "data": None},
    )
    parent_summary = {
        "operation_id": "promotion.bytedance.account.list",
        "output_path": "data.list[].advertiser_id",
        "selection": "caller_select",
        "candidate_count": 1,
        "status": "resolved",
    }
    recording = SimpleNamespace(observations=[])
    with (
        patch.object(
            draft_probe,
            "_discover",
            return_value=(source, {}, parent_summary, discovery, []),
        ),
        patch.object(draft_probe, "relative", side_effect=lambda path: path.as_posix()),
    ):
        result = draft_probe.probe_draft(
            source,
            stable_client=object(),
            runtime=object(),
            recording=recording,
            evidence_root=tmp_path / "evidence",
            draft_root=tmp_path / "drafts",
        )

    updated = json.loads(
        (
            tmp_path
            / "drafts"
            / f"{source['operation']['operation_id']}.json"
        ).read_text(encoding="utf-8")
    )
    assert result["conclusion"] == "semantic_error"
    assert updated["draft"]["probe_evidence"][-1]["successful"] is False
    assert updated["draft"]["probe_evidence"][-1]["parent_resolved"] is True


def test_probe_bounds_frontend_page_size_before_contract_confirmation(
) -> None:
    source = build_draft(_route(), set())
    operation = source["operation"]
    operation["input_fields"] = {
        "page": {"type": "integer", "default": 1},
        "page_size": {"type": "number", "default": 2_000.0},
    }
    operation["request"]["query_fields"] = ["page", "page_size"]
    operation["request"]["defaults"] = {"page": 1, "page_size": 2_000.0}
    operation["live_probe"]["inputs"] = {"page": 1, "page_size": 2_000.0}
    payload = {
        "code": 0,
        "data": {
            "list": [{"campaign_id": "campaign-1"}],
            "page_info": {
                "page": 1,
                "page_size": 2_000,
                "total_page": 1,
                "total_number": 1,
            },
        },
    }
    updated, _pagination, _fields, _sketch = draft_probe._observed_contract(
        source, payload
    )
    captured: dict[str, object] = {}

    class _Client:
        def read(self, operation_id: str, inputs: dict[str, object]) -> dict[str, str]:
            captured.update({"operation_id": operation_id, "inputs": inputs})
            return {"status": "success", "schema_fingerprint": "f" * 64}

    recording = SimpleNamespace(
        observing=lambda *_args: contextlib.nullcontext()
    )
    with patch.object(draft_probe, "build_draft_client", return_value=_Client()):
        status, fingerprint = draft_probe._confirm(
            updated,
            {"page": 1, "page_size": 2_000.0},
            object(),
            recording,
            "test-family",
        )

    assert captured["inputs"] == {"page": 1, "page_size": 100}
    assert updated["operation"]["input_fields"]["page_size"] == {
        "type": "integer",
        "default": 100,
    }
    assert updated["operation"]["request"]["defaults"]["page_size"] == 100
    assert updated["operation"]["live_probe"]["inputs"]["page_size"] == 100
    assert (status, fingerprint) == ("success", "f" * 64)


class _StaticTransport:
    is_test_transport = True

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def request(self, *_args: object, **_kwargs: object) -> TransportResponse:
        return TransportResponse(200, self.payload, "2026-08-09T00:00:00Z")


class _ParentProbeTransport:
    is_test_transport = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def request(
        self, _method: str, _path: str, *, operation: object, body: object, **_: object
    ) -> TransportResponse:
        operation_id = str(operation.operation_id)
        request_body = dict(body)
        self.calls.append((operation_id, request_body))
        if operation_id == "material.album.tree":
            payload = {
                "code": 0,
                "data": {
                    "tree": [
                        {
                            "id": 17,
                            "label": "fixture",
                            "parent_id": 0,
                            "root_id": 17,
                            "has_alum": True,
                            "children": [
                                {
                                    "id": 22,
                                    "label": "child",
                                    "parent_id": 17,
                                    "root_id": 17,
                                    "has_alum": False,
                                    "children": [],
                                }
                            ],
                        }
                    ],
                    "image_size": 0,
                    "video_size": 0,
                },
            }
        else:
            assert operation_id == "material.album.list"
            payload = {
                "code": 0,
                "data": {
                    "list": [
                        {
                            "type": 1,
                            "has_alum": False,
                            "group": {
                                "id": 17,
                                "name": "fixture",
                                "material_num": 0,
                                "parent_id": 0,
                                "root_id": 17,
                            },
                            "material": None,
                        }
                    ],
                    "page_info": {
                        "page": 1,
                        "page_size": 1,
                        "total_page": 1,
                        "total_number": 1,
                    },
                },
            }
        return TransportResponse(200, payload, "2026-08-11T00:00:00Z")


def test_public_probe_resolves_recursive_declared_parent_and_target_type() -> None:
    root = Path(__file__).resolve().parents[1]
    contract_root = root / "src" / "gravity_sdk" / "contracts" / "operations"
    operation_ids = ("material.album.tree", "material.album.list")
    metadata = {
        operation_id: json.loads(
            (contract_root / f"{operation_id}.json").read_text(encoding="utf-8")
        )["operation"]
        for operation_id in operation_ids
    }
    manifest_root = root / "src" / "gravity_sdk" / "manifests"
    compiled = [
        item
        for path in manifest_root.glob("*.json")
        for item in json.loads(path.read_text(encoding="utf-8"))["operations"]
    ]
    selected = [
        item
        for item in compiled
        if item["operation_id"] in operation_ids
    ]
    operations = load_operation_manifest(
        {"manifest_version": 1, "operations": selected}
    )
    registry = Registry(operations)
    transport = _ParentProbeTransport()
    client = GravityInsightClient(
        registry,
        ReadExecutor(registry, PolicyEngine(registry), transport),
        operation_catalog=OperationCatalog(
            operations,
            contract_metadata=metadata,
        ),
    )

    result = client.probe("material.album.list")

    assert result["status"] == "success"
    assert [call[0] for call in transport.calls] == [
        "material.album.tree",
        "material.album.list",
    ]
    assert transport.calls[1][1]["album_id"] == "17"


def test_public_probe_reuses_one_parent_envelope_for_multiple_fields() -> None:
    class ParentClient:
        def __init__(self) -> None:
            self.calls = 0
            fields = {
                name: SimpleNamespace(type="integer", item_type=None)
                for name in ("advertiser_id", "project_id")
            }
            self._registry = SimpleNamespace(
                get=lambda _operation_id: SimpleNamespace(fields=fields)
            )

        def describe(self, _operation_id: str) -> dict[str, object]:
            return {
                "required_parent": [
                    {
                        "operation_id": "promotion.bytedance.project_filter.list",
                        "output_path": "data.list[].advertiser_id",
                        "selection": "caller_select",
                        "target_input": "advertiser_id",
                    },
                    {
                        "operation_id": "promotion.bytedance.project_filter.list",
                        "output_path": "data.list[].project_id",
                        "selection": "caller_select",
                        "target_input": "project_id",
                    },
                ]
            }

        def probe(self, _operation_id: str) -> dict[str, object]:
            self.calls += 1
            if self.calls > 1:
                raise AssertionError("shared parent must be probed once")
            return {
                "data": {
                    "list": [
                        {"advertiser_id": "101", "project_id": "202"}
                    ]
                }
            }

    client = ParentClient()
    resolved = resolve_probe_inputs(
        client,
        {
            "advertiser_id": "$parent:advertiser_id",
            "project_id": "$parent:project_id",
        },
        operation_id="material.bytedance.project_material.list",
    )

    assert resolved == {"advertiser_id": 101, "project_id": 202}
    assert client.calls == 1


def _surface_client() -> tuple[
    GravityInsightClient, dict[str, object], dict[str, int]
]:
    root = Path(__file__).resolve().parents[1]
    source = json.loads(
        (
            root
            / "src"
            / "gravity_sdk"
            / "contracts"
            # gi-final-unlock promoted this source after live pagination proof.
            / "operations"
            / "report.company_amount.query.json"
        ).read_text(encoding="utf-8")
    )
    operation = source["operation"]
    operation["stability"] = "stable"
    operation["executable"] = True
    operation.pop("block_reason", None)
    operation["live_probe"]["enabled"] = True
    operation["semantic_error_rules"] = ["code", "extra.error"]
    operation["pagination"] = {
        "kind": "none",
        "page_field": "",
        "page_size_field": "",
        "list_path": "",
        "page_info_path": "",
        "total_page_field": "",
    }
    safe_total = {
        "ad_count": 3,
        "ad_create_amount_usage": 4,
        "adclick_count": 5,
        "cost_count": 6,
        "event_count": 7,
        "material_transmit_g_usage": 8,
        "profile_count": 9,
        "storage_count": 10,
        "tracking_count": 11,
    }
    payload = {
        "code": 0,
        "data": {
            "list": [
                {
                    "ad_count": 3,
                    "date": "2026-08-08",
                    SENSITIVE_KEY: SENSITIVE_VALUE,
                }
            ],
            "page_info": {
                "page": 1,
                "page_size": 20,
                "total_number": 1,
                "total_page": 1,
            },
            "total": [
                {
                    **safe_total,
                    SENSITIVE_KEY: SENSITIVE_VALUE,
                    "future_private_total": "must stay hidden",
                }
            ],
        },
    }
    projection = operation["response_projection"]
    manifest = {"manifest_version": 1, "operations": [operation]}
    client = GravityInsightClient._from_manifest_for_tests(
        manifest, transport=_StaticTransport(payload)
    )
    return client, projection, safe_total


def test_sensitive_field_is_hidden_from_projection_read_describe_and_cli() -> None:
    client, projection, safe_total = _surface_client()
    assert SENSITIVE_KEY not in _exposed_response_fields(projection)
    assert SENSITIVE_VALUE not in json.dumps(projection, sort_keys=True)

    read_result = client.read("report.company_amount.query", {})
    rendered_read = json.dumps(read_result, sort_keys=True)
    assert SENSITIVE_KEY not in rendered_read
    assert SENSITIVE_VALUE not in rendered_read
    assert read_result["data"] == {
        "list": [{"ad_count": 3, "date": "2026-08-08"}],
        "total": [safe_total],
    }

    described = client.describe("report.company_amount.query")
    assert SENSITIVE_KEY not in _exposed_response_fields(
        described["response_projection"]
    )
    assert SENSITIVE_VALUE not in json.dumps(described, sort_keys=True)

    stdout = io.StringIO()
    with (
        patch("gravity_sdk.cli._client", return_value=client),
        contextlib.redirect_stdout(stdout),
    ):
        assert cli.main(["read", "report.company_amount.query"]) == 0
    rendered_cli = stdout.getvalue()
    assert SENSITIVE_KEY not in rendered_cli
    assert SENSITIVE_VALUE not in rendered_cli


def _legacy_evidence(source: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
    sketch = response_schema_sketch(payload)
    return {
        "schema_version": "gravity-insight.probe-evidence.v1",
        "operation_id": source["operation"]["operation_id"],
        "route": {
            "method": source["operation"]["upstream_method"],
            "path": source["operation"]["path_template"],
            "family": source["operation"]["operation_id"],
        },
        "probed_at": "2026-08-08T20:55:13Z",
        "conclusion": "privacy_review_required",
        "successful": False,
        "http": [
            {
                "operation_id": source["operation"]["operation_id"],
                "purpose": "discovery",
                "http_status": 200,
                "response_schema_sketch": sketch,
            }
        ],
        "raw_schema_fingerprint": canonical_fingerprint(sketch),
        "projected_schema_fingerprint": None,
        "pagination": {"kind": "none", "verified": False},
        "semantic_errors": {},
        "required_parent": None,
        "privacy": {"values_persisted": False},
        "request_stats": {"total": 1, "failed": 0, "backoff_terminations": 0},
    }


def test_offline_reevaluation_keeps_unverified_pagination_out_of_stable(
    tmp_path: Path,
) -> None:
    draft_root = tmp_path / "drafts"
    operation_root = tmp_path / "operations"
    evidence_root = tmp_path / "evidence"
    source = build_draft(_route(), set())
    payload = {
        "code": 0,
        "data": {
            "list": [{"campaign_id": "campaign-1", SENSITIVE_KEY: SENSITIVE_VALUE}],
            "page_info": {"page": 1, "page_size": 20, "total_page": 1},
        },
    }
    fields = candidate_fields(response_schema_sketch(payload))
    source["operation"]["response_projection"] = build_projection(payload, fields)
    source["operation"]["privacy_policy"]["classification"] = "user_level"
    source["draft"]["candidate_fields"] = fields
    evidence = _legacy_evidence(source, payload)
    evidence_file = evidence_root / "legacy_paginated.yaml"
    _write_json(evidence_file, evidence)
    source["draft"]["probe_evidence"] = [
        {
            "path": evidence_file.name,
            "probed_at": evidence["probed_at"],
            "conclusion": "privacy_review_required",
            "successful": False,
            "pagination_verified": False,
            "raw_schema_fingerprint": evidence["raw_schema_fingerprint"],
            "projected_schema_fingerprint": None,
        }
    ]
    operation_id = source["operation"]["operation_id"]
    _write_json(draft_root / f"{operation_id}.json", source)

    result = reevaluate_drafts(
        draft_root=draft_root,
        operation_root=operation_root,
        evidence_root=evidence_root,
        promote=False,
        compile_products=False,
    )

    assert result["rejected"] == []
    assert result["reevaluated"][0]["eligible"] is False
    assert "pagination_unverified" in result["reevaluated"][0]["missing"]
    updated = json.loads(
        (draft_root / f"{operation_id}.json").read_text(encoding="utf-8")
    )
    assert updated["draft"]["probe_evidence"][-1]["successful"] is True
    assert updated["draft"]["probe_evidence"][-1]["pagination_verified"] is False


def _legacy_draft(
    draft_root: Path, evidence_root: Path, *, platform: str, manual: bool
) -> str:
    source = build_draft(_route(platform), set())
    payload = _payload(manual=manual)
    fields = candidate_fields(
        response_schema_sketch(payload),
        operation_id=source["operation"]["operation_id"],
    )
    source["operation"]["response_projection"] = build_projection(payload, fields)
    source["operation"]["privacy_policy"]["classification"] = "user_level"
    source["draft"]["candidate_fields"] = fields
    source["draft"]["manual_review_fields"] = sorted(
        item["path"]
        for item in fields
        if item["privacy_classification"] == "manual_review"
    )
    operation_id = source["operation"]["operation_id"]
    evidence_file = evidence_root / f"legacy_{operation_id}.yaml"
    evidence = _legacy_evidence(source, payload)
    _write_json(evidence_file, evidence)
    source["draft"]["probe_evidence"] = [
        {
            "path": evidence_file.name,
            "probed_at": evidence["probed_at"],
            "conclusion": "privacy_review_required",
            "successful": False,
            "pagination_verified": False,
            "parent_resolved": False,
            "method_verified": False,
            "raw_schema_fingerprint": evidence["raw_schema_fingerprint"],
            "projected_schema_fingerprint": None,
        }
    ]
    _write_json(draft_root / f"{operation_id}.json", source)
    return operation_id


def test_offline_reevaluation_only_unlocks_classified_and_hidden_case(
    tmp_path: Path,
) -> None:
    draft_root = tmp_path / "drafts"
    operation_root = tmp_path / "operations"
    evidence_root = tmp_path / "evidence"
    allowed_id = _legacy_draft(
        draft_root, evidence_root, platform="tencent", manual=False
    )
    blocked_id = _legacy_draft(
        draft_root, evidence_root, platform="bytedance", manual=True
    )

    result = reevaluate_drafts(
        draft_root=draft_root,
        operation_root=operation_root,
        evidence_root=evidence_root,
        promote=False,
        compile_products=False,
    )

    assert result["network_called"] is False
    assert result["drafts_examined"] == 2
    assert result["manual_review_blocked"] == 1
    assert (result["stable_before"], result["stable_after"]) == (0, 0)
    assert [item["operation_id"] for item in result["reevaluated"]] == [allowed_id]
    assert result["reevaluated"][0]["eligible"] is True
    rejection = {item["operation_id"]: item["reasons"] for item in result["rejected"]}
    assert "manual_review_required" in rejection[blocked_id]
    allowed = json.loads(
        (draft_root / f"{allowed_id}.json").read_text(encoding="utf-8")
    )
    assert allowed["draft"]["probe_evidence"][-1]["successful"] is True
    derived = Path(result["reevaluated"][0]["derived_evidence"])
    assert derived.suffix == ".yaml"
    assert json.loads(derived.read_text(encoding="utf-8"))["offline_reevaluation"] is True
