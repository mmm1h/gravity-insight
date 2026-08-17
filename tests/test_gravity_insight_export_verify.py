from __future__ import annotations
from pathlib import Path


import unittest
import tempfile

from types import SimpleNamespace


from gravity_sdk.prober.export_verify import (
    ExportVerificationRunner,
    _task_id,
    _replace_nested_string,
    load_catalog,
    validate_plan_item,
    validate_privacy_gate,
)



class GravityInsightExportVerifyTests(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.tmp_path = Path(self._temporary_directory.name)

    def test_export_verification_plan_refuses_never_call_route(self):
        catalog = load_catalog()
        route = catalog["export.subscribe.start"]
        with self.assertRaisesRegex(ValueError, "forbids"):
            validate_plan_item(
                {
                    "operation_id": "export.subscribe.start",
                    "call": True,
                    "effect": route["effect"],
                    "method": route["method"],
                    "path": route["path"],
                    "request": {},
                },
                catalog,
            )


    def test_export_verification_plan_requires_exact_catalog_route(self):
        catalog = load_catalog()
        route = catalog["export.analysis.user_detail.start"]
        with self.assertRaisesRegex(ValueError, "path differs"):
            validate_plan_item(
                {
                    "operation_id": route["operation_id"],
                    "call": True,
                    "effect": route["effect"],
                    "method": route["method"],
                    "path": route["path"] + "extra",
                    "request": {},
                },
                catalog,
            )


    def test_export_verification_budget_cannot_exceed_twelve(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 12"):
            ExportVerificationRunner(
                SimpleNamespace(),
                SimpleNamespace(),
                max_creation_requests=13,
            )


    def test_export_verification_finds_observed_task_id_location(self):
        assert _task_id({"code": 0, "data": {"task_id": 123}}) == (
            123,
            "data.task_id",
        )


    def test_export_verification_privacy_gate_rejects_narrow_allowlist(self):
        assert validate_privacy_gate(("A", "B")) == (True, True)


    def test_export_verification_replaces_private_parent_only_in_memory(self):
        assert _replace_nested_string(
            {"client_id": "$first_segment_client_id", "other": ["fixed"]},
            "$first_segment_client_id",
            "resolved",
        ) == {"client_id": "resolved", "other": ["fixed"]}


    def test_export_verification_failed_terminal_state_is_not_success(self):
        runner = ExportVerificationRunner(
            SimpleNamespace(),
            SimpleNamespace(),
            output_root=self.tmp_path,
            sleeper=lambda _: None,
        )
        runner._call_contract = lambda *args, **kwargs: (  # type: ignore[method-assign]
            None,
            None,
            {
                "semantic_success": True,
                "payload": {"code": 0, "data": {"task_id": "probe-task"}},
                "http_status": 200,
                "semantic_code": 0,
                "response_shape": {},
            },
        )
        runner._poll = lambda *args, **kwargs: {  # type: ignore[method-assign]
            "ready": False,
            "payload": {},
            "authorization": None,
            "policy": None,
            "evidence": {"terminal_state": 3},
        }

        result = runner._run_create(
            {
                "operation_id": "export.material.review.start",
                "method": "POST",
                "request": {"material_ids": [1]},
            },
            {"operation_id": "export.material.review.start"},
        )

        assert result["ok"] is False
        assert result["terminal_state"] == 3


    def test_export_verification_client_id_resolver_uses_default_projection(self):
        calls = []
        client = SimpleNamespace(
            read=lambda operation_id, inputs: (
                calls.append((operation_id, inputs))
                or {"data": {"list": [{"ClientID": "private-parent"}]}}
            )
        )
        runner = ExportVerificationRunner(
            client,
            SimpleNamespace(),
            output_root=self.tmp_path,
        )

        resolved = runner._resolved_request(
            {
                "request": {"client_id": "$first_segment_client_id"},
                "resolve_client_id": {"app_id": "app", "segment_id": "segment"},
            }
        )

        assert calls == [
            (
                "analysis.segment.user_detail.list",
                {"app_id": "app", "segment_id": "segment"},
            )
        ]
        assert resolved == {"client_id": "private-parent"}


    def test_four_export_families_have_independent_complete_file_shapes(self):
        catalog = load_catalog()
        expected = {
            "export.analysis.segment.result.start": ["identifier"],
            "export.analysis.segment_user_detail.start": ["identifier", "datetime"],
            "export.analysis.user_detail.start": ["identifier", "datetime"],
            "export.analysis.pay_event.start": ["identifier", "identifier"],
        }
        for operation_id, logical_types in expected.items():
            with self.subTest(operation_id=operation_id):
                route = catalog[operation_id]
                schema = route["privacy"]["file_schema"]
                assert (route["contract_status"], route["executable"], route["block_reason"]) == ("verified", True, None)
                assert [column["logical_type"] for column in schema["columns"]] == logical_types
                assert schema["empty_file"] == {"row_count": 0, "headers_preserved": True}


    def test_user_event_export_has_complete_observed_file_schema(self):
        route = load_catalog()["export.analysis.user_event.start"]
        schema = route["privacy"]["file_schema"]

        assert route["contract_status"] == "verified"
        assert route["executable"] is True
        assert route["block_reason"] is None
        assert schema["worksheet_count"] == 1
        assert [item["logical_type"] for item in schema["columns"]] == [
            "identifier", "datetime", "datetime", "text", "json_object_or_array"
        ]
        assert all(item["cell_storage_types"] for item in schema["columns"])
        origin = load_catalog()["export.analysis.origin_event.start"]
        assert origin["privacy"]["extension"] == ".csv.gz"
