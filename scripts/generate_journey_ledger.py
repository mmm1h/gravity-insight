"""Generate the packaged read-only Journey ledger snapshot."""

from __future__ import annotations

import argparse
from pathlib import Path

from gravity_sdk.journey_ledger import render_journey_ledger_snapshot


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "analysis-journeys.md"
TARGET = (
    ROOT
    / "src"
    / "gravity_sdk"
    / "contracts"
    / "journeys"
    / "ledger-snapshot.v1.json"
)


def rendered_snapshot() -> str:
    return render_journey_ledger_snapshot(SOURCE.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = rendered_snapshot()
    if args.check:
        try:
            current = TARGET.read_text(encoding="utf-8")
        except OSError:
            current = ""
        if current != rendered:
            print(
                "Journey ledger snapshot does not match docs/analysis-journeys.md. "
                "Run `python scripts/generate_journey_ledger.py` to rebuild "
                "src/gravity_sdk/contracts/journeys/ledger-snapshot.v1.json from "
                "that checked-in source, then review the generated snapshot."
            )
            return 1
        print("Journey ledger snapshot is current")
        return 0
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(rendered, encoding="utf-8", newline="\n")
    print(TARGET.relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
