"""Typed evidence boundaries for static Census observations, not API health."""
from __future__ import annotations

from typing import Any
from html.parser import HTMLParser

from gravity_insight.contracts.envelope_obligations import (
    CompletenessState, DataCompleteness, DiagnosticCategory, DiagnosticEvidence,
    DiagnosticState, EnvelopeObligations, ExecutionState, ExecutionStatus,
    MutationCertainty, MutationState, SemanticState, SemanticValidity, serialize_envelope,
)
from .io import sha256_bytes


class EntryHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.module_scripts: list[str] = []
        self.module_preloads: list[str] = []
        self.manifests: list[str] = []
        self.other_scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "script" and values.get("src"):
            if values.get("type", "").lower() == "module":
                self.module_scripts.append(values["src"])
            else:
                self.other_scripts.append(values["src"])
        if tag.lower() == "link" and values.get("href"):
            rel = set(values.get("rel", "").lower().split())
            if "modulepreload" in rel:
                self.module_preloads.append(values["href"])
            if "manifest" in rel:
                self.manifests.append(values["href"])


def census_obligations(
    code: str, *, graph_complete: bool = False, failed: bool = False,
    category: str = "upstream", retryable: bool = False,
) -> EnvelopeObligations:
    return EnvelopeObligations(
        ExecutionStatus(ExecutionState.FAILED if failed else ExecutionState.COMPLETE, code),
        DataCompleteness(CompletenessState.COMPLETE if graph_complete else CompletenessState.UNKNOWN,
            code, {"scope": "same_origin_static_js_graph", "platform_complete": False}),
        SemanticValidity(SemanticState.UNKNOWN, ("CENSUS_API_SEMANTICS_UNVERIFIED",)),
        DiagnosticEvidence(DiagnosticState.AVAILABLE, (code,), code,
            DiagnosticCategory(category), retryable) if failed else DiagnosticEvidence(DiagnosticState.NONE),
        MutationCertainty(MutationState.NOT_APPLICABLE, "CENSUS_READ_ONLY"),
    )


def entry_observation(
    site_url: str, baseline: dict[str, Any], response: Any,
    current_entries: list[str], build_info: dict[str, Any], attempts: int,
) -> dict[str, Any]:
    baseline_entries = sorted(str(item) for item in baseline.get("entry_urls", []))
    current_hash = sha256_bytes(response.content)
    entry_changed = current_entries != baseline_entries
    html_changed = current_hash != baseline.get("html", {}).get("sha256")
    changed = entry_changed or html_changed
    payload = {
        "schema_version": 1,
        "observation_state": "entry_change_observed" if changed else "entry_unchanged",
        "drift_conclusion_available": False,
        "api_breaking_confirmed": False,
        "next_action": "Fetch a complete graph and compare routes; entry identities alone do not prove API drift.",
        "site_url": site_url,
        "request_attempts": attempts,
        "baseline_entry_urls": baseline_entries,
        "current_entry_urls": current_entries,
        "entry_changed": entry_changed,
        "baseline_html_sha256": baseline.get("html", {}).get("sha256"),
        "current_html_sha256": current_hash,
        "html_changed": html_changed,
        "upstream_changed": changed,
        "etag": response.headers.get("ETag"),
        "last_modified": response.headers.get("Last-Modified"),
        "build_info": build_info,
        "note": "No JS was downloaded; hashed entry filenames are the lightweight content-version signal.",
    }
    return serialize_envelope(payload, census_obligations("CENSUS_ENTRY_OBSERVATION"))
