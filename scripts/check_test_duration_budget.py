"""Fail when one pytest item consumes too much of the CI job budget."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, TextIO

import pytest


ROOT = Path(__file__).resolve().parents[1]
CI_JOB_TIMEOUT_SECONDS = 20 * 60
# Calibration deliberately uses the slower environment instead of assuming
# local and CI item durations match. Three unchanged loadscope runs measured a
# 78.351s maximum, rounded up to 79s. Scaling by the supplied same-era suite
# ratio and a 25% scheduling reserve gives 79 * (716 / 364) * 1.25 = 194.24s.
# The immutable four-minute ceiling rounds that envelope to a whole minute and
# lets no item consume more than 20% of the real 20-minute CI job timeout.
OBSERVED_LOCAL_MAX_SECONDS = 79.0
HISTORICAL_LOCAL_SUITE_SECONDS = 364.0
HISTORICAL_CI_SUITE_SECONDS = 716.0
CI_VARIANCE_RESERVE = 1.25
CALIBRATED_CI_ENVELOPE_SECONDS = (
    OBSERVED_LOCAL_MAX_SECONDS
    * HISTORICAL_CI_SUITE_SECONDS
    / HISTORICAL_LOCAL_SUITE_SECONDS
    * CI_VARIANCE_RESERVE
)
TEST_DURATION_LIMIT_SECONDS = 4 * 60.0
MAX_SINGLE_TEST_JOB_SHARE = TEST_DURATION_LIMIT_SECONDS / CI_JOB_TIMEOUT_SECONDS
# Scope scheduling preserves parallelism without running a class's temporary
# repository mutations concurrently with that same class's repository scans.
PYTEST_ARGUMENTS = ("-q", "-n", "auto", "--dist", "loadscope")


@dataclass(frozen=True)
class DurationMeasurement:
    nodeid: str
    seconds: float


class DurationRecorder:
    """Collect phase timings reported by local or xdist pytest workers."""

    def __init__(self) -> None:
        self._seconds_by_nodeid: dict[str, float] = {}

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.when not in {"setup", "call", "teardown"}:
            return
        self._seconds_by_nodeid[report.nodeid] = (
            self._seconds_by_nodeid.get(report.nodeid, 0.0) + report.duration
        )

    def durations(self) -> tuple[DurationMeasurement, ...]:
        return tuple(
            DurationMeasurement(nodeid, seconds)
            for nodeid, seconds in sorted(
                self._seconds_by_nodeid.items(),
                key=lambda item: (-item[1], item[0]),
            )
        )


def duration_budget_errors(
    durations: Sequence[DurationMeasurement],
) -> tuple[str, ...]:
    return tuple(
        f"test={item.nodeid} duration={item.seconds:.3f}s "
        f"limit={TEST_DURATION_LIMIT_SECONDS:.3f}s; one test may consume at "
        f"most {MAX_SINGLE_TEST_JOB_SHARE:.2%} of the "
        f"{CI_JOB_TIMEOUT_SECONDS}s CI test-job timeout"
        for item in durations
        if item.seconds > TEST_DURATION_LIMIT_SECONDS
    )


def run_gate(
    targets: Sequence[str],
    *,
    pytest_runner: Callable[..., int | pytest.ExitCode] = pytest.main,
    stream: TextIO = sys.stdout,
) -> int:
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
        print(
            "test-duration-budget metrics: "
            f"measured_tests={len(durations)}, "
            f"max_test_duration={slowest.seconds:.3f}s, "
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

    errors = list(duration_budget_errors(durations))
    if exit_code != int(pytest.ExitCode.OK):
        errors.append(
            f"pytest exit_code={exit_code}; the duration gate requires a green collector"
        )
    if not durations:
        errors.append("pytest produced no per-test duration reports")
    if errors:
        for error in errors:
            print(f"FAIL P1 test-duration-budget: {error}", file=stream)
        return 1
    print(
        "PASS test-duration-budget: every test stayed within the immutable "
        f"{TEST_DURATION_LIMIT_SECONDS:.3f}s limit",
        file=stream,
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "targets",
        nargs="*",
        help="Optional pytest targets; the governed default is the complete tests directory.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return run_gate(args.targets)


if __name__ == "__main__":
    raise SystemExit(main())
