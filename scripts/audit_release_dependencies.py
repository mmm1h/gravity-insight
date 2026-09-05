from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import os
import sys
from pathlib import Path
from typing import Any, Sequence

from packaging.utils import canonicalize_name

try:
    from supply_chain_common import (
        ROOT,
        SupplyChainError,
        build_distributions,
        command_text,
        current_python,
        direct_runtime_dependencies,
        ensure_dependency_coverage,
        install_artifact,
        installed_runtime_components,
        select_distributions,
        work_directory,
    )
except ModuleNotFoundError:  # Imported as scripts.audit_release_dependencies by tests.
    from scripts.supply_chain_common import (
        ROOT,
        SupplyChainError,
        build_distributions,
        command_text,
        current_python,
        direct_runtime_dependencies,
        ensure_dependency_coverage,
        install_artifact,
        installed_runtime_components,
        select_distributions,
        work_directory,
    )


def _parse_audit(raw: str) -> dict[str, Any]:
    document = json.loads(raw)
    if not isinstance(document, dict) or not isinstance(document.get("dependencies"), list):
        raise ValueError("pip-audit JSON does not contain a dependencies array")
    return document


def _vulnerabilities(document: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    for dependency in document["dependencies"]:
        for vulnerability in dependency.get("vulns", []):
            findings.append(
                {
                    "dependency": str(dependency.get("name", "<unknown>")),
                    "id": str(vulnerability.get("id", "<unknown>")),
                    "version": str(dependency.get("version", "<unknown>")),
                }
            )
    return sorted(findings, key=lambda item: (item["id"], item["dependency"]))


def audit_site_packages(
    site_packages: Path,
    *,
    python: Path,
    osv_url: str,
    timeout: int,
    runner=subprocess.run,
) -> tuple[int, dict[str, Any]]:
    components = installed_runtime_components(site_packages)
    direct = direct_runtime_dependencies(site_packages)
    ensure_dependency_coverage(components, direct)
    completed = runner(
        (
            str(python),
            "-m",
            "pip_audit",
            "--path",
            str(site_packages),
            "--strict",
            "--format",
            "json",
            "--vulnerability-service",
            "osv",
            "--osv-url",
            osv_url,
            "--timeout",
            str(timeout),
            "--progress-spinner",
            "off",
        ),
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        errors="replace",
        capture_output=True,
        check=False,
    )
    try:
        document = _parse_audit(completed.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        return 2, {
            "dependency_count": len(components),
            "diagnostic": command_text(completed),
            "reason": f"advisory service did not return a complete audit: {exc}",
            "status": "unable_to_audit",
        }
    audited_names = {
        canonicalize_name(str(item.get("name", ""))) for item in document["dependencies"]
    }
    expected_names = {canonicalize_name(item["name"]) for item in components}
    missing = sorted(expected_names - audited_names)
    if missing:
        return 2, {
            "dependency_count": len(components),
            "missing_dependencies": missing,
            "reason": "pip-audit returned an incomplete dependency set",
            "status": "unable_to_audit",
        }
    findings = _vulnerabilities(document)
    if findings:
        return 1, {
            "dependency_count": len(components),
            "findings": findings,
            "status": "vulnerabilities_found",
            "vulnerability_count": len(findings),
        }
    if completed.returncode != 0:
        return 2, {
            "dependency_count": len(components),
            "diagnostic": command_text(completed),
            "reason": "pip-audit exited nonzero without a vulnerability finding",
            "status": "unable_to_audit",
        }
    return 0, {
        "dependency_count": len(components),
        "findings": [],
        "status": "passed",
        "vulnerability_count": 0,
    }


def audit_artifact(
    artifact: Path, *, python: Path, osv_url: str, timeout: int
) -> tuple[int, dict[str, Any]]:
    with work_directory("dependency-audit-") as work:
        _, site_packages = install_artifact(python, artifact, work / "environment")
        code, receipt = audit_site_packages(
            site_packages, python=python, osv_url=osv_url, timeout=timeout
        )
    receipt["artifact"] = artifact.name
    receipt["artifact_sha256"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    receipt["service"] = "OSV"
    receipt["tool"] = {
        "name": "pip-audit",
        "version": importlib.metadata.version("pip-audit"),
    }
    return code, receipt


def _write_receipt(path: Path | None, receipt: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed runtime dependency audit.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--artifact", type=Path)
    source.add_argument("--site-packages", type=Path)
    source.add_argument("--build", action="store_true")
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--python", type=Path, default=current_python())
    parser.add_argument("--osv-url", default="https://api.osv.dev/v1/query")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.site_packages is not None:
            code, receipt = audit_site_packages(
                args.site_packages.resolve(),
                python=args.python,
                osv_url=args.osv_url,
                timeout=args.timeout,
            )
            receipt["artifact"] = "installed-site-packages"
            receipt["service"] = "OSV"
            receipt["tool"] = {
                "name": "pip-audit",
                "version": importlib.metadata.version("pip-audit"),
            }
        elif args.artifact is not None:
            code, receipt = audit_artifact(
                args.artifact.resolve(),
                python=args.python,
                osv_url=args.osv_url,
                timeout=args.timeout,
            )
        elif args.build:
            with work_directory("dependency-audit-build-") as build_dir:
                wheel, _ = build_distributions(args.python, build_dir)
                code, receipt = audit_artifact(
                    wheel,
                    python=args.python,
                    osv_url=args.osv_url,
                    timeout=args.timeout,
                )
        else:
            wheel, _ = select_distributions(args.dist_dir)
            code, receipt = audit_artifact(
                wheel,
                python=args.python,
                osv_url=args.osv_url,
                timeout=args.timeout,
            )
    except (OSError, ValueError, SupplyChainError) as exc:
        code, receipt = 2, {"reason": str(exc), "status": "unable_to_audit"}
    _write_receipt(args.receipt, receipt)
    stream = sys.stdout if code == 0 else sys.stderr
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True), file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
