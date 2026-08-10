from __future__ import annotations

import re
import threading
import unittest

from gravity_sdk.sql.export import GravityExportError, fetch_all_rows_with_audit


_OFFSET_RE = re.compile(r"\bOFFSET\s+(\d+)\s*$", re.IGNORECASE)


def _offset(sql: str) -> int:
    match = _OFFSET_RE.search(sql)
    if match is None:
        raise AssertionError("paged SQL did not contain a terminal OFFSET")
    return int(match.group(1))


class _ScriptedClient:
    def __init__(
        self,
        pages: dict[int, list[dict] | BaseException],
        *,
        synchronize_offsets: set[int] | None = None,
    ) -> None:
        self._pages = pages
        self._lock = threading.Lock()
        self._synchronize_offsets = synchronize_offsets or set()
        self._barrier = threading.Barrier(len(self._synchronize_offsets)) if self._synchronize_offsets else None
        self.calls: list[int] = []

    def execute_sql(self, sql: str) -> list[dict]:
        offset = _offset(sql)
        with self._lock:
            self.calls.append(offset)
        if offset in self._synchronize_offsets and self._barrier is not None:
            self._barrier.wait(timeout=5)
        value = self._pages.get(offset, [])
        if isinstance(value, BaseException):
            raise value
        return value


class _ConcurrentClient:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._barrier = threading.Barrier(2)
        self.calls: list[int] = []
        self.active = 0
        self.max_active = 0
        self.stage_active = {1: 0, 2: 0}
        self.stage_max_active = {1: 0, 2: 0}

    def execute_sql(self, sql: str) -> list[dict]:
        page_index = _offset(sql)
        stage = 1 if page_index == 0 else 2
        with self._lock:
            self.calls.append(page_index)
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.stage_active[stage] += 1
            self.stage_max_active[stage] = max(self.stage_max_active[stage], self.stage_active[stage])
        try:
            if stage > 1:
                self._barrier.wait(timeout=5)
            if page_index == 3:
                return []
            return [{"user_id": f"u{page_index}"}]
        finally:
            with self._lock:
                self.active -= 1
                self.stage_active[stage] -= 1


class GravityExportConcurrencyTests(unittest.TestCase):
    def test_first_short_page_does_not_start_speculative_requests(self) -> None:
        client = _ScriptedClient({0: [{"user_id": "u1"}]})

        rows, audit = fetch_all_rows_with_audit(client, "SELECT user_id FROM source", page_size=2)

        self.assertEqual([{"user_id": "u1"}], rows)
        self.assertEqual([0], client.calls)
        self.assertEqual([0], [page.page_index for page in audit.pages])

    def test_two_page_export_only_speculates_one_extra_page(self) -> None:
        poison = [{"user_id": "must-not-be-included"}, {"user_id": "also-not-included"}]
        client = _ScriptedClient(
            {
                0: [{"user_id": "u0"}, {"user_id": "u1"}],
                2: [{"user_id": "u2"}],
                4: poison,
            },
            synchronize_offsets={2, 4},
        )

        rows, audit = fetch_all_rows_with_audit(client, "SELECT user_id FROM source", page_size=2)

        self.assertEqual(["u0", "u1", "u2"], [row["user_id"] for row in rows])
        self.assertLessEqual(len(client.calls), 3)
        self.assertEqual([0, 2, 4], sorted(client.calls))
        self.assertEqual([0, 1], [page.page_index for page in audit.pages])
        self.assertEqual(3, audit.total_rows)

    def test_windows_ramp_to_two_with_real_concurrency_and_preserve_order(self) -> None:
        client = _ConcurrentClient()

        rows, audit = fetch_all_rows_with_audit(client, "SELECT user_id FROM source", page_size=1)

        self.assertEqual([f"u{index}" for index in range(3)], [row["user_id"] for row in rows])
        self.assertEqual(list(range(4)), [page.page_index for page in audit.pages])
        self.assertEqual(list(range(5)), sorted(client.calls))
        self.assertEqual(2, client.max_active)
        self.assertEqual({1: 1, 2: 2}, client.stage_max_active)

    def test_failure_before_terminal_page_is_layered(self) -> None:
        client = _ScriptedClient(
            {
                0: [{"user_id": "u0"}],
                1: RuntimeError("upstream detail must remain in the cause"),
                2: [],
            }
        )

        with self.assertRaisesRegex(GravityExportError, r"export: page=1 request failed"):
            fetch_all_rows_with_audit(client, "SELECT secret FROM source", page_size=1)

        self.assertTrue(issubclass(GravityExportError, RuntimeError))

    def test_concurrency_hard_limit_is_enforced_before_network(self) -> None:
        for invalid in (0, 3, True):
            with self.subTest(invalid=invalid):
                client = _ScriptedClient({})
                with self.assertRaisesRegex(ValueError, "between 1 and 2"):
                    fetch_all_rows_with_audit(
                        client,
                        "SELECT user_id FROM source",
                        page_size=1,
                        max_concurrency=invalid,
                    )
                self.assertEqual([], client.calls)


if __name__ == "__main__":
    unittest.main()
