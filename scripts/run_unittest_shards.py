"""Run the complete unittest discovery set across fail-closed worker shards."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, Sequence


ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
DEFAULT_MAX_WORKERS = 8
DEFAULT_SHARD_TIMEOUT_SECONDS = 600
MANIFEST_ENV = "GRAVITY_UNITTEST_SHARD_MANIFEST"
CAPTURE_ENV = "GRAVITY_UNITTEST_SHARD_CAPTURE"
MANIFEST_SCHEMA = "gravity.unittest-shard-manifest.v1"
SUMMARY_PATTERN = re.compile(r"(?m)^Ran (\d+) tests? in ([0-9.]+)s$")
OK_PATTERN = re.compile(r"(?m)^OK(?: \(skipped=\d+\))?$")


class ShardError(RuntimeError):
    """Raised when discovery or worker configuration cannot be trusted."""


@dataclass(frozen=True)
class DiscoveredTest:
    test_id: str
    ordinal: int


@dataclass(frozen=True)
class WorkerResult:
    index: int
    assigned_ids: tuple[str, ...]
    actual_ids: tuple[str, ...]
    exit_code: int
    reported_count: int | None
    runtime_seconds: float | None
    log_path: Path
    process_id: int | None
    timed_out: bool
    current_test_ids: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass
class _WorkerHandle:
    index: int
    assigned_ids: tuple[str, ...]
    process: subprocess.Popen[bytes] | None
    stream: BinaryIO
    started: float


def _flatten_suite(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _flatten_suite(item)
        else:
            yield item


def _discover_tests() -> tuple[DiscoveredTest, ...]:
    root_text = str(ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    # Preserve the repository's package-level private-cache isolation in both
    # discovery and workers, even if the alphabetically first test ever changes.
    import tests as test_package

    del test_package
    loader = unittest.TestLoader()
    suite = loader.discover(str(TESTS))
    if loader.errors:
        raise ShardError("unittest discovery errors:\n" + "\n".join(loader.errors))
    discovered = tuple(
        DiscoveredTest(test.id(), ordinal)
        for ordinal, test in enumerate(_flatten_suite(suite))
    )
    if not discovered:
        raise ShardError("unittest discovery returned zero tests")
    return discovered


def _choose_worker_count(
    *, cpu_count: int | None, max_workers: int, unit_count: int
) -> int:
    if max_workers < 1:
        raise ShardError("--max-workers must be at least 1")
    if unit_count < 1:
        raise ShardError("cannot shard an empty test set")
    available_cpus = max(1, cpu_count or 1)
    return min(available_cpus, max_workers, unit_count)


def _partition_tests(
    discovered: Sequence[DiscoveredTest], worker_count: int
) -> tuple[tuple[str, ...], ...]:
    """Distribute the stable discovery order round-robin across workers."""
    shards: list[list[str]] = [[] for _ in range(worker_count)]
    for test in discovered:
        shards[test.ordinal % worker_count].append(test.test_id)
    return tuple(
        tuple(shard) for shard in shards
    )


def _duplicates(values: Sequence[str]) -> list[str]:
    return sorted(value for value, count in Counter(values).items() if count != 1)


def _set_differences(
    expected: Sequence[str], observed: Sequence[str]
) -> tuple[list[str], list[str]]:
    return sorted(set(expected) - set(observed)), sorted(set(observed) - set(expected))


def _audit_partition(
    serial_ids: Sequence[str], shards: Sequence[Sequence[str]], expected_total: int
) -> list[str]:
    assigned_ids = [test_id for shard in shards for test_id in shard]
    missing, unexpected = _set_differences(serial_ids, assigned_ids)
    errors: list[str] = []
    serial_duplicates = _duplicates(serial_ids)
    assigned_duplicates = _duplicates(assigned_ids)
    if len(serial_ids) != expected_total:
        errors.append(
            "serial discovery total mismatch: "
            f"expected={expected_total} discovered={len(serial_ids)} "
            f"delta={len(serial_ids) - expected_total:+d}"
        )
    if serial_duplicates:
        errors.append(f"serial discovery contains duplicate ids: {serial_duplicates}")
    if len(assigned_ids) != expected_total:
        errors.append(
            "partition total mismatch: "
            f"expected={expected_total} assigned={len(assigned_ids)} "
            f"delta={len(assigned_ids) - expected_total:+d}"
        )
    if assigned_duplicates:
        errors.append(f"partition contains duplicate ids: {assigned_duplicates}")
    if missing or unexpected:
        errors.append(
            f"partition set mismatch: missing={missing} unexpected={unexpected}"
        )
    return errors


def _drop_negative_control(
    shards: Sequence[Sequence[str]], test_id: str
) -> tuple[tuple[str, ...], ...]:
    matches = sum(test_id in shard for shard in shards)
    if matches != 1:
        raise ShardError(
            f"negative-control id must occur exactly once: id={test_id!r} matches={matches}"
        )
    return tuple(
        tuple(value for value in shard if value != test_id) for shard in shards
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_ids(path: Path, values: Sequence[str]) -> None:
    path.write_text("".join(f"{value}\n" for value in values), encoding="utf-8")


def _ids_sha256(values: Sequence[str]) -> str:
    payload = "".join(f"{value}\n" for value in sorted(values)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _install_actual_id_capture(capture_path: Path) -> Callable[[str, str], None]:
    original_make_result = unittest.TextTestRunner._makeResult
    claimed = False
    stream = capture_path.open("w", encoding="utf-8", buffering=1)

    def record(event: str, test_id: str) -> None:
        stream.write(
            json.dumps(
                {"event": event, "test_id": test_id},
                ensure_ascii=False,
                sort_keys=True,
            )
            + "\n"
        )

    def make_result(runner: unittest.TextTestRunner) -> unittest.TestResult:
        nonlocal claimed
        result = original_make_result(runner)
        if claimed:
            return result
        claimed = True
        unittest.TextTestRunner._makeResult = original_make_result
        original_start_test = result.startTest
        original_stop_test = result.stopTest
        original_stop_test_run = result.stopTestRun

        def start_test(test: unittest.TestCase) -> None:
            record("started", test.id())
            original_start_test(test)

        def stop_test(test: unittest.TestCase) -> None:
            original_stop_test(test)
            record("completed", test.id())

        def stop_test_run() -> None:
            try:
                original_stop_test_run()
            finally:
                stream.close()

        result.startTest = start_test  # type: ignore[method-assign]
        result.stopTest = stop_test  # type: ignore[method-assign]
        result.stopTestRun = stop_test_run  # type: ignore[method-assign]
        return result

    unittest.TextTestRunner._makeResult = make_result
    return record


def _record_scheduled_tests(
    tests: Sequence[unittest.TestCase],
    *,
    record_progress: Callable[[str, str], None],
) -> None:
    for test in tests:
        original_run = test.run

        def scheduled_run(
            result: unittest.TestResult | None = None,
            *,
            run: object = original_run,
            test_id: str = test.id(),
        ) -> unittest.TestResult:
            record_progress("scheduled", test_id)
            return run(result)  # type: ignore[operator]

        test.run = scheduled_run  # type: ignore[method-assign]


def load_tests(
    loader: unittest.TestLoader,
    standard_tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    """Load one manifest when this module is invoked by ``python -m unittest``."""
    del standard_tests, pattern
    manifest_raw = os.environ.get(MANIFEST_ENV)
    capture_raw = os.environ.get(CAPTURE_ENV)
    if not manifest_raw or not capture_raw:
        raise ShardError(f"worker requires {MANIFEST_ENV} and {CAPTURE_ENV}")
    manifest = json.loads(Path(manifest_raw).read_text(encoding="utf-8"))
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ShardError("worker manifest schema is invalid")
    test_ids = manifest.get("test_ids")
    if not isinstance(test_ids, list) or not test_ids or not all(
        isinstance(value, str) and value for value in test_ids
    ):
        raise ShardError("worker manifest test_ids must be a non-empty string list")
    if _duplicates(test_ids):
        raise ShardError("worker manifest contains duplicate test ids")
    shard_index = manifest.get("shard_index")
    shard_count = manifest.get("shard_count")
    if not isinstance(shard_index, int) or not isinstance(shard_count, int) or not (
        1 <= shard_index <= shard_count
    ):
        raise ShardError("worker manifest shard index/count is invalid")
    tests_text = str(TESTS)
    if tests_text not in sys.path:
        sys.path.insert(0, tests_text)
    import tests as test_package

    del test_package
    record_progress = _install_actual_id_capture(Path(capture_raw))
    tests = list(_flatten_suite(loader.loadTestsFromNames(test_ids)))
    _record_scheduled_tests(
        tests,
        record_progress=record_progress,
    )
    return unittest.TestSuite(tests)


def _worker_environment(manifest: Path, capture: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.update(
        {
            "PYTHONNOUSERSITE": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "GRAVITY_SDK_AUTO_UPGRADE": "0",
            "HTTP_PROXY": "http://127.0.0.1:9",
            "HTTPS_PROXY": "http://127.0.0.1:9",
            "ALL_PROXY": "http://127.0.0.1:9",
            "NO_PROXY": "127.0.0.1,localhost",
            MANIFEST_ENV: str(manifest),
            CAPTURE_ENV: str(capture),
        }
    )
    return environment


def _read_actual_ids(
    path: Path,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if not path.is_file():
        return (), (), (f"actual-id capture is missing: {path}",)
    scheduled: list[str] = []
    started: list[str] = []
    completed: list[str] = []
    errors: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"actual-id capture line {number} is invalid JSON: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"actual-id capture line {number} is not an event object")
            continue
        event = value.get("event")
        test_id = value.get("test_id")
        if event not in {"scheduled", "started", "completed"} or not isinstance(
            test_id, str
        ) or not test_id:
            errors.append(f"actual-id capture line {number} has an invalid event")
            continue
        if event == "scheduled":
            scheduled.append(test_id)
        elif event == "started":
            started.append(test_id)
        else:
            completed.append(test_id)
    incomplete = Counter(scheduled)
    incomplete.subtract(completed)
    current = tuple(sorted(test_id for test_id, count in incomplete.items() if count > 0))
    if Counter(started) - Counter(scheduled):
        errors.append("actual-id capture contains a started test that was not scheduled")
    if Counter(completed) - Counter(started):
        errors.append("actual-id capture contains a completed test that was not started")
    return tuple(completed), current, tuple(errors)


def _collect_worker(
    *,
    index: int,
    assigned_ids: Sequence[str],
    exit_code: int,
    root: Path,
    process_id: int | None = None,
    timed_out: bool = False,
    timeout_seconds: int | None = None,
) -> WorkerResult:
    log_path = root / f"shard-{index:02d}.log"
    output = log_path.read_text(encoding="utf-8", errors="replace")
    summaries = SUMMARY_PATTERN.findall(output)
    reported_count = int(summaries[-1][0]) if summaries else None
    runtime_seconds = float(summaries[-1][1]) if summaries else None
    actual_ids, current_test_ids, capture_errors = _read_actual_ids(
        root / f"shard-{index:02d}.ids.jsonl"
    )
    errors = list(capture_errors)
    if timed_out:
        current = list(current_test_ids) or ["<no test scheduled or capture unavailable>"]
        errors.append(
            f"shard {index} timed out after {timeout_seconds}s without process "
            f"termination: pid={process_id} current_tests={current}"
        )
    if exit_code != 0:
        errors.append(f"shard {index} exited nonzero: exit={exit_code}")
    if reported_count is None:
        errors.append(f"shard {index} produced no parseable unittest summary")
    elif reported_count != len(assigned_ids):
        errors.append(
            f"shard {index} count mismatch: assigned={len(assigned_ids)} "
            f"reported={reported_count}"
        )
    if exit_code == 0 and not OK_PATTERN.search(output):
        errors.append(f"shard {index} exited zero without a unittest OK status")
    if len(actual_ids) != len(assigned_ids):
        errors.append(
            f"shard {index} actual-id count mismatch: assigned={len(assigned_ids)} "
            f"actual={len(actual_ids)}"
        )
    duplicates = _duplicates(actual_ids)
    if duplicates:
        errors.append(f"shard {index} executed duplicate ids: {duplicates}")
    missing, unexpected = _set_differences(assigned_ids, actual_ids)
    if missing or unexpected:
        errors.append(
            f"shard {index} actual-id set mismatch: missing={missing} "
            f"unexpected={unexpected}"
        )
    return WorkerResult(
        index=index,
        assigned_ids=tuple(assigned_ids),
        actual_ids=actual_ids,
        exit_code=exit_code,
        reported_count=reported_count,
        runtime_seconds=runtime_seconds,
        log_path=log_path,
        process_id=process_id,
        timed_out=timed_out,
        current_test_ids=current_test_ids,
        errors=tuple(errors),
    )


def _run_workers(
    shards: Sequence[Sequence[str]], root: Path, timeout_seconds: int
) -> tuple[WorkerResult, ...]:
    if timeout_seconds < 1:
        raise ShardError("--shard-timeout-seconds must be at least 1")
    launched: list[_WorkerHandle] = []
    for index, assigned_ids in enumerate(shards, 1):
        manifest = root / f"shard-{index:02d}.manifest.json"
        capture = root / f"shard-{index:02d}.ids.jsonl"
        log_path = root / f"shard-{index:02d}.log"
        _write_json(
            manifest,
            {
                "schema_version": MANIFEST_SCHEMA,
                "shard_index": index,
                "shard_count": len(shards),
                "test_ids": list(assigned_ids),
            },
        )
        stream = log_path.open("wb")
        try:
            process = subprocess.Popen(
                [sys.executable, "-m", "unittest", "-v", "scripts.run_unittest_shards"],
                cwd=ROOT,
                env=_worker_environment(manifest, capture),
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
        except OSError as exc:
            stream.write(f"worker spawn failed: {exc}\n".encode("utf-8"))
            process = None
        launched.append(
            _WorkerHandle(
                index=index,
                assigned_ids=tuple(assigned_ids),
                process=process,
                stream=stream,
                started=time.monotonic(),
            )
        )
    results: list[WorkerResult] = []
    pending = list(launched)
    while pending:
        now = time.monotonic()
        for handle in list(pending):
            exit_code = 127 if handle.process is None else handle.process.poll()
            timed_out = (
                exit_code is None and now - handle.started >= timeout_seconds
            )
            if exit_code is None and not timed_out:
                continue
            handle.stream.close()
            results.append(
                _collect_worker(
                    index=handle.index,
                    assigned_ids=handle.assigned_ids,
                    exit_code=124 if timed_out else int(exit_code),
                    root=root,
                    process_id=(handle.process.pid if handle.process is not None else None),
                    timed_out=timed_out,
                    timeout_seconds=timeout_seconds,
                )
            )
            pending.remove(handle)
        if pending:
            time.sleep(0.05)
    return tuple(sorted(results, key=lambda result: result.index))


def _audit_outcome(
    serial_ids: Sequence[str], results: Sequence[WorkerResult], expected_total: int
) -> list[str]:
    assigned_ids = [value for result in results for value in result.assigned_ids]
    actual_ids = [value for result in results for value in result.actual_ids]
    reported_total = sum(result.reported_count or 0 for result in results)
    errors = [error for result in results for error in result.errors]
    assigned_missing, assigned_unexpected = _set_differences(serial_ids, assigned_ids)
    actual_missing, actual_unexpected = _set_differences(serial_ids, actual_ids)
    assigned_duplicates = _duplicates(assigned_ids)
    actual_duplicates = _duplicates(actual_ids)
    if len(assigned_ids) != expected_total:
        errors.append(
            "assigned total conservation failed: "
            f"expected={expected_total} assigned={len(assigned_ids)} "
            f"delta={len(assigned_ids) - expected_total:+d}"
        )
    if reported_total != expected_total:
        errors.append(
            "Ran N total conservation failed: "
            f"expected={expected_total} reported={reported_total} "
            f"delta={reported_total - expected_total:+d}"
        )
    if len(actual_ids) != expected_total:
        errors.append(
            "actual-id total conservation failed: "
            f"expected={expected_total} actual={len(actual_ids)} "
            f"delta={len(actual_ids) - expected_total:+d}"
        )
    if assigned_duplicates:
        errors.append(f"assigned ids are duplicated: {assigned_duplicates}")
    if actual_duplicates:
        errors.append(f"actual ids are duplicated: {actual_duplicates}")
    if assigned_missing or assigned_unexpected:
        errors.append(
            "assigned ids differ from serial discovery: "
            f"missing={assigned_missing} unexpected={assigned_unexpected}"
        )
    if actual_missing or actual_unexpected:
        errors.append(
            "actual ids differ from serial discovery: "
            f"missing={actual_missing} unexpected={actual_unexpected}"
        )
    return errors


@contextmanager
def _evidence_workspace(requested: Path | None) -> Iterator[Path]:
    if requested is not None:
        root = requested if requested.is_absolute() else ROOT / requested
        if root.exists() and any(root.iterdir()):
            raise ShardError(f"evidence directory must be absent or empty: {root}")
        root.mkdir(parents=True, exist_ok=True)
        yield root.resolve()
        return
    temporary_parent = ROOT / "tmp"
    temporary_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="unittest-shards-", dir=temporary_parent
    ) as raw:
        yield Path(raw)


def _print_failed_worker_logs(results: Sequence[WorkerResult]) -> None:
    for result in results:
        if not result.errors:
            continue
        print(f"===== shard {result.index} full output =====", file=sys.stderr)
        print(
            result.log_path.read_text(encoding="utf-8", errors="replace"),
            file=sys.stderr,
            end="",
        )
        print(f"===== end shard {result.index} output =====", file=sys.stderr)


def _run(args: argparse.Namespace) -> int:
    started = time.monotonic()
    discovered = _discover_tests()
    serial_ids = [test.test_id for test in discovered]
    worker_count = args.workers or _choose_worker_count(
        cpu_count=os.cpu_count(),
        max_workers=args.max_workers,
        unit_count=len(discovered),
    )
    if worker_count < 1 or worker_count > min(args.max_workers, len(discovered)):
        raise ShardError(
            "--workers must be between 1 and "
            f"min(--max-workers, discovered tests) ({min(args.max_workers, len(discovered))})"
        )
    shards = _partition_tests(discovered, worker_count)
    partition_errors = _audit_partition(serial_ids, shards, args.expected_total)
    if partition_errors:
        raise ShardError("\n".join(partition_errors))
    dropped_id = args.negative_control_drop_id
    if dropped_id:
        shards = _drop_negative_control(shards, dropped_id)

    with _evidence_workspace(args.evidence_dir) as evidence_root:
        _write_ids(evidence_root / "serial-ids.txt", serial_ids)
        _write_ids(
            evidence_root / "assigned-ids.txt",
            [value for shard in shards for value in shard],
        )
        results = _run_workers(
            shards, evidence_root, timeout_seconds=args.shard_timeout_seconds
        )
        errors = _audit_outcome(serial_ids, results, args.expected_total)
        actual_ids = [value for result in results for value in result.actual_ids]
        reported_total = sum(result.reported_count or 0 for result in results)
        missing, unexpected = _set_differences(serial_ids, actual_ids)
        duplicate_actual_ids = _duplicates(actual_ids)
        wall_seconds = round(time.monotonic() - started, 3)
        _write_ids(evidence_root / "actual-ids.txt", sorted(actual_ids))
        summary = {
            "schema_version": "gravity.unittest-shard-result.v1",
            "status": "passed" if not errors else "failed",
            "expected_total": args.expected_total,
            "serial_discovered_total": len(serial_ids),
            "assigned_total": sum(len(shard) for shard in shards),
            "reported_ran_total": reported_total,
            "actual_id_total": len(actual_ids),
            "actual_unique_id_total": len(set(actual_ids)),
            "serial_id_sha256": _ids_sha256(serial_ids),
            "actual_id_sha256": _ids_sha256(actual_ids),
            "missing_ids": missing,
            "unexpected_ids": unexpected,
            "duplicate_actual_ids": duplicate_actual_ids,
            "cpu_count": os.cpu_count(),
            "max_workers": args.max_workers,
            "worker_count": worker_count,
            "shard_assigned_counts": [len(shard) for shard in shards],
            "shard_reported_counts": [result.reported_count for result in results],
            "shard_runtime_seconds": [result.runtime_seconds for result in results],
            "shard_timeout_seconds": args.shard_timeout_seconds,
            "timed_out_shards": [result.index for result in results if result.timed_out],
            "shard_current_test_ids": [
                list(result.current_test_ids) for result in results
            ],
            "negative_control_dropped_id": dropped_id,
            "errors": errors,
            "wall_seconds": wall_seconds,
            "worker_command": [
                sys.executable,
                "-m",
                "unittest",
                "-v",
                "scripts.run_unittest_shards",
            ],
        }
        _write_json(evidence_root / "summary.json", summary)
        if errors:
            _print_failed_worker_logs(results)
            for error in errors:
                print(f"ERROR: {error}", file=sys.stderr)
        else:
            for result in results:
                print(
                    f"shard {result.index}/{worker_count}: "
                    f"tests={result.reported_count} runtime={result.runtime_seconds}s"
                )
        print("-" * 70)
        print(f"Ran {reported_total} tests in {wall_seconds}s")
        print()
        print("OK" if not errors else f"FAILED (shard_integrity_errors={len(errors)})")
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if not errors else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Discover the complete unittest suite once, run deterministic "
            "worker shards with python -m unittest, and prove count/id conservation."
        )
    )
    parser.add_argument("--expected-total", type=int, required=True)
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS)
    parser.add_argument("--workers", type=int)
    parser.add_argument(
        "--shard-timeout-seconds",
        type=int,
        default=DEFAULT_SHARD_TIMEOUT_SECONDS,
    )
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument(
        "--negative-control-drop-id",
        help="Deliberately omit one discovered id; the run must fail conservation.",
    )
    args = parser.parse_args(argv)
    if args.expected_total < 1:
        parser.error("--expected-total must be at least 1")
    try:
        return _run(args)
    except (OSError, ShardError, ValueError, json.JSONDecodeError) as exc:
        print(f"unittest sharding failed closed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
