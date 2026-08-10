from __future__ import annotations

import re
from urllib.parse import urlsplit


_DYNAMIC_TEMPLATE = re.compile(r"\$\{\s*([^}]+?)\s*\}")
_DYNAMIC_COLON = re.compile(r"(?<=/):([A-Za-z_$][\w$-]*)")
_DYNAMIC_BRACE = re.compile(r"\{\s*([^{}]+?)\s*\}")
_JS_ESCAPE = re.compile(r"\\(?:u\{([0-9a-fA-F]+)\}|u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2}))")


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
