from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    from scripts.build_offline_wheel import build_offline_wheel
except ModuleNotFoundError:
    from build_offline_wheel import build_offline_wheel


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONSUMER = ROOT.parent / "work-dashboard"
DEFAULT_REVISION = "d1915a18278fca8823782a7d13e691a6d5702ad2"
CONSUMER_TESTS = (
    "tests.test_gravity_sdk_adoption",
    "tests.test_r01_reference_journey_consumer",
)


class ConsumerCheckError(RuntimeError):
    pass


def _run(
    command: list[str],
    *,
    cwd: Path,
    environment: dict[str, str] | None = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def parse_unittest_summary(output: str) -> dict[str, int | bool | None]:
    count = re.search(r"Ran (\d+) tests?", output)
    skipped = re.search(r"skipped=(\d+)", output)
    return {
        "tests_run": int(count.group(1)) if count else None,
        "skipped": int(skipped.group(1)) if skipped else 0,
        "ok": bool(re.search(r"(?m)^OK(?: \(skipped=\d+\))?$", output)),
    }


def check_installed_wheel_consumer(
    consumer_repository: Path = DEFAULT_CONSUMER,
    revision: str = DEFAULT_REVISION,
) -> dict[str, Any]:
    consumer_repository = consumer_repository.resolve()
    resolved = _run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=consumer_repository,
    )
    if resolved.returncode != 0:
        raise ConsumerCheckError(
            f"canonical consumer revision is unavailable: {resolved.stderr.strip()}"
        )
    commit = resolved.stdout.strip()
    with tempfile.TemporaryDirectory(prefix="gravity-canonical-consumer-") as raw:
        temporary = Path(raw).resolve()
        wheelhouse = temporary / "wheelhouse"
        sdk_root = temporary / "gravity-sdk-wheel"
        site = sdk_root / "src"
        consumer = temporary / "work-dashboard"
        wheelhouse.mkdir()
        site.mkdir(parents=True)
        consumer.mkdir()
        wheel = build_offline_wheel(ROOT, wheelhouse)
        installed = _run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--no-deps",
                "--target",
                str(site),
                str(wheel),
            ],
            cwd=temporary,
        )
        if installed.returncode != 0:
            raise ConsumerCheckError(
                f"offline wheel install failed: {installed.stdout}\n{installed.stderr}"
            )
        initialized = _run(["git", "init", "--quiet"], cwd=consumer)
        if initialized.returncode != 0:
            raise ConsumerCheckError(
                f"temporary consumer init failed: {initialized.stderr.strip()}"
            )
        fetched = _run(
            [
                "git",
                "-c",
                "protocol.file.allow=always",
                "fetch",
                "--quiet",
                "--no-tags",
                str(consumer_repository),
                commit,
            ],
            cwd=consumer,
        )
        if fetched.returncode != 0:
            raise ConsumerCheckError(
                f"canonical consumer fetch failed: {fetched.stderr.strip()}"
            )
        checked_out = _run(
            ["git", "checkout", "--quiet", "--detach", "FETCH_HEAD"],
            cwd=consumer,
        )
        if checked_out.returncode != 0:
            raise ConsumerCheckError(
                f"canonical consumer checkout failed: {checked_out.stderr.strip()}"
            )
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["GRAVITY_SDK_AUTO_UPGRADE"] = "0"
        environment["WORK_DASHBOARD_GRAVITY_SDK_ROOT"] = str(sdk_root)
        probe = _run(
            [
                sys.executable,
                "-I",
                "-c",
                "import pathlib,sys; sys.path.insert(0, sys.argv[1]); "
                "import gravity_sdk; print(pathlib.Path(gravity_sdk.__file__).resolve()); "
                "print(gravity_sdk.__version__)",
                str(site),
            ],
            cwd=temporary,
            environment=environment,
        )
        if probe.returncode != 0:
            raise ConsumerCheckError(
                f"installed wheel import failed: {probe.stdout}\n{probe.stderr}"
            )
        lines = probe.stdout.splitlines()
        package_path = Path(lines[0]).resolve()
        if not package_path.is_relative_to(site):
            raise ConsumerCheckError(f"installed import escaped wheel: {package_path}")
        tested = _run(
            [sys.executable, "-m", "unittest", *CONSUMER_TESTS],
            cwd=consumer,
            environment=environment,
            timeout=600,
        )
        combined = tested.stdout + tested.stderr
        summary = parse_unittest_summary(combined)
        return {
            "schema_version": "gravity.installed-wheel-consumer-check.v1",
            "passed": tested.returncode == 0 and summary["ok"] is True,
            "exit_code": tested.returncode,
            "consumer_commit": commit,
            "consumer_tests": list(CONSUMER_TESTS),
            "wheel": wheel.name,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "installed_package": str(package_path),
            "installed_version": lines[1],
            "summary": summary,
            "output": combined,
            "network_calls": 0,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the bound canonical consumer against an installed wheel."
    )
    parser.add_argument("--consumer-repository", type=Path, default=DEFAULT_CONSUMER)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    args = parser.parse_args(argv)
    try:
        result = check_installed_wheel_consumer(
            args.consumer_repository, args.revision
        )
    except (ConsumerCheckError, OSError, subprocess.SubprocessError) as exc:
        print(f"installed wheel consumer check failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
