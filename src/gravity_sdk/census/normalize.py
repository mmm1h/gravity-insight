from __future__ import annotations

import bisect
import re
from dataclasses import dataclass
from urllib.parse import urlsplit


_DYNAMIC_TEMPLATE = re.compile(r"\$\{\s*([^}]+?)\s*\}")
_DYNAMIC_COLON = re.compile(r"(?<=/):([A-Za-z_$][\w$-]*)")
_DYNAMIC_BRACE = re.compile(r"\{\s*([^{}]+?)\s*\}")
_JS_ESCAPE = re.compile(r"\\(?:u\{([0-9a-fA-F]+)\}|u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2}))")
_CHINESE_STRING = re.compile(
    r"['\"`](?P<value>(?:\\.|[^'\"`]){0,120}[\u3400-\u9fff](?:\\.|[^'\"`]){0,120})['\"`]"
)


@dataclass(frozen=True)
class _StringToken:
    quote: str
    value: str
    start_offset: int
    end_offset: int

    def group(self, name: str) -> str:
        if name == "quote":
            return self.quote
        if name == "value":
            return self.value
        raise IndexError(name)

    def start(self) -> int:
        return self.start_offset

    def end(self) -> int:
        return self.end_offset


def _iter_js_strings(text: str):
    index = 0
    length = len(text)
    while index < length:
        quote = text[index]
        if quote not in "'\"`":
            index += 1
            continue
        start = index
        index += 1
        value_start = index
        while index < length:
            char = text[index]
            if char == "\\":
                index += 2
                continue
            if char == quote:
                yield _StringToken(quote, text[value_start:index], start, index + 1)
                index += 1
                break
            if quote != "`" and char in "\r\n":
                index += 1
                break
            index += 1


def _dynamic_name(expression: str) -> str:
    expression = expression.strip()
    parts = re.findall(r"[A-Za-z_$][\w$]*", expression)
    name = parts[-1] if parts else "param"
    name = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "param"
    return name


def decode_js_escapes(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        raw = next(group for group in match.groups() if group is not None)
        try:
            return chr(int(raw, 16))
        except (ValueError, OverflowError):
            return match.group(0)

    value = _JS_ESCAPE.sub(replace, value)
    return (
        value.replace(r"\/", "/")
        .replace(r"\`", "`")
        .replace(r'\"', '"')
        .replace(r"\'", "'")
    )


def _line_starts(text: str) -> list[int]:
    starts = [0]
    starts.extend(match.end() for match in re.finditer(r"\n", text))
    return starts


def _line_column(starts: list[int], offset: int) -> tuple[int, int]:
    index = bisect.bisect_right(starts, offset) - 1
    return index + 1, offset - starts[index] + 1


def _ui_evidence(text: str, offset: int) -> list[str]:
    start = max(0, offset - 1200)
    end = min(len(text), offset + 1200)
    candidates: list[tuple[int, str]] = []
    for match in _CHINESE_STRING.finditer(text[start:end]):
        value = re.sub(r"\s+", " ", decode_js_escapes(match.group("value")).strip())
        if not value or len(value) > 100 or value.startswith("/"):
            continue
        absolute = start + match.start()
        candidates.append((abs(absolute - offset), value))
    result: list[str] = []
    for _, value in sorted(candidates, key=lambda item: (item[0], item[1])):
        if value not in result:
            result.append(value)
        if len(result) == 3:
            break
    return result


def _expand_simple_concatenation(text: str, match: _StringToken) -> str:
    raw = match.group("value")
    if match.group("quote") == "`" or not text[match.end() :].lstrip().startswith("+"):
        return raw
    tail = text[match.end() : min(len(text), match.end() + 260)]
    cursor = 0
    result = raw
    additions = 0
    pattern = re.compile(
        r"\s*\+\s*(?:(?P<expr>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\+\s*)?"
        r"(?P<q>['\"])(?P<literal>(?:\\.|[^'\"])*?)(?P=q)"
    )
    while additions < 4:
        part = pattern.match(tail, cursor)
        if not part:
            break
        if part.group("expr"):
            result += "${" + part.group("expr") + "}"
        result += part.group("literal")
        cursor = part.end()
        additions += 1
    return result


def normalize_path(raw: str, *, preserve_trailing_slash: bool = True) -> str:
    value = decode_js_escapes(raw.strip())
    value = _DYNAMIC_TEMPLATE.sub(lambda match: "{" + _dynamic_name(match.group(1)) + "}", value)
    value = _DYNAMIC_COLON.sub(lambda match: "{" + match.group(1) + "}", value)
    value = _DYNAMIC_BRACE.sub(lambda match: "{" + _dynamic_name(match.group(1)) + "}", value)
    if value.startswith(("http://", "https://")):
        value = urlsplit(value).path
    else:
        value = value.split("?", 1)[0].split("#", 1)[0]
    value = re.sub(r"/{2,}", "/", value)
    if not value.startswith("/"):
        value = "/" + value
    if not preserve_trailing_slash and value != "/":
        value = value.rstrip("/")
    return value


def comparison_path(raw: str) -> str:
    value = normalize_path(raw, preserve_trailing_slash=False).lower()
    return re.sub(r"\{[^{}]+\}", "{}", value)


def looks_like_api_path(value: str) -> bool:
    decoded = decode_js_escapes(value)
    if decoded.startswith(("http://", "https://")):
        decoded = urlsplit(decoded).path
    if not decoded.startswith("/"):
        return False
    lower = decoded.lower()
    return any(
        marker in lower
        for marker in (
            "/api/",
            "/api-v",
            "/open_api/",
            "/openapi/",
            "/graphql",
        )
    )
