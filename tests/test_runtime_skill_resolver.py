from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from gravity_sdk import GravitySDK, RuntimeSkillResolver, __version__
from gravity_sdk.agent_runtime_contracts import canonical_digest
from gravity_sdk.core_skill_runtime import CoreSkillRuntime
from gravity_sdk.journey_contract import journey_artifact
from gravity_sdk.reference_journey import ReferenceJourneyRunner
from gravity_sdk.reference_journey_contract import JOURNEY_ID, SKILL_URI
from gravity_sdk.skill_contract import compile_skill_manifest, skill_uri
from gravity_sdk.skill_hub_contract import compile_hub_index
from gravity_sdk.skill_hub_locks import (
    build_skills_lock,
    build_trusted_packs_lock,
)
from gravity_sdk.skill_hub_state import build_trusted_installation_state
from gravity_sdk.skill_render import render_package_files, skill_package_descriptor
from tests.test_project_skill_overlay import project_overlay, project_semantic_source
from tests.test_reference_journey import (
    FakeSDK,
    StaticTrustService,
    journey_input,
    stable_trust,
)
from tests.test_skill_hub_clients import RaisingEntryPoint
from tests.test_skill_hub_contracts import (
    hub_index,
    skill_entry,
    source_snapshot,
    team_manifest,
    trusted_entry,
)
from tests.test_model_registry import MODEL_URI


def _team_manifest(*, models: list[str] | None = None) -> dict:
    value = team_manifest()
    value["covers_journeys"] = [JOURNEY_ID]
    value["model_dependencies"] = list(models or [])
    return value


def _artifact(manifest: dict) -> dict:
    contract = compile_skill_manifest(manifest)
    return {
        "contract": contract,
        "digest": canonical_digest(contract),
        "skill_uri": skill_uri(contract),
    }


def _synthetic_journey(manifest: dict) -> dict:
    result = journey_artifact(JOURNEY_ID)
    contract = result["contract"]
    compiled = compile_skill_manifest(manifest)
    contract["required_skill"] = skill_uri(compiled)
    contract["required_capabilities"] = copy.deepcopy(
        compiled["capability_dependencies"]
    )
    contract["required_semantics"] = copy.deepcopy(
        compiled["semantic_dependencies"]
    )
    contract["required_operators"] = copy.deepcopy(
        compiled["operator_dependencies"]
    )
    contract["required_models"] = copy.deepcopy(compiled["model_dependencies"])
    contract["required_context"] = copy.deepcopy(
        compiled["context_dependencies"]["required"]
    )
    contract["claim_policy"] = {
        "allowed": copy.deepcopy(compiled["claim_policy"]["allowed"]),
        "forbidden": copy.deepcopy(compiled["claim_policy"]["forbidden"]),
    }
    for field in (
        "known_requests_min",
        "known_requests_max",
        "unknown_discovery_max",
        "runtime_additional_requests",
    ):
        contract["request_budget"][field] = compiled["request_budget"][field]
    result["digest"] = canonical_digest(contract)
    return result


class RuntimeSkillResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _locks(
        self, manifest: dict, *, with_trusted_pack: bool = False
    ) -> tuple[dict, dict, dict | None]:
        packs = [trusted_entry(b"trusted wheel")] if with_trusted_pack else []
        index = compile_hub_index(
            hub_index(skills=[skill_entry(manifest)], packs=packs),
            runtime_version=__version__,
        )
        source = source_snapshot(index)
        artifact = _artifact(manifest)
        lock = build_skills_lock(
            index,
            source,
            [artifact["skill_uri"]],
            runtime_version=__version__,
        )
        trusted_lock = (
            build_trusted_packs_lock(
                index,
                source,
                [next(iter(index["trusted_packs"]))],
                runtime_version=__version__,
            )
            if with_trusted_pack
            else None
        )
        return artifact, lock, trusted_lock

    def _project(
        self,
        name: str,
        artifact: dict,
        *,
        lock: dict | None,
        cas: bool,
        trusted_lock: dict | None = None,
        trusted_state: dict | None = None,
    ) -> SimpleNamespace:
        root = self.root / name
        state = self.root / f"{name}-state"
        root.mkdir()
        (root / "docs").mkdir()
        (root / "docs" / "metric.md").write_text(
            "# Metric\nCanonical metric boundary.", encoding="utf-8"
        )
        (root / "docs" / "attribution.md").write_text(
            "# Attribution\nContext remains data.", encoding="utf-8"
        )
        contract_root = (
            root / "20_项目知识库" / "仓库与配置" / "gravity-agent-runtime"
        )
        contract_root.mkdir(parents=True)
        overlay = project_overlay()
        overlay["extends"]["skill_uri"] = artifact["skill_uri"]
        overlay["semantic_sources"] = [
            "20_项目知识库/仓库与配置/gravity-agent-runtime/r01-acquisition-spend.semantic.json"
        ]
        for requirement in overlay["context_requirements"]:
            requirement["skill_uri"] = artifact["skill_uri"]
        (contract_root / "r01-ap-cost-anomaly.json").write_text(
            json.dumps(overlay), encoding="utf-8"
        )
        (contract_root / "r01-acquisition-spend.semantic.json").write_text(
            json.dumps(project_semantic_source()), encoding="utf-8"
        )
        if lock is not None:
            (root / "gravity.skills.lock.json").write_text(
                json.dumps(lock, sort_keys=True) + "\n", encoding="utf-8"
            )
        if trusted_lock is not None:
            (root / "gravity.trusted-packs.lock.json").write_text(
                json.dumps(trusted_lock, sort_keys=True) + "\n", encoding="utf-8"
            )
        subprocess.run(
            ["git", "-C", str(root), "init", "-b", "test"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.name", "R09B Test"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "config", "user.email", "r09b@example.invalid"],
            check=True,
        )
        subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-m", "fixture"],
            check=True,
            capture_output=True,
        )
        if cas:
            target = (
                state
                / "skill-hub-cas"
                / "skills"
                / "sha256"
                / skill_package_descriptor(artifact)["package_digest"]
            )
            for relative, content in render_package_files(artifact).items():
                path = target.joinpath(*relative.split("/"))
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        if trusted_state is not None:
            state.mkdir(parents=True, exist_ok=True)
            (state / "trusted-packs-installation.json").write_text(
                json.dumps(trusted_state, sort_keys=True) + "\n", encoding="utf-8"
            )
        return SimpleNamespace(root=root, state_root=state)

    def test_builtin_resolution_never_reads_or_creates_project_hub_state(self) -> None:
        missing = self.root / "not-a-project"
        workspace = SimpleNamespace(root=missing, state_root=missing / "state")

        result = RuntimeSkillResolver(workspace=workspace).resolve(
            SKILL_URI,
            journey=journey_artifact(JOURNEY_ID),
        )

        self.assertTrue(result["ok"])
        binding = result["skill"]["runtime_binding"]
        self.assertEqual("unlocked", binding["resolution"])
        self.assertTrue(
            all(value is None for key, value in binding.items() if key != "resolution")
        )
        self.assertFalse((missing / "state").exists())
        self.assertFalse(result["network_called"])

    def test_two_clean_projects_execute_one_locked_digest_through_existing_owner(self) -> None:
        manifest = _team_manifest()
        artifact, lock, _trusted = self._locks(manifest)
        workspaces = [
            self._project(name, artifact, lock=lock, cas=True)
            for name in ("project-a", "project-b")
        ]
        synthetic = _synthetic_journey(manifest)
        results = []

        with (
            patch(
                "gravity_sdk.core_skill_runtime.journey_artifact",
                return_value=synthetic,
            ),
            patch(
                "gravity_sdk.skill_hub_client.SkillHubClient.sync",
                side_effect=AssertionError("Runtime attempted Hub sync"),
            ),
            patch(
                "gravity_sdk.skill_hub_client.SkillHubClient.fetch",
                side_effect=AssertionError("Runtime attempted Hub fetch"),
            ),
            patch(
                "gravity_sdk.skill_hub_client.SkillHubClient.install",
                side_effect=AssertionError("Runtime attempted Hub install"),
            ),
        ):
            for workspace in workspaces:
                resolver = RuntimeSkillResolver(workspace=workspace)
                self.assertFalse(
                    resolver.resolve(
                        artifact["skill_uri"], journey=synthetic
                    )["network_called"]
                )
                core = CoreSkillRuntime(
                    workspace=workspace,
                    capability_trust=StaticTrustService(stable_trust()),
                    skill_resolver=resolver,
                )
                sdk = FakeSDK(workspace)
                result = ReferenceJourneyRunner(sdk, core_runtime=core).run(
                    journey_input()
                )
                self.assertEqual("success", result["status"])
                self.assertEqual(1, len(sdk.calls))
                results.append(result)

            facade = GravitySDK(
                workspace=workspaces[0],
                insight_factory=lambda: self.fail("Skill resolution created Insight"),
                sql_factory=lambda: self.fail("Skill resolution created SQL"),
            )
            default_readiness = facade.skill_runtime.resolve(
                JOURNEY_ID,
                {
                    "app_alias": "merge2-legacy",
                    "windows": {
                        "current": {"start": "2026-07-04", "end": "2026-07-10"},
                        "reference": {"start": "2026-06-27", "end": "2026-07-03"},
                    },
                },
            )
            self.assertEqual("locked", default_readiness["skill"]["resolution"])

        first, second = (result["execution_snapshot"]["skill"] for result in results)
        self.assertEqual(first, second)
        self.assertEqual("locked", first["resolution"])
        self.assertEqual(lock["lock_digest"], first["team_lock_digest"])
        self.assertEqual(lock["source"], first["hub_source_reference"])
        self.assertRegex(first["hub_source_digest"], r"^[0-9a-f]{64}$")

    def test_lock_and_cas_fail_closed_without_fallback_or_creation(self) -> None:
        manifest = _team_manifest()
        artifact, lock, _trusted = self._locks(manifest)
        journey = _synthetic_journey(manifest)

        missing = self._project("missing", artifact, lock=lock, cas=False)
        missing_result = RuntimeSkillResolver(workspace=missing).resolve(
            artifact["skill_uri"], journey=journey
        )
        self.assertEqual(["HUB_CAS_MISSING"], missing_result["reason_codes"])
        self.assertFalse((missing.state_root / "skill-hub-cas").exists())

        absent_lock = self._project("absent-lock", artifact, lock=None, cas=False)
        absent_result = RuntimeSkillResolver(workspace=absent_lock).resolve(
            artifact["skill_uri"], journey=journey
        )
        self.assertEqual(["HUB_SKILL_MISSING"], absent_result["reason_codes"])
        self.assertTrue(
            RuntimeSkillResolver(workspace=absent_lock).resolve(
                SKILL_URI, journey=journey_artifact(JOURNEY_ID)
            )["ok"]
        )

        dirty = self._project("dirty", artifact, lock=lock, cas=True)
        (dirty.root / "gravity.skills.lock.json").write_text(
            json.dumps(lock, indent=2) + "\n", encoding="utf-8"
        )
        dirty_result = RuntimeSkillResolver(workspace=dirty).resolve(
            artifact["skill_uri"], journey=journey
        )
        self.assertEqual(
            ["HUB_SOURCE_SNAPSHOT_CHANGED"], dirty_result["reason_codes"]
        )

        wrong_runtime = copy.deepcopy(lock)
        wrong_runtime["runtime_version"] = "9.9.9"
        wrong_runtime["lock_digest"] = canonical_digest(
            {key: value for key, value in wrong_runtime.items() if key != "lock_digest"}
        )
        incompatible = self._project(
            "incompatible", artifact, lock=wrong_runtime, cas=True
        )
        incompatible_result = RuntimeSkillResolver(workspace=incompatible).resolve(
            artifact["skill_uri"], journey=journey
        )
        self.assertEqual(
            ["HUB_RUNTIME_INCOMPATIBLE"], incompatible_result["reason_codes"]
        )

        tampered = self._project("tampered", artifact, lock=lock, cas=True)
        guide = next(
            (tampered.state_root / "skill-hub-cas").rglob("GUIDE.md")
        )
        guide.write_text("tampered", encoding="utf-8")
        tampered_result = RuntimeSkillResolver(workspace=tampered).resolve(
            artifact["skill_uri"], journey=journey
        )
        self.assertEqual(["HUB_CAS_TAMPERED"], tampered_result["reason_codes"])

        drifted_lock = copy.deepcopy(lock)
        drifted_lock["skills"][0]["dependencies"]["semantics"] = [
            "metric://project/other@1"
        ]
        drifted_lock["lock_digest"] = canonical_digest(
            {key: value for key, value in drifted_lock.items() if key != "lock_digest"}
        )
        drifted = self._project(
            "dependency-drift", artifact, lock=drifted_lock, cas=True
        )
        drifted_result = RuntimeSkillResolver(workspace=drifted).resolve(
            artifact["skill_uri"], journey=journey
        )
        self.assertEqual(
            ["HUB_SKILL_DIGEST_MISMATCH"], drifted_result["reason_codes"]
        )

    def test_skill_journey_parity_rejects_a_self_consistent_team_drift(self) -> None:
        manifest = _team_manifest()
        manifest["output_schema"] = "gravity.other-result.v1"
        artifact, lock, _trusted = self._locks(manifest)
        workspace = self._project("parity", artifact, lock=lock, cas=True)

        result = RuntimeSkillResolver(workspace=workspace).resolve(
            artifact["skill_uri"],
            journey=_synthetic_journey(_team_manifest()),
        )

        self.assertEqual(["SKILL_DEPENDENCY_UNRESOLVED"], result["reason_codes"])
        self.assertEqual("locked", result["skill"]["runtime_binding"]["resolution"])

    def test_trusted_pack_binding_is_exact_and_never_loads_entry_points(self) -> None:
        manifest = _team_manifest(models=[MODEL_URI])
        artifact, lock, trusted_lock = self._locks(
            manifest, with_trusted_pack=True
        )
        self.assertIsNotNone(trusted_lock)
        item = trusted_lock["packs"][0]
        state = build_trusted_installation_state(
            trusted_lock["lock_digest"],
            [
                {
                    "pack_id": item["pack_id"],
                    "descriptor_digest": item["descriptor_digest"],
                    "distribution": item["distribution"],
                    "version": item["version"],
                    "wheel_sha256": item["wheel_sha256"],
                    "installed_at": "2026-08-22T12:00:00Z",
                    "local_path": "C:/external-installer/site-packages/example.dist-info",
                    "health": "healthy",
                }
            ],
        )
        workspace = self._project(
            "trusted",
            artifact,
            lock=lock,
            cas=True,
            trusted_lock=trusted_lock,
            trusted_state=state,
        )
        distribution = SimpleNamespace(
            version=item["version"],
            metadata={
                "Name": item["distribution"],
                "Gravity-Trusted-Pack-ID": item["pack_id"],
            },
            entry_points=[
                RaisingEntryPoint("gravity.models"),
                RaisingEntryPoint("gravity.operators"),
            ],
        )

        with patch(
            "importlib.metadata.entry_points",
            side_effect=AssertionError("global environment scan attempted"),
        ):
            result = RuntimeSkillResolver(
                workspace=workspace,
                distribution_lookup=lambda name: distribution,
            ).resolve(
                artifact["skill_uri"],
                journey=_synthetic_journey(manifest),
            )

        self.assertTrue(result["ok"])
        binding = result["skill"]["runtime_binding"]
        self.assertEqual(trusted_lock["lock_digest"], binding["trusted_pack_lock_digest"])
        self.assertEqual(state["state_digest"], binding["trusted_pack_state_digest"])
        self.assertRegex(binding["trusted_pack_verification_digest"], r"^[0-9a-f]{64}$")
        self.assertNotIn("local_path", repr(binding))
        self.assertNotIn("installed_at", repr(binding))

    def test_trusted_pack_missing_state_coverage_and_group_drift_are_scoped(self) -> None:
        manifest = _team_manifest(models=[MODEL_URI])
        artifact, lock, trusted_lock = self._locks(
            manifest, with_trusted_pack=True
        )
        item = trusted_lock["packs"][0]
        healthy = build_trusted_installation_state(
            trusted_lock["lock_digest"],
            [
                {
                    "pack_id": item["pack_id"],
                    "descriptor_digest": item["descriptor_digest"],
                    "distribution": item["distribution"],
                    "version": item["version"],
                    "wheel_sha256": item["wheel_sha256"],
                    "installed_at": "2026-08-22T12:00:00Z",
                    "local_path": "C:/external-installer/example.dist-info",
                    "health": "healthy",
                }
            ],
        )
        distribution = SimpleNamespace(
            version=item["version"],
            metadata={
                "Name": item["distribution"],
                "Gravity-Trusted-Pack-ID": item["pack_id"],
            },
            entry_points=[RaisingEntryPoint("gravity.models")],
        )

        missing = self._project(
            "trusted-missing",
            artifact,
            lock=lock,
            cas=True,
            trusted_lock=None,
        )
        missing_result = RuntimeSkillResolver(workspace=missing).resolve(
            artifact["skill_uri"], journey=_synthetic_journey(manifest)
        )
        self.assertEqual(
            ["HUB_TRUSTED_PACK_MISSING"], missing_result["reason_codes"]
        )

        no_state = self._project(
            "trusted-no-state",
            artifact,
            lock=lock,
            cas=True,
            trusted_lock=trusted_lock,
        )
        no_state_result = RuntimeSkillResolver(workspace=no_state).resolve(
            artifact["skill_uri"], journey=_synthetic_journey(manifest)
        )
        self.assertEqual(
            ["TRUSTED_PACK_STATE_INVALID"], no_state_result["reason_codes"]
        )

        tampered_state = copy.deepcopy(healthy)
        tampered_state["state_digest"] = "0" * 64
        tampered = self._project(
            "trusted-tampered-state",
            artifact,
            lock=lock,
            cas=True,
            trusted_lock=trusted_lock,
            trusted_state=tampered_state,
        )
        tampered_result = RuntimeSkillResolver(workspace=tampered).resolve(
            artifact["skill_uri"], journey=_synthetic_journey(manifest)
        )
        self.assertEqual(
            ["TRUSTED_PACK_STATE_DIGEST_MISMATCH"],
            tampered_result["reason_codes"],
        )

        uncovered_lock = copy.deepcopy(trusted_lock)
        uncovered_lock["packs"][0]["models"] = []
        uncovered_lock["packs"][0]["allowed_groups"] = ["gravity.operators"]
        uncovered_lock["lock_digest"] = canonical_digest(
            {key: value for key, value in uncovered_lock.items() if key != "lock_digest"}
        )
        uncovered_state = copy.deepcopy(healthy)
        uncovered_state["lock_digest"] = uncovered_lock["lock_digest"]
        uncovered_state["state_digest"] = canonical_digest(
            {key: value for key, value in uncovered_state.items() if key != "state_digest"}
        )
        uncovered = self._project(
            "trusted-uncovered",
            artifact,
            lock=lock,
            cas=True,
            trusted_lock=uncovered_lock,
            trusted_state=uncovered_state,
        )
        uncovered_result = RuntimeSkillResolver(workspace=uncovered).resolve(
            artifact["skill_uri"], journey=_synthetic_journey(manifest)
        )
        self.assertEqual(
            ["HUB_TRUSTED_PACK_MISSING"], uncovered_result["reason_codes"]
        )

        wrong_group = self._project(
            "trusted-group",
            artifact,
            lock=lock,
            cas=True,
            trusted_lock=trusted_lock,
            trusted_state=healthy,
        )
        group_result = RuntimeSkillResolver(
            workspace=wrong_group,
            distribution_lookup=lambda name: distribution,
        ).resolve(artifact["skill_uri"], journey=_synthetic_journey(manifest))
        self.assertEqual(
            ["TRUSTED_PACK_GROUP_INVALID"], group_result["reason_codes"]
        )
        self.assertTrue(
            RuntimeSkillResolver(workspace=wrong_group).resolve(
                SKILL_URI, journey=journey_artifact(JOURNEY_ID)
            )["ok"]
        )


if __name__ == "__main__":
    unittest.main()
