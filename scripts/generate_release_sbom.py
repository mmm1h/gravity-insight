from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from cyclonedx.schema import SchemaVersion
from cyclonedx.validation.json import JsonStrictValidator
from packaging.utils import canonicalize_name

try:
    from supply_chain_common import (
        PACKAGE_NAME,
        ROOT,
        SupplyChainError,
        build_distributions,
        current_python,
        direct_runtime_dependencies,
        ensure_dependency_coverage,
        install_artifact,
        installed_runtime_components,
        package_version_from_filename,
        run_checked,
        select_distributions,
        work_directory,
    )
except ModuleNotFoundError:  # Imported as scripts.generate_release_sbom by tests.
    from scripts.supply_chain_common import (
        PACKAGE_NAME,
        ROOT,
        SupplyChainError,
        build_distributions,
        current_python,
        direct_runtime_dependencies,
        ensure_dependency_coverage,
        install_artifact,
        installed_runtime_components,
        package_version_from_filename,
        run_checked,
        select_distributions,
        work_directory,
    )


SPEC_VERSION = "1.6"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _component_names(document: dict[str, Any]) -> set[str]:
    components = list(document.get("components", []))
    metadata_component = document.get("metadata", {}).get("component")
    if isinstance(metadata_component, dict):
        components.append(metadata_component)
    return {
        canonicalize_name(str(component.get("name", "")))
        for component in components
        if component.get("name")
    }


def _bind_distribution(
    document: dict[str, Any], artifact: Path, kind: str
) -> dict[str, Any]:
    metadata = document.setdefault("metadata", {})
    component = metadata.setdefault("component", {})
    if canonicalize_name(str(component.get("name", ""))) != canonicalize_name(PACKAGE_NAME):
        raise SupplyChainError("CycloneDX metadata does not identify gravity-insight as root")
    digest = _sha256(artifact)
    component["hashes"] = [{"alg": "SHA-256", "content": digest}]
    properties = [
        item
        for item in component.get("properties", [])
        if not str(item.get("name", "")).startswith("gravity:distribution:")
    ]
    properties.extend(
        (
            {"name": "gravity:distribution:filename", "value": artifact.name},
            {"name": "gravity:distribution:kind", "value": kind},
            {"name": "gravity:distribution:sha256", "value": digest},
        )
    )
    component["properties"] = sorted(properties, key=lambda item: item["name"])
    return document


def _validate(document: dict[str, Any], expected_names: set[str]) -> str:
    if document.get("bomFormat") != "CycloneDX" or document.get("specVersion") != SPEC_VERSION:
        raise SupplyChainError("SBOM is not CycloneDX JSON 1.6")
    if "serialNumber" in document or "timestamp" in document.get("metadata", {}):
        raise SupplyChainError("reproducible SBOM contains a random serial number or timestamp")
    missing = sorted(expected_names - _component_names(document))
    if missing:
        raise SupplyChainError("SBOM omits installed components: " + ", ".join(missing))
    rendered = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    validation_error = JsonStrictValidator(SchemaVersion.V1_6).validate_str(rendered)
    if validation_error is not None:
        raise SupplyChainError(f"CycloneDX schema validation failed: {validation_error}")
    return rendered


def generate_one(
    artifact: Path,
    *,
    kind: str,
    output_dir: Path,
    python: Path,
) -> dict[str, Any]:
    with work_directory(f"sbom-{kind}-") as work:
        target_python, site_packages = install_artifact(python, artifact, work / "environment")
        components = installed_runtime_components(site_packages)
        direct = direct_runtime_dependencies(site_packages)
        ensure_dependency_coverage(components, direct)
        raw_output = work / "raw.cdx.json"
        environment = dict(__import__("os").environ)
        environment.update({"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"})
        run_checked(
            (
                str(python),
                "-m",
                "cyclonedx_py",
                "environment",
                str(target_python),
                "--pyproject",
                str(ROOT / "pyproject.toml"),
                "--mc-type",
                "library",
                "--sv",
                SPEC_VERSION,
                "--output-reproducible",
                "--of",
                "JSON",
                "-o",
                str(raw_output),
            ),
            label=f"CycloneDX generation for {kind}",
            env=environment,
        )
        document = json.loads(raw_output.read_text(encoding="utf-8"))
        rendered = _validate(
            _bind_distribution(document, artifact, kind),
            {canonicalize_name(item["name"]) for item in components},
        )
    version = package_version_from_filename(artifact)
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"gravity_insight-{version}-{kind}.cdx.json"
    output.write_text(rendered, encoding="utf-8", newline="\n")
    return {
        "artifact": artifact.name,
        "artifact_sha256": _sha256(artifact),
        "component_count": len(components),
        "direct_dependency_count": len(direct),
        "format": "CycloneDX JSON",
        "output": output.as_posix(),
        "sha256": _sha256(output),
        "spec_version": SPEC_VERSION,
        "tool": {"name": "cyclonedx-bom", "version": importlib.metadata.version("cyclonedx-bom")},
    }


def generate_release_sboms(
    wheel: Path, sdist: Path, *, output_dir: Path, python: Path
) -> list[dict[str, Any]]:
    return [
        generate_one(wheel, kind="wheel", output_dir=output_dir, python=python),
        generate_one(sdist, kind="sdist", output_dir=output_dir, python=python),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate reproducible CycloneDX SBOMs for wheel and sdist."
    )
    parser.add_argument("--dist-dir", type=Path, default=ROOT / "dist")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "tmp" / "release-sbom")
    parser.add_argument("--python", type=Path, default=current_python())
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.build:
            with work_directory("sbom-build-") as build_dir:
                wheel, sdist = build_distributions(args.python, build_dir)
                results = generate_release_sboms(
                    wheel, sdist, output_dir=args.output_dir, python=args.python
                )
        else:
            wheel, sdist = select_distributions(args.dist_dir)
            results = generate_release_sboms(
                wheel, sdist, output_dir=args.output_dir, python=args.python
            )
    except (OSError, ValueError, SupplyChainError, json.JSONDecodeError) as exc:
        print(f"SBOM generation failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "passed", "sboms": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
