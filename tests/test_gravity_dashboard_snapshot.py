import json
import unittest

from gravity_sdk.dashboard_snapshot import dashboard_snapshot
from gravity_sdk.errors import (
    ContractChangedError, GravityInsightError, InputValidationError, LocalIOError,
    PaginationError,
)


def _tree(*dashboards):
    return {"ok": True, "status": "success", "data": [{
        "id": 1, "name": "space", "folder_or_dashboard": [{
            "id": 2, "name": "folder", "is_folder": True,
            "dashboards": list(dashboards),
        }],
    }]}


class _Client:
    def __init__(self, tree=None, *, omit=None, fail=None, malformed=None):
        self.tree = tree or _tree({"id": 3, "name": "Overview"})
        self.omit, self.fail, self.malformed, self.batch_calls = omit, fail, malformed, []

    def read(self, operation_id, inputs):
        self.read_call = (operation_id, inputs)
        return self.tree

    def batch(self, requests, *, max_workers, max_pages, max_total_items):
        self.batch_calls.append((requests, max_workers, max_pages, max_total_items))
        results = []
        for request in reversed(requests):
            source = request["request_id"]
            if source == self.omit:
                continue
            failed = source == self.fail
            data = {
                "detail": {"id": 3, "name": "Overview", "space_id": 1,
                           "ui_config": {"token": "secret"},
                           "even_report": [{"config": {"password": "secret"}}],
                           "share_members": [{"uid": "private"}]},
                "members": {"creator": {"uid": "private"},
                            "authUsers": [{"uid": "private", "authority": 2}]},
                "space_members": {"creator": {}, "authUsers": []},
                "favourites": {"list": [{"config": {"secret": "x"}}],
                               "page_info": {"page": 1, "total_page": 1}},
                "default_favourite": {"object": {"config": {"secret": "x"}}},
            }[source]
            result = {
                "operation_id": request["operation_id"], "request_id": source,
                "ok": not failed, "status": "error" if failed else "success",
                "data": None if failed else {"status": "success", "data": data},
                "error": ({"code": "UPSTREAM_UNAVAILABLE", "category": "upstream",
                            "message": "C:/private/raw boom"} if failed else None),
            }
            if source == self.malformed:
                result.update(ok=True, status="contract_changed", data=["opaque-secret-config"])
            results.append(result)
        return results


class DashboardSnapshotTests(unittest.TestCase):
    def test_resolves_exact_dashboard_and_returns_five_safe_ordered_sources(self):
        client = _Client(fail="members")
        result = dashboard_snapshot(client, 17, "Overview", max_workers=4,
                                    max_pages=3, max_items=40)
        requests, workers, pages, items = client.batch_calls[0]
        self.assertEqual((workers, pages, items), (4, 3, 37))
        self.assertEqual(["detail", "members", "space_members", "favourites",
                          "default_favourite"], [row["source"] for row in result["results"]])
        self.assertEqual({"id": "3", "name": "Overview", "space_id": "1"},
                         result["dashboard"])
        self.assertEqual(1, result["results"][2]["data"]["data"]["creator_count"])
        self.assertEqual(["3"], requests[3]["inputs"]["filters"][0]["values"])
        self.assertTrue(requests[3]["read_all"])
        self.assertEqual(("partial", 3), (result["status"], result["exit_code"]))
        encoded = json.dumps(result).casefold()
        for forbidden in ("ui_config", "config", "private", "raw boom", "request_id"):
            self.assertNotIn(forbidden, encoded)
        drift = dashboard_snapshot(_Client(malformed="detail"), 17, "Overview", max_items=40)
        self.assertEqual(("partial", 3), (drift["status"], drift["exit_code"]))
        self.assertNotIn("opaque-secret-config", json.dumps(drift))

    def test_reference_and_budget_fail_closed_without_guessing(self):
        ambiguous = _tree(
            {"id": 3, "name": "Same", "space_id": 1},
            {"id": 4, "name": "Same", "space_id": 1},
        )
        for ref in ("Same", "Missing"):
            client = _Client(ambiguous)
            with self.subTest(ref=ref), self.assertRaises(InputValidationError) as raised:
                dashboard_snapshot(client, 17, ref)
            self.assertEqual("ref", raised.exception.field)
            self.assertEqual([], client.batch_calls)
            self.assertNotIn(ref, str(raised.exception))
        bounded = _Client()
        with self.assertRaises(InputValidationError):
            dashboard_snapshot(bounded, 17, 3, max_items=6)
        self.assertFalse(hasattr(bounded, "read_call"))
        wide = _tree(*(
            [{"id": index + 20, "name": f"folder-{index}", "is_folder": True}
             for index in range(50)] + [{"id": 3, "name": "Overview"}]
        ))
        client = _Client(wide)
        with self.assertRaises(PaginationError):
            dashboard_snapshot(client, 17, 3, max_items=20)
        self.assertEqual([], client.batch_calls)
        with self.assertRaises(ContractChangedError):
            dashboard_snapshot(_Client(_tree({"id": 3, "name": "Overview",
                                              "space_id": []})), 17, 3)
        permission = _Client({"ok": False, "status": "permission_unavailable", "data": [],
                              "error": {"code": "PERMISSION_UNAVAILABLE",
                                        "message": "C:/private/raw"}})
        with self.assertRaises(GravityInsightError) as raised:
            dashboard_snapshot(permission, 17, 3)
        detail = raised.exception.to_error_detail()
        self.assertEqual(("PERMISSION_UNAVAILABLE", "upstream"), (detail.code, detail.category))
        self.assertNotIn("private", str(raised.exception))
        throwing = _Client(); throwing.batch = lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("C:/private/raw boom token=secret"))
        with self.assertRaises(LocalIOError) as raised:
            dashboard_snapshot(throwing, 17, 3)
        self.assertNotIn("private", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
