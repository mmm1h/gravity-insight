"""Generate the root package's lazy export table from its stable API manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "src/gravity_insight"
INIT_PATH = PACKAGE_ROOT / "__init__.py"
MANIFEST_PATH = PACKAGE_ROOT / "governance/public-api-manifest.json"
SCHEMA_VERSION = "gravity.public-api-manifest.v1"
START_MARKER = "# PUBLIC_API_EXPORTS_GENERATED_START"
END_MARKER = "# PUBLIC_API_EXPORTS_GENERATED_END"
_RELATIVE_MODULE = re.compile(r"^\.[A-Za-z_][A-Za-z0-9_.]*$")


def load_manifest(path: Path = MANIFEST_PATH) -> list[dict[str, str]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or set(document) != {"schema_version", "exports"}:
        raise ValueError("public API manifest must contain schema_version and exports")
    if document["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"public API manifest must use {SCHEMA_VERSION}")
    exports = document["exports"]
    if not isinstance(exports, list) or not exports:
        raise ValueError("public API manifest exports must be a non-empty list")
    selected: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, row in enumerate(exports):
        if not isinstance(row, dict) or set(row) != {"name", "module", "attribute"}:
            raise ValueError(f"public API manifest export {index} has invalid fields")
        name, module, attribute = row["name"], row["module"], row["attribute"]
        if not all(isinstance(value, str) for value in (name, module, attribute)):
            raise ValueError(f"public API manifest export {index} fields must be strings")
        if not name.isidentifier() or not attribute.isidentifier():
            raise ValueError(f"public API manifest export {index} names must be identifiers")
        if name in seen:
            raise ValueError(f"public API manifest repeats export {name!r}")
        if _RELATIVE_MODULE.fullmatch(module) is None:
            raise ValueError(f"public API manifest export {name!r} has invalid owner")
        owner = PACKAGE_ROOT.joinpath(*module[1:].split("."))
        if not owner.with_suffix(".py").is_file() and not (owner / "__init__.py").is_file():
            raise ValueError(
                f"public API manifest export {name!r} owner {module!r} does not exist"
            )
        seen.add(name)
        selected.append({"name": name, "module": module, "attribute": attribute})
    return selected


def export_mapping(
    path: Path = MANIFEST_PATH,
) -> dict[str, list[str]]:
    return {
        row["name"]: [row["module"], row["attribute"]]
        for row in load_manifest(path)
    }


def render_export_table(exports: Sequence[Mapping[str, str]]) -> str:
    lines = [START_MARKER, "_EXPORTS = {"]
    for row in exports:
        name = json.dumps(row["name"], ensure_ascii=False)
        module = json.dumps(row["module"], ensure_ascii=False)
        attribute = json.dumps(row["attribute"], ensure_ascii=False)
        rendered = f"    {name}: ({module}, {attribute}),"
        if len(rendered) <= 88:
            lines.append(rendered)
        else:
            lines.extend(
                (
                    f"    {name}: (",
                    f"        {module},",
                    f"        {attribute},",
                    "    ),",
                )
            )
    lines.extend(("}", END_MARKER))
    return "\n".join(lines)


def replace_generated(source: str, rendered: str) -> str:
    if source.count(START_MARKER) != 1 or source.count(END_MARKER) != 1:
        raise ValueError("root package must contain exactly one generated export block")
    start = source.index(START_MARKER)
    end = source.index(END_MARKER, start) + len(END_MARKER)
    return source[:start] + rendered + source[end:]


def generated_source() -> tuple[str, str]:
    source = INIT_PATH.read_text(encoding="utf-8")
    rendered = render_export_table(load_manifest())
    return source, replace_generated(source, rendered)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    try:
        source, expected = generated_source()
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"public API export generation failed: {exc}")
        return 1
    digest = hashlib.sha256(expected.encode("utf-8")).hexdigest()
    if args.write:
        INIT_PATH.write_text(expected, encoding="utf-8", newline="\n")
        print(f"wrote {INIT_PATH} sha256={digest}")
        return 0
    if source != expected:
        print(
            "stale generated public API exports; run "
            "`.venv/Scripts/python.exe scripts/generate_public_api_exports.py --write`"
        )
        return 1
    print(f"PASS public API export manifest: exports={len(load_manifest())} sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
