from __future__ import annotations

import json
import unittest
from types import SimpleNamespace

try:
    from gravity_insight.errors import PolicyViolation
    from gravity_insight.registry import _request_parts
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_insight.errors import PolicyViolation
    from gravity_insight.registry import _request_parts


class RequestCodecTests(unittest.TestCase):
    def test_onelink_codec_hides_filter_grammar_behind_promoted_object_id(self) -> None:
        operation = SimpleNamespace(operation_id="app.onelink.list")

        query, body = _request_parts(
            operation,
            {
                "turbo_promoted_object_id": "object-1",
                "page": 2,
                "page_size": 10,
            },
        )

        self.assertEqual({}, body)
        self.assertEqual(2, query["page"])
        self.assertEqual(10, query["page_size"])
        self.assertEqual(
            [
                {
                    "field": "turbo_promoted_object_id",
                    "operator": 6,
                    "values": ["object-1"],
                }
            ],
            json.loads(query["filters"]),
        )

    def test_onelink_codec_rejects_an_empty_parent_value(self) -> None:
        operation = SimpleNamespace(operation_id="app.onelink.list")

        with self.assertRaisesRegex(PolicyViolation, "promoted-object ID"):
            _request_parts(operation, {"turbo_promoted_object_id": ""})


if __name__ == "__main__":
    unittest.main()
