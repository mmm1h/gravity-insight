from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

from gravity_insight.validation_observability import (
    METRIC_NAMES,
    ValidationObservationError,
    append_baseline,
    build_observation,
    read_baselines,
    trend_summary,
    validate_observation,
)
from scripts.validation_observability import run_gate


def task_context() -> dict:
    return {
        "input": {"kind": "changed_files", "values": ["docs/example.md"]},
        "minimal_references": [
            {"path": "docs/current.md", "estimated_tokens": 7},
            {"path": "docs/archive/old.md", "estimated_tokens": 11},
            {"path": "src/gravity_insight/example.py", "estimated_tokens": 13},
        ],
        "size_comparison": {"pack_estimated_tokens": 31},
        "risk_assessment": {"level": "low"},
    }


class ValidationObservabilityTests(unittest.TestCase):
    def test_all_eleven_metrics_are_present_without_inventing_trace_values(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "AGENTS.md").write_text("bootstrap", encoding="utf-8")
            observation = build_observation(
                task_context(),
                root=root,
                token_estimator=lambda value: len(value),
                gate_receipts={
                    "focused": {"status": "passed", "total_seconds": 1.25, "ablated_commands": []},
                    "full": {"status": "passed", "total_seconds": 9.5, "ablated_commands": []},
                },
                revision="abc",
                captured_at="2026-09-01T00:00:00Z",
            )
        self.assertEqual(set(METRIC_NAMES), set(observation["metrics"]))
        self.assertEqual(9, observation["metrics"]["bootstrap_tokens"]["value"])
        self.assertEqual(31, observation["metrics"]["task_context_tokens"]["value"])
        self.assertEqual(11, observation["metrics"]["archive_tokens_loaded"]["value"])
        self.assertEqual(7, observation["metrics"]["active_docs_tokens"]["value"])
        self.assertEqual("unmeasured", observation["metrics"]["review_iterations"]["status"])
        self.assertIn("review-result events", observation["metrics"]["review_iterations"]["missing_source"])
        validate_observation(observation)

    def test_trace_derives_behavior_metrics_from_ordered_events(self) -> None:
        trace = {
            "session_started_at": "2026-09-01T00:00:00Z",
            "events": [
                {"type": "read", "path": "a.py", "at": "2026-09-01T00:00:01Z"},
                {"type": "read", "path": "a.py", "at": "2026-09-01T00:00:02Z"},
                {"type": "read", "path": "b.py", "at": "2026-09-01T00:00:03Z"},
                {"type": "reproduction", "at": "2026-09-01T00:00:04Z"},
                {"type": "edit", "path": "a.py", "at": "2026-09-01T00:00:05Z"},
                {"type": "useful_edit", "path": "a.py", "at": "2026-09-01T00:00:06Z"},
                {"type": "review_result", "at": "2026-09-01T00:00:07Z"},
                {"type": "context_reset", "at": "2026-09-01T00:00:08Z"},
            ],
        }
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "AGENTS.md").write_text("x", encoding="utf-8")
            observation = build_observation(
                task_context(),
                root=root,
                token_estimator=lambda value: len(value),
                trace=trace,
                revision="abc",
                captured_at="2026-09-01T00:00:00Z",
            )
        metrics = observation["metrics"]
        self.assertEqual(2, metrics["files_read_before_first_edit"]["value"])
        self.assertEqual(4.0, metrics["time_to_first_reproduction"]["value"])
        self.assertEqual(6.0, metrics["time_to_first_useful_edit"]["value"])
        self.assertEqual(1, metrics["review_iterations"]["value"])
        self.assertEqual(1, metrics["context_resets"]["value"])

    def test_baseline_archive_is_digest_bound_and_trends_use_revision_medians(self) -> None:
        observations = []
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "AGENTS.md").write_text("x", encoding="utf-8")
            archive = root / "baselines.json"
            for index, value in enumerate((10.0, 20.0, 30.0), start=1):
                observation = build_observation(
                    task_context(),
                    root=root,
                    token_estimator=lambda payload: len(payload),
                    gate_receipts={
                        "focused": {
                            "status": "passed",
                            "total_seconds": value,
                            "ablated_commands": [],
                        }
                    },
                    revision=f"v{index}",
                    captured_at=f"2026-09-0{index}T00:00:00Z",
                )
                observations.append(observation)
                append_baseline(archive, observation)
            document = read_baselines(archive)
        self.assertEqual(3, len(document["observations"]))
        self.assertEqual(
            "sustained_increase",
            trend_summary(observations)["focused_gate_seconds"]["status"],
        )
        mutated = json.loads(json.dumps(observations[0]))
        mutated["metrics"]["focused_gate_seconds"]["value"] = 999
        with self.assertRaises(ValidationObservationError):
            validate_observation(mutated)

    def test_gate_runner_records_real_cost_and_explicit_ablation(self) -> None:
        command = f'& "{sys.executable}" -c "print(123)"'
        with tempfile.TemporaryDirectory() as raw:
            receipt = run_gate("focused", [command], log_dir=Path(raw))
            ablated = run_gate(
                "full",
                [f'& "{sys.executable}" -m unittest discover -s tests'],
                log_dir=Path(raw),
                ablate=["unittest_collector"],
            )
        self.assertEqual("passed", receipt["status"])
        self.assertGreaterEqual(receipt["total_seconds"], 0)
        self.assertEqual(["unittest_collector"], ablated["ablated_commands"])
        self.assertEqual([], ablated["commands"])


if __name__ == "__main__":
    unittest.main()
