"""Conservative extraction of the affirmative side of intent contrasts."""

from __future__ import annotations

import re


_ENGLISH_REFRAME = re.compile(
    r"^(?:do\s+not|don['’]?t|not|rather\s+than|instead\s+of)\b.+?"
    r"(?:\bbut\b|[,;])\s*(?P<positive>.+)$",
    re.IGNORECASE,
)
_CHINESE_PROHIBITIVE = r"别(?!(?:人|的|样|处|称|名))"
# 「不是」 is a prohibitive only outside 「是不是」 / 「而不是」.
_CHINESE_NOT = r"(?<![而是])不是"
_CHINESE_REFRAME = re.compile(
    r"^(?:不要|" + _CHINESE_NOT + r"|并非|" + _CHINESE_PROHIBITIVE + r"|不查|不看|不读取|不执行|不运行|不做).+?"
    r"(?:而是|只要|只看|只查|改为|，(?:要|看|查)|,\s*(?:要|看|查))(?P<positive>.+)$",
)
_CHINESE_POSITIVE_AFTER_REJECT = re.compile(
    r"^(?:不要|" + _CHINESE_NOT + r"|并非|" + _CHINESE_PROHIBITIVE + r")(?P<rejected>.+?)(?:[，,；;。]|\s+)"
    r"(?:我要|只要|只看|只查|只告诉我|改为)(?P<positive>.+)$",
)
_CHINESE_POSITIVE_AFTER_SEMI = re.compile(
    r"^(?:不要|" + _CHINESE_NOT + r"|并非|" + _CHINESE_PROHIBITIVE + r")(?P<rejected>.+?)[；;]"
    r"(?P<positive>.+)$",
)
_NEGATED_TAIL = re.compile(
    r"(?:\s*[,;.!?，；。！？]\s*)?(?:"
    r"\brather\s+than\b|\binstead\s+of\b|"
    r"\bdo\s+not\b|\bdon['’]?t\b|\bnot\b|"
    r"不要|不只是|" + _CHINESE_NOT + r"|并非|而非|不按|不读取|不执行|不运行|不重放|不做|"
    r"不跑|不查|不看|不声称|无需|无须|不需要|不必|"
    r"(?<![一-龥])" + _CHINESE_PROHIBITIVE + r"(?:给|再|要|查|看|跑|读|做)?)",
    re.IGNORECASE,
)


def affirmative_intent_text(query: str) -> str:
    """Return only an explicit positive request, never infer one from negation."""

    selected = " ".join(str(query or "").strip().casefold().split())
    if not selected:
        return ""
    for pattern in (
        _ENGLISH_REFRAME,
        _CHINESE_REFRAME,
        _CHINESE_POSITIVE_AFTER_REJECT,
        _CHINESE_POSITIVE_AFTER_SEMI,
    ):
        match = pattern.match(selected)
        if match is not None:
            return match.group("positive").strip(" ,;.!?，；。！？")
    match = _NEGATED_TAIL.search(selected)
    if match is None:
        return selected
    prefix = selected[:match.start()].strip(" ,;.!?，；。！？")
    return prefix


__all__ = ["affirmative_intent_text"]
