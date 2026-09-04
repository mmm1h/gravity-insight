"""Fail-closed validation for governed SQL Evidence documents."""

from __future__ import annotations

import copy
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

from gravity_insight.sql.time_window import day_window, normalize_window


_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_LEGACY_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "datasource_id",
        "generated_at",
        "verified_for_date",
        "window",
        "verification_status",
        "products",
        "warnings",
        "forbidden_claims",
        "hashes",
    }
)
_REQUIRED_FIELDS = _LEGACY_REQUIRED_FIELDS | {"verification"}
_SEGMENT_FIELDS = frozenset(
    {
        "sequence",
        "started_at",
        "completed_at",
        "products",
        "status",
        "failure_product",
    }
)
_CHECKPOINT_FIELDS = frozenset(
    {
        "schema_version",
        "ok",
        "status",
        "exit_code",
        "readiness_achieved",
        "verification_status",
        "datasource_id",
        "verified_for_date",
        "window",
        "configured_products",
        "completed_products",
        "pending_products",
        "verification",
        "failure",
        "resume",
        "checkpoint_sha256",
    }
)


class EvidenceFormatError(ValueError):
    pass


def validate_evidence_document(
    evidence: Any,
    *,
    configured_products: tuple[str, ...],
    datasource_id: str,
    hash_json: Callable[[Any], str],
) -> None:
    root = _root(evidence)
    _validate_identity(root, datasource_id)
    window = _validate_window(root)
    products = _product_map(root, configured_products)
    _validate_products(products, configured_products, window)
    _validate_aggregate(root, products, configured_products, hash_json)
    if root["schema_version"] == 2:
        validate_verification_history(
            root["verification"], configured_products, complete=True
        )


def _root(evidence: Any) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise EvidenceFormatError("evidence root must be an object")
    expected_fields = (
        _LEGACY_REQUIRED_FIELDS
        if evidence.get("schema_version") == 1
        else _REQUIRED_FIELDS
    )
    missing = sorted(expected_fields - set(evidence))
    if missing:
        raise EvidenceFormatError(f"evidence is missing fields: {', '.join(missing)}")
    unknown = sorted(set(evidence) - expected_fields)
    if unknown:
        raise EvidenceFormatError(f"evidence has unknown fields: {', '.join(unknown)}")
    if not isinstance(evidence["datasource_id"], str):
        raise EvidenceFormatError("evidence datasource_id must be a string")
    return evidence


def _validate_identity(evidence: Mapping[str, Any], datasource_id: str) -> None:
    schema_version = evidence["schema_version"]
    if (
        type(schema_version) is not int
        or schema_version not in {1, 2}
        or evidence["datasource_id"] != datasource_id
    ):
        raise EvidenceFormatError("unsupported evidence schema or datasource")
    if evidence["verification_status"] not in {"verified", "verified_with_gaps"}:
        raise EvidenceFormatError("invalid evidence verification_status")
    try:
        date.fromisoformat(str(evidence["verified_for_date"]))
        datetime.fromisoformat(str(evidence["generated_at"]))
    except ValueError as exc:
        raise EvidenceFormatError("evidence contains an invalid date/time") from exc


def _validate_window(evidence: Mapping[str, Any]) -> Mapping[str, Any]:
    window = evidence["window"]
    if not isinstance(window, Mapping) or {"start", "end", "timezone"} - set(window):
        raise EvidenceFormatError("evidence window is incomplete")
    if window["timezone"] != "Asia/Shanghai":
        raise EvidenceFormatError("evidence timezone must be Asia/Shanghai")
    try:
        start_at, end_at = normalize_window(str(window["start"]), str(window["end"]))
    except ValueError as exc:
        raise EvidenceFormatError(str(exc)) from exc
    expected = day_window(date.fromisoformat(str(evidence["verified_for_date"])))
    if (start_at, end_at) != expected:
        raise EvidenceFormatError("evidence must describe one Beijing calendar day")
    return window


def _product_map(
    evidence: Mapping[str, Any], configured: tuple[str, ...]
) -> Mapping[str, Any]:
    products = evidence["products"]
    if not isinstance(products, Mapping) or set(products) != set(configured):
        raise EvidenceFormatError("evidence must contain exactly the configured SQL products")
    return products


def _validate_products(
    products: Mapping[str, Any],
    configured: tuple[str, ...],
    window: Mapping[str, Any],
) -> None:
    for product in configured:
        _validate_product(product, products[product], window)


def _validate_product(
    product: str, result: Any, window: Mapping[str, Any]
) -> None:
    if not isinstance(result, Mapping) or result.get("product") != product:
        raise EvidenceFormatError(f"invalid product evidence: {product}")
    if result.get("status") not in {"complete", "partial"}:
        raise EvidenceFormatError(f"invalid product status: {product}")
    if not isinstance(result.get("summary"), Mapping):
        raise EvidenceFormatError(f"missing product summary: {product}")
    _validate_claims(product, result)
    if result.get("window") != window:
        raise EvidenceFormatError(f"product window differs from evidence window: {product}")
    _validate_app_ids(product, result.get("app_ids"))
    _validate_hashes(result.get("hashes"), f"product {product}")


def validate_product_evidence(
    product: str, result: Any, window: Mapping[str, Any]
) -> None:
    """Validate one reusable component without claiming aggregate readiness."""

    _validate_product(product, result, window)


def validate_verification_history(
    value: Any,
    configured_products: Sequence[str],
    *,
    complete: bool,
) -> None:
    """Require ordered, gap-free verification segments for Evidence or checkpoints."""

    segments = _verification_history_root(value, complete)
    configured = list(configured_products)
    covered: list[str] = []
    prior_completed: datetime | None = None
    for index, segment in enumerate(segments, start=1):
        selected = _verification_segment_root(segment, index)
        started = _aware_datetime(selected["started_at"])
        completed_at = _aware_datetime(selected["completed_at"])
        _validate_segment_times(started, completed_at, prior_completed)
        prior_completed = completed_at
        segment_products = _verification_segment_products(selected)
        expected = configured[len(covered) : len(covered) + len(segment_products)]
        if segment_products != expected:
            raise EvidenceFormatError("verification segments must preserve product order")
        covered.extend(segment_products)
        _validate_segment_outcome(
            selected,
            complete=complete,
            is_last=index == len(segments),
            segment_products=segment_products,
            covered=covered,
            configured=configured,
        )
    if complete and covered != configured:
        raise EvidenceFormatError("complete verification history omits products")
    if not complete and len(covered) >= len(configured):
        raise EvidenceFormatError("interrupted verification cannot cover every product")


def _verification_history_root(value: Any, complete: bool) -> list[Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "mode",
        "segment_count",
        "segments",
    }:
        raise EvidenceFormatError("verification history fields are invalid")
    segments = value["segments"]
    expected_modes = {"single_run", "resumed_after_rate_limit"} if complete else {"interrupted"}
    valid = value["mode"] in expected_modes and type(value["segment_count"]) is int
    valid = valid and isinstance(segments, list) and bool(segments)
    valid = valid and value["segment_count"] == len(segments)
    if not valid:
        raise EvidenceFormatError("verification history shape is invalid")
    if complete and ((len(segments) == 1) != (value["mode"] == "single_run")):
        raise EvidenceFormatError("verification mode differs from its segments")
    return segments


def _verification_segment_root(value: Any, sequence: int) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _SEGMENT_FIELDS:
        raise EvidenceFormatError("verification segment fields are invalid")
    if value["sequence"] != sequence:
        raise EvidenceFormatError("verification segment sequence is invalid")
    return value


def _verification_segment_products(segment: Mapping[str, Any]) -> list[str]:
    selected = segment["products"]
    if not isinstance(selected, list) or any(
        not isinstance(product, str) for product in selected
    ):
        raise EvidenceFormatError("verification segment products are invalid")
    return selected


def _validate_segment_times(
    started: datetime, completed: datetime, prior_completed: datetime | None
) -> None:
    if started > completed or (
        prior_completed is not None and started < prior_completed
    ):
        raise EvidenceFormatError("verification segment timestamps are invalid")


def _validate_segment_outcome(
    segment: Mapping[str, Any],
    *,
    complete: bool,
    is_last: bool,
    segment_products: Sequence[str],
    covered: Sequence[str],
    configured: Sequence[str],
) -> None:
    expected_status = "complete" if complete and is_last else "rate_limited"
    if segment["status"] != expected_status:
        raise EvidenceFormatError("verification segment status is invalid")
    failure_product = segment["failure_product"]
    if expected_status == "complete":
        if failure_product is not None or not segment_products:
            raise EvidenceFormatError("complete verification segment is invalid")
        return
    if len(covered) >= len(configured) or failure_product != configured[len(covered)]:
        raise EvidenceFormatError(
            "rate-limited segment must identify the next unverified product"
        )


def _aware_datetime(value: Any) -> datetime:
    try:
        selected = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise EvidenceFormatError("verification segment timestamp is invalid") from exc
    if selected.utcoffset() is None:
        raise EvidenceFormatError("verification segment timestamp must be timezone-aware")
    return selected


def evidence_aggregate_lists(
    products: Mapping[str, Any], configured: Sequence[str]
) -> tuple[list[str], list[str]]:
    return _expected_warnings(products, configured), _expected_claims(products, configured)


def verification_resume_state(
    owner: Any,
    resume: Mapping[str, Any] | None,
    day: date,
    names: tuple[str, ...],
    workspace: Any,
    clock: Callable[[], datetime] | None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], int]:
    if resume is None:
        return [], {}, 0
    validate_resume_checkpoint(owner, resume, day, names, workspace)
    return (
        copy.deepcopy(resume["verification"]["segments"]),
        copy.deepcopy(resume["completed_products"]),
        owner.verification_resume_delay_ms(
            resume["verification"], resume["failure"], clock
        ),
    )


def validate_resume_checkpoint(
    owner: Any,
    value: Any,
    day: date,
    names: tuple[str, ...],
    workspace: Any,
) -> None:
    _validate_checkpoint_identity(owner, value, day, names, workspace)
    completed, prefix, pending = _checkpoint_products(value, names)
    _validate_checkpoint_history(value, names, prefix)
    for product in prefix:
        _validate_reusable_product(owner, product, completed[product], day, workspace)
    _validate_checkpoint_failure(owner, value["failure"], pending)
    if value["resume"] != owner.verification_resume_contract(owner, day, True):
        raise EvidenceFormatError("SQL verification checkpoint resume policy is invalid")


def _validate_checkpoint_identity(
    owner: Any, value: Any, day: date, names: tuple[str, ...], workspace: Any
) -> None:
    if not isinstance(value, Mapping) or set(value) != _CHECKPOINT_FIELDS:
        raise EvidenceFormatError("SQL verification checkpoint fields are invalid")
    expected = (
        owner.VERIFICATION_RUN_VERSION,
        "rate_limited",
        owner.sql_error_exit_code("runtime"),
        "interrupted",
        owner._datasource_id(workspace=workspace),
        day.isoformat(),
        owner._window_dict(*owner.day_window(day)),
        list(names),
    )
    actual = tuple(value[field] for field in (
        "schema_version", "status", "exit_code", "verification_status",
        "datasource_id", "verified_for_date", "window", "configured_products",
    ))
    if actual != expected or value["ok"] is not False or value["readiness_achieved"] is not False:
        raise EvidenceFormatError("SQL verification checkpoint identity is invalid")
    if value["checkpoint_sha256"] != owner.verification_checkpoint_digest(value):
        raise EvidenceFormatError("SQL verification checkpoint digest is invalid")


def _checkpoint_products(
    value: Mapping[str, Any], names: tuple[str, ...]
) -> tuple[Mapping[str, Any], list[str], list[str]]:
    completed = value["completed_products"]
    if not isinstance(completed, Mapping):
        raise EvidenceFormatError("SQL verification checkpoint products are invalid")
    prefix = list(names[: len(completed)])
    if list(completed) != prefix or len(completed) >= len(names):
        raise EvidenceFormatError(
            "SQL verification checkpoint must contain a strict configured-product prefix"
        )
    pending = list(names[len(completed) :])
    if value["pending_products"] != pending:
        raise EvidenceFormatError("SQL verification checkpoint pending suffix is invalid")
    return completed, prefix, pending


def _validate_checkpoint_history(
    value: Mapping[str, Any], names: tuple[str, ...], prefix: Sequence[str]
) -> None:
    validate_verification_history(value["verification"], names, complete=False)
    covered = [
        product
        for segment in value["verification"]["segments"]
        for product in segment["products"]
    ]
    if covered != list(prefix):
        raise EvidenceFormatError(
            "SQL verification checkpoint history differs from its completed prefix"
        )


def _validate_checkpoint_failure(
    owner: Any, failure: Any, pending: Sequence[str]
) -> None:
    valid = isinstance(failure, Mapping) and failure.get("product") == pending[0]
    valid = valid and failure.get("code") == "RATE_LIMITED"
    valid = valid and failure.get("sql_code") == "SQL_HTTP_RATE_LIMITED"
    valid = valid and failure.get("category") == "upstream"
    valid = valid and failure.get("retryable") is True
    retry_after = failure.get("retry_after_ms") if isinstance(failure, Mapping) else None
    valid = valid and type(retry_after) is int
    valid = valid and 0 <= retry_after <= owner.VERIFICATION_MAX_BACKOFF_MS
    if not valid:
        raise EvidenceFormatError(
            "SQL verification checkpoint is not a reusable rate-limit receipt"
        )


def _validate_reusable_product(
    owner: Any, product: str, result: Any, day: date, workspace: Any
) -> None:
    window = owner._window_dict(*owner.day_window(day))
    validate_product_evidence(product, result, window)
    if result["hashes"]["contract_sha256"] != owner.contract_hash(product, workspace):
        raise EvidenceFormatError(
            f"SQL verification checkpoint contract changed for {product}"
        )
    start_at, end_at = owner.normalize_window(window["start"], window["end"])
    app_ids = owner.normalize_app_ids(product, result["app_ids"], workspace)
    sql = owner.build_sql(product, start_at, end_at, app_ids, workspace)
    if result["hashes"]["sql_sha256"] != owner._sha256_text(sql):
        raise EvidenceFormatError(f"SQL verification checkpoint SQL changed for {product}")


def _validate_claims(product: str, result: Mapping[str, Any]) -> None:
    warnings = result.get("warnings")
    claims = result.get("forbidden_claims")
    if not _string_list(warnings) or not _nonempty_string_list(claims):
        raise EvidenceFormatError(f"invalid product warnings/claims: {product}")
    if result["status"] == "partial" and not warnings:
        raise EvidenceFormatError(f"partial product must contain warnings: {product}")


def _validate_app_ids(product: str, value: Any) -> None:
    if (
        not isinstance(value, list)
        or not value
        or any(type(app_id) is not int or app_id <= 0 for app_id in value)
    ):
        raise EvidenceFormatError(f"invalid product app_ids: {product}")


def _validate_aggregate(
    evidence: Mapping[str, Any],
    products: Mapping[str, Any],
    configured: tuple[str, ...],
    hash_json: Callable[[Any], str],
) -> None:
    warnings = _expected_warnings(products, configured)
    claims = _expected_claims(products, configured)
    expected_status = "verified_with_gaps" if warnings else "verified"
    if evidence["warnings"] != warnings:
        raise EvidenceFormatError("evidence warnings differ from product warnings")
    if evidence["forbidden_claims"] != claims:
        raise EvidenceFormatError("evidence forbidden_claims differ from product claims")
    if evidence["verification_status"] != expected_status:
        raise EvidenceFormatError("evidence verification_status differs from product statuses")
    _validate_aggregate_lists(evidence)
    _validate_hashes(evidence["hashes"], "evidence")
    if evidence["hashes"] != _evidence_hashes(products, configured, hash_json):
        raise EvidenceFormatError("evidence content does not match its top-level hashes")


def _validate_aggregate_lists(evidence: Mapping[str, Any]) -> None:
    if not _string_list(evidence["warnings"]):
        raise EvidenceFormatError("evidence warnings and forbidden_claims must be lists")
    if not _nonempty_string_list(evidence["forbidden_claims"]):
        raise EvidenceFormatError("evidence warnings and forbidden_claims must be lists")
    if evidence["verification_status"] == "verified_with_gaps" and not evidence["warnings"]:
        raise EvidenceFormatError("verified_with_gaps evidence must contain warnings")


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _nonempty_string_list(value: Any) -> bool:
    return bool(value) and _string_list(value)


def _expected_warnings(
    products: Mapping[str, Any], configured: Sequence[str]
) -> list[str]:
    return [
        f"{product}: {warning}"
        for product in configured
        for warning in products[product]["warnings"]
    ]


def _expected_claims(
    products: Mapping[str, Any], configured: Sequence[str]
) -> list[str]:
    return list(
        dict.fromkeys(
            claim
            for product in configured
            for claim in products[product]["forbidden_claims"]
        )
    )


def _validate_hashes(value: Any, label: str) -> None:
    if not isinstance(value, Mapping):
        raise EvidenceFormatError(f"{label} hashes must be an object")
    for name in ("sql_sha256", "result_sha256", "contract_sha256"):
        if not _HASH_RE.fullmatch(str(value.get(name, ""))):
            raise EvidenceFormatError(f"{label} contains invalid {name}")


def _evidence_hashes(
    products: Mapping[str, Any],
    configured: Sequence[str],
    hash_json: Callable[[Any], str],
) -> dict[str, str]:
    return {
        "sql_sha256": hash_json(
            {product: products[product]["hashes"]["sql_sha256"] for product in configured}
        ),
        "result_sha256": hash_json(products),
        "contract_sha256": hash_json(
            {
                product: products[product]["hashes"]["contract_sha256"]
                for product in configured
            }
        ),
    }


__all__ = [
    "EvidenceFormatError",
    "evidence_aggregate_lists",
    "validate_evidence_document",
    "validate_product_evidence",
    "validate_resume_checkpoint",
    "validate_verification_history",
    "verification_resume_state",
]
