"""Kernel SQL renderers used by workspace-defined products."""

from __future__ import annotations

from typing import Any, Mapping


def render_product_sql(
    definition: Mapping[str, Any],
    app_ids: tuple[int, ...],
    start: str,
    end: str,
) -> str:
    kind = str(definition["kind"])
    if kind == "payment-summary":
        return _payment_sql(_app_filter("e", app_ids), _app_filter("", app_ids), start, end)
    if kind == "event-coverage":
        return _event_sql(
            _app_filter("e", app_ids), _app_filter("coverage", app_ids), start, end
        )
    raise ValueError(f"unsupported SQL product kind: {kind}")


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


def _event_sql(app_filter: str, outer_filter: str, start: str, end: str) -> str:
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


def _app_filter(alias: str, app_ids: tuple[int, ...]) -> str:
    prefix = f"{alias}." if alias else ""
    return "(" + " OR ".join(f"{prefix}app_id = {app_id}" for app_id in app_ids) + ")"


__all__ = ["render_product_sql"]
