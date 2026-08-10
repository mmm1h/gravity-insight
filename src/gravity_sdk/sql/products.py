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
from typing import Any, Callable

from gravity_sdk.paths import DATA_CONTRACT_ROOT, EVIDENCE_ROOT, PROJECT_ROOT
from gravity_sdk.support.documents import replace_atomic_durable
from gravity_sdk.support.evidence import (
    EvidenceBinding,
    publish_json_snapshot,
    resolve_json_evidence,
    serialize_json_result,
)


ROOT = PROJECT_ROOT
BEIJING = timezone(timedelta(hours=8), name="Asia/Shanghai")
EVIDENCE_PATH = EVIDENCE_ROOT / "latest.json"
EVIDENCE_PRODUCT_ROOT = EVIDENCE_ROOT / "daily-verification"
DATASOURCE_PATH = DATA_CONTRACT_ROOT / "Gravity数据源.yaml"
EVENT_DICTIONARY_PATH = DATA_CONTRACT_ROOT / "Merge埋点字典.md"

PRODUCTS = (
    "payment-summary",
    "first-scene-coverage",
    "energy-profile-coverage",
    "event-coverage",
)
DEFAULT_APP_IDS = {
    "payment-summary": (29034827,),
    "first-scene-coverage": (29034827, 27192043, 24502679),
    "energy-profile-coverage": (29034827,),
    "event-coverage": (29034827,),
}
PRODUCT_CONTRACTS = {
    "payment-summary": DATA_CONTRACT_ROOT / "Gravity支付口径.md",
    "first-scene-coverage": DATA_CONTRACT_ROOT / "首次场景口径.md",
    "energy-profile-coverage": DATA_CONTRACT_ROOT / "体力消耗口径.md",
    "event-coverage": EVENT_DICTIONARY_PATH,
}
FORBIDDEN_CLAIMS = {
    "payment-summary": [
        "会计净收入或财务对账",
        "活动归因、投放回收或 ROI",
        "assignment/holdout 不完整时的因果 uplift",
    ],
    "first-scene-coverage": [
        "把用户属性 $first_scene 当作事件属性",
        "把空值或未知宿主解释为没有来源",
        "由场景覆盖率推导因果效果",
    ],
    "energy-profile-coverage": [
        "把累计/当前快照解释为窗口新增体力产耗",
        "用 paid_assets 还原逐次体力消耗",
        "由字段覆盖率推导活动效果",
    ],
    "event-coverage": [
        "把单日未出现解释为埋点失效",
        "声称已完成全部字段级验证",
        "由事件存在性推导活动或版本效果",
    ],
}
HOST_NAMES = {
    "01": "今日头条",
    "02": "抖音",
    "03": "皮皮虾",
    "04": "火山(旧)",
    "06": "头条极速",
    "10": "抖音极速",
    "14": "番茄畅听",
    "18": "番茄小说",
    "23": "火山(新)",
    "25": "PC抖音",
    "26": "红果",
    "27": "汽水",
    "28": "番茄音乐",
    "29": "抖音精选",
    "99": "IDE/特殊",
}
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class EvidenceFormatError(ValueError):
    pass


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
    if product not in PRODUCTS:
        raise ValueError(f"unknown product: {product}")
    values = tuple(dict.fromkeys(app_ids or DEFAULT_APP_IDS[product]))
    if not values or any(type(value) is not int or value <= 0 for value in values):
        raise ValueError("app ids must be positive integers")
    return values


def declared_events(path: Path = EVENT_DICTIONARY_PATH) -> list[str]:
    text = path.read_text(encoding="utf-8")
    marker = "## 事件索引"
    if marker not in text:
        raise EvidenceFormatError(f"{path}: missing event index")
    section = text.split(marker, 1)[1].split("\n## ", 1)[0]
    events: list[str] = []
    for line in section.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        event = cells[1]
        if event in {"", "埋点名称"} or set(event) <= {"-", ":"}:
            continue
        if event not in events:
            events.append(event)
    if not events:
        raise EvidenceFormatError(f"{path}: event index contains no events")
    return events


def build_sql(product: str, start_at: datetime, end_at: datetime, app_ids: tuple[int, ...]) -> str:
    app_ids = normalize_app_ids(product, app_ids)
    start = _sql_time(start_at)
    end = _sql_time(end_at)
    if product == "payment-summary":
        return _payment_sql(_app_filter("e", app_ids), _app_filter("", app_ids), start, end)
    if product == "first-scene-coverage":
        return _first_scene_sql(_app_filter("u", app_ids), _app_filter("", app_ids), start, end)
    if product == "energy-profile-coverage":
        return _energy_sql(
            _app_filter("e", app_ids),
            _app_filter("u", app_ids),
            _app_filter("", app_ids),
            start,
            end,
        )
    if product == "event-coverage":
        declared_events()
        return _event_sql(
            _app_filter("e", app_ids),
            _app_filter("coverage", app_ids),
            start,
            end,
        )
    raise ValueError(f"unknown product: {product}")


def _payment_sql(app_filter: str, outer_filter: str, start: str, end: str) -> str:
    return f"""WITH raw_pay AS (
  SELECT
    app_id,
    user_id,
    create_time,
    COALESCE(get_json_string(properties, '$.$pay_amount'), '') AS amount_raw,
    COALESCE(get_json_string(properties, '$.$pay_reason'), '') AS pay_reason,
    COALESCE(get_json_string(properties, '$.$order_id'), '') AS order_key,
    COALESCE(get_json_string(properties, '$.$pay_type'), '') AS pay_type,
    COALESCE(get_json_string(properties, '$.$pay_method'), '') AS pay_method
  FROM `default`.`event` e
  WHERE {app_filter}
    AND e.event = '$PayEvent'
    AND e.create_time >= CAST('{start}' AS DATETIME)
    AND e.create_time < CAST('{end}' AS DATETIME)
),
keyed AS (
  SELECT
    *,
    COALESCE(
      NULLIF(order_key, ''),
      CONCAT(
        CAST(user_id AS VARCHAR), '|', CAST(create_time AS VARCHAR), '|',
        pay_reason, '|', amount_raw
      )
    ) AS pay_key,
    CASE
      WHEN amount_raw REGEXP '^[0-9]+$' THEN CAST(amount_raw AS BIGINT)
      ELSE 0
    END AS amount_cent
  FROM raw_pay
),
pay_ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (
      PARTITION BY app_id, pay_key
      ORDER BY CAST(create_time AS DATETIME)
    ) AS duplicate_rank
  FROM keyed
)
SELECT
  app_id,
  COUNT(*) AS pay_event_rows,
  SUM(CASE WHEN duplicate_rank = 1 THEN 1 ELSE 0 END) AS order_count,
  COUNT(DISTINCT CASE WHEN duplicate_rank = 1 THEN user_id ELSE NULL END) AS buyer_count,
  SUM(CASE WHEN duplicate_rank = 1 THEN amount_cent ELSE 0 END) AS revenue_cent,
  SUM(CASE WHEN duplicate_rank > 1 THEN 1 ELSE 0 END) AS duplicate_rows,
  SUM(CASE WHEN amount_raw = '' THEN 1 ELSE 0 END) AS missing_amount_rows,
  SUM(CASE WHEN amount_raw <> '' AND NOT (amount_raw REGEXP '^[0-9]+$') THEN 1 ELSE 0 END) AS invalid_amount_rows,
  SUM(CASE WHEN pay_reason = '' THEN 1 ELSE 0 END) AS missing_reason_rows,
  SUM(CASE WHEN order_key = '' THEN 1 ELSE 0 END) AS fallback_order_key_rows,
  SUM(CASE WHEN pay_type = '' THEN 1 ELSE 0 END) AS missing_pay_type_rows,
  SUM(CASE WHEN pay_method = '' THEN 1 ELSE 0 END) AS missing_pay_method_rows,
  SUM(CASE WHEN pay_type <> '' AND pay_type <> 'CNY' THEN 1 ELSE 0 END) AS non_cny_rows,
  COUNT(DISTINCT NULLIF(pay_method, '')) AS pay_method_value_count,
  MIN(NULLIF(pay_method, '')) AS pay_method_min,
  MAX(NULLIF(pay_method, '')) AS pay_method_max,
  COUNT(DISTINCT NULLIF(pay_type, '')) AS pay_type_value_count,
  MIN(NULLIF(pay_type, '')) AS pay_type_min,
  MAX(NULLIF(pay_type, '')) AS pay_type_max,
  MIN(create_time) AS first_pay_at,
  MAX(create_time) AS last_pay_at
FROM pay_ranked
WHERE {outer_filter}
GROUP BY app_id
ORDER BY app_id
LIMIT 1000"""


def _first_scene_sql(app_filter: str, outer_filter: str, start: str, end: str) -> str:
    return f"""WITH user_scene AS (
  SELECT
    app_id,
    COALESCE(get_json_string(properties, '$.$first_scene'), '') AS scene
  FROM `default`.`user` u
  WHERE {app_filter}
    AND u.create_time >= CAST('{start}' AS DATETIME)
    AND u.create_time < CAST('{end}' AS DATETIME)
)
SELECT
  app_id,
  CASE
    WHEN scene = '' THEN 'missing'
    WHEN LENGTH(scene) = 6 THEN 'reported'
    ELSE 'invalid_format'
  END AS scene_status,
  CASE WHEN LENGTH(scene) = 6 THEN SUBSTR(scene, 1, 2) ELSE '' END AS host_prefix,
  COUNT(*) AS registrations
FROM user_scene
WHERE {outer_filter}
GROUP BY
  app_id,
  CASE
    WHEN scene = '' THEN 'missing'
    WHEN LENGTH(scene) = 6 THEN 'reported'
    ELSE 'invalid_format'
  END,
  CASE WHEN LENGTH(scene) = 6 THEN SUBSTR(scene, 1, 2) ELSE '' END
ORDER BY app_id, scene_status, host_prefix
LIMIT 10000"""


def _energy_sql(
    app_filter: str,
    user_filter: str,
    outer_filter: str,
    start: str,
    end: str,
) -> str:
    return f"""WITH active AS (
  SELECT
    app_id,
    user_id,
    SUM(CASE WHEN event = 'AssetList' THEN 1 ELSE 0 END) AS assetlist_events
  FROM `default`.`event` e
  WHERE {app_filter}
    AND e.create_time >= CAST('{start}' AS DATETIME)
    AND e.create_time < CAST('{end}' AS DATETIME)
    AND e.user_id IS NOT NULL
  GROUP BY app_id, user_id
),
per_user AS (
  SELECT
    a.app_id,
    a.user_id,
    MAX(a.assetlist_events) AS assetlist_events,
    MAX(CASE WHEN u.id IS NOT NULL THEN 1 ELSE 0 END) AS has_profile_row,
    MAX(CASE WHEN COALESCE(get_json_string(u.prop_concat, '$.total_getpower_num'), '') <> '' THEN 1 ELSE 0 END) AS has_getpower,
    MAX(CASE WHEN COALESCE(get_json_string(u.prop_concat, '$.total_usepower_num'), '') <> '' THEN 1 ELSE 0 END) AS has_usepower,
    MAX(CASE WHEN COALESCE(get_json_string(u.prop_concat, '$.current_power'), '') <> '' THEN 1 ELSE 0 END) AS has_current_power
  FROM active a
  LEFT JOIN `default`.`user` u
    ON u.app_id = a.app_id
   AND u.id = a.user_id
   AND {user_filter}
  GROUP BY a.app_id, a.user_id
)
SELECT
  app_id,
  COUNT(*) AS active_users,
  SUM(has_profile_row) AS profile_row_users,
  SUM(has_getpower) AS getpower_users,
  SUM(has_usepower) AS usepower_users,
  SUM(has_current_power) AS current_power_users,
  SUM(CASE
    WHEN has_getpower = 1 AND has_usepower = 1 AND has_current_power = 1
    THEN 1 ELSE 0 END
  ) AS complete_profile_users,
  SUM(assetlist_events) AS assetlist_events,
  SUM(CASE WHEN assetlist_events > 0 THEN 1 ELSE 0 END) AS assetlist_users
FROM per_user
WHERE {outer_filter}
GROUP BY app_id
ORDER BY app_id
LIMIT 1000"""


def _event_sql(
    app_filter: str,
    outer_filter: str,
    start: str,
    end: str,
) -> str:
    return f"""WITH filtered AS (
  SELECT app_id, user_id, event, create_time
  FROM `default`.`event` e
  WHERE {app_filter}
    AND e.create_time >= CAST('{start}' AS DATETIME)
    AND e.create_time < CAST('{end}' AS DATETIME)
)
SELECT *
FROM (
SELECT
  app_id,
  '__all__' AS event_name,
  COUNT(*) AS event_rows,
  COUNT(DISTINCT user_id) AS active_users,
  MIN(create_time) AS first_event_at,
  MAX(create_time) AS last_event_at
FROM filtered
GROUP BY app_id
UNION ALL
SELECT
  app_id,
  event AS event_name,
  COUNT(*) AS event_rows,
  COUNT(DISTINCT user_id) AS active_users,
  MIN(create_time) AS first_event_at,
  MAX(create_time) AS last_event_at
FROM filtered
GROUP BY app_id, event
) coverage
WHERE {outer_filter}
ORDER BY app_id, event_name
LIMIT 10000"""


def run_product(
    client: Any,
    product: str,
    start_at: datetime,
    end_at: datetime,
    app_ids: list[int] | tuple[int, ...] | None = None,
) -> dict[str, Any]:
    apps = normalize_app_ids(product, app_ids)
    sql = build_sql(product, start_at, end_at, apps)
    rows = client.execute_sql(sql)
    summary, status, warnings, notes = _SUMMARIZERS[product](rows, apps, start_at, end_at)
    result: dict[str, Any] = {
        "product": product,
        "status": status,
        "window": _window_dict(start_at, end_at),
        "app_ids": list(apps),
        "summary": summary,
        "warnings": warnings,
        "forbidden_claims": FORBIDDEN_CLAIMS[product],
        "hashes": {
            "sql_sha256": _sha256_text(sql),
            "result_sha256": _sha256_json(rows),
            "contract_sha256": contract_hash(product),
        },
    }
    if notes:
        result["notes"] = notes
    return result


def summarize_payment(
    rows: list[dict[str, Any]],
    app_ids: tuple[int, ...],
    _start_at: datetime,
    _end_at: datetime,
) -> tuple[dict[str, Any], str, list[str], list[str]]:
    by_app = {_as_int(row.get("app_id")): row for row in rows}
    apps: list[dict[str, Any]] = []
    warnings: list[str] = []
    for app_id in app_ids:
        row = by_app.get(app_id, {})
        item = {
            "app_id": app_id,
            "pay_event_rows": _as_int(row.get("pay_event_rows")),
            "order_count": _as_int(row.get("order_count")),
            "buyer_count": _as_int(row.get("buyer_count")),
            "revenue_cent": _as_int(row.get("revenue_cent")),
            "duplicate_rows": _as_int(row.get("duplicate_rows")),
            "missing_amount_rows": _as_int(row.get("missing_amount_rows")),
            "invalid_amount_rows": _as_int(row.get("invalid_amount_rows")),
            "missing_reason_rows": _as_int(row.get("missing_reason_rows")),
            "fallback_order_key_rows": _as_int(row.get("fallback_order_key_rows")),
            "missing_pay_type_rows": _as_int(row.get("missing_pay_type_rows")),
            "missing_pay_method_rows": _as_int(row.get("missing_pay_method_rows")),
            "non_cny_rows": _as_int(row.get("non_cny_rows")),
            "pay_method_value_count": _as_int(row.get("pay_method_value_count")),
            "pay_method_min": _nullable_text(row.get("pay_method_min")),
            "pay_method_max": _nullable_text(row.get("pay_method_max")),
            "pay_type_value_count": _as_int(row.get("pay_type_value_count")),
            "pay_type_min": _nullable_text(row.get("pay_type_min")),
            "pay_type_max": _nullable_text(row.get("pay_type_max")),
            "first_pay_at": _nullable_text(row.get("first_pay_at")),
            "last_pay_at": _nullable_text(row.get("last_pay_at")),
        }
        item["revenue_yuan"] = round(item["revenue_cent"] / 100.0, 2)
        apps.append(item)
        if item["pay_event_rows"] == 0:
            warnings.append(f"app_id={app_id}: no $PayEvent rows were observed")
        for field in (
            "duplicate_rows",
            "missing_amount_rows",
            "invalid_amount_rows",
            "missing_reason_rows",
            "fallback_order_key_rows",
            "missing_pay_type_rows",
            "missing_pay_method_rows",
            "non_cny_rows",
        ):
            if item[field]:
                warnings.append(f"app_id={app_id}: {field}={item[field]}")
    return {"apps": apps, "activity_attribution": "not_provided"}, "partial" if warnings else "complete", warnings, []


def summarize_first_scene(
    rows: list[dict[str, Any]],
    app_ids: tuple[int, ...],
    _start_at: datetime,
    _end_at: datetime,
) -> tuple[dict[str, Any], str, list[str], list[str]]:
    apps: list[dict[str, Any]] = []
    warnings: list[str] = []
    for app_id in app_ids:
        app_rows = [row for row in rows if _as_int(row.get("app_id")) == app_id]
        breakdown = []
        totals = {"reported": 0, "missing": 0, "invalid_format": 0}
        for row in app_rows:
            status = str(row.get("scene_status") or "invalid_format")
            count = _as_int(row.get("registrations"))
            totals[status if status in totals else "invalid_format"] += count
            host_prefix = str(row.get("host_prefix") or "")
            breakdown.append(
                {
                    "scene_status": status,
                    "host_prefix": host_prefix,
                    "host_name": HOST_NAMES.get(host_prefix, "空值/未列举宿主"),
                    "registrations": count,
                }
            )
        registrations = sum(totals.values())
        with_scene = totals["reported"] + totals["invalid_format"]
        apps.append(
            {
                "app_id": app_id,
                "registrations": registrations,
                "with_scene": with_scene,
                "six_digit_scene": totals["reported"],
                "missing_scene": totals["missing"],
                "invalid_format": totals["invalid_format"],
                "coverage_rate": round(with_scene / registrations, 6) if registrations else None,
                "by_status_host": breakdown,
            }
        )
        if registrations == 0:
            warnings.append(f"app_id={app_id}: no registrations were observed")
        elif totals["missing"] or totals["invalid_format"]:
            warnings.append(
                f"app_id={app_id}: missing_scene={totals['missing']}, invalid_format={totals['invalid_format']}"
            )
    return {"apps": apps}, "partial" if warnings else "complete", warnings, []


def summarize_energy(
    rows: list[dict[str, Any]],
    app_ids: tuple[int, ...],
    _start_at: datetime,
    _end_at: datetime,
) -> tuple[dict[str, Any], str, list[str], list[str]]:
    by_app = {_as_int(row.get("app_id")): row for row in rows}
    apps: list[dict[str, Any]] = []
    warnings: list[str] = []
    notes: list[str] = []
    for app_id in app_ids:
        row = by_app.get(app_id, {})
        active = _as_int(row.get("active_users"))
        complete = _as_int(row.get("complete_profile_users"))
        item = {
            "app_id": app_id,
            "active_users": active,
            "profile_row_users": _as_int(row.get("profile_row_users")),
            "getpower_users": _as_int(row.get("getpower_users")),
            "usepower_users": _as_int(row.get("usepower_users")),
            "current_power_users": _as_int(row.get("current_power_users")),
            "complete_profile_users": complete,
            "complete_profile_coverage_rate": round(complete / active, 6) if active else None,
            "assetlist_events": _as_int(row.get("assetlist_events")),
            "assetlist_users": _as_int(row.get("assetlist_users")),
        }
        apps.append(item)
        if active == 0:
            warnings.append(f"app_id={app_id}: no active users were observed")
        elif complete < active:
            warnings.append(f"app_id={app_id}: complete energy profile coverage is {complete}/{active}")
        if item["assetlist_events"] == 0:
            notes.append(f"app_id={app_id}: AssetList was absent; this is diagnostic-only")
    return {"apps": apps, "measurement": "current cumulative/profile snapshot coverage"}, "partial" if warnings else "complete", warnings, notes


def summarize_events(
    rows: list[dict[str, Any]],
    app_ids: tuple[int, ...],
    _start_at: datetime,
    end_at: datetime,
) -> tuple[dict[str, Any], str, list[str], list[str]]:
    declarations = declared_events()
    apps: list[dict[str, Any]] = []
    warnings: list[str] = []
    notes: list[str] = []
    for app_id in app_ids:
        app_rows = [row for row in rows if _as_int(row.get("app_id")) == app_id]
        overall = next((row for row in app_rows if row.get("event_name") == "__all__"), {})
        event_rows = [row for row in app_rows if row.get("event_name") != "__all__"]
        observed_rows = [row for row in event_rows if row.get("event_name") in declarations]
        observed = {str(row["event_name"]) for row in observed_rows}
        missing = [event for event in declarations if event not in observed]
        unknown = sorted(str(row["event_name"]) for row in event_rows if row.get("event_name") not in declarations)
        item = {
            "app_id": app_id,
            "event_rows": _as_int(overall.get("event_rows")),
            "active_users": _as_int(overall.get("active_users")),
            "first_event_at": _nullable_text(overall.get("first_event_at")),
            "last_event_at": _nullable_text(overall.get("last_event_at")),
            "declared_events": len(declarations),
            "observed_events": len(observed),
            "missing_events": missing,
            "unknown_events": unknown,
            "events": [
                {
                    "event_name": str(row["event_name"]),
                    "event_rows": _as_int(row.get("event_rows")),
                    "active_users": _as_int(row.get("active_users")),
                    "first_event_at": _nullable_text(row.get("first_event_at")),
                    "last_event_at": _nullable_text(row.get("last_event_at")),
                }
                for row in sorted(observed_rows, key=lambda value: str(value["event_name"]))
            ],
        }
        apps.append(item)
        if not item["event_rows"]:
            warnings.append(f"app_id={app_id}: no events were observed")
        else:
            last_at = _parse_gravity_time(item["last_event_at"])
            if last_at is None or last_at < end_at - timedelta(minutes=15):
                warnings.append(f"app_id={app_id}: latest event is more than 15 minutes before window end")
        if missing:
            notes.append(
                f"app_id={app_id}: {len(missing)} declared events were not observed; absence is informational"
            )
        if unknown:
            notes.append(f"app_id={app_id}: {len(unknown)} observed events are not declared in the dictionary")
    return {"apps": apps, "coverage": "declared-event presence only"}, "partial" if warnings else "complete", warnings, notes


_SUMMARIZERS: dict[
    str,
    Callable[
        [list[dict[str, Any]], tuple[int, ...], datetime, datetime],
        tuple[dict[str, Any], str, list[str], list[str]],
    ],
] = {
    "payment-summary": summarize_payment,
    "first-scene-coverage": summarize_first_scene,
    "energy-profile-coverage": summarize_energy,
    "event-coverage": summarize_events,
}


def build_evidence(day: date, product_results: list[dict[str, Any]]) -> dict[str, Any]:
    if len(product_results) != len(PRODUCTS) or {
        result.get("product") for result in product_results
    } != set(PRODUCTS):
        raise EvidenceFormatError("verification must contain exactly the four built-in products")
    start_at, end_at = day_window(day)
    products = {result["product"]: result for result in product_results}
    warnings = [
        f"{product}: {warning}"
        for product, result in products.items()
        for warning in result.get("warnings", [])
    ]
    forbidden = list(
        dict.fromkeys(
            claim
            for product in PRODUCTS
            for claim in products[product].get("forbidden_claims", [])
        )
    )
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "datasource_id": "gravity_merge2_v1",
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
            {product: products[product]["hashes"]["sql_sha256"] for product in PRODUCTS}
        ),
        "result_sha256": _sha256_json(products),
        "contract_sha256": _sha256_json(
            {product: products[product]["hashes"]["contract_sha256"] for product in PRODUCTS}
        ),
    }
    validate_evidence(evidence)
    return evidence


def verify_all(client: Any, day: date) -> dict[str, Any]:
    start_at, end_at = day_window(day)
    results = [
        run_product(client, product, start_at, end_at, DEFAULT_APP_IDS[product])
        for product in PRODUCTS
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
    if (
        type(evidence["schema_version"]) is not int
        or evidence["schema_version"] != 1
        or evidence["datasource_id"] != "gravity_merge2_v1"
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
    if not isinstance(products, dict) or set(products) != set(PRODUCTS):
        raise EvidenceFormatError("evidence must contain exactly the four built-in products")
    for product in PRODUCTS:
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
        for product in PRODUCTS
        for warning in products[product]["warnings"]
    ]
    expected_forbidden = list(
        dict.fromkeys(
            claim
            for product in PRODUCTS
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
    expected_hashes = {
        "sql_sha256": _sha256_json(
            {product: products[product]["hashes"]["sql_sha256"] for product in PRODUCTS}
        ),
        "result_sha256": _sha256_json(products),
        "contract_sha256": _sha256_json(
            {product: products[product]["hashes"]["contract_sha256"] for product in PRODUCTS}
        ),
    }
    if evidence["hashes"] != expected_hashes:
        raise EvidenceFormatError("evidence content does not match its top-level hashes")


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
    base = {
        "datasource_id": "gravity_merge2_v1",
        "declared_status": declared,
        "latest_safe_date": safe_day.isoformat(),
        "evidence_path": (EVIDENCE_PRODUCT_ROOT / "latest.yaml").relative_to(ROOT).as_posix(),
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
    has_token = bool(keys.intersection({"GRAVITY_AUTH_TOKEN", "GRAVITY_AUTHORIZATION"}))
    has_login = {"GRAVITY_USERNAME", "GRAVITY_PASSWORD"}.issubset(keys)
    return "ignored_local_file" if has_token or has_login else "missing"


def datasource_verification_status(path: Path = DATASOURCE_PATH) -> str:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EvidenceFormatError(f"cannot read datasource contract: {exc}") from exc
    match = re.search(r'(?m)^verification_status:\s*["\']?([a-z_]+)', text)
    if not match:
        raise EvidenceFormatError("datasource contract is missing verification_status")
    status = match.group(1)
    if status not in {"pending_review", "verified", "verified_with_gaps", "blocked"}:
        raise EvidenceFormatError(f"invalid datasource verification_status: {status}")
    return status


def contract_hash(product: str) -> str:
    try:
        return hashlib.sha256(PRODUCT_CONTRACTS[product].read_bytes()).hexdigest()
    except (KeyError, OSError) as exc:
        raise EvidenceFormatError(f"cannot hash contract for {product}: {exc}") from exc


def dry_run_checks() -> None:
    start_at, end_at = day_window(date(2026, 7, 22))
    for product in PRODUCTS:
        sql = build_sql(product, start_at, end_at, DEFAULT_APP_IDS[product])
        if "2026-07-22 00:00:00" not in sql or "2026-07-23 00:00:00" not in sql:
            raise AssertionError(f"{product}: rendered SQL has the wrong window")
        if "user_id" in _SUMMARIZERS[product]([], DEFAULT_APP_IDS[product], start_at, end_at)[0]:
            raise AssertionError(f"{product}: aggregate summary leaked a user-level key")
    if len(declared_events()) != 72:
        raise AssertionError("event dictionary must expose 72 declared events")
    if latest_safe_date(datetime(2026, 7, 23, 1, 59, tzinfo=BEIJING)) != date(2026, 7, 21):
        raise AssertionError("pre-02:00 safe-day rule failed")
    if latest_safe_date(datetime(2026, 7, 23, 2, 0, tzinfo=BEIJING)) != date(2026, 7, 22):
        raise AssertionError("post-02:00 safe-day rule failed")


def _stale_reason(evidence: dict[str, Any], safe_day: date) -> str | None:
    if evidence["verified_for_date"] != safe_day.isoformat():
        return f"evidence date {evidence['verified_for_date']} != latest safe date {safe_day.isoformat()}"
    for product in PRODUCTS:
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


def _app_filter(alias: str, app_ids: tuple[int, ...]) -> str:
    prefix = f"{alias}." if alias else ""
    return "(" + " OR ".join(f"{prefix}app_id = {app_id}" for app_id in app_ids) + ")"


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


def _as_int(value: Any) -> int:
    if value in (None, ""):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceFormatError(f"expected integer aggregate, got {value!r}") from exc


def _nullable_text(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _parse_gravity_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=BEIJING) if parsed.tzinfo is None else parsed.astimezone(BEIJING)
