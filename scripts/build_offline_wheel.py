from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
import re
import tomllib
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]


def _distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "_", value)


def _wheel_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _record_row(path: str, value: bytes) -> tuple[str, str, str]:
    digest = base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b"=")
    return path, f"sha256={digest.decode('ascii')}", str(len(value))


def _package_files(source: Path) -> Iterable[tuple[str, bytes]]:
    for path in sorted(source.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        relative = path.relative_to(source).as_posix()
        if path.suffix == ".py" or path.suffix == ".json":
            yield f"gravity_sdk/{relative}", _wheel_bytes(path)
        elif path.suffix == ".md" and relative.startswith("skills/"):
            yield f"gravity_sdk/{relative}", _wheel_bytes(path)


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
    entries = list(_package_files(repository / "src/gravity_sdk"))
    entries.extend(
        [
            (f"{dist_info}/METADATA", _metadata(project)),
            (
                f"{dist_info}/WHEEL",
                b"Wheel-Version: 1.0\nGenerator: gravity-offline-wheel\n"
                b"Root-Is-Purelib: true\nTag: py3-none-any\n",
            ),
            (f"{dist_info}/entry_points.txt", _entry_points(project)),
            (f"{dist_info}/top_level.txt", b"gravity_sdk\n"),
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
