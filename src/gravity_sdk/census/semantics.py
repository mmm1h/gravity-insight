"""Static route semantics used by Census coverage accounting."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Iterable


def _contains_any(value: str, tokens: Iterable[str]) -> bool:
    return any(token in value for token in tokens)


def _contains_action(value: str, actions: Iterable[str]) -> bool:
    return any(
        re.search(rf"(?:^|[/_]){re.escape(action)}(?:[/_]|$)", value) is not None
        for action in actions
    )


def _classify_read_signal(
    method: str,
    path: str,
    evidence: str,
    confidence: str,
    confirmed_read_routes: set[tuple[str, str]],
) -> tuple[str, str, list[str]]:
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "uncovered_read", confidence, [evidence]
    if method == "POST":
        if (method, path) in confirmed_read_routes:
            return "uncovered_read", "reviewed", ["probe_read_confirmation", evidence]
        return "unsafe_unknown", "unverified", [evidence]
    return "static_read_candidate", confidence, [evidence]


def classify_route_semantics(
    method: str,
    path: str,
    classification: Mapping[str, Any] | None,
    confirmed_read_routes: set[tuple[str, str]],
) -> tuple[str, str, list[str]]:
    if not classification:
        return classify_semantics(method, path, confirmed_read_routes)
    name = str(classification["classification"])
    evidence = f"route_registry:{classification['reason_code']}"
    if name == "read":
        return _classify_read_signal(
            method, path, evidence, "registered", confirmed_read_routes
        )
    status = {
        "write": "uncovered_write",
        "export": "uncovered_export",
        "auth": "uncovered_auth_or_proxy",
        "proxy": "uncovered_auth_or_proxy",
        "non_api": "unsupported_non_api",
    }[name]
    return status, "registered", [evidence]


def classify_route_accounting(
    *,
    covered: bool,
    reserved: bool,
    nonstable_stability: str | None,
    registered: bool,
    status: str,
) -> tuple[str, str]:
    if covered:
        return "covered_executable", "executable"
    if reserved:
        return "accounted_blocked_write", "contract_only"
    if nonstable_stability:
        accounting = {
            "blocked_write": "accounted_blocked_write",
            "blocked_privacy": "accounted_blocked_privacy",
            "permission_unavailable": "accounted_permission_unavailable",
            "deprecated": "accounted_deprecated",
            "experimental": "accounted_experimental",
        }.get(nonstable_stability, "accounted_nonstable")
        return accounting, "catalog_only"
    if registered and status not in {
        "uncovered_read", "static_read_candidate", "unsafe_unknown"
    }:
        return "accounted_unsupported", "unsupported"
    if status in {"uncovered_read", "static_read_candidate"}:
        return (
            "accounted_read_candidate"
            if status == "uncovered_read"
            else "accounted_static_read_candidate",
            "candidate",
        )
    if status == "unsafe_unknown":
        return "accounted_unsafe_unknown", "blocked"
    if status == "uncovered_export":
        return "accounted_export_candidate", "candidate"
    return "unaccounted", "unclassified"


def classify_semantics(
    method: str,
    path: str,
    confirmed_read_routes: set[tuple[str, str]] | None = None,
) -> tuple[str, str, list[str]]:
    confirmed_read_routes = confirmed_read_routes or set()
    lower = path.lower()
    if _contains_any(
        lower,
        (
            "/auth", "login", "logout", "oauth", "sso/", "token/", "captcha",
            "/proxy/", "/gateway/", "callback", "/post/api/", "/query_api/",
        ),
    ):
        return "uncovered_auth_or_proxy", "high", ["auth_or_proxy_path_token"]
    if _contains_action(lower, ("delete", "remove", "clear")):
        return "uncovered_write", "high", ["destructive_action_path_token"]
    if _contains_any(
        lower, ("export", "download", "/excel", "/csv", "/xlsx", "file_download")
    ):
        return "uncovered_export", "high", ["export_path_token"]
    if method in {"PUT", "PATCH", "DELETE"}:
        return "uncovered_write", "high", ["mutating_http_method"]
    write_actions = (
        "create", "add", "update", "edit", "delete", "remove", "save", "upload",
        "import", "copy", "move", "bind", "unbind", "enable", "disable", "submit",
        "approve", "execute", "cancel", "start", "stop", "sync", "reset", "push",
        "share", "collect", "clear", "kill", "terminate",
    )
    if _contains_action(lower, write_actions):
        return "uncovered_write", "medium", ["write_action_path_token"]
    read_tokens = (
        "/list", "/get", "/detail", "/query", "/search", "/tree", "/info",
        "/status", "/count", "/stat", "/trend", "/preview", "/check", "/validate",
        "/evaluate", "/calc", "/enums", "/options", "/report/", "/filters",
        "/components", "/favorites", "/campaigns", "/ad_groups", "/batch_options",
        "_detail/", "_list/", "_get/", "_info/",
    )
    if method in {"GET", "HEAD", "OPTIONS"}:
        return "uncovered_read", "high", ["safe_http_method"]
    if _contains_any(lower, read_tokens):
        return _classify_read_signal(
            method, path, "read_action_path_token", "medium", confirmed_read_routes
        )
    return "unclassified", "low", ["insufficient_semantic_evidence"]


__all__ = [
    "classify_route_accounting",
    "classify_route_semantics",
    "classify_semantics",
]
