from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from gravity_sdk.errors import InputValidationError
from gravity_sdk.skill_contract import (
    SkillContractError,
    load_skill_manifest,
    normalize_skill_identity,
    skill_artifact,
    skill_artifacts,
)


SKILL_URI = "skill://gravity.game/ap-cost-anomaly-localization@1.0.0"


class SkillContractTests(unittest.TestCase):
    def test_reference_manifest_has_orthogonal_state_and_typed_dependencies(self):
        artifacts = skill_artifacts()
        artifact = artifacts[0]
        contract = artifact["contract"]

        self.assertEqual(1, len(artifacts))
        self.assertEqual(SKILL_URI, artifact["skill_uri"])
        self.assertEqual("specified", contract["specification"])
        self.assertEqual("reviewed", contract["lifecycle"])
        self.assertEqual("blocked", contract["readiness"])
        self.assertEqual("validated", contract["validation"])
        self.assertEqual("product", contract["capability_dependencies"][0]["identity_kind"])
        self.assertEqual(
            ["analysis.merge2.ap-cost-anomaly-localization"],
            contract["covers_journeys"],
        )
        self.assertRegex(artifact["digest"], r"^[0-9a-f]{64}$")

    def test_identity_accepts_uri_or_exact_compact_form_and_rejects_guessing(self):
        compact = "gravity.game/ap-cost-anomaly-localization@1.0.0"

        self.assertEqual(SKILL_URI, normalize_skill_identity(SKILL_URI))
        self.assertEqual(SKILL_URI, normalize_skill_identity(compact))
        self.assertEqual(SKILL_URI, skill_artifact(compact)["skill_uri"])
        with self.assertRaises(InputValidationError):
            normalize_skill_identity("ap cost anomaly")

    def test_manifest_schema_and_cross_dependency_drift_fail_closed(self):
        contract = skill_artifact(SKILL_URI)["contract"]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "skill.json"
            malformed = copy.deepcopy(contract)
            malformed["unexpected"] = True
            path.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaises(SkillContractError):
                load_skill_manifest(path)

            malformed = copy.deepcopy(contract)
            malformed["request_budget"]["known_requests_min"] = 5
            malformed["request_budget"]["known_requests_max"] = 4
            path.write_text(json.dumps(malformed), encoding="utf-8")
            with self.assertRaises(SkillContractError):
                load_skill_manifest(path)

    def test_artifacts_are_defensive_copies(self):
        artifact = skill_artifact(SKILL_URI)
        artifact["contract"]["skill_id"] = "poison"

        self.assertEqual(
            "ap-cost-anomaly-localization",
            skill_artifact(SKILL_URI)["contract"]["skill_id"],
        )


if __name__ == "__main__":
    unittest.main()
