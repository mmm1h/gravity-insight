from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gravity_insight import cli
from gravity_insight.skill_cli import dispatch


class Resolver:
    def __init__(self, **_options):
        pass

    def list(self):
        return {"schema_version": "gravity.skill-list.v1"}

    def get(self, skill):
        return {"schema_version": "gravity.skill-result.v1", "skill_uri": skill}

    def materialize_agent(self, skill, output):
        return {
            "schema_version": "gravity.agent-skill-materialization.v1",
            "skill_uri": skill,
            "output": output,
        }


class SDK:
    capability_trust = object()

    @classmethod
    def from_env(cls, **_options):
        return cls()


class SkillCliTests(unittest.TestCase):
    def test_commands_are_all_offline_first(self):
        parser = cli.build_parser()
        for argv in (
            ["skills", "list"],
            ["skills", "show", "gravity.game/example@1.0.0"],
            [
                "skills",
                "export-agent",
                "gravity.game/example@1.0.0",
                "--output",
                "out",
            ],
        ):
            with self.subTest(argv=argv):
                parsed = parser.parse_args(argv)
                self.assertFalse(parsed.network_required)
                self.assertEqual(
                    argv[1] == "export-agent",
                    bool(getattr(parsed, "product_file_output", False)),
                )

    @patch("gravity_insight.skill_package.LocalSkillResolver", Resolver)
    @patch("gravity_insight.workspace.load_workspace", return_value=object())
    @patch("gravity_insight.sdk.GravitySDK", SDK)
    def test_dispatch_delegates_without_owning_resolution(self, _workspace):
        listed = dispatch(SimpleNamespace(skills_command="list"), None)
        shown = dispatch(
            SimpleNamespace(
                skills_command="show", skill="gravity.game/example@1.0.0", workspace=None
            ),
            None,
        )
        exported = dispatch(
            SimpleNamespace(
                skills_command="export-agent",
                skill="gravity.game/example@1.0.0",
                output="out",
            ),
            None,
        )

        self.assertEqual("gravity.skill-list.v1", listed["schema_version"])
        self.assertEqual("gravity.skill-result.v1", shown["schema_version"])
        self.assertEqual("out", exported["output"])


if __name__ == "__main__":
    unittest.main()
