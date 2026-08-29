from __future__ import annotations

import unittest
import tempfile

import json
from pathlib import Path
from types import SimpleNamespace

from gravity_sdk.prober.model import build_draft
from gravity_sdk.prober.drafts import validate_source
from gravity_sdk.prober.parameters import (
    apply_error_learning,
    apply_stable_request_patterns,
    assemble_source_parameters,
    bind_stable_parent_candidates,
    parameter_hints_from_error,
)
from gravity_sdk.prober.probe_support import resolve_inputs
from gravity_sdk.prober.reprobe import (
    downgrade_auth_contaminated_draft,
    prune_missing_probe_references,
    run_parameter_targets,
    select_parameter_reprobes,
)
from gravity_sdk.prober.transport import RecordingSession, RequestDiscipline


def _route() -> dict[str, object]:
    return {
        "business_module": "其它",
        "callers": ["loadExample"],
        "contract_family": None,
        "estimated_implementation_cost": "低",
        "first_occurrence": {"file": "raw/example.js", "offset": 10},
        "manifest_operations": [],
        "method": "POST",
        "method_certainty": "high",
        "method_evidence": ["same_request_options"],
        "path": "/turbo_engine/api/v1/example/list/",
        "promotion_platform": None,
        "status": "uncovered_read",
        "ui_texts": ["Example"],
    }


def _parameter_contract() -> dict[str, object]:
    return {
        "method": "POST",
        "path": "/turbo_engine/api/v1/example/list/",
        "status": "extracted",
        "contract_confidence": "medium",
        "analysis": {
            "call_sites": [
                {
                    "file": "raw/example.js",
                    "route_offset": 10,
                    "call_offset": 20,
                    "evidence_kind": "load_call",
                }
            ]
        },
        "path_parameters": [],
        "query_parameters": [],
        "body_parameters": [
            {
                "name": "app_id",
                "path": "$.app_id",
                "types": ["unknown"],
                "confidence": "medium",
                "required": "observed_always",
            },
            {
                "name": "page",
                "path": "$.page",
                "types": ["integer"],
                "confidence": "high",
                "required": "observed_always",
                "default": 1,
            },
            {
                "name": "filters",
                "path": "$.filters",
                "types": ["array"],
                "confidence": "medium",
                "required": "observed_conditional",
            },
        ],
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")



class GravityInsightReprobeTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.tmp_path = Path(self._temporary_directory.name)

    def test_parameter_target_runner_stops_before_request_at_budget_floor(self):
        context = SimpleNamespace(
            discipline=SimpleNamespace(
                request_limit=7, total=0, domain_stopped=False
            ),
            stable_client=object(),
            runtime=object(),
            recording=object(),
        )

        results, stopped = run_parameter_targets(
            context,
            ["analysis.example.list"],
            draft_root=self.tmp_path / "drafts",
            evidence_root=self.tmp_path / "evidence",
            results_path=self.tmp_path / "results.json",
        )

        assert results == []
        assert stopped is True
        assert not (self.tmp_path / "results.json").exists()

    def test_parameter_assembly_keeps_frontend_presence_distinct_from_required(self):
        source = build_draft(_route(), set())
        source["operation"]["request"]["query_fields"] = ["app_id"]

        assembled, stats = assemble_source_parameters(source, _parameter_contract())

        operation = assembled["operation"]
        assert {"app_id", "filters", "page"}.issubset(
            operation["request"]["body_fields"]
        )
        assert "app_id" not in operation["request"]["query_fields"]
        assert operation["live_probe"]["inputs"]["app_id"] == 0
        assert operation["live_probe"]["inputs"]["page"] == 1
        assert "filters" not in operation["live_probe"]["inputs"]
        assert "required" not in operation["input_fields"]["app_id"]
        assert "not a server-required declaration" in operation["input_fields"]["app_id"]["description"]
        assert stats["high_confidence"] == 1
        assert stats["medium_confidence"] == 2
        metadata = assembled["draft"]["route_evidence"]["parameter_contract"]
        assert metadata["required_semantics"] == "frontend_observation_only"
        assert metadata["call_sites"][0]["call_offset"] == 20


    def test_parameter_assembly_repairs_ambiguous_pagination_types_and_defaults(self):
        source = build_draft(_route(), set())
        source["operation"]["input_fields"]["page"] = {
            "type": "array",
            "item_type": "string",
            "default": 1,
        }
        contract = _parameter_contract()
        page = contract["body_parameters"][1]
        page["types"] = ["array", "integer"]
        page["items"] = {"types": ["string", "unknown"]}
        contract["body_parameters"].append(
            {
                "name": "page_size",
                "path": "$.page_size",
                "types": ["integer", "number"],
                "confidence": "high",
                "required": "observed_always",
                "default": 5000.0,
            }
        )

        assembled, _ = assemble_source_parameters(source, contract)

        operation = assembled["operation"]
        assert operation["input_fields"]["page"]["type"] == "integer"
        assert "item_type" not in operation["input_fields"]["page"]
        assert operation["input_fields"]["page_size"]["type"] == "integer"
        assert operation["input_fields"]["page_size"]["default"] == 5000
        assert isinstance(operation["input_fields"]["page_size"]["default"], int)
        assert operation["request"]["defaults"]["page_size"] == 5000
        assert operation["live_probe"]["inputs"]["page_size"] == 2


    def test_parameter_assembly_prefers_an_observed_default_type_over_array_noise(self):
        source = build_draft(_route(), set())
        contract = _parameter_contract()
        contract["body_parameters"] = [
            {
                "name": "album_id",
                "path": "$.album_id",
                "types": ["array", "string"],
                "confidence": "medium",
                "required": "observed_always",
                "default": "",
            }
        ]

        assembled, _ = assemble_source_parameters(source, contract)

        field = assembled["operation"]["input_fields"]["album_id"]
        assert field["type"] == "string"
        assert field["default"] == ""


    def test_parameter_reassembly_preserves_parent_binding_and_later_enrichment(self):
        source = build_draft(_route(), set())
        contract = _parameter_contract()
        contract["body_parameters"] = [
            {
                "name": "album_id",
                "path": "$.album_id",
                "types": ["array", "string"],
                "confidence": "medium",
                "required": "observed_always",
                "default": "",
            }
        ]
        source, _ = assemble_source_parameters(source, contract)
        source["operation"]["live_probe"]["inputs"]["album_id"] = "$parent:album_id"
        metadata = source["draft"]["route_evidence"]["parameter_contract"]
        metadata["stable_parent_candidates"] = [
            {
                "operation_id": "material.album.tree",
                "input_field": "album_id",
                "output_path": "data.tree..id",
                "selection": "all",
            }
        ]
        metadata["stable_pattern_adjustments"] = [
            {"field": "date_list", "candidate_shape": "array<string>"}
        ]

        reassembled, _ = assemble_source_parameters(source, contract)

        self_contract = reassembled["draft"]["route_evidence"]["parameter_contract"]
        assert reassembled["operation"]["live_probe"]["inputs"]["album_id"] == (
            "$parent:album_id"
        )
        assert self_contract["stable_parent_candidates"] == metadata[
            "stable_parent_candidates"
        ]
        assert self_contract["stable_pattern_adjustments"] == metadata[
            "stable_pattern_adjustments"
        ]


    def test_draft_validation_rejects_literal_type_conflicts_before_network(self):
        source = build_draft(_route(), set())
        source["operation"]["input_fields"]["page"] = {"type": "array"}
        source["operation"]["request"]["defaults"]["page"] = 1

        try:
            validate_source(source)
        except ValueError as exc:
            assert "request.defaults.page" in str(exc)
        else:  # pragma: no cover - regression guard
            raise AssertionError("literal type conflict was accepted")

        source["operation"]["request"]["defaults"].pop("page")
        source["operation"]["live_probe"]["inputs"]["page"] = "$parent:page"
        validate_source(source)


    def test_code_1004_learning_records_only_parameter_shape(self):
        source, _ = assemble_source_parameters(
            build_draft(_route(), set()), _parameter_contract()
        )
        payload = {
            "code": 1004,
            "extra": {"app_id": ["private error text must not persist"]},
        }

        hints = parameter_hints_from_error(payload, known_parameters=("app_id", "page"))
        learned, adjustment = apply_error_learning(source, payload, retry_index=1)

        assert hints == [{"field": "app_id", "basis": "semantic_error_extra_key"}]
        assert adjustment is not None
        assert adjustment["field"] == "app_id"
        assert adjustment["response_values_persisted"] is False
        assert "private error text" not in json.dumps(adjustment)
        assert learned["operation"]["live_probe"]["inputs"]["app_id"] == 1


    def test_code_1003_learning_applies_all_extra_parameter_keys_together(self):
        source, _ = assemble_source_parameters(
            build_draft(_route(), set()), _parameter_contract()
        )
        payload = {
            "code": 1003,
            "extra": {"app_id": ["hidden"], "filters": ["hidden"]},
        }

        learned, adjustment = apply_error_learning(source, payload, retry_index=1)

        assert adjustment is not None
        assert adjustment["fields"] == ["app_id", "filters"]
        assert learned["operation"]["live_probe"]["inputs"]["app_id"] == 1
        assert learned["operation"]["live_probe"]["inputs"]["filters"] == [{}]
        assert "hidden" not in json.dumps(adjustment)


    def test_error_learning_initializes_missing_parameter_contract(self):
        source = build_draft(_route(), set())
        source["draft"]["route_evidence"].pop("parameter_contract", None)

        learned, adjustment = apply_error_learning(
            source,
            {"code": 1004, "extra": {"parent_id": ["hidden"]}},
            retry_index=1,
        )

        assert adjustment is not None
        contract = learned["draft"]["route_evidence"]["parameter_contract"]
        assert contract["source"] == "live_semantic_error"
        assert contract["learned_parameters"] == ["parent_id"]
        assert "hidden" not in json.dumps(contract)


    def test_non_1004_semantic_error_does_not_trigger_parameter_learning(self):
        assert parameter_hints_from_error(
            {"code": 1005, "extra": {"app_id": "not retained"}},
            known_parameters=("app_id",),
        ) == []


    def test_parameter_reprobe_selection_keeps_write_semantics_skipped(self):
        source, _ = assemble_source_parameters(
            build_draft(_route(), set()), _parameter_contract()
        )
        source["draft"]["blockers"] = [
            {
                "code": "request_parameters_required",
                "status": "open",
                "detail": "semantic error",
            }
        ]
        _write_json(self.tmp_path / "metadata.example.list.json", source)

        selected, skipped = select_parameter_reprobes(self.tmp_path)

        assert selected == [source["operation"]["operation_id"]]
        assert skipped == []

        source["operation"]["path_template"] = "/turbo_engine/api/v1/example/export/"
        _write_json(self.tmp_path / "metadata.example.list.json", source)
        selected, skipped = select_parameter_reprobes(self.tmp_path)
        assert selected == []
        assert skipped[0]["write_semantics_reason"] == "forbidden_path_segment:export"


    def test_missing_probe_reference_is_removed_and_gate_is_downgraded(self):
        source = build_draft(_route(), set())
        source["operation"]["operation_id"] = "developer.application.list"
        source["draft"]["probe_evidence"] = [
            {
                "path": "tmp/codex/missing-probe-evidence.yaml",
                "probed_at": "2026-08-08T00:00:00Z",
                "conclusion": "success",
                "successful": True,
                "pagination_verified": True,
                "raw_schema_fingerprint": "a" * 64,
                "projected_schema_fingerprint": "b" * 64,
            }
        ]
        _write_json(self.tmp_path / "developer.application.list.json", source)

        result = prune_missing_probe_references(
            "developer.application.list", draft_root=self.tmp_path
        )

        persisted = json.loads(
            (self.tmp_path / "developer.application.list.json").read_text(encoding="utf-8")
        )
        assert result["removed"] == ["tmp/codex/missing-probe-evidence.yaml"]
        assert persisted["draft"]["probe_evidence"] == []
        assert "successful_probe" in persisted["draft"]["promotion_gate"]["missing"]


    def test_exact_stable_parent_candidate_is_bound_without_a_value(self):
        draft_root = self.tmp_path / "drafts"
        operation_root = self.tmp_path / "operations"
        source, _ = assemble_source_parameters(
            build_draft(_route(), set()), _parameter_contract()
        )
        source["operation"]["input_fields"]["app_id"] = {"type": "integer"}
        _write_json(draft_root / f"{source['operation']['operation_id']}.json", source)
        _write_json(
            operation_root / "app.list.json",
            {"operation": {"operation_id": "app.list", "stability": "stable"}},
        )

        result = bind_stable_parent_candidates(
            draft_root=draft_root,
            operation_root=operation_root,
            operation_ids=[source["operation"]["operation_id"]],
        )

        persisted = json.loads(
            (draft_root / f"{source['operation']['operation_id']}.json").read_text(
                encoding="utf-8"
            )
        )
        assert result["bindings"] == 1
        assert persisted["operation"]["live_probe"]["inputs"]["app_id"] == "$parent:app_id"
        assert persisted["operation"]["required_parent"][0]["output_path"] == "data.list[].id"
        assert persisted["operation"]["required_parent"][0]["selection"] == "caller_select"


    def test_ai_trusteeship_detail_binds_the_stable_rule_list(self):
        draft_root = self.tmp_path / "drafts"
        operation_root = self.tmp_path / "operations"
        source, _ = assemble_source_parameters(
            build_draft(_route(), set()), _parameter_contract()
        )
        source["operation"]["input_fields"] = {"ai_id": {"type": "integer"}}
        source["operation"]["live_probe"]["inputs"] = {"ai_id": 0}
        _write_json(draft_root / f"{source['operation']['operation_id']}.json", source)
        _write_json(
            operation_root / "promotion.ai_trusteeship.list.json",
            {
                "operation": {
                    "operation_id": "promotion.ai_trusteeship.list",
                    "stability": "stable",
                }
            },
        )

        result = bind_stable_parent_candidates(
            draft_root=draft_root,
            operation_root=operation_root,
            operation_ids=[source["operation"]["operation_id"]],
        )

        persisted = json.loads(
            (draft_root / f"{source['operation']['operation_id']}.json").read_text(
                encoding="utf-8"
            )
        )
        assert result["bindings"] == 1
        assert persisted["operation"]["live_probe"]["inputs"]["ai_id"] == "$parent:ai_id"
        assert persisted["operation"]["required_parent"] == [
            {
                "input_field": "ai_id",
                "operation_id": "promotion.ai_trusteeship.list",
                "output_path": "data.list[].id",
                "selection": "caller_select",
            }
        ]


    def test_automatic_parent_rebinding_preserves_manual_parent_and_is_idempotent(self):
        draft_root = self.tmp_path / "drafts"
        operation_root = self.tmp_path / "operations"
        source, _ = assemble_source_parameters(
            build_draft(_route(), set()), _parameter_contract()
        )
        source["operation"]["input_fields"].update(
            {"app_id": {"type": "integer"}, "custom_id": {"type": "string"}}
        )
        source["operation"]["required_parent"] = [
            {
                "operation_id": "custom.parent.list",
                "input_field": "custom_id",
                "output_path": "data.list[].id",
                "selection": "first",
            }
        ]
        source["operation"]["live_probe"]["inputs"]["custom_id"] = "$parent:custom_id"
        draft_path = draft_root / f"{source['operation']['operation_id']}.json"
        _write_json(draft_path, source)
        _write_json(
            operation_root / "app.list.json",
            {"operation": {"operation_id": "app.list", "stability": "stable"}},
        )

        for _ in range(2):
            bind_stable_parent_candidates(
                draft_root=draft_root,
                operation_root=operation_root,
                operation_ids=[source["operation"]["operation_id"]],
            )

        persisted = json.loads(draft_path.read_text(encoding="utf-8"))
        parents = persisted["operation"]["required_parent"]
        assert [item["input_field"] for item in parents] == ["custom_id", "app_id"]
        assert persisted["operation"]["live_probe"]["inputs"]["custom_id"] == "$parent:custom_id"
        assert persisted["operation"]["live_probe"]["inputs"]["app_id"] == "$parent:app_id"
        assert persisted["draft"]["route_evidence"]["parameter_contract"][
            "stable_parent_candidates"
        ] == [parents[1]]


    def test_frontend_verified_parent_wins_over_generic_same_field_candidate(self):
        draft_root = self.tmp_path / "drafts"
        operation_root = self.tmp_path / "operations"
        source = build_draft(_route(), set())
        operation = source["operation"]
        operation["operation_id"] = "promotion.bytedance.standard_project.list"
        operation["platform"] = "bytedance"
        operation["input_fields"] = {
            "advertiser_id": {"type": "integer", "required": True}
        }
        verified_parent = {
            "operation_id": "promotion.bytedance.account.list",
            "input_field": "advertiser_id",
            "output_path": "data.list[].advertiser_id",
            "selection": "caller_select",
        }
        operation["required_parent"] = [verified_parent]
        operation["live_probe"]["inputs"] = {
            "advertiser_id": "$parent:advertiser_id"
        }
        operation["provenance"]["applied_overrides"] = [
            "frontend_verified_parent_binding"
        ]
        source["draft"]["route_evidence"]["parameter_contract"] = {
            "stable_parent_candidates": [verified_parent]
        }
        draft_path = draft_root / f"{operation['operation_id']}.json"
        _write_json(draft_path, source)
        for operation_id in (
            "promotion.bytedance.account.list",
            "promotion.bytedance.project_filter.list",
        ):
            _write_json(
                operation_root / f"{operation_id}.json",
                {
                    "operation": {
                        "operation_id": operation_id,
                        "stability": "stable",
                    }
                },
            )

        result = bind_stable_parent_candidates(
            draft_root=draft_root,
            operation_root=operation_root,
            operation_ids=[operation["operation_id"]],
        )

        persisted = json.loads(draft_path.read_text(encoding="utf-8"))
        assert result["bindings"] == 0
        assert persisted["operation"]["required_parent"] == [verified_parent]
        assert persisted["draft"]["route_evidence"]["parameter_contract"][
            "stable_parent_candidates"
        ] == [verified_parent]


    def test_named_parent_placeholders_resolve_independent_fields(self):
        class StableClient:
            def probe(self, operation_id: str) -> dict[str, object]:
                assert operation_id == "promotion.example.advertiser.list"
                return {
                    "status": "success",
                    "data": {"list": [{"advertiser_id": 7, "campaign_id": 9}]},
                }

        source = build_draft(_route(), set())
        source["operation"]["input_fields"].update(
            {
                "advertiser_id": {"type": "string"},
                "campaign_id": {"type": "integer"},
            }
        )
        source["operation"]["required_parent"] = [
            {
                "operation_id": "promotion.example.advertiser.list",
                "input_field": "advertiser_id",
                "output_path": "data.list[].advertiser_id",
                "selection": "first",
            },
            {
                "operation_id": "promotion.example.advertiser.list",
                "input_field": "campaign_id",
                "output_path": "data.list[].campaign_id",
                "selection": "first",
            },
        ]
        recording = RecordingSession(
            object(), RequestDiscipline(sleeper=lambda _: None)
        )
        parent_cache: dict[str, tuple[object, dict[str, object]]] = {}

        resolved = resolve_inputs(
            {
                "advertiser_id": "$parent:advertiser_id",
                "campaign_id": "$parent:campaign_id",
            },
            source=source,
            stable_client=StableClient(),
            recording=recording,
            parent_cache=parent_cache,
        )

        assert resolved == {"advertiser_id": "7", "campaign_id": 9}
        assert len(parent_cache) == 2


    def test_parent_all_selection_preserves_array_cardinality(self):
        class StableClient:
            def probe(self, operation_id: str) -> dict[str, object]:
                assert operation_id == "promotion.example.advertiser.list"
                return {
                    "status": "success",
                    "data": {
                        "tree": [
                            {
                                "advertiser_id": 7,
                                "children": [{"advertiser_id": 9}],
                            }
                        ]
                    },
                }

        source = build_draft(_route(), set())
        source["operation"]["input_fields"]["advertiser_ids"] = {
            "type": "array",
            "item_type": "string",
        }
        source["operation"]["required_parent"] = [
            {
                "operation_id": "promotion.example.advertiser.list",
                "input_field": "advertiser_ids",
                "output_path": "data.tree..advertiser_id",
                "selection": "all",
            }
        ]
        recording = RecordingSession(
            object(), RequestDiscipline(sleeper=lambda _: None)
        )

        resolved = resolve_inputs(
            {"advertiser_ids": "$parent:advertiser_ids"},
            source=source,
            stable_client=StableClient(),
            recording=recording,
            parent_cache={},
        )

        assert resolved == {"advertiser_ids": ["7", "9"]}


    def test_verified_stable_date_pattern_replaces_invalid_scalar_candidate(self):
        source = build_draft(_route(), set())
        source["operation"]["input_fields"]["date_list"] = {
            "type": "string",
            "default": "",
        }
        source["operation"]["request"]["body_fields"].append("date_list")
        source["operation"]["request"]["defaults"]["date_list"] = ""
        source["operation"]["live_probe"]["inputs"]["date_list"] = ""
        operation_id = source["operation"]["operation_id"]
        _write_json(self.tmp_path / f"{operation_id}.json", source)

        result = apply_stable_request_patterns(
            draft_root=self.tmp_path, operation_ids=[operation_id]
        )

        persisted = json.loads(
            (self.tmp_path / f"{operation_id}.json").read_text(encoding="utf-8")
        )
        assert result["drafts_adjusted"] == 1
        assert persisted["operation"]["live_probe"]["inputs"]["date_list"] == [
            "$today",
            "$today",
        ]
        assert persisted["operation"]["input_fields"]["date_list"]["type"] == "array"
        assert "date_list" not in persisted["operation"]["request"]["defaults"]


    def test_auth_only_probe_reference_is_removed_from_target_contract(self):
        draft_root = self.tmp_path / "drafts"
        source = build_draft(_route(), set())
        operation_id = source["operation"]["operation_id"]
        reference = {
            "path": "evidence/auth-only.yaml",
            "probed_at": "2026-08-09T00:00:00Z",
            "conclusion": "privacy_review_required",
            "successful": False,
            "pagination_verified": False,
            "raw_schema_fingerprint": "a" * 64,
            "projected_schema_fingerprint": None,
        }
        source["draft"]["probe_evidence"] = [reference]
        source["draft"]["candidate_fields"] = [
            {
                "path": "data.user.id",
                "types": ["integer"],
                "presence": "observed",
                "privacy_classification": "non_sensitive",
                "classification_reason": "business_metadata_name_pattern",
                "expose": True,
            }
        ]
        _write_json(draft_root / f"{operation_id}.json", source)
        _write_json(
            self.tmp_path / "evidence" / "auth-only.yaml",
            {"http": [{"path": "/account_center/api/v1/user_login/v2/"}]},
        )

        result = downgrade_auth_contaminated_draft(
            operation_id, draft_root=draft_root, repo_root=self.tmp_path
        )

        persisted = json.loads(
            (draft_root / f"{operation_id}.json").read_text(encoding="utf-8")
        )
        assert result["removed"] == ["evidence/auth-only.yaml"]
        assert persisted["draft"]["probe_evidence"] == []
        assert persisted["operation"]["privacy_policy"]["classification"] == "unverified"
        assert persisted["operation"]["response_projection"]["item_keys"] == []
