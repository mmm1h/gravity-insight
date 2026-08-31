"""Validate the sole Canonical Architecture and its four-field binding."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from gravity_insight.documentation_gate import (
    DocumentationGateError,
    validate_architecture_binding,
    validate_mermaid,
)


ROOT = Path(__file__).resolve().parents[1]


def validate_repository(root: Path = ROOT) -> dict[str, object]:
    result = validate_architecture_binding(root)
    result["mermaid_blocks"] = validate_mermaid(
        (root / str(result["path"])).read_text(encoding="utf-8")
    )
    return result


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if arguments:
        print(f"canonical architecture validation failed: unknown arguments {arguments}", file=sys.stderr)
        return 2
    try:
        result = validate_repository()
    except (
        DocumentationGateError,
        json.JSONDecodeError,
        OSError,
        UnicodeError,
    ) as exc:
        print(f"canonical architecture validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
