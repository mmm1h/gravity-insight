from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from gravity_insight.errors import InputValidationError
from gravity_insight.skill_contract import (
    SkillContractError,
    load_skill_manifest,
    normalize_skill_identity,
    validate_skill_journey_parity,
)
from tests.locked_skill_fixture import canonical_skill_manifest, skill_artifact


SKILL_URI = "skill://gravity.game/ap-cost-anomaly-localization@1.0.0"


class SkillContractTests(unittest.TestCase):
    def test_reference_manifest_has_orthogonal_state_and_typed_dependencies(self):
        artifact = skill_artifact()
        contract = artifact["contract"]

        self.assertEqual(SKILL_URI, artifact["skill_uri"])
        self.assertEqual("specified", contract["specification"])
        self.assertEqual("reviewed", contract["lifecycle"])
        self.assertEqual("executable", contract["readiness"])
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
        with self.assertRaises(InputValidationError):
            normalize_skill_identity("ap cost anomaly")

    def test_manifest_schema_and_cross_dependency_drift_fail_closed(self):
        contract = canonical_skill_manifest()
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
        artifact = skill_artifact()
        artifact["contract"]["skill_id"] = "poison"

        self.assertEqual(
            "ap-cost-anomaly-localization",
            canonical_skill_manifest()["skill_id"],
        )

    def test_public_journey_parity_fails_with_the_skill_contract_error(self):
        with self.assertRaises(SkillContractError):
            validate_skill_journey_parity(
                canonical_skill_manifest(),
                {"journey_id": "analysis.malformed"},
            )


if __name__ == "__main__":
    unittest.main()
