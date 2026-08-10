from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from .io import json_bytes, read_json, write_json
from .normalize import comparison_path
from .params import (
    _Lexed,
    _call_open_for_route,
    _enclosing_scope,
    _load_bundle,
    _occurrences_by_route,
    _segments,
    _tokenize,
    _top_level_token,
)
from .parser import _line_column, _line_starts


RESPONSE_SCHEMA_VERSION = "gravity-census.route-response-fields.v1"
_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}
_CONSUMER_METHODS = {
    "concat",
    "every",
    "filter",
    "find",
    "findIndex",
    "flat",
    "flatMap",
    "forEach",
    "includes",
    "join",
    "length",
    "map",
    "push",
    "reduce",
    "reverse",
    "slice",
    "some",
    "sort",
    "splice",
    "toString",
}
_ITERATION_METHODS = {"every", "filter", "find", "findIndex", "flatMap", "forEach", "map", "some"}


RESPONSE_PARSER_LIMITATIONS = [
    "Only response consumers lexically bound to the exact route call are emitted; same-chunk columns and unrelated constants are intentionally ignored.",
    "The extractor proves that frontend code reads a key, not that every successful server response returns it.",
    "Static evidence cannot prove field types, requiredness, privacy classification, or safe external exposure.",
    "Consumers hidden behind stores imported from another chunk, computed keys, generic adapters, or runtime registries can be missed.",
    "A minified one-character binding can be shadowed in a nested scope, so its direct-member evidence is capped at medium confidence.",
]


def _binding_alias(lexed: _Lexed, call_open: int, key: str) -> str | None:
    tokens = lexed.tokens
    equals: int | None = None
    for index in range(call_open - 1, max(-1, call_open - 16), -1):
        if tokens[index].value == "=":
            equals = index
            break
        if tokens[index].value in {";", "=>"}:
            return None
    if equals is None or equals == 0 or tokens[equals - 1].value != "}":
        return None
    object_close = equals - 1
    object_open = lexed.pairs.get(object_close)
    if object_open is None:
        return None
    for start, end in _segments(lexed, object_open + 1, object_close):
        colon = _top_level_token(lexed, start, end, {":"})
        if colon == start + 1 and tokens[start].value == key:
            if colon + 1 < end and tokens[colon + 1].kind == "identifier":
                return tokens[colon + 1].value
        if colon is None and start < end and tokens[start].value == key:
            return key
    return None


def _member_chain(lexed: _Lexed, start: int, end: int) -> tuple[list[str], int]:
    members: list[str] = []
    cursor = start + 1
    while cursor + 1 < end:
        if lexed.tokens[cursor].value not in {".", "?."}:
            break
        member = lexed.tokens[cursor + 1]
        if member.kind != "identifier":
            break
        members.append(member.value)
        cursor += 2
    return members, cursor


def _response_members(members: Sequence[str]) -> tuple[list[str], str | None]:
    values = list(members)
    if values and values[0] == "value":
        values.pop(0)
    method: str | None = None
    for index, value in enumerate(values):
        if value in _CONSUMER_METHODS:
            method = value
            values = values[:index]
            break
    return values, method


def _path(parts: Sequence[str]) -> str:
    return "data." + ".".join(parts)


def _callback_parameter(
    lexed: _Lexed, call_open: int
) -> tuple[str | None, tuple[int, int] | None]:
    call_close = lexed.pairs.get(call_open)
    if call_close is None:
        return None, None
    arguments = _segments(lexed, call_open + 1, call_close)
    if not arguments:
        return None, None
    start, end = arguments[0]
    arrow = next(
        (index for index in range(start, end) if lexed.tokens[index].value == "=>"),
        None,
    )
    if arrow is None or arrow == start:
        return None, None
    parameter: str | None = None
    previous = lexed.tokens[arrow - 1]
    if previous.kind == "identifier":
        parameter = previous.value
    elif previous.value == ")":
        open_index = lexed.pairs.get(arrow - 1)
        if open_index is not None:
            identifiers = [
                token.value
                for token in lexed.tokens[open_index + 1 : arrow - 1]
                if token.kind == "identifier"
            ]
            if len(identifiers) == 1:
                parameter = identifiers[0]
    if parameter is None or arrow + 1 >= end:
        return None, None
    body_start = arrow + 1
    if lexed.tokens[body_start].value == "{" and body_start in lexed.pairs:
        return parameter, (body_start + 1, lexed.pairs[body_start])
    return parameter, (body_start, end)


def _callback_fields(
    lexed: _Lexed,
    *,
    call_open: int,
    receiver: Sequence[str],
) -> list[tuple[str, int]]:
    parameter, body = _callback_parameter(lexed, call_open)
    if parameter is None or body is None:
        return []
    start, end = body
    result: list[tuple[str, int]] = []
    for index in range(start, end):
        if lexed.tokens[index].value != parameter:
            continue
        members, _ = _member_chain(lexed, index, end)
        item_members, _ = _response_members(members)
        if not item_members:
            continue
        item_path = _path([*receiver[:-1], receiver[-1] + "[]", *item_members])
        result.append((item_path, lexed.tokens[index].start))
    return result


def _destructured_fields(
    lexed: _Lexed, alias_index: int, members_end: int
) -> list[tuple[str, int]]:
    tokens = lexed.tokens
    if alias_index == 0 or tokens[alias_index - 1].value != "=":
        return []
    equals = alias_index - 1
    if equals == 0 or tokens[equals - 1].value != "}":
        return []
    object_close = equals - 1
    object_open = lexed.pairs.get(object_close)
    if object_open is None:
        return []
    members, _ = _member_chain(lexed, alias_index, members_end)
    if members != ["value"]:
        return []
    result: list[tuple[str, int]] = []
    for start, end in _segments(lexed, object_open + 1, object_close):
        colon = _top_level_token(lexed, start, end, {":"})
        key_index = start if colon is None else start
        if key_index < end and tokens[key_index].kind in {"identifier", "string"}:
            result.append((_path([tokens[key_index].value]), tokens[key_index].start))
    return result


def _evidence(
    lexed: _Lexed,
    occurrence: Mapping[str, Any],
    *,
    consumer_offset: int,
    kind: str,
    confidence: str,
    confidence_reason: str,
) -> dict[str, Any]:
    starts = getattr(lexed, "_response_line_starts", None)
    if starts is None:
        starts = _line_starts(lexed.text)
        setattr(lexed, "_response_line_starts", starts)
    line, column = _line_column(starts, consumer_offset)
    return {
        "chunk": str(occurrence.get("file", "")),
        "route_offset": int(occurrence.get("offset", -1)),
        "consumer_offset": consumer_offset,
        "line": line,
        "column": column,
        "consumer_kind": kind,
        "confidence": confidence,
        "confidence_reason": confidence_reason,
    }


def _add_field(
    fields: dict[str, dict[str, Any]],
    path: str,
    evidence: Mapping[str, Any],
) -> None:
    if not path.startswith("data.") or path.endswith("."):
        return
    row = fields.setdefault(path, {"path": path, "confidence": "low", "evidence": []})
    confidence = str(evidence["confidence"])
    if _CONFIDENCE_ORDER[confidence] < _CONFIDENCE_ORDER[str(row["confidence"])]:
        row["confidence"] = confidence
    signature = (
        evidence["chunk"],
        evidence["route_offset"],
        evidence["consumer_offset"],
        evidence["consumer_kind"],
    )
    existing = {
        (item["chunk"], item["route_offset"], item["consumer_offset"], item["consumer_kind"])
        for item in row["evidence"]
    }
    if signature not in existing:
        row["evidence"].append(dict(evidence))


def _bound_data_fields(
    lexed: _Lexed,
    occurrence: Mapping[str, Any],
    *,
    call_open: int,
) -> tuple[dict[str, dict[str, Any]], int]:
    alias = _binding_alias(lexed, call_open, "data")
    if alias is None:
        return {}, 0
    call_close = lexed.pairs.get(call_open)
    if call_close is None:
        return {}, 0
    _, scope_end = _enclosing_scope(lexed, call_open)
    confidence = "high" if len(alias) > 1 else "medium"
    reason = (
        "exact_route_reactive_data_binding"
        if confidence == "high"
        else "exact_route_binding_with_one_character_shadowing_risk"
    )
    fields: dict[str, dict[str, Any]] = {}
    for index in range(call_close + 1, scope_end):
        if lexed.tokens[index].value != alias:
            continue
        members, chain_end = _member_chain(lexed, index, scope_end)
        response, method = _response_members(members)
        if response:
            _add_field(
                fields,
                _path(response),
                _evidence(
                    lexed,
                    occurrence,
                    consumer_offset=lexed.tokens[index].start,
                    kind="reactive_data_member",
                    confidence=confidence,
                    confidence_reason=reason,
                ),
            )
        if method in _ITERATION_METHODS and response and chain_end < scope_end:
            if lexed.tokens[chain_end].value == "(":
                for item_path, offset in _callback_fields(
                    lexed, call_open=chain_end, receiver=response
                ):
                    _add_field(
                        fields,
                        item_path,
                        _evidence(
                            lexed,
                            occurrence,
                            consumer_offset=offset,
                            kind="iterated_item_member",
                            confidence="medium",
                            confidence_reason="callback_receiver_is_exact_route_data_member",
                        ),
                    )
        for destructured_path, offset in _destructured_fields(lexed, index, scope_end):
            _add_field(
                fields,
                destructured_path,
                _evidence(
                    lexed,
                    occurrence,
                    consumer_offset=offset,
                    kind="response_destructuring",
                    confidence=confidence,
                    confidence_reason=reason,
                ),
            )
    return fields, 1


def _inline_result_fields(
    lexed: _Lexed,
    occurrence: Mapping[str, Any],
    *,
    call_open: int,
) -> dict[str, dict[str, Any]]:
    call_close = lexed.pairs.get(call_open)
    if call_close is None:
        return {}
    _, scope_end = _enclosing_scope(lexed, call_open)
    limit = min(scope_end, call_close + 100)
    fields: dict[str, dict[str, Any]] = {}
    for index in range(call_close + 1, limit):
        token = lexed.tokens[index]
        if token.value == ";":
            break
        if token.value != "data" or index == 0:
            continue
        if lexed.tokens[index - 1].value not in {".", "?."}:
            continue
        members, _ = _member_chain(lexed, index, limit)
        response, _ = _response_members(members)
        if not response:
            continue
        _add_field(
            fields,
            _path(response),
            _evidence(
                lexed,
                occurrence,
                consumer_offset=token.start,
                kind="inline_await_member",
                confidence="high",
                confidence_reason="member_chain_descends_from_exact_route_call_result",
            ),
        )
    return fields


def _merge_fields(
    target: dict[str, dict[str, Any]], source: Mapping[str, Mapping[str, Any]]
) -> None:
    for path, row in source.items():
        for evidence in row.get("evidence", []):
            _add_field(target, path, evidence)


def _route_fields(
    occurrences: Sequence[Mapping[str, Any]],
    lexed_by_file: Mapping[str, _Lexed],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fields: dict[str, dict[str, Any]] = {}
    bindings = 0
    unresolved = Counter()
    for occurrence in occurrences:
        lexed = lexed_by_file.get(str(occurrence.get("file", "")))
        if lexed is None:
            unresolved["chunk_not_loaded"] += 1
            continue
        token_index = lexed.token_at_offset(int(occurrence["offset"]))
        if token_index is None:
            unresolved["route_token_not_found"] += 1
            continue
        call_open = _call_open_for_route(lexed, token_index)
        if call_open is None:
            unresolved["request_call_not_found"] += 1
            continue
        bound, binding_count = _bound_data_fields(
            lexed, occurrence, call_open=call_open
        )
        bindings += binding_count
        _merge_fields(fields, bound)
        inline = _inline_result_fields(lexed, occurrence, call_open=call_open)
        _merge_fields(fields, inline)
        if not bound and not inline:
            unresolved["response_binding_not_resolved"] += 1
    rows = [fields[path] for path in sorted(fields)]
    for row in rows:
        row["evidence"].sort(
            key=lambda item: (
                item["chunk"], item["route_offset"], item["consumer_offset"], item["consumer_kind"]
            )
        )
    return rows, {
        "route_occurrences": len(occurrences),
        "response_bindings": bindings,
        "unresolved_reasons": dict(sorted(unresolved.items())),
    }


def build_route_response_fields(
    snapshot: Mapping[str, Any],
    routes_document: Mapping[str, Any],
    raw_dir: Path,
) -> dict[str, Any]:
    loaded = _load_bundle(snapshot, raw_dir)
    occurrences, _ = _occurrences_by_route(snapshot, loaded)
    lexed_by_file = {
        str(file_info.get("local_path", "")): _tokenize(text)
        for file_info, text in loaded
    }
    route_rows: list[dict[str, Any]] = []
    confidence = Counter()
    evidence_points = 0
    for route in routes_document.get("routes", []):
        key = (str(route.get("method", "")), str(route.get("path", "")))
        fields, analysis = _route_fields(occurrences.get(key, []), lexed_by_file)
        confidence.update(str(item["confidence"]) for item in fields)
        evidence_points += sum(len(item["evidence"]) for item in fields)
        route_rows.append(
            {
                "method": key[0],
                "path": key[1],
                "status": "extracted" if fields else "unknown",
                "fields": fields,
                "analysis": analysis,
            }
        )
    route_rows.sort(key=lambda item: (item["path"], item["method"]))
    missing = [
        str(item.get("local_path", ""))
        for item in snapshot.get("files", [])
        if not (raw_dir / str(item.get("local_path", ""))).is_file()
    ]
    return {
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "source": {
            "site_url": snapshot.get("site_url"),
            "bundle_id": snapshot.get("bundle_id"),
            "bundle_files": len(snapshot.get("files", [])),
            "bundle_complete": bool(snapshot.get("summary", {}).get("complete", False)),
            "scanned_chunks": len(loaded),
            "missing_local_files": sorted(missing),
        },
        "extractor": {
            "strategy": "lexical exact-route response binding and direct consumer-chain analysis",
            "confidence_model": {
                "high": "exact route result or multi-character reactive data binding with direct member access",
                "medium": "exact route one-character binding, or item field read in a callback directly rooted at an exact response member",
                "low": "reserved; ambiguous same-chunk evidence is not emitted",
            },
            "known_limitations": RESPONSE_PARSER_LIMITATIONS,
            "literal_values_persisted": False,
        },
        "summary": {
            "routes_total": len(route_rows),
            "routes_with_fields": sum(bool(item["fields"]) for item in route_rows),
            "fields": sum(len(item["fields"]) for item in route_rows),
            "evidence_points": evidence_points,
            "confidence": {
                level: confidence.get(level, 0) for level in ("high", "medium", "low")
            },
        },
        "routes": route_rows,
    }


def extract_route_response_fields(
    snapshot_path: Path,
    routes_path: Path,
    raw_dir: Path,
    output_path: Path,
) -> dict[str, Any]:
    result = build_route_response_fields(
        read_json(snapshot_path), read_json(routes_path), raw_dir
    )
    write_json(output_path, result)
    return result


def _route_key(method: Any, path: Any) -> tuple[str, str]:
    return str(method).upper(), comparison_path(str(path))


def _leaf_fields(fields: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    paths = {str(item.get("path", "")) for item in fields}
    result: list[Mapping[str, Any]] = []
    for item in fields:
        path = str(item.get("path", ""))
        prefixes = (path + ".", path + "[].")
        if any(other != path and other.startswith(prefixes) for other in paths):
            continue
        result.append(item)
    return result


def apply_response_fields_to_drafts(
    response_document: Mapping[str, Any], drafts_root: Path
) -> dict[str, Any]:
    indexed = {
        _route_key(item.get("method"), item.get("path")): (index, item)
        for index, item in enumerate(response_document.get("routes", []))
    }
    summary: dict[str, Any] = {
        "response_schema_unverified": 0,
        "route_matched": 0,
        "with_static_candidates": 0,
        "candidate_fields_added": 0,
        "candidate_fields_total": 0,
        "files_changed": 0,
        "confidence": {"high": 0, "medium": 0, "low": 0},
    }
    for draft_path in sorted(drafts_root.glob("*.json")):
        source = read_json(draft_path)
        original = json_bytes(source)
        draft = source.get("draft", {})
        operation = source.get("operation", {})
        blockers = draft.get("blockers", []) if isinstance(draft, Mapping) else []
        response_blocker = next(
            (
                item
                for item in blockers
                if isinstance(item, Mapping)
                and item.get("code") == "response_schema_unverified"
            ),
            None,
        )
        if response_blocker is None or not isinstance(operation, Mapping):
            continue
        summary["response_schema_unverified"] += 1
        matched = indexed.get(
            _route_key(operation.get("upstream_method"), operation.get("path_template"))
        )
        if matched is None:
            continue
        route_index, route = matched
        summary["route_matched"] += 1
        selected = _leaf_fields(route.get("fields", []))
        if not selected:
            continue
        summary["with_static_candidates"] += 1
        for item in selected:
            level = str(item.get("confidence", "low"))
            summary["confidence"][level] += 1
        candidates = draft.get("candidate_fields", [])
        if not isinstance(candidates, list):
            candidates = []
        by_path = {
            str(item.get("path")): item
            for item in candidates
            if isinstance(item, Mapping)
        }
        before = len(by_path)
        for item in selected:
            path = str(item.get("path", ""))
            by_path.setdefault(
                path,
                {
                    "path": path,
                    "types": ["unknown"],
                    "presence": "unknown",
                    "privacy_classification": "manual_review",
                    "classification_reason": "frontend_static_consumer_unreviewed",
                    "expose": False,
                },
            )
        added = len(by_path) - before
        draft["candidate_fields"] = [by_path[path] for path in sorted(by_path)]
        response_blocker["evidence"] = (
            f"src/gravity_sdk/census/data/route-response-fields.json#/routes/{route_index}"
        )
        summary["candidate_fields_added"] += added
        summary["candidate_fields_total"] += len(selected)
        if json_bytes(source) != original:
            write_json(draft_path, source)
            summary["files_changed"] += 1
    covered = int(summary["with_static_candidates"])
    summary["average_candidate_fields"] = (
        round(int(summary["candidate_fields_total"]) / covered, 3) if covered else 0.0
    )
    summary["blockers_advanced_by_static_plus_probe"] = 0
    return summary
