from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
CACHE_SCHEMA = "gravity.offline-wheel-cache.v1"


def _distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "_", value)


def _wheel_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _record_row(path: str, value: bytes) -> tuple[str, str, str]:
    digest = base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b"=")
    return path, f"sha256={digest.decode('ascii')}", str(len(value))


def _package_files(source: Path) -> Iterable[tuple[str, bytes]]:
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(source).as_posix()
        if path.suffix == ".py" or path.suffix == ".json":
            yield f"gravity_insight/{relative}", _wheel_bytes(path)
        elif path.suffix == ".md" and relative.startswith("skills/"):
            yield f"gravity_insight/{relative}", _wheel_bytes(path)


def _git_head(repository: Path) -> str | None:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        cwd=repository,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    head = completed.stdout.strip()
    if completed.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", head) is None:
        return None
    return head


def _offline_wheel_input_sha256(repository: Path) -> str:
    digest = hashlib.sha256()
    inputs = [
        ("scripts/build_offline_wheel.py", Path(__file__).resolve().read_bytes()),
        ("pyproject.toml", (repository / "pyproject.toml").read_bytes()),
        *_package_files(repository / "src/gravity_insight"),
    ]
    for name, value in inputs:
        encoded_name = name.encode("utf-8")
        digest.update(len(encoded_name).to_bytes(8, "big"))
        digest.update(encoded_name)
        digest.update(len(value).to_bytes(8, "big"))
        digest.update(value)
    return digest.hexdigest()


def _cache_identity(repository: Path) -> tuple[str, str] | None:
    head = _git_head(repository)
    if head is None:
        return None
    return head, _offline_wheel_input_sha256(repository)


def _cached_wheel(
    cache_directory: Path,
    *,
    head: str,
    input_sha256: str,
    wheel_name: str,
) -> Path | None:
    manifest_path = cache_directory / "manifest.json"
    wheel = cache_directory / wheel_name
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    expected_keys = {
        "schema_version", "head", "input_sha256", "wheel", "wheel_sha256"
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        return None
    if (
        manifest.get("schema_version") != CACHE_SCHEMA
        or manifest.get("head") != head
        or manifest.get("input_sha256") != input_sha256
        or manifest.get("wheel") != wheel_name
        or not wheel.is_file()
    ):
        return None
    wheel_sha256 = manifest.get("wheel_sha256")
    if (
        not isinstance(wheel_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", wheel_sha256) is None
        or _sha256_file(wheel) != wheel_sha256
    ):
        return None
    return wheel


def _publish_cached_wheel(
    cache_directory: Path,
    wheel: Path,
    *,
    head: str,
    input_sha256: str,
) -> None:
    cache_directory.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": CACHE_SCHEMA,
        "head": head,
        "input_sha256": input_sha256,
        "wheel": wheel.name,
        "wheel_sha256": _sha256_file(wheel),
    }
    with tempfile.TemporaryDirectory(
        prefix="publish-", dir=cache_directory
    ) as raw:
        staging = Path(raw)
        staged_wheel = staging / wheel.name
        staged_manifest = staging / "manifest.json"
        shutil.copy2(wheel, staged_wheel)
        staged_manifest.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        os.replace(staged_wheel, cache_directory / wheel.name)
        os.replace(staged_manifest, cache_directory / "manifest.json")


def _metadata(project: dict) -> bytes:
    lines = [
        "Metadata-Version: 2.4",
        f"Name: {project['name']}",
        f"Version: {project['version']}",
        f"Summary: {project.get('description', '')}",
        f"Requires-Python: {project.get('requires-python', '>=3.11')}",
    ]
    lines.extend(f"Requires-Dist: {value}" for value in project.get("dependencies", []))
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def _entry_points(project: dict) -> bytes:
    scripts = project.get("scripts", {})
    lines = ["[console_scripts]"]
    lines.extend(f"{name} = {target}" for name, target in sorted(scripts.items()))
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_offline_wheel(
    repository: Path = ROOT, wheelhouse: Path | None = None
) -> Path:
    repository = repository.resolve()
    wheelhouse = (wheelhouse or repository / "dist").resolve()
    document = tomllib.loads(
        (repository / "pyproject.toml").read_text(encoding="utf-8")
    )
    project = document["project"]
    distribution = _distribution_name(str(project["name"]))
    version = str(project["version"])
    wheelhouse.mkdir(parents=True, exist_ok=True)
    wheel = wheelhouse / f"{distribution}-{version}-py3-none-any.whl"
    dist_info = f"{distribution}-{version}.dist-info"
    entries = list(_package_files(repository / "src/gravity_insight"))
    entries.extend(
        [
            (f"{dist_info}/METADATA", _metadata(project)),
            (
                f"{dist_info}/WHEEL",
                b"Wheel-Version: 1.0\nGenerator: gravity-offline-wheel\n"
                b"Root-Is-Purelib: true\nTag: py3-none-any\n",
            ),
            (f"{dist_info}/entry_points.txt", _entry_points(project)),
            (f"{dist_info}/top_level.txt", b"gravity_insight\n"),
        ]
    )
    record_path = f"{dist_info}/RECORD"
    rows = [_record_row(path, value) for path, value in entries]
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    writer.writerows([*rows, (record_path, "", "")])
    entries.append((record_path, record.getvalue().encode("utf-8")))

    with zipfile.ZipFile(wheel, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, value in entries:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(f"unsafe wheel path: {name}")
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, value)
    return wheel


def build_or_reuse_offline_wheel(
    repository: Path = ROOT,
    wheelhouse: Path | None = None,
    *,
    cache_root: Path | None = None,
) -> Path:
    repository = repository.resolve()
    wheelhouse = (wheelhouse or repository / "dist").resolve()
    wheelhouse.mkdir(parents=True, exist_ok=True)
    document = tomllib.loads(
        (repository / "pyproject.toml").read_text(encoding="utf-8")
    )
    project = document["project"]
    wheel_name = (
        f"{_distribution_name(str(project['name']))}-{project['version']}"
        "-py3-none-any.whl"
    )
    identity = _cache_identity(repository)
    if identity is not None:
        head, input_sha256 = identity
        root = (cache_root or repository / "tmp/offline-wheel-cache").resolve()
        cache_directory = root / head
        cached = _cached_wheel(
            cache_directory,
            head=head,
            input_sha256=input_sha256,
            wheel_name=wheel_name,
        )
        if cached is not None:
            destination = wheelhouse / wheel_name
            shutil.copy2(cached, destination)
            if (
                _cache_identity(repository) == identity
                and _sha256_file(destination) == _sha256_file(cached)
            ):
                return destination
            destination.unlink(missing_ok=True)

    wheel = build_offline_wheel(repository, wheelhouse)
    final_identity = _cache_identity(repository)
    if identity is not None and final_identity == identity:
        head, input_sha256 = identity
        root = (cache_root or repository / "tmp/offline-wheel-cache").resolve()
        _publish_cached_wheel(
            root / head,
            wheel,
            head=head,
            input_sha256=input_sha256,
        )
    return wheel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the repository wheel with no network or build isolation."
    )
    parser.add_argument("--repository", type=Path, default=ROOT)
    parser.add_argument("--wheel-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    wheel = build_offline_wheel(args.repository, args.wheel_dir)
    print(wheel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
