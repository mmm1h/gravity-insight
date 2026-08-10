from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from gravity_sdk.paths import EVIDENCE_ROOT, PACKAGE_ROOT, PROJECT_ROOT
from gravity_sdk.support.documents import replace_atomic_durable
from gravity_sdk.support.evidence import (
    EvidenceBinding,
    publish_json_snapshot,
    resolve_json_evidence,
    serialize_json_result,
)
from gravity_sdk.workspace import Workspace, WorkspaceError, load_workspace, require_products


ROOT = PROJECT_ROOT
BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
EVIDENCE_PATH = EVIDENCE_ROOT / "latest.json"
EVIDENCE_PRODUCT_ROOT = EVIDENCE_ROOT / "daily-verification"
SQL_PRODUCT_CONTRACT_PATH = PACKAGE_ROOT / "contracts" / "sql-products" / "catalog.json"
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class EvidenceFormatError(ValueError):
    pass


def product_names(workspace: Workspace | None = None) -> tuple[str, ...]:
    selected = load_workspace() if workspace is None else workspace
    return require_products(selected)


def _product_definition(product: str, workspace: Workspace | None = None) -> Mapping[str, Any]:
    selected = load_workspace() if workspace is None else workspace
    try:
        return selected.product(product)
    except WorkspaceError as exc:
        raise EvidenceFormatError(str(exc)) from exc


def _product_apps(product: str, workspace: Workspace | None = None) -> tuple[int, ...]:
    selected = load_workspace() if workspace is None else workspace
    definition = _product_definition(product, selected)
    return tuple(selected.resolve_app(value) for value in definition["apps"])


def _datasource_contract(
    product: str | None = None, workspace: Workspace | None = None
) -> Mapping[str, Any]:
    selected = load_workspace() if workspace is None else workspace
    names = (product,) if product is not None else product_names(selected)
    datasource_names = {str(_product_definition(name, selected)["datasource"]) for name in names}
    if len(datasource_names) != 1:
        raise EvidenceFormatError("SQL Evidence products must use exactly one datasource")
    return selected.datasource(next(iter(datasource_names)))


def _datasource_id(product: str | None = None) -> str:
    return str(_datasource_contract(product)["id"])


def latest_safe_date(now: datetime | None = None) -> date:
    current = now.astimezone(BEIJING) if now and now.tzinfo else (now.replace(tzinfo=BEIJING) if now else datetime.now(BEIJING))
    return current.date() - timedelta(days=2 if current.hour < 2 else 1)


def day_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, BEIJING)
    return start, start + timedelta(days=1)


def parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid ISO timestamp: {value!r}") from exc
    parsed = parsed.replace(tzinfo=BEIJING) if parsed.tzinfo is None else parsed.astimezone(BEIJING)
    return parsed.replace(microsecond=0)


def normalize_window(start: str, end: str) -> tuple[datetime, datetime]:
    start_at, end_at = parse_timestamp(start), parse_timestamp(end)
    if start_at >= end_at:
        raise ValueError("start must be earlier than end")
    return start_at, end_at


def normalize_app_ids(product: str, app_ids: list[int] | tuple[int, ...] | None) -> tuple[int, ...]:
    defaults = _product_apps(product)
    values = tuple(dict.fromkeys(app_ids or defaults))
    if not values or any(type(value) is not int or value <= 0 for value in values):
        raise ValueError("app ids must be positive integers")
    return values


def build_sql(product: str, start_at: datetime, end_at: datetime, app_ids: tuple[int, ...]) -> str:
    app_ids = normalize_app_ids(product, app_ids)
    definition = _product_definition(product)
    start = _sql_time(start_at)
    end = _sql_time(end_at)
    return _custom_sql(definition, app_ids, start, end)


def _custom_sql(
    definition: Mapping[str, Any], app_ids: tuple[int, ...], start: str, end: str
) -> str:
    return str(definition["sql"]).format(
        app_ids=", ".join(str(app_id) for app_id in app_ids),
        start=start,
        end=end,
        limit=int(definition.get("max_rows", 1000)) + 1,
    )


def run_product(
    client: Any,
    product: str,
    start_at: datetime,
    end_at: datetime,
    app_ids: list[int] | tuple[int, ...] | None = None,
) -> dict[str, Any]:
    apps = normalize_app_ids(product, app_ids)
    definition = _product_definition(product)
    sql = build_sql(product, start_at, end_at, apps)
    rows = client.execute_sql(sql)
    summary, status, warnings, notes = _summarize_rows(
        definition, rows, apps, start_at, end_at
    )
    result: dict[str, Any] = {
        "product": product,
        "status": status,
        "window": _window_dict(start_at, end_at),
        "app_ids": list(apps),
        "summary": summary,
        "warnings": warnings,
        "forbidden_claims": list(definition["forbidden_claims"]),
        "hashes": {
            "sql_sha256": _sha256_text(sql),
            "result_sha256": _sha256_json(rows),
            "contract_sha256": contract_hash(product),
        },
    }
    if notes:
        result["notes"] = notes
    return result


def summarize_custom(
    rows: list[dict[str, Any]],
    app_ids: tuple[int, ...],
    _start_at: datetime,
    _end_at: datetime,
    *,
    output_fields: list[str],
    max_rows: int,
    measurement: str,
) -> tuple[dict[str, Any], str, list[str], list[str]]:
    if len(rows) > max_rows:
        raise EvidenceFormatError(f"custom SQL product exceeded max_rows={max_rows}")
    projected: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise EvidenceFormatError("custom SQL product returned a non-object row")
        projected.append({field: row.get(field) for field in output_fields})
    return {
        "rows": projected,
        "row_count": len(projected),
        "app_ids": list(app_ids),
        "measurement": measurement,
    }, "complete", [], []


def _summarize_rows(
    definition: Mapping[str, Any],
    rows: list[dict[str, Any]],
    app_ids: tuple[int, ...],
    start_at: datetime,
    end_at: datetime,
) -> tuple[dict[str, Any], str, list[str], list[str]]:
    return summarize_custom(
        rows,
        app_ids,
        start_at,
        end_at,
        output_fields=list(definition["output_fields"]),
        max_rows=int(definition.get("max_rows", 1000)),
        measurement=str(definition.get("measurement", "workspace aggregate")),
    )


def build_evidence(day: date, product_results: list[dict[str, Any]]) -> dict[str, Any]:
    configured_products = product_names()
    if len(product_results) != len(configured_products) or {
        result.get("product") for result in product_results
    } != set(configured_products):
        raise EvidenceFormatError("verification must contain exactly the configured SQL products")
    start_at, end_at = day_window(day)
    by_name = {result["product"]: result for result in product_results}
    products = {product: by_name[product] for product in configured_products}
    warnings = [
        f"{product}: {warning}"
        for product, result in products.items()
        for warning in result.get("warnings", [])
    ]
    forbidden = list(
        dict.fromkeys(
            claim
            for product in configured_products
            for claim in products[product].get("forbidden_claims", [])
        )
    )
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "datasource_id": _datasource_id(),
        "generated_at": datetime.now(BEIJING).isoformat(timespec="microseconds"),
        "verified_for_date": day.isoformat(),
        "window": _window_dict(start_at, end_at),
        "verification_status": "verified_with_gaps" if warnings else "verified",
        "products": products,
        "warnings": warnings,
        "forbidden_claims": forbidden,
    }
    evidence["hashes"] = {
        "sql_sha256": _sha256_json(
            {
                product: products[product]["hashes"]["sql_sha256"]
                for product in configured_products
            }
        ),
        "result_sha256": _sha256_json(products),
        "contract_sha256": _sha256_json(
            {
                product: products[product]["hashes"]["contract_sha256"]
                for product in configured_products
            }
        ),
    }
    validate_evidence(evidence)
    return evidence


def verify_all(client: Any, day: date) -> dict[str, Any]:
    start_at, end_at = day_window(day)
    results = [
        run_product(client, product, start_at, end_at)
        for product in product_names()
    ]
    return build_evidence(day, results)


def validate_evidence(evidence: Any) -> None:
    if not isinstance(evidence, dict):
        raise EvidenceFormatError("evidence root must be an object")
    required = {
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
    missing = sorted(required - set(evidence))
    if missing:
        raise EvidenceFormatError(f"evidence is missing fields: {', '.join(missing)}")
    unknown = sorted(set(evidence) - required)
    if unknown:
        raise EvidenceFormatError(f"evidence has unknown fields: {', '.join(unknown)}")
    if not isinstance(evidence["datasource_id"], str):
        raise EvidenceFormatError("evidence datasource_id must be a string")
    schema_version = evidence["schema_version"]
    datasource_id = _datasource_id()
    if (
        type(schema_version) is not int
        or schema_version != 1
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
    window = evidence["window"]
    if not isinstance(window, dict) or set(("start", "end", "timezone")) - set(window):
        raise EvidenceFormatError("evidence window is incomplete")
    if window["timezone"] != "Asia/Shanghai":
        raise EvidenceFormatError("evidence timezone must be Asia/Shanghai")
    try:
        start_at, end_at = normalize_window(str(window["start"]), str(window["end"]))
    except ValueError as exc:
        raise EvidenceFormatError(str(exc)) from exc
    expected_start, expected_end = day_window(date.fromisoformat(str(evidence["verified_for_date"])))
    if start_at != expected_start or end_at != expected_end:
        raise EvidenceFormatError("evidence must describe one Beijing calendar day")
    products = evidence["products"]
    configured_products = product_names()
    if not isinstance(products, dict) or set(products) != set(configured_products):
        raise EvidenceFormatError("evidence must contain exactly the configured SQL products")
    for product in configured_products:
        result = products[product]
        if not isinstance(result, dict) or result.get("product") != product:
            raise EvidenceFormatError(f"invalid product evidence: {product}")
        if result.get("status") not in {"complete", "partial"}:
            raise EvidenceFormatError(f"invalid product status: {product}")
        if not isinstance(result.get("summary"), dict):
            raise EvidenceFormatError(f"missing product summary: {product}")
        warnings = result.get("warnings")
        forbidden_claims = result.get("forbidden_claims")
        if (
            not isinstance(warnings, list)
            or not all(isinstance(item, str) for item in warnings)
            or not isinstance(forbidden_claims, list)
            or not forbidden_claims
            or not all(isinstance(item, str) for item in forbidden_claims)
        ):
            raise EvidenceFormatError(f"invalid product warnings/claims: {product}")
        if result["status"] == "partial" and not warnings:
            raise EvidenceFormatError(f"partial product must contain warnings: {product}")
        if result.get("window") != window:
            raise EvidenceFormatError(f"product window differs from evidence window: {product}")
        app_ids = result.get("app_ids")
        if (
            not isinstance(app_ids, list)
            or not app_ids
            or any(not isinstance(app_id, int) or app_id <= 0 for app_id in app_ids)
        ):
            raise EvidenceFormatError(f"invalid product app_ids: {product}")
        _validate_hashes(result.get("hashes"), f"product {product}")
    expected_warnings = [
        f"{product}: {warning}"
        for product in configured_products
        for warning in products[product]["warnings"]
    ]
    expected_forbidden = list(
        dict.fromkeys(
            claim
            for product in configured_products
            for claim in products[product]["forbidden_claims"]
        )
    )
    expected_status = "verified_with_gaps" if expected_warnings else "verified"
    if evidence["warnings"] != expected_warnings:
        raise EvidenceFormatError("evidence warnings differ from product warnings")
    if evidence["forbidden_claims"] != expected_forbidden:
        raise EvidenceFormatError("evidence forbidden_claims differ from product claims")
    if evidence["verification_status"] != expected_status:
        raise EvidenceFormatError("evidence verification_status differs from product statuses")
    if (
        not isinstance(evidence["warnings"], list)
        or not all(isinstance(item, str) for item in evidence["warnings"])
        or not isinstance(evidence["forbidden_claims"], list)
        or not evidence["forbidden_claims"]
        or not all(isinstance(item, str) for item in evidence["forbidden_claims"])
    ):
        raise EvidenceFormatError("evidence warnings and forbidden_claims must be lists")
    if evidence["verification_status"] == "verified_with_gaps" and not evidence["warnings"]:
        raise EvidenceFormatError("verified_with_gaps evidence must contain warnings")
    _validate_hashes(evidence["hashes"], "evidence")
    expected_hashes = _evidence_hashes(products, configured_products)
    if evidence["hashes"] != expected_hashes:
        raise EvidenceFormatError("evidence content does not match its top-level hashes")


def _evidence_hashes(
    products: Mapping[str, Any], configured_products: tuple[str, ...]
) -> dict[str, str]:
    return {
        "sql_sha256": _sha256_json(
            {
                product: products[product]["hashes"]["sql_sha256"]
                for product in configured_products
            }
        ),
        "result_sha256": _sha256_json(products),
        "contract_sha256": _sha256_json(
            {
                product: products[product]["hashes"]["contract_sha256"]
                for product in configured_products
            }
        ),
    }


def publish_evidence(evidence: dict[str, Any], path: Path = EVIDENCE_PATH) -> None:
    validate_evidence(evidence)
    canonical_publish = path.resolve() == EVIDENCE_PATH.resolve()
    snapshot_metadata = _snapshot_metadata(evidence) if canonical_publish else None
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(serialize_json_result(evidence).decode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        if snapshot_metadata is not None:
            publish_json_snapshot(
                EVIDENCE_PRODUCT_ROOT,
                evidence,
                snapshot_metadata,
                result_validator=validate_evidence,
            )
        # The mutable file is compatibility-only. Never expose it until the
        # canonical immutable snapshot and latest pointer are durable.
        replace_atomic_durable(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def resolve_current_evidence(product_root: Path | None = None) -> EvidenceBinding:
    """Resolve latest.yaml once and return one validated immutable binding."""

    try:
        return resolve_json_evidence(
            product_root or EVIDENCE_PRODUCT_ROOT,
            result_validator=validate_evidence,
        )
    except (ValueError, OSError) as exc:
        raise EvidenceFormatError(f"cannot resolve immutable Evidence: {exc}") from exc


def read_evidence(path: Path | None = None) -> dict[str, Any] | None:
    """Read Evidence; default to immutable resolution, explicit paths are compatibility-only."""

    if path is None:
        return resolve_current_evidence().result
    if not path.exists():
        return None
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceFormatError(f"cannot read evidence: {exc}") from exc
    validate_evidence(evidence)
    return evidence


def _snapshot_metadata(evidence: dict[str, Any]) -> dict[str, Any]:
    git_sha, git_dirty = _git_state()
    window = evidence["window"]
    return {
        "schema_version": 1,
        "data_product_id": "gravity.daily_verification",
        "evidence_origin": "generated",
        "generated_at": evidence["generated_at"],
        "latest_safe_date": evidence["verified_for_date"],
        "data_window": {"start": window["start"], "end": window["end"]},
        "timezone": window["timezone"],
        "data_contract_version": f"sha256:{evidence['hashes']['contract_sha256']}",
        "query_id": "gravity.verify_all",
        "query_version": f"sha256:{evidence['hashes']['sql_sha256']}",
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "row_count": len(evidence["products"]),
        "row_count_semantics": "data_product_count",
        "privacy_class": "aggregate",
        "provenance_status": "complete",
        "unknown_fields": [],
    }


def _git_state() -> tuple[str, bool]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if head.returncode or re.fullmatch(r"[0-9a-f]{40}", head.stdout.strip()) is None:
        raise EvidenceFormatError("cannot publish evidence without a valid repository Git SHA")
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if status.returncode:
        raise EvidenceFormatError("cannot determine repository state for evidence provenance")
    return head.stdout.strip(), bool(status.stdout.strip())


def readiness_status(
    evidence: dict[str, Any] | EvidenceBinding | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    binding = evidence if isinstance(evidence, EvidenceBinding) else None
    evidence_value = binding.result if binding else evidence
    safe_day = latest_safe_date(now)
    declared = datasource_verification_status()
    datasource_id = _datasource_id()
    evidence_pointer = EVIDENCE_PRODUCT_ROOT / "latest.yaml"
    try:
        evidence_path = evidence_pointer.relative_to(ROOT).as_posix()
    except ValueError:
        evidence_path = evidence_pointer.as_posix()
    base = {
        "datasource_id": datasource_id,
        "declared_status": declared,
        "latest_safe_date": safe_day.isoformat(),
        "evidence_path": evidence_path,
    }
    if binding:
        base["evidence_reference"] = binding.reference()
    elif evidence_value is not None:
        base["evidence_reference_missing_reason"] = "legacy_or_injected_evidence_dict"
    if declared not in {"verified", "verified_with_gaps"}:
        return {
            **base,
            "status": declared,
            "query_ready": False,
            "reason": f"datasource verification_status is {declared}",
        }
    if evidence_value is None:
        return {
            **base,
            "status": "pending_review",
            "query_ready": False,
            "reason": "immutable evidence is missing",
        }
    validate_evidence(evidence_value)
    if evidence_value["verification_status"] not in {"verified", "verified_with_gaps"}:
        return {
            **base,
            "status": evidence_value["verification_status"],
            "query_ready": False,
            "reason": "published evidence is not query-ready",
            "verified_for_date": evidence_value["verified_for_date"],
        }
    stale_reason = _stale_reason(evidence_value, safe_day)
    if stale_reason:
        return {
            **base,
            "status": "stale",
            "query_ready": False,
            "reason": stale_reason,
            "verified_for_date": evidence_value["verified_for_date"],
            "generated_at": evidence_value["generated_at"],
        }
    return {
        **base,
        "status": evidence_value["verification_status"],
        "query_ready": True,
        "reason": "latest safe Beijing day is verified",
        "verified_for_date": evidence_value["verified_for_date"],
        "generated_at": evidence_value["generated_at"],
        "warnings": evidence_value["warnings"],
        "forbidden_claims": evidence_value["forbidden_claims"],
    }


def evidence_preflight(
    target_day: date | None = None,
    *,
    now: datetime | None = None,
    root: Path = ROOT,
    product_root: Path | None = None,
) -> dict[str, Any]:
    """Return offline operational checks without contacting Gravity."""

    safe_day = latest_safe_date(now)
    selected_day = target_day or safe_day
    if selected_day > safe_day:
        raise EvidenceFormatError(f"target date {selected_day} is newer than latest safe date {safe_day}")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False
    )
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"], cwd=root, capture_output=True, check=False
    )
    git_sha = head.stdout.strip()
    if head.returncode or re.fullmatch(r"[0-9a-f]{40}", git_sha) is None or branch.returncode or status.returncode:
        raise EvidenceFormatError("cannot determine Git state for Evidence preflight")
    git_dirty = bool(status.stdout.strip())
    credential_source = _credential_source(root)
    binding = resolve_current_evidence(product_root)
    start_at, end_at = day_window(selected_day)
    current_status = readiness_status(binding, now)
    blockers: list[str] = []
    if git_dirty:
        blockers.append("working_tree_not_clean_or_scoped")
    if credential_source == "missing":
        blockers.append("gravity_read_only_credential_missing")
    return {
        "schema_version": 1,
        "mode": "offline_preflight_only",
        "working_tree_clean_or_scoped": not git_dirty,
        "current_branch": branch.stdout.strip() or "DETACHED",
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "python_version": platform.python_version(),
        "gravity_profile": "local_read_only",
        "gravity_credential_present": credential_source != "missing",
        "gravity_credential_source": credential_source,
        "latest_safe_date": safe_day.isoformat(),
        "target_date": selected_day.isoformat(),
        "data_window": {
            "start": start_at.isoformat(timespec="seconds"),
            "end": end_at.isoformat(timespec="seconds"),
            "timezone": "Asia/Shanghai",
        },
        "current_evidence": binding.reference(),
        "current_readiness": {
            "status": current_status["status"],
            "query_ready": current_status["query_ready"],
            "reason": current_status["reason"],
        },
        "offline_blockers": blockers,
        "offline_checks_passed": not blockers,
        "requires_explicit_live_read_authorization": True,
        "requires_separate_publish_authorization": True,
        "network_called": False,
    }


def _credential_source(root: Path) -> str:
    if os.environ.get("GRAVITY_AUTH_TOKEN") or os.environ.get("GRAVITY_AUTHORIZATION"):
        return "environment"
    if os.environ.get("GRAVITY_USERNAME") and os.environ.get("GRAVITY_PASSWORD"):
        return "environment"
    env_path = root / ".env.gravity.local"
    try:
        keys = {
            line.split("=", 1)[0].strip()
            for line in env_path.read_text(encoding="utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("#")
        }
    except (OSError, UnicodeError):
        return "missing"
    account_fields = {"GRAVITY_USERNAME", "GRAVITY_PASSWORD"}
    has_login = account_fields.issubset(keys)
    return "local_account_file" if has_login else "missing"


def datasource_verification_status() -> str:
    status = _datasource_contract().get("verification_status")
    if not isinstance(status, str):
        raise EvidenceFormatError("datasource contract is missing verification_status")
    if status not in {"pending_review", "verified", "verified_with_gaps", "blocked"}:
        raise EvidenceFormatError(f"invalid datasource verification_status: {status}")
    return status


def contract_hash(product: str) -> str:
    try:
        definition = _product_definition(product)
        datasource = _datasource_contract(product)
        kernel_contract = _load_sql_product_contract(SQL_PRODUCT_CONTRACT_PATH)
        kind_contract = kernel_contract["product_kinds"][definition["kind"]]
        encoded = json.dumps(
            {
                "datasource": datasource,
                "kernel_kind": kind_contract,
                "product": definition,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
    except (KeyError, TypeError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceFormatError(f"cannot hash contract for {product}: {exc}") from exc


def _load_sql_product_contract(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceFormatError(f"cannot read SQL product contract {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 3:
        raise EvidenceFormatError(f"{path}: unsupported SQL product contract schema")
    return value


def dry_run_checks() -> None:
    start_at, end_at = day_window(date(2026, 7, 22))
    for product in product_names():
        apps = _product_apps(product)
        definition = _product_definition(product)
        sql = build_sql(product, start_at, end_at, apps)
        if "2026-07-22 00:00:00" not in sql or "2026-07-23 00:00:00" not in sql:
            raise AssertionError(f"{product}: rendered SQL has the wrong window")
        summary = _summarize_rows(definition, [], apps, start_at, end_at)[0]
        if "user_id" in summary:
            raise AssertionError(f"{product}: aggregate summary leaked a user-level key")
    if latest_safe_date(datetime(2026, 7, 23, 1, 59, tzinfo=BEIJING)) != date(2026, 7, 21):
        raise AssertionError("pre-02:00 safe-day rule failed")
    if latest_safe_date(datetime(2026, 7, 23, 2, 0, tzinfo=BEIJING)) != date(2026, 7, 22):
        raise AssertionError("post-02:00 safe-day rule failed")


def _stale_reason(evidence: dict[str, Any], safe_day: date) -> str | None:
    if evidence["verified_for_date"] != safe_day.isoformat():
        return f"evidence date {evidence['verified_for_date']} != latest safe date {safe_day.isoformat()}"
    for product in product_names():
        result = evidence["products"][product]
        if result["hashes"]["contract_sha256"] != contract_hash(product):
            return f"{product} contract changed after verification"
        start_at, end_at = normalize_window(result["window"]["start"], result["window"]["end"])
        apps = normalize_app_ids(product, result["app_ids"])
        if result["hashes"]["sql_sha256"] != _sha256_text(build_sql(product, start_at, end_at, apps)):
            return f"{product} SQL changed after verification"
    return None


def _window_dict(start_at: datetime, end_at: datetime) -> dict[str, str]:
    return {
        "start": start_at.astimezone(BEIJING).isoformat(timespec="seconds"),
        "end": end_at.astimezone(BEIJING).isoformat(timespec="seconds"),
        "timezone": "Asia/Shanghai",
    }


def _sql_time(value: datetime) -> str:
    return value.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M:%S")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return _sha256_text(encoded)


def _validate_hashes(value: Any, label: str) -> None:
    if not isinstance(value, dict):
        raise EvidenceFormatError(f"{label} hashes must be an object")
    for name in ("sql_sha256", "result_sha256", "contract_sha256"):
        if not HASH_RE.fullmatch(str(value.get(name, ""))):
            raise EvidenceFormatError(f"{label} contains invalid {name}")
