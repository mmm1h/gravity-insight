from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gravity_sdk import GravitySDK
from gravity_sdk import cli
from gravity_sdk.journey_cli import dispatch
from gravity_sdk.reference_journey_contract import JOURNEY_ID


class Service:
    def list(self):
        return {"schema_version": "gravity.journey-list.v1"}

    def verify(self):
        return {"schema_version": "gravity.journey-registry-verification.v1"}

    def describe(self, journey_id):
        return {"schema_version": "gravity.journey-description.v1", "journey_id": journey_id}

    def can_run(self, journey_id, inputs):
        return {"schema_version": "gravity.journey-can-run.v1", "journey_id": journey_id, "inputs": inputs}

    def impact(self, inputs):
        return {"schema_version": "gravity.capability-impact.v1", "inputs": inputs}

    def run(self, journey_id, inputs):
        return {"schema_version": "gravity.analysis-result.v1", "journey_id": journey_id, "inputs": inputs}


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
            "gravity.journey-description.v1",
            first.describe(JOURNEY_ID)["schema_version"],
        )

    def test_cli_parser_marks_all_journey_commands_local_first(self):
        parser = cli.build_parser()
        cases = (
            ["journey", "list"],
            ["journey", "verify"],
            ["journey", "describe", JOURNEY_ID],
            ["journey", "can-run", JOURNEY_ID, "--input", "{}"],
            ["journey", "impact", "--input", '{"schema_version":"gravity.capability-impact-request.v1","changes":[]}'],
            ["journey", "run", JOURNEY_ID, "--input", "{}"],
        )
        for argv in cases:
            with self.subTest(argv=argv):
                self.assertFalse(parser.parse_args(argv).network_required)

    @patch("gravity_sdk.workspace.load_workspace", return_value=object())
    @patch("gravity_sdk.sdk.GravitySDK", SDK)
    def test_cli_dispatch_delegates_without_owning_execution(self, _workspace):
        listed = dispatch(
            SimpleNamespace(journey_command="list", workspace=None),
            lambda _value: self.fail("list has no input"),
        )
        verified = dispatch(
            SimpleNamespace(journey_command="verify", workspace=None),
            lambda _value: self.fail("verify has no input"),
        )
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
        impact = dispatch(
            SimpleNamespace(
                journey_command="impact",
                workspace=None,
                input="{}",
            ),
            lambda _value: {"request": "value"},
        )

        self.assertEqual("gravity.journey-list.v1", listed["schema_version"])
        self.assertEqual(
            "gravity.journey-registry-verification.v1",
            verified["schema_version"],
        )
        self.assertEqual("gravity.journey-description.v1", describe["schema_version"])
        self.assertEqual("gravity.journey-can-run.v1", can_run["schema_version"])
        self.assertEqual("gravity.analysis-result.v1", run["schema_version"])
        self.assertEqual("gravity.capability-impact.v1", impact["schema_version"])


if __name__ == "__main__":
    unittest.main()
