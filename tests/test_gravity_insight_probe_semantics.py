from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk import cli
from gravity_sdk.prober import draft_probe
from gravity_sdk.prober.model import (
    build_draft,
    build_projection,
    candidate_fields,
    canonical_fingerprint,
    reevaluate_drafts,
    response_schema_sketch,
)

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


class _StaticTransport:
    is_test_transport = True

    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def request(self, *_args: object, **_kwargs: object) -> TransportResponse:
        return TransportResponse(200, self.payload, "2026-08-09T00:00:00Z")


def _surface_client() -> tuple[GravityInsightClient, dict[str, object]]:
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
            "total": [{"ad_count": 3, SENSITIVE_KEY: SENSITIVE_VALUE}],
        },
    }
    projection = operation["response_projection"]
    manifest = {"manifest_version": 1, "operations": [operation]}
    client = GravityInsightClient._from_manifest_for_tests(
        manifest, transport=_StaticTransport(payload)
    )
    return client, projection


def test_sensitive_field_is_hidden_from_projection_read_describe_and_cli() -> None:
    client, projection = _surface_client()
    assert SENSITIVE_KEY not in _exposed_response_fields(projection)
    assert SENSITIVE_VALUE not in json.dumps(projection, sort_keys=True)

    read_result = client.read("report.company_amount.query", {})
    rendered_read = json.dumps(read_result, sort_keys=True)
    assert SENSITIVE_KEY not in rendered_read
    assert SENSITIVE_VALUE not in rendered_read
    assert read_result["data"] == {
        "list": [{"ad_count": 3, "date": "2026-08-08"}],
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
