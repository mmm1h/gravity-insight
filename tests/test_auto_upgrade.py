from __future__ import annotations

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from gravity_sdk import __version__
from gravity_sdk import __main__ as entry
from gravity_sdk.auto_upgrade import (
    AUTO_UPGRADE_ENV,
    DISTRIBUTION_HTTP_KIND,
    PINNED_VERSION_ENV,
    UPDATE_CHECK_INTERVAL,
    check_latest_tag,
    maybe_auto_upgrade,
    startup_update_enabled,
    update_state_path,
)
from gravity_sdk.receipt import count_http_requests


NOW = datetime(2026, 8, 27, 8, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, status: int, payload: object = None, *, etag: str | None = None):
        self.status_code = status
        self.content = payload if isinstance(payload, bytes) else b""
        self.headers = {"ETag": etag} if etag is not None else {}


def atom(*tags: str) -> bytes:
    entries = "".join(f"<entry><title>{tag}</title></entry>" for tag in tags)
    return (
        '<feed xmlns="http://www.w3.org/2005/Atom">'
        f"{entries}</feed>"
    ).encode("utf-8")


def state(*, checked_at: datetime, etag: str | None, latest_tag: str | None) -> dict[str, object]:
    return {
        "schema_version": 1,
        "checked_at": checked_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "etag": etag,
        "latest_tag": latest_tag,
    }


class UpdateStateTests(unittest.TestCase):
    def test_state_path_uses_the_existing_cross_platform_cache_root_top_level(self) -> None:
        cases = (
            ({"LOCALAPPDATA": "C:/Local", "XDG_CACHE_HOME": "C:/ignored"}, Path("C:/Local/GravityInsight/update-check.json")),
            ({"XDG_CACHE_HOME": "/var/cache/user"}, Path("/var/cache/user/GravityInsight/update-check.json")),
        )
        for environment, expected in cases:
            with self.subTest(environment=environment), patch.dict(os.environ, environment, clear=True):
                self.assertEqual(expected, update_state_path())
        with patch.dict(os.environ, {}, clear=True), patch(
            "gravity_sdk.runtime_scope.Path.home", return_value=Path("/Users/analyst")
        ):
            self.assertEqual(
                Path("/Users/analyst/.cache/gravity-insight/update-check.json"),
                update_state_path(),
            )

    def test_check_writes_only_the_four_authorized_fields_and_reuses_interval(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "update-check.json"
            request = Mock(return_value=FakeResponse(200, atom(), etag='"empty"'))
            first = check_latest_tag(state_path=path, now=NOW, request=request)
            second = check_latest_tag(
                state_path=path,
                now=NOW + UPDATE_CHECK_INTERVAL - timedelta(seconds=1),
                request=Mock(side_effect=AssertionError("interval must skip HTTP")),
            )
            stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(("checked", "cached"), (first.status, second.status))
        self.assertEqual(
            {"schema_version", "checked_at", "etag", "latest_tag"}, set(stored)
        )
        self.assertEqual((1, '"empty"', None), (stored["schema_version"], stored["etag"], stored["latest_tag"]))
        request.assert_called_once()

    def test_etag_is_sent_and_304_refreshes_without_production_http_accounting(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "update-check.json"
            path.write_text(
                json.dumps(
                    state(
                        checked_at=NOW - UPDATE_CHECK_INTERVAL,
                        etag='W/"release-etag"',
                        latest_tag="v0.3.2",
                    )
                ),
                encoding="utf-8",
            )
            observed: dict[str, str] = {}

            def request(headers):
                observed.update(headers)
                return FakeResponse(304)

            with count_http_requests() as production:
                result = check_latest_tag(state_path=path, now=NOW, request=request)
            stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("code_distribution", DISTRIBUTION_HTTP_KIND)
        self.assertEqual(0, production.count)
        self.assertEqual('W/"release-etag"', observed["If-None-Match"])
        self.assertEqual(("not_modified", "v0.3.2"), (result.status, result.latest_tag))
        self.assertEqual(
            (NOW.isoformat(timespec="seconds").replace("+00:00", "Z"), 'W/"release-etag"', "v0.3.2"),
            (stored["checked_at"], stored["etag"], stored["latest_tag"]),
        )

    def test_latest_strict_version_tag_wins_and_branches_cannot_be_selected(self) -> None:
        payload = atom("main", "v0.3.2", "v2.0.0", "release/99", "v2.0.0-rc1")
        with tempfile.TemporaryDirectory() as raw:
            result = check_latest_tag(
                state_path=Path(raw) / "update-check.json",
                now=NOW,
                request=lambda _headers: FakeResponse(200, payload, etag='"tags"'),
            )
        self.assertEqual(("checked", "v2.0.0"), (result.status, result.latest_tag))

    def test_corrupt_unreadable_or_unwritable_state_fails_open_without_http(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            corrupt = root / "corrupt.json"
            corrupt.write_text("{broken", encoding="utf-8")
            request = Mock(side_effect=AssertionError("bad state must skip HTTP"))
            damaged = check_latest_tag(state_path=corrupt, now=NOW, request=request)

            parent_file = root / "not-a-directory"
            parent_file.write_text("blocked", encoding="utf-8")
            unwritable = check_latest_tag(
                state_path=parent_file / "update-check.json",
                now=NOW,
                request=request,
            )
        self.assertEqual(("failed", "failed"), (damaged.status, unwritable.status))
        request.assert_not_called()

    def test_concurrent_callers_share_one_cross_process_claim(self) -> None:
        calls = 0

        def request(_headers):
            nonlocal calls
            calls += 1
            return FakeResponse(200, atom(), etag='"shared"')

        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "update-check.json"
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(
                        lambda _index: check_latest_tag(
                            state_path=path, now=NOW, request=request
                        ),
                        range(2),
                    )
                )
        self.assertEqual(1, calls)
        statuses = [result.status for result in results]
        self.assertEqual(1, statuses.count("checked"))
        self.assertIn(next(status for status in statuses if status != "checked"), {"busy", "cached"})


class StartupUpgradeTests(unittest.TestCase):
    def test_doctor_eval_test_pin_and_reexec_paths_disable_the_check(self) -> None:
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

    def test_pip_failure_is_visible_and_current_command_can_continue(self) -> None:
        stderr = io.StringIO()
        runner = Mock(return_value=subprocess.CompletedProcess([], 7))
        replacement = Mock(side_effect=AssertionError("failed pip must not restart"))
        with tempfile.TemporaryDirectory() as raw:
            result = maybe_auto_upgrade(
                ["agent-catalog", "categories"],
                environ={AUTO_UPGRADE_ENV: "1"},
                state_path=Path(raw) / "update-check.json",
                now=NOW,
                request=lambda _headers: FakeResponse(200, atom("v99.0.0")),
                run=runner,
                execv=replacement,
                stderr=stderr,
            )
        self.assertEqual("upgrade_failed", result.status)
        self.assertIn("continuing with version", stderr.getvalue())
        replacement.assert_not_called()

    def test_successful_pip_replaces_the_process_with_the_same_command(self) -> None:
        observed: dict[str, object] = {}

        def replace(executable: str, arguments: list[str]) -> None:
            observed.update(
                executable=executable,
                arguments=arguments,
                reexec=os.environ.get("GRAVITY_SDK_UPGRADE_REEXEC"),
            )

        with tempfile.TemporaryDirectory() as raw:
            result = maybe_auto_upgrade(
                ["agent-catalog", "categories"],
                environ={AUTO_UPGRADE_ENV: "1"},
                state_path=Path(raw) / "update-check.json",
                now=NOW,
                request=lambda _headers: FakeResponse(200, atom("v99.0.0")),
                run=lambda *args, **kwargs: subprocess.CompletedProcess(args, 0),
                execv=replace,
                stderr=io.StringIO(),
            )
        self.assertEqual("restarted", result.status)
        self.assertEqual("1", observed["reexec"])
        self.assertEqual(
            [os.sys.executable, "-m", "gravity_sdk", "agent-catalog", "categories"],
            observed["arguments"],
        )

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
            state_exists = Path(raw, "GravityInsight", "update-check.json").exists()
        result = json.loads(stdout.getvalue())
        self.assertEqual(0, exit_code, stderr.getvalue())
        self.assertFalse(result["network_called"])
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
