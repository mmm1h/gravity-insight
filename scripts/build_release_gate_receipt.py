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
    from scripts.supply_chain_common import SupplyChainError, select_distributions
except ModuleNotFoundError:
    from check_installed_wheel_consumer import DEFAULT_REVISION
    from check_release_ci import SCHEMA_VERSION as CI_SCHEMA
    from check_release_main import SCHEMA_VERSION as MAIN_SCHEMA
    from run_integrated_validation import gate_specs
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


def _validate_main(document: Mapping[str, Any], expected_sha: str, tag: str) -> None:
    _require(document.get("schema_version") == MAIN_SCHEMA, "main receipt schema mismatch")
    expected = {
        "status": "passed",
        "event_name": "push",
        "release_tag": tag,
        "commit_sha": expected_sha,
        "protected_branch": "main",
        "branch_protected": True,
        "checked_out_head": expected_sha,
        "tag_commit": expected_sha,
        "main_commit": expected_sha,
        "branch_api_commit": expected_sha,
    }
    _require(
        all(document.get(key) == value for key, value in expected.items()),
        f"main receipt is not exact-SHA protected-main evidence: {document}",
    )


def _validate_ci(document: Mapping[str, Any], expected_sha: str) -> None:
    _require(document.get("schema_version") == CI_SCHEMA, "CI receipt schema mismatch")
    expected = {
        "status": "passed",
        "commit_sha": expected_sha,
        "event_name": "push",
        "branch": "main",
        "workflow_path": ".github/workflows/ci.yml",
        "conclusion": "success",
    }
    _require(
        all(document.get(key) == value for key, value in expected.items()),
        f"CI receipt is not a green exact-SHA push/main run: {document}",
    )
    _require(isinstance(document.get("run_id"), int), "CI receipt run_id is missing")
    required = document.get("required_job")
    _require(
        isinstance(required, Mapping)
        and required.get("name") == "ci-required"
        and required.get("conclusion") == "success",
        "CI receipt does not bind one successful ci-required job",
    )


def _validate_iv(document: Mapping[str, Any], expected_sha: str) -> list[str]:
    _require(
        document.get("schema_version") == "gravity.integrated-validation-receipt.v2",
        "Integrated Validation receipt schema mismatch",
    )
    expected = {
        "commit_sha": expected_sha,
        "branch": "main",
        "trial": False,
        "complete_gate_set": True,
        "integrated_validation_green": True,
        "overall": "passed",
    }
    _require(
        all(document.get(key) == value for key, value in expected.items()),
        "Integrated Validation receipt is not an unqualified green exact-main receipt",
    )
    before = document.get("preconditions_before")
    after = document.get("preconditions_after")
    _require(
        isinstance(before, Mapping)
        and before.get("head") == expected_sha
        and before.get("branch_is_main") is True
        and before.get("clean") is True
        and before.get("independent_venv") is True,
        "Integrated Validation starting preconditions are not release-grade",
    )
    _require(
        isinstance(after, Mapping)
        and after.get("head") == expected_sha
        and after.get("branch_is_main") is True
        and after.get("clean") is True
        and after.get("independent_venv") is True,
        "Integrated Validation ending preconditions drifted",
    )
    gates = document.get("gates")
    _require(isinstance(gates, list), "Integrated Validation gates must be an array")
    expected_names = [
        gate.name
        for gate in gate_specs(
            Path(sys.executable), ROOT / "tmp/release-gate-inventory"
        )
    ]
    observed: dict[str, Mapping[str, Any]] = {}
    for gate in gates:
        _require(isinstance(gate, Mapping), "Integrated Validation gate must be an object")
        name = gate.get("name")
        _require(isinstance(name, str) and name not in observed, "duplicate or unnamed IV gate")
        observed[name] = gate
    _require(
        set(observed) == set(expected_names),
        "Integrated Validation gate inventory mismatch: "
        f"missing={sorted(set(expected_names) - set(observed))}, "
        f"extra={sorted(set(observed) - set(expected_names))}",
    )
    failed = [
        name
        for name in expected_names
        if observed[name].get("status") != "pass"
        or observed[name].get("passed") is not True
        or observed[name].get("exit_code") != 0
    ]
    _require(not failed, f"Integrated Validation has non-pass gates: {failed}")
    _require(document.get("skipped_gates") == [], "release IV may not contain skipped gates")
    return expected_names


def _validate_secret(document: Mapping[str, Any], expected_sha: str) -> None:
    _require(
        document.get("status") == "passed"
        and document.get("history_included") is True
        and document.get("repository_head") == expected_sha
        and isinstance(document.get("history_commit_count"), int)
        and document.get("history_commit_count", 0) > 0
        and isinstance(document.get("scanned_tracked_file_count"), int)
        and document.get("scanned_tracked_file_count", 0) > 0
        and document.get("unreviewed_findings") == [],
        "secret-history receipt is not a complete exact-SHA pass",
    )


def _sbom_binding(document: Mapping[str, Any]) -> tuple[str, str, str]:
    _require(
        document.get("bomFormat") == "CycloneDX"
        and document.get("specVersion") == "1.6",
        "SBOM is not CycloneDX JSON 1.6",
    )
    metadata = document.get("metadata")
    component = metadata.get("component") if isinstance(metadata, Mapping) else None
    _require(isinstance(component, Mapping), "SBOM root component is missing")
    properties = component.get("properties")
    _require(isinstance(properties, list), "SBOM distribution properties are missing")
    bound = {
        item.get("name"): item.get("value")
        for item in properties
        if isinstance(item, Mapping)
        and isinstance(item.get("name"), str)
        and str(item.get("name")).startswith("gravity:distribution:")
    }
    filename = bound.get("gravity:distribution:filename")
    kind = bound.get("gravity:distribution:kind")
    digest = bound.get("gravity:distribution:sha256")
    _require(
        isinstance(filename, str)
        and kind in {"wheel", "sdist"}
        and isinstance(digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", digest) is not None,
        "SBOM distribution binding is incomplete",
    )
    hashes = component.get("hashes")
    _require(
        isinstance(hashes, list)
        and {item.get("content") for item in hashes if isinstance(item, Mapping) and item.get("alg") == "SHA-256"}
        == {digest},
        "SBOM root SHA-256 does not match its distribution binding",
    )
    return kind, filename, digest


def _validate_sboms(
    sbom_dir: Path, *, wheel: Path, sdist: Path
) -> dict[str, dict[str, str]]:
    paths = sorted(sbom_dir.glob("*.cdx.json"))
    _require(len(paths) == 2, f"expected exactly two SBOM documents, found {len(paths)}")
    expected = {
        "wheel": (wheel.name, _sha256(wheel)),
        "sdist": (sdist.name, _sha256(sdist)),
    }
    observed: dict[str, dict[str, str]] = {}
    for path in paths:
        kind, filename, digest = _sbom_binding(_load(path, f"{path.name} SBOM"))
        _require(kind not in observed, f"duplicate {kind} SBOM")
        _require(
            (filename, digest) == expected[kind],
            f"{kind} SBOM is not bound to the intended distribution",
        )
        observed[kind] = {"filename": filename, "artifact_sha256": digest, **_source(path)}
    _require(set(observed) == {"wheel", "sdist"}, "wheel and sdist SBOMs are both required")
    return observed


def _validate_dependency(
    document: Mapping[str, Any], *, wheel: Path
) -> None:
    _require(
        document.get("status") == "passed"
        and document.get("artifact") == wheel.name
        and document.get("artifact_sha256") == _sha256(wheel)
        and document.get("vulnerability_count") == 0
        and document.get("findings") == []
        and isinstance(document.get("dependency_count"), int)
        and document.get("dependency_count", 0) > 0
        and document.get("service") == "OSV",
        "dependency-audit receipt is not a clean intended-wheel result",
    )


def _validate_surface(document: Mapping[str, Any], *, wheel: Path) -> None:
    _require(
        document.get("schema_version") == "gravity.installed-wheel-surface-matrix.v1"
        and document.get("passed") is True
        and document.get("wheel") == wheel.name
        and document.get("wheel_sha256") == _sha256(wheel)
        and document.get("surface_count") == len(_SURFACES)
        and document.get("network_calls") == 0,
        "installed-wheel surface receipt is invalid or bound to another wheel",
    )
    cases = document.get("cases")
    _require(
        isinstance(cases, list)
        and cases
        and document.get("case_count") == len(cases),
        "installed-wheel surface cases are missing or miscounted",
    )
    for case in cases:
        surfaces = case.get("surfaces") if isinstance(case, Mapping) else None
        _require(
            isinstance(surfaces, Mapping)
            and set(surfaces) == _SURFACES
            and set(surfaces.values()) == {"passed"},
            "installed-wheel surface case is incomplete",
        )


def _validate_consumer(document: Mapping[str, Any], *, wheel: Path) -> None:
    check = document.get("check")
    _require(
        document.get("schema_version") == "gravity.installed-wheel-consumer-gate.v1"
        and document.get("status") == "pass"
        and document.get("passed") is True
        and document.get("exit_code") == 0
        and document.get("strict_prerequisites") is True
        and document.get("revision") == DEFAULT_REVISION
        and isinstance(check, Mapping),
        "canonical-consumer gate did not strictly pass",
    )
    _require(
        check.get("schema_version") == "gravity.installed-wheel-consumer-check.v2"
        and check.get("passed") is True
        and check.get("consumer_commit") == DEFAULT_REVISION
        and check.get("wheel") == wheel.name
        and check.get("wheel_sha256") == _sha256(wheel)
        and check.get("network_calls") == 0,
        "canonical-consumer receipt is invalid or bound to another wheel",
    )
    summary = check.get("summary")
    _require(
        isinstance(summary, Mapping)
        and summary.get("ok") is True
        and isinstance(summary.get("tests_run"), int)
        and summary.get("tests_run", 0) > 0,
        "canonical-consumer tests did not report a non-empty OK run",
    )


def _validate_changelog(
    document: Mapping[str, Any], *, release_version: str, expected_sha: str
) -> dict[str, Any]:
    _require(
        document.get("schema_version") == "gravity.release-changelog.v1"
        and document.get("status") == "passed"
        and document.get("release_version") == release_version
        and document.get("project_version") == release_version
        and document.get("repository_head") == expected_sha
        and document.get("section_state") in {"unreleased_target", "released"}
        and document.get("breaking_change_declaration") in {"declared", "none_declared"},
        "changelog receipt is not bound to the release version",
    )
    migration = document.get("migration")
    _require(
        isinstance(migration, Mapping)
        and migration.get("status") in {"required_and_present", "not_required"},
        "migration declaration is missing",
    )
    if document.get("breaking_change_declaration") == "declared":
        _require(
            isinstance(document.get("breaking_entries"), int)
            and document.get("breaking_entries", 0) > 0,
            "breaking-change declaration has no entries",
        )
        path = migration.get("path")
        _require(
            migration.get("status") == "required_and_present"
            and isinstance(path, str)
            and (ROOT / path).is_file()
            and migration.get("sha256") == _sha256(ROOT / path),
            "breaking release migration guide is absent or changed",
        )
    else:
        _require(
            document.get("breaking_entries") == 0
            and migration.get("status") == "not_required",
            "non-breaking migration declaration drifted",
        )
    _require(
        document.get("changelog_sha256") == _sha256(ROOT / "CHANGELOG.md")
        and document.get("released_section_lock_sha256")
        == _sha256(ROOT / "scripts/changelog_release_lock.json"),
        "changelog receipt source binding is stale",
    )
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
) -> dict[str, Any]:
    _require(_SHA_RE.fullmatch(expected_sha) is not None, "expected SHA must be a full commit SHA")
    tag_match = _TAG_RE.fullmatch(release_tag)
    _require(tag_match is not None, "release tag must be vMAJOR.MINOR.PATCH")
    release_version = tag_match.group("version")
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
    parser.add_argument("--output", type=_path, required=True)
    args = parser.parse_args(argv)
    try:
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
