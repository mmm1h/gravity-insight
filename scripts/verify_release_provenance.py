"""Verify PyPI provenance and reconcile partially completed releases.

This dependency-free check proves that each release file has a PyPI attestation
whose statement names the file and repeats the SHA-256 published by PyPI's JSON
API. It does not cryptographically verify signatures, parse X.509 certificates,
validate OIDC identity claims, or prove that the signing identity is this
repository. Recovery additionally treats the checked-out tag, PyPI release JSON,
and GitHub Release API as the only durable state and uses SHA-256 throughout.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


PYPI_BASE_URL = "https://pypi.org"
PUBLISH_PREDICATE_TYPE = "https://docs.pypi.org/attestations/publish/v1"
MAX_ATTEMPTS = 7
RETRY_DELAY_SECONDS = 15
HTTP_TIMEOUT_SECONDS = 15
MAX_JSON_BYTES = 2 * 1024 * 1024
USER_AGENT = "gravity-insight-release-provenance/1"
MAX_DOWNLOAD_BYTES = 100 * 1024 * 1024
RECOVERY_ATTEMPTS = MAX_ATTEMPTS
RECOVERY_DELAY_SECONDS = RETRY_DELAY_SECONDS
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ProvenanceVerificationError(ValueError):
    """A release or provenance response does not satisfy the gate."""


@dataclass(frozen=True)
class ReleaseFile:
    filename: str
    packagetype: str
    sha256: str


def _mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ProvenanceVerificationError(f"{context} must be an object")
    return value


def release_files(release_payload: Mapping[str, Any]) -> tuple[ReleaseFile, ...]:
    """Parse PyPI release JSON and require wheel and sdist file classes."""

    urls = release_payload.get("urls")
    if not isinstance(urls, list) or not urls:
        raise ProvenanceVerificationError("PyPI release JSON has no distribution files")

    files: list[ReleaseFile] = []
    seen: set[str] = set()
    for index, raw_file in enumerate(urls):
        item = _mapping(raw_file, f"urls[{index}]")
        filename = item.get("filename")
        packagetype = item.get("packagetype")
        digests = _mapping(item.get("digests"), f"urls[{index}].digests")
        sha256 = digests.get("sha256")
        if not isinstance(filename, str) or not filename:
            raise ProvenanceVerificationError(f"urls[{index}].filename is missing")
        if filename in seen:
            raise ProvenanceVerificationError(
                f"PyPI release JSON repeats filename {filename!r}"
            )
        if not isinstance(packagetype, str) or not packagetype:
            raise ProvenanceVerificationError(
                f"PyPI release file {filename!r} has no packagetype"
            )
        if not isinstance(sha256, str) or _SHA256.fullmatch(sha256) is None:
            raise ProvenanceVerificationError(
                f"PyPI release file {filename!r} has no valid SHA-256"
            )
        seen.add(filename)
        files.append(ReleaseFile(filename, packagetype, sha256))

    present_types = {item.packagetype for item in files}
    missing_types = [
        label
        for packagetype, label in (("bdist_wheel", "wheel"), ("sdist", "sdist"))
        if packagetype not in present_types
    ]
    if missing_types:
        raise ProvenanceVerificationError(
            "PyPI release is missing required distribution type(s): "
            + ", ".join(missing_types)
        )
    return tuple(files)


def _decode_statement(attestation: Mapping[str, Any]) -> Mapping[str, Any]:
    envelope = _mapping(attestation.get("envelope"), "attestation.envelope")
    encoded = envelope.get("statement")
    if not isinstance(encoded, str) or not encoded:
        raise ProvenanceVerificationError("attestation.envelope.statement is missing")
    try:
        decoded = base64.b64decode(encoded, validate=True)
        statement = json.loads(decoded)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProvenanceVerificationError(
            "attestation.envelope.statement is not valid base64 JSON"
        ) from error
    return _mapping(statement, "decoded in-toto statement")


def _attestation_rejections(
    release_file: ReleaseFile, attestation: Mapping[str, Any]
) -> list[str]:
    rejections: list[str] = []
    try:
        statement = _decode_statement(attestation)
    except ProvenanceVerificationError as error:
        return [str(error)]

    subjects = statement.get("subject")
    named_subjects: list[Mapping[str, Any]] = []
    if isinstance(subjects, list):
        for subject in subjects:
            if isinstance(subject, Mapping) and subject.get("name") == release_file.filename:
                named_subjects.append(subject)
    if not named_subjects:
        rejections.append(
            f"statement subject does not name {release_file.filename!r}"
        )
    elif not any(
        isinstance(subject.get("digest"), Mapping)
        and subject["digest"].get("sha256") == release_file.sha256
        for subject in named_subjects
    ):
        rejections.append(
            "statement subject SHA-256 does not match PyPI JSON SHA-256 "
            f"{release_file.sha256}"
        )

    if statement.get("predicateType") != PUBLISH_PREDICATE_TYPE:
        rejections.append(
            f"statement predicateType is not {PUBLISH_PREDICATE_TYPE!r}"
        )

    verification_material = attestation.get("verification_material")
    if not isinstance(verification_material, Mapping):
        rejections.append("attestation verification_material is missing")
    else:
        if not verification_material.get("certificate"):
            rejections.append("attestation verification_material.certificate is missing")
        transparency_entries = verification_material.get("transparency_entries")
        if not isinstance(transparency_entries, list) or not transparency_entries:
            rejections.append(
                "attestation verification_material.transparency_entries is empty"
            )
    return rejections


def validate_file_provenance(
    release_file: ReleaseFile, provenance_payload: Mapping[str, Any]
) -> None:
    """Require one complete PyPI publish attestation for one release file."""

    bundles = provenance_payload.get("attestation_bundles")
    if not isinstance(bundles, list) or not bundles:
        raise ProvenanceVerificationError(
            f"{release_file.filename}: attestation_bundles is missing or empty"
        )

    candidate_rejections: list[str] = []
    candidate_count = 0
    for bundle_index, raw_bundle in enumerate(bundles):
        if not isinstance(raw_bundle, Mapping):
            candidate_rejections.append(f"bundle {bundle_index + 1} is not an object")
            continue
        attestations = raw_bundle.get("attestations")
        if not isinstance(attestations, list) or not attestations:
            candidate_rejections.append(
                f"bundle {bundle_index + 1} has no attestations"
            )
            continue
        for attestation_index, raw_attestation in enumerate(attestations):
            candidate_count += 1
            if not isinstance(raw_attestation, Mapping):
                candidate_rejections.append(
                    f"bundle {bundle_index + 1} attestation "
                    f"{attestation_index + 1} is not an object"
                )
                continue
            rejections = _attestation_rejections(release_file, raw_attestation)
            if not rejections:
                return
            candidate_rejections.append(
                f"bundle {bundle_index + 1} attestation {attestation_index + 1}: "
                + "; ".join(rejections)
            )

    if candidate_count == 0 and not candidate_rejections:
        candidate_rejections.append("bundles contain no attestations")
    raise ProvenanceVerificationError(
        f"{release_file.filename}: no attestation satisfies the release gate ("
        + " | ".join(candidate_rejections)
        + ")"
    )


def validate_release_provenance(
    release_payload: Mapping[str, Any],
    provenance_by_filename: Mapping[str, Mapping[str, Any]],
) -> tuple[ReleaseFile, ...]:
    """Purely validate parsed PyPI JSON structures without network access."""

    files = release_files(release_payload)
    for release_file in files:
        payload = provenance_by_filename.get(release_file.filename)
        if payload is None:
            raise ProvenanceVerificationError(
                f"{release_file.filename}: integrity provenance response is missing"
            )
        validate_file_provenance(release_file, payload)
    return files


def fetch_json(url: str) -> Mapping[str, Any]:
    """Fetch one bounded JSON document from PyPI."""

    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_JSON_BYTES + 1)
    except (OSError, urllib.error.URLError) as error:
        raise ProvenanceVerificationError(f"GET {url} failed: {error}") from error
    if len(body) > MAX_JSON_BYTES:
        raise ProvenanceVerificationError(f"GET {url} exceeded the JSON size limit")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProvenanceVerificationError(f"GET {url} returned invalid JSON") from error
    return _mapping(payload, f"GET {url} response")


def _release_url(project: str, version: str) -> str:
    return (
        f"{PYPI_BASE_URL}/pypi/{urllib.parse.quote(project, safe='')}/"
        f"{urllib.parse.quote(version, safe='')}/json"
    )


def _provenance_url(project: str, version: str, filename: str) -> str:
    return (
        f"{PYPI_BASE_URL}/integrity/{urllib.parse.quote(project, safe='')}/"
        f"{urllib.parse.quote(version, safe='')}/"
        f"{urllib.parse.quote(filename, safe='')}/provenance"
    )


def verify_pypi_release(
    project: str,
    version: str,
    *,
    fetcher: Callable[[str], Mapping[str, Any]] = fetch_json,
    sleeper: Callable[[float], None] = time.sleep,
    output: Callable[[str], None] = print,
) -> tuple[ReleaseFile, ...]:
    """Fetch and verify a release, retrying bounded PyPI propagation failures."""

    release_payload: Mapping[str, Any] | None = None
    files: tuple[ReleaseFile, ...] = ()
    verified_payloads: dict[str, Mapping[str, Any]] = {}
    last_failures: list[str] = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        output(f"Attempt {attempt}/{MAX_ATTEMPTS}: verify {project} {version}")
        last_failures = []
        if release_payload is None:
            try:
                candidate = fetcher(_release_url(project, version))
                files = release_files(candidate)
                release_payload = candidate
            except ProvenanceVerificationError as error:
                last_failures.append(str(error))

        if release_payload is not None:
            for release_file in files:
                if release_file.filename in verified_payloads:
                    continue
                try:
                    payload = fetcher(
                        _provenance_url(project, version, release_file.filename)
                    )
                    validate_file_provenance(release_file, payload)
                    verified_payloads[release_file.filename] = payload
                except ProvenanceVerificationError as error:
                    last_failures.append(str(error))

        if release_payload is not None and not last_failures:
            verified_files = validate_release_provenance(
                release_payload, verified_payloads
            )
            for release_file in verified_files:
                output(
                    f"PASS {release_file.filename} [{release_file.packagetype}] "
                    f"sha256={release_file.sha256}"
                )
            output(
                f"PASS release provenance: {project} {version}; "
                f"verified {len(verified_files)} file(s), including wheel and sdist"
            )
            return verified_files

        if attempt < MAX_ATTEMPTS:
            output(
                f"RETRY {attempt}/{MAX_ATTEMPTS}: {' | '.join(last_failures)}; "
                f"waiting {RETRY_DELAY_SECONDS}s"
            )
            sleeper(RETRY_DELAY_SECONDS)

    raise ProvenanceVerificationError(
        f"verification did not pass after {MAX_ATTEMPTS} attempts: "
        + " | ".join(last_failures)
    )


def provenance_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify PyPI provenance for every file in one release."
    )
    parser.add_argument("project")
    parser.add_argument("version")
    args = parser.parse_args(argv)
    try:
        verify_pypi_release(args.project, args.version)
    except ProvenanceVerificationError as error:
        print(
            f"FAIL release provenance: {args.project} {args.version}: {error}",
            file=sys.stderr,
        )
        return 1
    return 0


class ReleaseRecoveryError(RuntimeError):
    """An observed release state cannot be reconciled safely."""


@dataclass(frozen=True)
class Distribution:
    filename: str
    sha256: str
    path: Path | None = None
    url: str | None = None


@dataclass(frozen=True)
class PublishPlan:
    missing: tuple[Distribution, ...]
    identical: tuple[Distribution, ...]

    @property
    def upload_required(self) -> bool:
        return bool(self.missing)


class GitHubReleaseGateway(Protocol):
    def remote_tag_commit(self, tag: str) -> str: ...

    def get_release(self, tag: str) -> Mapping[str, Any] | None: ...

    def create_release(self, tag: str) -> None: ...

    def asset_sha256(self, asset: Mapping[str, Any]) -> str: ...

    def upload_asset(self, tag: str, distribution: Distribution) -> None: ...


def _valid_sha256(value: object, context: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ReleaseRecoveryError(f"{context} has no valid SHA-256")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_distributions(directory: Path) -> tuple[Distribution, ...]:
    if not directory.is_dir():
        raise ReleaseRecoveryError(f"distribution directory does not exist: {directory}")
    paths = sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and (path.suffix == ".whl" or path.name.endswith(".tar.gz"))
    )
    wheel_count = sum(path.suffix == ".whl" for path in paths)
    sdist_count = sum(path.name.endswith(".tar.gz") for path in paths)
    if (wheel_count, sdist_count) != (1, 1):
        raise ReleaseRecoveryError(
            "local distributions must contain exactly one wheel and one sdist; "
            f"found wheel={wheel_count}, sdist={sdist_count}"
        )
    return tuple(
        Distribution(path.name, file_sha256(path), path=path) for path in paths
    )


def pypi_distributions(payload: Mapping[str, Any]) -> tuple[Distribution, ...]:
    urls = payload.get("urls")
    if not isinstance(urls, list) or not urls:
        raise ReleaseRecoveryError("PyPI release JSON has no distribution files")
    distributions: list[Distribution] = []
    seen: set[str] = set()
    wheel_count = 0
    sdist_count = 0
    for index, raw in enumerate(urls):
        if not isinstance(raw, Mapping):
            raise ReleaseRecoveryError(f"PyPI urls[{index}] is not an object")
        filename = raw.get("filename")
        digests = raw.get("digests")
        url = raw.get("url")
        if not isinstance(filename, str) or not filename or Path(filename).name != filename:
            raise ReleaseRecoveryError(f"PyPI urls[{index}].filename is invalid")
        if filename in seen:
            raise ReleaseRecoveryError(f"PyPI repeats distribution {filename!r}")
        if not isinstance(digests, Mapping):
            raise ReleaseRecoveryError(f"PyPI distribution {filename!r} has no digests")
        sha256 = _valid_sha256(
            digests.get("sha256"), f"PyPI distribution {filename!r}"
        )
        if not isinstance(url, str) or not url.startswith("https://files.pythonhosted.org/"):
            raise ReleaseRecoveryError(
                f"PyPI distribution {filename!r} has an untrusted download URL"
            )
        wheel_count += filename.endswith(".whl")
        sdist_count += filename.endswith(".tar.gz")
        seen.add(filename)
        distributions.append(Distribution(filename, sha256, url=url))
    if (wheel_count, sdist_count) != (1, 1):
        raise ReleaseRecoveryError(
            "PyPI release must contain exactly one wheel and one sdist; "
            f"found wheel={wheel_count}, sdist={sdist_count}"
        )
    return tuple(distributions)


def plan_pypi_publish(
    local: Sequence[Distribution], remote: Sequence[Distribution] | None
) -> PublishPlan:
    if remote is None:
        return PublishPlan(tuple(local), ())
    local_by_name = {item.filename: item for item in local}
    remote_by_name = {item.filename: item for item in remote}
    unexpected = sorted(set(remote_by_name) - set(local_by_name))
    if unexpected:
        raise ReleaseRecoveryError(
            "PyPI version contains unexpected distribution(s): " + ", ".join(unexpected)
        )
    identical: list[Distribution] = []
    missing: list[Distribution] = []
    for filename, local_file in local_by_name.items():
        remote_file = remote_by_name.get(filename)
        if remote_file is None:
            missing.append(local_file)
        elif remote_file.sha256 != local_file.sha256:
            raise ReleaseRecoveryError(
                f"PyPI SHA-256 mismatch for {filename}: local={local_file.sha256} "
                f"remote={remote_file.sha256}; refusing upload"
            )
        else:
            identical.append(local_file)
    return PublishPlan(
        tuple(sorted(missing, key=lambda item: item.filename)),
        tuple(sorted(identical, key=lambda item: item.filename)),
    )


def stage_publish_plan(plan: PublishPlan, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    if any(directory.iterdir()):
        raise ReleaseRecoveryError(f"publish staging directory is not empty: {directory}")
    for distribution in plan.missing:
        if distribution.path is None:
            raise ReleaseRecoveryError(
                f"missing local path for distribution {distribution.filename}"
            )
        shutil.copy2(distribution.path, directory / distribution.filename)


def _request_json(url: str) -> Mapping[str, Any]:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            body = response.read(MAX_JSON_BYTES + 1)
    except urllib.error.HTTPError:
        raise
    except (OSError, urllib.error.URLError) as error:
        raise ReleaseRecoveryError(f"GET {url} failed: {error}") from error
    if len(body) > MAX_JSON_BYTES:
        raise ReleaseRecoveryError(f"GET {url} exceeded the JSON size limit")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ReleaseRecoveryError(f"GET {url} returned invalid JSON") from error
    if not isinstance(payload, Mapping):
        raise ReleaseRecoveryError(f"GET {url} did not return an object")
    return payload


def pypi_release_url(project: str, version: str) -> str:
    return (
        f"{PYPI_BASE_URL}/pypi/{urllib.parse.quote(project, safe='')}/"
        f"{urllib.parse.quote(version, safe='')}/json"
    )


def fetch_pypi_release(
    project: str,
    version: str,
    *,
    required: bool,
    fetcher: Callable[[str], Mapping[str, Any]] = _request_json,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[Distribution, ...] | None:
    attempts = RECOVERY_ATTEMPTS if required else 1
    url = pypi_release_url(project, version)
    for attempt in range(1, attempts + 1):
        try:
            return pypi_distributions(fetcher(url))
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise ReleaseRecoveryError(f"GET {url} failed: HTTP {error.code}") from error
            if attempt == attempts:
                if required:
                    raise ReleaseRecoveryError(
                        f"PyPI release {project} {version} is still missing after "
                        f"{attempts} attempts"
                    ) from error
                return None
            sleeper(RECOVERY_DELAY_SECONDS)
    raise AssertionError("unreachable")


def download_pypi_distributions(
    distributions: Sequence[Distribution], directory: Path
) -> tuple[Distribution, ...]:
    directory.mkdir(parents=True, exist_ok=True)
    downloaded: list[Distribution] = []
    for distribution in distributions:
        if distribution.url is None:
            raise ReleaseRecoveryError(f"PyPI URL missing for {distribution.filename}")
        destination = directory / distribution.filename
        request = urllib.request.Request(
            distribution.url, headers={"User-Agent": USER_AGENT}
        )
        try:
            with (
                urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response,
                destination.open("wb") as output,
            ):
                copied = 0
                while chunk := response.read(1024 * 1024):
                    copied += len(chunk)
                    if copied > MAX_DOWNLOAD_BYTES:
                        raise ReleaseRecoveryError(
                            f"download exceeded size limit: {distribution.filename}"
                        )
                    output.write(chunk)
        except (OSError, urllib.error.URLError) as error:
            raise ReleaseRecoveryError(
                f"download failed for {distribution.filename}: {error}"
            ) from error
        actual = file_sha256(destination)
        if actual != distribution.sha256:
            raise ReleaseRecoveryError(
                f"downloaded PyPI SHA-256 mismatch for {distribution.filename}: "
                f"expected={distribution.sha256} actual={actual}"
            )
        downloaded.append(
            Distribution(distribution.filename, actual, path=destination)
        )
    return tuple(downloaded)


def _git_commit(repository: Path, revision: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        cwd=repository,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ReleaseRecoveryError(f"cannot resolve {revision}: {detail}")
    return completed.stdout.strip()


def verify_checked_out_tag(
    tag: str, version: str, repository: Path, gateway: GitHubReleaseGateway
) -> str:
    expected = f"v{version}"
    if tag != expected:
        raise ReleaseRecoveryError(
            f"release tag {tag!r} does not match requested version {version!r}"
        )
    local_tag_commit = _git_commit(repository, f"refs/tags/{tag}")
    head_commit = _git_commit(repository, "HEAD")
    remote_tag_commit = gateway.remote_tag_commit(tag)
    if len({local_tag_commit, head_commit, remote_tag_commit}) != 1:
        raise ReleaseRecoveryError(
            f"tag verification failed for {tag}: local={local_tag_commit} "
            f"HEAD={head_commit} remote={remote_tag_commit}"
        )
    return head_commit


def sync_github_release(
    tag: str,
    distributions: Sequence[Distribution],
    gateway: GitHubReleaseGateway,
) -> tuple[str, ...]:
    release = gateway.get_release(tag)
    actions: list[str] = []
    if release is None:
        gateway.create_release(tag)
        actions.append("created-release")
        release = gateway.get_release(tag)
        if release is None:
            raise ReleaseRecoveryError(
                f"GitHub Release {tag} is missing after successful create"
            )
    raw_assets = release.get("assets")
    if not isinstance(raw_assets, list):
        raise ReleaseRecoveryError(f"GitHub Release {tag} has no asset list")
    assets: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(raw_assets):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("name"), str):
            raise ReleaseRecoveryError(f"GitHub Release asset {index} is invalid")
        name = raw["name"]
        if name in assets:
            raise ReleaseRecoveryError(f"GitHub Release repeats asset {name!r}")
        assets[name] = raw

    missing: list[Distribution] = []
    for distribution in distributions:
        asset = assets.get(distribution.filename)
        if asset is None:
            missing.append(distribution)
            continue
        remote_sha256 = gateway.asset_sha256(asset)
        if remote_sha256 != distribution.sha256:
            raise ReleaseRecoveryError(
                f"GitHub asset SHA-256 mismatch for {distribution.filename}: "
                f"expected={distribution.sha256} remote={remote_sha256}; "
                "refusing upload"
            )
        actions.append(f"verified-asset:{distribution.filename}")

    for distribution in missing:
        if distribution.path is None:
            raise ReleaseRecoveryError(
                f"missing local path for distribution {distribution.filename}"
            )
        gateway.upload_asset(tag, distribution)
        actions.append(f"uploaded-asset:{distribution.filename}")
    return tuple(actions)


class GhCliGateway:
    def __init__(self, repository: str):
        self.repository = repository

    def _run(
        self, arguments: Sequence[str], *, allow_not_found: bool = False
    ) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            ["gh", *arguments], text=True, capture_output=True, check=False
        )
        if completed.returncode == 0:
            return completed
        if allow_not_found and "HTTP 404" in completed.stderr:
            return completed
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ReleaseRecoveryError(f"gh {' '.join(arguments)} failed: {detail}")

    def _api_json(self, endpoint: str) -> Mapping[str, Any]:
        completed = self._run(["api", endpoint])
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ReleaseRecoveryError(
                f"gh api {endpoint} returned invalid JSON"
            ) from error
        if not isinstance(payload, Mapping):
            raise ReleaseRecoveryError(f"gh api {endpoint} did not return an object")
        return payload

    def remote_tag_commit(self, tag: str) -> str:
        encoded = urllib.parse.quote(tag, safe="")
        payload = self._api_json(
            f"repos/{self.repository}/git/ref/tags/{encoded}"
        )
        target = payload.get("object")
        for _ in range(5):
            if not isinstance(target, Mapping):
                break
            object_type = target.get("type")
            sha = target.get("sha")
            if not isinstance(sha, str):
                break
            if object_type == "commit":
                return sha
            if object_type != "tag":
                break
            target = self._api_json(
                f"repos/{self.repository}/git/tags/{sha}"
            ).get("object")
        raise ReleaseRecoveryError(f"remote tag {tag} does not resolve to a commit")

    def get_release(self, tag: str) -> Mapping[str, Any] | None:
        encoded = urllib.parse.quote(tag, safe="")
        endpoint = f"repos/{self.repository}/releases/tags/{encoded}"
        completed = self._run(["api", endpoint], allow_not_found=True)
        if completed.returncode != 0:
            return None
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise ReleaseRecoveryError(
                f"gh api {endpoint} returned invalid JSON"
            ) from error
        if not isinstance(payload, Mapping):
            raise ReleaseRecoveryError(f"gh api {endpoint} did not return an object")
        return payload

    def create_release(self, tag: str) -> None:
        self._run(
            [
                "release",
                "create",
                tag,
                "--repo",
                self.repository,
                "--verify-tag",
                "--generate-notes",
                "--title",
                tag,
            ]
        )

    def asset_sha256(self, asset: Mapping[str, Any]) -> str:
        digest = asset.get("digest")
        if isinstance(digest, str) and digest.startswith("sha256:"):
            return _valid_sha256(digest.removeprefix("sha256:"), "GitHub asset")
        asset_url = asset.get("url")
        if not isinstance(asset_url, str):
            raise ReleaseRecoveryError("GitHub asset has neither digest nor URL")
        with tempfile.NamedTemporaryFile(prefix="gravity-release-asset-", delete=False) as output:
            temporary = Path(output.name)
            completed = subprocess.run(
                ["gh", "api", asset_url, "-H", "Accept: application/octet-stream"],
                stdout=output,
                stderr=subprocess.PIPE,
                check=False,
            )
        try:
            if completed.returncode != 0:
                detail = completed.stderr.decode("utf-8", errors="replace").strip()
                raise ReleaseRecoveryError(
                    f"could not download existing GitHub asset: {detail}"
                )
            return file_sha256(temporary)
        finally:
            temporary.unlink(missing_ok=True)

    def upload_asset(self, tag: str, distribution: Distribution) -> None:
        if distribution.path is None:
            raise ReleaseRecoveryError(
                f"missing local path for distribution {distribution.filename}"
            )
        self._run(
            [
                "release",
                "upload",
                tag,
                str(distribution.path),
                "--repo",
                self.repository,
            ]
        )


def _write_github_output(path: Path | None, key: str, value: str) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8", newline="\n") as output:
        output.write(f"{key}={value}\n")


def _pypi_plan(args: argparse.Namespace) -> int:
    local = local_distributions(args.dist_dir.resolve())
    remote = fetch_pypi_release(args.project, args.version, required=False)
    plan = plan_pypi_publish(local, remote)
    if plan.upload_required:
        stage_publish_plan(plan, args.stage_dir.resolve())
        names = ", ".join(item.filename for item in plan.missing)
        print(f"UPLOAD PyPI missing distribution(s): {names}")
    else:
        names = ", ".join(item.filename for item in plan.identical)
        print(f"SKIP PyPI upload; SHA-256 identical: {names}")
    _write_github_output(
        args.github_output, "upload_required", str(plan.upload_required).lower()
    )
    _write_github_output(args.github_output, "upload_count", str(len(plan.missing)))
    return 0


def _recover(args: argparse.Namespace) -> int:
    gateway = GhCliGateway(args.repository)
    verify_checked_out_tag(
        args.tag, args.version, args.repository_root.resolve(), gateway
    )
    remote = fetch_pypi_release(args.project, args.version, required=True)
    if remote is None:
        raise AssertionError("required PyPI release unexpectedly absent")
    with tempfile.TemporaryDirectory(prefix="gravity-release-recovery-") as raw:
        distributions = download_pypi_distributions(remote, Path(raw))
        actions = sync_github_release(args.tag, distributions, gateway)
    if actions:
        for action in actions:
            print(action)
    else:
        print(f"PASS GitHub Release {args.tag} already complete")
    return 0


def release_recovery_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    pypi_plan = subparsers.add_parser("pypi-plan")
    pypi_plan.add_argument("--project", required=True)
    pypi_plan.add_argument("--version", required=True)
    pypi_plan.add_argument("--dist-dir", type=Path, required=True)
    pypi_plan.add_argument("--stage-dir", type=Path, required=True)
    pypi_plan.add_argument(
        "--github-output",
        type=Path,
        default=(
            Path(os.environ["GITHUB_OUTPUT"])
            if os.environ.get("GITHUB_OUTPUT")
            else None
        ),
    )
    pypi_plan.set_defaults(handler=_pypi_plan)

    recover = subparsers.add_parser("recover")
    recover.add_argument("--project", required=True)
    recover.add_argument("--version", required=True)
    recover.add_argument("--tag", required=True)
    recover.add_argument("--repository", required=True)
    recover.add_argument("--repository-root", type=Path, default=Path.cwd())
    recover.set_defaults(handler=_recover)

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, ReleaseRecoveryError, subprocess.SubprocessError) as error:
        print(f"FAIL release recovery: {error}", file=sys.stderr)
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {"pypi-plan", "recover"}:
        return release_recovery_main(arguments)
    return provenance_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
