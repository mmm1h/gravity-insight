from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json_bytes(value))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stable_bundle_id(files: list[dict[str, Any]]) -> str:
    rows = [f"{item['url']}\t{item['sha256']}\t{item['size']}" for item in files]
    return sha256_bytes(("\n".join(sorted(rows)) + "\n").encode("utf-8"))
