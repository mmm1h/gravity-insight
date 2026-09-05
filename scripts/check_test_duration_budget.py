"""Fail when one pytest item consumes too much of the CI job budget."""

from __future__ import annotations

import argparse
import ast
import hashlib, json, os, subprocess, sys, tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

import pytest


ROOT = Path(__file__).resolve().parents[1]
QUALITY_BASELINE_PATH = ROOT / "src/gravity_insight/governance/quality-baseline.json"
# The ratchet opened once, from 8 to 9, when CI exposed the calibration bug.
# The ninth item remains because it reads the frozen and current repository
# module sets and loads both isolated implementations: independently of its
# duration, that is the marker's semantic repository-scan boundary. All nine
# current members are scans, builds, or isolated subprocess gates, so the
# calibration repair does not justify removing one.
MAX_FULL_GATE_TESTS = 9
MAX_LOCAL_FOCUSED_WALL_SECONDS = 100.0
MAX_SLOW_TEST_SECONDS = 40.0
# One measured coordinate transform owns every local/CI duration comparison.
# Keep the source measurements visible so a future recalibration must change a
# single ratio rather than independently opening policy thresholds.
HISTORICAL_LOCAL_SUITE_SECONDS = 364.0
HISTORICAL_CI_SUITE_SECONDS = 716.0
LOCAL_TO_CI_DURATION_RATIO = (
    HISTORICAL_CI_SUITE_SECONDS / HISTORICAL_LOCAL_SUITE_SECONDS
)


def _test_tier_baseline() -> dict[str, Any]:
    document = json.loads(QUALITY_BASELINE_PATH.read_text(encoding="utf-8"))
    tiers = document.get("test_tiers")
    required = {
        "full_gate_nodeids", "local_focused_wall_seconds", "slow_test_seconds",
    }
    if not isinstance(tiers, dict) or set(tiers) != required:
        raise ValueError(f"test_tiers must contain exactly {sorted(required)}")
    nodeids = tiers["full_gate_nodeids"]
    if (
        not isinstance(nodeids, list)
        or not nodeids
        or not all(isinstance(value, str) and value for value in nodeids)
        or len(nodeids) != len(set(nodeids))
    ):
        raise ValueError("test_tiers.full_gate_nodeids must be a non-empty unique list")
    for field in ("local_focused_wall_seconds", "slow_test_seconds"):
        if type(tiers[field]) not in {int, float} or tiers[field] <= 0:
            raise ValueError(f"test_tiers.{field} must be positive")
    if len(nodeids) > MAX_FULL_GATE_TESTS:
        raise ValueError(
            f"test_tiers.full_gate_nodeids exceeds its {MAX_FULL_GATE_TESTS}-item ratchet"
        )
    if tiers["local_focused_wall_seconds"] > MAX_LOCAL_FOCUSED_WALL_SECONDS:
        raise ValueError("test_tiers.local_focused_wall_seconds may not exceed 100")
    if tiers["slow_test_seconds"] > MAX_SLOW_TEST_SECONDS:
        raise ValueError("test_tiers.slow_test_seconds may not exceed 40")
    return tiers


_TEST_TIERS = _test_tier_baseline()
FULL_GATE_NODEIDS = tuple(_TEST_TIERS["full_gate_nodeids"])
LOCAL_FOCUSED_WALL_LIMIT_SECONDS = _TEST_TIERS["local_focused_wall_seconds"]
SLOW_TEST_LIMIT_SECONDS = _TEST_TIERS["slow_test_seconds"]
FULL_GATE_MARKER = "full_gate"
CI_JOB_TIMEOUT_SECONDS = 20 * 60
# Calibration deliberately uses the slower environment instead of assuming
# local and CI item durations match. Three unchanged loadscope runs measured a
# 78.351s maximum, rounded up to 79s. Scaling by the supplied same-era suite
# ratio and a 25% scheduling reserve gives 79 * (716 / 364) * 1.25 = 194.24s.
# The immutable four-minute ceiling rounds that envelope to a whole minute and
# lets no item consume more than 20% of the real 20-minute CI job timeout.
OBSERVED_LOCAL_MAX_SECONDS = 79.0
CI_VARIANCE_RESERVE = 1.25
CALIBRATED_CI_ENVELOPE_SECONDS = (
    OBSERVED_LOCAL_MAX_SECONDS
    * LOCAL_TO_CI_DURATION_RATIO
    * CI_VARIANCE_RESERVE
)
TEST_DURATION_LIMIT_SECONDS = 4 * 60.0
MAX_SINGLE_TEST_JOB_SHARE = TEST_DURATION_LIMIT_SECONDS / CI_JOB_TIMEOUT_SECONDS
# Match direct developer runs and integrated validation. Repository tree readers
# and writers still coordinate through the shared cross-process test gate.
PYTEST_ARGUMENTS = (
    "-q", "-o", "addopts=", "-n", "auto", "--dist", "loadfile",
)
PYTEST_COLLECTION_ARGUMENTS = (
    "--collect-only", "-q", "-o", "addopts=", "-n", "0",
)
SHARD_RECEIPT_SCHEMA = "gravity.pytest-shard-receipt.v1"
SHARD_AUDIT_SCHEMA = "gravity.pytest-shard-audit.v1"


@dataclass(frozen=True)
class DurationMeasurement:
    nodeid: str
    seconds: float
    full_gate: bool = False
    call_seconds: float | None = None

    @property
    def slow_test_seconds(self) -> float:
        """Time this test itself spent, excluding shared fixture setup.

        A class- or module-scoped fixture is billed by pytest to whichever test
        happens to trigger it, so the summed phases make the slow-test verdict
        depend on execution order. Two tests failed this gate on `main` at
        147.629s and 81.777s while measuring 0.04s and 1.74s of their own work;
        the rest was a shared setUpClass that a different sibling would have
        absorbed on the next run.
        """

        return self.seconds if self.call_seconds is None else self.call_seconds


class DurationRecorder:
    """Collect phase timings reported by local or xdist pytest workers."""

    def __init__(self) -> None:
        self._seconds_by_nodeid: dict[str, float] = {}
        self._call_seconds_by_nodeid: dict[str, float] = {}
        self._phase_counts: dict[tuple[str, str], int] = {}
        self._full_gate_nodeids: set[str] = set()

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.when not in {"setup", "call", "teardown"}:
            return
        key = (report.nodeid, report.when)
        self._phase_counts[key] = self._phase_counts.get(key, 0) + 1
        self._seconds_by_nodeid[report.nodeid] = (
            self._seconds_by_nodeid.get(report.nodeid, 0.0) + report.duration
        )
        if report.when == "call":
            self._call_seconds_by_nodeid[report.nodeid] = (
                self._call_seconds_by_nodeid.get(report.nodeid, 0.0) + report.duration
            )
        if FULL_GATE_MARKER in getattr(report, "keywords", {}):
            self._full_gate_nodeids.add(report.nodeid)

    def durations(self) -> tuple[DurationMeasurement, ...]:
        return tuple(
            DurationMeasurement(
                nodeid,
                seconds,
                nodeid in self._full_gate_nodeids,
                self._call_seconds_by_nodeid.get(nodeid),
            )
            for nodeid, seconds in sorted(
                self._seconds_by_nodeid.items(),
                key=lambda item: (-item[1], item[0]),
            )
        )

    def nodeids(self) -> tuple[str, ...]:
        return tuple(sorted(self._seconds_by_nodeid))

    def duplicate_items(self) -> tuple[str, ...]:
        return tuple(
            f"{nodeid} [setup] x{count}"
            for (nodeid, phase), count in sorted(self._phase_counts.items())
            if phase == "setup" and count != 1
        )


class CollectionRecorder:
    """Capture the exact item identities from one non-xdist collection."""

    def __init__(self) -> None:
        self.nodeids: tuple[str, ...] = ()

    def pytest_collection_finish(self, session: Any) -> None:
        self.nodeids = tuple(item.nodeid for item in session.items)


def declared_full_gate_nodeids(root: Path = ROOT) -> tuple[str, ...]:
    """Return method nodeids carrying the repository's full_gate marker."""

    marked: list[str] = []
    for path in sorted((root / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for owner in tree.body:
            if not isinstance(owner, ast.ClassDef):
                continue
            for member in owner.body:
                if not isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if any(
                    isinstance(decorator, ast.Attribute)
                    and decorator.attr == FULL_GATE_MARKER
                    for decorator in member.decorator_list
                ):
                    marked.append(f"tests/{path.name}::{owner.name}::{member.name}")
    return tuple(marked)


def _duplicates(values: Sequence[str]) -> tuple[str, ...]:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return tuple(sorted(value for value, count in counts.items() if count != 1))


def _nodeids_sha256(values: Sequence[str]) -> str:
    payload = "".join(f"{value}\n" for value in sorted(values)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def collect_nodeids(
    targets: Sequence[str],
    *,
    pytest_runner: Callable[..., int | pytest.ExitCode] = pytest.main,
) -> tuple[int, tuple[str, ...], tuple[str, ...]]:
    recorder = CollectionRecorder()
    exit_code = int(
        pytest_runner(
            [*PYTEST_COLLECTION_ARGUMENTS, *(targets or ("tests",))],
            plugins=[recorder],
        )
    )
    duplicates = _duplicates(recorder.nodeids)
    errors: list[str] = []
    if exit_code != int(pytest.ExitCode.OK):
        errors.append(f"pytest collection exit_code={exit_code}")
    if not recorder.nodeids:
        errors.append("pytest collection returned zero test items")
    if duplicates:
        errors.append(f"pytest collection contains duplicate nodeids: {duplicates}")
    return exit_code, recorder.nodeids, tuple(errors)


def partition_nodeids(
    nodeids: Sequence[str], shard_count: int
) -> tuple[tuple[str, ...], ...]:
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    if shard_count > len(nodeids):
        raise ValueError("shard_count cannot exceed the collected item count")
    ordered = sorted(nodeids)
    return tuple(tuple(ordered[index::shard_count]) for index in range(shard_count))


def _collect_in_subprocess(targets: Sequence[str]) -> tuple[str, ...]:
    temporary_parent = ROOT / "tmp"
    temporary_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="pytest-shard-collection-", dir=temporary_parent
    ) as raw:
        output = Path(raw) / "collection.json"
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--write-collection",
                str(output),
                *(targets or ("tests",)),
            ],
            cwd=ROOT,
            env=os.environ.copy(),
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0 or not output.is_file():
            detail = (completed.stdout + completed.stderr).strip()
            raise ValueError(f"pytest shard collection failed: {detail}")
        payload = json.loads(output.read_text(encoding="utf-8"))
    errors = payload.get("errors")
    nodeids = payload.get("nodeids")
    if errors or not isinstance(nodeids, list) or not all(
        isinstance(value, str) and value for value in nodeids
    ):
        raise ValueError(f"pytest shard collection receipt is invalid: {payload}")
    print(
        "pytest shard collection: "
        f"items={len(nodeids)} sha256={_nodeids_sha256(nodeids)}"
    )
    return tuple(nodeids)


def duration_budget_errors(
    durations: Sequence[DurationMeasurement],
    *,
    duration_coordinate: str | None = None,
) -> tuple[str, ...]:
    coordinate = duration_coordinate or active_duration_coordinate()
    errors: list[str] = []
    for item in durations:
        # The absolute ceiling stays on the summed phases: shared setup really
        # does consume the job budget, whoever is billed for it. The slow-test
        # threshold asks a different question -- is this test too slow for the
        # local Focused loop -- and that must not depend on which sibling
        # happened to trigger a class-scoped fixture first.
        local_seconds = local_equivalent_seconds(
            item.slow_test_seconds, duration_coordinate=coordinate
        )
        if item.seconds > TEST_DURATION_LIMIT_SECONDS:
            errors.append(
                f"test={item.nodeid} duration={item.seconds:.3f}s "
                f"limit={TEST_DURATION_LIMIT_SECONDS:.3f}s; one test may consume at "
                f"most {MAX_SINGLE_TEST_JOB_SHARE:.2%} of the "
                f"{CI_JOB_TIMEOUT_SECONDS}s CI test-job timeout"
            )
        elif local_seconds > SLOW_TEST_LIMIT_SECONDS and not item.full_gate:
            errors.append(
                f"test={item.nodeid} call={item.slow_test_seconds:.3f}s "
                f"phases_total={item.seconds:.3f}s "
                f"coordinate={coordinate} local_equivalent={local_seconds:.3f}s "
                f"exceeds local_slow_test_limit={SLOW_TEST_LIMIT_SECONDS:.3f}s without "
                f"@pytest.mark.{FULL_GATE_MARKER}"
            )
    return tuple(errors)


def active_duration_coordinate(
    environ: Mapping[str, str] | None = None,
) -> str:
    """Return the coordinate used by the current measured duration reports."""

    selected = os.environ if environ is None else environ
    return "ci" if selected.get("GITHUB_ACTIONS", "").casefold() == "true" else "local"


def local_equivalent_seconds(
    seconds: float, *, duration_coordinate: str
) -> float:
    """Normalize a measured duration before applying the local Focused policy."""

    if duration_coordinate == "local":
        return seconds
    if duration_coordinate == "ci":
        return seconds / LOCAL_TO_CI_DURATION_RATIO
    raise ValueError(f"unsupported duration coordinate: {duration_coordinate!r}")


def run_gate(
    targets: Sequence[str],
    *,
    pytest_runner: Callable[..., int | pytest.ExitCode] = pytest.main,
    stream: TextIO = sys.stdout,
    expected_nodeids: Sequence[str] = (),
    collected_nodeids: Sequence[str] = (),
    shard_index: int | None = None,
    shard_count: int | None = None,
    receipt: Path | None = None,
) -> int:
    duration_coordinate = active_duration_coordinate()
    recorder = DurationRecorder()
    exit_code = int(
        pytest_runner(
            [*PYTEST_ARGUMENTS, *(targets or ("tests",))],
            plugins=[recorder],
        )
    )
    durations = recorder.durations()
    if durations:
        slowest = durations[0]
        slowest_local_seconds = local_equivalent_seconds(
            slowest.seconds, duration_coordinate=duration_coordinate
        )
        print(
            "test-duration-budget metrics: "
            f"measured_tests={len(durations)}, "
            f"max_test_duration={slowest.seconds:.3f}s, "
            f"duration_coordinate={duration_coordinate}, "
            f"max_local_equivalent_duration={slowest_local_seconds:.3f}s, "
            f"limit={TEST_DURATION_LIMIT_SECONDS:.3f}s, "
            f"slowest={slowest.nodeid}",
            file=stream,
        )
    else:
        print(
            "test-duration-budget metrics: measured_tests=0, "
            f"limit={TEST_DURATION_LIMIT_SECONDS:.3f}s",
            file=stream,
        )

    actual_nodeids = recorder.nodeids()
    full_gate_nodeids = tuple(
        sorted(item.nodeid for item in durations if item.full_gate)
    )
    errors = list(
        duration_budget_errors(
            durations, duration_coordinate=duration_coordinate
        )
    )
    if exit_code != int(pytest.ExitCode.OK):
        errors.append(
            f"pytest exit_code={exit_code}; the duration gate requires a green collector"
        )
    if not durations:
        errors.append("pytest produced no per-test duration reports")
    if expected_nodeids:
        expected = set(expected_nodeids)
        actual = set(actual_nodeids)
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        if len(actual_nodeids) != len(expected_nodeids) or missing or unexpected:
            errors.append(
                "pytest executed nodeids differ from the assigned shard: "
                f"expected={len(expected_nodeids)} actual={len(actual_nodeids)} "
                f"missing={missing} unexpected={unexpected}"
            )
    duplicate_items = recorder.duplicate_items()
    if duplicate_items:
        errors.append(f"pytest repeated test items: {duplicate_items}")
    if not targets and shard_count is None and set(full_gate_nodeids) != set(FULL_GATE_NODEIDS):
        errors.append(
            "full_gate marker set differs from the quality baseline: "
            f"expected={sorted(FULL_GATE_NODEIDS)} actual={list(full_gate_nodeids)}"
        )
    if receipt is not None:
        slowest = durations[0] if durations else None
        _write_json(
            receipt,
            {
                "schema_version": SHARD_RECEIPT_SCHEMA,
                "status": "passed" if not errors else "failed",
                "shard_index": shard_index,
                "shard_count": shard_count,
                "collection_count": len(collected_nodeids),
                "collection_sha256": _nodeids_sha256(collected_nodeids),
                "collected_nodeids": sorted(collected_nodeids),
                "selected_count": len(expected_nodeids),
                "selected_sha256": _nodeids_sha256(expected_nodeids),
                "selected_nodeids": sorted(expected_nodeids),
                "actual_count": len(actual_nodeids),
                "actual_sha256": _nodeids_sha256(actual_nodeids),
                "actual_nodeids": list(actual_nodeids),
                "full_gate_nodeids": list(full_gate_nodeids),
                "max_test_duration_seconds": (
                    round(slowest.seconds, 6) if slowest is not None else None
                ),
                "slowest_nodeid": slowest.nodeid if slowest is not None else None,
                "duration_limit_seconds": TEST_DURATION_LIMIT_SECONDS,
                "duration_coordinate": duration_coordinate,
                "local_to_ci_duration_ratio": LOCAL_TO_CI_DURATION_RATIO,
                "local_slow_test_limit_seconds": SLOW_TEST_LIMIT_SECONDS,
                "pytest_exit_code": exit_code,
                "duplicate_items": list(duplicate_items),
                "errors": errors,
            },
        )
    if errors:
        for error in errors:
            print(f"FAIL P1 test-duration-budget: {error}", file=stream)
        return 1
    print(
        "PASS test-duration-budget: every test stayed within the immutable "
        f"{TEST_DURATION_LIMIT_SECONDS:.3f}s limit; tests above "
        f"{SLOW_TEST_LIMIT_SECONDS:.3f}s local-equivalent were in the "
        f"full_gate tier (coordinate={duration_coordinate})",
        file=stream,
    )
    return 0


def _string_list(payload: dict[str, Any], key: str) -> tuple[str, ...] | None:
    value = payload.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        return None
    return tuple(value)


def audit_shard_receipts(
    receipt_root: Path,
    expected_shards: int,
    *,
    expected_full_gate_nodeids: Sequence[str] = FULL_GATE_NODEIDS,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    if expected_shards < 1:
        raise ValueError("expected_shards must be at least 1")
    paths = sorted(receipt_root.rglob("pytest-shard-*.json"))
    errors: list[str] = []
    payloads: dict[int, dict[str, Any]] = {}
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"cannot read shard receipt {path}: {exc}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"shard receipt is not an object: {path}")
            continue
        if payload.get("schema_version") != SHARD_RECEIPT_SCHEMA:
            errors.append(f"shard receipt schema is invalid: {path}")
            continue
        if payload.get("duration_coordinate") != "ci":
            errors.append(f"shard receipt duration coordinate is not ci: {path}")
        if payload.get("local_to_ci_duration_ratio") != LOCAL_TO_CI_DURATION_RATIO:
            errors.append(f"shard receipt duration ratio is stale: {path}")
        if payload.get("local_slow_test_limit_seconds") != SLOW_TEST_LIMIT_SECONDS:
            errors.append(f"shard receipt local slow-test limit is stale: {path}")
        index = payload.get("shard_index")
        if not isinstance(index, int) or not 1 <= index <= expected_shards:
            errors.append(f"shard receipt index is invalid: {path}: {index!r}")
            continue
        if index in payloads:
            errors.append(f"duplicate receipt for shard {index}: {path}")
            continue
        payloads[index] = payload

    expected_indices = set(range(1, expected_shards + 1))
    missing_indices = sorted(expected_indices - set(payloads))
    unexpected_indices = sorted(set(payloads) - expected_indices)
    if missing_indices or unexpected_indices:
        errors.append(
            "shard receipt index set mismatch: "
            f"missing={missing_indices} unexpected={unexpected_indices}"
        )

    canonical: tuple[str, ...] = ()
    selected_by_index: dict[int, tuple[str, ...]] = {}
    actual_by_index: dict[int, tuple[str, ...]] = {}
    full_gate_by_index: dict[int, tuple[str, ...]] = {}
    for index, payload in sorted(payloads.items()):
        collected = _string_list(payload, "collected_nodeids")
        selected = _string_list(payload, "selected_nodeids")
        actual = _string_list(payload, "actual_nodeids")
        full_gate = _string_list(payload, "full_gate_nodeids")
        if collected is None or selected is None or actual is None or full_gate is None:
            errors.append(f"shard {index} receipt has an invalid nodeid list")
            continue
        if payload.get("shard_count") != expected_shards:
            errors.append(
                f"shard {index} count mismatch: "
                f"expected={expected_shards} actual={payload.get('shard_count')!r}"
            )
        if payload.get("status") != "passed" or payload.get("errors"):
            errors.append(f"shard {index} did not produce a clean passing receipt")
        if _duplicates(collected):
            errors.append(f"shard {index} collected duplicate nodeids")
        if not canonical:
            canonical = collected
        elif collected != canonical:
            errors.append(f"shard {index} collection differs from shard 1")
        selected_by_index[index] = selected
        actual_by_index[index] = actual
        full_gate_by_index[index] = full_gate

    if canonical and len(payloads) == expected_shards:
        expected_partitions = partition_nodeids(canonical, expected_shards)
        for index, expected in enumerate(expected_partitions, 1):
            selected = selected_by_index.get(index, ())
            actual = actual_by_index.get(index, ())
            if selected != expected:
                missing = sorted(set(expected) - set(selected))
                unexpected = sorted(set(selected) - set(expected))
                errors.append(
                    f"shard {index} partition mismatch: "
                    f"missing={missing} unexpected={unexpected}"
                )
            if actual != selected:
                missing = sorted(set(selected) - set(actual))
                unexpected = sorted(set(actual) - set(selected))
                errors.append(
                    f"shard {index} execution mismatch: "
                    f"missing={missing} unexpected={unexpected}"
                )

        selected_all = [
            nodeid
            for index in sorted(selected_by_index)
            for nodeid in selected_by_index[index]
        ]
        actual_all = [
            nodeid
            for index in sorted(actual_by_index)
            for nodeid in actual_by_index[index]
        ]
        for label, observed in (("selected", selected_all), ("actual", actual_all)):
            missing = sorted(set(canonical) - set(observed))
            unexpected = sorted(set(observed) - set(canonical))
            duplicates = _duplicates(observed)
            if len(observed) != len(canonical) or missing or unexpected or duplicates:
                errors.append(
                    f"{label} union does not conserve the full collection: "
                    f"collection={len(canonical)} {label}={len(observed)} "
                    f"missing={missing} unexpected={unexpected} "
                    f"duplicates={list(duplicates)}"
                )
        marked_all = sorted(
            nodeid
            for index in sorted(full_gate_by_index)
            for nodeid in full_gate_by_index[index]
        )
        if set(marked_all) != set(expected_full_gate_nodeids):
            errors.append(
                "full_gate marker union differs from the quality baseline: "
                f"expected={sorted(expected_full_gate_nodeids)} actual={marked_all}"
            )

    summary = {
        "schema_version": SHARD_AUDIT_SCHEMA,
        "status": "passed" if not errors else "failed",
        "expected_shards": expected_shards,
        "receipt_count": len(payloads),
        "collection_count": len(canonical),
        "collection_sha256": _nodeids_sha256(canonical),
        "selected_total": sum(len(value) for value in selected_by_index.values()),
        "actual_total": sum(len(value) for value in actual_by_index.values()),
        "full_gate_total": sum(len(value) for value in full_gate_by_index.values()),
        "duration_coordinate": "ci",
        "local_to_ci_duration_ratio": LOCAL_TO_CI_DURATION_RATIO,
        "local_slow_test_limit_seconds": SLOW_TEST_LIMIT_SECONDS,
        "shard_selected_counts": {
            str(index): len(value) for index, value in sorted(selected_by_index.items())
        },
        "errors": errors,
    }
    return summary, tuple(errors)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard-index", type=int)
    parser.add_argument("--shard-count", type=int)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--audit-receipts", type=Path)
    parser.add_argument("--expected-shards", type=int)
    parser.add_argument("--audit-output", type=Path)
    parser.add_argument("--write-collection", type=Path, help=argparse.SUPPRESS)
    parser.add_argument(
        "targets",
        nargs="*",
        help="Optional pytest targets; the governed default is the complete tests directory.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.write_collection is not None:
        exit_code, nodeids, errors = collect_nodeids(args.targets)
        _write_json(
            args.write_collection,
            {
                "pytest_exit_code": exit_code,
                "nodeid_count": len(nodeids),
                "nodeids_sha256": _nodeids_sha256(nodeids),
                "nodeids": list(nodeids),
                "errors": list(errors),
            },
        )
        return 1 if errors else 0

    if args.audit_receipts is not None:
        if args.expected_shards is None or args.audit_output is None:
            print(
                "--audit-receipts requires --expected-shards and --audit-output",
                file=sys.stderr,
            )
            return 2
        try:
            summary, errors = audit_shard_receipts(
                args.audit_receipts.resolve(), args.expected_shards
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"pytest shard audit failed closed: {exc}", file=sys.stderr)
            return 2
        _write_json(args.audit_output, summary)
        if errors:
            for error in errors:
                print(f"FAIL pytest-shard-audit: {error}", file=sys.stderr)
            return 1
        print(
            "PASS pytest-shard-audit: "
            f"shards={summary['receipt_count']} "
            f"collected={summary['collection_count']} "
            f"selected={summary['selected_total']} actual={summary['actual_total']} "
            f"sha256={summary['collection_sha256']}"
        )
        return 0

    shard_options = (args.shard_index, args.shard_count, args.receipt)
    if any(value is not None for value in shard_options):
        if any(value is None for value in shard_options):
            print(
                "sharded runs require --shard-index, --shard-count, and --receipt",
                file=sys.stderr,
            )
            return 2
        assert args.shard_index is not None
        assert args.shard_count is not None
        assert args.receipt is not None
        if not 1 <= args.shard_index <= args.shard_count:
            print("--shard-index must be between 1 and --shard-count", file=sys.stderr)
            return 2
        try:
            collected = _collect_in_subprocess(args.targets)
            partitions = partition_nodeids(collected, args.shard_count)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"pytest sharding failed closed: {exc}", file=sys.stderr)
            return 2
        selected = partitions[args.shard_index - 1]
        print(
            f"pytest shard {args.shard_index}/{args.shard_count}: "
            f"selected={len(selected)} sha256={_nodeids_sha256(selected)}"
        )
        return run_gate(
            selected,
            expected_nodeids=selected,
            collected_nodeids=collected,
            shard_index=args.shard_index,
            shard_count=args.shard_count,
            receipt=args.receipt,
        )

    return run_gate(args.targets)


if __name__ == "__main__":
    raise SystemExit(main())
