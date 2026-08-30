from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gravity_insight import cli
from gravity_insight.capability_trust_cli import dispatch


class Service:
    def trust(self, identity_kind, selector):
        return {"kind": identity_kind, "selector": selector}

    def validate(self, value):
        return {"validated": value}

    def impact(self, value):
        return {"impact": value}


class SDK:
    capability_trust = Service()

    @classmethod
    def from_env(cls, **_options):
        return cls()


class CapabilityTrustCliTests(unittest.TestCase):
    def test_all_capability_commands_are_offline_first(self):
        parser = cli.build_parser()
        for argv in (
            ["capabilities", "trust", "operation", "app.list"],
            ["capabilities", "validate", "--input", "{}"],
            ["capabilities", "impact", "--input", "{}"],
        ):
            with self.subTest(argv=argv):
                self.assertFalse(parser.parse_args(argv).network_required)

    @patch("gravity_insight.workspace.load_workspace", return_value=object())
    @patch("gravity_insight.sdk.GravitySDK", SDK)
    def test_dispatch_only_delegates_to_the_service(self, _workspace):
        trusted = dispatch(
            SimpleNamespace(
                capabilities_command="trust",
                identity_kind="operation",
                selector="app.list",
                workspace=None,
            ),
            lambda _value: self.fail("trust has no input"),
        )
        validated = dispatch(
            SimpleNamespace(
                capabilities_command="validate", input="{}", workspace=None
            ),
            lambda _value: {"value": "validation"},
        )
        impact = dispatch(
            SimpleNamespace(
                capabilities_command="impact", input="{}", workspace=None
            ),
            lambda _value: {"value": "change"},
        )

        self.assertEqual("app.list", trusted["selector"])
        self.assertEqual({"value": "validation"}, validated["validated"])
        self.assertEqual({"value": "change"}, impact["impact"])


if __name__ == "__main__":
    unittest.main()
