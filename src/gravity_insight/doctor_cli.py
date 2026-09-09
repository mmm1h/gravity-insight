"""Doctor command orchestration kept out of the shared CLI spine."""

from __future__ import annotations

from typing import Any, Mapping
import copy
import os
from pathlib import Path
from types import SimpleNamespace

from . import runtime
from .domains import DOMAIN_OPERATIONS
from .errors import ErrorCategory, ErrorDetail
from .install_doctor import inspect_install_consistency
from . import __version__
from .runtime_skill_resolver import RuntimeSkillResolver
from .skill_host_install import inspect_host_skills
from .skill_hub_archive import validate_skill_directory
from .skill_hub_cli import _project_lock_status
from .skill_hub_contract import SkillHubContractError
from .skill_hub_locks import compile_skills_lock
from .skill_hub_paths import assert_unlinked_path
from .skill_hub_state import read_json
from .skill_maintenance import maintenance_status
from .skill_maintenance_state import load_skill_maintenance_generation
from .skill_seed import read_bundled_skill_seed, validate_bundled_skill_seed
from .workspace import load_workspace


def run_doctor(args: Any) -> dict[str, Any]:
    installation = _public_installation(inspect_install_consistency())
    if installation["status"] != "pass":
        return {**_install_failure(installation), "skill_diagnosis": diagnose_skills()}

    local = runtime.validate_manifest_json()
    client = runtime.build_client()
    operation_ids = runtime.operation_ids(client.operations())
    result: dict[str, Any] = {
        "status": "pass",
        "live": False,
        "network_called": False,
        "installation": installation,
        **local,
        "registered_operations": len(operation_ids),
        "auth": runtime.credential_status(),
        "skill_diagnosis": diagnose_skills(),
    }
    if not args.live:
        return result
    if callable(getattr(client, "probe_all", None)):
        probes = client.probe_all(max_workers=args.concurrency)
        coverage = probes.get("coverage", {}) if isinstance(probes, Mapping) else {}
        probe_status = (
            str(probes.get("status", "error"))
            if isinstance(probes, Mapping)
            else "error"
        )
        result.update(
            {
                "status": (
                    "pass" if probe_status in {"success", "empty"} else "partial"
                ),
                "live": True,
                "network_called": True,
                "probe_status": probe_status,
                "probes_run": (
                    probes.get("probed", 0) if isinstance(probes, Mapping) else 0
                ),
                "coverage": coverage,
            }
        )
        return result
    operation_id = runtime.resolve_operation_id(
        client, DOMAIN_OPERATIONS["apps.list"]
    )
    schema = runtime.to_jsonable(client.schema(operation_id))
    live_probe = schema.get("live_probe", {}) if isinstance(schema, Mapping) else {}
    if not isinstance(live_probe, Mapping):
        raise ValueError(f"{operation_id} has an invalid live probe contract")
    probe_inputs = live_probe.get("inputs", live_probe.get("input", {}))
    if not isinstance(probe_inputs, Mapping):
        raise ValueError(f"{operation_id} live probe inputs must be an object")
    runtime.call_read(client, operation_id, dict(probe_inputs), read_all=False)
    result.update(
        {
            "live": True,
            "network_called": True,
            "probe_operation_id": operation_id,
            "probe_succeeded": True,
        }
    )
    return result


def _install_failure(installation: Mapping[str, Any]) -> dict[str, Any]:
    reason_code = str(installation["reason_code"])
    detail = ErrorDetail.create(
        reason_code,
        str(installation["message"]),
        category=ErrorCategory.LOCAL,
        retryable=False,
        next_action=str(installation["next_action"]),
    )
    return {
        "schema_version": "gravity-insight.doctor.v2",
        "ok": False,
        "status": "error",
        "live": False,
        "network_called": False,
        "reason_code": reason_code,
        "installation": dict(installation),
        "error": detail.to_dict(),
    }


def _public_installation(installation: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(dict(installation))
    paths = {}
    records = [*result.get("metadata", []), result.get("source"), result.get("import")]
    for record in records:
        if not isinstance(record, dict):
            continue
        for key in ("path", "metadata_path", "project_root"):
            if record.get(key):
                paths[str(record[key])] = f"<{key}>"
                record[key] = f"<{key}>"
    if "reinstall_commands" in result:
        commands = result["reinstall_commands"]
        for path, label in sorted(paths.items(), key=lambda item: -len(item[0])):
            commands = [command.replace(path, label) for command in commands]
        result["reinstall_commands"] = commands
    return result


def diagnose_skills(
    *, state_root: Path | None = None, cas_root: Path | None = None,
    project_root: Path | None = None, lock_path: Path | None = None,
    home: Path | None = None, environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    state_root, project_root, cas_root = _diagnostic_roots(state_root, project_root, cas_root)
    client = SimpleNamespace(state_root=state_root, runtime_version=__version__)
    env = os.environ if environ is None else environ
    auto = str(env.get("GRAVITY_INSIGHT_AUTO_SKILLS", "")).strip().casefold() not in {
        "0", "false", "no", "off",
    }
    library, seed = _library(client, cas_root, auto)
    project, lock = _project(client, project_root, lock_path, cas_root)
    entries = seed["agent_index"]["skills"] if seed else []
    selection = "bundled_inventory_not_project_selection"
    unavailable = 0
    if lock is not None:
        entries = [entry for entry in entries if entry["skill_uri"] in lock["requested"]]
        unavailable = len(set(lock["requested"]) - {entry["skill_uri"] for entry in entries})
        selection = "project_requested_uris_compared_to_bundled_seed"
    return _diagnosis_report(library, project, seed, entries, selection, unavailable, project_root, home or Path.home())


def _diagnostic_roots(state_root: Path | None, project_root: Path | None, cas_root: Path | None) -> tuple[Path, Path, Path]:
    if state_root is None or project_root is None:
        workspace = load_workspace()
        state_root = state_root if state_root is not None else workspace.state_root
        project_root = project_root if project_root is not None else (
            workspace.root if workspace.configured else Path.cwd()
        )
    state_root, project_root = Path(state_root).expanduser(), Path(project_root).expanduser()
    cas_root = Path(cas_root).expanduser() if cas_root is not None else state_root / "skill-hub-cas"
    return state_root, project_root, cas_root


def _diagnosis_report(library: dict, project: dict, seed: Any, entries: list, selection: str, unavailable: int, project_root: Path, home: Path) -> dict[str, Any]:
    return {
        "schema_version": "gravity.skill-trigger-diagnosis.v1",
        "network_called": False, "writes_performed": False,
        "runtime_library": library, "project_lock": project,
        "native_files": {
            "comparison_basis": selection,
            "status": "checked" if seed else "not_checked",
            "unavailable_requested_count": unavailable,
            "next_action": "Use the exact matching seed for requested versions absent from the bundled comparison; do not substitute current versions." if unavailable else None,
            "hosts": inspect_host_skills(entries, project_root=project_root, home=home, packages=seed["agent_packages"] if seed else None),
        },
        "host_discovery": {
            "status": "unknown", "enablement": "unknown",
            "reason_code": "HOST_DISCOVERY_EVIDENCE_UNAVAILABLE",
            "next_action": "Check the host's enabled Skill list in a fresh session; if disabled, explicitly enable it. No host config or session content was read.",
        },
        "invocation": {
            "status": "not_measured", "valid_result": "not_measured",
            "reason_code": "HOST_INVOCATION_EVIDENCE_UNAVAILABLE",
            "next_action": "Observe an authorized host invocation and its governed result; discovery alone is not execution or business success.",
        },
        "routing": {
            "status": "not_measured", "arm": None, "selector": None,
            "terminal_state": None,
            "next_action": "Use the same invocation's routing_mode, selected selector and terminal result; no selection or event was supplied to this read-only diagnostic.",
        },
    }


def _library(client: Any, cas_root: Path, auto: bool) -> tuple[dict[str, Any], Any]:
    result = {
        "status": "unavailable", "runtime_version": __version__,
        "auto_bootstrap": "enabled" if auto else "disabled",
        "maintenance_status": "unknown", "seed_status": "unknown",
        "managed_runtime_version": None,
        "seed_digest": None, "active_seed_digest": None,
        "cas_status": "not_checked", "reason_codes": [], "next_action": None,
    }
    seed = None
    try:
        seed = validate_bundled_skill_seed(read_bundled_skill_seed())
        result.update(seed_status="verified", seed_digest=seed["seed_digest"])
    except (OSError, SkillHubContractError) as exc:
        result["seed_status"] = "unavailable"
        result["reason_codes"].append(exc.reason_code if isinstance(exc, SkillHubContractError) else "HUB_SEED_UNAVAILABLE")
    try:
        assert_unlinked_path(client.state_root, reason="HUB_STATE_INVALID", label="State root")
        receipt = maintenance_status(client)
        result.update(maintenance_status=receipt["status"], active_seed_digest=receipt["active_seed_digest"])
        if receipt["status"] in {"ready", "degraded"}:
            generation = load_skill_maintenance_generation(client.state_root, receipt["active_seed_digest"])
            result["managed_runtime_version"] = generation["managed_lock"]["runtime_version"]
            if generation["managed_lock"]["runtime_version"] != __version__:
                result["reason_codes"].append("HUB_RUNTIME_INCOMPATIBLE")
            if seed and seed["seed_digest"] != receipt["active_seed_digest"]:
                result["reason_codes"].append("HOST_SKILL_SEED_NOT_ACTIVE")
            _verify_managed_cas(generation["managed_lock"], cas_root)
            result["cas_status"] = "verified"
            if not result["reason_codes"] and receipt["status"] == "ready":
                result["status"] = "ready"
        else:
            result["status"] = receipt["status"]
    except (OSError, SkillHubContractError) as exc:
        result["reason_codes"].append(exc.reason_code if isinstance(exc, SkillHubContractError) else "HUB_STATE_INVALID")
        result["cas_status"] = "unavailable"
    if result["status"] != "ready":
        result["next_action"] = "Run gravity skills repair explicitly to validate the current seed and CAS; this does not install host files."
    if seed is None:
        result["next_action"] = "Build and install a wheel containing the sealed Skill seed, then retry. An editable checkout or generated build directory alone is not a bundled seed installation; bootstrap cannot recover a missing wheel seed."
    if not auto:
        result["bootstrap_next_action"] = "GRAVITY_INSIGHT_AUTO_SKILLS is disabled; explicitly run gravity skills bootstrap, or enable automatic Runtime maintenance. Host installation is separate."
    return result, seed


def _verify_managed_cas(lock: Mapping[str, Any], cas_root: Path) -> None:
    for entry in lock["skills"]:
        path = cas_root / "skills" / "sha256" / entry["package_digest"]
        assert_unlinked_path(path, reason="HUB_CAS_TAMPERED", label="Skill CAS")
        validate_skill_directory(path, expected_digest=entry["package_digest"])


def _project(client: Any, root: Path, supplied: Path | None, cas_root: Path) -> tuple[dict[str, Any], Any]:
    path = Path(supplied).expanduser() if supplied is not None else root / "gravity.skills.lock.json"
    result = {
        "path": "<project-lock>", "exists": None, "parse_status": "not_checked",
        "runtime_match": "not_checked", "resolution": "not_checked",
        "reason_codes": [], "next_action": None,
    }
    lock = None
    try:
        try:
            path.lstat()
            result["exists"] = True
        except FileNotFoundError:
            result["exists"] = False
        observation = _project_lock_status(client, path)
        result["exists"] = observation["reason"] != "no_lock"
        if not result["exists"]:
            result.update(reason_codes=["PROJECT_LOCK_MISSING"], next_action="Create and track gravity.skills.lock.json with explicitly selected exact Skill URIs using gravity skills lock.")
            return result, None
        lock = compile_skills_lock(read_json(path))
        result.update(parse_status="valid", runtime_match=observation["status"])
        if observation["status"] != "match":
            result.update(resolution="blocked", reason_codes=["HUB_RUNTIME_INCOMPATIBLE"], next_action="Preserve the old lock; use its matching Runtime or explicitly generate and review a new lock. Do not auto-upgrade project bindings.")
            return result, lock
        if path.absolute() != (root / "gravity.skills.lock.json").absolute():
            result.update(resolution="blocked", reason_codes=["PROJECT_LOCK_WRONG_LOCATION"], next_action="Place the reviewed lock at the project root as gravity.skills.lock.json and track it in Git; Runtime does not resolve arbitrary lock filenames.")
            return result, lock
        resolver = RuntimeSkillResolver(workspace=SimpleNamespace(root=root, state_root=client.state_root), cas_root=cas_root)
        reasons = set()
        for identity in lock["requested"]:
            reasons.update(resolver.resolve(identity)["reason_codes"])
        result.update(resolution="blocked" if reasons else "resolved", reason_codes=sorted(reasons))
        if reasons:
            result["next_action"] = "Check the tracked, clean project lock and its exact CAS/dependency artifacts with gravity skills verify --lock gravity.skills.lock.json; resolve the reported dependency gaps before invoking."
            if "HUB_SOURCE_UNAVAILABLE" in reasons or "HUB_SOURCE_SNAPSHOT_CHANGED" in reasons:
                result["next_action"] = "Use the calling project's Git root; review and commit the exact project lock and required bindings, then retry from a clean snapshot."
            elif "HUB_CAS_MISSING" in reasons:
                result["next_action"] = "Fetch the exact project lock from its explicitly approved source with gravity skills fetch --lock gravity.skills.lock.json --source <approved-source.json> --state-root <state-root>, then verify and retry."
    except (OSError, SkillHubContractError):
        result.update(parse_status="invalid_or_unreadable", resolution="blocked", reason_codes=["SKILLS_LOCK_INVALID"], next_action="Restore a valid digest-checked, regular unlinked project lock and verify access; preserve the original for comparison.")
    return result, lock


__all__ = ["run_doctor", "diagnose_skills"]
