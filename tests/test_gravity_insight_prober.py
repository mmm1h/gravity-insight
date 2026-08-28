from __future__ import annotations

import unittest
from unittest import mock
import tempfile

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


from gravity_sdk.errors import PolicyViolation, exit_code_for_error
from gravity_sdk.prober import batch as prober_batch
from gravity_sdk.prober import cli as prober_cli
from gravity_sdk.prober import online, probe_support, transport as prober_transport
from gravity_sdk.prober.batch import finalize_batch_report
from gravity_sdk.prober.drafts import _resource_action
from gravity_sdk.prober.model import (
    build_draft,
    build_projection,
    candidate_fields,
    classify_field,
    create_drafts,
    evaluate_gate,
    promote_drafts,
    refresh_structured_blockers,
    response_schema_sketch,
    status_report,
)
from gravity_sdk.prober.online import RecordingSession, RequestDiscipline
from gravity_sdk.prober.probe_support import (
    assert_read_only_source,
    evidence_path,
    relative,
)
from gravity_sdk.prober.read_semantics import (
    PROBE_SEMANTIC_STATUSES,
    assert_probe_read_semantics,
    probe_semantic_status,
)





def _route(
    path: str = "/turbo_engine/api/v1/tencent/manager/account/by_company/",
) -> dict[str, object]:
    return {
        "business_module": "推广平台",
        "callers": ["loadAccounts"],
        "contract_family": {
            "family_id": "promotion.family.001",
            "family_kind": "same_level_cross_platform",
            "member_count": 3,
        },
        "estimated_implementation_cost": "低",
        "first_occurrence": {"file": "raw/example.js", "offset": 10},
        "manifest_operations": [],
        "method": "GET",
        "method_certainty": "high",
        "method_evidence": ["same_request_options"],
        "path": path,
        "promotion_platform": "tencent",
        "status": "uncovered_read",
        "ui_texts": ["账户主体"],
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")




















def _gate_ready_source() -> dict[str, object]:
    source = build_draft(_route(), set())
    source["operation"]["response_projection"] = {
        "data_keys": ["list"],
        "required_data_keys": ["list"],
        "item_keys": ["name"],
        "dynamic_item_fields": [],
    }
    source["draft"]["candidate_fields"] = [
        {
            "path": "data.list[].name",
            "types": ["string"],
            "presence": "observed",
            "privacy_classification": "non_sensitive",
            "classification_reason": "business_metadata_name_pattern",
            "expose": True,
        }
    ]
    source["draft"]["probe_evidence"] = [
        {
            "path": "evidence/probe/example.json",
            "probed_at": "2026-08-09T00:00:00Z",
            "conclusion": "success",
            "successful": True,
            "pagination_verified": True,
            "raw_schema_fingerprint": "a" * 64,
            "projected_schema_fingerprint": "b" * 64,
        }
    ]
    return source


class GravityInsightProberTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.tmp_path = Path(self._temporary_directory.name)

    def setattr(self, target, name, value):
        patcher = mock.patch(target, new=name) if isinstance(target, str) else mock.patch.object(target, name, new=value)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_evidence_display_path_accepts_scoped_root_outside_default(self):
        default_root = self.tmp_path / "default"
        self.setattr(probe_support, "REPO_ROOT", default_root)

        assert relative(default_root / "evidence" / "inside.yaml") == (
            "evidence/inside.yaml"
        )
        outside = self.tmp_path / "repository" / "evidence" / "outside.yaml"
        assert relative(outside) == outside.as_posix()


    def test_probe_runtime_uses_project_credential_path(self):
        calls: dict[str, object] = {}
        credential = object()

        class Provider:
            @classmethod
            def from_env(cls, path: Path, **kwargs: object) -> object:
                calls["provider_path"] = path
                calls["provider_kwargs"] = kwargs
                return credential

        class Runtime:
            def __init__(self, **kwargs: object) -> None:
                calls["runtime_kwargs"] = kwargs

        self.setattr(prober_transport, "PROJECT_ROOT", self.tmp_path)
        self.setattr(
            prober_transport,
            "sdk_parts",
            lambda: {
                "credentials": SimpleNamespace(CredentialProvider=Provider),
                "http_runtime": SimpleNamespace(GravityHttpRuntime=Runtime),
            },
        )
        recording = object()

        prober_transport.build_runtime(recording)

        expected = self.tmp_path / ".env.gravity.local"
        assert calls["provider_path"] == expected
        assert calls["provider_kwargs"] == {"session": recording, "persist": True}
        runtime_kwargs = calls["runtime_kwargs"]
        assert isinstance(runtime_kwargs, dict)
        assert runtime_kwargs["env_path"] == expected
        assert runtime_kwargs["session"] is recording
        assert runtime_kwargs["credentials"] is credential

    def test_draft_generator_uses_census_identity_and_fails_closed(self) -> None:
        tmp_path = self.tmp_path
        coverage = {"routes": [_route()]}
        coverage_path = tmp_path / "coverage.json"
        draft_root = tmp_path / "drafts"
        operation_root = tmp_path / "operations"
        _write_json(coverage_path, coverage)

        created = create_drafts(
            paths=[str(_route()["path"])],
            coverage_path=coverage_path,
            draft_root=draft_root,
            operation_root=operation_root,
        )

        assert created[0]["operation_id"] == "promotion.tencent.account_company.list"
        source = json.loads(
            (draft_root / "promotion.tencent.account_company.list.json").read_text(
                encoding="utf-8"
            )
        )
        assert source["draft"]["status"] == "draft"
        assert source["operation"]["executable"] is False
        assert source["operation"]["response_projection"]["item_keys"] == []
        assert source["draft"]["promotion_gate"]["eligible"] is False

    def test_resource_action_table_preserves_rule_precedence(self) -> None:
        cases = (
            (("manager", "account", "by_company"), "GET", (), ("account_company", "list")),
            (("campaign", "tree"), "GET", (), ("campaign", "tree")),
            (("report", "calc_total"), "GET", (), ("report", "calc_total")),
            (("manager", "campaign", "list"), "GET", (), ("campaign_option", "list")),
            (("account", "public_list"), "GET", (), ("account_public", "list")),
            (("campaigns",), "GET", (), ("campaign", "list")),
            (("campaign", "filters"), "GET", (), ("campaign_filter", "list")),
            (("campaign", "detail"), "GET", (), ("campaign", "detail")),
            (("campaign", "get"), "GET", (), ("campaign", "get")),
            (("fetch_app_info",), "GET", (), ("app_info", "get")),
            (("campaign", "custom_get"), "POST", (), ("campaign", "query")),
            (("query_company_amount",), "POST", (), ("company_amount", "query")),
            (("campaign", "report"), "GET", (), ("campaign", "list")),
            (("report", "campaign"), "POST", (), ("campaign", "list")),
            (("opaque",), "GET", (), ("opaque", "get")),
            (("opaque",), "POST", ("read_action_path_token",), ("opaque", "query")),
            (("set",), "POST", ("read_action_path_token",), ("unknown", "unknown")),
        )
        for segments, method, evidence, expected in cases:
            with self.subTest(segments=segments, method=method):
                route = {"method": method, "semantic_evidence": list(evidence)}
                assert _resource_action(
                    route, segments, domain="promotion"
                ) == expected

    def test_draft_generator_rejects_stable_id_collision(self) -> None:
        tmp_path = self.tmp_path
        coverage_path = tmp_path / "coverage.json"
        draft_root = tmp_path / "drafts"
        operation_root = tmp_path / "operations"
        _write_json(coverage_path, {"routes": [_route()]})
        _write_json(
            operation_root / "existing.json",
            {"operation": {"operation_id": "promotion.tencent.account_company.list"}},
        )

        with pytest.raises(ValueError, match="conflicts with stable"):
            create_drafts(
                paths=[str(_route()["path"])],
                coverage_path=coverage_path,
                draft_root=draft_root,
                operation_root=operation_root,
            )

    def test_privacy_classifier_is_conservative(self) -> None:
        for field, expected in [('data.list[].advertiser_id', 'non_sensitive'), ('data.list[].campaign_name', 'non_sensitive'), ('data.list[].uid', 'non_sensitive'), ('data.list[].device_id', 'non_sensitive'), ('data.list[].phone', 'non_sensitive'), ('data.list[].idfa', 'non_sensitive'), ('data.list[].imei', 'non_sensitive'), ('data.list[].order_id', 'non_sensitive'), ('data.list[].email', 'non_sensitive'), ('data.list[].ip_address', 'non_sensitive'), ('data.list[].operator_id', 'non_sensitive'), ('data.list[].operator_name', 'non_sensitive'), ('data.list[].description', 'manual_review')]:
            with self.subTest(field=field, expected=expected):
                assert classify_field(field)[0] == expected

    def test_schema_sketch_and_projection_never_retain_values(self) -> None:
        payload = {
            "code": 0,
            "data": {
                "list": [
                    {
                        "advertiser_id": "business-123",
                        "name": "Example Account",
                        "uid": "user-456",
                        "description": "free form secret",
                    }
                ],
                "page_info": {
                    "page": 1,
                    "page_size": 10,
                    "total_page": 1,
                    "total_number": 1,
                },
            },
        }

        sketch = response_schema_sketch(payload)
        rendered = json.dumps(sketch)
        assert "business-123" not in rendered
        assert "Example Account" not in rendered
        assert "user-456" not in rendered
        assert "free form secret" not in rendered

        fields = candidate_fields(sketch)
        projection = build_projection(payload, fields)
        assert projection["item_keys"] == ["advertiser_id", "name", "uid"]
        assert projection["known_omitted_item_keys"] == ["description"]
        assert "uid" in projection["item_keys"]
        assert "description" not in projection["item_keys"]

    def test_scalar_business_selector_list_is_typed_value_free_after_review(self) -> None:
        payload = {"data": {"list": ["Private Company A", "Private Company B"]}}
        sketch = response_schema_sketch(payload)

        generic = candidate_fields(sketch)
        reviewed = [
            {
                **generic[0],
                "privacy_classification": "non_sensitive",
                "classification_reason": "business_company_selector_manual_review",
                "expose": True,
            }
        ]
        projection = build_projection(payload, reviewed)

        assert generic[0]["path"] == "data.list[]"
        assert generic[0]["privacy_classification"] == "manual_review"
        assert reviewed[0]["privacy_classification"] == "non_sensitive"
        assert reviewed[0]["classification_reason"] == "business_company_selector_manual_review"
        assert projection == {
            "data_keys": ["list"],
            "required_data_keys": ["list"],
            "item_keys": [],
            "dynamic_item_fields": [],
            "data_scalar_list_types": {"list": "string"},
        }
        rendered = json.dumps(
            {"sketch": sketch, "fields": reviewed, "projection": projection}
        )
        assert "Private Company" not in rendered

    def test_free_text_review_remains_a_contract_question(self) -> None:
        sketch = response_schema_sketch(
            {"data": {"list": [{"remark": "not persisted"}]}}
        )

        generic = candidate_fields(sketch)
        reviewed = candidate_fields(
            sketch, operation_id="metadata.property.list"
        )

        assert generic[0]["privacy_classification"] == "manual_review"
        assert reviewed[0]["privacy_classification"] == "manual_review"
        assert reviewed[0]["classification_reason"] == "free_text_field_review"

    def test_authorized_identifiers_are_exposed_but_credentials_are_not(self) -> None:
        sketch = response_schema_sketch(
            {"data": {"list": [{"user_id": "u-1", "email": "u@example.test", "password": "x"}]}}
        )

        fields = {item["path"].rsplit(".", 1)[-1]: item for item in candidate_fields(sketch)}

        assert fields["user_id"]["privacy_classification"] == "non_sensitive"
        assert fields["user_id"]["expose"] is True
        assert fields["email"]["privacy_classification"] == "non_sensitive"
        assert fields["email"]["expose"] is True
        assert fields["password"]["privacy_classification"] == "sensitive"
        assert fields["password"]["expose"] is False

    def test_route_specific_numeric_business_metric_review_stays_scoped(self) -> None:
        sketch = response_schema_sketch(
            {"data": {"list": [{"total_consume": 1.0}]}}
        )

        generic = candidate_fields(sketch)
        reviewed = candidate_fields(
            sketch, operation_id="promotion.bilibili.account.list"
        )

        assert generic[0]["privacy_classification"] == "manual_review"
        assert reviewed[0]["privacy_classification"] == "non_sensitive"
        assert reviewed[0]["classification_reason"] == "route_specific_field_review"

    def test_bare_order_is_a_reviewed_sort_index_not_an_order_identifier(self) -> None:
        fields = candidate_fields(
            response_schema_sketch({"data": {"list": [{"order": 3}]}})
        )

        assert fields[0]["privacy_classification"] == "non_sensitive"
        assert fields[0]["classification_reason"] == "display_sort_index_review"
        assert fields[0]["expose"] is True

    def test_promotion_gate_requires_classified_exposure(self) -> None:
        source = _gate_ready_source()
        assert evaluate_gate(source) == {"eligible": True, "missing": []}

        source["draft"]["candidate_fields"][0]["privacy_classification"] = "manual_review"
        assert "unclassified_or_sensitive_field_exposed" in evaluate_gate(source)["missing"]

    def test_promotion_gate_accepts_a_reviewed_scalar_list_projection(self) -> None:
        source = _gate_ready_source()
        source["operation"]["response_projection"] = {
            "data_keys": ["list"],
            "required_data_keys": ["list"],
            "item_keys": [],
            "dynamic_item_fields": [],
            "data_scalar_list_types": {"list": "string"},
        }
        source["draft"]["candidate_fields"] = [
            {
                "path": "data.list[]",
                "types": ["string"],
                "presence": "observed",
                "privacy_classification": "non_sensitive",
                "classification_reason": "route_specific_field_review",
                "expose": True,
            }
        ]

        assert evaluate_gate(source) == {"eligible": True, "missing": []}
        refreshed = refresh_structured_blockers(source)
        assert refreshed["draft"]["promotion_gate"] == {
            "eligible": True,
            "missing": [],
        }
        assert [item["code"] for item in refreshed["draft"]["blockers"]] == [
            "promotion_pending"
        ]

    def test_promotion_gate_blocks_unsupported_parent_placeholder(self) -> None:
        route = _route("/turbo_engine/api/v1/honor/manager/campaign/list/")
        route["method"] = "POST"
        route["promotion_platform"] = "honor"
        source = build_draft(route, {"promotion.honor.account.list"})
        source["operation"]["response_projection"]["item_keys"] = ["name"]
        source["draft"]["candidate_fields"] = [
            {
                "path": "data.list[].name",
                "types": ["string"],
                "presence": "observed",
                "privacy_classification": "non_sensitive",
                "classification_reason": "business_metadata_name_pattern",
                "expose": True,
            }
        ]
        source["draft"]["probe_evidence"] = [
            {
                "successful": True,
                "pagination_verified": True,
            }
        ]

        assert "runtime_probe_placeholder_unsupported" in evaluate_gate(source)["missing"]
        assert source["operation"]["required_parent"][0]["selection"] == "caller_select"

    def test_promote_moves_only_gate_passing_draft(self) -> None:
        tmp_path = self.tmp_path
        draft_root = tmp_path / "drafts"
        operation_root = tmp_path / "operations"
        source = _gate_ready_source()
        source["operation"]["privacy_policy"]["redact_fields"] = [
            "authorization",
            "token",
        ]
        operation_id = source["operation"]["operation_id"]
        _write_json(draft_root / f"{operation_id}.json", source)

        result = promote_drafts(
            [operation_id],
            draft_root=draft_root,
            operation_root=operation_root,
            compile_products=False,
        )

        assert result[0]["status"] == "stable"
        stable = json.loads(
            (operation_root / f"{operation_id}.json").read_text(encoding="utf-8")
        )
        assert "draft" not in stable
        assert stable["operation"]["stability"] == "stable"
        assert stable["operation"]["executable"] is True
        assert stable["operation"]["semantic_error_rules"]
        assert {
            "authorization",
            "token",
            "operator",
            "callback_url",
        } <= set(stable["operation"]["privacy_policy"]["redact_fields"])
        assert stable["operation"]["provenance"]["family"] is None
        assert stable["operation"]["provenance"]["applied_overrides"] == []
        assert not (draft_root / f"{operation_id}.json").exists()

    def test_promote_restores_draft_when_compilation_fails(self) -> None:
        tmp_path = self.tmp_path
        monkeypatch = pytest.MonkeyPatch()
        self.addCleanup(monkeypatch.undo)
        draft_root = tmp_path / "drafts"
        operation_root = tmp_path / "operations"
        source = _gate_ready_source()
        operation_id = source["operation"]["operation_id"]
        draft_path = draft_root / f"{operation_id}.json"
        destination = operation_root / f"{operation_id}.json"
        _write_json(draft_path, source)
        original = draft_path.read_bytes()
        compile_calls = 0

        def compile_products() -> None:
            nonlocal compile_calls
            compile_calls += 1
            if compile_calls == 1:
                raise RuntimeError("prospective compilation failed")

        monkeypatch.setattr(
            "gravity_sdk.prober.promotion_transaction.compile_contract_products",
            compile_products,
        )

        with pytest.raises(RuntimeError, match="prospective compilation failed"):
            promote_drafts(
                [operation_id],
                draft_root=draft_root,
                operation_root=operation_root,
                compile_products=True,
            )

        assert compile_calls == 2
        assert draft_path.read_bytes() == original
        assert not destination.exists()

    def test_request_discipline_enforces_spacing_budget_and_family_stop(self) -> None:
        now = [0.0]
        sleeps: list[float] = []

        def clock() -> float:
            return now[0]

        def sleeper(delay: float) -> None:
            sleeps.append(delay)
            now[0] += delay

        discipline = RequestDiscipline(
            interval_seconds=0.3,
            request_limit=4,
            clock=clock,
            sleeper=sleeper,
        )
        discipline.before_request("family-a")
        discipline.after_response("family-a", 200)
        discipline.before_request("family-a")
        discipline.after_response("family-a", 500)
        discipline.before_request("family-a")
        discipline.after_response("family-a", 500)
        discipline.before_request("family-a")
        discipline.after_response("family-a", 500)

        assert sleeps == [0.3, 1.0, 2.0, 4.0]
        assert discipline.total == 4
        assert discipline.failed == 3
        assert discipline.backoff_events == 3
        assert discipline.backoff_terminations == 1
        with pytest.raises(RuntimeError, match="terminated"):
            discipline.before_request("family-a")

    def test_request_discipline_rejects_unsafe_configuration(self) -> None:
        with pytest.raises(ValueError, match="300ms"):
            RequestDiscipline(interval_seconds=0.299)
        with pytest.raises(ValueError, match="between 1 and 200"):
            RequestDiscipline(request_limit=201)

    def test_request_discipline_stops_domain_across_operation_families(self) -> None:
        discipline = RequestDiscipline(
            interval_seconds=0.3,
            request_limit=4,
            clock=lambda: 0.0,
            sleeper=lambda _: None,
        )
        for family in ("family-a", "family-b", "family-c"):
            discipline.before_request(family)
            discipline.after_response(family, 500)

        assert discipline.domain_stopped is True
        assert discipline.backoff_terminations == 1
        with pytest.raises(RuntimeError, match="domain is terminated"):
            discipline.before_request("family-d")

    def test_authentication_refresh_observation_cannot_become_target_primary(self) -> None:
        class Response:
            status_code = 200
            headers: dict[str, str] = {}

            @staticmethod
            def json() -> dict[str, object]:
                return {"data": {"user": {"id": 1}}}

        class Session:
            headers: dict[str, str] = {}

            @staticmethod
            def request(method: str, url: str, **kwargs: object) -> Response:
                return Response()

        recording = RecordingSession(
            Session(), RequestDiscipline(sleeper=lambda _: None)
        )
        with recording.observing("promotion.example.list", "family", "discovery"):
            recording.request(
                "POST", "https://example.test/account_center/api/v1/user_login/v2/"
            )

        assert recording.observations[0].operation_id == "authentication"
        assert recording.observations[0].purpose == "authentication"

    def test_online_probe_rejects_non_read_route_segments(self) -> None:
        for segment in ['create', 'update', 'delete', 'export', 'upload', 'set', 'submit_task']:
            with self.subTest(segment=segment):
                source = build_draft(_route(), set())
                source["operation"]["path_template"] = f"/turbo_engine/api/v1/resource/{segment}/"

                with pytest.raises(ValueError, match="refused"):
                    assert_read_only_source(source)

    def test_online_probe_allows_read_list_under_manage_directory(self) -> None:
        source = build_draft(_route(), set())
        source["operation"]["path_template"] = (
            "/turbo_engine/api/v1/bytedance/manage/account/list/"
        )

        assert_read_only_source(source)

    def test_online_probe_still_rejects_mutation_under_manage_directory(self) -> None:
        source = build_draft(_route(), set())
        source["operation"]["path_template"] = (
            "/turbo_engine/api/v1/bytedance/manage/account/delete/"
        )

        with pytest.raises(ValueError, match="refused"):
            assert_read_only_source(source)

    def test_probe_policy_honors_confirmed_read_with_blocked_path_segment(self) -> None:
        source = json.loads(Path("src/gravity_sdk/contracts/operations/report.subscribe.list.json").read_text(encoding="utf-8"))
        parts = prober_transport.sdk_parts()
        operation = parts["models"].load_operation_manifest({"operations": [prober_transport._source_to_runtime(source["operation"])]})[0]
        registry = parts["registry"].Registry([operation])
        prober_transport.build_probe_policy(parts, registry, operation.path_template, operation.upstream_method).authorize_operation(operation.operation_id)

    def test_online_probe_rejects_non_read_effect(self) -> None:
        source = build_draft(_route(), set())
        source["operation"]["effect"] = "export"

        with pytest.raises(ValueError, match="declared as read"):
            assert_read_only_source(source)

    def test_stable_online_probe_never_dispatches_registered_mutations(self) -> None:
        operation_root = Path("src/gravity_sdk/contracts/operations")
        mutation_ids = sorted(
            source["operation"]["operation_id"]
            for path in operation_root.glob("*.json")
            if (source := json.loads(path.read_text(encoding="utf-8")))[
                "operation"
            ]["effect"]
            == "mutation"
        )
        probe_calls: list[str] = []

        class StableClient:
            def probe(self, operation_id: str) -> None:
                probe_calls.append(operation_id)

        class StableClientFactory:
            @classmethod
            def from_env(cls, **_kwargs: object) -> StableClient:
                return StableClient()

        with mock.patch.object(online, "build_runtime", return_value=object()), mock.patch.object(
            online,
            "sdk_parts",
            return_value={"GravityInsightClient": StableClientFactory},
        ):
            for operation_id in mutation_ids:
                with self.subTest(operation_id=operation_id), self.assertRaisesRegex(
                    ValueError, "only accepts operations declared as read"
                ):
                    online.run_online_probes(
                        [operation_id],
                        stable=True,
                        operation_root=operation_root,
                        evidence_root=self.tmp_path / "evidence",
                        session=object(),
                    )

        self.assertEqual(38, len(mutation_ids))
        self.assertEqual([], probe_calls)

    def test_weak_post_probe_requires_traceable_static_confirmation(self) -> None:
        tmp_path = self.tmp_path
        monkeypatch = pytest.MonkeyPatch()
        self.addCleanup(monkeypatch.undo)
        source = build_draft(_route("/candidate/query/"), set())
        route = source["draft"]["route_evidence"]
        route["semantic_evidence"] = ["read_action_path_token"]
        source["operation"]["upstream_method"] = "POST"
        confirmations = tmp_path / "confirmations.json"
        document = {
            "schema_version": "gravity-insight.probe-read-confirmations.v1",
            "confirmations": [],
        }
        _write_json(confirmations, document)

        with pytest.raises(PolicyViolation, match="have not been verified") as error:
            assert_probe_read_semantics(source, confirmations_path=confirmations)
        detail = error.value.to_error_detail().to_dict()
        assert (detail["code"], detail["category"], detail["field"]) == (
            "PROBE_UNSAFE_UNKNOWN", "local", "operation.route_semantics"
        )
        assert "actual value:" in detail["message"] and detail["next_action"]
        assert exit_code_for_error(error.value) == 4
        _write_json(tmp_path / "candidate.query.json", source)
        touched = []

        def forbidden(name):
            touched.append(name)
            pytest.fail(f"{name} must not be constructed")

        monkeypatch.setattr(online, "_session_or_default", lambda _session: forbidden("session"))
        monkeypatch.setattr(online, "build_runtime", lambda _recording: forbidden("runtime"))
        with pytest.raises(PolicyViolation, match="have not been verified"):
            online.run_online_probes(["candidate.query"], draft_root=tmp_path)
        assert touched == []
        monkeypatch.setattr(prober_batch, "classify_drafts", lambda _root: [{"operation_id": "candidate.query"}])
        monkeypatch.setattr(prober_batch, "build_runtime", lambda _recording: forbidden("batch runtime"))
        with pytest.raises(PolicyViolation, match="have not been verified"):
            prober_batch.run_batch_probes(draft_root=tmp_path, report_root=tmp_path / "batch", session=object())
        assert touched == []
        monkeypatch.setattr(prober_cli.runtime, "credential_status", lambda: forbidden("credentials"))
        with pytest.raises(PolicyViolation, match="Probe blocked"):
            prober_cli._probe_auth(["analysis.setting.query"], False)
        assert touched == []

        confirmed = {
            "method": "POST", "path": "/candidate/query/",
            "decision": "confirmed_read", "reviewer": "maintainer@example.test",
            "reviewed_at": "2026-08-14", "evidence": [{
                "source": "raw/example.js#control-flow",
                "detail": "The call only renders returned rows.",
            }],
        }
        for field, invalid in (("reviewer", ""), ("reviewed_at", "not-a-date"), ("evidence", [])):
            document["confirmations"] = [{**confirmed, field: invalid}]
            _write_json(confirmations, document)
            with pytest.raises(PolicyViolation, match="incomplete record"):
                assert_probe_read_semantics(source, confirmations_path=confirmations)
        document["confirmations"] = [confirmed]
        _write_json(confirmations, document)
        assert_probe_read_semantics(source, confirmations_path=confirmations)

        source["operation"]["upstream_method"] = "GET"
        for evidence in (["read_action_path_token"], ["safe_http_method"]):
            route["semantic_evidence"] = evidence
            assert_probe_read_semantics(
                source, confirmations_path=tmp_path / "intentionally-missing.json"
            )
        source["operation"]["upstream_method"] = "POST"
        source["operation"]["path_template"] = "/candidate/unverified/"
        route["semantic_evidence"] = ["route_registry:read_contract_not_verified"]
        with pytest.raises(PolicyViolation, match="have not been verified"):
            assert_probe_read_semantics(source, confirmations_path=confirmations)

    def test_batch_skip_reasons_keep_their_precedence(self) -> None:
        row = {
            "operation_id": "candidate.query",
            "write_semantics_reason": "write route",
            "privacy_name_risk": "user data",
            "parent_indicated": False,
        }

        write_skip = prober_batch._unattempted_probe_result(
            row, request_budget_exhausted=True, stop_loss=True
        )
        privacy_skip = prober_batch._unattempted_probe_result(
            {**row, "write_semantics_reason": None},
            request_budget_exhausted=True,
            stop_loss=True,
        )
        budget_skip = prober_batch._unattempted_probe_result(
            {**row, "write_semantics_reason": None, "privacy_name_risk": None},
            request_budget_exhausted=True,
            stop_loss=True,
        )
        stop_loss_skip = prober_batch._unattempted_probe_result(
            {**row, "write_semantics_reason": None, "privacy_name_risk": None},
            request_budget_exhausted=False,
            stop_loss=True,
        )
        parent_attempt = prober_batch._unattempted_probe_result(
            {
                **row,
                "write_semantics_reason": None,
                "privacy_name_risk": None,
                "parent_indicated": True,
            },
            request_budget_exhausted=False,
            stop_loss=True,
        )

        assert [
            write_skip["conclusion"],
            privacy_skip["conclusion"],
            budget_skip["conclusion"],
            stop_loss_skip["conclusion"],
            parent_attempt,
        ] == [
            "skipped_write_semantics",
            "skipped_privacy_name_risk",
            "not_attempted_budget",
            "not_attempted_stop_loss",
            None,
        ]

    def test_probe_semantic_status_model_has_no_ambiguous_unknown(self) -> None:
        source = build_draft(_route("/candidate/query/"), set())
        route = source["draft"]["route_evidence"]
        statuses = [probe_semantic_status(source)]
        source["operation"]["upstream_method"] = "UNKNOWN"
        statuses.append(probe_semantic_status(source))
        source["draft"]["probe_evidence"] = [{"conclusion": "blocked_by_data"}]
        statuses.append(probe_semantic_status(source))
        source["draft"]["probe_evidence"] = []
        route.update({"status": "unclassified", "semantic_evidence": ["insufficient_semantic_evidence"]})
        statuses.append(probe_semantic_status(source))
        source["operation"]["effect"] = "export"
        statuses.append(probe_semantic_status(source))
        mutation = json.loads(Path("src/gravity_sdk/contracts/operations/analysis.segment.by.manual.update.json").read_text(encoding="utf-8"))
        statuses.append(probe_semantic_status(mutation))
        assert set(statuses) == set(PROBE_SEMANTIC_STATUSES)

    def test_probe_evidence_uses_privacy_guard_compatible_yaml(self) -> None:
        tmp_path = self.tmp_path
        path = evidence_path("metadata.example.list", tmp_path)

        assert path.suffix == ".yaml"

    def test_status_reports_unparseable_files_without_failing(self) -> None:
        tmp_path = self.tmp_path
        evidence_root = tmp_path / "evidence"
        _write_json(
            evidence_root / "20260809T000000Z_metadata.example.list.yaml",
            {
                "schema_version": "gravity-insight.probe-evidence.v1",
                "request_stats": {
                    "total": 2,
                    "failed": 1,
                    "backoff_terminations": 0,
                },
            },
        )
        (evidence_root / "20260809T000001Z_privacy_audit.yaml").write_text(
            "schema_version: gravity-insight.privacy-audit.v1\n"
            "summary:\n"
            "  reviewed: true\n",
            encoding="utf-8",
        )
        (evidence_root / "20260809T000002Z_broken.yaml").write_text(
            '{"schema_version": "gravity-insight.probe-evidence.v1",',
            encoding="utf-8",
        )

        result = status_report(
            draft_root=tmp_path / "drafts",
            operation_root=tmp_path / "operations",
            evidence_root=evidence_root,
        )

        assert result["ok"] is True
        evidence = result["evidence"]
        assert evidence["files"] == 1
        assert evidence["request_total"] == 2
        assert evidence["failed_total"] == 1
        assert evidence["backoff_terminations"] == 0
        assert evidence["skipped_file_count"] == 2
        assert [item["reason"] for item in evidence["skipped_files"]] == [
            "non_json_yaml",
            "invalid_json",
        ]
        assert [Path(item["path"]).name for item in evidence["skipped_files"]] == [
            "20260809T000001Z_privacy_audit.yaml",
            "20260809T000002Z_broken.yaml",
        ]

    def test_batch_finalizer_reports_true_yaml_without_reading_it(self) -> None:
        tmp_path = self.tmp_path
        report_root = tmp_path / "report"
        evidence_root = tmp_path / "evidence"
        _write_json(
            report_root / "layering.json",
            {
                "drafts": [
                    {"operation_id": f"synthetic.operation.{index}", "tier": 1}
                    for index in range(309)
                ]
            },
        )
        evidence_root.mkdir()
        (evidence_root / "20260809T000001Z_privacy_audit.yaml").write_text(
            "schema_version: gravity-insight.privacy-audit.v1\n",
            encoding="utf-8",
        )

        result = finalize_batch_report(
            task_evidence_floor="20260809T000000Z",
            report_root=report_root,
            draft_root=tmp_path / "drafts",
            operation_root=tmp_path / "operations",
            evidence_root=evidence_root,
        )

        assert result["skipped_evidence_file_count"] == 1
        assert result["skipped_evidence_files"][0]["reason"] == "non_json_yaml"
