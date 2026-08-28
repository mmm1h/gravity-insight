from __future__ import annotations

import io
import json
import os
import subprocess
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
    UPDATE_CHECK_INTERVAL,
    UPGRADE_RESTART_EXIT_CODE,
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


def completed(returncode: int, *, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def verified(version: str, *, code_verified: bool = True) -> str:
    return json.dumps(
        {
            "distribution_version": version,
            "code_verified": code_verified,
            "package_file_count": 200,
        }
    )


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

    def test_corrupt_or_unwritable_state_fails_open_without_http(self) -> None:
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


class StartupUpgradeTests(unittest.TestCase):
    def test_doctor_pin_off_switch_and_reexec_paths_disable_the_check(self) -> None:
        enabled = {AUTO_UPGRADE_ENV: "1"}
        self.assertFalse(startup_update_enabled(["doctor"], environ=enabled))
        self.assertFalse(startup_update_enabled(["insight", "doctor"], environ=enabled))
        self.assertFalse(
            startup_update_enabled(
                ["agent"], environ={**enabled, PINNED_VERSION_ENV: __version__}
            )
        )
        self.assertFalse(startup_update_enabled(["agent"], environ={AUTO_UPGRADE_ENV: "0"}))
        self.assertFalse(
            startup_update_enabled(
                ["agent"],
                environ={**enabled, "GRAVITY_SDK_UPGRADE_REEXEC": "1"},
            )
        )
        self.assertTrue(startup_update_enabled(["agent"], environ=enabled))

    def test_invalid_or_mismatched_pin_does_not_act_as_a_boolean_off_switch(self) -> None:
        for pinned in ("not-a-version", "99.0.0"):
            with self.subTest(pinned=pinned):
                self.assertTrue(
                    startup_update_enabled(
                        ["agent"],
                        environ={
                            AUTO_UPGRADE_ENV: "1",
                            PINNED_VERSION_ENV: pinned,
                        },
                    )
                )

    def test_pip_failure_is_terminal_and_blocks_the_next_startup(self) -> None:
        stderr = io.StringIO()
        runner = Mock(return_value=completed(7))
        replacement = Mock(side_effect=AssertionError("failed pip must not restart"))
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "update-check.json"
            first = maybe_auto_upgrade(
                ["agent-catalog", "categories"],
                environ={AUTO_UPGRADE_ENV: "1"},
                state_path=path,
                now=NOW,
                request=lambda _headers: FakeResponse(200, pypi("99.0.0")),
                run=runner,
                execv=replacement,
                stderr=stderr,
            )
            second = maybe_auto_upgrade(
                ["agent-catalog", "categories"],
                environ={AUTO_UPGRADE_ENV: "1"},
                state_path=path,
                now=NOW + timedelta(seconds=1),
                request=Mock(side_effect=AssertionError("successful check must be cached")),
                run=runner,
                execv=replacement,
                stderr=stderr,
            )
            stored = json.loads(
                update_attempt_state_path(path).read_text(encoding="utf-8")
            )
        self.assertEqual(
            ("upgrade_failed", "upgrade_incomplete"),
            (first.status, second.status),
        )
        self.assertEqual(1, runner.call_count)
        command = runner.call_args.args[0]
        self.assertIn("gravity-insight==99.0.0", command)
        self.assertIn("https://pypi.org/simple", command)
        self.assertNotIn("github.com", " ".join(command))
        self.assertEqual(
            ("99.0.0", timestamp(NOW), "failed"),
            (stored["attempted_version"], stored["attempted_at"], stored["status"]),
        )
        self.assertNotIn("continuing with version", stderr.getvalue())
        self.assertIn("this command was not run", stderr.getvalue())
        replacement.assert_not_called()

    def test_release_and_attempt_state_are_both_isolated_by_runtime(self) -> None:
        first_request = Mock(return_value=FakeResponse(200, pypi("99.0.0")))
        second_request = Mock(return_value=FakeResponse(200, pypi("99.0.0")))
        runner = Mock(return_value=completed(7))
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            first_scope = upgrade_state.runtime_scope_id(
                str(root / "python-a"), root / "package-a"
            )
            second_scope = upgrade_state.runtime_scope_id(
                str(root / "python-b"), root / "package-b"
            )
            first_path = root / f"update-check-{first_scope}.json"
            second_path = root / f"update-check-{second_scope}.json"
            first = maybe_auto_upgrade(
                ["agent-catalog", "categories"],
                environ={AUTO_UPGRADE_ENV: "1"},
                state_path=first_path,
                now=NOW,
                request=first_request,
                run=runner,
                stderr=io.StringIO(),
            )
            first_attempt = update_attempt_state_path(first_path)
            second = maybe_auto_upgrade(
                ["agent-catalog", "categories"],
                environ={AUTO_UPGRADE_ENV: "1"},
                state_path=second_path,
                now=NOW + timedelta(seconds=1),
                request=second_request,
                run=runner,
                stderr=io.StringIO(),
            )
            second_attempt = update_attempt_state_path(second_path)
            attempt_files_exist = (first_attempt.exists(), second_attempt.exists())
        self.assertEqual(("upgrade_failed", "upgrade_failed"), (first.status, second.status))
        self.assertEqual((1, 1), (first_request.call_count, second_request.call_count))
        self.assertEqual(2, runner.call_count)
        self.assertNotEqual(first_path, second_path)
        self.assertNotEqual(first_attempt, second_attempt)
        self.assertEqual((True, True), attempt_files_exist)

    def test_pip_success_but_version_mismatch_is_terminal_before_exec(self) -> None:
        stderr = io.StringIO()
        runner = Mock(side_effect=[completed(0), completed(0, stdout=verified("98.0.0"))])
        replacement = Mock(side_effect=AssertionError("unverified install must not restart"))
        with tempfile.TemporaryDirectory() as raw:
            result = maybe_auto_upgrade(
                ["agent-catalog", "categories"],
                environ={AUTO_UPGRADE_ENV: "1"},
                state_path=Path(raw) / "update-check.json",
                now=NOW,
                request=lambda _headers: FakeResponse(200, pypi("99.0.0")),
                run=runner,
                execv=replacement,
                stderr=stderr,
            )
        self.assertEqual("verification_failed", result.status)
        self.assertIn("installed version could not be verified", stderr.getvalue())
        self.assertIn("This command was not run; rerun it once", stderr.getvalue())
        replacement.assert_not_called()

    def test_matching_metadata_with_shadowed_imported_code_is_terminal(self) -> None:
        stderr = io.StringIO()
        runner = Mock(
            side_effect=[
                completed(0),
                completed(0, stdout=verified("99.0.0", code_verified=False)),
            ]
        )
        replacement = Mock(side_effect=AssertionError("shadowed code must not restart"))
        with tempfile.TemporaryDirectory() as raw:
            result = maybe_auto_upgrade(
                ["agent-catalog", "categories"],
                environ={AUTO_UPGRADE_ENV: "1"},
                state_path=Path(raw) / "update-check.json",
                now=NOW,
                request=lambda _headers: FakeResponse(200, pypi("99.0.0")),
                run=runner,
                execv=replacement,
                stderr=stderr,
            )
        self.assertEqual("verification_failed", result.status)
        self.assertIn("does not match the installed distribution files", result.detail or "")
        self.assertIn("This command was not run; rerun it once", stderr.getvalue())
        replacement.assert_not_called()

    def test_exec_return_is_failure_and_never_claimed_as_restarted(self) -> None:
        stderr = io.StringIO()
        runner = Mock(side_effect=[completed(0), completed(0, stdout=verified("99.0.0"))])
        replacement = Mock(return_value=None)
        with tempfile.TemporaryDirectory() as raw:
            result = maybe_auto_upgrade(
                ["agent-catalog", "categories"],
                environ={AUTO_UPGRADE_ENV: "1"},
                state_path=Path(raw) / "update-check.json",
                now=NOW,
                request=lambda _headers: FakeResponse(200, pypi("99.0.0")),
                run=runner,
                execv=replacement,
                stderr=stderr,
            )
        self.assertEqual("restart_failed", result.status)
        self.assertIn("returned unexpectedly", result.detail or "")
        self.assertIn("This command was not run; rerun it once", stderr.getvalue())

    def test_entry_terminates_after_pip_success_and_exec_failure_before_command(self) -> None:
        def runner(command, **_kwargs):
            if command[1:4] == ["-m", "pip", "install"]:
                return completed(0)
            return completed(0, stdout=verified("99.0.0"))

        with tempfile.TemporaryDirectory() as raw:
            environment = {
                AUTO_UPGRADE_ENV: "1",
                "LOCALAPPDATA": raw,
                "XDG_CACHE_HOME": raw,
            }
            command_guard = Mock(
                side_effect=AssertionError("user command must not execute in old process")
            )
            stderr = io.StringIO()
            original_guard = entry.ensure_first_run_credentials
            entry.ensure_first_run_credentials = command_guard
            try:
                with patch.dict(os.environ, environment), patch(
                    "gravity_sdk.auto_upgrade._distribution_get",
                    return_value=FakeResponse(200, pypi("99.0.0")),
                ), patch(
                    "gravity_sdk.auto_upgrade.subprocess.run", side_effect=runner
                ) as subprocess_run, patch(
                    "gravity_sdk.auto_upgrade.os.execv", side_effect=OSError("blocked")
                ) as replacement, redirect_stderr(stderr):
                    exit_code = entry.main(["agent-catalog", "categories"])
            finally:
                entry.ensure_first_run_credentials = original_guard
        self.assertEqual(UPGRADE_RESTART_EXIT_CODE, exit_code)
        self.assertEqual(2, subprocess_run.call_count)
        replacement.assert_called_once()
        command_guard.assert_not_called()
        self.assertIn("was upgraded to 99.0.0", stderr.getvalue())
        self.assertIn("This command was not run; rerun it once", stderr.getvalue())

    def test_entry_terminates_after_pip_nonzero_or_timeout_before_command(self) -> None:
        def nonzero(_command, **_kwargs):
            return completed(7)

        def timeout(command, **_kwargs):
            raise subprocess.TimeoutExpired(command, 300)

        for label, runner in (("nonzero", nonzero), ("timeout", timeout)):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                environment = {
                    AUTO_UPGRADE_ENV: "1",
                    "LOCALAPPDATA": raw,
                    "XDG_CACHE_HOME": raw,
                }
                command_guard = Mock(
                    side_effect=AssertionError("user command must not execute after pip")
                )
                stderr = io.StringIO()
                original_guard = entry.ensure_first_run_credentials
                entry.ensure_first_run_credentials = command_guard
                try:
                    with patch.dict(os.environ, environment), patch(
                        "gravity_sdk.auto_upgrade._distribution_get",
                        return_value=FakeResponse(200, pypi("99.0.0")),
                    ), patch(
                        "gravity_sdk.auto_upgrade.subprocess.run", side_effect=runner
                    ) as subprocess_run, redirect_stderr(stderr):
                        exit_code = entry.main(["agent-catalog", "categories"])
                finally:
                    entry.ensure_first_run_credentials = original_guard
            self.assertEqual(UPGRADE_RESTART_EXIT_CODE, exit_code)
            self.assertEqual(1, subprocess_run.call_count)
            command_guard.assert_not_called()
            self.assertIn("pip may have modified this environment", stderr.getvalue())
            self.assertIn("this command was not run", stderr.getvalue())

    def test_offline_help_and_real_command_exit_zero_with_visible_warning(self) -> None:
        commands = (["--help"], ["agent-catalog", "categories"])
        for command in commands:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as raw:
                environment = {
                    AUTO_UPGRADE_ENV: "1",
                    "LOCALAPPDATA": raw,
                    "XDG_CACHE_HOME": raw,
                }
                stdout, stderr = io.StringIO(), io.StringIO()
                with patch.dict(os.environ, environment), patch(
                    "gravity_sdk.auto_upgrade._distribution_get",
                    side_effect=OSError("offline"),
                ), redirect_stdout(stdout), redirect_stderr(stderr):
                    exit_code = entry.main(command)
            self.assertEqual(0, exit_code, stderr.getvalue())
            self.assertIn("update check failed", stderr.getvalue())
            self.assertTrue(stdout.getvalue().strip())

    def test_doctor_neither_checks_nor_touches_state_and_remains_offline(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            stdout, stderr = io.StringIO(), io.StringIO()
            network = Mock(side_effect=AssertionError("doctor must not check updates"))
            with patch.dict(
                os.environ,
                {AUTO_UPGRADE_ENV: "1", "LOCALAPPDATA": raw, "XDG_CACHE_HOME": raw},
            ), patch("gravity_sdk.auto_upgrade._distribution_get", network), redirect_stdout(
                stdout
            ), redirect_stderr(stderr):
                exit_code = entry.main(["doctor"])
            state_exists = bool(
                list(Path(raw, "GravityInsight").glob("update-check*.json"))
            )
        result = json.loads(stdout.getvalue())
        self.assertEqual(0, exit_code, stderr.getvalue())
        self.assertFalse(result["network_called"])
        self.assertFalse(state_exists)
        network.assert_not_called()

    def test_pinned_version_keeps_real_entry_offline_and_does_not_touch_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            network = Mock(side_effect=AssertionError("pin must keep startup offline"))
            stdout, stderr = io.StringIO(), io.StringIO()
            with patch.dict(
                os.environ,
                {
                    AUTO_UPGRADE_ENV: "1",
                    PINNED_VERSION_ENV: __version__,
                    "LOCALAPPDATA": raw,
                    "XDG_CACHE_HOME": raw,
                },
            ), patch("gravity_sdk.auto_upgrade._distribution_get", network), redirect_stdout(
                stdout
            ), redirect_stderr(stderr):
                exit_code = entry.main(["--help"])
            state_exists = bool(
                list(Path(raw, "GravityInsight").glob("update-check*.json"))
            )
        self.assertEqual(0, exit_code, stderr.getvalue())
        self.assertTrue(stdout.getvalue().strip())
        self.assertFalse(state_exists)
        network.assert_not_called()

    def test_test_and_evaluation_entrypoints_explicitly_set_the_off_switch(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertIn(
            '"GRAVITY_SDK_AUTO_UPGRADE": "0"',
            (root / "tests" / "__init__.py").read_text(encoding="utf-8"),
        )
        self.assertIn(
            'os.environ["GRAVITY_SDK_AUTO_UPGRADE"] = "0"',
            (root / "scripts" / "agent_usability_eval.py").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
