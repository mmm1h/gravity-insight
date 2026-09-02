from __future__ import annotations

import unittest

from gravity_insight import cli
from gravity_insight.errors import InputValidationError


class SkillCliTests(unittest.TestCase):
    def test_commands_are_all_offline_first(self):
        parser = cli.build_parser()
        for argv in (
            ["skills", "list"],
            [
                "skills", "show",
                "gravity.game/example@1.0.0",
            ],
        ):
            with self.subTest(argv=argv):
                parsed = parser.parse_args([*argv, "--state-root", "state"])
                self.assertFalse(parsed.network_required)

    def test_builtin_only_export_surface_is_removed(self):
        with self.assertRaises(InputValidationError):
            cli.build_parser().parse_args(
                [
                    "skills",
                    "export-agent",
                    "gravity.game/example@1.0.0",
                    "--output",
                    "out",
                ]
            )

    def test_hub_list_and_show_require_explicit_state_root(self):
        parser = cli.build_parser()
        for argv in (
            ["skills", "list"],
            ["skills", "show", "gravity.game/example@1.0.0"],
        ):
            with self.subTest(argv=argv), self.assertRaises(InputValidationError):
                parser.parse_args(argv)


if __name__ == "__main__":
    unittest.main()
