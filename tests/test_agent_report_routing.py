from __future__ import annotations

import unittest

from gravity_insight.agents.report_routing import NO_SPEC_PRODUCTS, REPORT_PRODUCTS


class AgentReportRoutingTests(unittest.TestCase):
    def test_legacy_report_products_name_is_same_object_alias(self) -> None:
        self.assertIs(NO_SPEC_PRODUCTS, REPORT_PRODUCTS)
        self.assertEqual(
            {
                "advertiser_profile",
                "business_pulse",
                "company_usage",
                "custom_audience",
                "report_directory",
                "report_subscriptions",
            },
            NO_SPEC_PRODUCTS,
        )


if __name__ == "__main__":
    unittest.main()
