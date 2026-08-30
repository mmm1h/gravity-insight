"""CLI registration for the single versioned analysis playbook."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from .find_input import load_json_input
from .result_output import output_file


def add_analysis_playbook_commands(
    analysis_commands: Any,
    add_input: Callable[..., None],
    concurrency_type: Callable[[str], int],
) -> Any:
    playbook = analysis_commands.add_parser(
        "playbook", help="Inspect or run the versioned metric-anomaly investigation."
    )
    actions = playbook.add_subparsers(dest="analysis_playbook_command", required=True)
    schema = actions.add_parser("schema", help="Print the fixed playbook DAG and input contract.")
    schema.set_defaults(network_required=False, _gravity_handler=dispatch_analysis_playbook)
    run = actions.add_parser(
        "run", help="Run or resume metric-anomaly-localization@1 through Plan v1."
    )
    add_input(run, required=True)
    run.add_argument(
        "--checkpoint",
        help="Prior result/checkpoint as inline JSON or a JSON file; only DAG descendants rerun.",
    )
    run.add_argument("--concurrency", type=concurrency_type, default=6)
    run.add_argument(
        "--dry-run", dest="analysis_playbook_dry_run", action="store_true",
        help="Compile the full or resumed Plan and preflight it with zero network calls.",
    )
    run.add_argument(
        "--output", type=output_file,
        help="Atomically write the complete result, including its resumable checkpoint.",
    )
    run.set_defaults(
        network_required=False,
        result_output_fail_closed=True,
        _gravity_handler=dispatch_analysis_playbook,
    )
    return playbook


def dispatch_analysis_playbook(
    args: Any, object_input: Callable[[Any], Mapping[str, Any]],
) -> dict[str, Any]:
    from .analysis_playbook import metric_anomaly_playbook_schema

    if args.analysis_playbook_command == "schema":
        return metric_anomaly_playbook_schema()
    from .sdk import GravitySDK
    from .workspace import load_workspace

    checkpoint = load_json_input(args.checkpoint) if args.checkpoint else None
    if checkpoint is not None and not isinstance(checkpoint, Mapping):
        from .analysis_playbook_input import PLAYBOOK_INPUT_ACTION, playbook_input_error
        from .semantic_compose import actual_value

        raise playbook_input_error(
            "analysis playbook checkpoint must be a JSON object",
            "checkpoint",
            actual_value(type(checkpoint).__name__),
            "gravity.analysis-playbook-checkpoint.v1 object",
            next_action=PLAYBOOK_INPUT_ACTION,
        )
    workspace = load_workspace(getattr(args, "workspace", None))
    return GravitySDK.from_env(workspace=workspace, attempts=1).metric_anomaly_playbook(
        object_input(args.input),
        checkpoint=checkpoint,
        max_workers=args.concurrency,
        dry_run=bool(args.analysis_playbook_dry_run),
    )


__all__ = ["add_analysis_playbook_commands", "dispatch_analysis_playbook"]
