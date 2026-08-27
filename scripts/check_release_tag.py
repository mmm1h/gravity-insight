"""Require every release tag at HEAD to match the installed project version."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Sequence

from gravity_sdk import __version__


ROOT = Path(__file__).resolve().parents[1]


def head_release_tags(repository: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "tag", "--points-at", "HEAD", "--list", "v*"],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"cannot inspect HEAD tags: {detail}")
    return sorted(line.strip() for line in completed.stdout.splitlines() if line.strip())


def check_release_tags(version: str, tags: Sequence[str]) -> str:
    expected = f"v{version}"
    if not tags:
        return f"PASS release-tag: HEAD has no v* tag; version={version}"
    if list(tags) != [expected]:
        actual = ", ".join(tags)
        raise ValueError(
            f"FAIL release-tag: HEAD tags [{actual}] do not match expected {expected}"
        )
    return f"PASS release-tag: {expected} matches version {version}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        message = check_release_tags(
            __version__, head_release_tags(args.repository.resolve())
        )
    except (RuntimeError, ValueError) as error:
        print(error)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
