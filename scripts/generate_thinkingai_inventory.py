"""Import one frozen metadata observation and compile the CT01 inventory artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gravity_sdk.thinkingai_inventory import (
    build_source_observation,
    compile_inventory_diff,
    compile_inventory_snapshot,
    load_source_observation,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / "src" / "gravity_sdk" / "contracts" / "thinkingai"
CURRENT_OBSERVED_AT = "2026-08-24T10:21:12.565Z"
_STEM = "thinkingai-cn-20260824T102112565Z.v1.json"
OBSERVATION_TARGET = CONTRACT_ROOT / "observations" / _STEM
SNAPSHOT_TARGET = CONTRACT_ROOT / "snapshots" / _STEM
DIFF_TARGET = (
    CONTRACT_ROOT
    / "diffs"
    / "empty-to-thinkingai-cn-20260824T102112565Z.v1.json"
)


def render_outputs(observation: dict[str, Any]) -> dict[Path, str]:
    snapshot = compile_inventory_snapshot(observation)
    difference = compile_inventory_diff(None, snapshot)
    return {
        SNAPSHOT_TARGET: _render(snapshot),
        DIFF_TARGET: _render(difference),
    }


def import_playwright_output(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise SystemExit("Playwright metadata output is unavailable") from exc
    marker = "### Result"
    end_marker = "### Ran Playwright code"
    if marker not in raw or end_marker not in raw:
        raise SystemExit("Playwright metadata output has no bounded result object")
    encoded = raw.split(marker, 1)[1].split(end_marker, 1)[0].strip()
    try:
        value = json.loads(encoded)
    except json.JSONDecodeError as exc:
        raise SystemExit("Playwright metadata result is not JSON") from exc
    observation = build_source_observation(value)
    if observation["observed_at"] != CURRENT_OBSERVED_AT:
        raise SystemExit("Playwright observation time does not match the pinned artifact")
    return observation


def _render(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
        allow_nan=False,
    ) + "\n"


def _write_immutable_observation(observation: dict[str, Any]) -> None:
    rendered = _render(observation)
    if OBSERVATION_TARGET.is_file():
        if OBSERVATION_TARGET.read_text(encoding="utf-8") != rendered:
            raise SystemExit("refusing to rewrite the immutable source observation")
        return
    OBSERVATION_TARGET.parent.mkdir(parents=True, exist_ok=True)
    OBSERVATION_TARGET.write_text(rendered, encoding="utf-8", newline="")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--import-playwright-output", type=Path)
    options = parser.parse_args()
    if options.check and options.import_playwright_output is not None:
        parser.error("--check and --import-playwright-output are mutually exclusive")

    if options.import_playwright_output is not None:
        observation = import_playwright_output(options.import_playwright_output)
        _write_immutable_observation(observation)
    else:
        observation = load_source_observation(OBSERVATION_TARGET)

    outputs = render_outputs(observation)
    mismatched = [
        path
        for path, rendered in outputs.items()
        if not path.is_file() or path.read_text(encoding="utf-8") != rendered
    ]
    if options.check:
        if mismatched:
            raise SystemExit(
                "generated ThinkingAI inventory artifacts do not match the pinned "
                "immutable source observation: "
                + ", ".join(str(path.relative_to(ROOT)) for path in mismatched)
                + ". Run `python scripts/generate_thinkingai_inventory.py` to "
                "rebuild only the derived snapshot and diff. Do not use "
                "`--import-playwright-output` to repair this stale check; that mode "
                "imports a new observation and is a separate review decision."
            )
        print("ThinkingAI inventory artifacts are current")
        return 0

    for path, rendered in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8", newline="")
    print(f"rendered {len(outputs) + 1} ThinkingAI inventory artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
