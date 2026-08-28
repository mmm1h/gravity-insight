from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class StageRollback:
    stage: str
    baseline: str
    checkpoint: str
    retained_paths: tuple[str, ...]


STAGES = (
    StageRollback(
        stage="R12-A",
        baseline="3a47ce9f48902313c7898a0ab632c58d4c29259b",
        checkpoint="ba404f80498faae741d69efda3634204133cddda",
        retained_paths=(),
    ),
    StageRollback(
        stage="R12-B",
        baseline="7e6c190c4e527579ce772261b947c79c5dcb4d45",
        checkpoint="012d591574d27efd75e109fca18325e3261dc85c",
        retained_paths=(
            "src/gravity_sdk/action_plan.py",
            "tests/test_action_plan.py",
        ),
    ),
    StageRollback(
        stage="R12-C",
        baseline="50ada33b7d612a35fec99da46f63ffc16ff84def",
        checkpoint="d721074316c0aca7878051156d8f3a9d6429371b",
        retained_paths=(
            "src/gravity_sdk/action_plan.py",
            "src/gravity_sdk/receipt_facets.py",
            "tests/test_action_plan.py",
            "tests/test_receipt_facets.py",
        ),
    ),
)


class StageRollbackError(RuntimeError):
    pass


def _git(
    arguments: list[str],
    *,
    root: Path,
    env: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
) -> bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        env=env,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise StageRollbackError(
            f"git {' '.join(arguments)} failed with {result.returncode}: {detail}"
        )
    return result.stdout


def validate_stage_rollback(
    stage: StageRollback, *, root: Path = ROOT
) -> dict[str, object]:
    for revision in (stage.baseline, stage.checkpoint):
        resolved = _git(
            ["rev-parse", "--verify", f"{revision}^{{commit}}"], root=root
        ).decode("ascii").strip()
        if resolved != revision:
            raise StageRollbackError(
                f"{stage.stage} revision is not the expected full commit: {revision}"
            )

    _git(["merge-base", "--is-ancestor", stage.baseline, stage.checkpoint], root=root)
    baseline_tree = _git(
        ["rev-parse", f"{stage.baseline}^{{tree}}"], root=root
    ).decode("ascii").strip()
    checkpoint_tree = _git(
        ["rev-parse", f"{stage.checkpoint}^{{tree}}"], root=root
    ).decode("ascii").strip()
    if checkpoint_tree == baseline_tree:
        raise StageRollbackError(f"{stage.stage} checkpoint has no tree change")

    for path in stage.retained_paths:
        _git(["cat-file", "-e", f"{stage.baseline}:{path}"], root=root)

    rollback_patch = _git(
        [
            "diff",
            "--binary",
            "--full-index",
            "--no-renames",
            f"{stage.baseline}..{stage.checkpoint}",
        ],
        root=root,
    )
    if not rollback_patch:
        raise StageRollbackError(f"{stage.stage} rollback patch is empty")

    with tempfile.TemporaryDirectory(prefix="gravity-r12-rollback-") as temp:
        temporary_index = Path(temp) / "index"
        environment = os.environ.copy()
        environment["GIT_INDEX_FILE"] = str(temporary_index)
        _git(["read-tree", stage.checkpoint], root=root, env=environment)
        _git(
            ["apply", "--cached", "--reverse", "--check", "-"],
            root=root,
            env=environment,
            input_bytes=rollback_patch,
        )
        _git(
            ["apply", "--cached", "--reverse", "-"],
            root=root,
            env=environment,
            input_bytes=rollback_patch,
        )
        rolled_back_tree = _git(["write-tree"], root=root, env=environment).decode(
            "ascii"
        ).strip()

    if rolled_back_tree != baseline_tree:
        raise StageRollbackError(
            f"{stage.stage} rollback tree mismatch: "
            f"expected={baseline_tree} actual={rolled_back_tree}"
        )
    return {
        "stage": stage.stage,
        "baseline": stage.baseline,
        "checkpoint": stage.checkpoint,
        "baseline_tree": baseline_tree,
        "checkpoint_tree": checkpoint_tree,
        "rolled_back_tree": rolled_back_tree,
        "retained_paths": list(stage.retained_paths),
    }


def main() -> int:
    try:
        receipts = [validate_stage_rollback(stage) for stage in STAGES]
    except StageRollbackError as exc:
        print(f"R12 staged rollback validation failed: {exc}", file=sys.stderr)
        return 1
    for receipt in receipts:
        print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
