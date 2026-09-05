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

from gravity_insight import __version__
from gravity_insight import _auto_upgrade_state as upgrade_state
from gravity_insight import __main__ as entry
from gravity_insight import auto_upgrade as upgrade
from gravity_insight.auto_upgrade import (
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
from gravity_insight.receipt import (
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
    def test_state_path_uses_the_existing_cross_platform_cache_root_top_level(
        self,
    ) -> None:
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
            with (
                self.subTest(environment=environment),
                patch.dict(os.environ, environment, clear=True),
            ):
                self.assertEqual(
                    expected.with_name(f"update-check-{scope}.json"),
                    update_state_path(),
                )
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "gravity_insight.runtime_scope.Path.home",
                return_value=Path("/Users/analyst"),
            ),
        ):
            self.assertEqual(
                Path(
                    f"/Users/analyst/.cache/gravity-insight/update-check-{scope}.json"
                ),
                update_state_path(),
            )

    def test_successful_check_writes_release_facts_and_cached_check_reuses_version(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "update-check.json"
            request = Mock(
                return_value=FakeResponse(200, pypi(__version__), etag='"release"')
            )
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
        self.assertEqual(f"gravity-insight/{__version__}", observed["User-Agent"])
        self.assertEqual(
            ("not_modified", "0.3.2"), (result.status, result.latest_version)
        )
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

    def test_distribution_request_enters_authoritative_boundary_without_production_count(
        self,
    ) -> None:
        response = FakeResponse(200, pypi(__version__))
        with patch(
            "gravity_insight.auto_upgrade.requests.get", return_value=response
        ) as network:
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

    def test_concurrent_stale_lease_takeover_has_one_inspector_and_one_holder(
        self,
    ) -> None:
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
        self.assertEqual(
            ("checked", "busy"), (first_result.status, second_result.status)
        )
        self.assertEqual(1, expired_checks)
        self.assertEqual(1, maximum_holders)

    def test_success_state_is_published_with_atomic_replace(self) -> None:
        with (
            tempfile.TemporaryDirectory() as raw,
            patch(
                "gravity_insight._auto_upgrade_state.os.replace", wraps=os.replace
            ) as replace,
        ):
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


class StartupInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        from gravity_insight import _auto_upgrade_install as installer

        self.installer = installer
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = io.StringIO()
        self.request = Mock(return_value=FakeResponse(200, pypi("99.0.0")))
        self.python = patch.object(
            installer,
            "_python",
            return_value=Mock(
                returncode=0,
                stdout="Successfully installed gravity-insight-99.0.0\n",
                stderr="",
            ),
        ).start()
        self.addCleanup(patch.stopall)

    def install(self, **kwargs):
        return maybe_auto_upgrade(
            ["agent"],
            environ=kwargs.pop("environ", {}),
            state_path=self.root / "update-check.json",
            now=kwargs.pop("now", NOW),
            request=self.request,
            stderr=self.output,
            **kwargs,
        )

    def test_default_is_on_and_all_explicit_off_values_skip_every_side_effect(self):
        self.assertTrue(startup_update_enabled(["agent"], environ={}))
        for value in ("0", "false", "no", "off", " FALSE "):
            self.assertEqual(
                "disabled", self.install(environ={AUTO_UPGRADE_ENV: value}).status
            )
        self.request.assert_not_called()
        self.python.assert_not_called()
        self.assertEqual([], list(self.root.iterdir()))

    def test_new_environment_names_take_effect_for_all_inputs(self):
        self.assertEqual(
            (
                "GRAVITY_INSIGHT_AUTO_UPGRADE",
                "GRAVITY_INSIGHT_PINNED_VERSION",
                "GRAVITY_INSIGHT_AUTO_UPGRADE_TARGET_PYTHON",
            ),
            (AUTO_UPGRADE_ENV, PINNED_VERSION_ENV, TARGET_PYTHON_ENV),
        )
        self.assertEqual(
            "chosen",
            upgrade._target_python_from_environment({TARGET_PYTHON_ENV: "chosen"}),
        )

    def test_legacy_environment_names_remain_effective_for_all_inputs(self):
        self.assertTrue(
            startup_update_enabled(["agent"], environ={"GRAVITY_SDK_AUTO_UPGRADE": "1"})
        )
        self.assertFalse(
            startup_update_enabled(
                ["agent"], environ={"GRAVITY_SDK_PINNED_VERSION": __version__}
            )
        )
        self.assertEqual(
            "old",
            upgrade._target_python_from_environment(
                {"GRAVITY_SDK_AUTO_UPGRADE_TARGET_PYTHON": "old"}
            ),
        )

    def test_new_environment_names_win_when_both_names_are_set(self):
        self.assertFalse(
            startup_update_enabled(
                ["agent"],
                environ={AUTO_UPGRADE_ENV: "0", "GRAVITY_SDK_AUTO_UPGRADE": "1"},
            )
        )
        self.assertTrue(
            startup_update_enabled(
                ["agent"],
                environ={
                    PINNED_VERSION_ENV: "99.0.0",
                    "GRAVITY_SDK_PINNED_VERSION": __version__,
                },
            )
        )
        self.assertEqual(
            "new",
            upgrade._target_python_from_environment(
                {
                    TARGET_PYTHON_ENV: "new",
                    "GRAVITY_SDK_AUTO_UPGRADE_TARGET_PYTHON": "old",
                }
            ),
        )

    def test_doctor_pin_and_test_evaluation_paths_remain_offline(self):
        for argv in (["doctor"], ["insight", "doctor"]):
            self.assertFalse(
                startup_update_enabled(argv, environ={AUTO_UPGRADE_ENV: "1"})
            )
        self.assertFalse(
            startup_update_enabled(["agent"], environ={PINNED_VERSION_ENV: __version__})
        )
        root = Path(__file__).resolve().parents[1]
        self.assertIn(
            '"GRAVITY_INSIGHT_AUTO_UPGRADE": "0"',
            (root / "tests/__init__.py").read_text(encoding="utf-8"),
        )
        self.assertIn(
            'os.environ["GRAVITY_INSIGHT_AUTO_UPGRADE"] = "0"',
            (root / "scripts/agent_usability_eval.py").read_text(encoding="utf-8"),
        )

    def test_invalid_or_mismatched_pin_does_not_disable_the_check(self):
        for value in ("invalid", "99.0.0"):
            self.assertTrue(
                startup_update_enabled(["agent"], environ={PINNED_VERSION_ENV: value})
            )

    def test_default_interpreter_installs_exact_version_in_separate_stage(self):
        result = self.install()
        self.assertEqual("installed", result.status)
        target, args = self.python.call_args_list[0].args
        self.assertEqual(Path(sys.executable).resolve(), target)
        self.assertIn("--target", args)
        self.assertEqual("gravity-insight==99.0.0", args[-1])
        self.assertNotEqual(Path(upgrade.__file__).parent, Path(result.state["stage"]))
        self.assertIn(f"this process still runs {__version__}", self.output.getvalue())

    def test_explicit_current_interpreter_is_safe_because_only_stage_is_written(self):
        result = self.install(target_python=sys.executable)
        self.assertEqual("installed", result.status)
        self.assertIn("--target", self.python.call_args_list[0].args[1])

    def test_environment_target_is_used(self):
        target = fake_target_python(self.root)
        result = self.install(environ={TARGET_PYTHON_ENV: str(target)})
        self.assertEqual(str(target), result.state["target_python"])
        self.assertEqual(target, self.python.call_args_list[0].args[0])

    def test_missing_target_reports_actionable_failure_without_install(self):
        result = self.install(target_python=self.root / "absent")
        self.assertEqual("failed", result.status)
        self.assertIn("valid target interpreter", self.output.getvalue())
        self.python.assert_not_called()

    def test_receipt_binds_transition_time_trigger_target_and_running_version(self):
        result = self.install()
        receipt = result.state
        self.assertEqual(self.installer.RECEIPT_SCHEMA, receipt["schema_version"])
        self.assertEqual(
            (__version__, "99.0.0", __version__),
            (
                receipt["from_version"],
                receipt["to_version"],
                receipt["running_version"],
            ),
        )
        self.assertEqual(
            {"kind": "cli_startup", "pid": os.getpid()}, receipt["trigger"]
        )
        self.assertTrue(receipt["captured_at"].endswith("Z"))
        journal = (
            Path(receipt["stage"]).parent / f"receipt-{receipt['receipt_id']}.json"
        )
        self.assertEqual(receipt, json.loads(journal.read_text(encoding="utf-8")))

    def test_success_cache_reuses_install_without_network_or_second_pip(self):
        first = self.install()
        second = self.install(now=NOW + timedelta(seconds=1))
        self.assertEqual(first.state, second.state)
        self.assertEqual(1, self.request.call_count)
        self.assertEqual(2, self.python.call_count)  # pip and isolated validation

    def test_failed_pip_is_diagnosable_and_retry_is_throttled(self):
        self.python.return_value = Mock(
            returncode=1, stdout="", stderr="Permission denied"
        )
        first = self.install()
        second = self.install(now=NOW + timedelta(seconds=1))
        self.assertEqual(("failed", "suppressed"), (first.status, second.status))
        self.assertIn("pip exited 1", self.output.getvalue())
        self.assertIn("permissions", self.output.getvalue())
        self.assertEqual(1, self.python.call_count)
        self.assertIn(
            "Permission denied",
            next(self.root.rglob("pip-*.log")).read_text(encoding="utf-8"),
        )

    def test_network_failure_continues_actual_cli_help(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, {AUTO_UPGRADE_ENV: "1"}),
            patch.object(
                upgrade,
                "update_state_path",
                return_value=self.root / "update-check.json",
            ),
            patch.object(upgrade, "_distribution_get", side_effect=OSError("offline")),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = entry.main(["--help"])
        self.assertEqual(0, code)
        self.assertIn("Gravity SDK", stdout.getvalue())
        self.assertIn("PyPI release source is unavailable", stderr.getvalue())
        self.assertIn("retry", stderr.getvalue())
        self.python.assert_not_called()

    def test_pip_failure_continues_actual_cli_help(self):
        self.python.return_value = Mock(
            returncode=1, stdout="", stderr="injected pip failure"
        )
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, {AUTO_UPGRADE_ENV: "1"}),
            patch.object(
                upgrade,
                "update_state_path",
                return_value=self.root / "update-check.json",
            ),
            patch.object(upgrade, "_distribution_get", self.request),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = entry.main(["--help"])
        self.assertEqual(0, code)
        self.assertIn("Gravity SDK", stdout.getvalue())
        self.assertIn("pip exited 1", stderr.getvalue())
        self.assertIn("Continuing this command", stderr.getvalue())

    def test_state_write_failure_is_nonfatal_and_no_install_occurs(self):
        with patch.object(
            upgrade_state, "_write_state_file", side_effect=PermissionError("read only")
        ):
            result = self.install()
        self.assertEqual("failed", result.status)
        self.python.assert_not_called()
        self.assertIn("permissions", self.output.getvalue())

    def test_validation_failure_does_not_publish_installed_stage(self):
        self.python.side_effect = [
            Mock(returncode=0, stdout="ok", stderr=""),
            Mock(returncode=1),
        ]
        self.assertEqual("failed", self.install().status)
        self.assertEqual([], list(self.root.rglob("installed-*.json")))
        self.assertIn("validation", self.output.getvalue())

    def test_current_and_older_releases_do_not_install(self):
        self.request.return_value = FakeResponse(200, pypi(__version__))
        self.assertEqual("checked", self.install().status)
        self.request.return_value = FakeResponse(200, pypi("0.0.1"))
        self.assertEqual("checked", self.install(now=NOW + timedelta(days=2)).status)
        self.python.assert_not_called()

    def test_environment_and_project_lock_are_not_mutated(self):
        lock = self.root / "gravity.skills.lock.json"
        lock.write_text('{"locked":true}', encoding="utf-8")
        before = dict(os.environ)
        self.install()
        self.assertEqual(before, dict(os.environ))
        self.assertEqual('{"locked":true}', lock.read_text(encoding="utf-8"))

    def test_parallel_installers_share_target_lock_even_with_different_check_files(
        self,
    ):
        entered, release = Event(), Event()
        original = self.python.return_value

        def run(*args, **kwargs):
            if "pip" in args[1]:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("test synchronization timeout")
            return original

        self.python.side_effect = run
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.install)
            self.assertTrue(entered.wait(5))
            try:
                second = maybe_auto_upgrade(
                    ["agent"],
                    environ={},
                    state_path=self.root / "other.json",
                    now=NOW + timedelta(minutes=2),
                    request=self.request,
                    stderr=self.output,
                )
                self.assertEqual("busy", second.status)
            finally:
                release.set()
            self.assertEqual("installed", first.result().status)
        self.assertEqual(
            1, sum("pip" in call.args[1] for call in self.python.call_args_list)
        )

    def test_activation_disables_recursion_passes_argv_and_propagates_business_exit(
        self,
    ):
        result = self.install()
        self.python.reset_mock()
        self.python.side_effect = [Mock(returncode=0), Mock(returncode=7)]
        code = self.installer.activate_install(
            result.state, ["agent", "private query"], output=self.output
        )
        self.assertEqual(7, code)
        call = self.python.call_args
        self.assertEqual(["agent", "private query"], call.args[1][-2:])
        self.assertFalse(call.kwargs["capture"])
        self.assertIsNone(call.kwargs["timeout"])
        self.assertEqual("0", call.kwargs["environment"][AUTO_UPGRADE_ENV])
        receipt = json.loads(
            Path(call.kwargs["environment"][self.installer.RECEIPT_ENV]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            ("process_exited", 7, "99.0.0"),
            (receipt["status"], receipt["exit_code"], receipt["running_version"]),
        )
        self.assertNotIn("private query", json.dumps(receipt))
        self.assertEqual(2, self.python.call_count)

    def test_activation_preflight_failure_falls_back_before_dispatch(self):
        result = self.install()
        self.python.reset_mock()
        self.python.return_value = Mock(returncode=1)
        self.assertIsNone(
            self.installer.activate_install(result.state, ["agent"], output=self.output)
        )
        self.assertEqual(1, self.python.call_count)
        self.assertIn("Continuing this command", self.output.getvalue())

    def test_child_spawn_failure_allows_current_command(self):
        result = self.install()
        self.python.side_effect = [Mock(returncode=0), PermissionError("denied")]
        self.assertIsNone(
            self.installer.activate_install(result.state, ["agent"], output=self.output)
        )
        self.assertIn("Check target permissions", self.output.getvalue())

    def test_entry_hands_off_before_importing_command_owners(self):
        with (
            patch.dict(os.environ, {AUTO_UPGRADE_ENV: "1"}),
            patch.object(
                upgrade,
                "maybe_auto_upgrade",
                return_value=upgrade.UpdateCheck("installed", state={"test": True}),
            ),
            patch.object(
                self.installer, "activate_install", return_value=17
            ) as activate,
        ):
            self.assertEqual(
                17, entry.main(["--workspace", "example", "agent", "query"])
            )
        self.assertEqual(["agent", "query"], activate.call_args.args[1])

    def test_external_plan_contract_remains_available_without_mutation(self):
        target = fake_target_python(self.root)
        result = upgrade._plan_checked_update(
            upgrade.UpdateCheck("checked", "99.0.0"),
            target_python=target,
            output=self.output,
        )
        self.assertEqual(
            "external-installer", result.plan.to_dict()["activation_owner"]
        )
        self.python.assert_not_called()

    def test_unexpected_startup_state_failure_is_nonfatal(self):
        with (
            patch.dict(os.environ, {AUTO_UPGRADE_ENV: "1"}),
            patch.object(
                upgrade,
                "update_state_path",
                side_effect=PermissionError("cache unavailable"),
            ),
            redirect_stdout(io.StringIO()),
            redirect_stderr(self.output),
        ):
            self.assertEqual(0, entry.main(["--help"]))
        self.assertIn("permissions", self.output.getvalue())
        self.python.assert_not_called()

    def test_actual_doctor_and_exact_pin_never_touch_update_state(self):
        with (
            patch.dict(os.environ, {AUTO_UPGRADE_ENV: "1"}),
            patch.object(
                upgrade,
                "update_state_path",
                side_effect=AssertionError("must stay offline"),
            ) as state_path,
            redirect_stdout(io.StringIO()),
            redirect_stderr(self.output),
        ):
            with self.assertRaises(SystemExit) as completed:
                entry.main(["doctor", "--help"])
            self.assertEqual(0, completed.exception.code)
            with patch.dict(os.environ, {PINNED_VERSION_ENV: __version__}):
                self.assertEqual(0, entry.main(["--help"]))
        state_path.assert_not_called()
        self.python.assert_not_called()


if __name__ == "__main__":
    unittest.main()
