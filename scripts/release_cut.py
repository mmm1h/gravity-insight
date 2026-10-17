"""Resumable release cut; local transforms also serve the manual fallback."""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import tomllib
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SEMVER = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
PREP_FILES = {
    "CHANGELOG.md", "scripts/changelog_release_lock.json",
    "src/gravity_insight/contracts/generated/release-compatibility.v1.json",
    "src/gravity_insight/contracts/generated/repository-map.v2.json",
    "tests/fixtures/agent_module_reference_checkpoint.json",
}


class CutError(ValueError):
    """Unsafe or incomplete release state."""


def next_version(version: str) -> str:
    if re.fullmatch(SEMVER, version) is None:
        raise CutError("version must be a three-part SemVer")
    major, minor, patch = map(int, version.split("."))
    return f"{major}.{minor}.{patch + 1}"


def project_version(text: str) -> str:
    version = tomllib.loads(text)["project"]["version"]
    next_version(version)
    return version


def require_version(actual: str, requested: str) -> str:
    if requested and requested != actual:
        raise CutError(f"requested version {requested} differs from main version {actual}")
    return actual


def prepare_changelog(text: str, version: str, release_date: str) -> str:
    if date.fromisoformat(release_date).isoformat() != release_date:
        raise CutError("date must be YYYY-MM-DD")
    following = next_version(version)
    match = re.search(r"^## \[Unreleased\]\n(.*?)(?=^## \[|\Z)", text, re.M | re.S)
    if not match:
        raise CutError("missing Unreleased section")
    body = match[1]
    targets = re.findall(r"^Target release: `([^`]+)`$", body, re.M)
    if targets != [version]:
        raise CutError(f"Target release must equal {version}")
    if re.search(rf"^## \[{re.escape(version)}\]", text, re.M):
        raise CutError("version already has a dated release section")
    body = re.sub(r"^Target release: `[^`]+`\n", "", body, flags=re.M).strip()
    meaningful = [line.strip() for line in body.splitlines()
                  if line.strip() and not line.startswith("### ") and line.strip() != "- None."]
    if not meaningful:
        raise CutError("refusing empty release")
    replacement = (f"## [Unreleased]\n\nTarget release: `{following}`\n\n"
                   f"### Breaking changes\n\n- None.\n\n"
                   f"## [{version}] - {release_date}\n\n{body}\n\n")
    return text[:match.start()] + replacement + text[match.end():]


def open_train_text(text: str, changelog: str, version: str) -> str:
    following = next_version(version)
    if project_version(text) != version:
        raise CutError("train base version differs from release")
    target = re.search(r"^Target release: `([^`]+)`$", changelog, re.M)
    if not target or target[1] != following:
        raise CutError("train version differs from changelog target")
    # Restrict the edit to the project table, not other version keys.
    match = re.search(r"^\[project\]\n(.*?)(?=^\[|\Z)", text, re.M | re.S)
    if not match:
        raise CutError("missing project table")
    body, count = re.subn(r'^version[ \t]*=[ \t]*"' + re.escape(version) + r'"[ \t]*$',
                         f'version = "{following}"', match[1], flags=re.M)
    if count != 1:
        raise CutError("expected exactly one project version line")
    return text[:match.start(1)] + body + text[match.end(1):]


def detect_stage(main: str, prep: str | None, train: str | None,
                 tag: str | None, base: str | None) -> str:
    if tag and tag != prep:
        raise CutError("release tag exists elsewhere; never move or replace it")
    if train and main == train:
        if not tag:
            raise CutError("train on main without release tag")
        return "done"
    if train and not tag:
        raise CutError("train exists before release tag")
    if prep and main == prep:
        return "open-train" if tag else "tag"
    if tag:
        raise CutError("main moved after tag; nothing may land between tag and train")
    if prep:
        if main != base:
            raise CutError("main moved from candidate base; refusing stale promotion")
        return "promote"
    return "prepare"


class Repository:
    def __init__(self, root: Path = ROOT):
        self.root = root

    def run(self, *command: str, timeout: int = 600) -> str:
        if not command or command[0] != "gh":
            raise CutError("Actions runner only accepts gh")
        result = subprocess.run(
            ["gh", *command[1:]], cwd=self.root, check=True, capture_output=True,
            encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=timeout,
        )
        return result.stdout.strip()

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True,
            encoding="utf-8", timeout=600,
        ).stdout.strip()

    def python(self, *args: str) -> str:
        if args[0] == "-m":
            return subprocess.run(
                [sys.executable, "-m", *args[1:]], cwd=self.root, check=True,
                capture_output=True, encoding="utf-8",
                env={**os.environ, "PYTHONIOENCODING": "utf-8"}, timeout=600,
            ).stdout.strip()
        return subprocess.run(
            [sys.executable, "--", *args], cwd=self.root, check=True, capture_output=True,
            encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            timeout=600,
        ).stdout.strip()

    def read(self, path: str) -> str:
        return (self.root / path).read_text(encoding="utf-8")

    def write(self, path: str, text: str) -> None:
        (self.root / path).write_text(text, encoding="utf-8", newline="\n")

    def ref(self, ref: str) -> str | None:
        # Missing refs are ordinary state; transport/errors are not swallowed.
        exists = self.git("for-each-ref", "--format=%(refname)", ref).splitlines()
        return self.git("rev-parse", ref + "^{commit}") if ref in exists else None

    def refresh(self) -> str:
        self.git("fetch", "--prune", "--tags", "origin",
                 "+refs/heads/*:refs/remotes/origin/*")
        return self.git("rev-parse", "refs/remotes/origin/main")

    def prepare(self, version: str, release_date: str) -> None:
        require_version(project_version(self.read("pyproject.toml")), version)
        if self.ref(f"refs/tags/v{version}"):
            raise CutError("refusing prepare: release tag already exists")
        self.prepare_files(version, release_date)

    def prepare_files(self, version: str, release_date: str) -> None:
        self.python("scripts/check_changelog.py")  # Check all old locks before edits.
        self.write("CHANGELOG.md", prepare_changelog(self.read("CHANGELOG.md"), version, release_date))
        digests = json.loads(self.python("scripts/check_changelog.py", "--print-digests"))
        lock = json.loads(self.read("scripts/changelog_release_lock.json"))
        if version in lock["sections"]:
            raise CutError("new digest must not replace an existing lock")
        if {k: v for k, v in digests.items() if k != version} != lock["sections"]:
            raise CutError("old release digests changed")
        lock["sections"][version] = digests[version]
        self.write("scripts/changelog_release_lock.json", json.dumps(lock, indent=2) + "\n")
        self.python("scripts/generate_release_compatibility.py")
        self.python("scripts/refresh_validation_harnesses.py")

    def train(self, version: str) -> None:
        self.write("pyproject.toml", open_train_text(self.read("pyproject.toml"),
                                                    self.read("CHANGELOG.md"), version))

    def checks(self) -> None:
        # Editable metadata must reflect a freshly bumped pyproject version.
        self.python("-m", "pip", "install", "--no-deps", "--no-build-isolation", "-e", ".")
        for script in ("check_changelog.py", "generate_release_compatibility.py",
                       "refresh_validation_harnesses.py", "check_release_tag.py"):
            args = ("--check",) if script.startswith(("generate_", "refresh_")) else ()
            print(self.python(f"scripts/{script}", *args), flush=True)
        print(self.python("-m", "gravity_insight.compiler", "check"), flush=True)
        self.git("diff", "--check")

    def commit(self, stage: str, version: str, release_date: str = "") -> str:
        allowed = PREP_FILES if stage == "prepare" else {"pyproject.toml"}
        changed = set(self.git("diff", "--name-only").splitlines())
        if not changed or not changed <= allowed:
            raise CutError(f"unexpected {stage} files: {sorted(changed)}")
        self.git("add", "--", *sorted(changed))
        self.git("-c", "user.name=github-actions[bot]", "-c",
                 "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                 "commit", "-m", f"Release cut: {stage} {version}",
                 "-m", f"Release-Cut-Date: {release_date}")
        return self.git("rev-parse", "HEAD")

    def validate_candidate(self, sha: str, stage: str, version: str, base: str) -> None:
        parents = self.git("rev-list", "--parents", "-n", "1", sha).split()
        if parents != [sha, base]:
            raise CutError("candidate must have exactly the expected single parent")
        message = self.git("show", "-s", "--format=%B", sha)
        if message.splitlines()[0] != f"Release cut: {stage} {version}":
            raise CutError("unrecognized release candidate")
        self.git("checkout", "--detach", base)
        try:
            if stage == "prepare":
                stamp = re.search(r"^Release-Cut-Date: (\d{4}-\d{2}-\d{2})$", message, re.M)
                if not stamp:
                    raise CutError("candidate missing release date")
                self.prepare_files(version, stamp[1])
            else:
                self.train(version)
            self.git("add", "--update")
            if self.git("write-tree") != self.git("rev-parse", sha + "^{tree}"):
                raise CutError("candidate tree differs from deterministic generated release")
        finally:
            self.git("reset", "--hard", base)
            self.git("checkout", "--detach", sha)


class Actions:
    def __init__(self, repo: Repository):
        self.repo = repo
        self.slug = os.environ["GITHUB_REPOSITORY"]

    def api(self, path: str, *args: str):
        return json.loads(self.repo.run("gh", "api", "--method", "GET",
                                        f"repos/{self.slug}/{path}", *args))

    def find(self, workflow: str, branch: str, sha: str, event: str):
        runs = self.api(f"actions/workflows/{workflow}/runs", "-f", f"head_sha={sha}",
                        "-f", f"branch={branch}", "-f", f"event={event}",
                        "-f", "per_page=100")["workflow_runs"]
        matches = [run for run in runs if run["head_sha"] == sha
                   and run["head_branch"] == branch and run["event"] == event]
        return max(matches, key=lambda run: run["id"]) if matches else None

    def wait(self, workflow: str, branch: str, sha: str, event: str,
             *, dispatch: bool = False) -> str:
        run = self.find(workflow, branch, sha, event)
        if run is None and dispatch:
            self.repo.run("gh", "workflow", "run", workflow, "--repo", self.slug,
                          "--ref", branch)
        for _ in range(20):
            if run is not None:
                break
            time.sleep(30)
            run = self.find(workflow, branch, sha, event)
        if run is None:
            raise CutError(f"no {workflow} {event} run for {branch}@{sha} after 10 minutes")
        if run["status"] != "completed":
            self.repo.run("gh", "run", "watch", str(run["id"]), "--repo", self.slug,
                          "--interval", "30", "--exit-status", timeout=5400)
        current = self.api(f"actions/runs/{run['id']}")
        if (current["head_sha"], current["head_branch"], current["event"],
                current["status"], current["conclusion"]) != (sha, branch, event, "completed", "success"):
            raise CutError(f"run not successful: {current['html_url']}; rerun failed jobs then retry cut")
        if workflow == "ci.yml":
            jobs = self.api(f"actions/runs/{run['id']}/jobs", "-f", "per_page=100")
            required = [job for job in jobs["jobs"] if job["name"] == "ci-required"]
            if jobs["total_count"] > 100 or len(required) != 1 or required[0]["conclusion"] != "success":
                raise CutError("missing unique successful ci-required on exact-SHA CI run")
        return current["html_url"]


def cleanup(repo: Repository, branch: str) -> None:
    if not re.fullmatch(r"release-cut/dry-run/[0-9]+-[0-9]+", branch):
        raise CutError("cleanup only accepts this workflow's dry-run branch")
    if repo.git("ls-remote", "--heads", "origin", f"refs/heads/{branch}"):
        repo.git("push", "origin", "--delete", branch)


def orchestrate(repo: Repository, requested: str, dry_run: bool) -> None:
    if os.environ.get("GITHUB_REF") != "refs/heads/main" or os.environ.get("GITHUB_EVENT_NAME") != "workflow_dispatch":
        raise CutError("release cut requires workflow_dispatch from refs/heads/main")
    if repo.git("status", "--porcelain"):
        raise CutError("release cut requires a clean checkout")
    main = repo.refresh()
    repo.git("checkout", "--detach", main)
    version = require_version(project_version(repo.read("pyproject.toml")), requested)
    actions = Actions(repo)
    if dry_run:
        branch = f"release-cut/dry-run/{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
        try:
            stamp = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
            repo.prepare(version, stamp)
            prep = repo.commit("prepare", version, stamp)
            repo.checks()
            repo.git("push", "origin", f"{prep}:refs/heads/{branch}")
            actions.wait("ci.yml", branch, prep, "workflow_dispatch", dispatch=True)
            repo.train(version)
            train = repo.commit("open-train", version)
            repo.checks()
            summary(f"Dry run {version}: prepared {prep}, locally checked train {train}. "
                    f"Real run would promote prep, wait for main push CI, tag v{version}, "
                    "wait for release.yml, then validate and promote train. Main/tags unchanged.")
        finally:
            cleanup(repo, branch)
        return
    # A completed train can be recognized on a rerun after the last push.
    title = repo.git("show", "-s", "--format=%s", main)
    completed = re.fullmatch(rf"Release cut: open-train ({SEMVER})", title)
    if completed and next_version(completed[1]) == version:
        version = completed[1]
    prefix = f"release-cut/v{version}"
    prep = repo.ref(f"refs/remotes/origin/{prefix}/prepare")
    train = repo.ref(f"refs/remotes/origin/{prefix}/open-train")
    tag = repo.ref(f"refs/tags/v{version}")
    if not prep and repo.git("show", "-s", "--format=%s", main) == f"Release cut: prepare {version}":
        prep = main
    base = repo.git("rev-parse", prep + "^") if prep else main
    stage = detect_stage(main, prep, train, tag, base)
    print(f"Resume {version}: {stage}", flush=True)
    if prep:
        repo.validate_candidate(prep, "prepare", version, base)
    if train:
        if not prep:
            raise CutError("train without prep")
        repo.validate_candidate(train, "open-train", version, prep)
    if stage == "prepare":
        stamp = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        repo.prepare(version, stamp)
        prep = repo.commit("prepare", version, stamp)
        repo.checks()
        repo.git("push", "origin", f"{prep}:refs/heads/{prefix}/prepare")
    assert prep is not None
    if stage in {"prepare", "promote"}:
        actions.wait("ci.yml", prefix + "/prepare", prep, "workflow_dispatch", dispatch=True)
        if repo.refresh() != base:
            raise CutError("main moved before promotion; no tag or train was pushed")
        repo.git("push", "origin", f"{prep}:refs/heads/main")
    if stage != "done":
        actions.wait("ci.yml", "main", prep, "push")
        if repo.refresh() != prep:
            raise CutError("main moved; refusing tag/train (nothing may land between tag and train)")
        if not tag:
            repo.git("-c", "user.name=github-actions[bot]", "-c",
                     "user.email=41898282+github-actions[bot]@users.noreply.github.com",
                     "tag", "-a", f"v{version}", prep, "-m", f"Release {version}")
            repo.git("push", "origin", f"refs/tags/v{version}")
    release_url = actions.wait("release.yml", f"v{version}", prep, "push")
    if stage != "done":
        if repo.refresh() != prep:
            raise CutError("main moved after tag; nothing may land between tag and train")
        if not train:
            repo.git("checkout", "--detach", prep)
            repo.train(version)
            train = repo.commit("open-train", version)
            repo.checks()
            repo.git("push", "origin", f"{train}:refs/heads/{prefix}/open-train")
        actions.wait("ci.yml", prefix + "/open-train", train, "workflow_dispatch", dispatch=True)
        if repo.refresh() != prep:
            raise CutError("main moved after tag; refusing train promotion")
        repo.git("push", "origin", f"{train}:refs/heads/main")
    summary(f"Release {version}\n\nPrep: {prep}\n\nTrain: {train}\n\n"
            f"Tag: v{version}\n\nRelease run: {release_url}")


def summary(text: str) -> None:
    print(text, flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(text + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "prepare", "open-train", "cleanup", "check"])
    parser.add_argument("--version", default="")
    parser.add_argument("--date", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--branch")
    args = parser.parse_args(argv)
    repo = Repository()
    try:
        if args.command == "run":
            orchestrate(repo, args.version, args.dry_run)
        elif args.command == "check":
            repo.checks()
        elif args.command == "cleanup":
            cleanup(repo, args.branch or "")
        else:
            version = require_version(project_version(repo.read("pyproject.toml")), args.version)
            if args.command == "prepare":
                repo.prepare(version, args.date or datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())
            else:
                repo.train(version)
    except (CutError, subprocess.SubprocessError, OSError, ValueError) as exc:
        print(f"FAIL release cut: {exc}", file=sys.stderr)
        if isinstance(exc, subprocess.CalledProcessError):
            print(exc.stdout, exc.stderr, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
