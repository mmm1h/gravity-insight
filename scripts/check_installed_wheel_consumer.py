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
    from scripts.build_offline_wheel import build_or_reuse_offline_wheel
except ModuleNotFoundError:
    from build_offline_wheel import build_or_reuse_offline_wheel


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONSUMER = ROOT.parent / "work-dashboard"
DEFAULT_REVISION = "64c08582690ac4bb2b04d3c3cd22a5716b1dc0f0"
STRICT_PREREQUISITES_ENV = "GRAVITY_REQUIRE_CANONICAL_CONSUMER"
CONSUMER_TESTS = (
    "tests.test_gravity_insight_adoption",
    "tests.test_r01_reference_journey_consumer",
)
CONSUMER_TEST_PROJECTIONS = (
    {
        "source_module": "tests.test_gravity_sdk_adoption",
        "target_module": "tests.test_gravity_insight_adoption",
        "default_source_sha256": "c072f16ff1eaf012c60bbfbd8b414a50d7bd01601230aaf895bc85ee7167a745",
        "replacements": (
            (
                "WORK_DASHBOARD_GRAVITY_SDK_ROOT",
                "WORK_DASHBOARD_GRAVITY_INSIGHT_ROOT",
                2,
            ),
            ('ROOT.parent / "gravity-sdk"', 'ROOT.parent / "gravity-insight"', 1),
            (
                "gravity-sdk sibling checkout or gravity executable is unavailable",
                "gravity-insight sibling checkout or gravity executable is unavailable",
                1,
            ),
            ("gravity_sdk", "gravity_insight", 4),
        ),
    },
    {
        "source_module": "tests.test_r01_reference_journey_consumer",
        "target_module": "tests.test_r01_reference_journey_consumer",
        "default_source_sha256": "6c2b762b629a4156127f7ab19639722c9ea94f2edbd2270f2a72f36901c08519",
        "replacements": (
            (
                "WORK_DASHBOARD_GRAVITY_SDK_ROOT",
                "WORK_DASHBOARD_GRAVITY_INSIGHT_ROOT",
                1,
            ),
            ('ROOT.parent / "gravity-sdk"', 'ROOT.parent / "gravity-insight"', 1),
            (
                "gravity-sdk source checkout is unavailable",
                "gravity-insight source checkout is unavailable",
                1,
            ),
            ("gravity_sdk", "gravity_insight", 1),
        ),
    },
)


class ConsumerCheckError(RuntimeError):
    pass


class ConsumerPrerequisiteError(ConsumerCheckError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


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


def _resolve_consumer_revision(consumer_repository: Path, revision: str) -> str:
    if not consumer_repository.is_dir():
        raise ConsumerPrerequisiteError(
            "consumer_repository_missing",
            "canonical consumer repository directory is unavailable: "
            f"{consumer_repository}",
        )
    repository_root = _run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=consumer_repository,
    )
    if repository_root.returncode != 0:
        detail = repository_root.stderr.strip() or (
            f"git exited {repository_root.returncode}"
        )
        raise ConsumerPrerequisiteError(
            "consumer_repository_not_git",
            "canonical consumer path is not a Git repository: "
            f"path={consumer_repository}; git_error={detail}",
        )
    # Both sides must be resolved before comparing: git reports the long form
    # while the caller's path can still carry a Windows 8.3 short name.
    discovered_root = Path(repository_root.stdout.strip()).resolve()
    if discovered_root != consumer_repository.resolve():
        raise ConsumerPrerequisiteError(
            "consumer_repository_not_git",
            "canonical consumer path is not a Git repository root: "
            f"path={consumer_repository}; discovered_root={discovered_root}",
        )
    resolved = _run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=consumer_repository,
    )
    if resolved.returncode != 0:
        detail = resolved.stderr.strip() or f"git exited {resolved.returncode}"
        raise ConsumerPrerequisiteError(
            "consumer_revision_unavailable",
            "canonical consumer revision is unavailable: "
            f"revision={revision}; git_error={detail}",
        )
    return resolved.stdout.strip()


def parse_unittest_summary(output: str) -> dict[str, int | bool | None]:
    count = re.search(r"Ran (\d+) tests?", output)
    skipped = re.search(r"skipped=(\d+)", output)
    return {
        "tests_run": int(count.group(1)) if count else None,
        "skipped": int(skipped.group(1)) if skipped else 0,
        "ok": bool(re.search(r"(?m)^OK(?: \(skipped=\d+\))?$", output)),
    }


def _containing_branches(consumer_repository: Path, commit: str) -> str:
    result = _run(
        [
            "git",
            "for-each-ref",
            "--sort=refname",
            "--format=%(refname:short)",
            f"--contains={commit}",
            "refs/heads",
            "refs/remotes",
        ],
        cwd=consumer_repository,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"git exited {result.returncode}"
        return f"<unavailable: {detail}>"
    return ", ".join(result.stdout.splitlines()) or "<none>"


def _require_revision_on_main(consumer_repository: Path, commit: str) -> str:
    main = _run(
        ["git", "rev-parse", "--verify", "refs/heads/main^{commit}"],
        cwd=consumer_repository,
    )
    if main.returncode != 0:
        detail = main.stderr.strip() or f"git exited {main.returncode}"
        raise ConsumerCheckError(
            "canonical consumer main branch is unavailable: "
            f"pinned_revision={commit}; "
            f"containing_branches={_containing_branches(consumer_repository, commit)}; "
            f"main_tip=<unavailable>; git_error={detail}"
        )
    main_tip = main.stdout.strip()
    ancestor = _run(
        ["git", "merge-base", "--is-ancestor", commit, main_tip],
        cwd=consumer_repository,
    )
    if ancestor.returncode == 0:
        return main_tip
    branches = _containing_branches(consumer_repository, commit)
    if ancestor.returncode == 1:
        raise ConsumerCheckError(
            "canonical consumer revision is not on main: "
            f"pinned_revision={commit}; containing_branches={branches}; "
            f"main_tip={main_tip}"
        )
    detail = ancestor.stderr.strip() or f"git exited {ancestor.returncode}"
    raise ConsumerCheckError(
        "canonical consumer main ancestry check failed: "
        f"pinned_revision={commit}; containing_branches={branches}; "
        f"main_tip={main_tip}; git_error={detail}"
    )


def _require_consumer_tests(consumer: Path, commit: str) -> None:
    missing = [
        (module, Path(*module.split(".")).with_suffix(".py"))
        for module in CONSUMER_TESTS
        if not (consumer / Path(*module.split(".")).with_suffix(".py")).is_file()
    ]
    if missing:
        detail = ", ".join(f"{module} ({path.as_posix()})" for module, path in missing)
        raise ConsumerCheckError(
            "canonical consumer test module(s) missing at pinned revision "
            f"{commit}: {detail}"
        )


def _module_path(root: Path, module: str) -> Path:
    return root / Path(*module.split(".")).with_suffix(".py")


def _project_consumer_tests(consumer: Path, commit: str) -> list[dict[str, Any]]:
    """Project the pinned consumer's live tests without mutating its repository."""

    receipts: list[dict[str, Any]] = []
    for specification in CONSUMER_TEST_PROJECTIONS:
        source_module = str(specification["source_module"])
        target_module = str(specification["target_module"])
        source = _module_path(consumer, source_module)
        target = _module_path(consumer, target_module)
        selected = target if target.is_file() and target != source else source
        if not selected.is_file():
            continue
        text = selected.read_text(encoding="utf-8")
        replacements = specification["replacements"]
        observed_counts = [text.count(old) for old, _new, _count in replacements]
        if not any(observed_counts):
            if "gravity_sdk" in text or "WORK_DASHBOARD_GRAVITY_SDK_ROOT" in text:
                raise ConsumerCheckError(
                    f"canonical consumer test has an ungoverned old package root: {target_module}"
                )
            receipts.append(
                {
                    "mode": "native_current_root",
                    "source_module": target_module,
                    "target_module": target_module,
                    "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                }
            )
            continue
        expected_counts = [count for _old, _new, count in replacements]
        if observed_counts != expected_counts:
            raise ConsumerCheckError(
                "canonical consumer package-root projection precondition drifted: "
                f"module={source_module}; expected_counts={expected_counts}; "
                f"observed_counts={observed_counts}"
            )
        source_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if (
            commit == DEFAULT_REVISION
            and source_sha256 != specification["default_source_sha256"]
        ):
            raise ConsumerCheckError(
                "canonical consumer package-root projection source digest drifted: "
                f"module={source_module}; sha256={source_sha256}"
            )
        rendered = text
        for old, new, _count in replacements:
            rendered = rendered.replace(old, new)
        if "gravity_sdk" in rendered or "WORK_DASHBOARD_GRAVITY_SDK_ROOT" in rendered:
            raise ConsumerCheckError(
                f"canonical consumer projection left an old package root: {source_module}"
            )
        target.write_text(rendered, encoding="utf-8", newline="\n")
        if source != target:
            source.unlink()
        receipts.append(
            {
                "mode": "exact_package_root_projection",
                "source_module": source_module,
                "target_module": target_module,
                "source_sha256": source_sha256,
                "target_sha256": hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
                "replacement_counts": expected_counts,
            }
        )
    return receipts


def check_installed_wheel_consumer(
    consumer_repository: Path = DEFAULT_CONSUMER,
    revision: str = DEFAULT_REVISION,
) -> dict[str, Any]:
    consumer_repository = consumer_repository.resolve()
    commit = _resolve_consumer_revision(consumer_repository, revision)
    _require_revision_on_main(consumer_repository, commit)
    with tempfile.TemporaryDirectory(prefix="gravity-canonical-consumer-") as raw:
        temporary = Path(raw).resolve()
        wheelhouse = temporary / "wheelhouse"
        sdk_root = temporary / "gravity-insight-wheel"
        site = sdk_root / "src"
        consumer = temporary / "work-dashboard"
        wheelhouse.mkdir()
        site.mkdir(parents=True)
        consumer.mkdir()
        wheel = build_or_reuse_offline_wheel(ROOT, wheelhouse)
        install_command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-index",
            "--no-deps",
        ]
        if sys.version_info >= (3, 13):
            install_command.append("--ignore-requires-python")
        install_command.extend(["--target", str(site), str(wheel)])
        installed = _run(install_command, cwd=temporary)
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
        consumer_test_projection = _project_consumer_tests(consumer, commit)
        _require_consumer_tests(consumer, commit)
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["GRAVITY_INSIGHT_AUTO_UPGRADE"] = "0"
        environment["WORK_DASHBOARD_GRAVITY_INSIGHT_ROOT"] = str(sdk_root)
        probe = _run(
            [
                sys.executable,
                "-I",
                "-c",
                "import pathlib,sys; sys.path.insert(0, sys.argv[1]); "
                "import gravity_insight; print(pathlib.Path(gravity_insight.__file__).resolve()); "
                "print(gravity_insight.__version__)",
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
            "schema_version": "gravity.installed-wheel-consumer-check.v2",
            "passed": tested.returncode == 0 and summary["ok"] is True,
            "exit_code": tested.returncode,
            "consumer_commit": commit,
            "consumer_tests": list(CONSUMER_TESTS),
            "consumer_test_projection": consumer_test_projection,
            "wheel": wheel.name,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "installed_package": str(package_path),
            "installed_version": lines[1],
            "summary": summary,
            "output": combined,
            "network_calls": 0,
        }


def _strict_prerequisites_from_environment() -> bool:
    raw = os.environ.get(STRICT_PREREQUISITES_ENV, "").strip().casefold()
    if raw in {"", "0", "false", "no", "off"}:
        return False
    if raw in {"1", "true", "yes", "on"}:
        return True
    raise ConsumerCheckError(
        f"{STRICT_PREREQUISITES_ENV} must be one of 1/0, true/false, "
        "yes/no, or on/off"
    )


def run_consumer_gate(
    consumer_repository: Path = DEFAULT_CONSUMER,
    revision: str = DEFAULT_REVISION,
    *,
    strict_prerequisites: bool | None = None,
) -> dict[str, Any]:
    strict = (
        _strict_prerequisites_from_environment()
        if strict_prerequisites is None
        else strict_prerequisites
    )
    try:
        check = check_installed_wheel_consumer(consumer_repository, revision)
    except ConsumerPrerequisiteError as exc:
        status = "fail" if strict else "skipped"
        return {
            "schema_version": "gravity.installed-wheel-consumer-gate.v1",
            "status": status,
            "passed": False,
            "exit_code": 2 if strict else 0,
            "strict_prerequisites": strict,
            "reason_code": exc.reason_code,
            "reason": str(exc),
            "consumer_repository": str(consumer_repository.resolve()),
            "revision": revision,
        }
    except (ConsumerCheckError, OSError, subprocess.SubprocessError) as exc:
        return {
            "schema_version": "gravity.installed-wheel-consumer-gate.v1",
            "status": "fail",
            "passed": False,
            "exit_code": 2,
            "strict_prerequisites": strict,
            "reason_code": "consumer_check_failed",
            "reason": str(exc),
            "consumer_repository": str(consumer_repository.resolve()),
            "revision": revision,
        }
    passed = check.get("passed") is True
    result = {
        "schema_version": "gravity.installed-wheel-consumer-gate.v1",
        "status": "pass" if passed else "fail",
        "passed": passed,
        "exit_code": 0 if passed else max(1, int(check.get("exit_code", 1))),
        "strict_prerequisites": strict,
        "consumer_repository": str(consumer_repository.resolve()),
        "revision": revision,
        "check": check,
    }
    if not passed:
        result.update(
            {
                "reason_code": "consumer_tests_failed",
                "reason": "canonical consumer tests did not pass",
            }
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the bound canonical consumer against an installed wheel."
    )
    parser.add_argument("--consumer-repository", type=Path, default=DEFAULT_CONSUMER)
    parser.add_argument("--revision", default=DEFAULT_REVISION)
    args = parser.parse_args(argv)
    try:
        result = run_consumer_gate(
            args.consumer_repository, args.revision
        )
    except ConsumerCheckError as exc:
        result = {
            "schema_version": "gravity.installed-wheel-consumer-gate.v1",
            "status": "fail",
            "passed": False,
            "exit_code": 2,
            "strict_prerequisites": True,
            "reason_code": "invalid_strict_prerequisites_setting",
            "reason": str(exc),
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
