from __future__ import annotations

from typing import Any

import json
import tempfile
import unittest
from pathlib import Path

from gravity_insight.prober.drafts import build_draft, create_drafts
from gravity_insight.prober.promotion import evaluate_gate
from gravity_insight.prober.transport import (
    RecordingSession,
    RequestDiscipline,
    _OpenApiProbeRuntime,
    _source_to_runtime,
    build_probe_policy,
    sdk_parts,
)


def _open_develop_route() -> dict[str, Any]:
    return {
        "business_module": "其它",
        "callers": ["loadDeveloperApplications"],
        "contract_family": None,
        "estimated_implementation_cost": "低",
        "first_occurrence": {"file": "raw/Develop.js", "offset": 10},
        "manifest_operations": [],
        "method": "POST",
        "method_certainty": "high",
        "method_evidence": ["same_request_options", "live_options_allow"],
        "path": "/openapi/api/v1/open_develop/list/",
        "promotion_platform": None,
        "status": "uncovered_read",
        "ui_texts": ["开发者应用"],
    }








class _Response:
    status_code = 200
    headers = {"Content-Type": "application/json"}

    @staticmethod
    def json() -> dict[str, Any]:
        return {"code": 0, "data": {"list": [], "page_info": {}}, "msg": "ok"}


class _Session:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        self.calls.append((method, url, kwargs))
        return _Response()


class _Credentials:
    @staticmethod
    def authorization_headers() -> dict[str, str]:
        return {"Authorization": "test-only"}


class _BaseRuntime:
    def _request_insight(self, *_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("OpenAPI probe unexpectedly used the stable route profile")




class RepositoryOpenApiContractTests(unittest.TestCase):
    def test_precise_drafts_replace_all_placeholder_candidates(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src" / "gravity_insight" / "contracts"
        expected = {
            "developer.application.list": (
                "/openapi/api/v1/open_develop/list/", "gravity_authorization"
            ),
            "promotion.promoted_object.list": (
                "/openapi/api/v1/user/promoted_object/list/", "gravity_openapi_signature"
            ),
            "report.adreport.query": (
                "/openapi/api/v1/report/adreport/custom_get/", "gravity_openapi_signature"
            ),
            "report.metric.list": (
                "/openapi/api/v1/report/metrics/list/", "gravity_openapi_signature"
            ),
        }
        draft_routes: set[tuple[str, str]] = set()
        for operation_id, (path_template, auth_profile) in expected.items():
            with self.subTest(operation_id=operation_id):
                source = json.loads(
                    (root / "drafts" / f"{operation_id}.json").read_text(encoding="utf-8")
                )
                operation = source["operation"]
                self.assertEqual(operation_id, operation["operation_id"])
                self.assertEqual(path_template, operation["path_template"])
                self.assertEqual(auth_profile, operation["auth_profile"])
                self.assertTrue(source["draft"]["coverage_reference"])
                self.assertTrue(source["draft"]["blockers"])
                draft_routes.add((operation["upstream_method"], path_template))

        superseded = {
            "candidate.open_develop.list": root / "drafts" / "candidate.open_develop.list.json",
            "candidate.openapi.metric.list": root / "operations" / "candidate.openapi.metric.list.json",
            "candidate.openapi.promotion_object.list": (
                root / "operations" / "candidate.openapi.promotion_object.list.json"
            ),
            "candidate.openapi.report.query": root / "operations" / "candidate.openapi.report.query.json",
        }
        for operation_id, source_path in superseded.items():
            with self.subTest(superseded_operation_id=operation_id):
                self.assertFalse(source_path.exists())

        operation_routes = set()
        for source_path in (root / "operations").glob("*.json"):
            operation = json.loads(source_path.read_text(encoding="utf-8"))["operation"]
            operation_routes.add(
                (operation["upstream_method"], operation["path_template"])
            )
        with self.subTest(check="route_uniqueness"):
            self.assertTrue(draft_routes.isdisjoint(operation_routes))


class OpenApiProberTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.tmp_path = Path(self._temporary_directory.name)

    def test_open_develop_draft_has_stable_identity_and_runtime_gate(self) -> None:
        source = build_draft(_open_develop_route(), set())
        operation = source["operation"]

        assert operation["operation_id"] == "developer.application.list"
        assert operation["input_fields"] == {
            "page": {"type": "integer", "default": 1},
            "page_size": {"type": "integer", "default": 20},
            "filters": {"type": "array", "default": []},
        }
        assert operation["request"]["body_fields"] == ["page", "page_size", "filters"]
        assert "stable_runtime_route_unsupported" in evaluate_gate(source)["missing"]

    def test_signed_openapi_report_drafts_capture_documented_business_inputs(self) -> None:
        report_route = _open_develop_route()
        report_route.update(
            {
                "business_module": "报表",
                "path": "/openapi/api/v1/report/adreport/custom_get/",
            }
        )
        report = build_draft(report_route, set())
        operation = report["operation"]

        assert operation["operation_id"] == "report.adreport.query"
        assert operation["auth_profile"] == "gravity_openapi_signature"
        assert operation["request"]["body_fields"] == list(operation["input_fields"])
        assert "sign" not in operation["input_fields"]
        assert operation["input_fields"]["filters"]["required"] is True
        assert "openapi_developer_credentials_unavailable" in evaluate_gate(report)["missing"]

        metric_route = dict(report_route)
        metric_route["path"] = "/openapi/api/v1/report/metrics/list/"
        metric = build_draft(metric_route, set())["operation"]
        assert metric["operation_id"] == "report.metric.list"
        assert metric["input_fields"] == {
            "data_topic": {
                "type": "string", "default": "adreport", "enum": ["adreport"]
            },
            "metric_type": {
                "type": "string", "required": True,
                "enum": ["gravity_preset", "user_custom"],
            },
        }

    def test_live_options_evidence_resolves_unknown_method_for_draft(self) -> None:
        tmp_path = self.tmp_path
        route = _open_develop_route()
        route["method"] = "UNKNOWN"
        route["method_certainty"] = "low"
        coverage_path = tmp_path / "coverage.json"
        evidence_path = tmp_path / "options.json"
        coverage_path.write_text(json.dumps({"routes": [route]}), encoding="utf-8")
        evidence_path.write_text(
            json.dumps(
                {
                    "routes": {
                        "results": [
                            {"path": route["path"], "options": {"allow": ["POST"]}}
                        ]
                    }
                }
            ),
            encoding="utf-8",
        )

        created = create_drafts(
            paths=[route["path"]],
            coverage_path=coverage_path,
            draft_root=tmp_path / "drafts",
            operation_root=tmp_path / "operations",
            method_evidence_path=evidence_path,
        )

        assert created[0]["method"] == "POST"
        source = json.loads(
            (tmp_path / "drafts" / "developer.application.list.json").read_text(encoding="utf-8")
        )
        assert source["draft"]["route_evidence"]["method_evidence"] == [
            "live_options_allow",
            "same_request_options",
        ]

    def test_openapi_probe_runtime_consumes_policy_receipt_and_records_request(self) -> None:
        source = build_draft(_open_develop_route(), set())
        parts = sdk_parts()
        operation = parts["models"].load_operation_manifest(
            {"operations": [_source_to_runtime(source["operation"])]}
        )[0]
        registry = parts["registry"].Registry([operation])
        policy = build_probe_policy(parts, registry, operation.path_template)
        inputs = {"page": 1, "page_size": 2, "filters": []}
        authorization = policy._prepare_request(operation.operation_id, inputs)
        session = _Session()
        recording = RecordingSession(
            session,
            RequestDiscipline(
                interval_seconds=0.3,
                request_limit=2,
                clock=lambda: 0.0,
                sleeper=lambda _delay: None,
            ),
        )
        runtime = _OpenApiProbeRuntime(_BaseRuntime(), recording, _Credentials())

        response = runtime._request_insight(
            "POST",
            operation.path_template,
            policy_authorization=authorization,
            params={},
            json_body=inputs,
            attempts=1,
        )

        assert response.status_code == 200
        assert response.payload["code"] == 0
        assert len(recording.observations) == 1
        assert session.calls[0][0] == "POST"
        assert session.calls[0][1].endswith("/openapi/api/v1/open_develop/list/")
        assert session.calls[0][2]["json"] == inputs
