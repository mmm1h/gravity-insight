from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOWLIST = (
    ROOT / "tests/fixtures/integrated_validation/capability_loss_allowlist.json"
)
CATEGORIES = (
    "public_api",
    "cli_commands",
    "journeys",
    "operations",
    "products",
)

_SNAPSHOT_PROBE = r'''
import argparse
import json
import pathlib
import sys
import tomllib

root = pathlib.Path(sys.argv[1]).resolve()
source = root / "src"
sys.path.insert(0, str(source))

import gravity_sdk
from gravity_sdk.cli import build_parser


def cli_commands(parser, prefix=()):
    subparsers = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    if not subparsers:
        return {" ".join(prefix)} if prefix else set()
    result = set()
    for action in subparsers:
        for name, child in action.choices.items():
            result.update(cli_commands(child, (*prefix, name)))
    return result


journeys = set()
products = set()
for path in (source / "gravity_sdk/contracts/journeys").glob("*.json"):
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("artifact_kind") != "journey":
        continue
    journeys.add(str(value["journey_id"]))
    for requirement in value.get("required_capabilities", []):
        if requirement.get("identity_kind") == "product":
            products.add("journey:" + str(requirement["selector"]))

operations = set()
for path in (source / "gravity_sdk/contracts/operations").glob("*.json"):
    value = json.loads(path.read_text(encoding="utf-8"))
    operation = value.get("operation", {})
    operation_id = operation.get("operation_id")
    if operation_id:
        operations.add(str(operation_id))

sql_catalog = source / "gravity_sdk/contracts/sql-products/catalog.json"
if sql_catalog.is_file():
    value = json.loads(sql_catalog.read_text(encoding="utf-8"))
    products.update("sql-kind:" + str(name) for name in value.get("product_kinds", {}))
for path in (root / "examples").rglob("*.toml"):
    value = tomllib.loads(path.read_text(encoding="utf-8"))
    products.update("workspace:" + str(name) for name in value.get("products", {}))

snapshot = {
    "public_api": sorted(str(name) for name in gravity_sdk.__all__),
    "cli_commands": sorted(cli_commands(build_parser())),
    "journeys": sorted(journeys),
    "operations": sorted(operations),
    "products": sorted(products),
}
print(json.dumps(snapshot, sort_keys=True))
'''


class CapabilityCheckError(RuntimeError):
    pass


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise CapabilityCheckError(
            f"git {' '.join(arguments)} failed: {completed.stderr.strip()}"
        )
    return completed.stdout.strip()


def resolve_revision(revision: str) -> str:
    return _git("rev-parse", "--verify", f"{revision}^{{commit}}")


def _extract_archive(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            path = PurePosixPath(item.filename)
            if path.is_absolute() or ".." in path.parts:
                raise CapabilityCheckError(
                    f"git archive contains unsafe path: {item.filename}"
                )
        bundle.extractall(destination)


def collect_revision_snapshot(revision: str) -> tuple[str, dict[str, list[str]]]:
    commit = resolve_revision(revision)
    with tempfile.TemporaryDirectory(prefix="gravity-capability-snapshot-") as raw:
        temporary = Path(raw)
        archive = temporary / "repository.zip"
        checkout = temporary / "repository"
        checkout.mkdir()
        completed = subprocess.run(
            ["git", "archive", "--format=zip", f"--output={archive}", commit],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise CapabilityCheckError(
                f"git archive {commit} failed: {completed.stderr.strip()}"
            )
        _extract_archive(archive, checkout)
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        probe = subprocess.run(
            [sys.executable, "-I", "-c", _SNAPSHOT_PROBE, str(checkout)],
            cwd=temporary,
            env=environment,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=120,
            check=False,
        )
        if probe.returncode != 0:
            raise CapabilityCheckError(
                f"capability probe failed for {commit}: {probe.stderr.strip()}"
            )
        try:
            snapshot = json.loads(probe.stdout)
        except json.JSONDecodeError as exc:
            raise CapabilityCheckError(
                f"capability probe returned invalid JSON for {commit}"
            ) from exc
    return commit, snapshot


def compare_capability_snapshots(
    base: Mapping[str, list[str]],
    head: Mapping[str, list[str]],
    allowlist: Mapping[str, Any],
) -> dict[str, Any]:
    errors: list[str] = []
    records: dict[tuple[str, str], Mapping[str, Any]] = {}
    raw_records = allowlist.get("allowed_losses", [])
    if not isinstance(raw_records, list):
        errors.append("allowed_losses must be an array")
        raw_records = []
    for index, record in enumerate(raw_records):
        if not isinstance(record, Mapping):
            errors.append(f"allowed_losses[{index}] must be an object")
            continue
        category = record.get("category")
        identifier = record.get("identifier")
        key = (str(category), str(identifier))
        if category not in CATEGORIES or not isinstance(identifier, str):
            errors.append(f"allowed_losses[{index}] has invalid identity")
        elif key in records:
            errors.append(f"duplicate allowed loss: {category}:{identifier}")
        else:
            records[key] = record

    comparisons: dict[str, Any] = {}
    actual_losses: set[tuple[str, str]] = set()
    unrecorded: list[dict[str, str]] = []
    unapproved: list[dict[str, str]] = []
    for category in CATEGORIES:
        before = set(base.get(category, []))
        after = set(head.get(category, []))
        removed = sorted(before - after)
        added = sorted(after - before)
        approved: list[str] = []
        for identifier in removed:
            key = (category, identifier)
            actual_losses.add(key)
            record = records.get(key)
            if record is None:
                unrecorded.append({"category": category, "identifier": identifier})
            elif (
                record.get("owner_review") == "approved"
                and isinstance(record.get("recorded_in"), str)
                and bool(record["recorded_in"])
            ):
                approved.append(identifier)
            else:
                unapproved.append({"category": category, "identifier": identifier})
        comparisons[category] = {
            "base_count": len(before),
            "head_count": len(after),
            "added": added,
            "removed": removed,
            "approved_losses": approved,
        }

    unused = [
        {"category": category, "identifier": identifier}
        for category, identifier in sorted(set(records) - actual_losses)
    ]
    passed = not errors and not unrecorded and not unapproved and not unused
    return {
        "passed": passed,
        "comparisons": comparisons,
        "unrecorded_losses": unrecorded,
        "unapproved_losses": unapproved,
        "unused_allowlist_records": unused,
        "structural_errors": errors,
    }


def check_cumulative_capabilities(
    base_revision: str,
    head_revision: str,
    allowlist_path: Path = DEFAULT_ALLOWLIST,
) -> dict[str, Any]:
    base_commit, base = collect_revision_snapshot(base_revision)
    head_commit, head = collect_revision_snapshot(head_revision)
    allowlist = json.loads(allowlist_path.read_text(encoding="utf-8"))
    result = compare_capability_snapshots(base, head, allowlist)
    return {
        "schema_version": "gravity.cumulative-capability-check.v1",
        "base_revision": base_revision,
        "base_commit": base_commit,
        "head_revision": head_revision,
        "head_commit": head_commit,
        **result,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reject cumulative unrecorded capability loss across Git revisions."
    )
    parser.add_argument("--base", default="main")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--allowlist", type=Path, default=DEFAULT_ALLOWLIST)
    args = parser.parse_args(argv)
    try:
        result = check_cumulative_capabilities(
            args.base, args.head, args.allowlist
        )
    except (CapabilityCheckError, json.JSONDecodeError, OSError, TypeError) as exc:
        print(f"cumulative capability check failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
