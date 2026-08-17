from __future__ import annotations

import contextlib
import io
import json
import unittest
from unittest.mock import patch

from gravity_sdk import GravitySDK
from gravity_sdk.account_permission_profile import (
    PERMISSION_EMPTY_NOTE,
    ROLE_DETAIL_OPERATION_ID,
    SCHEMA_VERSION,
    account_permission_profile,
)
from gravity_sdk.cli import main
from gravity_sdk.errors import InputValidationError


class _Client:
    def __init__(self, principal="91"):
        self._executor = type("_E", (), {
            "_transport": type("_T", (), {"current_principal_id": lambda self: principal})(),
        })()
        self.calls = []

    def batch(self, requests, **_options):
        self.calls.append(list(requests))
        payloads = {
            "permission_menu": {"list": [{"name": "报表", "children": [{"name": "变现报表"}]}]},
            "roles": {"list": [{"id": 7, "name": "运营", "code": "dept_admin"}]},
            "current_user": {"list": [{"id": 91, "user_id": 91, "roles": [{"id": 7, "name": "运营", "code": "dept_admin"}]}]},
            "assigned_role": {"name": "运营", "code": "dept_admin", "data_permission": [{"effect_module": "Report_Report", "child_module": "", "role_effect": 3}]},
        }
        return [{
            "operation_id": item["operation_id"], "request_id": item["request_id"],
            "ok": True, "status": "success",
            "data": {"status": "success", "data": payloads[item["request_id"]]},
        } for item in requests]


class AccountPermissionProfileTests(unittest.TestCase):
    def test_profile_exposes_facts_and_does_not_guess_unmatched_roles(self):
        client = _Client()
        result = account_permission_profile(client, max_items=8)
        self.assertEqual(
            (SCHEMA_VERSION, True, ["运营"], ["报表", "变现报表"]),
            (result["schema_version"], result["principal_matched"],
             result["assigned_role_names"], result["menu_names"]),
        )
        self.assertEqual("Report_Report", result["data_permission_modules"][0]["effect_module"])
        self.assertEqual(PERMISSION_EMPTY_NOTE, result["empty_result_note"])
        self.assertEqual(ROLE_DETAIL_OPERATION_ID, client.calls[1][0]["operation_id"])
        missed = account_permission_profile(_Client("404"), max_items=8)
        self.assertEqual((False, 0, "parent_required"), (
            missed["principal_matched"], missed["assigned_role_count"],
            missed["results"][1]["status"],
        ))

    def test_sdk_cli_and_invalid_bounds_share_the_contract(self):
        self.assertEqual(
            SCHEMA_VERSION,
            GravitySDK(insight=_Client()).account_permission_profile()["schema_version"],
        )
        stdout = io.StringIO()
        with patch("gravity_sdk.capability_cli.runtime.build_client", return_value=_Client()), \
                contextlib.redirect_stdout(stdout):
            self.assertEqual(0, main(["apps", "permission-profile"]))
        self.assertEqual(SCHEMA_VERSION, json.loads(stdout.getvalue())["schema_version"])
        with self.assertRaises(InputValidationError):
            account_permission_profile(_Client(), max_workers=0)
