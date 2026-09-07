"""Setuptools hooks for staging the generated Skill seed into distributions."""

from __future__ import annotations

import sys
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.command.sdist import sdist as _sdist


ROOT = Path(__file__).resolve().parent
SOURCE_SEED = ROOT / "src" / "gravity_insight" / "skill_seed" / "skill-seed-v1.zip"


def _render_seed() -> bytes:
    sys.path.insert(0, str(ROOT / "src"))
    sys.path.insert(0, str(ROOT))
    try:
        from scripts.generate_skill_library import render_seed

        return render_seed()
    finally:
        del sys.path[:2]


class _SeedBuildPy(_build_py):
    def run(self) -> None:
        super().run()
        target = Path(self.build_lib) / "gravity_insight" / "skill_seed" / SOURCE_SEED.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(SOURCE_SEED.read_bytes() if SOURCE_SEED.is_file() else _render_seed())

    def get_outputs(self, include_bytecode: bool = True) -> list[str]:
        outputs = list(super().get_outputs(include_bytecode=include_bytecode))
        target = Path(self.build_lib) / "gravity_insight" / "skill_seed" / SOURCE_SEED.name
        if str(target) not in outputs:
            outputs.append(str(target))
        return outputs


class _SeedSdist(_sdist):
    def make_release_tree(self, base_dir: str, files: list[str]) -> None:
        super().make_release_tree(base_dir, files)
        target = Path(base_dir) / "src" / "gravity_insight" / "skill_seed" / SOURCE_SEED.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_render_seed())


setup(cmdclass={"build_py": _SeedBuildPy, "sdist": _SeedSdist})
