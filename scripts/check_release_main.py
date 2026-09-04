from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = "gravity.release-main-equivalence.v1"
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_TAG_RE = re.compile(r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)")


class ReleaseMainError(RuntimeError):
    """The release tag is not the exact protected-main commit."""


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ReleaseMainError(f"git {' '.join(arguments)} failed: {detail}")
    return completed.stdout.strip()


def _commit(root: Path, revision: str) -> str:
    value = _git(root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if _SHA_RE.fullmatch(value) is None:
        raise ReleaseMainError(f"{revision} did not resolve to a full commit SHA")
    return value


def check_release_main(
    *,
    root: Path,
    expected_sha: str,
    tag: str,
    main_ref: str,
    event_name: str,
    branch_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    root = root.resolve()
    if event_name != "push":
        raise ReleaseMainError(
            f"release publication requires a push event, got {event_name!r}"
        )
    if _SHA_RE.fullmatch(expected_sha) is None:
        raise ReleaseMainError("expected SHA must be a lowercase 40-character commit SHA")
    if _TAG_RE.fullmatch(tag) is None:
        raise ReleaseMainError(f"release tag must be vMAJOR.MINOR.PATCH, got {tag!r}")

    head = _commit(root, "HEAD")
    tag_commit = _commit(root, f"refs/tags/{tag}")
    main_commit = _commit(root, main_ref)
    api_commit = branch_metadata.get("commit")
    api_sha = api_commit.get("sha") if isinstance(api_commit, Mapping) else None
    if branch_metadata.get("name") != "main" or branch_metadata.get("protected") is not True:
        raise ReleaseMainError("GitHub branch metadata does not report protected main")
    observed = {
        "checked_out_head": head,
        "tag_commit": tag_commit,
        "main_commit": main_commit,
        "branch_api_commit": api_sha,
    }
    mismatched = {name: value for name, value in observed.items() if value != expected_sha}
    if mismatched:
        raise ReleaseMainError(
            "release commit is not identical across checkout, tag, and protected main: "
            f"expected={expected_sha}; mismatched={mismatched}"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "event_name": event_name,
        "release_tag": tag,
        "commit_sha": expected_sha,
        "protected_branch": "main",
        "branch_protected": True,
        "main_ref": main_ref,
        **observed,
    }


def _write_receipt(path: Path | None, receipt: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _load_branch_metadata(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseMainError(f"cannot read GitHub branch metadata at {path}") from exc
    if not isinstance(value, Mapping):
        raise ReleaseMainError("GitHub branch metadata must be a JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prove a release tag is the exact current protected-main commit."
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--main-ref", default="refs/remotes/origin/main")
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--branch-metadata", type=Path, required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        receipt = check_release_main(
            root=args.root,
            expected_sha=args.expected_sha,
            tag=args.tag,
            main_ref=args.main_ref,
            event_name=args.event_name,
            branch_metadata=_load_branch_metadata(args.branch_metadata),
        )
        _write_receipt(args.receipt, receipt)
    except (OSError, ReleaseMainError) as exc:
        print(f"FAIL release main equivalence: {exc}", file=sys.stderr)
        return 1
    print(
        "PASS release main equivalence: "
        f"tag={receipt['release_tag']} sha={receipt['commit_sha']} main_ref={receipt['main_ref']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
