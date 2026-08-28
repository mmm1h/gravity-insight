from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from gravity_sdk.agent_runtime_contracts import canonical_digest
from gravity_sdk.runtime_compatibility import runtime_satisfies, runtime_within
from gravity_sdk.skill_contract import compile_skill_manifest, skill_uri
from gravity_sdk.skill_hub_contract import (
    SkillHubContractError,
    compile_hub_index,
    compile_hub_source,
)
from gravity_sdk.skill_hub_locks import (
    build_skills_lock,
    build_trusted_pack_install_plan,
    build_trusted_packs_lock,
    compile_skills_lock,
    compile_trusted_pack_install_plan,
    compile_trusted_packs_lock,
)
from gravity_sdk.skill_render import skill_package_descriptor
from gravity_sdk.trusted_pack_contract import compile_trusted_pack_descriptor
from tests.test_operator_model_contracts import trusted_pack


ROOT = Path(__file__).resolve().parents[1]


def team_manifest(
    *, namespace: str = "org.example", skill_id: str = "team-analysis", version: str = "1.0.0"
) -> dict:
    path = (
        ROOT
        / "src"
        / "gravity_sdk"
        / "contracts"
        / "skills"
        / "gravity.game.ap-cost-anomaly-localization.v1.json"
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    value.update(
        {
            "namespace": namespace,
            "skill_id": skill_id,
            "version": version,
            "covers_journeys": [f"analysis.{namespace}.{skill_id}"],
        }
    )
    value["provenance"] = {
        "source_kind": "independent",
        "source_ref": "hub-source://org/example@1",
        "source_revision": "1" * 40,
        "authorship": "independently_authored",
        "license_review": "approved_internal",
    }
    return value


def skill_entry(manifest: dict | None = None, archive: bytes = b"skill archive") -> dict:
    contract = compile_skill_manifest(manifest or team_manifest())
    identity = skill_uri(contract)
    artifact = {
        "contract": contract,
        "digest": canonical_digest(contract),
        "skill_uri": identity,
    }
    return {
        "skill_uri": identity,
        "manifest": contract,
        "package": skill_package_descriptor(artifact),
        "archive": {
            "path": f"artifacts/skills/{contract['skill_id']}-{contract['version']}.zip",
            "sha256": hashlib.sha256(archive).hexdigest(),
            "size_bytes": len(archive),
            "media_type": "application/vnd.gravity.skill-package.v1+zip",
        },
    }


def trusted_entry(wheel: bytes = b"trusted wheel") -> dict:
    descriptor = trusted_pack(wheel_sha256=hashlib.sha256(wheel).hexdigest())
    compiled = compile_trusted_pack_descriptor(descriptor)
    return {
        "pack_id": descriptor["pack_id"],
        "descriptor": descriptor,
        "descriptor_digest": compiled["digest"],
        "archive": {
            "path": "artifacts/trusted/gravity_team_forecast_methods-1.2.3-py3-none-any.whl",
            "sha256": descriptor["wheel_sha256"],
            "size_bytes": len(wheel),
            "media_type": "application/vnd.python.wheel",
        },
    }


def hub_index(*, skills=None, packs=None) -> dict:
    return {
        "artifact_kind": "skill_hub_index",
        "schema_version": "gravity.skill-hub-index.v1",
        "index_version": 1,
        "skills": [skill_entry()] if skills is None else skills,
        "trusted_packs": [trusted_entry()] if packs is None else packs,
    }


def source_snapshot(index: dict, *, transport: str = "git") -> dict:
    source = git_source()
    if transport == "static_https":
        source.update(
            {
                "transport": "static_https",
                "git": None,
                "https": {
                    "index_url": "https://skills.example.invalid/v1/index.json",
                    "artifact_base_url": "https://skills.example.invalid/v1/artifacts/",
                    "source_revision": "review-1",
                },
            }
        )
    return {
        "source_id": "hub-source://org/example@1",
        "transport": transport,
        "source_descriptor_digest": compile_hub_source(source)["digest"],
        "source_revision": "3" * 40,
        "index_digest": index["digest"],
    }


def git_source() -> dict:
    return {
        "artifact_kind": "skill_hub_source",
        "schema_version": "gravity.skill-hub-source.v1",
        "source_id": "hub-source://org/example@1",
        "transport": "git",
        "owner": "data-platform",
        "trust_model": "stage_a_team_controlled_reviewed",
        "git": {
            "repository_uri": "https://github.com/example/team-skills.git",
            "ref": "refs/heads/main",
            "index_path": "hub/index.json",
        },
        "https": None,
        "limits": {
            "max_index_bytes": 1048576,
            "max_artifact_bytes": 4194304,
            "timeout_seconds": 10,
        },
    }


def _render_without_wheel_paths(plan: dict) -> str:
    """Render an install plan for forbidden-token scanning, minus wheel paths.

    ``wheel_path`` names which artifact to install; it is data, not an
    instruction. It also carries a random temporary directory supplied by the
    test, so scanning it for short tokens such as ``pip`` or ``command``
    produces failures that depend on ``tempfile`` naming rather than on the
    plan itself. Drop only those values and scan everything else verbatim.
    """
    rendered = repr(plan)
    for action in plan.get("actions", ()):
        wheel_path = action.get("wheel_path")
        if isinstance(wheel_path, str):
            rendered = rendered.replace(repr(wheel_path), "'<wheel-path>'")
    return rendered


class SkillHubContractTests(unittest.TestCase):
    def test_source_contract_separates_git_and_exact_static_https(self) -> None:
        git = compile_hub_source(git_source())
        https = git_source()
        https.update(
            {
                "transport": "static_https",
                "git": None,
                "https": {
                    "index_url": "https://skills.example.invalid/v1/index.json",
                    "artifact_base_url": "https://skills.example.invalid/v1/artifacts/",
                    "source_revision": "review-2026-08-22",
                },
            }
        )
        static = compile_hub_source(https)

        self.assertRegex(git["digest"], r"^[0-9a-f]{64}$")
        self.assertNotEqual(git["digest"], static["digest"])
        for mutate in (
            lambda value: value["git"].update(
                {"repository_uri": "https://token@example.invalid/team.git"}
            ),
            lambda value: value.update({"https": https["https"]}),
            lambda value: value["git"].update({"index_path": "../index.json"}),
        ):
            value = git_source()
            mutate(value)
            with self.assertRaises(SkillHubContractError):
                compile_hub_source(value)

    def test_index_recompiles_skill_package_and_trusted_descriptor(self) -> None:
        first = compile_hub_index(hub_index(), runtime_version="0.3.0")
        reordered = hub_index(
            skills=[
                skill_entry(team_manifest(skill_id="zeta")),
                skill_entry(team_manifest(skill_id="alpha")),
            ],
            packs=[],
        )
        compiled = compile_hub_index(reordered, runtime_version="0.3.0")

        self.assertRegex(first["digest"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            sorted(compiled["skills"]),
            [item["skill_uri"] for item in compiled["contract"]["skills"]],
        )

        tampered = hub_index()
        tampered["skills"][0]["package"]["package_digest"] = "0" * 64
        with self.assertRaisesRegex(SkillHubContractError, "HUB_SKILL_DIGEST_MISMATCH"):
            compile_hub_index(tampered)

        tampered = hub_index()
        tampered["trusted_packs"][0]["descriptor_digest"] = "0" * 64
        with self.assertRaisesRegex(
            SkillHubContractError, "HUB_TRUSTED_PACK_DIGEST_MISMATCH"
        ):
            compile_hub_index(tampered)

    def test_exact_skill_lock_is_deterministic_and_has_no_local_state(self) -> None:
        compiled = compile_hub_index(hub_index(packs=[]), runtime_version="0.3.0")
        identity = next(iter(compiled["skills"]))
        first = build_skills_lock(
            compiled, source_snapshot(compiled), [identity], runtime_version="0.3.0"
        )
        second = build_skills_lock(
            compiled, source_snapshot(compiled), [identity], runtime_version="0.3.0"
        )

        self.assertEqual(first, second)
        self.assertEqual([identity], first["requested"])
        rendered = repr(first)
        for forbidden in (
            "installed_at",
            "local_path",
            "cache_path",
            "downloaded_at",
            "health",
        ):
            self.assertNotIn(forbidden, rendered)

        tampered = copy.deepcopy(first)
        tampered["skills"][0]["package_digest"] = "0" * 64
        with self.assertRaisesRegex(
            SkillHubContractError, "SKILLS_LOCK_DIGEST_MISMATCH"
        ):
            compile_skills_lock(tampered)

        local = copy.deepcopy(first)
        local["skills"][0]["dependencies"]["local_path"] = "C:/cache"
        local["lock_digest"] = canonical_digest(
            {key: value for key, value in local.items() if key != "lock_digest"}
        )
        with self.assertRaisesRegex(SkillHubContractError, "HUB_LOCK_LOCAL_STATE"):
            compile_skills_lock(local)

        unordered = copy.deepcopy(first)
        unordered["skills"][0]["dependencies"]["semantics"] = [
            "semantic://z/example@1",
            "semantic://a/example@1",
        ]
        unordered["lock_digest"] = canonical_digest(
            {key: value for key, value in unordered.items() if key != "lock_digest"}
        )
        with self.assertRaisesRegex(SkillHubContractError, "HUB_LOCK_INVALID"):
            compile_skills_lock(unordered)

        malformed = copy.deepcopy(first)
        malformed["skills"][0]["dependencies"]["capabilities"] = [
            {"selector": "product@1"}
        ]
        malformed["lock_digest"] = canonical_digest(
            {key: value for key, value in malformed.items() if key != "lock_digest"}
        )
        with self.assertRaisesRegex(SkillHubContractError, "SKILLS_LOCK_INVALID"):
            compile_skills_lock(malformed)

    def test_lock_requires_exact_ids_and_rejects_builtin_override(self) -> None:
        compiled = compile_hub_index(hub_index(packs=[]))
        with self.assertRaisesRegex(SkillHubContractError, "HUB_SKILL_MISSING"):
            build_skills_lock(
                compiled,
                source_snapshot(compiled),
                ["skill://org.example/missing@1.0.0"],
            )

        path = (
            ROOT
            / "src"
            / "gravity_sdk"
            / "contracts"
            / "skills"
            / "gravity.game.ap-cost-anomaly-localization.v1.json"
        )
        builtin = json.loads(path.read_text(encoding="utf-8"))
        collision = compile_hub_index(
            hub_index(skills=[skill_entry(builtin)], packs=[])
        )
        with self.assertRaisesRegex(SkillHubContractError, "HUB_BUILTIN_COLLISION"):
            build_skills_lock(
                collision,
                source_snapshot(collision),
                [next(iter(collision["skills"]))],
            )

    def test_trusted_lock_and_installer_plan_are_separate_and_non_executable(self) -> None:
        wheel = b"trusted wheel"
        compiled = compile_hub_index(
            hub_index(skills=[], packs=[trusted_entry(wheel)]),
            runtime_version="0.3.0",
        )
        identity = next(iter(compiled["trusted_packs"]))
        lock = build_trusted_packs_lock(
            compiled, source_snapshot(compiled), [identity], runtime_version="0.3.0"
        )
        self.assertEqual("trusted_packs_lock", lock["artifact_kind"])
        self.assertNotIn("skills", lock)
        self.assertEqual(lock, compile_trusted_packs_lock(lock))

        reversed_range = copy.deepcopy(lock)
        compatibility = reversed_range["packs"][0]["runtime_compatibility"]
        compatibility["minimum"], compatibility["maximum"] = (
            compatibility["maximum"],
            compatibility["minimum"],
        )
        reversed_range["lock_digest"] = canonical_digest(
            {
                key: value
                for key, value in reversed_range.items()
                if key != "lock_digest"
            }
        )
        with self.assertRaisesRegex(
            SkillHubContractError, "TRUSTED_PACK_LOCK_INVALID"
        ):
            compile_trusted_packs_lock(reversed_range)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "trusted.whl"
            path.write_bytes(wheel)
            plan = build_trusted_pack_install_plan(lock, {identity: path})

            linked = Path(directory) / "trusted-hardlink.whl"
            os.link(path, linked)
            with self.assertRaisesRegex(
                SkillHubContractError, "TRUSTED_PACK_WHEEL_TAMPERED"
            ):
                build_trusted_pack_install_plan(lock, {identity: path})
        self.assertEqual(plan, compile_trusted_pack_install_plan(plan))
        self.assertEqual("external_installer", plan["installation_owner"])
        self.assertEqual("install_exact_wheel", plan["actions"][0]["effect"])
        rendered = _render_without_wheel_paths(plan)
        for forbidden in ("pip", "command", "entry_point", "http://", "https://"):
            self.assertNotIn(forbidden, rendered)

    def test_runtime_compatibility_is_exact_and_fail_closed(self) -> None:
        self.assertTrue(runtime_satisfies("0.3.0", ">=0.3,<0.4"))
        self.assertFalse(runtime_satisfies("0.4.0", ">=0.3,<0.4"))
        self.assertTrue(runtime_within("0.3.0", "0.3.0", "0.9.0"))
        with self.assertRaises(ValueError):
            runtime_satisfies("0.3.0", "latest")

        incompatible = team_manifest()
        incompatible["runtime_requires"] = ">=9.0,<10.0"
        with self.assertRaisesRegex(SkillHubContractError, "HUB_RUNTIME_INCOMPATIBLE"):
            compile_hub_index(
                hub_index(skills=[skill_entry(incompatible)], packs=[]),
                runtime_version="0.3.0",
            )


if __name__ == "__main__":
    unittest.main()
