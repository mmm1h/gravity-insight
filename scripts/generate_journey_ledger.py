"""Generate the packaged read-only Journey ledger snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path

from gravity_insight.journey_ledger import (
    FACTS_PATH, render_journey_ledger_snapshot, render_journey_ledger_markdown,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = FACTS_PATH
DOCUMENT = ROOT / "docs" / "analysis-journeys.md"
TARGET = (
    ROOT
    / "src"
    / "gravity_insight"
    / "contracts"
    / "journeys"
    / "ledger-snapshot.v2.json"
)


def rendered_snapshot() -> str:
    return render_journey_ledger_snapshot(SOURCE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    outputs = {TARGET: rendered_snapshot(), DOCUMENT: render_journey_ledger_markdown(SOURCE)}
    stale = []
    for path, rendered in outputs.items():
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != rendered:
                stale.append(str(path))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8", newline="\n")
            print(path.relative_to(ROOT).as_posix())
    if stale:
        print(
            "Journey ledger projection does not match structured governance owners: "
            + ", ".join(stale)
            + ". Run \x60python scripts/generate_journey_ledger.py\x60 to rebuild."
        )
        return 1
    print("Journey ledger projections are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
