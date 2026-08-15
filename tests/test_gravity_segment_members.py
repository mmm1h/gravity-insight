import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gravity_sdk import GravitySDK, cli
from gravity_sdk.errors import InputValidationError
from gravity_sdk.plan import AdapterContext
from gravity_sdk import plan_segment_members_adapter as plan_subject
from gravity_sdk.segment_members import (
    ANALYSIS_SEGMENT_USER_DETAIL,
    SCHEMA_VERSION,
    segment_members,
)
from gravity_sdk.segment_spec_cli import run_segment_command
from gravity_sdk.agent_segment_members import segment_members_query
from gravity_sdk.agent_intent_routing import multiple_product_intents


def _member_read(*, truncated=False, status="success"):
    return {
        "ok": True,
        "status": status,
        "data": {
            "list": [
                {"ClientID": "c1", "Name": "n1", "user$level": 8},
                {"ClientID": "c2", "Name": "n2", "user$level": 9},
            ],
            "page_info": {"page": 1, "total_number": 2},
        },
        "truncated": truncated,
        "next_page_input": None,
        "total": {"items": 2, "returned_items": 1 if truncated else 2},
    }


class _Client:
    def __init__(self, member=None):
        self.member = member or _member_read()
        self.calls = []

    def read_limited(self, operation_id, inputs, **options):
        self.calls.append(("limited", operation_id, inputs, options))
        return self.member

    def read_all(self, operation_id, inputs, **options):
        self.calls.append(("all", operation_id, inputs, options))
        return {
            "ok": True, "status": "success", "truncated": False,
            "next_page_input": None,
            "data": {"list": [
                {"segment_id": 8, "segment_name": "Buyers", "app_id": 17}
            ]},
        }


class _Workspace:
    def resolve_app(self, value):
        if value != "main":
            raise KeyError(value)
        return 17


def _context(workspace, *, fields=(), targets=(), items=20):
    return AdapterContext("segment", "segment", "composite", workspace,
                          fields, targets, 5, items)


class SegmentMembersTests(unittest.TestCase):
    def test_natural_language_reachability_and_adjacent_intent_boundary(self):
        self.assertTrue(segment_members_query("这个分群里都有哪些人"))
        self.assertTrue(segment_members_query("list the members of this segment"))
        self.assertEqual(
            {"composite:segment_snapshot", "composite:segment_members"},
            set(multiple_product_intents("list segment members and segment size")),
        )

    def test_core_direct_id_local_fields_and_explicit_partial(self):
        client = _Client()
        result = segment_members(
            client, 17, 8, fields=("ClientID", "Name"), max_items=20
        )
        self.assertEqual((True, "success", 0, 2), (
            result["ok"], result["status"], result["exit_code"], result["returned_items"]
        ))
        self.assertEqual({"ClientID", "Name"}, set(result["data"]["list"][0]))
        self.assertEqual(ANALYSIS_SEGMENT_USER_DETAIL, client.calls[0][1])
        self.assertEqual(["ClientID", "Name"], client.calls[0][2]["fields"])

        partial = segment_members(_Client(_member_read(truncated=True)), 17, 8, max_items=1)
        self.assertEqual((False, "partial", 2, False), (
            partial["ok"], partial["status"], partial["exit_code"], partial["complete"]
        ))
        self.assertEqual(
            ("PAGINATION_LIMIT", "caller", False),
            (
                partial["error"]["code"],
                partial["error"]["category"],
                partial["error"]["retryable"],
            ),
        )
        self.assertEqual(1, partial["returned_items"])

    def test_exact_name_catalog_and_contract_change_fail_closed(self):
        client = _Client()
        result = segment_members(client, 17, "Buyers")
        self.assertEqual(["all", "limited"], [call[0] for call in client.calls])
        self.assertEqual({"id": "8", "name": "Buyers"}, result["segment"])
        changed = segment_members(
            _Client(_member_read(status="contract_changed_additive")), 17, 8
        )
        self.assertEqual((False, "contract_changed", None), (
            changed["ok"], changed["status"], changed["data"]
        ))
        denied_read = _member_read(status="permission_unavailable")
        denied_read.update({
            "ok": False,
            "error": {"code": "PERMISSION_UNAVAILABLE", "category": "upstream"},
        })
        denied = segment_members(_Client(denied_read), 17, 8)
        self.assertEqual(("permission_unavailable", 3), (
            denied["status"], denied["exit_code"]
        ))
        with self.assertRaises(InputValidationError):
            segment_members(_Client(), 17, "missing")

    def test_cli_sdk_and_plan_share_the_product_envelope(self):
        parsed = cli.build_parser().parse_args([
            "analysis", "segment", "members", "--app", "main", "--ref", "8",
            "--fields", "Name,user$level", "--segment-version-id", "3",
            "--max-items", "30",
        ])
        expected = {"schema_version": SCHEMA_VERSION, "ok": True}
        workspace = _Workspace()
        with (
            patch("gravity_sdk.segment_spec_cli.load_workspace", return_value=workspace),
            patch("gravity_sdk.segment_spec_cli.resolve_workspace_app", return_value=17),
            patch("gravity_sdk.segment_spec_cli.segment_members", return_value=expected) as facade,
        ):
            self.assertIs(expected, run_segment_command(
                parsed, lambda: object(), lambda _v: {}, lambda *_a, **_k: {}
            ))
        self.assertEqual((17, "8"), facade.call_args.args[1:])
        self.assertEqual(("Name", "user$level"), facade.call_args.kwargs["fields"])

        sdk = GravitySDK(workspace=workspace, insight_factory=lambda: object())
        with patch("gravity_sdk.segment_members.segment_members", return_value=expected) as core:
            self.assertIs(expected, sdk.segment_members("main", 8, fields=("Name",)))
        self.assertEqual((17, 8), core.call_args.args[1:])

        request = {"name": "segment_members", "app": "main", "ref": 8,
                   "fields": ["Name"]}
        context = _context(workspace, fields=("data",), items=30)
        plan_subject.validate_segment_members_plan(request, context, workspace)
        native = {
            "schema_version": SCHEMA_VERSION, "ok": True, "status": "success",
            "exit_code": 0, "data": {"list": [{"Name": "n"}]}, "error": None,
        }
        calls = []
        plan_sdk = SimpleNamespace(segment_members=lambda *args, **kwargs:
                                   (calls.append((args, kwargs)), native)[1])
        safe = plan_subject.execute_segment_members_plan(plan_sdk, request, context)
        self.assertEqual((SCHEMA_VERSION, 1), (safe["schema_version"], calls[0][1]["max_workers"]))
        self.assertEqual({"data"}, set(plan_subject.project_segment_members_result(
            safe, context.output_fields, context
        )) & plan_subject.SEGMENT_MEMBERS_OUTPUT_FIELDS)


if __name__ == "__main__":
    unittest.main()
