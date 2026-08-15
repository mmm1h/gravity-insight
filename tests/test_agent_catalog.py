from __future__ import annotations

from types import SimpleNamespace
import importlib.util
from pathlib import Path
import unittest

from gravity_sdk import GravityInsightClient
from gravity_sdk.agent import SCHEMA_VERSION as AGENT_SCHEMA_VERSION, discover_capabilities
from gravity_sdk.agent_catalog import SCHEMA_VERSION, run_agent_catalog_command


def _args(action: str, **values: object) -> SimpleNamespace:
    return SimpleNamespace(agent_catalog_command=action, **values)


class AgentCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = GravityInsightClient.from_env()

    def test_categories_are_manifest_and_card_derived_offline(self) -> None:
        result = run_agent_catalog_command(_args("categories"), self.client)
        self.assertEqual(SCHEMA_VERSION, result["schema_version"])
        self.assertTrue(result["offline"])
        self.assertFalse(result["network_called"])
        analysis = next(item for item in result["categories"] if item["name"] == "analysis")
        self.assertGreater(analysis["composites"], 0)
        self.assertGreater(analysis["operations"], 0)

    def test_category_is_bounded_and_describe_reuses_existing_card(self) -> None:
        listed = run_agent_catalog_command(
            _args("category", name="analysis", limit=1, offset=0), self.client
        )
        self.assertEqual("get_category_capabilities", listed["mode"])
        self.assertEqual(1, listed["count"])
        self.assertEqual(1, len(listed["capabilities"]))

        described = run_agent_catalog_command(
            _args("describe", selector="composite:analysis_context"), self.client
        )
        self.assertEqual("describe_capability", described["mode"])
        self.assertEqual("composite:analysis_context", described["capability"]["selector"])
        self.assertEqual("read", described["capability"]["effect"])

    def test_existing_agent_protocol_is_unchanged(self) -> None:
        result = discover_capabilities("event analysis", client=self.client)
        self.assertEqual(AGENT_SCHEMA_VERSION, result["schema_version"])
        self.assertEqual("discover_and_describe", result["mode"])


class AgentGuideGenerationTests(unittest.TestCase):
    def test_committed_guides_match_the_contract_generator(self) -> None:
        root = Path(__file__).resolve().parents[1]
        script = root / "scripts" / "generate_agent_skills.py"
        spec = importlib.util.spec_from_file_location("agent_guides", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for path, content in module.render_documents().items():
            with self.subTest(path=path.name):
                self.assertEqual(content, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
