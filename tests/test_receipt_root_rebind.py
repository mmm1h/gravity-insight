"""Offline regression for generation-bound runtime receipt and observation state."""

from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest import mock

from gravity_insight import shared_runtime
from gravity_insight.errors import AuthenticationError, CredentialError
from gravity_insight.governor_observation import observation_snapshot
from gravity_insight.http_runtime import SQL_PROFILE
from gravity_insight.receipt_query import list_http_receipts
from gravity_insight.runtime_scope import principal_state_root
from tests.test_evidence_provenance import _scope
from tests.test_gravity_http_runtime import FakeResponse, QueueSession, StaticCredentials


def _sql(runtime):
    return runtime.request(
        SQL_PROFILE, "POST", "/custom_sql/api/sql/execute",
        json_body={"sql": "SELECT 1", "tabId": "1"},
    )


class ReceiptRootRebindTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.first_scope = replace(_scope("before"), workspace_fingerprint=str(self.root))
        self.second_scope = replace(self.first_scope, credential_generation="after")
        self.current_scope = self.first_scope
        self.provider = StaticCredentials()
        self.stack.enter_context(mock.patch.dict(shared_runtime._SHARED_RUNTIMES, {}, clear=True))
        self.resolver = self.stack.enter_context(mock.patch(
            "gravity_insight.shared_runtime.runtime_scope_key",
            side_effect=lambda *a, **k: self.current_scope,
        ))
        self.stack.enter_context(mock.patch(
            "gravity_insight.http_runtime.CredentialProvider.from_env",
            return_value=self.provider,
        ))
        self.stack.enter_context(mock.patch.object(shared_runtime._PROCESS_LIMITER, "acquire", return_value=0.0))
        refresh = self.provider.refresh_if_rejected

        def refreshed(credential):
            result = refresh(credential)
            self.current_scope = self.second_scope
            return result

        self.provider.refresh_if_rejected = refreshed

    def runtime(self, responses):
        self.session = QueueSession(responses)
        self.stack.enter_context(mock.patch("gravity_insight.http_runtime._build_session", return_value=self.session))
        return shared_runtime.get_shared_runtime(
            env_path=self.root / "unused-fixture.env", receipt_root=self.root,
        )

    def test_401_replay_and_later_receipts_leave_old_generation(self):
        runtime = self.runtime([
            FakeResponse({}), FakeResponse({}, 401), FakeResponse({}), FakeResponse({}),
        ])
        first_root = principal_state_root(self.root, self.first_scope)
        second_root = principal_state_root(self.root, self.second_scope)
        _sql(runtime)
        [first] = list_http_receipts(first_root)["items"]
        _sql(runtime)
        _sql(runtime)
        old = list_http_receipts(first_root)["items"]
        new = list_http_receipts(second_root)["items"]
        self.assertEqual(2, len(old), "post-refresh receipts must leave the old generation directory")
        self.assertEqual(2, len(new))
        self.assertEqual({False, True}, {item["retry"] for item in new})
        self.assertNotEqual(first["credential_scope_opaque_id"], new[0]["credential_scope_opaque_id"])
        self.assertEqual(1, self.provider.refreshes)
        self.assertIs(self.session, runtime.__dict__["_GravityHttpRuntime__session"])

    def test_observation_partition_follows_refreshed_generation(self):
        runtime = self.runtime([FakeResponse({}), FakeResponse({}, 401), FakeResponse({})])
        _sql(runtime)
        _sql(runtime)
        old = observation_snapshot(self.first_scope.fingerprint)
        new = observation_snapshot(self.second_scope.fingerprint)
        self.assertEqual(2, len(old["observations"]))
        self.assertEqual(1, len(new["observations"]))
        self.assertEqual(new, runtime.governor_observations())
        governor = runtime.__dict__["_GravityHttpRuntime__governor"]
        with mock.patch.object(governor, "snapshot", return_value={}) as snapshot:
            runtime.adaptive_governor_snapshot()
        snapshot.assert_called_once_with(self.second_scope.fingerprint)

    def test_proactive_get_refresh_rebinds_without_a_401(self):
        runtime = self.runtime([FakeResponse({}), FakeResponse({})])
        _sql(runtime)
        get = self.provider.get

        def refreshed_get():
            self.current_scope = self.second_scope
            return get()

        self.provider.get = refreshed_get
        _sql(runtime)
        new = list_http_receipts(principal_state_root(self.root, self.second_scope))["items"]
        self.assertEqual(1, len(new))
        self.assertFalse(new[0]["retry"])

    def test_old_inflight_response_keeps_its_binding_after_other_request_refreshes(self):
        runtime = self.runtime([FakeResponse({}, 401), FakeResponse({})])
        entered = threading.Event()
        release = threading.Event()
        request = self.session.request

        def delayed(method, url, **kwargs):
            if kwargs["json"]["sql"] == "SELECT 2":
                entered.set()
                if not release.wait(5):
                    raise AssertionError("fixture response was not released")
                return FakeResponse({})
            return request(method, url, **kwargs)

        self.session.request = delayed
        with ThreadPoolExecutor(max_workers=1) as pool:
            old_request = pool.submit(
                runtime.request, SQL_PROFILE, "POST", "/custom_sql/api/sql/execute",
                json_body={"sql": "SELECT 2", "tabId": "1"},
            )
            try:
                self.assertTrue(entered.wait(5))
                _sql(runtime)
            finally:
                release.set()
            old_request.result(timeout=5)
        old = list_http_receipts(principal_state_root(self.root, self.first_scope))["items"]
        self.assertEqual([200, 401], sorted(item["http_status"] for item in old))
        self.assertEqual(1, runtime.governor_observations()["count"])

    def test_transport_retries_reuse_one_scope_resolution(self):
        runtime = self.runtime([FakeResponse({}, 500), FakeResponse({}), FakeResponse({})])
        requester = runtime.__dict__["_GravityHttpRuntime__requester"]
        requester.sleeper = lambda delay: None
        request = self.session.request

        def refreshed_elsewhere(*args, **kwargs):
            response = request(*args, **kwargs)
            self.current_scope = self.second_scope
            return response

        self.session.request = refreshed_elsewhere
        self.resolver.reset_mock()
        _sql(runtime)
        self.assertEqual(1, self.resolver.call_count)
        old = list_http_receipts(principal_state_root(self.root, self.first_scope))["items"]
        self.assertEqual({1, 2}, {item["attempt"] for item in old})
        _sql(runtime)
        self.assertEqual(1, runtime.governor_observations()["count"])

    def test_rejected_replay_still_records_new_generation(self):
        runtime = self.runtime([FakeResponse({}, 401), FakeResponse({}, 401)])
        with self.assertRaises(AuthenticationError):
            _sql(runtime)
        new = list_http_receipts(principal_state_root(self.root, self.second_scope))["items"]
        self.assertEqual([401], [item["http_status"] for item in new])
        self.assertEqual(1, self.provider.refreshes)

    def test_account_change_cannot_relabel_old_runtime_traffic(self):
        runtime = self.runtime([FakeResponse({})])
        _sql(runtime)
        self.current_scope = replace(self.second_scope, account_fingerprint="another-account")
        with self.assertRaises(CredentialError):
            _sql(runtime)
        self.assertEqual(1, len(self.session.calls))


if __name__ == "__main__":
    unittest.main()
