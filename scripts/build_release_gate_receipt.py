from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from scripts.check_installed_wheel_consumer import DEFAULT_REVISION
    from scripts.check_release_ci import SCHEMA_VERSION as CI_SCHEMA
    from scripts.check_release_main import SCHEMA_VERSION as MAIN_SCHEMA
    from scripts.run_integrated_validation import gate_specs
    from scripts.release_step_coverage import require_release_coverage
    from scripts.supply_chain_common import SupplyChainError, select_distributions
except ModuleNotFoundError:
    from check_installed_wheel_consumer import DEFAULT_REVISION
    from check_release_ci import SCHEMA_VERSION as CI_SCHEMA
    from check_release_main import SCHEMA_VERSION as MAIN_SCHEMA
    from run_integrated_validation import gate_specs
    from release_step_coverage import require_release_coverage
    from supply_chain_common import SupplyChainError, select_distributions


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "gravity.release-gate-receipt.v1"
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_TAG_RE = re.compile(r"v(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))")
_SURFACES = {"cli", "sdk", "plan", "agent", "mcp"}


class ReleaseGateError(ValueError):
    """One or more pre-publish facts are missing, stale, or invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseGateError(message)


def _load(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseGateError(f"cannot read {label} JSON at {path}") from exc
    if not isinstance(value, Mapping):
        raise ReleaseGateError(f"{label} JSON must be an object")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source(path: Path) -> dict[str, str]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(ROOT).as_posix()
    except ValueError:
        display = resolved.as_posix()
    return {"path": display, "sha256": _sha256(resolved)}


def _expect(actual: Any, expected: Any, label: str, remedy: str) -> None:
    _require(
        type(actual) is type(expected) and actual == expected,
        f"{label}: expected {expected!r}; observed {actual!r}; next: {remedy}",
    )


def _fields(document: Mapping[str, Any], expected: Mapping[str, Any],
            label: str, remedy: str) -> None:
    for key, value in expected.items():
        _expect(document.get(key), value, f"{label}.{key}", remedy)


def _typed(value: Any, kind: type, label: str, remedy: str) -> None:
    _require(isinstance(value, kind),
             f"{label}: expected {kind.__name__}; observed {value!r}; next: {remedy}")


def _positive(value: Any, label: str, remedy: str) -> None:
    _require(type(value) is int and value > 0,
             f"{label}: expected positive integer (not bool); observed {value!r}; next: {remedy}")


def _choice(value: Any, choices: Sequence[str], label: str, remedy: str) -> None:
    _require(value in choices,
             f"{label}: expected one of {tuple(choices)!r}; observed {value!r}; next: {remedy}")


def _validate_main(document: Mapping[str, Any], expected_sha: str, tag: str) -> None:
    _fields(document, {
        "schema_version": MAIN_SCHEMA, "status": "passed", "event_name": "push",
        "release_tag": tag, "commit_sha": expected_sha, "protected_branch": "main",
        "branch_protected": True, "checked_out_head": expected_sha,
        "tag_commit": expected_sha, "main_commit": expected_sha,
        "branch_api_commit": expected_sha,
    }, "main", "rerun check_release_main.py against the exact tag and protected main")


def _validate_ci(document: Mapping[str, Any], expected_sha: str) -> None:
    remedy = "select a successful exact-SHA push/main CI run and rerun check_release_ci.py"
    _fields(document, {
        "schema_version": CI_SCHEMA, "status": "passed", "commit_sha": expected_sha,
        "event_name": "push", "branch": "main", "workflow_path": ".github/workflows/ci.yml",
        "conclusion": "success",
    }, "CI", remedy)
    _positive(document.get("run_id"), "CI.run_id", remedy)
    required = document.get("required_job")
    _typed(required, Mapping, "CI.required_job", remedy)
    _fields(required, {"name": "ci-required", "conclusion": "success"}, "CI.required_job", remedy)


def _validate_iv(document: Mapping[str, Any], expected_sha: str) -> list[str]:
    remedy = "rerun complete Integrated Validation on clean exact-SHA main in this worktree's independent venv"
    _fields(document, {
        "schema_version": "gravity.integrated-validation-receipt.v2",
        "commit_sha": expected_sha, "branch": "main", "trial": False,
        "complete_gate_set": True, "integrated_validation_green": True, "overall": "passed",
    }, "IV", remedy)
    for phase in ("preconditions_before", "preconditions_after"):
        preconditions = document.get(phase)
        _typed(preconditions, Mapping, f"IV.{phase}", remedy)
        _fields(preconditions, {"head": expected_sha, "branch_is_main": True,
                               "clean": True, "independent_venv": True}, f"IV.{phase}", remedy)
    gates = document.get("gates")
    _typed(gates, list, "IV.gates", remedy)
    expected_names = [gate.name for gate in gate_specs(Path(sys.executable), ROOT / "tmp/release-gate-inventory")]
    observed: dict[str, Mapping[str, Any]] = {}
    for gate in gates:
        _typed(gate, Mapping, "IV.gate", remedy)
        name = gate.get("name")
        _typed(name, str, "IV.gate.name", remedy)
        _require(name not in observed,
                 f"IV.gate.name: expected unique name; observed duplicate {name!r}; next: {remedy}")
        observed[name] = gate
    _expect(sorted(observed), sorted(expected_names), "IV.gate_inventory", remedy)
    for name in expected_names:
        _fields(observed[name], {"status": "pass", "passed": True, "exit_code": 0}, f"IV.gates.{name}", remedy)
    _expect(document.get("skipped_gates"), [], "IV.skipped_gates", remedy)
    return expected_names


def _validate_secret(document: Mapping[str, Any], expected_sha: str) -> None:
    _expect(document.get("status"), "passed", "secret.status",
            "resolve scanner failures and rerun scan_repository_secrets.py --history")
    _expect(document.get("history_included"), True, "secret.history_included",
            "fetch complete Git history and rerun scan_repository_secrets.py --history")
    _expect(document.get("repository_head"), expected_sha, "secret.repository_head",
            "check out the intended release SHA and regenerate its secret-history receipt")
    _positive(document.get("history_commit_count"), "secret.history_commit_count",
              "fetch complete Git history and rerun the history scan; do not use a shallow/range receipt")
    _positive(document.get("scanned_tracked_file_count"), "secret.scanned_tracked_file_count",
              "verify the checkout has tracked files and rerun the scanner from that repository root")
    _expect(document.get("unreviewed_findings"), [], "secret.unreviewed_findings",
            "review each finding, remove or rotate confirmed secrets, then rerun the history scan")


def _sbom_binding(document: Mapping[str, Any]) -> tuple[str, str, str]:
    remedy = "regenerate both SBOMs with generate_release_sbom.py for the intended distributions"
    _fields(document, {"bomFormat": "CycloneDX", "specVersion": "1.6"}, "SBOM", remedy)
    metadata = document.get("metadata")
    _typed(metadata, Mapping, "SBOM.metadata", remedy)
    component = metadata.get("component")
    _typed(component, Mapping, "SBOM.component", remedy)
    properties = component.get("properties")
    _typed(properties, list, "SBOM.properties", remedy)
    bound = {item.get("name"): item.get("value") for item in properties
             if isinstance(item, Mapping) and isinstance(item.get("name"), str)
             and item["name"].startswith("gravity:distribution:")}
    filename = bound.get("gravity:distribution:filename")
    kind = bound.get("gravity:distribution:kind")
    digest = bound.get("gravity:distribution:sha256")
    _typed(filename, str, "SBOM.filename", remedy)
    _choice(kind, ("wheel", "sdist"), "SBOM.kind", remedy)
    _typed(digest, str, "SBOM.sha256", remedy)
    _require(re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
             f"SBOM.sha256: expected 64 lowercase hex digits; observed {digest!r}; next: {remedy}")
    hashes = component.get("hashes")
    _typed(hashes, list, "SBOM.hashes", remedy)
    observed_hashes = [item.get("content") for item in hashes
                       if isinstance(item, Mapping) and item.get("alg") == "SHA-256"]
    _expect(observed_hashes, [digest], "SBOM.root_sha256", remedy)
    return kind, filename, digest


def _validate_sboms(sbom_dir: Path, *, wheel: Path, sdist: Path) -> dict[str, dict[str, str]]:
    remedy = "regenerate exactly one SBOM per intended distribution"
    paths = sorted(sbom_dir.glob("*.cdx.json"))
    _expect(len(paths), 2, "SBOM.document_count", remedy)
    expected = {"wheel": (wheel.name, _sha256(wheel)), "sdist": (sdist.name, _sha256(sdist))}
    observed: dict[str, dict[str, str]] = {}
    for path in paths:
        kind, filename, digest = _sbom_binding(_load(path, f"{path.name} SBOM"))
        _require(kind not in observed,
                 f"SBOM.kind: expected unique kind; observed duplicate {kind!r}; next: {remedy}")
        _expect(filename, expected[kind][0], f"SBOM.{kind}.filename", remedy)
        _expect(digest, expected[kind][1], f"SBOM.{kind}.sha256", remedy)
        observed[kind] = {"filename": filename, "artifact_sha256": digest, **_source(path)}
    _expect(sorted(observed), ["sdist", "wheel"], "SBOM.kinds", remedy)
    return observed


def _validate_dependency(document: Mapping[str, Any], *, wheel: Path) -> None:
    remedy = "resolve audit findings/errors and rerun audit_release_dependencies.py for the intended wheel"
    _fields(document, {"status": "passed", "artifact": wheel.name,
                       "artifact_sha256": _sha256(wheel), "vulnerability_count": 0,
                       "findings": [], "service": "OSV"}, "dependency", remedy)
    _positive(document.get("dependency_count"), "dependency.dependency_count", remedy)


def _validate_surface(document: Mapping[str, Any], *, wheel: Path) -> None:
    remedy = "rerun check_installed_wheel_surface_matrix.py for the intended wheel and all five surfaces"
    _fields(document, {"schema_version": "gravity.installed-wheel-surface-matrix.v1",
                       "passed": True, "wheel": wheel.name, "wheel_sha256": _sha256(wheel),
                       "surface_count": len(_SURFACES), "network_calls": 0}, "surface", remedy)
    cases = document.get("cases")
    _typed(cases, list, "surface.cases", remedy)
    _positive(len(cases), "surface.cases.length", remedy)
    _expect(document.get("case_count"), len(cases), "surface.case_count", remedy)
    for index, case in enumerate(cases):
        _typed(case, Mapping, f"surface.cases[{index}]", remedy)
        surfaces = case.get("surfaces")
        _typed(surfaces, Mapping, f"surface.cases[{index}].surfaces", remedy)
        _expect(sorted(surfaces), sorted(_SURFACES), f"surface.cases[{index}].inventory", remedy)
        _fields(surfaces, {name: "passed" for name in sorted(_SURFACES)}, f"surface.cases[{index}]", remedy)


def _validate_consumer(document: Mapping[str, Any], *, wheel: Path) -> None:
    remedy = "rerun check_installed_wheel_consumer.py --strict-prerequisites for the intended wheel and pinned consumer"
    _fields(document, {"schema_version": "gravity.installed-wheel-consumer-gate.v1",
                       "status": "pass", "passed": True, "exit_code": 0,
                       "strict_prerequisites": True, "revision": DEFAULT_REVISION}, "consumer", remedy)
    check = document.get("check")
    _typed(check, Mapping, "consumer.check", remedy)
    _fields(check, {"schema_version": "gravity.installed-wheel-consumer-check.v2",
                   "passed": True, "consumer_commit": DEFAULT_REVISION,
                   "wheel": wheel.name, "wheel_sha256": _sha256(wheel), "network_calls": 0}, "consumer.check", remedy)
    summary = check.get("summary")
    _typed(summary, Mapping, "consumer.summary", remedy)
    _expect(summary.get("ok"), True, "consumer.summary.ok", remedy)
    _positive(summary.get("tests_run"), "consumer.summary.tests_run", remedy)


def _validate_changelog(document: Mapping[str, Any], *, release_version: str, expected_sha: str) -> dict[str, Any]:
    remedy = "correct the release declaration/migration and rerun check_changelog.py for the intended version and SHA"
    _fields(document, {"schema_version": "gravity.release-changelog.v1", "status": "passed",
                       "release_version": release_version, "project_version": release_version,
                       "repository_head": expected_sha}, "changelog", remedy)
    _choice(document.get("section_state"), ("unreleased_target", "released"), "changelog.section_state", remedy)
    _choice(document.get("breaking_change_declaration"), ("declared", "none_declared"), "changelog.breaking_change_declaration", remedy)
    migration = document.get("migration")
    _typed(migration, Mapping, "migration", remedy)
    _choice(migration.get("status"), ("required_and_present", "not_required"), "migration.status", remedy)
    if document.get("breaking_change_declaration") == "declared":
        _positive(document.get("breaking_entries"), "changelog.breaking_entries", remedy)
        _expect(migration.get("status"), "required_and_present", "migration.status", remedy)
        path = migration.get("path")
        _typed(path, str, "migration.path", remedy)
        _require((ROOT / path).is_file(),
                 f"migration.path: expected existing guide; observed {path!r}; next: {remedy}")
        _expect(migration.get("sha256"), _sha256(ROOT / path), "migration.sha256", remedy)
    else:
        _expect(document.get("breaking_entries"), 0, "changelog.breaking_entries", remedy)
        _expect(migration.get("status"), "not_required", "migration.status", remedy)
    _expect(document.get("changelog_sha256"), _sha256(ROOT / "CHANGELOG.md"), "changelog.changelog_sha256", remedy)
    _expect(document.get("released_section_lock_sha256"), _sha256(ROOT / "scripts/changelog_release_lock.json"), "changelog.released_section_lock_sha256", remedy)
    return dict(migration)


def build_release_gate_receipt(
    *,
    expected_sha: str,
    release_tag: str,
    dist_dir: Path,
    sbom_dir: Path,
    main_receipt: Path,
    ci_receipt: Path,
    integrated_validation_receipt: Path,
    secret_scan_receipt: Path,
    dependency_audit_receipt: Path,
    surface_receipt: Path,
    consumer_receipt: Path,
    changelog_receipt: Path,
    coverage_receipt: Path,
    run_id: str,
    run_attempt: str,
) -> dict[str, Any]:
    _require(_SHA_RE.fullmatch(expected_sha) is not None, "expected SHA must be a full commit SHA")
    tag_match = _TAG_RE.fullmatch(release_tag)
    _require(tag_match is not None, "release tag must be vMAJOR.MINOR.PATCH")
    release_version = tag_match.group("version")
    try:
        coverage = require_release_coverage(
            _load(coverage_receipt, "release coverage"), sha=expected_sha,
            run_id=run_id, run_attempt=run_attempt,
        )
    except ValueError as exc:
        raise ReleaseGateError(str(exc)) from exc
    wheel, sdist = select_distributions(dist_dir.resolve())

    main = _load(main_receipt, "protected-main")
    ci = _load(ci_receipt, "release CI")
    iv = _load(integrated_validation_receipt, "Integrated Validation")
    secret = _load(secret_scan_receipt, "secret-history")
    dependency = _load(dependency_audit_receipt, "dependency audit")
    surface = _load(surface_receipt, "installed-wheel surface")
    consumer = _load(consumer_receipt, "canonical consumer")
    changelog = _load(changelog_receipt, "changelog")

    _validate_main(main, expected_sha, release_tag)
    _validate_ci(ci, expected_sha)
    iv_gates = _validate_iv(iv, expected_sha)
    _validate_secret(secret, expected_sha)
    sboms = _validate_sboms(sbom_dir.resolve(), wheel=wheel, sdist=sdist)
    _validate_dependency(dependency, wheel=wheel)
    _validate_surface(surface, wheel=wheel)
    _validate_consumer(consumer, wheel=wheel)
    migration = _validate_changelog(
        changelog, release_version=release_version, expected_sha=expected_sha
    )

    sources = {
        "step_coverage": _source(coverage_receipt),
        "protected_main": _source(main_receipt),
        "ci": _source(ci_receipt),
        "integrated_validation": _source(integrated_validation_receipt),
        "secret_history": _source(secret_scan_receipt),
        "dependency_audit": _source(dependency_audit_receipt),
        "installed_wheel_surface": _source(surface_receipt),
        "canonical_consumer": _source(consumer_receipt),
        "changelog": _source(changelog_receipt),
    }
    artifacts = {
        "wheel": {"filename": wheel.name, "sha256": _sha256(wheel)},
        "sdist": {"filename": sdist.name, "sha256": _sha256(sdist)},
    }
    required_items: dict[str, Any] = {
        "protected_main": {"status": "passed", "commit_sha": expected_sha},
        "integrated_validation": {
            "status": "passed",
            "gate_count": len(iv_gates),
            "skipped_gate_count": 0,
        },
        "wheel_and_sdist": {"status": "passed", **artifacts},
        "non_editable_install": {
            "status": "passed",
            "surface_count": surface["surface_count"],
            "sbom_install_coverage": ["wheel", "sdist"],
        },
        "canonical_consumer": {
            "status": "passed",
            "consumer_commit": DEFAULT_REVISION,
        },
        "journey_certifications": {
            "status": "passed",
            "iv_gates": [
                "runtime_component_index",
                "generator_journey_ledger",
                "installed_wheel_surface_matrix",
                "promotion_readiness",
            ],
        },
        "provenance": {
            "status": "deferred_post_publish",
            "enforcement": "publish OIDC attestations and finalize-release PyPI verification",
        },
        "sbom": {"status": "passed", "documents": sboms},
        "dependency_audit": {
            "status": "passed",
            "dependency_count": dependency["dependency_count"],
            "vulnerability_count": 0,
        },
        "changelog": {
            "status": "passed",
            "section_state": changelog["section_state"],
            "breaking_change_declaration": changelog["breaking_change_declaration"],
        },
        "migration": {"status": "passed", "declaration": migration},
        "release_receipt": {
            "status": "passed",
            "schema_version": SCHEMA_VERSION,
        },
    }
    prepublish_gate_count = sum(
        item.get("status") == "passed" for item in required_items.values()
    )
    post_publish_deferred_count = sum(
        item.get("status") == "deferred_post_publish"
        for item in required_items.values()
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "release_tag": release_tag,
        "release_version": release_version,
        "commit_sha": expected_sha,
        "prepublish_gate_count": prepublish_gate_count,
        "post_publish_deferred_count": post_publish_deferred_count,
        "artifacts": artifacts,
        "source_receipts": sources,
        "coverage": coverage,
        "required_items": required_items,
    }


def _path(value: str) -> Path:
    return Path(value).resolve()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate and aggregate every release gate into one pre-publish receipt."
    )
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--release-tag", required=True)
    parser.add_argument("--dist-dir", type=_path, required=True)
    parser.add_argument("--sbom-dir", type=_path, required=True)
    parser.add_argument("--main-receipt", type=_path, required=True)
    parser.add_argument("--ci-receipt", type=_path, required=True)
    parser.add_argument("--integrated-validation-receipt", type=_path, required=True)
    parser.add_argument("--secret-scan-receipt", type=_path, required=True)
    parser.add_argument("--dependency-audit-receipt", type=_path, required=True)
    parser.add_argument("--surface-receipt", type=_path, required=True)
    parser.add_argument("--consumer-receipt", type=_path, required=True)
    parser.add_argument("--changelog-receipt", type=_path, required=True)
    parser.add_argument("--coverage-receipt", type=_path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--output", type=_path, required=True)
    args = parser.parse_args(argv)
    try:
        # A failed rebuild must not leave an earlier passing output to upload.
        args.output.unlink(missing_ok=True)
        receipt = build_release_gate_receipt(
            expected_sha=args.expected_sha,
            release_tag=args.release_tag,
            dist_dir=args.dist_dir,
            sbom_dir=args.sbom_dir,
            main_receipt=args.main_receipt,
            ci_receipt=args.ci_receipt,
            integrated_validation_receipt=args.integrated_validation_receipt,
            secret_scan_receipt=args.secret_scan_receipt,
            dependency_audit_receipt=args.dependency_audit_receipt,
            surface_receipt=args.surface_receipt,
            consumer_receipt=args.consumer_receipt,
            changelog_receipt=args.changelog_receipt,
            coverage_receipt=args.coverage_receipt,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (OSError, ReleaseGateError, SupplyChainError, ValueError) as exc:
        print(f"FAIL aggregate release gate: {exc}", file=sys.stderr)
        return 1
    print(
        "PASS aggregate release gate: "
        f"tag={receipt['release_tag']} sha={receipt['commit_sha']} "
        f"prepublish={receipt['prepublish_gate_count']} "
        f"post_publish_deferred={receipt['post_publish_deferred_count']} "
        f"receipt={args.output.as_posix()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
