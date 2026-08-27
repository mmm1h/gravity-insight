"""Build and import the non-editable distribution that users receive."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path, PurePosixPath

from tests.agent_migration_characterization import module_inventory


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ONLY_RESOURCES = frozenset({
    "census/census-guide.md", "contracts/contracts-guide.md",
    "contracts/prober-guide.md",
})
KNOWN_WHEEL_IMPORT_FAILURES = {
    "gravity_sdk.quality": (
        "ValueError",
        "is not in the subpath",
    ),
}


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


class InstalledWheelTests(unittest.TestCase):
    def test_built_wheel_contains_and_imports_every_source_module_and_resource(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="gravity-sdk-wheel-") as raw:
            temporary = Path(raw).resolve()
            self.assertNotEqual(ROOT, temporary)
            self.assertNotIn(ROOT, temporary.parents)
            project = temporary / "project"
            source = project / "src" / "gravity_sdk"
            wheelhouse = temporary / "wheelhouse"
            extracted = temporary / "extracted"
            project.mkdir()
            shutil.copy2(ROOT / "pyproject.toml", project / "pyproject.toml")
            shutil.copy2(ROOT / "README.md", project / "README.md")
            ignored = shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info")
            shutil.copytree(ROOT / "src", project / "src", ignore=ignored)
            wheelhouse.mkdir()
            pip = [sys.executable, "-m", "pip", "--disable-pip-version-check"]
            wheel_command = [
                "wheel", "--no-deps",
                "--wheel-dir", str(wheelhouse), str(project),
            ]
            _run(pip + wheel_command, cwd=temporary)
            wheels = list(wheelhouse.glob("gravity_insight-*.whl"))
            self.assertEqual(1, len(wheels), f"unexpected wheels: {wheels}")
            with zipfile.ZipFile(wheels[0]) as wheel:
                entries = wheel.namelist()
                unsafe = [
                    entry for entry in entries
                    if PurePosixPath(entry).is_absolute()
                    or ".." in PurePosixPath(entry).parts
                ]
                self.assertEqual([], unsafe, "wheel contains unsafe paths")
                metadata_paths = [
                    entry for entry in entries if entry.endswith(".dist-info/WHEEL")
                ]
                self.assertEqual(1, len(metadata_paths))
                metadata = wheel.read(metadata_paths[0]).decode("utf-8")
                self.assertIn("Root-Is-Purelib: true", metadata)
                wheel.extractall(extracted)

            expected_modules = {
                name for name, _ in module_inventory(source).values()
            }
            source_resources = _resource_inventory(source)
            self.assertLessEqual(SOURCE_ONLY_RESOURCES, source_resources)
            expected_resources = source_resources - SOURCE_ONLY_RESOURCES
            wheel_package = extracted / "gravity_sdk"
            installed_modules = {
                name for name, _ in module_inventory(wheel_package).values()
            }
            missing = sorted(expected_modules - installed_modules)
            extra = sorted(installed_modules - expected_modules)
            self.assertEqual(
                expected_modules,
                installed_modules,
                f"wheel module inventory drift; missing={missing}, extra={extra}",
            )
            installed_resources = _resource_inventory(wheel_package)
            missing_resources = sorted(expected_resources - installed_resources)
            if missing_resources:
                self.fail(
                    "wheel resource inventory drift; "
                    f"missing_count={len(missing_resources)}, "
                    f"sample={missing_resources[:20]}"
                )

            probe = r"""
import importlib
import json
import pathlib
import sys

target = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(target))
import gravity_sdk
assert pathlib.Path(gravity_sdk.__file__).resolve().is_relative_to(target)
assert all(
    pathlib.Path(entry).resolve().is_relative_to(target)
    for entry in gravity_sdk.__path__
)
failures = []
for module in json.load(sys.stdin):
    try:
        importlib.import_module(module)
    except BaseException as error:
        failures.append(
            {"module": module, "type": type(error).__name__, "message": str(error)}
        )
leaks = []
for name, module in sys.modules.items():
    location = getattr(module, "__file__", None)
    if name.startswith("gravity_sdk") and location:
        resolved = pathlib.Path(location).resolve()
        if not resolved.is_relative_to(target):
            leaks.append({"module": name, "path": str(resolved)})
assert leaks == [], f"imports escaped extracted wheel: {leaks}"
print(json.dumps(failures))
"""
            completed = subprocess.run(
                [sys.executable, "-I", "-c", probe, str(extracted)],
                input=json.dumps(sorted(expected_modules)), text=True,
                capture_output=True, cwd=temporary, timeout=300,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            failures = json.loads(completed.stdout)
            self.assertEqual(
                set(KNOWN_WHEEL_IMPORT_FAILURES),
                {item["module"] for item in failures},
                failures,
            )
            for failure in failures:
                expected_type, *message_parts = KNOWN_WHEEL_IMPORT_FAILURES[
                    failure["module"]
                ]
                self.assertEqual(expected_type, failure["type"])
                for expected_message in message_parts:
                    self.assertIn(expected_message, failure["message"])


if __name__ == "__main__":
    unittest.main()
