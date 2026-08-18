from __future__ import annotations

import argparse
import unittest
from datetime import datetime, timezone

from gravity_sdk.errors import InputValidationError
from gravity_sdk.relative_date_agent import fill_agent_relative_dates
from gravity_sdk.relative_dates import (
    DEFAULT_TIMEZONE,
    apply_relative_dates,
    attach_resolved_window,
    extract_relative_expression,
    parse_date_token,
    parse_date_window,
)


NOW = datetime(2026, 8, 18, 15, 30, tzinfo=timezone.utc)


class RelativeDateParserTests(unittest.TestCase):
    def test_iso_and_named_days_are_symmetric(self) -> None:
        iso = parse_date_window("2026-08-17", "2026-08-17", now=NOW)
        self.assertEqual(("2026-08-17", "2026-08-17", "iso"), (iso.start, iso.end, iso.kind))
        cases = (
            ("昨天", "yesterday", "2026-08-17", "2026-08-17"),
            ("今天", "today", "2026-08-18", "2026-08-18"),
            ("前天", "day before yesterday", "2026-08-16", "2026-08-16"),
            ("最近7天", "last 7 days", "2026-08-12", "2026-08-18"),
            ("过去7天", "past 7 days", "2026-08-12", "2026-08-18"),
            ("本周", "this week", "2026-08-17", "2026-08-23"),
            ("上周", "last week", "2026-08-10", "2026-08-16"),
            ("本月", "this month", "2026-08-01", "2026-08-18"),
            ("上月", "last month", "2026-07-01", "2026-07-31"),
        )
        for chinese, english, start, end in cases:
            with self.subTest(chinese=chinese):
                left = parse_date_token(chinese, field="start", now=NOW)
                right = parse_date_token(english, field="start", now=NOW)
                self.assertEqual((start, end), (left.start, left.end))
                self.assertEqual((left.start, left.end, left.timezone), (
                    right.start, right.end, right.timezone,
                ))
                self.assertEqual(DEFAULT_TIMEZONE, left.timezone)
                self.assertIn("→", left.to_dict()["display"])
                self.assertIn(left.timezone, left.to_dict()["display"])

    def test_timezone_is_explicit_and_naive_now_is_rejected(self) -> None:
        utc = parse_date_token("yesterday", field="date", timezone_name="UTC", now=NOW)
        self.assertEqual(("2026-08-17", "explicit", "UTC"), (
            utc.start, utc.timezone_source, utc.timezone,
        ))
        late = datetime(2026, 8, 18, 16, 30, tzinfo=timezone.utc)
        shanghai = parse_date_token("today", field="date", now=late)
        utc_today = parse_date_token(
            "today", field="date", timezone_name="UTC", now=late,
        )
        self.assertEqual("2026-08-19", shanghai.start)
        self.assertEqual("2026-08-18", utc_today.start)
        with self.assertRaises(InputValidationError) as raised:
            parse_date_token(
                "yesterday", field="date", now=datetime(2026, 8, 18, 15, 30),
            )
        self.assertEqual("now", raised.exception.field)

    def test_ambiguous_phrases_fail_closed(self) -> None:
        for phrase in ("最近一段时间", "前阵子", "recently", "last few days"):
            with self.subTest(phrase=phrase):
                with self.assertRaises(InputValidationError) as raised:
                    parse_date_token(phrase, field="start/end", now=NOW)
                self.assertEqual("start/end", raised.exception.field)
                self.assertIn("ambiguous", str(raised.exception))
                self.assertIn("YYYY-MM-DD", raised.exception.next_action or "")
                with self.assertRaises(InputValidationError):
                    extract_relative_expression(f"查一下{phrase}的注册")

    def test_cli_resolves_and_echoes_without_guessing_iso_garbage(self) -> None:
        args = argparse.Namespace(start="yesterday", end="yesterday", timezone=None)
        window = apply_relative_dates(args, now=NOW)
        self.assertEqual(("2026-08-17", "2026-08-17"), (args.start, args.end))
        self.assertIsNotNone(window)
        echoed = attach_resolved_window({"ok": True}, window)
        self.assertEqual(
            "昨天 → 2026-08-17..2026-08-17 (Asia/Shanghai)".replace("昨天", window.expression),
            echoed["resolved_date_window"]["display"],
        )
        leftover = argparse.Namespace(start="bad", end="2026-08-02")
        self.assertIsNone(apply_relative_dates(leftover, now=NOW))
        self.assertEqual("bad", leftover.start)

    def test_cli_parser_resolves_yesterday_and_rejects_recently(self) -> None:
        from gravity_sdk import cli

        parsed = cli.build_parser().parse_args([
            "attribution", "performance", "--app", "1",
            "--start", "yesterday", "--end", "yesterday",
        ])
        self.assertRegex(parsed.start, r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(parsed.start, parsed.end)
        self.assertEqual("Asia/Shanghai", parsed.resolved_date_window["timezone"])
        self.assertIn(parsed.start, parsed.resolved_date_window["display"])
        with self.assertRaises(InputValidationError) as raised:
            cli.build_parser().parse_args([
                "attribution", "performance", "--app", "1",
                "--start", "最近一段时间", "--end", "最近一段时间",
            ])
        self.assertEqual("start/end", raised.exception.field)
        self.assertIn("ambiguous", str(raised.exception))
        self.assertIn("YYYY-MM-DD", raised.exception.next_action or "")

    def test_agent_fills_a_unique_window_and_leaves_app_alone(self) -> None:
        card = fill_agent_relative_dates(
            {
                "kind": "composite",
                "required_inputs": ["app", "start", "end"],
                "missing_inputs": ["app", "start", "end"],
                "input_template": {
                    "app": "<app>",
                    "start": "<start:YYYY-MM-DD>",
                    "end": "<end:YYYY-MM-DD>",
                },
            },
            "昨天注册多少",
            now=NOW,
        )
        self.assertEqual(["app"], card["missing_inputs"])
        self.assertEqual("2026-08-17", card["start"])
        self.assertEqual("<app>", card["input_template"]["app"])
        english = fill_agent_relative_dates(
            {"kind": "composite", "missing_inputs": ["start", "end"]},
            "what did we get yesterday",
            now=NOW,
        )
        self.assertEqual("2026-08-17", english["start"])
        self.assertEqual([], english["missing_inputs"])
        empty = fill_agent_relative_dates(
            {"missing_inputs": ["start", "end"]}, "注册多少", now=NOW,
        )
        self.assertEqual(["start", "end"], empty["missing_inputs"])
