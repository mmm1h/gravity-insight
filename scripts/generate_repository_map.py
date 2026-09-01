"""Generate or verify the deterministic Repository Map projection."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from repository_map import (
    MAP_PATH,
    MAP_SCHEMA,
    build_repository_map,
    canonical_json_bytes,
    validate_contract,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the checked-in projection is stale")
    parser.add_argument("--output", type=Path, default=MAP_PATH)
    args = parser.parse_args(argv)

    document = build_repository_map()
    validate_contract(document, MAP_SCHEMA)
    payload = canonical_json_bytes(document) + b"\n"
    if args.check:
        if not args.output.is_file() or args.output.read_bytes() != payload:
            print(f"stale repository map: {args.output}", file=sys.stderr)
            return 1
        status = "current"
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(payload)
        status = "written"
    print(
        json.dumps(
            {
                "bytes": len(payload),
                "entries": len(document["entries"]),
                "module_graph_edges": document["module_graph"]["edge_count"],
                "module_graph_nodes": document["module_graph"]["node_count"],
                "output": str(args.output),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "status": status,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
