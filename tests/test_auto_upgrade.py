from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Lock
from unittest.mock import Mock, patch

from gravity_sdk import __version__
from gravity_sdk import _auto_upgrade_state as upgrade_state
from gravity_sdk import __main__ as entry
from gravity_sdk import auto_upgrade as upgrade
from gravity_sdk.auto_upgrade import (
    AUTO_UPGRADE_ENV,
    PINNED_VERSION_ENV,
    TARGET_PYTHON_ENV,
    TERMINAL_UPGRADE_STATUSES,
    UPDATE_CHECK_INTERVAL,
    UPDATE_POLICY_EXIT_CODE,
    check_latest_version,
    maybe_auto_upgrade,
    startup_update_enabled,
    update_attempt_state_path,
    update_state_path,
)
from gravity_sdk.receipt import (
    DISTRIBUTION_HTTP_KIND,
    count_http_requests,
)


NOW = datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, status: int, payload: bytes = b"", *, etag: str | None = None):
        self.status_code = status
        self.content = payload
        self.headers = {"ETag": etag} if etag is not None else {}


def pypi(version: str, *, name: str = "gravity-insight") -> bytes:
    return json.dumps({"info": {"name": name, "version": version}}).encode("utf-8")


def timestamp(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def state(
    *,
    successful_checked_at: datetime | None,
    etag: str | None,
    latest_version: str | None,
) -> dict[str, object]:
    return {
        "schema_version": 3,
        "successful_checked_at": (
            timestamp(successful_checked_at)
            if successful_checked_at is not None
            else None
        ),
        "etag": etag,
        "latest_version": latest_version,
    }


def legacy_state(
    *,
    successful_checked_at: datetime | None,
    etag: str | None,
    latest_version: str | None,
    attempted_version: str | None = None,
    attempted_at: datetime | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "successful_checked_at": (
            timestamp(successful_checked_at)
            if successful_checked_at is not None
            else None
        ),
        "etag": etag,
        "latest_version": latest_version,
        "attempted_version": attempted_version,
        "attempted_at": timestamp(attempted_at) if attempted_at is not None else None,
    }


def fake_target_python(root: Path) -> Path:
    target = root / "target-python.exe"
    target.touch()
    return target.resolve()


class UpdateStateTests(unittest.TestCase):
    def test_state_path_uses_the_existing_cross_platform_cache_root_top_level(self) -> None:
        scope = upgrade._runtime_scope_id()
        cases = (
            (
                {"LOCALAPPDATA": "C:/Local", "XDG_CACHE_HOME": "C:/ignored"},
                Path("C:/Local/GravityInsight/update-check.json"),
            ),
            (
                {"XDG_CACHE_HOME": "/var/cache/user"},
                Path("/var/cache/user/GravityInsight/update-check.json"),
            ),
        )
        for environment, expected in cases:
            with self.subTest(environment=environment), patch.dict(
                os.environ, environment, clear=True
            ):
                self.assertEqual(
                    expected.with_name(f"update-check-{scope}.json"),
                    update_state_path(),
                )
        with patch.dict(os.environ, {}, clear=True), patch(
            "gravity_sdk.runtime_scope.Path.home", return_value=Path("/Users/analyst")
        ):
            self.assertEqual(
                Path(
                    f"/Users/analyst/.cache/gravity-insight/update-check-{scope}.json"
                ),
                update_state_path(),
            )

    def test_successful_check_writes_release_facts_and_cached_check_reuses_version(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "update-check.json"
            request = Mock(return_value=FakeResponse(200, pypi(__version__), etag='"release"'))
            first = check_latest_version(state_path=path, now=NOW, request=request)
            second = check_latest_version(
                state_path=path,
                now=NOW + UPDATE_CHECK_INTERVAL - timedelta(seconds=1),
                request=Mock(side_effect=AssertionError("interval must skip HTTP")),
            )
            stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(("checked", "cached"), (first.status, second.status))
        self.assertEqual(__version__, second.latest_version)
        self.assertEqual(
            {
                "schema_version",
                "successful_checked_at",
                "etag",
                "latest_version",
            },
            set(stored),
        )
        self.assertEqual(
            (3, timestamp(NOW), '"release"', __version__),
            (
                stored["schema_version"],
                stored["successful_checked_at"],
                stored["etag"],
                stored["latest_version"],
            ),
        )
        request.assert_called_once()

    def test_failed_check_is_retried_and_never_becomes_cached(self) -> None:
        failed_request = Mock(side_effect=OSError("offline"))
        successful_request = Mock(return_value=FakeResponse(200, pypi(__version__)))
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "update-check.json"
            first = check_latest_version(
                state_path=path, now=NOW, request=failed_request
            )
            state_after_failure = path.exists()
            second = check_latest_version(
                state_path=path,
                now=NOW + timedelta(seconds=1),
                request=successful_request,
            )
        self.assertEqual(("failed", "checked"), (first.status, second.status))
        self.assertFalse(state_after_failure)
        failed_request.assert_called_once()
        successful_request.assert_called_once()

    def test_etag_is_sent_and_live_304_migrates_legacy_release_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "update-check.json"
            path.write_text(
                json.dumps(
                    legacy_state(
                        successful_checked_at=NOW - UPDATE_CHECK_INTERVAL,
                        etag='W/"release-etag"',
                        latest_version="0.3.2",
                        attempted_version="0.3.2",
                        attempted_at=NOW - UPDATE_CHECK_INTERVAL,
                    )
                ),
                encoding="utf-8",
            )
            observed: dict[str, str] = {}

            def request(headers):
                observed.update(headers)
                return FakeResponse(304)

            result = check_latest_version(state_path=path, now=NOW, request=request)
            stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual('W/"release-etag"', observed["If-None-Match"])
        self.assertEqual(("not_modified", "0.3.2"), (result.status, result.latest_version))
        self.assertEqual(
            (3, timestamp(NOW), 'W/"release-etag"', "0.3.2"),
            (
                stored["schema_version"],
                stored["successful_checked_at"],
                stored["etag"],
                stored["latest_version"],
            ),
        )
        self.assertNotIn("attempted_version", stored)

    def test_304_without_sent_validator_or_reusable_version_is_not_cached(self) -> None:
        cases = (
            state(
                successful_checked_at=NOW - UPDATE_CHECK_INTERVAL,
                etag=None,
                latest_version="0.3.2",
            ),
            legacy_state(
                successful_checked_at=NOW - UPDATE_CHECK_INTERVAL,
                etag='"orphaned"',
                latest_version=None,
            ),
        )
        for previous in cases:
            with self.subTest(previous=previous), tempfile.TemporaryDirectory() as raw:
                path = Path(raw) / "update-check.json"
                path.write_text(json.dumps(previous), encoding="utf-8")
                result = check_latest_version(
                    state_path=path,
                    now=NOW,
                    request=lambda _headers: FakeResponse(304),
                )
                stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("failed", result.status)
            self.assertEqual(previous, stored)

    def test_distribution_request_enters_authoritative_boundary_without_production_count(self) -> None:
        response = FakeResponse(200, pypi(__version__))
        with patch("gravity_sdk.auto_upgrade.requests.get", return_value=response) as network:
            with count_http_requests() as counter:
                actual = upgrade._distribution_get({"If-None-Match": '"known"'})
        self.assertIs(response, actual)
        self.assertEqual(0, counter.count)
        self.assertEqual({DISTRIBUTION_HTTP_KIND: 1}, counter.attempts_by_kind)
        network.assert_called_once_with(
            "https://pypi.org/pypi/gravity-insight/json",
            headers={"If-None-Match": '"known"'},
            timeout=(2.0, 4.0),
            allow_redirects=False,
        )

    def test_pypi_identity_and_strict_stable_version_are_both_required(self) -> None:
        cases = (
            (pypi("2.0.0", name="other-project"), "wrong-name"),
            (pypi("2.0.0rc1"), "prerelease"),
            (b"not-json", "malformed"),
        )
        for payload, label in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                result = check_latest_version(
                    state_path=Path(raw) / "update-check.json",
                    now=NOW,
                    request=lambda _headers, body=payload: FakeResponse(200, body),
                )
            self.assertEqual("failed", result.status)

    def test_corrupt_or_unwritable_state_fails_closed_without_http(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            corrupt = root / "corrupt.json"
            corrupt.write_text("{broken", encoding="utf-8")
            request = Mock(side_effect=AssertionError("bad state must skip HTTP"))
            damaged = check_latest_version(state_path=corrupt, now=NOW, request=request)

            parent_file = root / "not-a-directory"
            parent_file.write_text("blocked", encoding="utf-8")
            unwritable = check_latest_version(
                state_path=parent_file / "update-check.json",
                now=NOW,
                request=request,
            )
        self.assertEqual(("failed", "failed"), (damaged.status, unwritable.status))
        request.assert_not_called()

    def test_concurrent_callers_share_one_short_lease_and_one_request(self) -> None:
        calls = 0

        def request(_headers):
            nonlocal calls
            calls += 1
            return FakeResponse(200, pypi(__version__), etag='"shared"')

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "update-check.json"
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(
                        lambda _index: check_latest_version(
                            state_path=path, now=NOW, request=request
                        ),
                        range(2),
                    )
                )
        self.assertEqual(1, calls)
        statuses = [result.status for result in results]
        self.assertEqual(1, statuses.count("checked"))
        self.assertIn(
            next(status for status in statuses if status != "checked"),
            {"busy", "cached"},
        )

    def test_concurrent_stale_lease_takeover_has_one_inspector_and_one_holder(self) -> None:
        first_inspector = Event()
        release_inspector = Event()
        counter_lock = Lock()
        expired_checks = 0
        active_holders = 0
        maximum_holders = 0

        def slow_expiry(_path, _now):
            nonlocal expired_checks
            with counter_lock:
                expired_checks += 1
            first_inspector.set()
            release_inspector.wait(2)
            return True

        def request(_headers):
            nonlocal active_holders, maximum_holders
            with counter_lock:
                active_holders += 1
                maximum_holders = max(maximum_holders, active_holders)
            try:
                return FakeResponse(200, pypi(__version__), etag='"reclaimed"')
            finally:
                with counter_lock:
                    active_holders -= 1

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "update-check.json"
            lease_path = path.with_name(f"{path.name}.lease")
            lease_path.write_text(
                json.dumps(
                    {
                        "schema_version": 3,
                        "lease_id": "stale-owner",
                        "claimed_at": timestamp(NOW - timedelta(minutes=2)),
                    }
                ),
                encoding="utf-8",
            )
            original_expiry = upgrade_state._lease_is_expired
            upgrade_state._lease_is_expired = slow_expiry
            try:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    first = pool.submit(
                        check_latest_version,
                        state_path=path,
                        now=NOW,
                        request=request,
                    )
                    self.assertTrue(first_inspector.wait(1))
                    second = pool.submit(
                        check_latest_version,
                        state_path=path,
                        now=NOW,
                        request=request,
                    )
                    try:
                        second_result = second.result(timeout=1)
                    finally:
                        release_inspector.set()
                    first_result = first.result(timeout=2)
            finally:
                upgrade_state._lease_is_expired = original_expiry
        self.assertEqual(("checked", "busy"), (first_result.status, second_result.status))
        self.assertEqual(1, expired_checks)
        self.assertEqual(1, maximum_holders)

    def test_success_state_is_published_with_atomic_replace(self) -> None:
        with tempfile.TemporaryDirectory() as raw, patch(
            "gravity_sdk._auto_upgrade_state.os.replace", wraps=os.replace
        ) as replace:
            path = Path(raw) / "update-check.json"
            result = check_latest_version(
                state_path=path,
                now=NOW,
                request=lambda _headers: FakeResponse(200, pypi(__version__)),
            )
            leftovers = list(path.parent.glob(f".{path.name}.*.tmp"))
        self.assertEqual("checked", result.status)
        self.assertEqual(1, replace.call_count)
        self.assertEqual(path, replace.call_args.args[1])
        self.assertEqual([], leftovers)


class StartupPlanOnlyTests(unittest.TestCase):
    def test_doctor_pin_and_off_switch_paths_disable_the_check(self) -> None:
        enabled = {AUTO_UPGRADE_ENV: "1"}
        self.assertFalse(startup_update_enabled(["agent"], environ={}))
        self.assertFalse(startup_update_enabled(["doctor"], environ=enabled))
        self.assertFalse(startup_update_enabled(["insight", "doctor"], environ=enabled))
        self.assertFalse(startup_update_enabled(
            ["agent"], environ={**enabled, PINNED_VERSION_ENV: __version__}
        ))
        self.assertFalse(startup_update_enabled(["agent"], environ={AUTO_UPGRADE_ENV: "0"}))
        self.assertTrue(startup_update_enabled(["agent"], environ=enabled))

    def test_invalid_or_mismatched_pin_does_not_disable_the_check(self) -> None:
        for pinned in ("not-a-version", "99.0.0"):
            with self.subTest(pinned=pinned):
                self.assertTrue(startup_update_enabled(
                    ["agent"],
                    environ={AUTO_UPGRADE_ENV: "1", PINNED_VERSION_ENV: pinned},
                ))

    def test_new_version_produces_a_plan_request_without_installer_calls(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            installer = Mock(side_effect=AssertionError("Runtime must not invoke installer"))
            result = maybe_auto_upgrade(
                ["agent-catalog", "categories"],
                environ={AUTO_UPGRADE_ENV: "1"},
                state_path=root / "update-check.json",
                now=NOW,
                request=lambda _headers: FakeResponse(200, pypi("99.0.0")),
                stderr=io.StringIO(),
                target_python=fake_target_python(root),
            )
        self.assertEqual("plan_ready", result.status)
        self.assertIsNotNone(result.plan)
        installer.assert_not_called()

    def test_missing_target_environment_fails_closed_but_reports_version(self) -> None:
        stderr = io.StringIO()
        with tempfile.TemporaryDirectory() as raw:
            result = maybe_auto_upgrade(
                ["agent"],
                environ={AUTO_UPGRADE_ENV: "1"},
                state_path=Path(raw) / "update-check.json",
                now=NOW,
                request=lambda _headers: FakeResponse(200, pypi("99.0.0")),
                stderr=stderr,
            )
        self.assertEqual(("target_unconfigured", "99.0.0"), (
            result.status, result.latest_version
        ))
        self.assertIn("cannot plan update", stderr.getvalue())

    def test_running_environment_cannot_be_named_as_external_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = maybe_auto_upgrade(
                ["agent"],
                environ={AUTO_UPGRADE_ENV: "1"},
                state_path=Path(raw) / "update-check.json",
                now=NOW,
                request=lambda _headers: FakeResponse(200, pypi("99.0.0")),
                stderr=io.StringIO(),
                target_python=sys.executable,
            )
        self.assertEqual("target_rejected", result.status)
        self.assertIn("running environment", result.detail or "")

    def test_plan_request_freezes_external_owner_gates_and_target(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = fake_target_python(root)
            result = maybe_auto_upgrade(
                ["agent"],
                environ={AUTO_UPGRADE_ENV: "1"},
                state_path=root / "update-check.json",
                now=NOW,
                request=lambda _headers: FakeResponse(200, pypi("99.0.0")),
                stderr=io.StringIO(),
                target_python=target,
            )
            rendered = result.plan.to_dict() if result.plan is not None else {}
        self.assertEqual("external-installer", rendered["activation_owner"])
        self.assertEqual("gravity-insight==99.0.0", rendered["artifact"])
        self.assertEqual(str(target), rendered["target_environment"])
        self.assertIn("artifact-digest", rendered["required_verification"])
        self.assertIn("provenance", rendered["required_verification"])
        self.assertIn("signature", rendered["required_verification"])

    def test_successful_check_cache_reuses_the_same_plan_request(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = fake_target_python(root)
            first = maybe_auto_upgrade(
                ["agent"], environ={AUTO_UPGRADE_ENV: "1"},
                state_path=root / "update-check.json", now=NOW,
                request=lambda _headers: FakeResponse(200, pypi("99.0.0")),
                stderr=io.StringIO(), target_python=target,
            )
            second = maybe_auto_upgrade(
                ["agent"], environ={AUTO_UPGRADE_ENV: "1"},
                state_path=root / "update-check.json", now=NOW + timedelta(seconds=1),
                request=Mock(side_effect=AssertionError("successful check must be cached")),
                stderr=io.StringIO(), target_python=target,
            )
        self.assertEqual(first.plan, second.plan)
        self.assertEqual("plan_ready", second.status)

    def test_entry_continues_the_command_after_plan_generation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            target = fake_target_python(Path(raw))
            environment = {
                AUTO_UPGRADE_ENV: "1",
                TARGET_PYTHON_ENV: str(target),
                "LOCALAPPDATA": raw,
                "XDG_CACHE_HOME": raw,
            }
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, environment), patch(
                "gravity_sdk.auto_upgrade._distribution_get",
                return_value=FakeResponse(200, pypi("99.0.0")),
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = entry.main(["--help"])
        self.assertEqual(0, exit_code, stderr.getvalue())
        self.assertIn("Gravity SDK", stdout.getvalue())
        self.assertIn("continuing this command", stderr.getvalue())

    def test_runtime_does_not_mutate_environment_target_or_project_lock(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = fake_target_python(root)
            project_lock = root / "gravity.skills.lock.json"
            project_lock.write_text('{"locked":true}\n', encoding="utf-8")
            before_lock = project_lock.read_bytes()
            before_target = target.stat()
            environment = {AUTO_UPGRADE_ENV: "1", "UNCHANGED_SENTINEL": "yes"}
            with patch.dict(os.environ, environment, clear=True):
                before_environment = dict(os.environ)
                with patch("subprocess.run", side_effect=AssertionError("no subprocess")) as run, patch(
                    "os.execv", side_effect=AssertionError("no process replacement")
                ) as execv:
                    result = maybe_auto_upgrade(
                        ["agent"], environ=os.environ,
                        state_path=root / "cache" / "update-check.json", now=NOW,
                        request=lambda _headers: FakeResponse(200, pypi("99.0.0")),
                        stderr=io.StringIO(), target_python=target,
                    )
                after_environment = dict(os.environ)
            self.assertEqual(before_lock, project_lock.read_bytes())
            self.assertEqual((before_target.st_size, before_target.st_mtime_ns), (
                target.stat().st_size, target.stat().st_mtime_ns
            ))
        self.assertEqual("plan_ready", result.status)
        self.assertEqual(before_environment, after_environment)
        run.assert_not_called()
        execv.assert_not_called()
        source = Path(upgrade.__file__).read_text(encoding="utf-8")
        self.assertNotIn("subprocess", source)
        self.assertNotIn('"-m", "pip"', source)
        self.assertNotIn("execv", source)

    def test_unreachable_release_source_blocks_opted_in_entry(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            environment = {
                AUTO_UPGRADE_ENV: "1", "LOCALAPPDATA": raw, "XDG_CACHE_HOME": raw
            }
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, environment), patch(
                "gravity_sdk.auto_upgrade._distribution_get", side_effect=OSError("offline")
            ), redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = entry.main(["--help"])
        self.assertEqual(UPDATE_POLICY_EXIT_CODE, exit_code)
        self.assertEqual("", stdout.getvalue())
        self.assertIn("This command was not run", stderr.getvalue())

    def test_doctor_neither_checks_nor_touches_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            network = Mock(side_effect=AssertionError("doctor must stay offline"))
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, {
                AUTO_UPGRADE_ENV: "1", "LOCALAPPDATA": raw, "XDG_CACHE_HOME": raw
            }), patch("gravity_sdk.auto_upgrade._distribution_get", network), redirect_stdout(
                stdout
            ), redirect_stderr(stderr):
                exit_code = entry.main(["doctor"])
            state_exists = bool(list(Path(raw, "GravityInsight").glob("update-check*.json")))
        self.assertEqual(0, exit_code, stderr.getvalue())
        self.assertFalse(state_exists)
        network.assert_not_called()

    def test_pinned_version_keeps_real_entry_offline(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            network = Mock(side_effect=AssertionError("pin must stay offline"))
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(os.environ, {
                AUTO_UPGRADE_ENV: "1", PINNED_VERSION_ENV: __version__,
                "LOCALAPPDATA": raw, "XDG_CACHE_HOME": raw,
            }), patch("gravity_sdk.auto_upgrade._distribution_get", network), redirect_stdout(
                stdout
            ), redirect_stderr(stderr):
                exit_code = entry.main(["--help"])
        self.assertEqual(0, exit_code, stderr.getvalue())
        self.assertTrue(stdout.getvalue().strip())
        network.assert_not_called()

    def test_test_and_evaluation_entrypoints_set_the_off_switch(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertIn('"GRAVITY_SDK_AUTO_UPGRADE": "0"', (
            root / "tests" / "__init__.py"
        ).read_text(encoding="utf-8"))
        self.assertIn('os.environ["GRAVITY_SDK_AUTO_UPGRADE"] = "0"', (
            root / "scripts" / "agent_usability_eval.py"
        ).read_text(encoding="utf-8"))


class AutoUpgradePlanEndToEndTests(unittest.TestCase):
    def test_e2e_new_version_returns_external_plan_request_and_no_environment(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = fake_target_python(root)
            installer = Mock(side_effect=AssertionError("installer belongs outside Runtime"))
            result = maybe_auto_upgrade(
                ["agent-catalog", "categories"], environ={AUTO_UPGRADE_ENV: "1"},
                state_path=root / "update-check.json", now=NOW,
                request=lambda _headers: FakeResponse(200, pypi("99.0.0")),
                stderr=io.StringIO(), target_python=target,
            )
            rendered = result.plan.to_dict() if result.plan is not None else {}
        self.assertEqual("plan_ready", result.status)
        self.assertEqual("gravity-insight==99.0.0", rendered["artifact"])
        self.assertEqual("forbidden", rendered["runtime_environment_mutation"])
        installer.assert_not_called()

    def test_e2e_current_version_has_no_plan_and_no_install(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            installer = Mock(side_effect=AssertionError("current version must not install"))
            result = maybe_auto_upgrade(
                ["agent"], environ={AUTO_UPGRADE_ENV: "1"},
                state_path=root / "update-check.json", now=NOW,
                request=lambda _headers: FakeResponse(200, pypi(__version__)),
                stderr=io.StringIO(), target_python=fake_target_python(root),
            )
        self.assertEqual(("checked", __version__), (result.status, result.latest_version))
        self.assertIsNone(result.plan)
        installer.assert_not_called()

    def test_e2e_unreachable_index_is_terminal_and_has_no_plan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            result = maybe_auto_upgrade(
                ["agent"], environ={AUTO_UPGRADE_ENV: "1"},
                state_path=Path(raw) / "update-check.json", now=NOW,
                request=Mock(side_effect=OSError("offline")), stderr=io.StringIO(),
                target_python=fake_target_python(Path(raw)),
            )
        self.assertEqual("failed", result.status)
        self.assertIn(result.status, TERMINAL_UPGRADE_STATUSES)
        self.assertIsNone(result.plan)

    def test_e2e_downgrade_is_rejected_without_a_plan_or_install(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = maybe_auto_upgrade(
                ["agent"], environ={AUTO_UPGRADE_ENV: "1"},
                state_path=root / "update-check.json", now=NOW,
                request=lambda _headers: FakeResponse(200, pypi("0.3.1")),
                stderr=io.StringIO(), target_python=fake_target_python(root),
            )
        self.assertEqual("downgrade_rejected", result.status)
        self.assertIsNone(result.plan)

    def test_e2e_external_install_failure_remains_outside_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            failed_installer = Mock(side_effect=RuntimeError("mid-install failure"))
            result = maybe_auto_upgrade(
                ["agent"], environ={AUTO_UPGRADE_ENV: "1"},
                state_path=root / "update-check.json", now=NOW,
                request=lambda _headers: FakeResponse(200, pypi("98.0.0")),
                stderr=io.StringIO(), target_python=fake_target_python(root),
            )
            rendered = result.plan.to_dict() if result.plan is not None else {}
        self.assertEqual("plan_ready", result.status)
        self.assertEqual("external-installer", rendered["activation_owner"])
        self.assertEqual("rollback", rendered["lifecycle"][-1])
        failed_installer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
