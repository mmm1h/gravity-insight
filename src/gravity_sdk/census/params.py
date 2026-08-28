from __future__ import annotations

import bisect
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import unquote_plus

from .io import all_parameter_nodes as _all_parameter_nodes, batch_parameter_validation as _batch_validation, read_json, summarize_parameter_routes as _summary, write_json
from .normalize import comparison_path, decode_js_escapes
from .parser import (
    _api_exported_bases,
    _base_aliases,
    parse_text,
)


PARAM_SCHEMA_VERSION = "gravity-census.route-params.v1"
_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
_TYPE_ORDER = {
    "object": 0,
    "array": 1,
    "string": 2,
    "integer": 3,
    "number": 4,
    "boolean": 5,
    "null": 6,
    "unknown": 7,
}
_IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")
_PATH_PARAMETER = re.compile(r"\{([^{}]+)\}")
_NO_DEFAULT = object()


PARAM_PARSER_LIMITATIONS = [
    "Payloads assembled in another chunk, class instance, store mutation, serializer, or runtime registry remain unresolved.",
    "A variable initializer is used only for type and nested-key inference; it is not claimed as a request default.",
    "Computed property names, Object.assign chains, reducers, and dynamically generated query strings can be missed.",
    "Observed-always means present in every statically resolved frontend call, not server-side validation proof.",
    "Minified bindings can be shadowed in a nested scope; lexical scope bounding reduces but cannot eliminate that ambiguity.",
    "Probe evidence persists schema shapes without response values, so the numeric code and error message cannot be replayed.",
]


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str
    start: int
    end: int
    quote: str | None = None


@dataclass
class _Field:
    name: str
    types: set[str] = field(default_factory=set)
    confidence: str = "high"
    type_confidence: str = "low"
    defaults: list[Any] = field(default_factory=list)
    default_confidence: str | None = None
    children: dict[str, "_Field"] = field(default_factory=dict)
    item_types: set[str] = field(default_factory=set)
    item_confidence: str = "low"
    item_children: dict[str, "_Field"] = field(default_factory=dict)
    conditional: bool = False
    unresolved: bool = False
    evidence: set[str] = field(default_factory=set)


@dataclass
class _Shape:
    fields: dict[str, _Field] = field(default_factory=dict)
    unresolved: bool = False
    unresolved_reasons: set[str] = field(default_factory=set)


@dataclass
class _CallShape:
    offset: int
    locations: dict[str, _Shape] = field(default_factory=dict)
    unresolved_locations: set[str] = field(default_factory=set)
    evidence_kind: str = "load_call"


@dataclass
class _OccurrenceResult:
    calls: list[_CallShape] = field(default_factory=list)
    unresolved_reasons: set[str] = field(default_factory=set)


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


def _worse(left: str, right: str) -> str:
    return max((left, right), key=lambda value: _CONFIDENCE_ORDER.get(value, 9))


def _downgrade(value: str, floor: str) -> str:
    return _worse(value, floor)


def _tokenize(text: str) -> _Lexed:
    def scan_quoted(start: int) -> int:
        quote = text[start]
        cursor = start + 1
        while cursor < length:
            current = text[cursor]
            if current == "\\":
                cursor += 2
                continue
            if current == quote:
                return cursor + 1
            if quote == "`" and text.startswith("${", cursor):
                cursor = scan_template_expression(cursor + 1)
                continue
            if quote != "`" and current in "\r\n":
                return cursor
            cursor += 1
        return cursor

    def scan_template_expression(open_brace: int) -> int:
        depth = 1
        cursor = open_brace + 1
        while cursor < length and depth:
            current = text[cursor]
            if current in "'\"`":
                cursor = scan_quoted(cursor)
                continue
            if current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
            cursor += 1
        return cursor

    tokens: list[_Token] = []
    index = 0
    length = len(text)
    operators = (
        "===",
        "!==",
        ">>>",
        "**=",
        "...",
        "=>",
        "==",
        "!=",
        "<=",
        ">=",
        "&&",
        "||",
        "??",
        "?.",
        "++",
        "--",
        "**",
        "+=",
        "-=",
        "*=",
        "/=",
    )
    while index < length:
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if text.startswith("/*", index):
            close = text.find("*/", index + 2)
            index = length if close < 0 else close + 2
            continue
        if char in "'\"`":
            quote = char
            start = index
            index = scan_quoted(start)
            value_end = index - 1 if index <= length and text[index - 1 : index] == quote else index
            tokens.append(_Token("string", text[start + 1 : value_end], start, index, quote))
            continue
        identifier = _IDENTIFIER.match(text, index)
        if identifier:
            tokens.append(_Token("identifier", identifier.group(0), index, identifier.end()))
            index = identifier.end()
            continue
        if char.isdigit():
            number = re.match(
                r"(?:0[xX][0-9A-Fa-f]+|\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)", text[index:]
            )
            if number:
                end = index + number.end()
                tokens.append(_Token("number", number.group(0), index, end))
                index = end
                continue
        operator = next((item for item in operators if text.startswith(item, index)), None)
        if operator:
            tokens.append(_Token("punct", operator, index, index + len(operator)))
            index += len(operator)
            continue
        tokens.append(_Token("punct", char, index, index + 1))
        index += 1

    pairs: dict[int, int] = {}
    stacks: dict[str, list[int]] = {"(": [], "{": [], "[": []}
    closing = {")": "(", "}": "{", "]": "["}
    for token_index, token in enumerate(tokens):
        if token.value in stacks:
            stacks[token.value].append(token_index)
        elif token.value in closing:
            stack = stacks[closing[token.value]]
            if stack:
                open_index = stack.pop()
                pairs[open_index] = token_index
                pairs[token_index] = open_index
    return _Lexed(text, tokens, pairs, [token.start for token in tokens])


def _trim(tokens: Sequence[_Token], start: int, end: int) -> tuple[int, int]:
    while start < end and tokens[start].value == ";":
        start += 1
    while end > start and tokens[end - 1].value == ";":
        end -= 1
    return start, end


def _segments(lexed: _Lexed, start: int, end: int, delimiter: str = ",") -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    segment_start = start
    index = start
    while index < end:
        token = lexed.tokens[index]
        if token.value in "({[" and index in lexed.pairs:
            index = lexed.pairs[index] + 1
            continue
        if token.value == delimiter:
            if segment_start < index:
                result.append((segment_start, index))
            segment_start = index + 1
        index += 1
    if segment_start < end:
        result.append((segment_start, end))
    return result


def _top_level_token(lexed: _Lexed, start: int, end: int, values: set[str]) -> int | None:
    index = start
    while index < end:
        token = lexed.tokens[index]
        if token.value in "({[" and index in lexed.pairs:
            index = lexed.pairs[index] + 1
            continue
        if token.value in values:
            return index
        index += 1
    return None


def _expression_end(lexed: _Lexed, start: int, limit: int) -> int:
    index = start
    ternary_depth = 0
    while index < limit:
        token = lexed.tokens[index]
        if token.value in "({[" and index in lexed.pairs:
            index = lexed.pairs[index] + 1
            continue
        if token.value == "?":
            ternary_depth += 1
        elif token.value == ":" and ternary_depth:
            ternary_depth -= 1
        elif token.value in {",", ";"} and ternary_depth == 0:
            break
        index += 1
    return index


def _literal(token: _Token) -> tuple[str, Any] | None:
    if token.kind == "string":
        if token.quote == "`" and "${" in token.value:
            return "string", _NO_DEFAULT
        return "string", decode_js_escapes(token.value)
    if token.kind == "number":
        try:
            if any(marker in token.value.casefold() for marker in (".", "e")):
                return "number", float(token.value)
            return "integer", int(token.value, 0)
        except ValueError:
            return "number", _NO_DEFAULT
    if token.value in {"true", "false"}:
        return "boolean", token.value == "true"
    if token.value == "null":
        return "null", None
    return None


def _copy_field(source: _Field, *, name: str | None = None) -> _Field:
    return _Field(
        name=name or source.name,
        types=set(source.types),
        confidence=source.confidence,
        type_confidence=source.type_confidence,
        defaults=list(source.defaults),
        default_confidence=source.default_confidence,
        children={key: _copy_field(value) for key, value in source.children.items()},
        item_types=set(source.item_types),
        item_confidence=source.item_confidence,
        item_children={key: _copy_field(value) for key, value in source.item_children.items()},
        conditional=source.conditional,
        unresolved=source.unresolved,
        evidence=set(source.evidence),
    )


def _merge_field(target: _Field, source: _Field) -> None:
    target.types.update(source.types)
    target.confidence = _worse(target.confidence, source.confidence)
    target.type_confidence = _worse(target.type_confidence, source.type_confidence)
    target.conditional = target.conditional or source.conditional
    target.unresolved = target.unresolved or source.unresolved
    target.evidence.update(source.evidence)
    for value in source.defaults:
        if not any(existing == value for existing in target.defaults):
            target.defaults.append(value)
    if source.default_confidence:
        target.default_confidence = (
            source.default_confidence
            if target.default_confidence is None
            else _worse(target.default_confidence, source.default_confidence)
        )
    for name, child in source.children.items():
        if name in target.children:
            _merge_field(target.children[name], child)
        else:
            target.children[name] = _copy_field(child)
    target.item_types.update(source.item_types)
    target.item_confidence = _worse(target.item_confidence, source.item_confidence)
    for name, child in source.item_children.items():
        if name in target.item_children:
            _merge_field(target.item_children[name], child)
        else:
            target.item_children[name] = _copy_field(child)


def _merge_shape(target: _Shape, source: _Shape, *, conditional: bool = False) -> None:
    target.unresolved = target.unresolved or source.unresolved
    target.unresolved_reasons.update(source.unresolved_reasons)
    for name, field_value in source.fields.items():
        copied = _copy_field(field_value)
        copied.conditional = copied.conditional or conditional
        if conditional:
            copied.evidence.add("conditional_spread")
        if name in target.fields:
            _merge_field(target.fields[name], copied)
        else:
            target.fields[name] = copied


def _enclosing_scope(lexed: _Lexed, token_index: int) -> tuple[int, int]:
    for open_index in range(token_index - 1, -1, -1):
        if lexed.tokens[open_index].value != "{":
            continue
        close_index = lexed.pairs.get(open_index)
        if close_index is not None and close_index > token_index:
            return open_index, close_index
    return -1, len(lexed.tokens)


def _initializer_range(
    lexed: _Lexed, identifier: str, before: int, scope_start: int
) -> tuple[int, int] | None:
    tokens = lexed.tokens
    index = before - 1
    lower = max(scope_start + 1, 0)
    while index >= lower:
        token = tokens[index]
        if token.value == identifier and index + 1 < before and tokens[index + 1].value == "=":
            value_start = index + 2
            value_end = _expression_end(lexed, value_start, before)
            if value_start < value_end:
                return value_start, value_end
        index -= 1
    return None


def _pure_member_chain(
    tokens: Sequence[_Token], start: int, end: int
) -> list[str] | None:
    if start >= end or tokens[start].kind != "identifier":
        return None
    members: list[str] = []
    index = start + 1
    while index < end:
        if tokens[index].value not in {".", "?."}:
            return None
        if index + 1 >= end or tokens[index + 1].kind != "identifier":
            return None
        members.append(tokens[index + 1].value)
        index += 2
    return members


def _select_member(inferred: _Field, members: Sequence[str], *, name: str) -> _Field:
    selected = _copy_field(inferred, name=name)
    for member in members:
        if member == "value" and member not in selected.children:
            continue
        if member == "length" and "array" in selected.types:
            return _Field(
                name=name,
                types={"integer"},
                confidence="medium",
                type_confidence="medium",
                evidence={"array_length"},
            )
        child = selected.children.get(member)
        if child is None:
            return _Field(
                name=name,
                types={"unknown"},
                confidence="medium",
                type_confidence="low",
                unresolved=True,
                evidence={"unresolved_member_access"},
            )
        selected = _copy_field(child, name=name)
    return selected


def _unknown_expression(name: str, evidence: str = "runtime_expression") -> _Field:
    return _Field(
        name=name, types={"unknown"}, type_confidence="low", unresolved=True,
        evidence={"literal_object_key", evidence},
    )


def _infer_collection(
    lexed: _Lexed, start: int, end: int, name: str, scope_start: int, seen: frozenset[str]
) -> _Field | None:
    result = _Field(name=name, evidence={"literal_object_key"})
    if lexed.tokens[start].value == "{" and lexed.pairs.get(start) == end - 1:
        shape = _parse_object(lexed, start, scope_start=scope_start, seen=seen)
        result.types.add("object")
        result.type_confidence = "high"
        result.children = shape.fields
        result.unresolved = shape.unresolved
        return result
    if lexed.tokens[start].value != "[" or lexed.pairs.get(start) != end - 1:
        return None
    result.types.add("array")
    result.type_confidence = "high"
    for item_start, item_end in _segments(lexed, start + 1, end - 1):
        item = _infer_expression(
            lexed, item_start, item_end, name="[]", scope_start=scope_start, seen=seen
        )
        result.item_types.update(item.types)
        result.item_confidence = _worse(result.item_confidence, item.type_confidence)
        for child_name, child in item.children.items():
            if child_name in result.item_children:
                _merge_field(result.item_children[child_name], child)
            else:
                result.item_children[child_name] = _copy_field(child)
    if not result.item_types:
        result.item_types.add("unknown")
    return result


def _infer_literal_expression(tokens: Sequence[_Token], start: int, end: int, name: str) -> _Field | None:
    result = _Field(name=name, evidence={"literal_object_key"})
    literal = _literal(tokens[start]) if end - start == 1 else None
    sign = tokens[start].value if end - start == 2 else None
    signed_literal = _literal(tokens[start + 1]) if sign in {"+", "-"} else None
    if literal:
        value_type, value = literal
    elif signed_literal and signed_literal[0] in {"integer", "number"}:
        value_type, value = signed_literal
        value = value if sign == "+" else -value
    elif end - start == 2 and tokens[start].value == "!" and tokens[start + 1].value in {"0", "1"}:
        value_type, value = "boolean", tokens[start + 1].value == "0"
    else:
        return None
    result.types.add(value_type)
    result.type_confidence = "high"
    if value is not _NO_DEFAULT:
        result.defaults.append(value)
        result.default_confidence = "high"
    return result


def _infer_conditional(
    lexed: _Lexed, start: int, end: int, name: str, scope_start: int, seen: frozenset[str]
) -> _Field | None:
    question = _top_level_token(lexed, start, end, {"?"})
    if question is None:
        return None
    colon = _top_level_token(lexed, question + 1, end, {":"})
    if colon is None:
        return None
    left = _infer_expression(
        lexed, question + 1, colon, name=name, scope_start=scope_start, seen=seen
    )
    right = _infer_expression(
        lexed, colon + 1, end, name=name, scope_start=scope_start, seen=seen
    )
    _merge_field(left, right)
    left.defaults = []
    left.default_confidence = None
    left.type_confidence = _downgrade(left.type_confidence, "medium")
    left.evidence.add("conditional_value")
    return left


def _infer_fallback(
    lexed: _Lexed, start: int, end: int, name: str, scope_start: int, seen: frozenset[str]
) -> _Field | None:
    fallback = _top_level_token(lexed, start, end, {"||", "??"})
    if fallback is None:
        return None
    left = _infer_expression(lexed, start, fallback, name=name, scope_start=scope_start, seen=seen)
    right = _infer_expression(
        lexed, fallback + 1, end, name=name, scope_start=scope_start, seen=seen
    )
    left.types.update(right.types)
    left.type_confidence = _downgrade(_worse(left.type_confidence, right.type_confidence), "medium")
    if right.defaults:
        left.defaults = list(right.defaults)
        left.default_confidence = _downgrade(right.default_confidence or "high", "medium")
    left.evidence.add("fallback_literal")
    return left


def _infer_known_call(tokens: Sequence[_Token], start: int, end: int, name: str) -> _Field | None:
    result = _Field(name=name, evidence={"literal_object_key"})
    first_identifier = next(
        (token.value for token in tokens[start:end] if token.kind == "identifier"), None
    )
    conversion_types = {"Number": "integer", "parseInt": "integer", "parseFloat": "number", "String": "string"}
    if first_identifier in conversion_types:
        result.types.add(conversion_types[first_identifier])
        result.type_confidence = "medium"
        result.evidence.add("conversion_call")
        return result
    if not any(token.value == "map" for token in tokens[start:end]):
        return None
    result.types.add("array")
    result.item_types.add("unknown")
    result.type_confidence = "medium"
    result.evidence.add("array_method")
    return result


def _infer_identifier(
    lexed: _Lexed, start: int, end: int, name: str, scope_start: int, seen: frozenset[str]
) -> _Field | None:
    tokens = lexed.tokens
    if tokens[start].kind != "identifier":
        return None
    identifier = tokens[start].value
    member_chain = _pure_member_chain(tokens, start, end)
    if member_chain is None or identifier in seen:
        return None
    initializer = _initializer_range(lexed, identifier, start, scope_start)
    if not initializer:
        return None
    inferred = _infer_expression(
        lexed, *initializer, name=name, scope_start=scope_start, seen=seen | {identifier}
    )
    if inferred.types == {"unknown"} and initializer[0] + 1 < initializer[1]:
        call_open = initializer[0] + 1
        call_close = lexed.pairs.get(call_open) if tokens[call_open].value == "(" else None
        if call_close and call_close < initializer[1]:
            arguments = _segments(lexed, call_open + 1, call_close)
            if arguments:
                inferred = _infer_expression(
                    lexed, *arguments[0], name=name, scope_start=scope_start, seen=seen | {identifier}
                )
    inferred = _select_member(inferred, member_chain, name=name)
    inferred.confidence = _downgrade(inferred.confidence, "medium")
    inferred.type_confidence = _downgrade(inferred.type_confidence, "medium")
    inferred.defaults = []
    inferred.default_confidence = None
    inferred.evidence.add("variable_initializer")
    return inferred


def _infer_expression(
    lexed: _Lexed,
    start: int,
    end: int,
    *,
    name: str,
    scope_start: int,
    seen: frozenset[str] = frozenset(),
) -> _Field:
    tokens = lexed.tokens
    start, end = _trim(tokens, start, end)
    if start >= end:
        return _unknown_expression(name)
    while (
        tokens[start].value == "("
        and start in lexed.pairs
        and lexed.pairs[start] == end - 1
    ):
        start += 1
        end -= 1
    if start >= end:
        return _unknown_expression(name)
    if tokens[start].value == "void":
        return _unknown_expression(name)
    handlers = (
        lambda: _infer_collection(lexed, start, end, name, scope_start, seen),
        lambda: _infer_literal_expression(tokens, start, end, name),
        lambda: _infer_conditional(lexed, start, end, name, scope_start, seen),
        lambda: _infer_fallback(lexed, start, end, name, scope_start, seen),
        lambda: _infer_known_call(tokens, start, end, name),
        lambda: _infer_identifier(lexed, start, end, name, scope_start, seen),
    )
    for handler in handlers:
        inferred = handler()
        if inferred is not None:
            return inferred
    return _unknown_expression(name)


def _spread_shape(
    lexed: _Lexed,
    start: int,
    end: int,
    *,
    scope_start: int,
    seen: frozenset[str],
) -> tuple[_Shape, bool]:
    while (
        start < end
        and lexed.tokens[start].value == "("
        and start in lexed.pairs
        and lexed.pairs[start] == end - 1
    ):
        start += 1
        end -= 1
    question = _top_level_token(lexed, start, end, {"?"})
    if question is not None:
        colon = _top_level_token(lexed, question + 1, end, {":"})
        if colon is not None:
            combined = _Shape()
            for branch_start, branch_end in ((question + 1, colon), (colon + 1, end)):
                branch = _infer_expression(
                    lexed,
                    branch_start,
                    branch_end,
                    name="...",
                    scope_start=scope_start,
                    seen=seen,
                )
                if "object" in branch.types:
                    _merge_shape(combined, _Shape(branch.children), conditional=True)
            if combined.fields:
                return combined, True
    logical = _top_level_token(lexed, start, end, {"&&"})
    if logical is not None:
        branch = _infer_expression(
            lexed,
            logical + 1,
            end,
            name="...",
            scope_start=scope_start,
            seen=seen,
        )
        if "object" in branch.types:
            return _Shape(branch.children), True
    inferred = _infer_expression(
        lexed,
        start,
        end,
        name="...",
        scope_start=scope_start,
        seen=seen,
    )
    if "object" in inferred.types and inferred.children:
        shape = _Shape(inferred.children, unresolved=inferred.unresolved)
        for child in shape.fields.values():
            child.confidence = _downgrade(child.confidence, "medium")
            child.evidence.add("resolved_spread")
        return shape, inferred.unresolved
    return _Shape(unresolved=True, unresolved_reasons={"unresolved_object_spread"}), True


def _parse_object(
    lexed: _Lexed,
    open_index: int,
    *,
    scope_start: int,
    seen: frozenset[str] = frozenset(),
) -> _Shape:
    close_index = lexed.pairs.get(open_index)
    if close_index is None:
        return _Shape(unresolved=True, unresolved_reasons={"unbalanced_object"})
    shape = _Shape()
    for start, end in _segments(lexed, open_index + 1, close_index):
        start, end = _trim(lexed.tokens, start, end)
        if start >= end:
            continue
        if lexed.tokens[start].value == "...":
            spread, conditional = _spread_shape(
                lexed,
                start + 1,
                end,
                scope_start=scope_start,
                seen=seen,
            )
            _merge_shape(shape, spread, conditional=conditional)
            continue
        colon = _top_level_token(lexed, start, end, {":"})
        if colon is None:
            key_token = lexed.tokens[start]
            if key_token.kind != "identifier":
                shape.unresolved = True
                shape.unresolved_reasons.add("computed_or_method_property")
                continue
            value = _infer_expression(
                lexed,
                start,
                end,
                name=key_token.value,
                scope_start=scope_start,
                seen=seen,
            )
            value.evidence.add("shorthand_property")
            shape.fields[key_token.value] = value
            continue
        if colon != start + 1:
            shape.unresolved = True
            shape.unresolved_reasons.add("computed_property_name")
            continue
        key_token = lexed.tokens[start]
        if key_token.kind not in {"identifier", "string", "number"}:
            shape.unresolved = True
            shape.unresolved_reasons.add("computed_property_name")
            continue
        name = decode_js_escapes(key_token.value)
        value = _infer_expression(
            lexed,
            colon + 1,
            end,
            name=name,
            scope_start=scope_start,
            seen=seen,
        )
        shape.fields[name] = value
    return shape


def _call_open_for_route(lexed: _Lexed, route_index: int) -> int | None:
    for open_index in range(route_index - 1, 0, -1):
        if lexed.tokens[open_index].value != "(":
            continue
        close_index = lexed.pairs.get(open_index)
        if close_index is None or close_index < route_index:
            continue
        previous = lexed.tokens[open_index - 1]
        if previous.kind == "identifier" or previous.value in {")", "]"}:
            return open_index
    return None


def _object_containing(
    lexed: _Lexed, token_index: int, *, inside_start: int, inside_end: int
) -> int | None:
    for open_index in range(token_index - 1, inside_start - 1, -1):
        if lexed.tokens[open_index].value != "{":
            continue
        close_index = lexed.pairs.get(open_index)
        if close_index is not None and token_index < close_index <= inside_end:
            return open_index
    return None


def _load_alias(lexed: _Lexed, call_open: int) -> str | None:
    callee = call_open - 1
    if callee < 1 or lexed.tokens[callee - 1].value != "=":
        return None
    equals = callee - 1
    object_close = equals - 1
    if object_close < 0 or lexed.tokens[object_close].value != "}":
        return None
    object_open = lexed.pairs.get(object_close)
    if object_open is None:
        return None
    for start, end in _segments(lexed, object_open + 1, object_close):
        colon = _top_level_token(lexed, start, end, {":"})
        if colon == start + 1 and lexed.tokens[start].value == "load":
            if colon + 1 < end and lexed.tokens[colon + 1].kind == "identifier":
                return lexed.tokens[colon + 1].value
        if colon is None and start < end and lexed.tokens[start].value == "load":
            return "load"
    return None


def _field_to_shape(field_value: _Field, reason: str) -> _Shape:
    if "object" in field_value.types:
        return _Shape(
            fields={name: _copy_field(value) for name, value in field_value.children.items()},
            unresolved=field_value.unresolved,
            unresolved_reasons={reason} if field_value.unresolved else set(),
        )
    return _Shape(unresolved=True, unresolved_reasons={reason})


def _envelope_locations(
    envelope: _Shape,
    *,
    method: str,
) -> tuple[dict[str, _Shape], set[str]]:
    locations: dict[str, _Shape] = {}
    unresolved_locations: set[str] = set()
    for key, field_value in envelope.fields.items():
        location: str | None = None
        if key in {"params", "query"}:
            location = "query"
        elif key in {"body", "data"}:
            location = "query" if method.upper() == "GET" else "body"
        if location is None:
            continue
        converted = _field_to_shape(field_value, f"unresolved_{key}_expression")
        if converted.unresolved and not converted.fields:
            unresolved_locations.add(location)
        if location in locations:
            _merge_shape(locations[location], converted)
        else:
            locations[location] = converted
    return locations, unresolved_locations


def _parse_call_envelope(
    lexed: _Lexed,
    call_open: int,
    *,
    method: str,
    scope_start: int,
) -> _CallShape:
    call_close = lexed.pairs.get(call_open)
    if call_close is None:
        return _CallShape(
            lexed.tokens[call_open].start,
            unresolved_locations={"query", "body"},
        )
    arguments = _segments(lexed, call_open + 1, call_close)
    if not arguments:
        return _CallShape(lexed.tokens[call_open].start)
    first_start, first_end = arguments[0]
    inferred = _infer_expression(
        lexed,
        first_start,
        first_end,
        name="request",
        scope_start=scope_start,
    )
    if "object" not in inferred.types:
        return _CallShape(
            lexed.tokens[call_open].start,
            unresolved_locations={"query", "body"},
        )
    envelope = _Shape(inferred.children, unresolved=inferred.unresolved)
    locations, unresolved = _envelope_locations(envelope, method=method)
    return _CallShape(
        offset=lexed.tokens[call_open].start,
        locations=locations,
        unresolved_locations=unresolved,
    )


def _route_options(
    lexed: _Lexed,
    call_open: int,
    route_index: int,
    *,
    scope_start: int,
) -> _Shape | None:
    call_close = lexed.pairs.get(call_open)
    if call_close is None:
        return None
    arguments = _segments(lexed, call_open + 1, call_close)
    for argument_index, (start, end) in enumerate(arguments):
        if start <= route_index < end:
            if argument_index + 1 >= len(arguments):
                return None
            option_start, option_end = arguments[argument_index + 1]
            inferred = _infer_expression(
                lexed,
                option_start,
                option_end,
                name="options",
                scope_start=scope_start,
            )
            if "object" in inferred.types:
                return _Shape(inferred.children, unresolved=inferred.unresolved)
            return None
    return None


def _find_alias_calls(
    lexed: _Lexed,
    alias: str,
    *,
    after: int,
    scope_end: int,
    method: str,
    scope_start: int,
) -> list[_CallShape]:
    calls: list[_CallShape] = []
    index = after
    while index + 1 < scope_end:
        if lexed.tokens[index].value == alias and lexed.tokens[index + 1].value == "(":
            call_open = index + 1
            call_close = lexed.pairs.get(call_open)
            if call_close is not None and call_close <= scope_end:
                calls.append(
                    _parse_call_envelope(
                        lexed,
                        call_open,
                        method=method,
                        scope_start=scope_start,
                    )
                )
                index = call_close + 1
                continue
        index += 1
    return calls


def _downgrade_shape(shape: _Shape, floor: str, evidence: str) -> None:
    def visit(value: _Field) -> None:
        value.confidence = _downgrade(value.confidence, floor)
        value.evidence.add(evidence)
        for child in value.children.values():
            visit(child)
        for child in value.item_children.values():
            visit(child)

    for field_value in shape.fields.values():
        visit(field_value)


def _find_forwarded_alias_calls(
    lexed: _Lexed,
    alias: str,
    *,
    after: int,
    scope_end: int,
    method: str,
    scope_start: int,
) -> list[_CallShape]:
    tokens = lexed.tokens
    calls: list[_CallShape] = []
    for alias_index in range(after, scope_end):
        if tokens[alias_index].value != alias:
            continue
        equals: int | None = None
        for index in range(alias_index - 1, max(after - 1, alias_index - 80), -1):
            if tokens[index].value in {";", "{"}:
                break
            if tokens[index].value == "=":
                equals = index
                break
        if equals is None or equals == 0 or tokens[equals - 1].kind != "identifier":
            continue
        forwarded = tokens[equals - 1].value
        expression_end = _expression_end(lexed, equals + 1, scope_end)
        if not (equals < alias_index < expression_end):
            continue
        search_end = min(scope_end, expression_end + 400)
        forwarded_calls = _find_alias_calls(
            lexed,
            forwarded,
            after=expression_end,
            scope_end=search_end,
            method=method,
            scope_start=scope_start,
        )
        for call in forwarded_calls:
            call.evidence_kind = "forwarded_load_call"
            for shape in call.locations.values():
                _downgrade_shape(shape, "medium", "conditional_loader_forwarding")
            calls.append(call)
    unique: dict[int, _CallShape] = {}
    for call in calls:
        unique.setdefault(call.offset, call)
    return [unique[offset] for offset in sorted(unique)]


def _extract_occurrence(
    lexed: _Lexed,
    occurrence: Mapping[str, Any],
) -> _OccurrenceResult:
    token_index = lexed.token_at_offset(int(occurrence["offset"]))
    if token_index is None:
        return _OccurrenceResult(unresolved_reasons={"route_token_not_found"})
    call_open = _call_open_for_route(lexed, token_index)
    if call_open is None:
        return _OccurrenceResult(unresolved_reasons={"request_call_not_found"})
    call_close = lexed.pairs.get(call_open)
    if call_close is None:
        return _OccurrenceResult(unresolved_reasons={"unbalanced_request_call"})
    scope_start, scope_end = _enclosing_scope(lexed, call_open)
    method = str(occurrence["method"])

    request_object = _object_containing(
        lexed,
        token_index,
        inside_start=call_open,
        inside_end=call_close,
    )
    if request_object is not None:
        request_shape = _parse_object(
            lexed,
            request_object,
            scope_start=scope_start,
        )
        if {"url", "path"} & set(request_shape.fields):
            locations, unresolved = _envelope_locations(request_shape, method=method)
            return _OccurrenceResult(
                calls=[
                    _CallShape(
                        offset=lexed.tokens[call_open].start,
                        locations=locations,
                        unresolved_locations=unresolved,
                        evidence_kind="direct_request_options",
                    )
                ]
            )

    options = _route_options(
        lexed,
        call_open,
        token_index,
        scope_start=scope_start,
    )
    alias = _load_alias(lexed, call_open)
    if alias:
        calls = _find_alias_calls(
            lexed,
            alias,
            after=call_close + 1,
            scope_end=scope_end,
            method=method,
            scope_start=scope_start,
        )
        if not calls:
            calls = _find_forwarded_alias_calls(
                lexed,
                alias,
                after=call_close + 1,
                scope_end=scope_end,
                method=method,
                scope_start=scope_start,
            )
        if calls:
            default_locations: dict[str, _Shape] = {}
            default_unresolved: set[str] = set()
            if options:
                default_locations, default_unresolved = _envelope_locations(options, method=method)
            for call in calls:
                for location, shape in default_locations.items():
                    if location not in call.locations:
                        call.locations[location] = shape
                call.unresolved_locations.update(default_unresolved)
            return _OccurrenceResult(calls=calls)
        if options:
            locations, unresolved = _envelope_locations(options, method=method)
            if locations or unresolved:
                return _OccurrenceResult(
                    calls=[
                        _CallShape(
                            offset=lexed.tokens[call_open].start,
                            locations=locations,
                            unresolved_locations=unresolved,
                            evidence_kind="factory_default_only",
                        )
                    ],
                    unresolved_reasons={"load_alias_has_no_static_call"},
                )
        return _OccurrenceResult(unresolved_reasons={"load_alias_has_no_static_call"})

    if options:
        locations, unresolved = _envelope_locations(options, method=method)
        if locations or unresolved:
            return _OccurrenceResult(
                calls=[
                    _CallShape(
                        offset=lexed.tokens[call_open].start,
                        locations=locations,
                        unresolved_locations=unresolved,
                        evidence_kind="inline_request_factory",
                    )
                ]
            )
    return _OccurrenceResult(unresolved_reasons={"request_binding_not_resolved"})


def _raw_query_shape(raw_path: str) -> _Shape:
    if "?" not in raw_path:
        return _Shape()
    query = raw_path.split("?", 1)[1].split("#", 1)[0]
    shape = _Shape()
    for part in query.split("&"):
        if not part:
            continue
        name, separator, raw_value = part.partition("=")
        name = unquote_plus(name)
        if not name or "${" in name:
            shape.unresolved = True
            shape.unresolved_reasons.add("dynamic_query_parameter_name")
            continue
        parameter = _Field(name=name, confidence="high", evidence={"url_query_key"})
        if not separator or "${" in raw_value:
            parameter.types.add("unknown")
            parameter.type_confidence = "low"
            parameter.unresolved = True
        else:
            value = unquote_plus(raw_value)
            parameter.types.add("string")
            parameter.type_confidence = "high"
            parameter.defaults.append(value)
            parameter.default_confidence = "high"
        shape.fields[name] = parameter
    return shape


def _path_parameters(route: Mapping[str, Any]) -> list[dict[str, Any]]:
    normalized_names = _PATH_PARAMETER.findall(str(route["path"]))
    return [
        {
            "confidence": "high",
            "evidence": ["normalized_route_template"],
            "name": name,
            "required": "observed_always",
            "type_confidence": "low",
            "types": ["unknown"],
        }
        for name in dict.fromkeys(normalized_names)
    ]


def _field_dict(
    value: _Field,
    *,
    required: str,
    path: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "confidence": value.confidence,
        "evidence": sorted(value.evidence),
        "name": value.name,
        "path": path,
        "required": required,
        "type_confidence": value.type_confidence,
        "types": sorted(value.types or {"unknown"}, key=lambda item: _TYPE_ORDER.get(item, 99)),
    }
    if len(value.defaults) == 1:
        result["default"] = value.defaults[0]
        result["default_confidence"] = value.default_confidence
    elif value.defaults:
        result["observed_defaults"] = sorted(
            value.defaults,
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
        result["default_confidence"] = value.default_confidence
    if value.children:
        result["properties"] = [
            _field_dict(
                child,
                required=(
                    "observed_conditional"
                    if child.conditional
                    else "observed_always"
                ),
                path=f"{path}.{name}",
            )
            for name, child in sorted(value.children.items())
        ]
    if "array" in value.types:
        item: dict[str, Any] = {
            "type_confidence": value.item_confidence,
            "types": sorted(
                value.item_types or {"unknown"}, key=lambda entry: _TYPE_ORDER.get(entry, 99)
            ),
        }
        if value.item_children:
            item["properties"] = [
                _field_dict(
                    child,
                    required=(
                        "observed_conditional"
                        if child.conditional
                        else "observed_always"
                    ),
                    path=f"{path}[].{name}",
                )
                for name, child in sorted(value.item_children.items())
            ]
        result["items"] = item
    return result


def _aggregate_location(
    calls: Sequence[_CallShape],
    location: str,
    *,
    unresolved_context: bool = False,
) -> tuple[list[dict[str, Any]], bool]:
    merged: dict[str, _Field] = {}
    present: defaultdict[str, int] = defaultdict(int)
    conditional: defaultdict[str, bool] = defaultdict(bool)
    unresolved = unresolved_context or any(
        location in call.unresolved_locations for call in calls
    )
    for call in calls:
        shape = call.locations.get(location)
        if shape is None:
            continue
        unresolved = unresolved or shape.unresolved
        for name, field_value in shape.fields.items():
            present[name] += 1
            conditional[name] = conditional[name] or field_value.conditional
            if name in merged:
                _merge_field(merged[name], field_value)
            else:
                merged[name] = _copy_field(field_value)
    parameters: list[dict[str, Any]] = []
    for name in sorted(merged):
        value = merged[name]
        if unresolved:
            required = "unknown"
        elif conditional[name] or present[name] < len(calls):
            required = "observed_conditional"
        else:
            required = "observed_always"
        parameters.append(_field_dict(value, required=required, path=f"$.{name}"))
    return parameters, unresolved


def _contract_confidence(route: Mapping[str, Any]) -> str:
    parameters = list(route.get("path_parameters", []))
    parameters.extend(route.get("query_parameters", []))
    parameters.extend(route.get("body_parameters", []))
    nodes = list(_all_parameter_nodes(parameters))
    if not nodes:
        return "unknown"
    if route["analysis"]["unresolved_calls"] or route["analysis"]["unresolved_occurrences"]:
        return "low"
    return max(
        (str(node.get("confidence", "low")) for node in nodes),
        key=lambda value: _CONFIDENCE_ORDER.get(value, 9),
    )


def _load_bundle(snapshot: Mapping[str, Any], raw_dir: Path) -> list[tuple[dict[str, Any], str]]:
    loaded: list[tuple[dict[str, Any], str]] = []
    for file_info in sorted(snapshot.get("files", []), key=lambda item: item.get("url", "")):
        local_path = raw_dir / str(file_info.get("local_path", ""))
        if local_path.is_file():
            loaded.append((dict(file_info), local_path.read_bytes().decode("utf-8", errors="replace")))
    return loaded


def _occurrences_by_route(
    snapshot: Mapping[str, Any], loaded: Sequence[tuple[dict[str, Any], str]]
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    api_locals: dict[str, str] = {}
    exported_bases: dict[str, str] = {}
    for file_info, text in loaded:
        if re.search(r"/api-[^/]+\.js(?:\?|$)", str(file_info.get("url", ""))):
            api_locals, exported_bases = _api_exported_bases(text)
            break
    grouped: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_file: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    all_occurrences: list[dict[str, Any]] = []
    for file_info, text in loaded:
        own_bases = (
            api_locals
            if re.search(r"/api-[^/]+\.js(?:\?|$)", str(file_info.get("url", "")))
            else {}
        )
        aliases = _base_aliases(text, exported_bases, own_bases)
        all_occurrences.extend(parse_text(text, file_info=file_info, base_aliases=aliases))
    known_paths = {item["path"] for item in all_occurrences if item["method"] != "UNKNOWN"}
    for occurrence in all_occurrences:
        if occurrence["method"] == "UNKNOWN" and occurrence["path"] in known_paths:
            continue
        grouped[(occurrence["method"], occurrence["path"])].append(occurrence)
        by_file[str(occurrence["file"])].append(occurrence)
    for values in grouped.values():
        values.sort(key=lambda item: (item["file"], item["offset"], item["raw_path"]))
    return dict(grouped), dict(by_file)


def _route_document(
    route: Mapping[str, Any],
    occurrences: Sequence[Mapping[str, Any]],
    results: Sequence[_OccurrenceResult],
) -> dict[str, Any]:
    calls = [call for result in results for call in result.calls]
    unresolved_occurrences = sum(not result.calls for result in results)
    call_sites = sorted(
        (
            {
                "call_offset": call.offset,
                "column": occurrence.get("column"),
                "evidence_kind": call.evidence_kind,
                "file": occurrence.get("file"),
                "line": occurrence.get("line"),
                "route_offset": occurrence.get("offset"),
            }
            for occurrence, result in zip(occurrences, results)
            for call in result.calls
        ),
        key=lambda item: (
            str(item["file"]),
            int(item["route_offset"] or -1),
            int(item["call_offset"] or -1),
        ),
    )
    query_parameters, query_unresolved = _aggregate_location(
        calls, "query", unresolved_context=bool(unresolved_occurrences)
    )
    body_parameters, body_unresolved = _aggregate_location(
        calls, "body", unresolved_context=bool(unresolved_occurrences)
    )

    url_query = _Shape()
    for raw_path in route.get("raw_paths", []):
        _merge_shape(url_query, _raw_query_shape(str(raw_path)))
    if url_query.fields:
        synthetic = _CallShape(offset=-1, locations={"query": url_query})
        url_parameters, url_unresolved = _aggregate_location([synthetic], "query")
        by_name = {item["name"]: item for item in query_parameters}
        for item in url_parameters:
            by_name.setdefault(item["name"], item)
        query_parameters = [by_name[name] for name in sorted(by_name)]
        query_unresolved = query_unresolved or url_unresolved

    path_parameters = _path_parameters(route)
    extracted = bool(path_parameters or query_parameters or body_parameters)
    if extracted:
        status = "extracted"
    elif calls and not (query_unresolved or body_unresolved):
        status = "observed_empty"
    else:
        status = "unknown"
    document: dict[str, Any] = {
        "analysis": {
            "analyzed_calls": len(calls),
            "call_sites": call_sites,
            "route_occurrences": len(occurrences),
            "unresolved_calls": sum(bool(call.unresolved_locations) for call in calls),
            "unresolved_occurrences": unresolved_occurrences,
            "unresolved_reasons": sorted(
                {reason for result in results for reason in result.unresolved_reasons}
            ),
        },
        "body_parameters": body_parameters,
        "contract_confidence": "unknown",
        "first_occurrence": dict(route.get("first_occurrence", {})),
        "method": route["method"],
        "path": route["path"],
        "path_parameters": path_parameters,
        "query_parameters": query_parameters,
        "status": status,
    }
    document["contract_confidence"] = _contract_confidence(document)
    return document


def _route_key(method: Any, path: Any) -> tuple[str, str]:
    return str(method), str(path)


def build_route_params(
    snapshot: Mapping[str, Any],
    routes_document: Mapping[str, Any],
    raw_dir: Path,
    *,
    repo_root: Path,
    batch_results_path: Path | None = None,
    drafts_root: Path | None = None,
) -> dict[str, Any]:
    loaded = _load_bundle(snapshot, raw_dir)
    occurrences, by_file = _occurrences_by_route(snapshot, loaded)
    extracted_by_key: defaultdict[tuple[str, str], list[_OccurrenceResult]] = defaultdict(list)
    lexed_files = 0
    for file_info, text in loaded:
        file_occurrences = by_file.get(str(file_info.get("local_path", "")), [])
        if not file_occurrences:
            continue
        lexed = _tokenize(text)
        lexed_files += 1
        for occurrence in file_occurrences:
            extracted_by_key[_route_key(occurrence["method"], occurrence["path"])].append(
                _extract_occurrence(lexed, occurrence)
            )

    route_documents: list[dict[str, Any]] = []
    for route in routes_document.get("routes", []):
        key = _route_key(route["method"], route["path"])
        route_occurrences = occurrences.get(key, [])
        results = extracted_by_key.get(key, [])
        route_documents.append(_route_document(route, route_occurrences, results))
    route_documents.sort(key=lambda item: (item["path"], item["method"]))
    return {
        "parser": {
            "known_limitations": PARAM_PARSER_LIMITATIONS,
            "strategy": "existing route occurrence scan plus balanced-token request binding and object-shape inference",
        },
        "routes": route_documents,
        "schema_version": PARAM_SCHEMA_VERSION,
        "source": {
            "bundle_complete": bool(snapshot.get("summary", {}).get("complete", False)),
            "bundle_files": len(snapshot.get("files", [])),
            "bundle_id": snapshot.get("bundle_id"),
            "lexed_route_files": lexed_files,
            "route_source_schema_version": routes_document.get("schema_version"),
        },
        "summary": _summary(route_documents),
        "validation": _batch_validation(
            route_documents,
            comparison_path,
            repo_root=repo_root,
            batch_results_path=batch_results_path,
            drafts_root=drafts_root,
        ),
    }


def extract_route_params(
    snapshot_path: Path,
    routes_path: Path,
    raw_dir: Path,
    output_path: Path,
    *,
    repo_root: Path,
    batch_results_path: Path | None = None,
    drafts_root: Path | None = None,
) -> dict[str, Any]:
    result = build_route_params(
        read_json(snapshot_path),
        read_json(routes_path),
        raw_dir,
        repo_root=repo_root,
        batch_results_path=batch_results_path,
        drafts_root=drafts_root,
    )
    write_json(output_path, result)
    return result
