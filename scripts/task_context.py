"""Build a minimal Repository Map task context pack as JSON."""

from __future__ import annotations

import argparse
import json

from repository_map import RepositoryMapError, build_task_context


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selectors = parser.add_mutually_exclusive_group(required=True)
    selectors.add_argument("--issue")
    selectors.add_argument("--journey")
    selectors.add_argument("--skill")
    selectors.add_argument("--selector")
    selectors.add_argument("--changed-files", nargs="+")
    args = parser.parse_args(argv)
    choices = {
        "issue": args.issue,
        "journey": args.journey,
        "skill": args.skill,
        "selector": args.selector,
        "changed_files": args.changed_files,
    }
    kind, value = next((kind, value) for kind, value in choices.items() if value is not None)
    try:
        result = build_task_context(kind, value)
    except RepositoryMapError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
