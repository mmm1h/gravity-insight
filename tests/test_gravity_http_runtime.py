from __future__ import annotations

import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import requests

from gravity_sdk.adaptive_governor import AdaptiveRequestGovernor, STATIC

try:
    from gravity_sdk import (
        AuthenticationError,
        Credential,
        CredentialProvider,
        PermissionUnavailableError,
        PolicyViolation,
        SqlValidationError,
    )
    from gravity_sdk.credentials import GRAVITY_HOST
    from gravity_sdk import http_runtime as runtime_module
    from gravity_sdk.http_runtime import (
        CONNECTION_POOL_SIZE,
        FALLBACK_CHROME_MAJOR,
        INSIGHT_PROFILE,
        SQL_PROFILE,
        GravityHttpRuntime,
        HostRateLimiter,
        _detect_chrome_major,
        _build_session,
        browser_headers,
    )
except ModuleNotFoundError:  # source checkout without an editable install
    from gravity_sdk import (
        AuthenticationError,
        Credential,
        CredentialProvider,
        PermissionUnavailableError,
        PolicyViolation,
        SqlValidationError,
    )
    from gravity_sdk.credentials import GRAVITY_HOST
    from gravity_sdk import http_runtime as runtime_module
    from gravity_sdk.http_runtime import (
        CONNECTION_POOL_SIZE,
        FALLBACK_CHROME_MAJOR,
        INSIGHT_PROFILE,
        SQL_PROFILE,
        GravityHttpRuntime,
        HostRateLimiter,
        _detect_chrome_major,
        _build_session,
        browser_headers,
    )

from gravity_sdk.errors import RateLimitedError, TransportError
from gravity_sdk.transport import _raise_for_status


NOW = datetime(2026, 8, 8, 8, 0, tzinfo=timezone.utc)


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = dict(headers or {})

    def json(self):
        return self._payload


class QueueSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.lock = threading.Lock()

    def request(self, method, url, **kwargs):
        with self.lock:
            self.calls.append((method, url, kwargs))
            response = self.responses.pop(0)
        return response


class StaticCredentials:
    def __init__(self, token="opaque"):
        self.token = token
        self.refreshes = 0

    def get(self):
        return Credential(self.token)

    def refresh_if_rejected(self, rejected):
        self.refreshes += 1
        self.token = "fresh"
        return Credential(self.token)


def runtime_for(session, **kwargs):
    return GravityHttpRuntime(
        session=session,
        credentials=kwargs.pop("credentials", StaticCredentials()),
        requests_per_second=kwargs.pop("requests_per_second", 100),
        sleeper=kwargs.pop("sleeper", lambda _delay: None),
        random_source=kwargs.pop("random_source", lambda: 0.0),
        interval_jitter_ratio=kwargs.pop("interval_jitter_ratio", 0.0),
        wall_clock=kwargs.pop("wall_clock", lambda: NOW),
        **kwargs,
    )


class GravityHttpRuntimeTests(unittest.TestCase):
    def test_login_transport_failures_remain_retryable_upstream_errors(self):
        invalid_json = FakeResponse(None)
        invalid_json.json = mock.Mock(side_effect=ValueError("truncated"))
        cases = ((FakeResponse({}, 503), TransportError, None),
                 (invalid_json, TransportError, None),
                 (FakeResponse({}, 429, {"Retry-After": "3"}), RateLimitedError, 3000))
        for response, error_type, retry_after in cases:
            with self.subTest(status=response.status_code), tempfile.TemporaryDirectory() as directory:
                provider = CredentialProvider(Path(directory) / ".env.gravity.local",
                    environ={"GRAVITY_USERNAME": "user", "GRAVITY_PASSWORD": "password"}, persist=False)
                runtime_for(QueueSession([response]), credentials=provider, attempts=1)
                with self.assertRaises(error_type) as raised:
                    provider.get(force_refresh=True)
                self.assertEqual(("upstream", True, retry_after), (
                    raised.exception.to_error_detail().category,
                    raised.exception.to_error_detail().retryable,
                    raised.exception.retry_after_ms))
        with self.assertRaises(RateLimitedError) as raised:
            _raise_for_status(429, 3000)
        self.assertEqual(3000, raised.exception.retry_after_ms)

    def test_pool_has_spare_login_connection_and_browser_versions_align(self):
        self.assertEqual(25, CONNECTION_POOL_SIZE)
        session = _build_session()
        adapter = session.get_adapter(GRAVITY_HOST)
        self.assertEqual(25, adapter._pool_maxsize)
        self.assertTrue(adapter._pool_block)

        headers = browser_headers(150)
        self.assertIn("Chrome/150.0.0.0", headers["User-Agent"])
        self.assertIn('"Chromium";v="150"', headers["sec-ch-ua"])
        self.assertIn('"Google Chrome";v="150"', headers["sec-ch-ua"])
        self.assertEqual(runtime_module.ACCEPT_ENCODING, headers["Accept-Encoding"])
        for required in (
            "sec-ch-ua-mobile",
            "sec-ch-ua-platform",
            "Sec-Fetch-Dest",
            "Sec-Fetch-Mode",
            "Sec-Fetch-Site",
            "Accept-Language",
        ):
            self.assertIn(required, headers)
        session.close()

    def test_chrome_detection_has_a_deterministic_no_browser_fallback(self):
        with (
            mock.patch.dict(runtime_module.os.environ, {}, clear=True),
            mock.patch.object(runtime_module.os, "name", "posix"),
        ):
            self.assertEqual(FALLBACK_CHROME_MAJOR, _detect_chrome_major())

    def test_rate_limiter_reserves_under_lock_but_sleeps_concurrently(self):
        limiter = HostRateLimiter(
            clock=lambda: 0.0,
            random_source=lambda: 0.0,
            interval_jitter_ratio=0.0,
        )
        limiter.configure(GRAVITY_HOST, 2)
        # Reserve the immediate first slot so both worker slots need to sleep.
        self.assertEqual(0.0, limiter.acquire(GRAVITY_HOST, lambda _delay: None))
        barrier = threading.Barrier(2)
        entered = []
        entered_lock = threading.Lock()

        def sleep(delay):
            with entered_lock:
                entered.append(delay)
            barrier.wait(timeout=2)

        with ThreadPoolExecutor(max_workers=2) as pool:
            delays = list(pool.map(lambda _: limiter.acquire(GRAVITY_HOST, sleep), range(2)))

        self.assertEqual([0.5, 1.0], sorted(delays))
        self.assertEqual([0.5, 1.0], sorted(entered))

    def test_waiting_rate_slot_rechecks_a_late_retry_after_cooldown(self):
        now = [0.0]
        initial_sleep_entered = threading.Event()
        release_initial_sleep = threading.Event()
        delays: list[float] = []
        delay_lock = threading.Lock()

        limiter = HostRateLimiter(
            clock=lambda: now[0],
            random_source=lambda: 0.0,
            interval_jitter_ratio=0.0,
        )
        limiter.configure(GRAVITY_HOST, 10)
        self.assertEqual(0.0, limiter.acquire(GRAVITY_HOST, lambda _delay: None))

        def sleep(delay: float) -> None:
            with delay_lock:
                delays.append(delay)
                first_sleep = len(delays) == 1
            if first_sleep:
                initial_sleep_entered.set()
                self.assertTrue(release_initial_sleep.wait(30))
            now[0] += delay

        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(limiter.acquire, GRAVITY_HOST, sleep)
            try:
                self.assertTrue(initial_sleep_entered.wait(30))
                limiter.defer(GRAVITY_HOST, 3.0)
                release_initial_sleep.set()
                total_delay = waiting.result(timeout=30)
            finally:
                release_initial_sleep.set()

        self.assertGreaterEqual(total_delay, 3.0)
        self.assertEqual(2, len(delays))
        self.assertGreaterEqual(sum(delays), 3.0)

    def test_two_runtimes_share_one_host_bucket(self):
        now = [0.0]
        sleeps = []

        def sleep(delay):
            sleeps.append(delay)
            now[0] += delay

        limiter = HostRateLimiter(
            clock=lambda: now[0],
            random_source=lambda: 0.0,
            interval_jitter_ratio=0.0,
        )
        insight_session = QueueSession([FakeResponse({"code": 0})])
        sql_session = QueueSession([FakeResponse([])])
        common = {
            "credentials": StaticCredentials(),
            "limiter": limiter,
            "requests_per_second": 2,
            "sleeper": sleep,
            "random_source": lambda: 0.0,
            "interval_jitter_ratio": 0.0,
            "rate_clock": lambda: now[0],
            "wall_clock": lambda: NOW,
        }
        insight = GravityHttpRuntime(session=insight_session, **common)
        sql = GravityHttpRuntime(session=sql_session, **common)

        insight.request(
            SQL_PROFILE,
            "POST",
            "/custom_sql/api/sql/execute",
            json_body={"sql": "SELECT 1", "tabId": "1"},
        )
        sql.request(
            SQL_PROFILE,
            "POST",
            "/custom_sql/api/sql/execute",
            json_body={"sql": "SELECT 1", "tabId": "1"},
        )

        self.assertEqual([0.5], sleeps)
        self.assertEqual(
            "https://bi.gravity-engine.com",
            insight_session.calls[0][2]["headers"]["Origin"],
        )
        self.assertEqual(
            "https://bi.gravity-engine.com",
            sql_session.calls[0][2]["headers"]["Origin"],
        )

    def test_public_runtime_cannot_bypass_insight_manifest_policy(self):
        session = QueueSession([])
        runtime = runtime_for(session)
        with self.assertRaisesRegex(PolicyViolation, "manifest-authorized"):
            runtime.request(
                INSIGHT_PROFILE,
                "GET",
                "/report/api/v3/example/list/",
            )
        self.assertEqual([], session.calls)

    def test_runtime_does_not_expose_composable_raw_http_state(self):
        session = QueueSession([])
        runtime = runtime_for(session)
        for name in (
            "session",
            "credentials",
            "requester",
            "_requester",
            "limiter",
        ):
            with self.subTest(name=name):
                self.assertFalse(hasattr(runtime, name))
                with self.assertRaises(AttributeError):
                    getattr(runtime, name)
        self.assertEqual([], session.calls)

    def test_six_requests_can_reach_the_session_concurrently(self):
        barrier = threading.Barrier(6)

        class ConcurrentSession:
            def __init__(self):
                self.active = 0
                self.max_active = 0
                self.lock = threading.Lock()

            def request(self, _method, _url, **_kwargs):
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                barrier.wait(timeout=3)
                with self.lock:
                    self.active -= 1
                return FakeResponse([])

        session = ConcurrentSession()
        runtime = GravityHttpRuntime(
            session=session,
            credentials=StaticCredentials(),
            governor=AdaptiveRequestGovernor(
                mode=STATIC,
                total_capacity=7,
                business_capacity=6,
                sql_capacity=6,
            ),
            limiter=HostRateLimiter(
                clock=lambda: 0.0,
                random_source=lambda: 0.0,
                interval_jitter_ratio=0.0,
            ),
            requests_per_second=100,
            sleeper=lambda _delay: None,
            random_source=lambda: 0.0,
            wall_clock=lambda: NOW,
        )

        def execute(index):
            return runtime.request(
                SQL_PROFILE,
                "POST",
                "/custom_sql/api/sql/execute",
                json_body={"sql": f"SELECT {index}", "tabId": "1"},
            )

        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(execute, range(6)))
        self.assertEqual(6, session.max_active)
        self.assertTrue(all(response.status_code == 200 for response in responses))

    def test_six_business_requests_leave_the_seventh_pool_slot_for_login(self):
        six_business_entered = threading.Event()
        login_entered = threading.Event()
        release_business = threading.Event()

        class PoolProbeSession:
            def __init__(self) -> None:
                self.lock = threading.Lock()
                self.business_started = 0
                self.active = 0
                self.max_active = 0

            def request(self, _method, url, **_kwargs):
                is_login = url.endswith("/user_login/v2/")
                with self.lock:
                    self.active += 1
                    self.max_active = max(self.max_active, self.active)
                    if is_login:
                        login_entered.set()
                    else:
                        self.business_started += 1
                        if self.business_started == 6:
                            six_business_entered.set()
                try:
                    if is_login:
                        return FakeResponse(
                            {
                                "code": 0,
                                "data": {"user": {"Authorization": "fresh-token"}},
                            }
                        )
                    if not release_business.wait(3):
                        raise AssertionError("business request was not released")
                    return FakeResponse([])
                finally:
                    with self.lock:
                        self.active -= 1

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.gravity.local"
            path.write_text(
                "GRAVITY_USERNAME=user\n"
                "GRAVITY_PASSWORD=password\n"
                "GRAVITY_AUTH_TOKEN=old-token\n",
                encoding="utf-8",
            )
            provider = CredentialProvider(path, environ={}, persist=False)
            session = PoolProbeSession()
            runtime = GravityHttpRuntime(
                session=session,
                credentials=provider,
                governor=AdaptiveRequestGovernor(
                    mode=STATIC,
                    total_capacity=7,
                    business_capacity=6,
                    sql_capacity=6,
                ),
                requests_per_second=100,
                sleeper=lambda _delay: None,
                random_source=lambda: 0.0,
                interval_jitter_ratio=0.0,
                wall_clock=lambda: NOW,
            )

            def execute(index: int):
                return runtime.request(
                    SQL_PROFILE,
                    "POST",
                    "/custom_sql/api/sql/execute",
                    json_body={"sql": f"SELECT {index}", "tabId": "1"},
                )

            with ThreadPoolExecutor(max_workers=8) as pool:
                business = [pool.submit(execute, index) for index in range(6)]
                self.assertTrue(six_business_entered.wait(3))
                seventh = pool.submit(execute, 7)
                login = pool.submit(provider.refresh)
                self.assertTrue(login_entered.wait(3))
                self.assertEqual(6, session.business_started)
                self.assertEqual(7, session.max_active)
                release_business.set()
                self.assertTrue(login.result(timeout=3).token)
                self.assertEqual(200, seventh.result(timeout=3).status_code)
                self.assertTrue(all(item.result(timeout=3).status_code == 200 for item in business))

        self.assertEqual(7, session.business_started)

    def test_runtime_sql_limit_is_shared_across_runtime_instances(self):
        lock = threading.Lock()
        rendezvous = threading.Barrier(2, timeout=20)
        active = 0
        max_active = 0

        class SqlConcurrencySession:
            def request(self, _method, _url, **_kwargs):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                try:
                    try:
                        rendezvous.wait()
                    except threading.BrokenBarrierError as exc:
                        raise AssertionError(
                            "shared SQL limit rendezvous timed out or broke after "
                            f"20s: active={active}, peak={max_active}"
                        ) from exc
                    return FakeResponse([])
                finally:
                    with lock:
                        active -= 1

        governor = AdaptiveRequestGovernor(mode=STATIC)
        runtimes = tuple(
            GravityHttpRuntime(
                session=SqlConcurrencySession(),
                credentials=StaticCredentials(),
                governor=governor,
                requests_per_second=100,
                sleeper=lambda _delay: None,
                random_source=lambda: 0.0,
                interval_jitter_ratio=0.0,
                wall_clock=lambda: NOW,
            )
            for _ in range(2)
        )

        def execute(index: int):
            return runtimes[index % 2].request(
                SQL_PROFILE,
                "POST",
                "/custom_sql/api/sql/execute",
                json_body={"sql": f"SELECT {index}", "tabId": "1"},
            )

        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(execute, range(8)))

        self.assertTrue(all(response.status_code == 200 for response in responses))
        self.assertEqual(2, max_active)

    def test_sql_body_is_exactly_constrained_before_network(self):
        session = QueueSession([])
        runtime = runtime_for(session)
        invalid = (
            None,
            {"sql": "SELECT 1"},
            {"sql": "", "tabId": "1"},
            {"sql": "SELECT 1", "tabId": 1},
            {"sql": "SELECT 1", "tabId": "1", "url": "https://invalid"},
        )
        for body in invalid:
            with self.subTest(body=body), self.assertRaises(SqlValidationError):
                runtime.request(
                    SQL_PROFILE,
                    "POST",
                    "/custom_sql/api/sql/execute",
                    json_body=body,
                )
        with self.assertRaises(SqlValidationError):
            runtime.request(
                SQL_PROFILE,
                "POST",
                "/custom_sql/api/sql/execute",
                params={"host": "invalid"},
                json_body={"sql": "SELECT 1", "tabId": "1"},
            )
        self.assertEqual([], session.calls)

    def test_sql_top_level_list_payload_is_preserved(self):
        rows = [{"one": 1}]
        runtime = runtime_for(QueueSession([FakeResponse(rows)]))
        response = runtime.request(
            SQL_PROFILE,
            "POST",
            "/custom_sql/api/sql/execute",
            json_body={"sql": "SELECT 1", "tabId": "1"},
        )
        self.assertEqual(rows, response.payload)

    def test_second_auth_rejection_uses_typed_errors(self):
        credentials = StaticCredentials()
        runtime = runtime_for(
            QueueSession([FakeResponse({}, 401), FakeResponse({}, 401)]),
            credentials=credentials,
            attempts=1,
        )
        with self.assertRaises(AuthenticationError):
            runtime.request(
                SQL_PROFILE,
                "POST",
                "/custom_sql/api/sql/execute",
                json_body={"sql": "SELECT 1", "tabId": "1"},
            )
        self.assertEqual(1, credentials.refreshes)

        credentials = StaticCredentials()
        runtime = runtime_for(
            QueueSession([FakeResponse({}, 403), FakeResponse({}, 403)]),
            credentials=credentials,
            attempts=1,
        )
        with self.assertRaises(PermissionUnavailableError):
            runtime.request(
                SQL_PROFILE,
                "POST",
                "/custom_sql/api/sql/execute",
                json_body={"sql": "SELECT 1", "tabId": "1"},
            )
        self.assertEqual(1, credentials.refreshes)

    def test_staggered_old_token_rejections_only_login_once(self):
        calls = 0

        def login(_username, _password):
            nonlocal calls
            calls += 1
            return {
                "code": 0,
                "data": {"user": {"Authorization": f"fresh-{calls}"}},
            }

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.gravity.local"
            path.write_text(
                "GRAVITY_USERNAME=user\n"
                "GRAVITY_PASSWORD=password\n"
                "GRAVITY_AUTH_TOKEN=old\n",
                encoding="utf-8",
            )
            provider = CredentialProvider(
                path,
                environ={},
                login=login,
                clock=lambda: NOW,
                persist=False,
            )
            old = provider.get()
            first = provider.refresh_if_rejected(old)
            late = provider.refresh_if_rejected(old)
        self.assertEqual(1, calls)
        self.assertEqual(first.token, late.token)

    def test_login_cookie_is_carried_by_the_same_session(self):
        class CookieSession(requests.Session):
            def __init__(self):
                super().__init__()
                self.prepared = []

            def request(self, method, url, **kwargs):
                request = requests.Request(
                    method,
                    url,
                    headers=kwargs.get("headers"),
                    params=kwargs.get("params"),
                    json=kwargs.get("json"),
                )
                prepared = self.prepare_request(request)
                self.prepared.append(prepared)
                if url.endswith("/user_login/v2/"):
                    self.cookies.set(
                        "gravity_sticky",
                        "session-value",
                        domain="api-insight.gravity-engine.com",
                        path="/",
                    )
                    return FakeResponse(
                        {
                            "code": 0,
                            "data": {"user": {"Authorization": "fresh"}},
                        }
                    )
                return FakeResponse([])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env.gravity.local"
            path.write_text(
                "GRAVITY_USERNAME=user\nGRAVITY_PASSWORD=password\n",
                encoding="utf-8",
            )
            session = CookieSession()
            runtime = GravityHttpRuntime(
                env_path=path,
                session=session,
                requests_per_second=100,
                sleeper=lambda _delay: None,
                random_source=lambda: 0.0,
                interval_jitter_ratio=0.0,
                wall_clock=lambda: NOW,
                persist_credentials=False,
                environ={},
            )
            response = runtime.request(
                SQL_PROFILE,
                "POST",
                "/custom_sql/api/sql/execute",
                json_body={"sql": "SELECT 1", "tabId": "1"},
            )
            session.close()

        self.assertEqual([], response.payload)
        self.assertEqual(2, len(session.prepared))
        self.assertNotIn("Cookie", session.prepared[0].headers)
        self.assertEqual(
            "gravity_sticky=session-value",
            session.prepared[1].headers.get("Cookie"),
        )

    def test_retry_backoff_and_retry_after_have_positive_jitter(self):
        now = [0.0]
        sleeps = []

        def sleep(delay):
            sleeps.append(delay)
            now[0] += delay

        limiter = HostRateLimiter(
            clock=lambda: now[0],
            random_source=lambda: 0.0,
            interval_jitter_ratio=0.0,
        )
        session = QueueSession(
            [
                FakeResponse({}, 503),
                FakeResponse({}, 429, {"Retry-After": "3"}),
                FakeResponse([]),
            ]
        )
        runtime = GravityHttpRuntime(
            session=session,
            credentials=StaticCredentials(),
            limiter=limiter,
            requests_per_second=100,
            attempts=3,
            sleeper=sleep,
            rate_clock=lambda: now[0],
            random_source=lambda: 0.5,
            interval_jitter_ratio=0.0,
            wall_clock=lambda: NOW,
        )
        runtime.request(
            SQL_PROFILE,
            "POST",
            "/custom_sql/api/sql/execute",
            json_body={"sql": "SELECT 1", "tabId": "1"},
        )
        # First retry is 2 seconds plus 10% jitter. Retry-After is never shortened.
        self.assertIn(2.2, sleeps)
        self.assertTrue(any(delay >= 3.0 for delay in sleeps))


if __name__ == "__main__":
    unittest.main()
