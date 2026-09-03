"""Deferred action DAG and bounded execution estimates for Kanban board plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .kanban_content_mutation import compile_notes


def build_actions(
    decisions: Sequence[Mapping[str, Any]],
    notes: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
    existing: Mapping[str, Any],
) -> list[dict[str, Any]]:
    actions = _target_actions(target) + _saved_actions(decisions)
    actions.extend(_content_actions(actions, decisions, notes, target, existing))
    return [{**item, "index": index} for index, item in enumerate(actions)]


def _target_actions(target: Mapping[str, Any]) -> list[dict[str, Any]]:
    if target["decision"] != "create":
        return []
    return [
        _action(
            "target.create", "dashboard.create", [], input_source="target",
            outputs={"dashboard_id": target_binding()},
        )
    ]


def _saved_actions(
    decisions: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    for item in decisions:
        if item["decision"] not in {"create", "update"}:
            continue
        outputs = (
            {"report_id": saved_binding(item["key"])}
            if item["decision"] == "create" else {}
        )
        result.append(
            _action(
                f"saved.{item['key']}.{item['decision']}",
                f"saved.{item['decision']}",
                [],
                input_source=f"saved_definitions[{item['index']}]",
                outputs=outputs,
            )
        )
    return result


def _content_actions(
    prior: Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    notes: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
    existing: Mapping[str, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    notes_changed = _notes_changed(notes, target, existing)
    if notes_changed and (notes or existing["notes"]):
        result.append(_notes_action(prior, notes, target))
    existing_ids = set(existing["report_ids"])
    link_items = [
        item for item in decisions if item.get("report_id") not in existing_ids
    ]
    if link_items:
        dependencies = _link_dependencies([*prior, *result])
        result.append(_link_action(dependencies, link_items, target))
    return result


def _notes_changed(
    notes: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
    existing: Mapping[str, Any],
) -> bool:
    dashboard_id = target.get("dashboard_id")
    if dashboard_id is None:
        return True
    return list(existing["notes"]) != compile_notes(notes, dashboard_id)


def _notes_action(
    prior: Sequence[Mapping[str, Any]],
    notes: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
) -> dict[str, Any]:
    dependencies = [
        item["step_id"] for item in prior if item["action"] == "dashboard.create"
    ]
    return _action(
        "target.notes.replace", "dashboard.notes.replace", dependencies,
        input_source="notes", literal_inputs={"notes": list(notes)},
        deferred_inputs={"dashboard_id": dashboard_id_value(target)},
    )


def _link_dependencies(actions: Sequence[Mapping[str, Any]]) -> list[str]:
    required = {
        "saved.create", "saved.update", "dashboard.create",
        "dashboard.notes.replace",
    }
    return [item["step_id"] for item in actions if item["action"] in required]


def _link_action(
    dependencies: Sequence[str],
    items: Sequence[Mapping[str, Any]],
    target: Mapping[str, Any],
) -> dict[str, Any]:
    report_ids = [
        item.get("report_id") or item["report_id_binding"] for item in items
    ]
    return _action(
        "target.link", "dashboard.report.link", dependencies,
        input_source="saved_definitions",
        deferred_inputs={
            "dashboard_id": dashboard_id_value(target), "report_ids": report_ids,
        },
    )


def _action(
    step_id: str,
    action: str,
    depends_on: Sequence[str],
    *,
    input_source: str,
    outputs: Mapping[str, Any] | None = None,
    literal_inputs: Mapping[str, Any] | None = None,
    deferred_inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "action": action,
        "depends_on": list(dict.fromkeys(depends_on)),
        "input_source": input_source,
        "literal_inputs": dict(literal_inputs or {}),
        "deferred_inputs": dict(deferred_inputs or {}),
        "outputs": dict(outputs or {}),
        "confirmation_flow": ["dry-run", "human-review", "execute"],
    }


def execution_estimate(
    actions: Sequence[Mapping[str, Any]], *, max_pages: int
) -> dict[str, Any]:
    page_cost = {
        "saved.create": 2 * max_pages + 1,
        "saved.update": 2 * max_pages + 2,
        "dashboard.create": 2,
        "dashboard.report.link": 2 * max_pages + 3,
        "dashboard.notes.replace": 3,
    }
    count = len(actions)
    reads = sum(page_cost[item["action"]] for item in actions)
    return {
        "action_count": count,
        "preview_invocations": count,
        "execute_invocations": count,
        "http_reads_upper_bound": reads,
        "mutation_writes": {
            "planned_from_snapshot": count,
            "minimum": 0,
            "maximum": count,
            "maximum_reason": "each governed execute action sends at most one mutation",
            "minimum_reason": "execution-time idempotent reuse or concurrent convergence can eliminate writes",
        },
    }


def saved_binding(key: str) -> dict[str, str]:
    return {"$ref": f"saved_definitions.{key}.report_id", "type": "report_id"}


def target_binding() -> dict[str, str]:
    return {"$ref": "target.dashboard_id", "type": "positive_integer"}


def dashboard_id_value(target: Mapping[str, Any]) -> Any:
    return target.get("dashboard_id") or target.get("dashboard_id_binding")


__all__ = ["build_actions", "execution_estimate"]
