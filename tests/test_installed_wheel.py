"""Build and import the non-editable distribution that users receive."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ONLY_RESOURCES = frozenset({
    "census/census-guide.md", "contracts/contracts-guide.md",
    "contracts/prober-guide.md",
})
KNOWN_WHEEL_IMPORT_FAILURES = {"gravity_sdk.quality": ("ValueError", "is not in the subpath")}


def _module_inventory(package: Path) -> set[str]:
    modules: set[str] = set()
    for path in package.rglob("*.py"):
        parts = list(path.relative_to(package).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules.add(".".join(("gravity_sdk", *parts)))
    return modules


def _resource_inventory(package: Path) -> set[str]:
    return {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file()
        and path.suffix not in {".py", ".pyc"}
        and "__pycache__" not in path.parts
    }


def _run(command: list[str], *, cwd: Path, timeout: int = 300) -> None:
    completed = subprocess.run(
        command, cwd=cwd, text=True, capture_output=True, timeout=timeout,
    )
    assert completed.returncode == 0, (
        f"command failed ({completed.returncode}): {' '.join(command)}\n"
        f"{completed.stdout}\n{completed.stderr}"
    )


def test_built_wheel_contains_and_imports_every_source_module_and_resource() -> None:
    with tempfile.TemporaryDirectory(prefix="gravity-sdk-wheel-") as raw:
        temporary = Path(raw).resolve()
        assert ROOT not in temporary.parents and temporary != ROOT
        project = temporary / "project"
        source = project / "src" / "gravity_sdk"
        wheelhouse = temporary / "wheelhouse"
        installed = temporary / "installed"
        project.mkdir()
        shutil.copy2(ROOT / "pyproject.toml", project / "pyproject.toml")
        shutil.copy2(ROOT / "README.md", project / "README.md")
        ignored = shutil.ignore_patterns("__pycache__", "*.pyc")
        shutil.copytree(ROOT / "src", project / "src", ignore=ignored)
        wheelhouse.mkdir()
        pip = [sys.executable, "-m", "pip"]
        wheel_command = ["wheel", "--no-deps", "--wheel-dir", str(wheelhouse)]
        _run(pip + wheel_command + [str(project)], cwd=temporary)
        wheels = list(wheelhouse.glob("gravity_sdk-*.whl"))
        assert len(wheels) == 1, f"expected one wheel, found {wheels}"
        install_command = ["install", "--no-compile", "--no-deps", "--target"]
        _run(pip + install_command + [str(installed), str(wheels[0])], cwd=temporary)

        expected_modules = _module_inventory(source)
        source_resources = _resource_inventory(source)
        assert SOURCE_ONLY_RESOURCES <= source_resources
        expected_resources = source_resources - SOURCE_ONLY_RESOURCES
        wheel_package = installed / "gravity_sdk"
        installed_modules = _module_inventory(wheel_package)
        missing = sorted(expected_modules - installed_modules)
        extra = sorted(installed_modules - expected_modules)
        assert installed_modules == expected_modules, (
            f"wheel module inventory drift; missing={missing}, extra={extra}"
        )
        installed_resources = _resource_inventory(wheel_package)
        missing_resources = sorted(expected_resources - installed_resources)
        assert expected_resources <= installed_resources, missing_resources

        probe = r"""
import importlib
import json
import pathlib
import sys

target = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(target))
import gravity_sdk
assert pathlib.Path(gravity_sdk.__file__).resolve().is_relative_to(target)
failures = []
for module in json.load(sys.stdin):
    try:
        importlib.import_module(module)
    except BaseException as error:
        failures.append(
            {"module": module, "type": type(error).__name__, "message": str(error)}
        )
print(json.dumps(failures))
"""
        completed = subprocess.run(
            [sys.executable, "-I", "-c", probe, str(installed)],
            input=json.dumps(sorted(expected_modules)), text=True,
            capture_output=True, cwd=temporary, timeout=300,
        )
        assert completed.returncode == 0, completed.stderr
        failures = json.loads(completed.stdout)
        assert {item["module"] for item in failures} == set(KNOWN_WHEEL_IMPORT_FAILURES), failures
        for failure in failures:
            expected_type, expected_message = KNOWN_WHEEL_IMPORT_FAILURES[failure["module"]]
            assert failure["type"] == expected_type
            assert expected_message in failure["message"]
