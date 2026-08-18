"""Closed Chinese/English relative-date phrases. No host timezone."""

from __future__ import annotations

import re
from typing import Any

from .actionable_error_values import actual_value
from .errors import InputValidationError


ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NAMED_OFFSETS = {
    "today": 0,
    "今天": 0,
    "yesterday": 1,
    "昨天": 1,
    "day before yesterday": 2,
    "前天": 2,
}
RANGE_PHRASES = {
    "this week": "this_week",
    "本周": "this_week",
    "last week": "last_week",
    "上周": "last_week",
    "this month": "this_month",
    "本月": "this_month",
    "last month": "last_month",
    "上月": "last_month",
}
AMBIGUOUS = (
    "最近一段时间",
    "前阵子",
    "一段时间",
    "最近几天",
    "过去几天",
    "the other day",
    "recently",
    "lately",
    "a while ago",
    "some time ago",
    "last few days",
    "past few days",
    "the last few days",
    "the past few days",
)
CHINESE_ROLLING = re.compile(r"(最近|过去)(\d{1,3})(天|日)")
ENGLISH_ROLLING = re.compile(r"\b(last|past)\s+(\d{1,3})\s+days?\b")
REMEDY = (
    "Pass an explicit YYYY-MM-DD window, or one of the closed relative "
    "phrases (yesterday/today/前天, last N days/过去 N 天, this/last "
    "week or month), then retry."
)
ORDERED_PHRASES = tuple(
    sorted((*NAMED_OFFSETS, *RANGE_PHRASES), key=len, reverse=True)
)


def reject(value: Any, field: str) -> InputValidationError:
    return InputValidationError(
        f"actual value: {actual_value(value)}; "
        "allowed format: YYYY-MM-DD or a closed relative phrase; "
        "ambiguous windows are not guessed",
        field=field,
        next_action=REMEDY,
    )


def phrase_present(folded: str, compact: str, phrase: str) -> bool:
    if phrase.isascii():
        return (
            re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", folded)
            is not None
        )
    return phrase in compact


def match_rolling(text: str) -> tuple[str, int, str] | None:
    compact = "".join(text.split())
    chinese = CHINESE_ROLLING.fullmatch(compact)
    if chinese is not None:
        kind = "last_n_days" if chinese.group(1) == "最近" else "past_n_days"
        return f"{chinese.group(1)}{chinese.group(2)}天", int(chinese.group(2)), kind
    english = ENGLISH_ROLLING.fullmatch(text.casefold().strip())
    if english is None:
        return None
    count = int(english.group(2))
    unit = "day" if count == 1 else "days"
    return f"{english.group(1)} {count} {unit}", count, f"{english.group(1)}_n_days"


def extract_rolling(compact: str, folded: str) -> str | None:
    chinese = CHINESE_ROLLING.search(compact)
    if chinese is not None:
        return f"{chinese.group(1)}{chinese.group(2)}天"
    english = ENGLISH_ROLLING.search(folded)
    if english is None:
        return None
    count = int(english.group(2))
    unit = "day" if count == 1 else "days"
    return f"{english.group(1)} {count} {unit}"


def classify_token(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        return "other"
    text = " ".join(value.strip().split())
    if ISO_DATE.fullmatch(text):
        return "iso"
    if _exact_closed_phrase(text) is not None or match_rolling(text) is not None:
        return "relative"
    folded = text.casefold()
    joined = "".join(text.split())
    if any(
        (phrase.isascii() and phrase == folded)
        or (not phrase.isascii() and phrase == joined)
        for phrase in AMBIGUOUS
    ):
        return "relative"
    return "other"


def normalize_phrase(value: str) -> str:
    compact = " ".join(value.strip().split())
    folded = compact.casefold()
    joined = "".join(compact.split())
    for phrase in AMBIGUOUS:
        if phrase.isascii() and phrase == folded:
            raise InputValidationError(
                f"actual value: {actual_value(compact)}; "
                "allowed format: YYYY-MM-DD or a closed relative phrase; "
                "ambiguous windows are not guessed",
                field="start/end",
                next_action=REMEDY,
            )
        if not phrase.isascii() and phrase == joined:
            raise InputValidationError(
                f"actual value: {actual_value(compact)}; "
                "allowed format: YYYY-MM-DD or a closed relative phrase; "
                "ambiguous windows are not guessed",
                field="start/end",
                next_action=REMEDY,
            )
    named = _exact_closed_phrase(compact)
    if named is not None:
        return named
    rolling = match_rolling(compact)
    return rolling[0] if rolling is not None else compact


def _exact_closed_phrase(text: str) -> str | None:
    folded = text.casefold()
    joined = "".join(text.split())
    for key in (*NAMED_OFFSETS, *RANGE_PHRASES):
        if key.isascii() and key == folded:
            return key
        if not key.isascii() and key == joined:
            return key
    return None


__all__ = [
    "AMBIGUOUS",
    "ISO_DATE",
    "NAMED_OFFSETS",
    "ORDERED_PHRASES",
    "RANGE_PHRASES",
    "REMEDY",
    "classify_token",
    "extract_rolling",
    "match_rolling",
    "normalize_phrase",
    "phrase_present",
    "reject",
]
