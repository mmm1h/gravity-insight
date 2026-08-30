"""Render Built-in Skill wheel resources from authoritative JSON manifests."""

from __future__ import annotations

import argparse
from pathlib import Path

from gravity_sdk.skill_contract import skill_artifacts
from gravity_sdk.skill_render import render_package_files, skill_package_descriptor


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src" / "gravity_sdk"


def render_outputs() -> dict[Path, bytes]:
    result: dict[Path, bytes] = {}
    for artifact in skill_artifacts():
        root = PACKAGE_ROOT / skill_package_descriptor(artifact)["resource_root"]
        for relative, content in render_package_files(artifact).items():
            result[root / Path(*relative.split("/"))] = content
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = render_outputs()
    roots = {path.parents[1] if path.parent.name == "references" else path.parent for path in rendered}
    expected_paths = set(rendered)
    extras = sorted(
        path
        for root in roots
        if root.is_dir()
        for path in root.rglob("*")
        if path.is_file() and path not in expected_paths
    )
    mismatched = [
        path
        for path, content in rendered.items()
        if not path.is_file() or path.read_bytes() != content
    ]
    if args.check:
        if mismatched or extras:
            parts: list[str] = []
            if mismatched:
                parts.append(
                    "generated Skill package files are missing or differ from their "
                    "authoritative manifests: "
                    + ", ".join(
                        str(path.relative_to(ROOT)) for path in mismatched
                    )
                    + ". Run `python scripts/generate_skill_packages.py` to rebuild "
                    "those generated package files, then review the result."
                )
            if extras:
                parts.append(
                    "unregistered files exist inside generated Skill package roots: "
                    + ", ".join(str(path.relative_to(ROOT)) for path in extras)
                    + ". The generator will not delete them. Review each listed file "
                    "and delete only files that are not registered package content; "
                    "then run `python scripts/generate_skill_packages.py`."
                )
            raise SystemExit(" ".join(parts))
        print("Built-in Skill packages are current")
        return 0
    if extras:
        raise SystemExit(
            "refusing to delete unregistered Skill package files: "
            + ", ".join(str(path.relative_to(ROOT)) for path in extras)
        )
    for path, content in rendered.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print(f"rendered {len(rendered)} Built-in Skill package files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
