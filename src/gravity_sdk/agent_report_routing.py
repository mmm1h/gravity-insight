"""Narrow Agent recognizer routing for bounded no-spec products."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

REPORT_PRODUCTS = frozenset({
    "advertiser_profile",
    "business_pulse",
    "company_usage",
    "custom_audience",
})


def report_product_query(name: str, query: str) -> bool:
    if name == "business_pulse":
        from .agent_business_pulse import business_pulse_query

        return business_pulse_query(query)
    if name == "advertiser_profile":
        from .agent_advertiser_profile import advertiser_profile_query

        return advertiser_profile_query(query)
    if name == "company_usage":
        from .agent_company_usage import company_usage_query

        return company_usage_query(query)
    if name == "custom_audience":
        from .agent_custom_audience import custom_audience_query

        return custom_audience_query(query)
    raise ValueError(f"unknown report product: {name}")


def report_product_plan_request(
    name: str, card: Mapping[str, Any]
) -> dict[str, Any]:
    if name == "business_pulse":
        from .agent_business_pulse import business_pulse_plan_request

        return business_pulse_plan_request(card)
    if name == "advertiser_profile":
        from .agent_advertiser_profile import advertiser_profile_plan_request

        return advertiser_profile_plan_request(card)
    if name == "company_usage":
        from .agent_company_usage import company_usage_plan_request

        return company_usage_plan_request(card)
    if name == "custom_audience":
        from .agent_custom_audience import custom_audience_plan_request

        return custom_audience_plan_request(card)
    raise ValueError(f"unknown report product: {name}")


__all__ = [
    "REPORT_PRODUCTS",
    "report_product_plan_request",
    "report_product_query",
]
