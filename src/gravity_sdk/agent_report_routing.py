"""Narrow Agent recognizer routing for report products."""

from __future__ import annotations


REPORT_PRODUCTS = frozenset({"business_pulse", "company_usage"})


def report_product_query(name: str, query: str) -> bool:
    if name == "business_pulse":
        from .agent_business_pulse import business_pulse_query

        return business_pulse_query(query)
    from .agent_company_usage import company_usage_query

    return company_usage_query(query)


__all__ = ["REPORT_PRODUCTS", "report_product_query"]
