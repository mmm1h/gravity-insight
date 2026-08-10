from __future__ import annotations

import json
import unittest
from pathlib import Path

try:
    from gravity_sdk import GravityInsightClient
except ModuleNotFoundError:  # source checkout before editable installation
    from gravity_sdk import GravityInsightClient


ROOT = Path(__file__).resolve().parents[1]
OPERATION_ROOT = (
    ROOT / "src" / "gravity_sdk" / "contracts" / "operations"
)


class GravityInsightExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = GravityInsightClient.from_env()

    def test_every_contract_example_passes_offline_input_validation(self):
        example_count = 0
        for path in sorted(OPERATION_ROOT.glob("*.json")):
            operation = json.loads(path.read_text(encoding="utf-8"))["operation"]
            operation_id = operation["operation_id"]
            for example in operation["examples"]:
                example_count += 1
                with self.subTest(operation_id=operation_id, example=example["name"]):
                    result = self.client.validate(operation_id, example["inputs"])
                    self.assertTrue(result["ok"], result.get("error"))
                    self.assertFalse(result["network_called"])
                    self.assertIn(
                        result["status"], {"valid_offline", "needs_live_metadata"}
                    )
        self.assertGreater(example_count, 0)


if __name__ == "__main__":
    unittest.main()
