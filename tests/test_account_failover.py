"""Offline authentication failover contracts; no production credential sources."""

from __future__ import annotations

import json
import hashlib
import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from gravity_insight import connect
from gravity_insight.credentials import Credential
from gravity_insight.credential_storage import UPDATED_KEY, session_path
from gravity_insight.errors import AuthenticationError, CredentialError, PolicyViolation, TransportError
from gravity_insight.http_runtime import GravityHttpRuntime, HostRateLimiter
from tests.test_gravity_http_runtime import QueueSession, FakeResponse


class AccountFailoverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.paths = tuple(self.root / f"slot-{slot}.env" for slot in (1, 2))
        for path in self.paths:
            path.touch()
        self.sessions = {}
        self.providers = {}
        self.roots = []
        self.limiter = mock.Mock(spec=HostRateLimiter)
        self.limiter.acquire.return_value = 0.0
        self.addCleanup(mock.patch.stopall)

    def build(self, responses, *, enabled=True, workspace=None):
        from gravity_insight.account_pool import AccountPoolConfig

        owner = self

        class Credentials:
            def __init__(self, path):
                self.path = path
                self.refreshes = 0

            def get(self):
                return Credential("offline-fixture")

            def current_principal_id(self):
                return str(owner.paths.index(self.path) + 1)

            def refresh_if_rejected(self, rejected):
                self.refreshes += 1
                session_path(self.path).write_text(
                    f"{UPDATED_KEY}={self.refreshes}\n", encoding="utf-8"
                )
                return self.get()

        for path, values in zip(self.paths, responses, strict=True):
            self.sessions[path] = QueueSession(values)
            self.providers[path] = Credentials(path)

        def runtime(**options):
            from gravity_insight.runtime_scope import principal_receipt_root

            path = Path(options["env_path"])
            root = principal_receipt_root(options["receipt_root"], path, isolated=True)
            owner.roots.append(root)
            return GravityHttpRuntime(
                env_path=path, session=owner.sessions[path],
                credentials=owner.providers[path], limiter=owner.limiter,
                receipt_root=root, attempts=2, sleeper=lambda delay: None,
            )

        mock.patch("gravity_insight.shared_runtime.get_shared_runtime", side_effect=runtime).start()
        mock.patch("gravity_insight.account_pool._protect_sources").start()
        self.admission_patch = mock.patch("gravity_insight.account_pool._load_admission", side_effect=lambda sdk, path: {
            "principal": str(self.paths.index(path) + 1),
            "permission_scope": "fixture-permission", "data_scope": "fixture-data",
        })
        self.admission_patch.start()
        self.validation_patch = mock.patch("gravity_insight.account_pool._validate_capabilities", side_effect=lambda sdk, admission, lease:
                   setattr(lease, "sql_products", frozenset({"fixture"})))
        self.validation_patch.start()
        self.product_patch = mock.patch("gravity_insight.sql.run_product_queries", side_effect=lambda client, *args, **kwargs: {
            "ok": True, "rows": client.execute_sql("SELECT 1"),
        })
        self.product_patch.start()
        from dataclasses import replace
        from gravity_insight.workspace import load_workspace

        workspace = workspace or replace(load_workspace(), state_root=self.root / "state")
        self.workspace = workspace
        return connect(
            env_path=self.paths[0], workspace=workspace,
            account_pool=AccountPoolConfig(enabled=enabled, env_paths=self.paths),
        )

    @staticmethod
    def success():
        return FakeResponse({"data": [{"value": 1}]})

    def test_01_401_refresh_then_switch_succeeds(self):
        sdk = self.build([[FakeResponse({}, 401), FakeResponse({}, 401)], [self.success()]])
        self.assertEqual([{"value": 1}], sdk.query_sql_products({"product": "fixture"})["rows"])
        self.assertEqual(1, self.providers[self.paths[0]].refreshes)
        self.assertEqual((2, "switched_success", 1), (
            sdk.account_pool_status["active_slot"], sdk.account_pool_status["transition_state"],
            sdk.account_pool_status["switch_count"],
        ))

    def test_02_429_uses_existing_backoff_without_switch(self):
        sdk = self.build([[FakeResponse({}, 429, {"Retry-After": "2"}), self.success()], []])
        self.assertTrue(sdk.query_sql_products({"product": "fixture"})["ok"])
        self.limiter.defer.assert_called_once()
        self.assertGreaterEqual(self.limiter.defer.call_args.args[1], 2)
        self.assertEqual([], self.sessions[self.paths[1]].calls)
        self.assertEqual(0, sdk.account_pool_status["switch_count"])

    def test_03_all_401_fail_closed_with_exhaustion_reason(self):
        sdk = self.build([[FakeResponse({}, 401), FakeResponse({}, 401)]] * 2)
        with self.assertRaises(AuthenticationError) as raised:
            sdk.query_sql_products({"product": "fixture"})
        self.assertEqual("ACCOUNT_POOL_EXHAUSTED", raised.exception.to_error_detail().code)
        self.assertEqual("caller", raised.exception.to_error_detail().category)
        self.assertIn("all configured accounts", str(raised.exception))
        self.assertEqual("exhausted", sdk.account_pool_status["transition_state"])

    def test_04_disabled_never_opens_secondary_source(self):
        from gravity_insight.account_pool import AccountPoolConfig

        self.assertFalse(AccountPoolConfig().enabled)
        original = Path.open
        opened = []

        def guard(path, *args, **kwargs):
            opened.append(path)
            if path == self.paths[1]:
                raise AssertionError("disabled secondary was opened")
            return original(path, *args, **kwargs)

        with mock.patch.object(Path, "open", guard):
            sdk = self.build([[FakeResponse({}, 401), FakeResponse({}, 401)], []], enabled=False)
            with self.assertRaises(AuthenticationError) as raised:
                sdk.query_sql_products({"product": "fixture"})
        self.assertEqual("AUTH_REJECTED", raised.exception.to_error_detail().code)
        self.assertNotIn(self.paths[1], opened)

    def test_05_switched_receipts_use_separate_generation_roots(self):
        sdk = self.build([[FakeResponse({}, 401), FakeResponse({}, 401)], [self.success()]])
        sdk.query_sql_products({"product": "fixture"})
        receipts = list((self.root / "state").rglob("*.json"))
        http = [(path, json.loads(path.read_text(encoding="utf-8"))) for path in receipts
                if "http" in path.parts]
        self.assertGreaterEqual(len(http), 3)
        roots = {path.relative_to(self.root / "state").parts[1] for path, _ in http}
        self.assertGreaterEqual(len(roots), 2)
        self.assertEqual(self.roots[-1], sdk.workspace.state_root)
        self.assertTrue(any(path.parent.name == "account-failover" for path in receipts))
        selected = sdk.list_http_receipts()["items"]
        self.assertEqual([200], [item["http_status"] for item in selected])
        self.assertEqual(selected, sdk.get_http_receipt(selected[0]["receipt_id"])["items"])
        exported = self.root / "receipt-export.json"
        sdk.export_http_receipts(exported)
        self.assertEqual(selected, json.loads(exported.read_text(encoding="utf-8"))["items"])

    def test_429_auth_body_does_not_refresh_or_switch(self):
        sdk = self.build([[FakeResponse({"code": 2001}, 429)] * 2, []])
        with self.assertRaises(TransportError):
            sdk.query_sql_products({"product": "fixture"})
        self.assertEqual(0, self.providers[self.paths[0]].refreshes)
        self.assertEqual([], self.sessions[self.paths[1]].calls)

    def test_5xx_auth_body_does_not_switch(self):
        sdk = self.build([[FakeResponse({"code": 2001}, 503)] * 2, []])
        with self.assertRaises(TransportError):
            sdk.query_sql_products({"product": "fixture"})
        self.assertEqual(0, sdk.account_pool_status["switch_count"])

    def test_403_never_switches(self):
        sdk = self.build([[FakeResponse({}, 403)], []])
        from gravity_insight.errors import PermissionUnavailableError
        with self.assertRaises(PermissionUnavailableError):
            sdk.query_sql_products({"product": "fixture"})
        self.assertEqual(0, self.providers[self.paths[0]].refreshes)
        self.assertEqual([], self.sessions[self.paths[1]].calls)

    def test_401_without_refresh_credentials_can_switch(self):
        sdk = self.build([[FakeResponse({}, 401)], [self.success()]])
        self.providers[self.paths[0]].refresh_if_rejected = mock.Mock(side_effect=CredentialError("fixture unavailable"))
        self.assertTrue(sdk.query_sql_products({"product": "fixture"})["ok"])
        self.assertEqual(1, sdk.account_pool_status["switch_count"])

    def test_successful_same_account_refresh_restarts_without_switch(self):
        sdk = self.build([[FakeResponse({}, 401), self.success()], []])
        self.assertTrue(sdk.query_sql_products({"product": "fixture"})["ok"])
        self.assertEqual(0, sdk.account_pool_status["switch_count"])
        self.assertNotEqual(self.roots[0], self.roots[-1])

    def test_configured_unavailable_is_not_unconfigured(self):
        sdk = self.build([[self.success()], []])
        with mock.patch("gravity_insight.account_pool._protect_sources", side_effect=[None, OSError()]):
            sdk.query_sql_products({"product": "fixture"})
        self.assertEqual("configured_unavailable", sdk.account_pool_status["secondary_state"])
        self.assertEqual("ACCOUNT_ADMISSION_UNAVAILABLE", sdk.account_pool_status["slots"][1]["reason_code"])

    def test_unconfigured_secondary_has_distinct_state(self):
        from gravity_insight.account_pool import AccountPoolConfig
        sdk = connect(account_pool=AccountPoolConfig(enabled=True, env_paths=(self.paths[0],)))
        self.assertEqual("not_configured", sdk.account_pool_status["secondary_state"])

    def test_scope_mismatch_rejects_before_any_read(self):
        sdk = self.build([[], []])
        with mock.patch("gravity_insight.account_pool._load_admission", side_effect=[
            {"principal": "1", "permission_scope": "scope-a", "data_scope": "scope"},
            {"principal": "2", "permission_scope": "scope-b", "data_scope": "scope"},
        ]), self.assertRaises(PolicyViolation) as raised:
            sdk.query_sql_products({"product": "fixture"})
        self.assertEqual("ACCOUNT_SCOPE_MISMATCH", raised.exception.code)
        self.assertEqual("configured_unavailable", sdk.account_pool_status["secondary_state"])
        self.assertEqual("ACCOUNT_SCOPE_MISMATCH", sdk.account_pool_status["reason_code"])
        self.assertTrue(all(not session.calls for session in self.sessions.values()))

    def test_duplicate_principal_rejects_before_any_read(self):
        sdk = self.build([[], []])
        with mock.patch("gravity_insight.account_pool._load_admission", return_value={
            "principal": "same", "permission_scope": "scope", "data_scope": "scope",
        }), self.assertRaises(PolicyViolation) as raised:
            sdk.query_sql_products({"product": "fixture"})
        self.assertEqual("ACCOUNT_DUPLICATE_PRINCIPAL", raised.exception.code)
        self.assertEqual("configured_unavailable", sdk.account_pool_status["secondary_state"])
        self.assertEqual("ACCOUNT_DUPLICATE_PRINCIPAL", sdk.account_pool_status["reason_code"])

    def test_exhausted_pool_is_terminal_until_reconnect(self):
        sdk = self.build([[FakeResponse({}, 401), FakeResponse({}, 401)]] * 2)
        for _ in range(2):
            with self.assertRaises(AuthenticationError):
                sdk.query_sql_products({"product": "fixture"})
        self.assertEqual([2, 2], [len(session.calls) for session in self.sessions.values()])

    def test_audit_is_value_free_and_tracks_switch_reason(self):
        sdk = self.build([[FakeResponse({}, 401), FakeResponse({}, 401)], [self.success()]])
        with self.assertLogs("gravity_insight", "INFO") as captured:
            sdk.query_sql_products({"product": "fixture"})
        events = [record.account_failover for record in captured.records if hasattr(record, "account_failover")]
        rendered = json.dumps(events)
        for forbidden in (str(self.paths[0]), str(self.paths[1]), "offline-fixture", "fixture-permission"):
            self.assertNotIn(forbidden, rendered)
        self.assertIn("AUTH_REJECTED", rendered)
        self.assertEqual((2, 1), (events[-1]["active_slot"], events[-1]["switch_count"]))

    def test_mutation_lease_is_blocked_before_wire(self):
        from gravity_insight.account_pool_lease import AccountReadLease, check_read_lease
        lease = AccountReadLease()
        with self.assertRaises(PolicyViolation) as raised:
            check_read_lease(lease, {"_governor_effect": "mutation"})
        self.assertEqual("ACCOUNT_MUTATION_BLOCKED", raised.exception.code)
        self.assertIs(raised.exception, lease.failure)

    def test_pool_does_not_expose_unleased_specialized_clients(self):
        sdk = self.build([[], []])
        with self.assertRaises(PolicyViolation):
            _ = sdk.insight
        with self.assertRaises(PolicyViolation):
            _ = sdk.sql

    def test_capability_validation_and_admission_real_sql_flow(self):
        self._admitted_sql_setup()
        result = self.sdk.query_sql_products(self.query)
        self.assertTrue(result["ok"], result)
        self.assertEqual(1, self.sdk.account_pool_status["switch_count"])

    def test_real_admission_expiry_is_unavailable_not_healthy(self):
        self._admitted_sql_setup()
        from gravity_insight.account_pool import ADMISSION_PATH
        path = self.admission_roots[0] / ADMISSION_PATH
        value = json.loads(path.read_text(encoding="utf-8"))
        value["expires_at"] = value["validated_at"]
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(PolicyViolation):
            self.sdk.query_sql_products(self.query)
        self.assertEqual([], self.sessions[self.paths[0]].calls)

    def test_real_sql_capability_contract_drift_is_rejected(self):
        self._admitted_sql_setup()
        from gravity_insight.capability_validation import STORE_RELATIVE_PATH
        path = self.admission_roots[0] / STORE_RELATIVE_PATH
        value = json.loads(path.read_text(encoding="utf-8"))
        value["validations"][0]["contract_digest"] = "f" * 64
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(PolicyViolation):
            self.sdk.query_sql_products(self.query)
        self.assertTrue(all(not session.calls for session in self.sessions.values()))

    def test_capability_expiry_is_rechecked_during_logical_read(self):
        self._admitted_sql_setup()
        from gravity_insight.account_pool import _load_admission, _validate_capabilities
        from gravity_insight.account_pool_lease import AccountReadLease
        lease = AccountReadLease()
        single = self.sdk._account_pool._connect(0, lease)
        admission = {**_load_admission(single, self.paths[0]), "_validation_root": single.workspace.state_root}
        _validate_capabilities(single, admission, lease)
        with mock.patch("gravity_insight.account_pool_validation.datetime") as clock:
            clock.now.return_value = datetime.now(timezone.utc) + timedelta(hours=2)
            with self.assertRaises(PolicyViolation) as raised:
                lease.check_capability("sql.query")
        self.assertEqual("ACCOUNT_CAPABILITY_UNAVAILABLE", raised.exception.code)
        self.assertTrue(all(not session.calls for session in self.sessions.values()))

    def test_pagination_discards_prior_account_pages_and_restarts_at_one(self):
        from gravity_insight.client import GravityInsightClient
        from gravity_insight.executor import ReadExecutor
        from gravity_insight.models import load_operation_manifest
        from gravity_insight.registry import PolicyEngine, Registry
        from gravity_insight.transport import Transport
        from tests.test_gravity_insight_pagination import _operation

        def page(number, value):
            return FakeResponse({"code": 0, "data": {"list": [{"id": value}], "page_info": {
                "total_page": 2, "total_number": 2, "page": number, "page_size": 1,
            }}})

        sdk = self.build([
            [page(1, 11111), FakeResponse({}, 401), page(1, 11111), FakeResponse({}, 401)],
            [page(1, 22221), page(2, 22222)],
        ])

        def client(**options):
            registry = Registry(load_operation_manifest({"operations": [_operation()]}))
            policy = PolicyEngine(registry)
            transport = Transport(policy=policy, runtime=options["runtime"])
            return GravityInsightClient(registry, ReadExecutor(registry, policy, transport))

        with mock.patch.object(GravityInsightClient, "from_env", side_effect=client):
            result = sdk.read_all("example.concurrent.list", max_workers=1)
        self.assertEqual([{"id": 22221}, {"id": 22222}], result["data"]["list"])
        self.assertEqual([1, 2, 1, 2], [call[2]["params"]["page"] for call in self.sessions[self.paths[0]].calls])
        self.assertEqual([1, 2], [call[2]["params"]["page"] for call in self.sessions[self.paths[1]].calls])

    def test_dependent_plan_restarts_as_a_unit_after_auth_failure(self):
        self._admitted_sql_setup()
        first = FakeResponse({"data": [{"app_id": 101, "event_count": 11111}]})
        second = FakeResponse({"data": [{"app_id": 101, "event_count": 22222}]})
        self.sessions[self.paths[0]].responses = [first, FakeResponse({}, 401), first, FakeResponse({}, 401)]
        self.sessions[self.paths[1]].responses = [second, second]
        plan = {"schema_version": "gravity.plan.v1", "nodes": [
            {"id": "first", "kind": "sql_product", "request": self.query},
            {"id": "second", "kind": "sql_product", "request": self.query, "depends_on": ["first"]},
        ]}
        result = self.sdk.execute_plan(plan, max_workers=1)
        self.assertTrue(result["ok"], result)
        self.assertNotIn("11111", json.dumps(result))
        self.assertIn("22222", json.dumps(result))
        self.assertEqual([4, 2], [len(session.calls) for session in self.sessions.values()])

    def _admitted_sql_setup(self):
        from dataclasses import replace
        from gravity_insight.account_pool import ADMISSION_PATH, AccountPoolConfig
        from gravity_insight.capability_validation import CapabilityValidationStore
        from gravity_insight.data_quality import data_quality_result
        from gravity_insight.runtime_scope import credential_scope_opaque_id
        from gravity_insight.sql.products import contract_hash
        from gravity_insight.workspace import load_workspace
        from tests.test_workspace import _workspace_text

        workspace_path = self.root / "gravity.toml"
        workspace_path.write_text(_workspace_text(product="fixture"), encoding="utf-8")
        workspace = replace(load_workspace(workspace_path), state_root=self.root / "state")
        self.sdk = self.build([
            [FakeResponse({}, 401), FakeResponse({}, 401)],
            [FakeResponse({"data": [{"app_id": 101, "event_count": 2}]})],
        ], workspace=workspace)
        self.admission_patch.stop()
        self.validation_patch.stop()
        self.product_patch.stop()
        current = datetime.now(timezone.utc)
        stamp = lambda value: value.isoformat(timespec="seconds").replace("+00:00", "Z")
        timestamps = {"validated_at": stamp(current - timedelta(minutes=1)),
                      "expires_at": stamp(current + timedelta(hours=1))}
        self.admission_roots = []
        for index, source in enumerate(self.paths):
            single = connect(env_path=source, workspace=workspace, account_pool=AccountPoolConfig())
            root = single.workspace.state_root
            self.admission_roots.append(root)
            validation = {
                "schema_version": "gravity.capability-validation.v1", "identity_kind": "product",
                "selector": "sql-product:fixture", "contract_version": "1",
                "contract_digest": contract_hash("fixture", workspace),
                "provider_fingerprint": contract_hash("fixture", workspace), **timestamps,
                "trust_status": "stable", "completeness": "complete",
                "data_quality": data_quality_result([{"check_id": "shape", "status": "pass", "scope": "sql-product:fixture"}]),
                "evidence_references": [{"kind": "fixture", "reference": "fixture://account-pool/sql"}],
                "reason_codes": [],
            }
            CapabilityValidationStore(root, scope_bound=True).upsert([validation])
            admission = {
                "schema_version": "gravity.account-admission.v1",
                "generation_ref": credential_scope_opaque_id(root),
                "principal": hashlib.sha256(str(index + 1).encode()).hexdigest(),
                "permission_scope": "a" * 64, "data_scope": "b" * 64,
                **timestamps, "evidence_references": ["fixture://account-pool/scope"],
                "capabilities": [{"identity_kind": "product", "selector": "sql-product:fixture"}],
            }
            (root / ADMISSION_PATH).write_text(json.dumps(admission), encoding="utf-8")
        self.query = {"product": "fixture", "start": "2026-09-01", "end": "2026-09-02"}


class AccountPoolConfigTests(unittest.TestCase):
    def test_repository_scanners_do_not_open_credential_sources_or_templates(self):
        from scripts.audit_agent_module_references import version_controlled_files
        from gravity_insight.governance.vendor_neutrality import scan_vendor_identities
        root = Path(__file__).resolve().parents[1]
        sources = [".env.example", ".env.gravity.local", "slot-b.env", "slot-b.env.gravity.session"]
        with mock.patch("gravity_insight.governance.vendor_neutrality._tracked_paths", return_value=sources), \
                mock.patch.object(Path, "read_bytes", side_effect=AssertionError("source content must stay unread")):
            self.assertEqual((), scan_vendor_identities(root))
        with mock.patch("scripts.audit_agent_module_references._git_lines", return_value=sources), \
                mock.patch.object(Path, "is_file", return_value=True):
            files, excluded = version_controlled_files(root)
        self.assertEqual([], files)
        self.assertEqual(sorted(sources), sorted(excluded))

    def test_disabled_environment_does_not_parse_secondary_settings(self):
        from gravity_insight.account_pool import AccountPoolConfig
        with mock.patch.dict(os.environ, {"GRAVITY_ACCOUNT_FAILOVER": "0", "GRAVITY_ACCOUNT_ENV_FILES": "invalid json"}):
            self.assertEqual((), AccountPoolConfig.from_environment().paths())

    def test_account_bound_is_configurable_beyond_two(self):
        from gravity_insight.account_pool import AccountPoolConfig
        paths = tuple(f"slot-{index}.env" for index in range(11))
        self.assertEqual(11, len(AccountPoolConfig(enabled=True, env_paths=paths, max_accounts=11).paths()))
        with self.assertRaises(ValueError) as raised:
            AccountPoolConfig(enabled=True, env_paths=paths).paths()
        self.assertEqual("caller", raised.exception.to_error_detail().category)

    def test_source_inside_repository_is_rejected_without_open(self):
        from gravity_insight.account_pool import _protect_sources
        from gravity_insight.paths import PROJECT_ROOT
        with mock.patch.object(Path, "open", side_effect=AssertionError("no source read allowed")):
            with self.assertRaises(PolicyViolation) as raised:
                _protect_sources(PROJECT_ROOT / "synthetic.env")
        self.assertEqual("ACCOUNT_SOURCE_IN_REPOSITORY", raised.exception.code)

    def test_windows_reparse_source_is_rejected_without_open(self):
        import stat
        from gravity_insight.account_pool import _protect_sources
        attributes = mock.Mock(st_mode=stat.S_IFREG, st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        with mock.patch.object(Path, "lstat", return_value=attributes), \
                mock.patch.object(Path, "open", side_effect=AssertionError("linked source must stay unread")):
            with self.assertRaises(PolicyViolation) as raised:
                _protect_sources(Path("synthetic-linked.env").absolute())
        self.assertEqual("ACCOUNT_SOURCE_LINK_BLOCKED", raised.exception.code)

    def test_disabled_cli_status_does_not_connect(self):
        from gravity_insight.account_pool_cli import main
        with mock.patch.dict(os.environ, {"GRAVITY_ACCOUNT_FAILOVER": "0"}), \
                mock.patch("gravity_insight.sdk.connect", side_effect=AssertionError("unexpected connect")), \
                redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, main(["status"]))
        self.assertEqual("ACCOUNT_POOL_DISABLED", json.loads(output.getvalue())["reason_code"])
