"""Narrow Agent recognizer routing for bounded no-spec products."""

from __future__ import annotations


REPORT_PRODUCTS = frozenset({"business_pulse", "company_usage", "custom_audience"})


def report_product_query(name: str, query: str) -> bool:
    if name == "business_pulse":
        from .agent_business_pulse import business_pulse_query

        return business_pulse_query(query)
    if name == "company_usage":
        from .agent_company_usage import company_usage_query

        return company_usage_query(query)
    from .agent_custom_audience import custom_audience_query

    return custom_audience_query(query)


__all__ = ["REPORT_PRODUCTS", "report_product_query"]
