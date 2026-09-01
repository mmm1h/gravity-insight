from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest

from gravity_insight.skill_contract import skill_artifact
from gravity_insight.skill_render import (
    agent_skill_name,
    render_agent_export,
    render_docs_mirror,
    render_guide,
    render_package_files,
    skill_package_descriptor,
)


ROOT = Path(__file__).resolve().parents[1]
SKILL_URI = "skill://gravity.game/ap-cost-anomaly-localization@1.0.0"


class SkillRenderTests(unittest.TestCase):
    def test_repeated_package_render_is_byte_identical(self):
        artifact = skill_artifact(SKILL_URI)

        first_files = render_package_files(artifact)
        second_files = render_package_files(artifact)
        first = skill_package_descriptor(artifact)
        second = skill_package_descriptor(artifact)

        self.assertEqual(first_files, second_files)
        self.assertEqual(first, second)
        self.assertRegex(first["package_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            render_guide(artifact["contract"]),
            first_files["GUIDE.md"].decode("utf-8"),
        )
        self.assertEqual(
            sorted(first_files), [item["path"] for item in first["files"]]
        )

    def test_agent_export_meets_frontmatter_and_progressive_disclosure_limits(self):
        artifact = skill_artifact(SKILL_URI)
        export = render_agent_export(artifact, [artifact["contract"]])
        files = {item["path"]: item["content"] for item in export["files"]}
        lines = files["SKILL.md"].splitlines()
        name = lines[1].split(":", 1)[1].strip()
        description = json.loads(lines[2].split(":", 1)[1].strip())
        frontmatter_keys = {
            line.split(":", 1)[0]
            for line in lines[1:lines[1:].index("---") + 1]
            if line and not line.startswith(" ")
        }

        self.assertEqual(export["directory"], name)
        self.assertRegex(name, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
        self.assertLessEqual(len(name), 64)
        self.assertTrue(1 <= len(description) <= 1024)
        self.assertLess(len(lines), 500)
        self.assertEqual({"name", "description", "metadata"}, frontmatter_keys)
        self.assertIn("  gravity-runtime-requires: ", files["SKILL.md"])
        self.assertEqual(
            {
                "SKILL.md",
                "references/GUIDE.md",
                "references/SCHEMA.json",
                "references/CLAIMS.md",
                "references/EXAMPLES.md",
            },
            set(files),
        )
        self.assertIn("# Run Examples", files["references/EXAMPLES.md"])
        self.assertNotIn("scripts/", repr(files))
        self.assertFalse(export["network_called"])

    def test_namespace_normalization_collision_and_long_name_are_stable(self):
        original = skill_artifact(SKILL_URI)["contract"]
        first = copy.deepcopy(original)
        second = copy.deepcopy(original)
        first["namespace"] = "studio.alpha"
        second["namespace"] = "studio-alpha"
        registry = [first, second]

        first_name = agent_skill_name(first, registry)
        second_name = agent_skill_name(second, registry)
        long_contract = copy.deepcopy(original)
        long_contract["namespace"] = "very.long.namespace.with.many.sections.for.export.boundary"
        long_contract["skill_id"] = "a-very-long-skill-name-for-deterministic-export"
        long_name = agent_skill_name(long_contract, [long_contract])

        self.assertNotEqual(first_name, second_name)
        self.assertTrue(first_name.startswith("studio-alpha-"))
        self.assertTrue(second_name.startswith("studio-alpha-"))
        self.assertLessEqual(len(long_name), 64)
        self.assertEqual(long_name, agent_skill_name(long_contract, [long_contract]))

    def test_docs_and_package_generators_are_current(self):
        artifact = skill_artifact(SKILL_URI)
        docs = ROOT / "docs" / "agent-skills" / "ap-cost-anomaly-localization.md"
        self.assertFalse(docs.exists())
        self.assertEqual(render_docs_mirror(artifact), render_docs_mirror(artifact))

        script = ROOT / "scripts" / "generate_skill_packages.py"
        spec = importlib.util.spec_from_file_location("skill_packages", script)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for path, content in module.render_outputs().items():
            with self.subTest(path=path):
                self.assertEqual(content, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
