from __future__ import annotations

import bisect
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .io import read_json, write_json
from .normalize import (
    _expand_simple_concatenation,
    _iter_js_strings,
    _line_column,
    _line_starts,
    _ui_evidence,
    decode_js_escapes,
    looks_like_api_path,
    normalize_path,
)


COVERAGE_SCOPE = "same_origin_static_js_graph_discoverable_from_site_entry"
KNOWN_EXCLUDED_ORIGINS = ("rank.gravity-engine.com",)


_PARAM_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")
_PARAM_NUMBER = re.compile(r"(?:0[xX][0-9A-Fa-f]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)")
_PARAM_OPERATORS = (
    "===", "!==", ">>>", "**=", "...", "=>", "==", "!=", "<=", ">=",
    "&&", "||", "??", "?.", "++", "--", "**", "+=", "-=", "*=", "/=",
)
_DIRECT_METHOD = re.compile(
    r"(?i)(?:\.|\b)(get|post|put|patch|delete|head|options)\s*\(\s*$"
)
_CALL_NAME = re.compile(r"([A-Za-z_$][\w$]*)\s*\(\s*$")
_METHOD_LITERAL = re.compile(
    r"(?i)\b(?:method|type)\s*:\s*['\"`](GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)['\"`]"
)
_METHOD_AFTER = re.compile(
    r"(?i)^\s*,?\s*(?:\{|[^{}]{0,120}\{)[^{}]{0,160}\b(?:method|type)\s*:\s*['\"`]"
    r"(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)['\"`]"
)
_ASSIGNMENT = re.compile(
    r"(?:function\s+([A-Za-z_$][\w$]*)\s*\([^)]{0,200}\)\s*\{|"
    r"(?:^|[,;])\s*(?:const\s+|let\s+|var\s+)?([A-Za-z_$][\w$]*)\s*=)",
    re.MULTILINE,
)
_WRAPPER = re.compile(
    r"(?:^|[,;])\s*(?:const\s+|let\s+|var\s+)?(?P<name>[A-Za-z_$][\w$]*)\s*="
    r"\s*(?:async\s*)?(?:\([^)]{0,160}\)|[A-Za-z_$][\w$]*)\s*=>"
    r"(?P<body>.{0,500}?)(?:[,;]\s*[A-Za-z_$][\w$]*\s*=|;|\n)",
    re.DOTALL,
)
_BASE_URL = re.compile(r"\bbaseURL\s*:\s*([A-Za-z_$][\w$]*)")
_IMPORT_API = re.compile(r"import\{(?P<items>[^{}]+)\}from['\"]\./api-[^'\"]+\.js['\"]")
_EXPORT_LIST = re.compile(r"export\{(?P<items>[^{}]+)\}")
_API_BASE_PATH = re.compile(
    r"/(?:account_center|turbo_engine|report|apprank|openapi)/api/v(?:1|2|3)"
)
_DERIVED_BASE = re.compile(
    r"(?:^|[,;])\s*(?P<target>[A-Za-z_$][\w$]*)\s*=\s*`\$\{(?P<source>[A-Za-z_$][\w$]*)\}"
    r"(?P<suffix>/[^`]*)`"
)


PARSER_LIMITATIONS = [
    "Computed URLs assembled through arrays, replace(), decoding, encryption, or runtime configuration may be missed.",
    "Methods routed through wrappers whose implementation is outside the downloaded chunks can remain UNKNOWN.",
    "Caller/export names and nearby Chinese text are proximity evidence, not source-map-backed ownership.",
    "Literal third-party API paths embedded in vendor code can be included when they look like executable API calls.",
    "A partial bundle snapshot necessarily produces a partial route census.",
]


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    start: int
    end: int
    quote: str | None = None


@dataclass
class _Lexed:
    text: str
    tokens: list[_Token]
    pairs: dict[int, int]
    starts: list[int]

    def token_at_offset(self, offset: int) -> int | None:
        index = bisect.bisect_left(self.starts, offset)
        if index < len(self.tokens) and self.tokens[index].start == offset:
            return index
        if index and self.tokens[index - 1].start <= offset < self.tokens[index - 1].end:
            return index - 1
        return None


class _Tokenizer:
    def __init__(self, text: str) -> None:
        self.text = text
        self.length = len(text)

    def _scan_quoted(self, start: int) -> int:
        quote = self.text[start]
        cursor = start + 1
        while cursor < self.length:
            current = self.text[cursor]
            if current == "\\":
                cursor += 2
                continue
            if current == quote:
                return cursor + 1
            if quote == "`" and self.text.startswith("${", cursor):
                cursor = self._scan_template_expression(cursor + 1)
                continue
            if quote != "`" and current in "\r\n":
                return cursor
            cursor += 1
        return cursor

    def _scan_template_expression(self, open_brace: int) -> int:
        depth = 1
        cursor = open_brace + 1
        while cursor < self.length and depth:
            current = self.text[cursor]
            if current in "'\"`":
                cursor = self._scan_quoted(cursor)
                continue
            if current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
            cursor += 1
        return cursor

    def _skip_ignored(self, index: int) -> int | None:
        if self.text[index].isspace():
            return index + 1
        if self.text.startswith("/*", index):
            close = self.text.find("*/", index + 2)
            return self.length if close < 0 else close + 2
        return None

    def _string_token(self, start: int) -> tuple[_Token, int]:
        quote = self.text[start]
        end = self._scan_quoted(start)
        closed = end <= self.length and self.text[end - 1 : end] == quote
        value_end = end - 1 if closed else end
        return _Token("string", self.text[start + 1 : value_end], start, end, quote), end

    def _token(self, index: int) -> tuple[_Token, int]:
        char = self.text[index]
        if char in "'\"`":
            return self._string_token(index)
        identifier = _PARAM_IDENTIFIER.match(self.text, index)
        if identifier:
            return _Token("identifier", identifier.group(0), index, identifier.end()), identifier.end()
        if char.isdigit():
            number = _PARAM_NUMBER.match(self.text, index)
            if number:
                return _Token("number", number.group(0), index, number.end()), number.end()
        operator = next(
            (item for item in _PARAM_OPERATORS if self.text.startswith(item, index)), None
        )
        if operator:
            end = index + len(operator)
            return _Token("punct", operator, index, end), end
        return _Token("punct", char, index, index + 1), index + 1

    def scan(self) -> list[_Token]:
        tokens: list[_Token] = []
        index = 0
        while index < self.length:
            next_index = self._skip_ignored(index)
            if next_index is not None:
                index = next_index
                continue
            token, index = self._token(index)
            tokens.append(token)
        return tokens


def _token_pairs(tokens: list[_Token]) -> dict[int, int]:
    pairs: dict[int, int] = {}
    stacks: dict[str, list[int]] = {"(": [], "{": [], "[": []}
    closing = {")": "(", "}": "{", "]": "["}
    for token_index, token in enumerate(tokens):
        if token.value in stacks:
            stacks[token.value].append(token_index)
            continue
        if token.value not in closing:
            continue
        stack = stacks[closing[token.value]]
        if stack:
            open_index = stack.pop()
            pairs[open_index] = token_index
            pairs[token_index] = open_index
    return pairs


def _tokenize(text: str) -> _Lexed:
    tokens = _Tokenizer(text).scan()
    return _Lexed(text, tokens, _token_pairs(tokens), [token.start for token in tokens])


def _learn_wrappers(text: str) -> dict[str, str]:
    wrappers: dict[str, str] = {}
    for match in _WRAPPER.finditer(text):
        body = match.group("body")
        methods = {item.upper() for item in _METHOD_LITERAL.findall(body)}
        if len(methods) == 1 and re.search(r"\b(?:url|path)\s*:", body):
            wrappers[match.group("name")] = next(iter(methods))
    return wrappers


def _method_for(text: str, start: int, end: int, wrappers: dict[str, str]) -> tuple[str, str, str]:
    before = text[max(0, start - 220) : start]
    after = text[end : min(len(text), end + 260)]
    direct = _DIRECT_METHOD.search(before)
    if direct:
        return direct.group(1).upper(), "high", "direct_method_call"
    call = _CALL_NAME.search(before)
    if call and call.group(1) in wrappers:
        return wrappers[call.group(1)], "medium", "learned_request_wrapper"
    call_tail = after
    boundary = re.search(r"(?:\}\)|;)", call_tail)
    if boundary:
        call_tail = call_tail[: boundary.end()]
    call_methods = {item.upper() for item in _METHOD_LITERAL.findall(call_tail)}
    if len(call_methods) == 1:
        return next(iter(call_methods)), "high", "same_request_options"
    nearby = text[max(0, start - 180) : min(len(text), end + 180)]
    literals = {item.upper() for item in _METHOD_LITERAL.findall(nearby)}
    if len(literals) == 1:
        return next(iter(literals)), "medium", "nearby_method_property"
    after_match = _METHOD_AFTER.search(after)
    if after_match:
        return after_match.group(1).upper(), "medium", "following_request_options"
    fetch_prefix = re.search(r"\bfetch\s*\(\s*$", before)
    if fetch_prefix:
        return "GET", "low", "fetch_default_method"
    return "UNKNOWN", "low", "method_not_resolved"


def _route_evidence_kind(text: str, start: int) -> str:
    before = text[max(0, start - 90) : start]
    if re.search(r"\bquery_api\s*:\s*$", before):
        return "proxy_query_api_value"
    if re.search(r"\bhref\s*:\s*$", before):
        return "documentation_link"
    if re.search(r"\bvalue\s*:\s*$", before):
        return "api_catalog_value"
    if re.search(r"[A-Za-z_$][\w$]*\s*=\s*$", before):
        return "service_url_constant"
    return "request_call_candidate"


def _split_aliases(value: str) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for item in value.split(","):
        parts = item.strip().split()
        if not parts:
            continue
        if len(parts) == 3 and parts[1] == "as":
            result.append((parts[0], parts[2]))
        elif len(parts) == 1:
            result.append((parts[0], parts[0]))
    return result


def _api_exported_bases(text: str) -> tuple[dict[str, str], dict[str, str]]:
    local: dict[str, str] = {}
    for match in _iter_js_strings(text):
        if match.group("quote") != "`":
            continue
        base_match = _API_BASE_PATH.search(match.group("value"))
        if not base_match:
            continue
        before = text[max(0, match.start() - 260) : match.start()]
        assignments = list(re.finditer(r"([A-Za-z_$][\w$]*)\s*=", before))
        if assignments:
            local[assignments[-1].group(1)] = base_match.group(0)
    for _ in range(5):
        changed = False
        for match in _DERIVED_BASE.finditer(text):
            source = match.group("source")
            if source in local and match.group("target") not in local:
                local[match.group("target")] = local[source].rstrip("/") + match.group("suffix")
                changed = True
        if not changed:
            break
    exported: dict[str, str] = {}
    export_matches = list(_EXPORT_LIST.finditer(text))
    if export_matches:
        for source, public in _split_aliases(export_matches[-1].group("items")):
            if source in local:
                exported[public] = local[source]
    return local, exported


def _base_aliases(
    text: str,
    exported_bases: dict[str, str],
    own_bases: dict[str, str],
) -> dict[str, str]:
    aliases = dict(own_bases)
    for match in _IMPORT_API.finditer(text):
        for public, local in _split_aliases(match.group("items")):
            if public in exported_bases:
                aliases[local] = exported_bases[public]
    return aliases


def _base_for_context(
    text: str, start: int, end: int, base_aliases: dict[str, str]
) -> tuple[str | None, str | None]:
    after = text[end : min(len(text), end + 240)]
    boundary = re.search(r"(?:\}\)|;)", after)
    nearby = after[: boundary.end() if boundary else len(after)]
    match = _BASE_URL.search(nearby)
    if match and match.group(1) in base_aliases:
        return base_aliases[match.group(1)], match.group(1)
    return None, None


def _caller_for(text: str, start: int) -> str | None:
    window_start = max(0, start - 700)
    matches = list(_ASSIGNMENT.finditer(text[window_start:start]))
    if not matches:
        return None
    name = matches[-1].group(1) or matches[-1].group(2)
    if name and len(name) <= 120:
        return name
    return None


def parse_text(
    text: str,
    *,
    file_info: dict[str, Any],
    base_aliases: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    base_aliases = base_aliases or {}
    wrappers = _learn_wrappers(text)
    starts = _line_starts(text)
    occurrences: list[dict[str, Any]] = []
    for match in _iter_js_strings(text):
        raw = _expand_simple_concatenation(text, match)
        base, base_alias = _base_for_context(text, match.start(), match.end(), base_aliases)
        if base is not None and (
            not raw.startswith("/")
            or re.search(r"[\s\u3400-\u9fff<>]", raw)
            or raw.startswith("//")
        ):
            continue
        if not looks_like_api_path(raw) and base is None:
            continue
        resolved_raw = base.rstrip("/") + "/" + raw.lstrip("/") if base else raw
        path = normalize_path(resolved_raw)
        if len(path) > 500 or path.count("/") < 2:
            continue
        method, certainty, evidence = _method_for(text, match.start(), match.end(), wrappers)
        line, column = _line_column(starts, match.start())
        occurrences.append(
            {
                "method": method,
                "path": path,
                "raw_path": decode_js_escapes(raw),
                "resolved_base": base,
                "base_alias": base_alias,
                "file": file_info.get("local_path", ""),
                "url": file_info.get("url", ""),
                "offset": match.start(),
                "line": line,
                "column": column,
                "caller": _caller_for(text, match.start()),
                "ui_texts": _ui_evidence(text, match.start()),
                "method_certainty": certainty,
                "method_evidence": evidence,
                "route_evidence_kind": _route_evidence_kind(text, match.start()),
            }
        )
    return occurrences


def _source_metadata(
    snapshot: dict[str, Any], summary: dict[str, Any], missing_files: list[str]
) -> dict[str, Any]:
    return {
        "site_url": snapshot.get("site_url"),
        "bundle_id": snapshot.get("bundle_id"),
        "bundle_files": summary.get("bundle_files", len(snapshot.get("files", []))),
        "bundle_complete": bool(summary.get("complete", False)),
        "coverage_scope": COVERAGE_SCOPE,
        "known_excluded_origins": list(KNOWN_EXCLUDED_ORIGINS),
        "platform_complete": False,
        "missing_local_files": sorted(missing_files),
    }


def _load_sources(
    snapshot: dict[str, Any], raw_dir: Path
) -> tuple[list[tuple[dict[str, Any], str]], list[str]]:
    missing_files: list[str] = []
    loaded: list[tuple[dict[str, Any], str]] = []
    for file_info in sorted(snapshot.get("files", []), key=lambda item: item.get("url", "")):
        local_path = raw_dir / str(file_info.get("local_path", ""))
        if not local_path.is_file():
            missing_files.append(str(file_info.get("local_path", "")))
            continue
        text = local_path.read_bytes().decode("utf-8", errors="replace")
        loaded.append((file_info, text))
    return loaded, missing_files


def _exported_api_bases(
    loaded: list[tuple[dict[str, Any], str]],
) -> tuple[dict[str, str], dict[str, str]]:
    api_locals: dict[str, str] = {}
    exported_bases: dict[str, str] = {}
    for file_info, text in loaded:
        if re.search(r"/api-[^/]+\.js(?:\?|$)", str(file_info.get("url", ""))):
            api_locals, exported_bases = _api_exported_bases(text)
            break
    return api_locals, exported_bases


def _parse_loaded_sources(
    loaded: list[tuple[dict[str, Any], str]],
) -> list[dict[str, Any]]:
    api_locals, exported_bases = _exported_api_bases(loaded)
    occurrences: list[dict[str, Any]] = []
    for file_info, text in loaded:
        own_bases = api_locals if re.search(
            r"/api-[^/]+\.js(?:\?|$)", str(file_info.get("url", ""))
        ) else {}
        aliases = _base_aliases(text, exported_bases, own_bases)
        occurrences.extend(parse_text(text, file_info=file_info, base_aliases=aliases))
    return occurrences


def _group_occurrences(
    occurrences: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    known_paths = {
        item["path"] for item in occurrences if item["method"] != "UNKNOWN"
    }
    for item in occurrences:
        if item["method"] == "UNKNOWN" and item["path"] in known_paths:
            continue
        grouped[(item["method"], item["path"])].append(item)
    return grouped


def _route_from_occurrences(
    method: str, path: str, items: list[dict[str, Any]]
) -> dict[str, Any]:
    certainty_order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda item: (item["url"], item["offset"], item["raw_path"]))
    first = items[0]
    return {
        "method": method,
        "path": path,
        "raw_paths": sorted({item["raw_path"] for item in items}),
        "resolved_bases": sorted(
            {item["resolved_base"] for item in items if item.get("resolved_base")}
        ),
        "occurrences": len(items),
        "first_occurrence": {
            "file": first["file"],
            "url": first["url"],
            "offset": first["offset"],
            "line": first["line"],
            "column": first["column"],
        },
        "callers": sorted({item["caller"] for item in items if item.get("caller")})[:20],
        "ui_texts": sorted(
            {text for item in items for text in item.get("ui_texts", [])}
        )[:20],
        "method_certainty": max(
            (item["method_certainty"] for item in items),
            key=lambda value: certainty_order.get(value, 9) * -1,
        ),
        "method_evidence": sorted({item["method_evidence"] for item in items}),
        "route_evidence_kinds": sorted(
            {item["route_evidence_kind"] for item in items}
        ),
    }


def _unknown_reason_summary(routes: list[dict[str, Any]]) -> dict[str, int]:
    unknown_reason_counts: Counter[str] = Counter()
    for route in routes:
        if route["method"] != "UNKNOWN":
            continue
        kinds = set(route["route_evidence_kinds"])
        if "proxy_query_api_value" in kinds:
            unknown_reason_counts["proxy target path does not encode upstream HTTP method"] += 1
        elif kinds & {"api_catalog_value", "documentation_link", "service_url_constant"}:
            unknown_reason_counts["API catalog, documentation, or service URL literal is not a request call"] += 1
        else:
            unknown_reason_counts["request wrapper method could not be resolved statically"] += 1
    return dict(sorted(unknown_reason_counts.items()))


def build_routes(snapshot: dict[str, Any], raw_dir: Path) -> dict[str, Any]:
    loaded, missing_files = _load_sources(snapshot, raw_dir)
    grouped = _group_occurrences(_parse_loaded_sources(loaded))
    routes = [
        _route_from_occurrences(method, path, items)
        for (method, path), items in grouped.items()
    ]
    routes.sort(key=lambda item: (item["path"], item["method"]))
    summary = snapshot.get("summary", {})
    return {
        "schema_version": 1,
        "source": _source_metadata(snapshot, summary, missing_files),
        "parser": {
            "strategy": "hybrid lexical string scan plus request-call context and wrapper inference",
            "known_limitations": PARSER_LIMITATIONS,
        },
        "summary": {
            "unique_method_path": len(routes),
            "route_occurrences": sum(item["occurrences"] for item in routes),
            "unknown_method_routes": sum(item["method"] == "UNKNOWN" for item in routes),
            "unknown_method_reasons": _unknown_reason_summary(routes),
        },
        "routes": routes,
    }


def parse_snapshot(snapshot_path: Path, raw_dir: Path, output_path: Path) -> dict[str, Any]:
    result = build_routes(read_json(snapshot_path), raw_dir)
    write_json(output_path, result)
    return result
