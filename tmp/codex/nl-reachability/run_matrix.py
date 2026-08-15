from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
PHRASINGS = ROOT / "tmp" / "codex" / "nl-reachability" / "phrasings.md"


def load_questions() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    section = ""
    for line in PHRASINGS.read_text(encoding="utf-8").splitlines():
        if line == "## 32 条已闭环动线":
            section = "closed"
        elif line == "## 15 条完全缺失动线":
            section = "missing"
        if not line.startswith("| J"):
            continue
        fields = [field.strip() for field in line.strip().strip("|").split("|")]
        journey_id, journey, chinese, english = fields
        for language, query in (("中文", chinese), ("English", english)):
            rows.append({
                "id": journey_id,
                "journey": journey,
                "ledger_status": section,
                "language": language,
                "query": query,
            })
    if len(rows) != 94:
        raise RuntimeError(f"expected 94 questions, got {len(rows)}")
    return rows


def run_one(row: dict[str, Any]) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, "-m", "gravity_sdk", "agent", row["query"], "--format", "json"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    result: dict[str, Any] = {**row, "exit_code": completed.returncode}
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        result.update({
            "parse_error": str(error),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        })
        return result
    result.update({
        "status": payload.get("status"),
        "ok": payload.get("ok"),
        "offline": payload.get("offline"),
        "network_called": payload.get("network_called"),
        "candidates": [
            {
                "rank": index,
                "selector": card.get("selector"),
                "kind": card.get("kind"),
                "composite": card.get("composite"),
                "executable": card.get("executable"),
                "plan_executable": card.get("plan_executable"),
                "exact_selector": (
                    card.get("match", {}).get("exact_selector")
                    if isinstance(card.get("match"), dict)
                    else None
                ),
                "period_compare": bool(card.get("period_compare")),
            }
            for index, card in enumerate(payload.get("candidates", []), start=1)
        ],
        "capability_gaps": [
            {
                "code": gap.get("code"),
                "reason": gap.get("reason"),
                "next_action": gap.get("next_action"),
                "candidate_selectors": gap.get("candidate_selectors"),
            }
            for gap in payload.get("capability_gaps", [])
        ],
        "next_action": payload.get("next_action"),
        "stderr": completed.stderr,
    })
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    questions = load_questions()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        results = list(executor.map(run_one, questions))
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    errors = [item for item in results if item.get("exit_code") != 0 or item.get("parse_error")]
    network = [item for item in results if item.get("network_called") is not False]
    print(json.dumps({
        "questions": len(results),
        "errors": len(errors),
        "network_not_false": len(network),
        "output": str(output),
    }, ensure_ascii=False))
    return 1 if errors or network else 0


if __name__ == "__main__":
    raise SystemExit(main())
