"""Fill Agent cards from a unique closed relative-date phrase."""

from __future__ import annotations

from typing import Any

from .errors import InputValidationError
from .relative_dates import (
    RelativeDateWindow,
    extract_relative_expression,
    parse_date_token,
    parse_date_window,
)


def fill_agent_relative_dates(
    card: dict[str, Any],
    query: str,
    *,
    workspace: Any | None = None,
    now: Any | None = None,
) -> dict[str, Any]:
    """Fill start/end/date on a card when the query names a unique window."""

    extracted = extract_relative_expression(query)
    if extracted is None or not _card_accepts_dates(card):
        return card
    field = "date" if _wants_single_day(card) else "start/end"
    try:
        window = (
            parse_date_token(extracted, field=field, workspace=workspace, now=now)
            if field == "date"
            else parse_date_window(
                extracted, extracted, field=field, workspace=workspace, now=now
            )
        )
    except InputValidationError:
        return card
    if field == "date" and window.start != window.end:
        return card
    selected = dict(card)
    if field == "date":
        selected["date"] = window.start
    else:
        selected["start"] = window.start
        selected["end"] = window.end
    selected["resolved_date_window"] = window.to_dict()
    missing = selected.get("missing_inputs")
    if isinstance(missing, list):
        drop = {"date"} if field == "date" else {"start", "end"}
        selected["missing_inputs"] = [
            item for item in missing if str(item) not in drop
        ]
    template = selected.get("input_template")
    if isinstance(template, dict):
        selected["input_template"] = _fill_template(template, window, field)
    return selected


def _fill_template(
    template: dict[str, Any], window: RelativeDateWindow, field: str
) -> dict[str, Any]:
    rendered = dict(template)
    if field == "date":
        rendered["date"] = window.start
        return rendered
    rendered["start"] = window.start
    rendered["end"] = window.end
    return rendered


def _card_accepts_dates(card: dict[str, Any]) -> bool:
    return bool(_card_date_names(card) & {"start", "end", "date"})


def _card_date_names(card: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for key in ("missing_inputs", "required_inputs"):
        value = card.get(key)
        if isinstance(value, list):
            names.update(str(item) for item in value)
    template = card.get("input_template")
    if isinstance(template, dict):
        names.update(str(key) for key in template)
    return names


def _wants_single_day(card: dict[str, Any]) -> bool:
    names = _card_date_names(card)
    return "date" in names and "start" not in names


__all__ = ["fill_agent_relative_dates"]
