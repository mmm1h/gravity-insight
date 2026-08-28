"""Verify that PyPI provenance exists and binds to the distributed files.

This dependency-free check proves that each release file has a PyPI attestation
whose statement names the file and repeats the SHA-256 published by PyPI's JSON
API. It does not cryptographically verify signatures, parse X.509 certificates,
validate OIDC identity claims, or prove that the signing identity is this
repository.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any


PYPI_BASE_URL = "https://pypi.org"
PUBLISH_PREDICATE_TYPE = "https://docs.pypi.org/attestations/publish/v1"
MAX_ATTEMPTS = 7
RETRY_DELAY_SECONDS = 15
HTTP_TIMEOUT_SECONDS = 15
MAX_JSON_BYTES = 2 * 1024 * 1024
USER_AGENT = "gravity-insight-release-provenance/1"
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


def main(argv: Sequence[str] | None = None) -> int:
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


if __name__ == "__main__":
    raise SystemExit(main())
