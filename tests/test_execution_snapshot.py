from __future__ import annotations

import copy
import unittest

from gravity_sdk.agent_runtime_contracts import canonical_digest
from gravity_sdk.execution_snapshot import (
    ExecutionSnapshotError,
    build_execution_snapshot,
    compile_execution_snapshot,
)


DIGEST = "a" * 64


def snapshot(**changes):
    value = build_execution_snapshot(
        status="resolved",
        journey={"journey_id": "analysis.example", "version": 1, "digest": DIGEST},
        skill={
            "uri": "skill://gravity.game/example@1.0.0",
            "version": "1.0.0",
            "manifest_digest": "b" * 64,
            "package_digest": "c" * 64,
            "resolution": "unlocked",
            "team_lock_digest": None,
            "hub_source_digest": None,
            "hub_source_reference": None,
            "trusted_pack_lock_digest": None,
            "trusted_pack_state_digest": None,
            "trusted_pack_verification_digest": None,
            "lifecycle": "reviewed",
            "readiness": "executable",
            "validation": "validated",
        },
        project_overlay={
            "uri": "skill://project.demo/example@1.0.0",
            "version": "1.0.0",
            "digest": "d" * 64,
            "source_revision": "e" * 40,
        },
        capabilities=[
            {
                "identity_kind": "product",
                "selector": "example@1",
                "contract_version": "1",
                "contract_digest": "e" * 64,
                "trust_digest": "f" * 64,
                "status": "stable",
            }
        ],
        semantics=[
            {
                "uri": "metric://project/example@1",
                "version": 1,
                "definition_digest": "1" * 64,
                "binding_digest": "2" * 64,
                "source_digest": "3" * 64,
                "registry_digest": "4" * 64,
                "status": "resolved",
            }
        ],
        operators=[
            {
                "uri": "operator://gravity/example@1",
                "version": 1,
                "digest": "5" * 64,
                "assumptions_digest": "6" * 64,
                "status": "available",
            }
        ],
        models=[],
        context_packs=[],
        contracts={
            "input_schema_version": "gravity.example-input.v1",
            "analysis_result_schema_version": "gravity.analysis-result.v1",
            "execution_mode": "plan",
            "execution_owner": "example@1",
        },
    )
    if not changes:
        return value
    unsigned = {key: copy.deepcopy(item) for key, item in value.items() if key != "snapshot_digest"}
    unsigned.update(changes)
    return build_execution_snapshot(
        status=unsigned["status"],
        journey=unsigned["journey"],
        skill=unsigned["skill"],
        project_overlay=unsigned["project_overlay"],
        capabilities=unsigned["capabilities"],
        semantics=unsigned["semantics"],
        operators=unsigned["operators"],
        models=unsigned["models"],
        context_packs=unsigned["context_packs"],
        contracts=unsigned["contracts"],
        runtime_version=unsigned["runtime"]["version"],
    )


class ExecutionSnapshotTests(unittest.TestCase):
    def test_snapshot_is_self_digested_ordered_and_value_free(self):
        value = snapshot()

        self.assertEqual("gravity.execution-snapshot.v1", value["schema_version"])
        self.assertRegex(value["snapshot_digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(value, compile_execution_snapshot(value))
        rendered = repr(value)
        for forbidden in ("question", "current_window", "hypothesis", "content"):
            self.assertNotIn(forbidden, rendered)

    def test_tamper_unknown_fields_and_value_keys_fail_closed(self):
        tampered = snapshot()
        tampered["journey"]["digest"] = "0" * 64
        with self.assertRaisesRegex(ExecutionSnapshotError, "digest changed"):
            compile_execution_snapshot(tampered)

        unknown = snapshot()
        unknown["guess"] = True
        with self.assertRaises(ExecutionSnapshotError):
            compile_execution_snapshot(unknown)

        with self.assertRaises(ExecutionSnapshotError):
            snapshot(contracts={
                "input_schema_version": "gravity.example-input.v1",
                "analysis_result_schema_version": "gravity.analysis-result.v1",
                "execution_mode": "plan",
                "execution_owner": "example@1",
                "question": "secret",
            })

    def test_builder_returns_defensive_copies(self):
        value = snapshot()
        compiled = compile_execution_snapshot(value)
        compiled["journey"]["journey_id"] = "changed"

        self.assertEqual("analysis.example", value["journey"]["journey_id"])

    def test_skill_binding_requires_exact_locked_or_empty_unlocked_state(self):
        source = {
            "source_id": "hub-source://org/example@1",
            "transport": "git",
            "source_descriptor_digest": "7" * 64,
            "source_revision": "8" * 40,
            "index_digest": "9" * 64,
        }
        locked = copy.deepcopy(snapshot()["skill"])
        locked.update(
            {
                "resolution": "locked",
                "team_lock_digest": "0" * 64,
                "hub_source_digest": canonical_digest(source),
                "hub_source_reference": source,
            }
        )
        self.assertEqual("locked", snapshot(skill=locked)["skill"]["resolution"])

        polluted = copy.deepcopy(snapshot()["skill"])
        polluted["team_lock_digest"] = "0" * 64
        with self.assertRaisesRegex(ExecutionSnapshotError, "Team binding"):
            snapshot(skill=polluted)

        drifted = copy.deepcopy(locked)
        drifted["hub_source_digest"] = "f" * 64
        with self.assertRaisesRegex(ExecutionSnapshotError, "source binding"):
            snapshot(skill=drifted)


if __name__ == "__main__":
    unittest.main()
