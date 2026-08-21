from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gravity_sdk import GravitySDK
from gravity_sdk import cli
from gravity_sdk.journey_cli import dispatch
from gravity_sdk.reference_journey_contract import JOURNEY_ID


class Service:
    def describe(self):
        return {"schema_version": "gravity.journey-description.v1"}

    def can_run(self, inputs):
        return {"schema_version": "gravity.journey-can-run.v1", "inputs": inputs}

    def run(self, inputs):
        return {"schema_version": "gravity.analysis-result.v1", "inputs": inputs}


class SDK:
    def __init__(self, **_options):
        self.journeys = Service()

    @classmethod
    def from_env(cls, **options):
        return cls(**options)


class ReferenceJourneySurfaceTests(unittest.TestCase):
    def test_sdk_service_is_lazy_cached_and_does_not_construct_clients(self):
        sdk = GravitySDK(
            insight_factory=lambda: self.fail("Journey describe must stay local"),
            sql_factory=lambda: self.fail("Journey describe must stay local"),
        )
        first = sdk.journeys
        second = sdk.journeys

        self.assertIs(first, second)
        self.assertEqual(
            "gravity.journey-description.v1", first.describe()["schema_version"]
        )

    def test_cli_parser_marks_all_r01_commands_local_first(self):
        parser = cli.build_parser()
        cases = (
            ["journey", "describe", JOURNEY_ID],
            ["journey", "can-run", JOURNEY_ID, "--input", "{}"],
            ["journey", "run", JOURNEY_ID, "--input", "{}"],
        )
        for argv in cases:
            with self.subTest(argv=argv):
                self.assertFalse(parser.parse_args(argv).network_required)

    @patch("gravity_sdk.workspace.load_workspace", return_value=object())
    @patch("gravity_sdk.sdk.GravitySDK", SDK)
    def test_cli_dispatch_delegates_without_owning_execution(self, _workspace):
        describe = dispatch(
            SimpleNamespace(
                journey_id=JOURNEY_ID,
                journey_command="describe",
                workspace=None,
            ),
            lambda _value: self.fail("describe has no input"),
        )
        can_run = dispatch(
            SimpleNamespace(
                journey_id=JOURNEY_ID,
                journey_command="can-run",
                workspace=None,
                input="{}",
            ),
            lambda _value: {"request": "value"},
        )
        run = dispatch(
            SimpleNamespace(
                journey_id=JOURNEY_ID,
                journey_command="run",
                workspace=None,
                input="{}",
            ),
            lambda _value: {"request": "value"},
        )

        self.assertEqual("gravity.journey-description.v1", describe["schema_version"])
        self.assertEqual("gravity.journey-can-run.v1", can_run["schema_version"])
        self.assertEqual("gravity.analysis-result.v1", run["schema_version"])

    def test_unknown_journey_id_fails_before_sdk_construction(self):
        with self.assertRaisesRegex(Exception, "journey_id"):
            dispatch(
                SimpleNamespace(
                    journey_id="analysis.unknown",
                    journey_command="describe",
                    workspace=None,
                ),
                lambda _value: {},
            )


if __name__ == "__main__":
    unittest.main()
