from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gravity_insight import __version__
from gravity_insight.agent_runtime_contracts import canonical_digest
from gravity_insight.skill_contract import compile_skill_manifest, skill_uri
from gravity_insight.skill_hub_contract import compile_hub_index
from gravity_insight.skill_hub_locks import build_skills_lock
from gravity_insight.skill_render import render_package_files, skill_package_descriptor
from tests.test_skill_hub_contracts import hub_index, skill_entry, source_snapshot


ROOT = Path(__file__).resolve().parents[1]
AP_COST_SKILL_ID = "ap-cost-anomaly-localization"


def canonical_skill_manifest(skill_id: str = AP_COST_SKILL_ID) -> dict[str, Any]:
    path = ROOT / "skills" / "library" / f"{skill_id}.json"
    return compile_skill_manifest(
        json.loads(path.read_text(encoding="utf-8")), label=path.name
    )


def skill_artifact(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    contract = compile_skill_manifest(manifest or canonical_skill_manifest())
    return {
        "contract": contract,
        "digest": canonical_digest(contract),
        "skill_uri": skill_uri(contract),
    }


def locked_skill(
    manifest: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    artifact = skill_artifact(manifest)
    index = compile_hub_index(
        hub_index(skills=[skill_entry(artifact["contract"])], packs=[]),
        runtime_version=__version__,
    )
    source = source_snapshot(index)
    lock = build_skills_lock(
        index,
        source,
        [artifact["skill_uri"]],
        runtime_version=__version__,
    )
    return artifact, lock


def write_skill_lock(root: Path, lock: dict[str, Any]) -> None:
    (root / "gravity.skills.lock.json").write_text(
        json.dumps(lock, sort_keys=True) + "\n", encoding="utf-8"
    )


def bind_locked_skill(
    artifact: dict[str, Any], lock: dict[str, Any]
) -> dict[str, Any]:
    selected = {**artifact, "package_digest": skill_package_descriptor(artifact)["package_digest"]}
    source = lock["source"]
    selected["runtime_binding"] = {
        "resolution": "locked",
        "team_lock_digest": lock["lock_digest"],
        "hub_source_digest": canonical_digest(source),
        "hub_source_reference": source,
        "trusted_pack_lock_digest": None,
        "trusted_pack_state_digest": None,
        "trusted_pack_verification_digest": None,
    }
    return selected


def materialize_skill_cas(state_root: Path, artifact: dict[str, Any]) -> Path:
    target = (
        state_root
        / "skill-hub-cas"
        / "skills"
        / "sha256"
        / skill_package_descriptor(artifact)["package_digest"]
    )
    for relative, content in render_package_files(artifact).items():
        path = target.joinpath(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return target


__all__ = [
    "AP_COST_SKILL_ID",
    "canonical_skill_manifest",
    "bind_locked_skill",
    "locked_skill",
    "materialize_skill_cas",
    "skill_artifact",
    "write_skill_lock",
]
