from __future__ import annotations

import unittest

from gravity_insight.cli import _ndjson_rows
from gravity_insight.models import BatchResult
from gravity_insight.result_source import (
    CALLER_DEFINED,
    GOVERNED_PRODUCT,
    LOCAL_AUDIT,
    RAW_OPERATION,
    aggregate_result_sources,
    card_result_source,
    plan_result_source,
    result_source,
)
from gravity_insight.sql.query import _envelope


class ResultSourceTests(unittest.TestCase):
    def test_tiers_are_discrete_facts_without_a_score(self) -> None:
        for tier in (GOVERNED_PRODUCT, CALLER_DEFINED, RAW_OPERATION, LOCAL_AUDIT):
            with self.subTest(tier=tier):
                source = result_source(tier)
                self.assertEqual(tier, source["tier"])
                self.assertNotIn("score", source)
                self.assertNotIn("confidence", source)

    def test_sdk_sql_plan_agent_and_ndjson_use_the_same_contract(self) -> None:
        raw = BatchResult("app.list", True, "success").to_dict()
        sql = _envelope([])
        _, metadata = _ndjson_rows(sql)
        self.assertEqual(result_source(RAW_OPERATION), raw["result_source"])
        self.assertEqual(result_source(CALLER_DEFINED), sql["result_source"])
        self.assertEqual(sql["result_source"], metadata["result_source"])
        self.assertEqual(sql["result_source"], plan_result_source("sql_product", {}))
        self.assertEqual(sql["result_source"], card_result_source({"kind": "sql_product"}))
        mixed = aggregate_result_sources([raw, {"result_source": sql["result_source"]}])
        self.assertEqual("mixed", mixed["tier"])


if __name__ == "__main__":
    unittest.main()
