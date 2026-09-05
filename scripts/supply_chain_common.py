from __future__ import annotations

import importlib.metadata
import json
import os
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT / "tmp"
PACKAGE_NAME = "gravity-insight"


class SupplyChainError(RuntimeError):
    pass


def command_text(completed: subprocess.CompletedProcess[str], *, limit: int = 4000) -> str:
    output = "\n".join(
        part.strip() for part in (completed.stdout or "", completed.stderr or "") if part.strip()
    )
    return output[-limit:] if output else "no diagnostic output"


def run_checked(
    command: Sequence[str],
    *,
    label: str,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env={**(os.environ if env is None else env), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SupplyChainError(f"{label} failed: {command_text(completed)}")
    return completed


@contextmanager
def work_directory(prefix: str) -> Iterator[Path]:
    TMP_ROOT.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=prefix, dir=TMP_ROOT) as raw:
        yield Path(raw)


def build_distributions(python: Path, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_checked(
        (str(python), "-m", "build", "--outdir", str(output_dir), str(ROOT)),
        label="wheel and sdist build",
    )
    return select_distributions(output_dir)


def select_distributions(dist_dir: Path) -> tuple[Path, Path]:
    wheels = sorted(dist_dir.glob("*.whl"))
    sdists = sorted(dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise SupplyChainError(
            "distribution selection requires exactly one wheel and one sdist; "
            f"found wheels={len(wheels)}, sdists={len(sdists)} in {dist_dir}"
        )
    return wheels[0].resolve(), sdists[0].resolve()


def _environment_python(environment: Path) -> Path:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def install_artifact(
    host_python: Path,
    artifact: Path,
    environment: Path,
) -> tuple[Path, Path]:
    run_checked(
        (str(host_python), "-m", "venv", "--without-pip", str(environment)),
        label=f"create isolated environment for {artifact.name}",
    )
    target_python = _environment_python(environment)
    run_checked(
        (
            str(host_python),
            "-m",
            "pip",
            "--python",
            str(target_python),
            "install",
            "--disable-pip-version-check",
            "--no-compile",
            str(artifact),
        ),
        label=f"non-editable install of {artifact.name}",
    )
    completed = run_checked(
        (
            str(target_python),
            "-c",
            "import json,site; print(json.dumps(site.getsitepackages()))",
        ),
        label="locate isolated site-packages",
    )
    paths = json.loads(completed.stdout)
    site_packages = next(
        (Path(value) for value in paths if Path(value).name == "site-packages"),
        None,
    )
    if site_packages is None or not site_packages.is_dir():
        raise SupplyChainError("isolated site-packages directory is unavailable")
    return target_python, site_packages


def installed_runtime_components(site_packages: Path) -> list[dict[str, str]]:
    components = []
    for distribution in importlib.metadata.distributions(path=[str(site_packages)]):
        name = distribution.metadata.get("Name")
        if name:
            components.append({"name": name, "version": distribution.version})
    components.sort(key=lambda item: canonicalize_name(item["name"]))
    names = {canonicalize_name(item["name"]) for item in components}
    if canonicalize_name(PACKAGE_NAME) not in names:
        raise SupplyChainError("isolated install does not contain gravity-insight")
    if len(components) < 2:
        raise SupplyChainError("isolated install contains no runtime dependencies")
    return components


def direct_runtime_dependencies(site_packages: Path) -> set[str]:
    root = next(
        (
            distribution
            for distribution in importlib.metadata.distributions(path=[str(site_packages)])
            if canonicalize_name(distribution.metadata.get("Name", ""))
            == canonicalize_name(PACKAGE_NAME)
        ),
        None,
    )
    if root is None:
        raise SupplyChainError("gravity-insight distribution metadata is unavailable")
    selected: set[str] = set()
    for raw in root.requires or ():
        requirement = Requirement(raw)
        if requirement.marker is not None and not requirement.marker.evaluate({"extra": ""}):
            continue
        selected.add(canonicalize_name(requirement.name))
    if not selected:
        raise SupplyChainError("gravity-insight declares no runtime dependencies")
    return selected


def ensure_dependency_coverage(
    components: Sequence[dict[str, str]], direct_dependencies: set[str]
) -> None:
    installed = {canonicalize_name(item["name"]) for item in components}
    missing = sorted(direct_dependencies - installed)
    if missing:
        raise SupplyChainError(
            "isolated install is missing declared runtime dependencies: " + ", ".join(missing)
        )


def package_version_from_filename(artifact: Path) -> str:
    match = re.search(r"gravity[_-]insight-(\d+\.\d+\.\d+)", artifact.name)
    if not match:
        raise SupplyChainError(f"unrecognized gravity-insight artifact name: {artifact.name}")
    return match.group(1)


def current_python() -> Path:
    return Path(sys.executable).resolve()
