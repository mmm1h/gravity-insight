"""Compact host-facing projection of canonical Agent products and gaps."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from .caller_language import caller_language_fields
from .product_inventory import canonical_capability_cards
from .unavailable import registered_unavailable_gaps
from ..host_effect_sources import SOURCE_SCHEMA_VERSION, host_source
from ..contracts.envelope_obligations import (
    CompletenessState, DataCompleteness, DiagnosticEvidence, DiagnosticState,
    EnvelopeObligations, ExecutionState, ExecutionStatus, MutationCertainty,
    MutationState, SemanticState, SemanticValidity, serialize_envelope,
)


CATALOG_SCHEMA_VERSION = "gravity.host-product-catalog.v1"
SELECTION_SCHEMA_VERSION = "gravity.host-product-selection.v1"
MAX_CANDIDATES = 5
MUTATION_SELECTION_BOUNDARY = (
    "Selection is read-only; preview and execute still require the governed user authorization flow."
)
GAP_SELECTION_BOUNDARY = (
    "Unavailable and never executable; do not substitute a neighboring product."
)
HOST_WORKFLOW_REF = (
    "https://github.com/mmm1h/gravity-insight/blob/main/docs/agent-workflow.md"
)
HOST_SELECTION_POLICY = (
    "Known current contracts use dedicated execution without catalog or lexical reselection.",
    "For unknown capabilities, read `agent-catalog host` and pass gravity.host-product-selection.v1 "
    "with `--routing host_catalog --host-selection` or routing omitted.",
    "Omit --routing to keep the recognizer floor only when the caller cannot produce a host selection.",
    "Use authorized project sources for missing facts; report remaining inputs. Repair invalid/stale "
    "selections and stop on permission/contract/quality failures; never silently switch routes, "
    "products, accounts or raw SQL.",
    "Reuse existing task budgets. Do not poll both arms with unchanged input.",
    "Prefer a matching workspace recipe because it owns project semantics.",
    "Prefer a registered composite when it already covers the requested context.",
    "Otherwise select a callable stable Insight operation.",
    "Use governed SQL only when Insight cannot express equivalent semantics.",
)


def host_product_catalog(client: Any) -> dict[str, Any]:
    """Project the existing card/gap owners without raw operations or execution."""

    cards = canonical_capability_cards(client)
    gaps = registered_unavailable_gaps()
    entries = tuple(sorted(
        (*(_product_entry(card) for card in cards), *(_gap_entry(gap) for gap in gaps)),
        key=lambda item: str(item["catalog_ref"]),
    ))
    fingerprint = _fingerprint(entries)
    catalog = {
        "schema_version": CATALOG_SCHEMA_VERSION,
        "ok": True,
        "status": "success",
        "offline": True,
        "network_called": False,
        "mode": "host_product_catalog",
        "catalog_sha256": fingerprint,
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "selection_schema_version": SELECTION_SCHEMA_VERSION,
        "workflow_ref": HOST_WORKFLOW_REF,
        "selection_rules": {
            "priority": (
                "Known current contracts: call dedicated CLI/SDK/Composite/Plan directly. "
                "Unknown capability: read this catalog and needed describe/schema, then "
                "submit host-selection. Use recognizer only when the host cannot reliably select."
            ),
            "candidate_count": f"0..{MAX_CANDIDATES}",
            "zero": "return abstained; the SDK emits its canonical routing gap",
            "one": "reference exactly one catalog_ref",
            "many": "use only for independent intents; the SDK returns MULTIPLE_INTENTS",
            "control_boundary": (
                "catalog_ref is validated as sdk_contract/instruction; host output "
                "never supplies operation, path, or Plan control identities"
            ),
            "failure_boundary": (
                "Missing business facts: consult authorized project sources, then report missing inputs. "
                "Invalid/stale selection, permission denial or contract/quality drift: repair or stop; "
                "never silently switch router, product, account or raw SQL."
            ),
            "budget": (
                "Reuse existing task budgets for catalog refresh, fallback and retries; "
                "do not poll both arms for unchanged input."
            ),
            "observation_boundary": (
                "Validated selection proves receipt and validation only, not host catalog reading "
                "or execution. Verify host order with tool events; otherwise unknown/not_measured."
            ),
        },
        "response_schema": host_product_selection_schema(),
        "selection_template": host_product_selection_template(fingerprint),
        "catalog_refs": [str(item["catalog_ref"]) for item in entries],
        "entries": [dict(item) for item in entries],
    }
    validate_host_catalog_projection(catalog, product_cards=cards, gaps=gaps)
    obligations = discovery_obligations()
    return serialize_envelope(catalog, obligations)


def discovery_obligations(gaps: Sequence[Mapping[str, Any]] = ()) -> EnvelopeObligations:
    """Discovery never validates product inputs or executes the selected product."""

    codes = tuple(dict.fromkeys(str(gap.get("code") or "DISCOVERY_GAP_REPORTED") for gap in gaps))
    return EnvelopeObligations(
        ExecutionStatus(ExecutionState.NOT_STARTED, "DISCOVERY_ONLY"),
        DataCompleteness(CompletenessState.NOT_APPLICABLE, "NO_PRODUCT_DATA_READ"),
        SemanticValidity(SemanticState.UNKNOWN, ("PRODUCT_INPUTS_NOT_VALIDATED",)),
        DiagnosticEvidence(DiagnosticState.INCOMPLETE if codes else DiagnosticState.NONE, codes),
        MutationCertainty(MutationState.NOT_ATTEMPTED, "DISCOVERY_ONLY"),
    )


def host_workflow(prefix: list[str]) -> list[dict[str, Any]]:
    """Short executable entry hints; the linked workflow owns the full order."""

    return [
        {
            "step": "known_contract",
            "when": "a suitable capability and its current input contract are already known",
            "action": "Call its dedicated CLI/SDK/Composite/Plan directly; no rediscovery.",
        },
        {
            "step": "unknown_capability",
            "argv": [*prefix, "agent-catalog", "host"],
            "action": "Read needed describe/schema, then submit the existing host-selection.",
            "network_required": False,
        },
        {
            "step": "selection_floor",
            "when": "host cannot reliably select or its selection protocol is unavailable",
            "argv": [*prefix, "agent", "<query>", "--routing", "recognizer"],
            "network_required": False,
        },
        {
            "step": "execute",
            "action": "After filling inputs and validating the contract, use the card's dedicated entry; check results and limits.",
        },
    ]


def host_product_selection_template(
    catalog_sha256: str = "<catalog_sha256 from agent-catalog host>",
    query: str = "<query>",
) -> dict[str, Any]:
    """Return one copyable gravity.host-product-selection.v1 skeleton."""

    return {
        "schema_version": SELECTION_SCHEMA_VERSION,
        "catalog_sha256": catalog_sha256,
        "query": query,
        "decision": "selected",
        "reason": {
            "summary": "<why this catalog_ref matches the query>",
            "needs_clarification": False,
        },
        "candidates": [
            {
                "catalog_ref": "<one catalog_ref from catalog_refs>",
                "reason": {
                    "goal_match": "<why this product matches>",
                    "boundary_check": "<why neighboring products were excluded>",
                },
            }
        ],
    }


def host_selection_upgrade_contract(query: str) -> dict[str, Any]:
    """Declare the host-arm contract a source-free caller can copy from the envelope."""

    selected = query or "<query>"
    return {
        "when": (
            "the caller can emit gravity.host-product-selection.v1 after "
            "reading the host catalog, and has not already tried the same unchanged input"
        ),
        "workflow_ref": HOST_WORKFLOW_REF,
        "next_action": (
            "This answer is the offline recognizer floor. Read "
            "`gravity agent-catalog host`, copy `selection_template`, set "
            "`query` to this same query and `catalog_sha256` to the catalog "
            "fingerprint, pick one `catalog_ref` from `catalog_refs`, then "
            "resubmit with `--routing host_catalog --host-selection` within the existing budget. "
            "Do not alternate arms on unchanged input or reinterpret a protocol/permission "
            "failure as fallback authorization. Known current contracts need no rediscovery."
        ),
        "selection_schema_version": SELECTION_SCHEMA_VERSION,
        "selection_schema": host_product_selection_schema(),
        "selection_example": host_product_selection_template(query=selected),
    }


def host_product_selection_schema() -> dict[str, Any]:
    """Return the vendor-neutral strict JSON response contract."""

    reason = {
        "type": "object",
        "additionalProperties": False,
        "required": ["goal_match", "boundary_check"],
        "properties": {
            "goal_match": {"type": "string", "minLength": 1},
            "boundary_check": {"type": "string", "minLength": 1},
        },
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version", "catalog_sha256", "query", "decision",
            "reason", "candidates",
        ],
        "properties": {
            "schema_version": {"const": SELECTION_SCHEMA_VERSION},
            "catalog_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            "query": {"type": "string", "minLength": 1},
            "decision": {
                "enum": ["selected", "multiple_intents", "abstained"],
            },
            "reason": {
                "type": "object",
                "additionalProperties": False,
                "required": ["summary", "needs_clarification"],
                "properties": {
                    "summary": {"type": "string", "minLength": 1},
                    "needs_clarification": {"type": "boolean"},
                },
            },
            "candidates": {
                "type": "array",
                "maxItems": MAX_CANDIDATES,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["catalog_ref", "reason"],
                    "properties": {
                        "catalog_ref": {"type": "string", "minLength": 1},
                        "reason": reason,
                    },
                },
            },
        },
    }


def host_catalog_sources(catalog: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Build model-external sdk_contract source records for every catalog identity."""

    fingerprint = str(catalog["catalog_sha256"])
    return {
        str(entry["catalog_ref"]): host_source(
            "sdk_contract",
            "instruction",
            {
                "catalog_sha256": fingerprint,
                "identity": str(entry["catalog_ref"]),
                "identity_kind": str(entry["identity_kind"]),
            },
        )
        for entry in catalog["entries"]
    }


def validate_host_catalog_projection(
    catalog: Mapping[str, Any],
    *,
    product_cards: Sequence[Mapping[str, Any]],
    gaps: Sequence[Mapping[str, Any]],
) -> None:
    """Mechanically prove the compact identities and owner fields are equal."""

    entries = catalog.get("entries")
    if not isinstance(entries, list):
        raise RuntimeError("host product catalog entries must be an array")
    actual = {str(item.get("catalog_ref", "")): item for item in entries}
    expected_products = {str(card["selector"]): card for card in product_cards}
    expected_gaps = {f"gap:{gap['code']}": gap for gap in gaps}
    if "" in actual or len(actual) != len(entries):
        raise RuntimeError("host product catalog identities must be unique")
    if set(actual) != set(expected_products) | set(expected_gaps):
        raise RuntimeError("host product catalog identity projection drift")
    for selector, card in expected_products.items():
        _validate_product_projection(actual[selector], card)
    for selector, gap in expected_gaps.items():
        _validate_gap_projection(actual[selector], gap)
    if catalog.get("catalog_sha256") != _fingerprint(entries):
        raise RuntimeError("host product catalog fingerprint drift")


def _product_entry(card: Mapping[str, Any]) -> dict[str, Any]:
    selector = str(card["selector"])
    description = str(card.get("description", "")).strip()
    return {
        "catalog_ref": selector,
        "identity_kind": "product",
        "domain": str(card.get("domain", "uncategorized")),
        "goals": list(caller_language_fields(selector) or (description,)),
        "does_and_returns": description,
        "boundaries": owner_boundaries(card),
        "prerequisites": list(map(str, card.get("required_inputs", ()))),
        "effect": str(card.get("effect", "read")),
        "executable": bool(card.get("executable", False)),
        "description_origin": "canonical_product_card",
    }


def _gap_entry(gap: Mapping[str, Any]) -> dict[str, Any]:
    selector = f"gap:{gap['code']}"
    reason = str(gap["reason"])
    return {
        "catalog_ref": selector,
        "identity_kind": "capability_gap",
        "domain": "capability_gap",
        "goals": list(caller_language_fields(selector) or (str(gap["query"]),)),
        "does_and_returns": reason,
        "boundaries": [GAP_SELECTION_BOUNDARY],
        "prerequisites": [str(gap["next_action"])],
        "effect": "none",
        "executable": False,
        "description_origin": "registered_gap",
    }


def owner_boundaries(card: Mapping[str, Any]) -> list[str]:
    """Return the owner-declared host boundaries; missing declarations fail closed."""

    declared = card.get("boundaries")
    if not isinstance(declared, Sequence) or isinstance(declared, (str, bytes)):
        raise RuntimeError(
            f"canonical product card {card.get('selector')!r} must declare non-empty boundaries"
        )
    clauses = [str(item).strip() for item in declared]
    if not clauses:
        raise RuntimeError(
            f"canonical product card {card.get('selector')!r} must declare non-empty boundaries"
        )
    if any(not item for item in clauses):
        raise RuntimeError(
            f"canonical product card {card.get('selector')!r} boundaries must be non-empty strings"
        )
    if card.get("effect") == "mutation" and MUTATION_SELECTION_BOUNDARY not in clauses:
        raise RuntimeError(
            f"canonical product card {card.get('selector')!r} must keep the mutation authorization boundary"
        )
    return list(dict.fromkeys(clauses))


def _validate_product_projection(entry: Mapping[str, Any], card: Mapping[str, Any]) -> None:
    expected = (
        "product", str(card.get("description", "")).strip(),
        owner_boundaries(card),
        list(map(str, card.get("required_inputs", ()))),
        str(card.get("effect", "read")), bool(card.get("executable", False)),
    )
    actual = (
        entry.get("identity_kind"), entry.get("does_and_returns"),
        entry.get("boundaries"),
        entry.get("prerequisites"), entry.get("effect"), entry.get("executable"),
    )
    if actual != expected or entry.get("description_origin") != "canonical_product_card":
        raise RuntimeError(f"host product catalog owner projection drift: {card['selector']}")


def _validate_gap_projection(entry: Mapping[str, Any], gap: Mapping[str, Any]) -> None:
    expected = (
        "capability_gap", gap["reason"], [GAP_SELECTION_BOUNDARY],
        [gap["next_action"]], False,
    )
    actual = (
        entry.get("identity_kind"), entry.get("does_and_returns"),
        entry.get("boundaries"),
        entry.get("prerequisites"), entry.get("executable"),
    )
    if actual != expected or entry.get("description_origin") != "registered_gap":
        raise RuntimeError(f"host product catalog gap projection drift: {gap['code']}")


def _fingerprint(entries: Sequence[Mapping[str, Any]]) -> str:
    encoded = json.dumps(
        list(entries), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "CATALOG_SCHEMA_VERSION",
    "GAP_SELECTION_BOUNDARY",
    "MAX_CANDIDATES",
    "MUTATION_SELECTION_BOUNDARY",
    "SELECTION_SCHEMA_VERSION",
    "host_catalog_sources",
    "host_product_catalog",
    "host_product_selection_schema",
    "host_product_selection_template",
    "host_selection_upgrade_contract",
    "owner_boundaries",
    "validate_host_catalog_projection",
]
